"""The strategies of the batch, each written from its published rule. Stdlib only.

A strategy is a function (day, bars) -> list of batch.Plan. It may read:
  * anything in `day` (all of it is fixed before the open, see batch.build_days), and
  * bars up to and including the bar named as the plan's `sig`.
verify.py cuts the data off after each decision and scrambles what follows; a strategy that reads
further ahead than its own `sig` fails there.

Clock times are New York. "The price at 10:00" is the close of the bar that ends at 10:00; the
order it triggers is filled at the open of the bar that starts at 10:00. The regular session is
09:30-16:00 and everything is closed at 16:00 (the open of the 16:00 bar).
"""
from __future__ import annotations

from batch import Day, Plan

OPEN, CLOSE = 570, 960
HALF_HOURS = list(range(OPEN, CLOSE, 30))            # 09:30, 10:00, ... 15:30


def sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def seen(bars, day: Day, minute: int):
    """What is known at a clock time: (index, close) of the bar that ends then, or (None, None).
    At 09:30 that is the 09:25 bar, the last one before the regular session."""
    i = day.at.get(minute)
    j = None if i is None else i - 1
    if j is None or j < 0 or bars.mod[j] != (minute - bars.tf) % 1440:
        return None, None                              # the bar that should end here is missing
    return j, bars.c[j]


def window(bars, day: Day, t_in: int, t_out: int, side: int, stop=None, target=None) -> list[Plan]:
    """One trade from clock time t_in to clock time t_out, decided on what was known at t_in."""
    j, _ = seen(bars, day, t_in)
    k, x = day.at.get(t_in), day.at.get(t_out)
    if side == 0 or j is None or k is None or x is None:
        return []
    return [Plan(sig=j, k=k, x=x, side=side, stop=stop, target=target)]


# ----------------------------------------------------------------------------- intraday momentum


def gao(combined: bool = False, need_flag: str | None = None):
    """Gao, Han, Li & Zhou (2018): the first half-hour return, measured from yesterday's close to
    10:00, predicts the last half-hour. Long 15:30-16:00 if it was up, short if down. `combined`
    also needs the 15:00-15:30 return to agree."""
    def f(day: Day, bars):
        if day.prev_close is None or (need_flag and need_flag not in day.flags):
            return []
        _, p10 = seen(bars, day, 600)
        _, p1530 = seen(bars, day, 930)
        if p10 is None or p1530 is None:
            return []
        side = sign(p10 / day.prev_close - 1.0)
        if combined:
            _, p15 = seen(bars, day, 900)
            if p15 is None or sign(p1530 / p15 - 1.0) != side:
                return []
        return window(bars, day, 930, CLOSE, side)
    return f


def rest_of_day(from_open: bool = False):
    """Baltussen, Da, Lammers & Martens (2021): the return up to 15:30 predicts the last half
    hour. Measured from yesterday's close (their r_ROD), or from today's open."""
    def f(day: Day, bars):
        base = day.open if from_open else day.prev_close
        _, p = seen(bars, day, 930)
        if base is None or p is None:
            return []
        return window(bars, day, 930, CLOSE, sign(p / base - 1.0))
    return f


def early_to_close(minute: int, from_open: bool):
    """Intraday time-series momentum held to the close: the sign of the return up to `minute`
    (from yesterday's close or from the open), traded from `minute` to 16:00."""
    def f(day: Day, bars):
        base = day.open if from_open else day.prev_close
        _, p = seen(bars, day, minute)
        if base is None or p is None:
            return []
        return window(bars, day, minute, CLOSE, sign(p / base - 1.0))
    return f


# ----------------------------------------------------------------------------- overnight against intraday


def overnight(direction: int, min_gap: float = 0.0, t_out: int = CLOSE, t_in: int = OPEN):
    """Trade a window of the regular session on the sign of the overnight move (yesterday's 16:00
    to 09:30). direction +1 follows it, -1 fades it. `min_gap` is the smallest gap traded, in
    DATRs. The default window is the whole session; Rosa (2022) and Liu & Tse (2017) follow the
    overnight move in the last half hour, Iwanaga & Sakemoto (2025) fade it in the first."""
    def f(day: Day, bars):
        _, p = seen(bars, day, OPEN)
        if day.prev_close is None or p is None:
            return []
        gap = p - day.prev_close
        if abs(gap) < min_gap * day.datr:
            return []
        return window(bars, day, t_in, t_out, direction * sign(gap))
    return f


def vwap_trend():
    """Zarattini & Aziz (2023), the VWAP paper: long while price is above the session's VWAP,
    short while below, flat at the close. Read on 5-minute closes here: the side is set at each
    bar's close and changed at the next open."""
    def f(day: Day, bars):
        s = day.s
        plans, pos, k0, sig0 = [], 0, None, None
        pv = vol = 0.0
        for i in range(s.first_sig, s.exit_i - 1):
            v = bars.v[i]
            pv += (bars.h[i] + bars.l[i] + bars.c[i]) / 3.0 * v
            vol += v
            if vol <= 0:
                continue
            vw = pv / vol
            want = 1 if bars.c[i] > vw else -1 if bars.c[i] < vw else pos
            if want != pos:
                if pos:
                    plans.append(Plan(sig=sig0, k=k0, x=i + 1, side=pos))
                pos, k0, sig0 = want, i + 1, i
        if pos:
            plans.append(Plan(sig=sig0, k=k0, x=s.exit_i, side=pos))
        return plans
    return f


def big_day(minute: int = 885, threshold: float = 0.02):
    """Shum, Hejazi, Haryanto & Rodier (2012): when the market is up or down 2% on the day by
    14:45, leveraged-ETF rebalancing pushes it the same way into the close. Follow it to 16:00."""
    def f(day: Day, bars):
        _, p = seen(bars, day, minute)
        if day.prev_close is None or p is None:
            return []
        r = p / day.prev_close - 1.0
        return window(bars, day, minute, CLOSE, sign(r)) if abs(r) >= threshold else []
    return f


# ----------------------------------------------------------------------------- breakouts


def orb_first_candle(target_r: float | None = 10.0):
    """Zarattini & Aziz (2023): trade in the direction of the first 5-minute candle from the open
    of the second, stop at the first candle's other end, target 10R, out at the close. R is the
    distance from the fill to the stop price."""
    def f(day: Day, bars):
        i = day.s.first_sig
        k = i + 1
        if bars.mod[k] != OPEN + bars.tf:
            return []
        side = sign(bars.c[i] - bars.o[i])
        if side == 0:
            return []
        return [Plan(sig=i, k=k, x=day.s.exit_i, side=side, stop_px=bars.l[i] if side == 1 else bars.h[i],
                     target_r=target_r)]
    return f


def opening_range(minutes: int, last_entry: int = 900):
    """Opening-range breakout held to the close: the first bar to CLOSE outside the high/low of
    the first `minutes` is followed at the next open, stop at the far side of the range, no target.
    One trade a day, and no entry after `last_entry` (15:00)."""
    def f(day: Day, bars):
        s = day.s
        n = minutes // bars.tf
        first = s.first_sig
        if bars.mod[first + n - 1] != OPEN + minutes - bars.tf:
            return []                                  # a bar of the range is missing
        hi, lo = max(bars.h[first:first + n]), min(bars.l[first:first + n])
        for i in range(first + n, s.exit_i - 1):
            if bars.mod[i] + bars.tf > last_entry:
                break
            c = bars.c[i]
            side = 1 if c > hi else -1 if c < lo else 0
            if side:
                return [Plan(sig=i, k=i + 1, x=s.exit_i, side=side, stop_px=lo if side == 1 else hi)]
        return []
    return f


def noise_area(vwap_stop: bool, lookback: int = 14):
    """Zarattini, Aziz & Barbon (2024), "Beat the Market".
    Noise area at each half-hour mark T: sigma(T) = the mean, over the previous 14 sessions, of
    |price(T) / open - 1|. Upper = max(open, yesterday's close) * (1 + sigma), Lower =
    min(open, yesterday's close) * (1 - sigma). Decisions only on the half-hour, 10:00 to 15:30:
    flat and above Upper -> long, below Lower -> short. Base version: a position is held until
    price is beyond the OPPOSITE boundary, where it reverses. VWAP version: a long is closed when
    price is under max(Upper, VWAP), a short when it is over min(Lower, VWAP). Flat at 16:00."""
    marks = HALF_HOURS[1:]

    def f(day: Day, bars):
        if day.prev_close is None:
            return []
        hist, d = [], day.back                         # the previous 14 kept sessions, gaps or not
        while d is not None and len(hist) < lookback:
            hist.append(d)
            d = d.back
        if len(hist) < lookback:
            return []
        s = day.s
        up0, lo0 = max(day.open, day.prev_close), min(day.open, day.prev_close)
        plans, pos, entry_k, entry_sig = [], 0, None, None
        pv = vol = 0.0
        done = s.first_sig                             # VWAP is accumulated up to the decision bar
        for T in marks:
            j, p = seen(bars, day, T)
            if j is None or any(T not in h.move for h in hist):
                continue
            sig = sum(h.move[T] for h in hist) / lookback
            upper, lower = up0 * (1.0 + sig), lo0 * (1.0 - sig)
            while done <= j:
                v = bars.v[done]
                pv += (bars.h[done] + bars.l[done] + bars.c[done]) / 3.0 * v
                vol += v
                done += 1
            vwap = pv / vol if vol > 0 else p
            want = pos
            if pos == 0:
                want = 1 if p > upper else -1 if p < lower else 0
            elif vwap_stop:
                if pos == 1 and p < max(upper, vwap):
                    want = -1 if p < lower else 0
                elif pos == -1 and p > min(lower, vwap):
                    want = 1 if p > upper else 0
            else:
                if pos == 1 and p < lower:
                    want = -1
                elif pos == -1 and p > upper:
                    want = 1
            if want != pos:
                k = day.at[T]
                if pos != 0:
                    plans.append(Plan(sig=entry_sig, k=entry_k, x=k, side=pos))
                pos, entry_k, entry_sig = want, k, j
        if pos != 0 and entry_k < s.exit_i:
            plans.append(Plan(sig=entry_sig, k=entry_k, x=s.exit_i, side=pos))
        return plans
    return f


# ----------------------------------------------------------------------------- clock and calendar


def clock(t_in: int, t_out: int, side: int, flag: str | None = None):
    """Always the same side over the same clock window, optionally only on days carrying a
    calendar flag. A seasonality, not a signal."""
    def f(day: Day, bars):
        if flag and flag not in day.flags:
            return []
        return window(bars, day, t_in, t_out, side)
    return f


def fomc_after(minutes: int = 30):
    """On FOMC days, follow the move of the first `minutes` after the 14:00 statement to the close."""
    def f(day: Day, bars):
        if "fomc" not in day.flags:
            return []
        _, p0 = seen(bars, day, 840)
        _, p1 = seen(bars, day, 840 + minutes)
        if p0 is None or p1 is None:
            return []
        return window(bars, day, 840 + minutes, CLOSE, sign(p1 / p0 - 1.0))
    return f


# ----------------------------------------------------------------------------- yesterday into today


def after_down_days(n: int = 3):
    """Short-term reversal, daytime part: after `n` lower closes in a row, long 09:30-16:00."""
    def f(day: Day, bars):
        d, closes = day.prev, []
        while d is not None and len(closes) <= n:
            closes.append(bars.o[d.s.exit_i])
            d = d.prev
        if len(closes) <= n or not all(closes[i] < closes[i + 1] for i in range(n)):
            return []
        return window(bars, day, OPEN, CLOSE, 1)
    return f


def yesterday(direction: int):
    """Trade today's regular session on the sign of yesterday's regular-session return."""
    def f(day: Day, bars):
        if day.prev is None:
            return []
        return window(bars, day, OPEN, CLOSE, direction * sign(day.prev.ret))
    return f


def same_half_hour():
    """Heston, Korajczyk & Sadka (2010), index version: each half hour of today takes the side of
    the same half hour yesterday. The whole day's schedule is known before the open. A position is
    held, not closed and reopened, while consecutive half hours call for the same side."""
    def f(day: Day, bars):
        p = day.prev
        if p is None:
            return []
        want = []                                      # the side wanted in each half hour, 0 = flat
        for T in HALF_HOURS:
            _, a = seen(bars, p, T)                    # yesterday's prices at T and T + 30
            _, b = seen(bars, p, T + 30)
            j, _ = seen(bars, day, T)
            ok = None not in (a, b, j, day.at.get(T), day.at.get(T + 30))
            want.append(sign(b / a - 1.0) if ok else 0)
        plans, i = [], 0
        while i < len(want):
            e = i
            while e + 1 < len(want) and want[e + 1] == want[i]:
                e += 1
            if want[i]:
                plans += window(bars, day, HALF_HOURS[i], HALF_HOURS[e] + 30, want[i])
            i = e + 1
        return plans
    return f


def payday():
    """Ma & Pratt: hold the index on the 16th of the month. Daytime part: long 09:30-16:00 on the
    first trading day on or after the 16th."""
    def f(day: Day, bars):
        d = day.date
        if d.day < 16 or d.day > 19:
            return []
        import batch
        k = 16
        while not batch.is_trading_day(d.replace(day=k)):
            k += 1
        return window(bars, day, OPEN, CLOSE, 1) if d.day == k else []
    return f


def fomc_reversal(entry: int = 845):
    """Baglioni & Ribeiro (2025): on FOMC days the market tends to reverse after the statement.
    Fade the move from yesterday's close to 14:00, entering five minutes after the statement and
    holding to the close. (The public summary gives no windows; these are stated in the
    pre-registration as this study's reading.)"""
    def f(day: Day, bars):
        if "fomc" not in day.flags or day.prev_close is None:
            return []
        _, p = seen(bars, day, 840)
        if p is None:
            return []
        return window(bars, day, entry, CLOSE, -sign(p / day.prev_close - 1.0))
    return f


def with_vix(inner, above: bool):
    """Run `inner` only when yesterday's VIX close is above (or below) its own median over the
    previous 252 trading days. The flag is set in batch.build_days."""
    def f(day: Day, bars):
        want = "vix_high" if above else "vix_low"
        return inner(day, bars) if want in day.flags else []
    return f
