"""The batch study's machinery: what is known about each session at the open, how a planned
trade is filled, and the statistics. Stdlib only.

A strategy here is a function (day, bars) -> list of Plan. Each Plan says: decided at the close of
bar `sig`, entered at the open of bar `k`, closed at the open of bar `x` unless a stop or target
(if it has one) is hit first. Everything a strategy reads must be known by the close of `sig`;
verify.py checks that mechanically for every strategy by cutting the data off and by scrambling
the future.

Fills and costs are core.py's (reviewed in ta_setups): market orders pay one tick beyond the bar's
open, stops pay one tick, targets need a tick through and pay none, plus the round-trip commission.
"""
from __future__ import annotations

import bisect
import csv
import math
import random
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from operator import itemgetter
from pathlib import Path

import core
import data

HERE = Path(__file__).resolve().parent
VIX_CSV = HERE / "data" / "vix_fred.csv"
DATR_DAYS, DATR_MIN = 20, 15
NO_STOP = 1e12

# Statement days of scheduled FOMC meetings, from federalreserve.gov (fomchistorical<year>.htm and
# fomccalendars.htm, fetched 2026-10-01). Every one of these statements came out at 14:00 New York
# time: the Board announced the move to 14:00 on 2013-03-13, so the list starts with the March 2013
# meeting (January 2013 was still 14:15). The unscheduled Sunday meeting of 2020-03-15 is not a
# trading day and is left out.
FOMC = {date.fromisoformat(d) for d in """
2013-03-20 2013-05-01 2013-06-19 2013-07-31 2013-09-18 2013-10-30 2013-12-18
2014-01-29 2014-03-19 2014-04-30 2014-06-18 2014-07-30 2014-09-17 2014-10-29 2014-12-17
2015-01-28 2015-03-18 2015-04-29 2015-06-17 2015-07-29 2015-09-17 2015-10-28 2015-12-16
2016-01-27 2016-03-16 2016-04-27 2016-06-15 2016-07-27 2016-09-21 2016-11-02 2016-12-14
2017-02-01 2017-03-15 2017-05-03 2017-06-14 2017-07-26 2017-09-20 2017-11-01 2017-12-13
2018-01-31 2018-03-21 2018-05-02 2018-06-13 2018-08-01 2018-09-26 2018-11-08 2018-12-19
2019-01-30 2019-03-20 2019-05-01 2019-06-19 2019-07-31 2019-09-18 2019-10-30 2019-12-11
2020-01-29 2020-04-29 2020-06-10 2020-07-29 2020-09-16 2020-11-05 2020-12-16
2021-01-27 2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15
2022-01-26 2022-03-16 2022-05-04 2022-06-15 2022-07-27 2022-09-21 2022-11-02 2022-12-14
2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13
2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18
2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10
2026-01-28 2026-03-18 2026-04-29 2026-06-17 2026-07-29 2026-09-16
""".split()}


# ----------------------------------------------------------------------------- the day


@dataclass
class Day:
    s: data.Session
    n: int                         # position among the series' kept sessions
    date: date
    at: dict                       # minute of the New York day -> bar index, 09:30 .. 16:00
    open: float                    # the 09:30 bar's open
    prev: "Day | None" = None      # yesterday's Day, only if yesterday was the previous trading day AND kept
    back: "Day | None" = None      # the previous KEPT session, however long ago (for lookbacks)
    prev_close: float | None = None    # yesterday's 16:00 price
    datr: float | None = None      # mean regular-session range (high - low) of the previous 20 kept sessions
    vix: float | None = None       # VIX close of the previous trading day
    flags: frozenset = frozenset()  # calendar facts, all known before the open (see calendar_flags)
    pre: int | None = None         # the 09:25 bar: the last one to close before the regular session
    first_bar: int = 0             # first bar of this calendar date (00:00 on a weekday): the earliest tradable bar
    rng: float = 0.0               # this session's own high - low; only ever read on LATER days
    ret: float = 0.0               # this session's own 09:30 -> 16:00 return; only read on LATER days
    move: dict = field(default_factory=dict)   # |price / open - 1| at 10:00, 10:30 .. 16:00; LATER days only

    def px(self, bars, minute: int):
        """The price at a clock time: the open of the bar that starts then (None if missing)."""
        i = self.at.get(minute)
        return None if i is None else bars.o[i]

    def bar(self, minute: int):
        """Index of the bar that starts at this clock time (None if missing)."""
        return self.at.get(minute)

    def last_closed(self, minute: int):
        """Index of the bar that CLOSES at this clock time, i.e. the last thing known then."""
        i = self.at.get(minute)
        return None if i is None else i - 1


def easter(y: int) -> date:
    """Gregorian Easter Sunday (the anonymous algorithm)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    return date(y, (h + el - 7 * m + 114) // 31, (h + el - 7 * m + 114) % 31 + 1)


def _nth(y: int, m: int, weekday: int, n: int) -> date:
    """The n-th given weekday of a month; n = -1 is the last."""
    if n > 0:
        d = date(y, m, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(days=7 * (n - 1))
    d = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


SPECIAL_CLOSURES = {date(2012, 10, 29), date(2012, 10, 30), date(2018, 12, 5), date(2025, 1, 9)}


def equity_holidays(y: int) -> set[date]:
    """Days the New York Stock Exchange is closed. The futures file is no guide here: index futures
    trade a short session on most of these days. A holiday on a Sunday is kept on the Monday; one
    on a Saturday is kept on the Friday, except New Year's Day (31 December stays open)."""
    def observed(d: date, saturday_to_friday: bool = True):
        if d.weekday() == 6:
            return d + timedelta(days=1)
        if d.weekday() == 5:
            return d - timedelta(days=1) if saturday_to_friday else None
        return d

    out = {observed(date(y, 1, 1), False), _nth(y, 1, 0, 3), _nth(y, 2, 0, 3), easter(y) - timedelta(days=2),
           _nth(y, 5, 0, -1), observed(date(y, 7, 4)), _nth(y, 9, 0, 1), _nth(y, 11, 3, 4),
           observed(date(y, 12, 25))}
    if y >= 2022:
        out.add(observed(date(y, 6, 19)))
    out.discard(None)
    return out | {d for d in SPECIAL_CLOSURES if d.year == y}


def trading_days(bars) -> list[date]:
    """Every New York Stock Exchange trading day across the span of the file, by rule: weekdays
    that are not holidays. Half days count (they are trading days; the session rules drop them)."""
    first, last = date.fromordinal(bars.t[0] // 1440), date.fromordinal(bars.t[-1] // 1440)
    closed = set()
    for y in range(first.year, last.year + 1):
        closed |= equity_holidays(y)
    out, d = [], first
    while d <= last:
        if d.weekday() < 5 and d not in closed:
            out.append(d)
        d += timedelta(days=1)
    return out


_HOLIDAYS: dict[int, set] = {}


def is_trading_day(d: date) -> bool:
    if d.year not in _HOLIDAYS:
        _HOLIDAYS[d.year] = equity_holidays(d.year)
    return d.weekday() < 5 and d not in _HOLIDAYS[d.year]


def step_trading_day(d: date, direction: int) -> date:
    d += timedelta(days=direction)
    while not is_trading_day(d):
        d += timedelta(days=direction)
    return d


def calendar_flags(days: list[date]) -> dict[date, frozenset]:
    """Calendar facts for each trading day, all known before that day opens.

      dow0..dow4      Monday..Friday
      tom             turn of the month: the last trading day of a month and the first three of the next
      mfirst, mlast   first / last trading day of the month
      opex            monthly option expiration: the third Friday, or the Thursday before it when
                      that Friday is an exchange holiday (Good Friday in 2014, 2019, 2022 and 2025,
                      Juneteenth in 2026)
      opex_week       Monday..Friday of the week holding the third Friday
      pre_holiday     the next weekday is an exchange holiday
      fomc            scheduled FOMC statement day

    Every flag is worked out from the date and the published exchange calendar alone, so it is
    known in advance and does not depend on where a data file happens to start or stop."""
    out = {}
    for d in days:
        f = {f"dow{d.weekday()}"}
        first = step_trading_day(d, -1).month != d.month
        last = step_trading_day(d, 1).month != d.month
        if first:
            f.add("mfirst")
        if last:
            f.add("mlast")
        nth = sum(1 for k in range(1, d.day + 1) if is_trading_day(date(d.year, d.month, k)))
        if last or nth <= 3:
            f.add("tom")
        tf = data.third_friday(d.year, d.month)
        if d == (tf if is_trading_day(tf) else step_trading_day(tf, -1)):
            f.add("opex")
        if tf - timedelta(days=4) <= d <= tf:
            f.add("opex_week")
        nd = d + timedelta(days=1)
        while nd.weekday() >= 5:
            nd += timedelta(days=1)
        if not is_trading_day(nd):
            f.add("pre_holiday")
        if d in FOMC:
            f.add("fomc")
        out[d] = frozenset(f)
    return out


def load_vix() -> dict[date, float]:
    out = {}
    with open(VIX_CSV, newline="") as f:
        rd = csv.reader(f)
        next(rd)
        for d, v in rd:
            try:
                out[date.fromisoformat(d)] = float(v)
            except ValueError:
                pass                                  # FRED writes "." on days with no value
    return out


VIX_WINDOW = 252


def build_days(bars, vix: dict | None = None) -> list[Day]:
    """One Day per kept session, with everything a strategy may know before the open.

    With a VIX history each day also carries "vix_high" or "vix_low": yesterday's VIX close against
    the median of the 252 closes up to and including yesterday."""
    cal = trading_days(bars)
    cal_idx = {d: i for i, d in enumerate(cal)}
    flags = calendar_flags(cal)
    vix_dates = sorted(vix) if vix else []
    vix_vals = [vix[d] for d in vix_dates]
    days: list[Day] = []
    by_date: dict[date, Day] = {}
    for n, s in enumerate(bars.sessions):
        at = {bars.mod[i]: i for i in range(s.first_sig, s.exit_i + 1)}
        fl = set(flags.get(s.day, frozenset()))
        if vix_dates:
            j = bisect.bisect_left(vix_dates, s.day)           # closes strictly before today
            if j >= VIX_WINDOW:
                med = statistics.median(vix_vals[j - VIX_WINDOW:j])
                fl.add("vix_high" if vix_vals[j - 1] > med else "vix_low")
        d = Day(s=s, n=n, date=s.day, at=at, open=bars.o[s.first_sig], flags=frozenset(fl),
                back=days[-1] if days else None)
        d.rng = max(bars.h[s.first_sig:s.exit_i]) - min(bars.l[s.first_sig:s.exit_i])
        d.ret = bars.o[s.exit_i] / d.open - 1.0
        # the price at a half-hour mark is the close of the bar ending there, as everywhere else
        d.move = {m: abs(bars.c[i - 1] / d.open - 1.0) for m, i in at.items()
                  if m % 30 == 0 and m > data.RTH_OPEN and bars.mod[i - 1] == m - bars.tf}
        p0 = s.first_sig - 1
        if p0 >= 0 and bars.mod[p0] == data.RTH_OPEN - bars.tf and bars.t[p0] // 1440 == s.ordinal:
            d.pre = p0
        # the hours of the same date before 09:30 belong to the same exchange session (it opened at
        # 18:00 the evening before), so a trade inside them is still flat by this day's close
        j = s.first_sig
        while j > 0 and bars.t[j - 1] // 1440 == s.ordinal:
            j -= 1
            at[bars.mod[j]] = j
        d.first_bar = j
        ci = cal_idx.get(s.day)
        if ci is not None and ci > 0:
            y = cal[ci - 1]
            if vix is not None:
                d.vix = vix.get(y)
            p = by_date.get(y)
            if p is not None:                          # yesterday was the previous trading day and was kept
                d.prev = p
                d.prev_close = bars.o[p.s.exit_i]
        past = days[-DATR_DAYS:]
        if len(past) >= DATR_MIN:
            d.datr = sum(x.rng for x in past) / len(past)
        days.append(d)
        by_date[s.day] = d
    return days


# ----------------------------------------------------------------------------- plans and fills


@dataclass(frozen=True)
class Plan:
    sig: int                       # the bar whose close the decision was made on
    k: int                         # entry bar: filled at its open
    x: int                         # time exit: closed at this bar's open
    side: int
    stop: float | None = None      # stop distance in points from the fill ...
    target: float | None = None    # target distance in points from the fill ...
    stop_px: float | None = None   # ... or a stop PRICE, fixed at the decision. The distance is then
                                   #     whatever the fill leaves, so a strategy never reads its own fill
    target_r: float | None = None  # ... or a target as a multiple of the stop distance


@dataclass
class Trade:
    day: int
    k: int
    x: int
    side: int
    pts: float                     # net points per contract
    gross: float                   # points before commission and slippage
    twin: float                    # the same fill taken the other way, gross points
    why: str
    unit: float                    # the day's DATR: what a point was worth that day


def execute(bars, day: Day, plan: Plan) -> Trade:
    tick, comm = bars.tick, bars.commission_pts
    if not (plan.sig < plan.k < plan.x <= day.s.exit_i and plan.k >= day.first_bar):
        raise ValueError(f"plan out of order: sig {plan.sig}, entry {plan.k}, exit {plan.x}")
    if (plan.stop is not None and plan.stop_px is not None) or (plan.target is not None and plan.target_r is not None):
        raise ValueError("a plan gives a stop (or a target) one way, not both")
    px = bars.o[plan.k]
    if plan.stop_px is not None:
        # A stop at a price. If the fill is already at or beyond it, the stop is hit at once: in and
        # out at the same open by market order, which costs a tick each way and the commission.
        stop = core.round_up((px + plan.side * tick - plan.stop_px) * plan.side, tick)
        if stop <= 0.0:
            return Trade(day=day.s.ordinal, k=plan.k, x=plan.k, side=plan.side, pts=-2 * tick - comm,
                         gross=0.0, twin=0.0, why="stop", unit=day.datr or math.nan)
    else:
        stop = NO_STOP if plan.stop is None else core.round_up(plan.stop, tick)
    tgt = None if plan.target is None else core.round_up(plan.target, tick)
    if plan.target_r is not None:
        if stop >= NO_STOP:
            raise ValueError("a target in multiples of the stop needs a stop")
        tgt = core.round_up(plan.target_r * stop, tick)
    pts, why, x, _, _, xslip = core.run_exit(bars, plan.k, plan.x, plan.side, px + plan.side * tick, stop, tgt)
    o_pts, *_ = core.run_exit(bars, plan.k, plan.x, -plan.side, px - plan.side * tick, stop, tgt, both="target")
    return Trade(day=day.s.ordinal, k=plan.k, x=x, side=plan.side, pts=pts - xslip * tick - comm,
                 gross=pts + tick, twin=o_pts + tick, why=why, unit=day.datr or math.nan)


def run(bars, days: list[Day], strategy) -> list[Trade]:
    """Every plan the strategy makes, filled. A day without a DATR (the first weeks of a series)
    is skipped so that every trade can be put on the same scale."""
    out = []
    for d in days:
        if d.datr is None:
            continue
        for plan in strategy(d, bars):
            out.append(execute(bars, d, plan))
    return out


# ----------------------------------------------------------------------------- statistics


def daily(trades: list[Trade], days: list[Day], value) -> list[float]:
    """One number per session (zero on a day with no trade), in session order. Only sessions with a
    DATR count, the same ones `run` trades."""
    tot: dict[int, float] = {}
    for t in trades:
        tot[t.day] = tot.get(t.day, 0.0) + value(t)
    return [tot.get(d.s.ordinal, 0.0) for d in days if d.datr is not None]


def tstat(xs: list[float]) -> dict:
    n = len(xs)
    if n < 2:
        return {"n": n, "mean": math.nan, "sd": math.nan, "t": math.nan, "sharpe": math.nan}
    m = sum(xs) / n
    sd = statistics.stdev(xs)
    t = m / (sd / math.sqrt(n)) if sd > 0 else math.nan
    return {"n": n, "mean": m, "sd": sd, "t": t, "sharpe": m / sd * math.sqrt(252) if sd > 0 else math.nan}


def reality_check(series: dict[str, list[float]], runs: int, rng: random.Random) -> dict:
    """White's reality check on daily series that share one calendar, with each draw's own
    t-statistic (the studentized bootstrap).

    Null: no strategy has a positive mean. Days are drawn with replacement, the SAME days for every
    strategy so that their correlation survives. Each series is centred on the mean of the days it
    traded (a day without a trade stays zero), and in every draw each strategy gets the t-statistic
    of its own resampled days: their mean over their standard error, both taken from the draw. The
    best t of the draw is kept. A strategy's corrected p is the share of draws whose best t is at
    least its own.
    -> {"best": sorted best-of-draw t values, "p": {name: corrected p}, "t": {name: t}}

    Why the draw's own standard error: for a strategy that trades a few dozen days and loses big on
    a few of them, the mean and the spread move together, and dividing every draw by the
    full-sample spread makes the corrected p too small.
    Why only the traded days are centred: shifting the idle days as well turns a rarely-traded
    loser into a series that is a little positive on most days and very negative on a few. A draw
    that happens to miss those few days then has a huge t, and one such strategy raises the bar
    for all the others. verify.py [6] measures both points."""
    names = list(series)
    n = len(next(iter(series.values())))
    stats_ = {k: tstat(v) for k, v in series.items()}
    cols = []
    for k in names:
        s = stats_[k]
        if s["sd"] and s["sd"] > 0:
            live = [x for x in series[k] if x != 0.0]
            m = sum(live) / len(live)
            c = [x - m if x != 0.0 else 0.0 for x in series[k]]
            cols.append((c, [x * x for x in c]))
    best = []
    for _ in range(runs):
        pick = itemgetter(*[rng.randrange(n) for _ in range(n)])
        top = -math.inf
        for c, c2 in cols:
            s1, s2 = sum(pick(c)), sum(pick(c2))
            var = (s2 - s1 * s1 / n) / (n - 1)
            if var > 1e-12 * s2 / n:                    # a draw with no spread at all has no t
                t = s1 / math.sqrt(var * n)             # = (s1 / n) / sqrt(var / n)
                if t > top:
                    top = t
        best.append(top)
    best.sort()
    p = {}
    for k in names:
        t = stats_[k]["t"]
        p[k] = 1.0 if t != t else (1 + sum(1 for b in best if b >= t)) / (1 + runs)
    return {"best": best, "p": p, "t": {k: stats_[k]["t"] for k in names}}


Z_STILL_THERE = core.inv_norm(0.95)      # route 3: one-sided 5% on set A, uncorrected


def decide(now: dict[str, list[float]], before: dict[str, list[float]], runs: int, rng: random.Random,
           a_now: float = 0.05, a_before: float = 0.10, a_all: float = 0.05) -> dict:
    """The three routes of PREREGISTRATION.md, on daily series keyed by strategy. `now` is set A
    (NQ 2021-2026), `before` the pooled data before 2021; the whole sample is one after the other.

      route 1  corrected p <= a_now on `now`
      route 2  corrected p <= a_before on `before`, then on `now` a positive mean with t at or
               above the one-sided 5% point shared across the candidates (Bonferroni)
      route 3  corrected p <= a_all on the whole sample, a positive mean before, and on `now` a t
               at or above the one-sided 5% point (1.645). Without that last test a strategy whose
               edge died after 2020 would pass on its history alone about half the time.

    One function on purpose: verify.py measures the false-alarm rate and the power of exactly what
    run_batch.py applies."""
    whole = {k: before[k] + now[k] for k in now}
    rc_now = reality_check(now, runs, rng)
    rc_before = reality_check(before, runs, rng)
    rc_all = reality_check(whole, runs, rng)
    up = lambda s, k: sum(s[k]) > 0
    route1 = [k for k in now if up(now, k) and rc_now["p"][k] <= a_now]
    cand2 = [k for k in now if up(before, k) and rc_before["p"][k] <= a_before]
    z2 = core.inv_norm(1.0 - 0.05 / len(cand2)) if cand2 else math.nan
    route2 = [k for k in cand2 if up(now, k) and rc_now["t"][k] >= z2]
    cand3 = [k for k in now if up(before, k) and rc_all["p"][k] <= a_all]
    route3 = [k for k in cand3 if rc_now["t"][k] >= Z_STILL_THERE]
    passed = [k for k in now if k in route1 or k in route2 or k in route3]
    return {"now": rc_now, "before": rc_before, "all": rc_all, "route1": route1, "cand2": cand2, "z2": z2,
            "route2": route2, "cand3": cand3, "route3": route3, "passed": passed}


def drawdown(xs: list[float]) -> float:
    eq = peak = dd = 0.0
    for x in xs:
        eq += x
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return dd


def account_fit(dollars: list[float], dates: list[date], limit: float = 2000.0, lock: float = 100.0,
                horizons=(60, 120, 250)) -> dict:
    """A fresh account with an end-of-day trailing loss limit, opened on the first session of every
    month (a series that begins mid-month opens its first account at the next month). The limit
    trails the closing high by `limit` and stops rising once it reaches +`lock` (Lucid 50K: $2,000,
    locking at +$100). -> for each horizon, the share of accounts that hit the limit inside it and
    the median result (a busted account counts as -limit). The accounts overlap: sixty-odd monthly
    starts over five years hold only about ten separate 120-session stretches, so the share
    describes this history; it is not a probability with a tight error bar."""
    starts = [i for i, d in enumerate(dates) if i > 0 and d.month != dates[i - 1].month]
    out = {}
    for hz in horizons:
        bust, ends = 0, []
        for i0 in starts:
            if i0 + hz > len(dollars):
                continue
            bal = hwm = 0.0
            dead = False
            for x in dollars[i0:i0 + hz]:
                bal += x
                if bal <= min(hwm, limit + lock) - limit:
                    dead = True
                    break
                hwm = max(hwm, bal)
            bust += dead
            ends.append(-limit if dead else bal)
        if ends:
            out[hz] = {"n": len(ends), "bust": bust / len(ends), "median": statistics.median(ends)}
    return out
