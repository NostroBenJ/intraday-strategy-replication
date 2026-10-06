"""Indicators, the four setups, the fill simulator and the statistics. Stdlib only.

Everything here works on plain column lists (o, h, l, c), so it runs on any bar series. Nothing in
this file reads a file or knows a symbol: `data.py` builds the series and `verify.py` checks every
piece against a closed form or a hand-built case before a real bar is scored.

Conventions
  * Bar i is known at its close. A setup may read bars <= i and nothing later; the order it raises
    can only fill in bar i+1 or later. verify.py [5] proves this by truncation and by perturbing
    the future.
  * Prices are points. R is points won or lost divided by the stop distance in points, the stop
    distance being entry fill to stop price. `g` is gross R (no commission, no slippage), `r` is
    net R. Never one without the other.
  * A bar that holds both the stop and the target books the stop. A limit order (a target, or a
    limit entry) needs price to trade THROUGH it by a tick; a touch is not a fill.
  * Every trade is also walked the other way from the same fill (its coin-flip twin). Wherever a
    bar leaves the order of events open, the real trade gets the losing reading and the twin the
    winning one, so the doubt can only make a setup look worse than it is.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from itertools import compress

# ----------------------------------------------------------------------------- indicators


def ema(x: list[float], n: int) -> list[float]:
    """Exponential moving average, alpha = 2/(n+1), seeded with the first value."""
    a = 2.0 / (n + 1.0)
    out = [0.0] * len(x)
    if not x:
        return out
    prev = x[0]
    out[0] = prev
    for i in range(1, len(x)):
        prev += a * (x[i] - prev)
        out[i] = prev
    return out


def tema(x: list[float], n: int) -> list[float]:
    """Mulloy's triple exponential moving average: 3*E1 - 3*E2 + E3, each an EMA(n) of the one
    before. Zero lag on a straight line (verify.py [1])."""
    e1 = ema(x, n)
    e2 = ema(e1, n)
    e3 = ema(e2, n)
    return [3.0 * a - 3.0 * b + c for a, b, c in zip(e1, e2, e3)]


def wma(x: list[float], n: int) -> list[float]:
    """Linearly weighted moving average, weights 1..n with n on the newest bar. The first n-1
    values use the bars that exist (weights 1..k), so the output has no holes."""
    out = [0.0] * len(x)
    num = 0.0          # sum of weight * value over the window
    tot = 0.0          # plain sum over the window
    for i, v in enumerate(x):
        if i < n:
            num += (i + 1) * v
            tot += v
            out[i] = num / ((i + 1) * (i + 2) / 2.0)
        else:
            num += n * v - tot          # every weight drops by one; the new bar enters at n
            tot += v - x[i - n]
            out[i] = num / (n * (n + 1) / 2.0)
    return out


def hma(x: list[float], n: int) -> list[float]:
    """Hull moving average: WMA(2*WMA(n/2) - WMA(n), sqrt(n)), integer parts as Hull defines it."""
    half = wma(x, max(1, n // 2))
    full = wma(x, n)
    raw = [2.0 * a - b for a, b in zip(half, full)]
    return wma(raw, max(1, int(math.sqrt(n))))


def true_range(h: list[float], l: list[float], c: list[float]) -> list[float]:
    out = [0.0] * len(h)
    for i in range(len(h)):
        if i == 0:
            out[i] = h[i] - l[i]
        else:
            pc = c[i - 1]
            out[i] = max(h[i] - l[i], abs(h[i] - pc), abs(l[i] - pc))
    return out


def wilder(x: list[float], n: int) -> list[float]:
    """Wilder smoothing: the running mean for the first n values, then prev + (x - prev)/n."""
    out = [0.0] * len(x)
    s = 0.0
    prev = 0.0
    for i, v in enumerate(x):
        if i < n:
            s += v
            prev = s / (i + 1)
        else:
            prev += (v - prev) / n
        out[i] = prev
    return out


def atr(h: list[float], l: list[float], c: list[float], n: int = 14) -> list[float]:
    """Average true range, Wilder smoothing. Gap-aware: the true range uses the prior close."""
    return wilder(true_range(h, l, c), n)


def adx(h: list[float], l: list[float], c: list[float], n: int = 14):
    """Wilder's ADX. -> (adx, plus_di, minus_di)."""
    m = len(h)
    pdm = [0.0] * m
    mdm = [0.0] * m
    for i in range(1, m):
        up = h[i] - h[i - 1]
        dn = l[i - 1] - l[i]
        if up > dn and up > 0:
            pdm[i] = up
        if dn > up and dn > 0:
            mdm[i] = dn
    tr_s = wilder(true_range(h, l, c), n)
    p_s = wilder(pdm, n)
    m_s = wilder(mdm, n)
    pdi = [0.0] * m
    mdi = [0.0] * m
    dx = [0.0] * m
    for i in range(m):
        if tr_s[i] > 0:
            pdi[i] = 100.0 * p_s[i] / tr_s[i]
            mdi[i] = 100.0 * m_s[i] / tr_s[i]
        tot = pdi[i] + mdi[i]
        dx[i] = 100.0 * abs(pdi[i] - mdi[i]) / tot if tot > 0 else 0.0
    return wilder(dx, n), pdi, mdi


MOVING_AVERAGES = {"ema": ema, "tema": tema, "hma": hma, "wma": wma}


# ----------------------------------------------------------------------------- setups
#
# A setup is a function (i, params, ind, bars) -> None or an Order, called at the close of bar i.
# `ind` holds the indicator columns the variant asked for (data.build_indicators). Every setup is
# symmetric: the short rule is the long rule on mirrored prices (verify.py [6]).


@dataclass(frozen=True)
class Order:
    side: int                         # +1 long, -1 short
    entry: str                        # "market" (next bar's open), "stop" or "limit" at `level`
    level: float = 0.0                # trigger price for stop / limit entries
    valid: int = 1                    # bars a pending stop / limit order stays alive
    stop_px: float | None = None      # structural stop price (pattern setups) ...
    stop_atr: float | None = None     # ... or a multiple of the signal bar's ATR, from the fill
    cancel_px: float | None = None    # a pending order dies if price trades here first


def line_order(vals: list[float]) -> int:
    """+1 if strictly descending (fastest line on top), -1 if strictly ascending, else 0."""
    if all(a > b for a, b in zip(vals, vals[1:])):
        return 1
    if all(a < b for a, b in zip(vals, vals[1:])):
        return -1
    return 0


def slope_state(lines, i: int) -> int:
    """+1 if every line rose from bar i-1 to bar i, -1 if every line fell, else 0."""
    if all(ln[i] > ln[i - 1] for ln in lines):
        return 1
    if all(ln[i] < ln[i - 1] for ln in lines):
        return -1
    return 0


def setup_ribbon_align(i: int, p: dict, ind: dict, bars) -> Order | None:
    """The ribbon BECOMES fully aligned on this bar: every line in strict order, fastest on top
    for a long, and it was not aligned that way on the bar before."""
    if i < 1:
        return None
    lines = ind["ribbon"]
    now = line_order([ln[i] for ln in lines])
    if now == 0 or line_order([ln[i - 1] for ln in lines]) == now:
        return None
    return Order(now, "market", stop_atr=p["stop_atr"])


def setup_slope_turn(i: int, p: dict, ind: dict, bars) -> Order | None:
    """Every line in the set is rising on this bar and that was not so on the bar before (long);
    mirrored for a short. With a single line this is the plain slope turn of that average.
    `true_turn` = N additionally demands the whole set was pointing the other way at some bar in
    the previous N."""
    if i < 2:
        return None
    lines = ind["ribbon"]
    now = slope_state(lines, i)
    if now == 0 or slope_state(lines, i - 1) == now:
        return None
    look = p.get("true_turn", 0)
    if look and not any(slope_state(lines, j) == -now for j in range(max(1, i - look), i)):
        return None
    return Order(now, "market", stop_atr=p["stop_atr"])


def setup_pin_bar(i: int, p: dict, ind: dict, bars) -> Order | None:
    """Fuller's pin bar. Long: the lower tail is at least `tail` of the bar's range (so open and
    close both sit in the top 1 - tail of it), the low is below the low of each of the previous
    `protrude` bars, and the range is at least `min_range_atr` ATRs. Stop one tick beyond the tail.
    Entry: at the next open ("market"), on a stop one tick beyond the other end of the bar
    ("stop"), or on a limit halfway back into the bar ("limit")."""
    n = p["protrude"]
    if i < n:
        return None
    o, h, l, c = bars.o[i], bars.h[i], bars.l[i], bars.c[i]
    rng = h - l
    if rng <= 0 or rng < p["min_range_atr"] * ind["atr"][i]:
        return None
    body_lo, body_hi = (o, c) if o <= c else (c, o)
    need = p["tail"] * rng - 1e-9               # a tail of exactly the fraction qualifies
    side = 0
    if body_lo - l >= need:
        if n == 0 or l < min(bars.l[i - n:i]):
            side = 1
    elif h - body_hi >= need:
        if n == 0 or h > max(bars.h[i - n:i]):
            side = -1
    if side == 0:
        return None
    tick = bars.tick
    stop_px = l - tick if side == 1 else h + tick
    mode = p.get("entry", "market")
    if mode == "market":
        return Order(side, "market", stop_px=stop_px)
    if mode == "stop":
        level = h + tick if side == 1 else l - tick
        return Order(side, "stop", level=level, valid=p.get("valid", 2), stop_px=stop_px,
                     cancel_px=stop_px)
    # halfway back into the bar, rounded to the tick on the tail's side (the harder fill)
    if side == 1:
        level = math.floor((l + 0.5 * rng) / tick + 1e-9) * tick
    else:
        level = math.ceil((h - 0.5 * rng) / tick - 1e-9) * tick
    return Order(side, "limit", level=level, valid=p.get("valid", 3), stop_px=stop_px)


def setup_ema_pullback(i: int, p: dict, ind: dict, bars) -> Order | None:
    """Pullback to a moving average inside a trend, continuation entry.

    Trend: `trend` = "ema" needs, at bar i, the fast EMA above the slow EMA and the slow EMA higher
    than it was `rising` bars ago. `trend` = "adx" is Raschke's: ADX above `adx_min` AND rising
    marks the trend, and the retracement comes afterwards ("usually accompanied by a turndown in
    the ADX"), so the test is whether ADX was above the floor and rising on some bar in the last
    `armed` bars; the side is +DI against -DI on the most recent such bar.
    Pullback: this bar's low reaches the pullback average (low <= average) and the previous `away`
    bars all stayed clear of it (low above). With `close_holds` the bar must also close back above
    the average. Entry: a buy stop one tick above this bar's high, alive for `valid` bars and
    cancelled if the bar's low gives way first; or, with `entry` = "market", the next open, which
    also needs the close in the upper half of the bar. Stop one tick under this bar's low. Shorts
    are the mirror image."""
    away = p["away"]
    if i < max(away, p.get("rising", 0), p.get("armed", 0), 1):
        return None
    side = 0
    if p["trend"] == "adx":
        a, floor = ind["adx"], p["adx_min"]
        for j in range(i, i - p["armed"], -1):
            if a[j] > floor and a[j] > a[j - 1]:
                pdi, mdi = ind["pdi"][j], ind["mdi"][j]
                side = 1 if pdi > mdi else -1 if pdi < mdi else 0
                break
    else:
        fast, slow, k = ind["fast"], ind["slow"], p["rising"]
        if fast[i] > slow[i] and slow[i] > slow[i - k]:
            side = 1
        elif fast[i] < slow[i] and slow[i] < slow[i - k]:
            side = -1
    if side == 0:
        return None
    touch = ind["touch"]
    h, l, c = bars.h[i], bars.l[i], bars.c[i]
    e = touch[i]
    tick = bars.tick
    hold = p.get("close_holds", False)
    market = p.get("entry", "stop") == "market"
    if side == 1:
        if l > e or ((hold or market) and c <= e):
            return None
        if any(bars.l[j] <= touch[j] for j in range(i - away, i)):
            return None
        stop_px, level = l - tick, h + tick
    else:
        if h < e or ((hold or market) and c >= e):
            return None
        if any(bars.h[j] >= touch[j] for j in range(i - away, i)):
            return None
        stop_px, level = h + tick, l - tick
    if market:
        mid = 0.5 * (h + l)
        if (side == 1 and c < mid) or (side == -1 and c > mid):
            return None
        return Order(side, "market", stop_px=stop_px)
    return Order(side, "stop", level=level, valid=p.get("valid", 3), stop_px=stop_px,
                 cancel_px=stop_px)


SETUPS = {
    "ribbon_align": setup_ribbon_align,
    "slope_turn": setup_slope_turn,
    "pin_bar": setup_pin_bar,
    "ema_pullback": setup_ema_pullback,
}


def trend_ok(i: int, side: int, mode: str | None, ind: dict, bars, look: int = 12) -> bool:
    """Optional filter for the search grid. "with": longs only above a rising trend EMA, shorts
    only below a falling one. "against": the reverse."""
    if not mode:
        return True
    e = ind["trend_ema"]
    if i < look:
        return False
    up = bars.c[i] > e[i] and e[i] > e[i - look]
    dn = bars.c[i] < e[i] and e[i] < e[i - look]
    want = side if mode == "with" else -side
    return up if want == 1 else dn


# ----------------------------------------------------------------------------- simulator


@dataclass
class Trade:
    day: int                  # session ordinal: the cluster id
    sig: int                  # signal bar index
    k: int                    # entry bar index
    side: int
    entry: float              # fill price
    stop_dist: float
    r: float                  # net R
    g: float                  # gross R
    r_other: float            # the same fill taken the other way, net R
    g_other: float
    why: str                  # "target" | "stop" | "time" | "flag"
    exit_i: int
    ambiguous: bool           # the exit bar held both stop and target
    pts: float                # net points per contract
    mae: float                # worst open loss in points
    minute: int               # minute of day (ET) of the entry bar


def round_up(x: float, tick: float) -> float:
    return math.ceil(x / tick - 1e-9) * tick


def first_touch(bars, j: int, side: int, level: float, cancel: float) -> str:
    """Bar j traded at both a pending stop order's trigger and its cancel price. Which came first?
    -> "trigger" | "cancel".

    Where the series carries 1-minute bars (`bars.fine`), walk them in order: the first minute
    that reaches one and not the other settles it. Where it does not, or a single minute reaches
    both, use the side the bar opened nearer to (a tie reads as the trigger, the losing reading).
    Every decision is tallied in bars.cache["touch"] so the run can report how often the opening
    rule agrees with the 1-minute answer."""
    tally = bars.cache.setdefault("touch", {"both": 0, "by_minute": 0, "rule_agrees": 0})
    tally["both"] += 1
    o = bars.o[j]
    rule = "trigger" if abs(o - level) <= abs(o - cancel) else "cancel"
    fine = getattr(bars, "fine", None)
    if fine is not None:
        fs, fo, fh, fl = fine
        for q in range(fs[j], fs[j + 1]):
            hit_t = (fh[q] >= level) if side == 1 else (fl[q] <= level)
            hit_c = (fl[q] <= cancel) if side == 1 else (fh[q] >= cancel)
            if hit_t and hit_c:
                return "trigger" if abs(fo[q] - level) <= abs(fo[q] - cancel) else "cancel"
            if hit_t or hit_c:
                ans = "trigger" if hit_t else "cancel"
                tally["by_minute"] += 1
                tally["rule_agrees"] += ans == rule
                return ans
    return rule


def fill_entry(bars, i: int, order: Order, last_entry: int):
    """Fill an order raised at the close of bar i.
    -> ("fill", bar index, the market's price at that instant, points the order paid beyond it,
        filled at the bar's open?)   or   ("dead", bar index it died on).

    market  next bar's open; the order pays one tick beyond it
    stop    once price trades at its level, or at the open if the bar opens through it; the order
            pays one tick beyond that price. It dies if the bar opens beyond `cancel_px`, or trades
            there without reaching the level. A bar that reaches both is settled by `first_touch`.
    limit   filled at its own price, with no price improvement, once price has traded THROUGH it
            by a tick (a bar that opens beyond it counts). At that instant the market is a tick or
            more beyond the limit, so the order has paid at least a tick relative to the market:
            that is what resting orders cost, and it is counted as slippage like any other.

    Gross R and the coin-flip twin are both measured from the market's price at the instant of
    the fill, whatever the order type. The twin is a market order the other way at that instant."""
    side = order.side
    if order.entry == "market":
        k = i + 1
        return ("fill", k, bars.o[k], bars.tick, True) if k <= last_entry else ("dead", i)
    end = min(i + order.valid, last_entry)
    for j in range(i + 1, end + 1):
        o, h, l = bars.o[j], bars.h[j], bars.l[j]
        if order.entry == "stop":
            can = order.cancel_px
            if (o - order.level) * side >= 0:
                return "fill", j, o, bars.tick, True
            if can is not None and (o - can) * side <= 0:
                return "dead", j
            hit_t = (h >= order.level) if side == 1 else (l <= order.level)
            hit_c = can is not None and ((l <= can) if side == 1 else (h >= can))
            if hit_t and hit_c and first_touch(bars, j, side, order.level, can) == "cancel":
                return "dead", j
            if hit_t:
                return "fill", j, order.level, bars.tick, False
            if hit_c:
                return "dead", j
        else:
            if (o - order.level) * side < -1e-9:
                return "fill", j, o, (order.level - o) * side, True
            if (l < order.level - 1e-9) if side == 1 else (h > order.level + 1e-9):
                return "fill", j, order.level - side * bars.tick, bars.tick, False
    return "dead", max(end, i)


def post_fill_range(bars, k: int, order: Order, at_open: bool):
    """The low and the high the entry bar is taken to have printed AFTER the fill. The real trade
    and its coin-flip twin are both walked against this one range, so whatever is assumed about the
    part of the bar nobody can see is assumed for both. None means the whole bar.

    A fill at the bar's open (every market order; a stop or limit the bar opened beyond) has the
    whole bar after it. Otherwise only one side of the bar is certain to follow the fill: the side
    a stop entry was heading for, or the side a limit entry fell through. The uncertain side is
    read the way that can only hurt the real trade and help the twin:

      stop entry   with 1-minute bars, the range from the fill minute to the end of the bar (the
                   fill minute's own low may have printed before the trigger and is still counted);
                   without them, the whole bar
      limit entry  with 1-minute bars, the certain side from the fill minute on, and for the other
                   side the minutes AFTER the fill minute plus the bar's close; without them, the
                   certain side and the close. The close is certain to come after the fill."""
    if order.entry == "market" or at_open:
        return None
    side, lvl = order.side, order.level
    fine = getattr(bars, "fine", None)
    q0 = q1 = 0
    if fine is not None:
        fs, _, fh, fl = fine
        q0, q1 = fs[k], fs[k + 1]
    if order.entry == "stop":
        for q in range(q0, q1):
            if (fh[q] >= lvl) if side == 1 else (fl[q] <= lvl):
                return min(fl[q:q1]), max(fh[q:q1])
        return None
    c = bars.c[k]
    px = lvl - side * bars.tick                 # where the market was when the limit filled
    for q in range(q0, q1):
        if (fl[q] < lvl - 1e-9) if side == 1 else (fh[q] > lvl + 1e-9):
            if side == 1:
                return min(fl[q:q1]), max([px, c] + fh[q + 1:q1])
            return min([px, c] + fl[q + 1:q1]), max(fh[q:q1])
    return (bars.l[k], max(px, c)) if side == 1 else (min(px, c), bars.h[k])


def run_exit(bars, k: int, last: int, side: int, entry: float, stop_dist: float,
             tgt_dist: float | None, entry_range=None, state=None, flag: str | None = None,
             flag_side: int | None = None, both: str = "stop"):
    """Walk a position from entry bar k. `last` is the time-exit bar: the position is closed at
    that bar's open. -> (points from `entry`, why, exit bar, ambiguous, worst open loss, exit
    slippage ticks). The caller charges slippage and commission.

    The stop fills at its price, or at the open when a later bar opens beyond it. The target is a
    limit: it needs price a tick through it. A bar that holds both is ambiguous, and `both` says
    how it is booked: "stop" for the real trade, "target" for its coin-flip twin, so the doubt
    always counts against the setup. A bar that OPENS beyond the stop is a stop for either.

    `entry_range` is the (low, high) the entry bar printed after the fill (post_fill_range); None
    means the whole bar.

    `state` / `flag` give the setup's own exit: with flag "lost" the position is closed at the next
    open once the state no longer equals the SIGNAL's side at a bar's close; with "opposite", once
    it equals the reverse. `flag_side` is the signal's side, which differs from `side` for the
    twin: the twin is the same trade held the other way, so it leaves on the same bar."""
    tick = bars.tick
    stop = entry - side * stop_dist
    need = None if tgt_dist is None else tgt_dist + tick
    fs = side if flag_side is None else flag_side
    mae = 0.0
    o, h, l = bars.o, bars.h, bars.l
    for j in range(k, last + 1):
        if j > k:
            if j == last:
                return (o[j] - entry) * side, "time", j, False, mae, 1
            if flag is not None:
                s = state[j - 1]
                if (s != fs) if flag == "lost" else (s == -fs):
                    return (o[j] - entry) * side, "flag", j, False, mae, 1
        lo, hi = (l[j], h[j]) if j > k or entry_range is None else entry_range
        adverse = (entry - lo) if side == 1 else (hi - entry)
        favor = (hi - entry) if side == 1 else (entry - lo)
        hit_tgt = need is not None and favor >= need - 1e-9
        if adverse >= stop_dist - 1e-9:
            gapped = j > k and (o[j] - stop) * side <= 0
            if hit_tgt and both == "target" and not gapped:
                return tgt_dist, "target", j, True, mae, 0
            px = o[j] if gapped else stop
            return (px - entry) * side, "stop", j, hit_tgt, max(mae, (entry - px) * side), 1
        if adverse > mae:
            mae = adverse
        if hit_tgt:
            return tgt_dist, "target", j, False, mae, 0
    return (bars.c[last] - entry) * side, "time", last, False, mae, 1     # entered on the last bar


def simulate(bars, sessions, setup, params: dict, ind: dict, exit_spec: dict, audit: list | None = None) -> list[Trade]:
    """Run one setup over every session. One position at a time: a signal raised while a position
    is open or an order is pending is ignored. Every trade is also walked the other way from the
    same fill with the same distances (`r_other`, `g_other`), which makes the coin-flip control
    exact arithmetic instead of a second random simulation.

    exit_spec: target_r (None = no target), min_stop_atr (floor for structural stops, in ATRs),
    flag ("lost" | "opposite" | None) with the state column in ind["state"], trend ("with" |
    "against" | None) with ind["trend_ema"], hold (close at the open of the bar this many bars
    after the entry bar), stop_atr_override (replace the setup's stop with this many ATRs; with
    `hold` and a very wide stop this measures the plain move after the signal).
    `audit`, if given, collects (signal bar, order, "fill" | "dead", session) for every order."""
    tick, comm = bars.tick, bars.commission_pts
    target_r = exit_spec.get("target_r")
    floor_atr = exit_spec.get("min_stop_atr", 0.5)
    flag = exit_spec.get("flag")
    state = ind.get("state") if flag else None
    trend = exit_spec.get("trend")
    hold = exit_spec.get("hold")
    override = exit_spec.get("stop_atr_override")
    atr_col = ind["atr"]
    out: list[Trade] = []
    for s in sessions:
        i = s.first_sig
        while i <= s.last_sig:
            order = setup(i, params, ind, bars)
            if order is None or not trend_ok(i, order.side, trend, ind, bars):
                i += 1
                continue
            got = fill_entry(bars, i, order, s.last_entry)
            if audit is not None:
                audit.append((i, order, got[0], s))
            if got[0] == "dead":
                i = max(i + 1, got[1])            # nothing may be raised while it was pending
                continue
            _, k, px, slip, at_open = got          # slip: points the order paid beyond the market
            side = order.side
            entry = px + side * slip
            if override is not None:
                stop_dist = override * atr_col[i]
            elif order.stop_px is not None:
                stop_dist = max((entry - order.stop_px) * side, floor_atr * atr_col[i])
            else:
                stop_dist = order.stop_atr * atr_col[i]
            stop_dist = round_up(stop_dist, tick)
            if stop_dist <= 0:
                i += 1
                continue
            tgt_dist = None if target_r is None else round_up(target_r * stop_dist, tick)
            last = s.exit_i if hold is None else min(s.exit_i, k + hold)
            after = post_fill_range(bars, k, order, at_open)
            pts, why, x, amb, mae, xslip = run_exit(bars, k, last, side, entry, stop_dist, tgt_dist,
                                                    after, state, flag)
            net = pts - xslip * tick - comm
            gross = pts + slip
            # The coin-flip twin: the same fill the other way, same distances, same entry-bar
            # range, same exit bar under a flag exit. A bar holding both its stop and its target
            # is booked as its target, so the doubt counts against the setup.
            o_entry = px - side * tick
            o_pts, _, _, _, _, o_xslip = run_exit(bars, k, last, -side, o_entry, stop_dist, tgt_dist,
                                                  after, state, flag, side, "target")
            o_net = o_pts - o_xslip * tick - comm
            o_gross = o_pts + tick
            out.append(Trade(day=s.ordinal, sig=i, k=k, side=side, entry=entry, stop_dist=stop_dist,
                             r=net / stop_dist, g=gross / stop_dist, r_other=o_net / stop_dist,
                             g_other=o_gross / stop_dist, why=why, exit_i=x, ambiguous=amb, pts=net,
                             mae=mae, minute=bars.mod[k]))
            # flat by the close of bar x (stop / target inside it, time / flag at its open)
            i = max(i + 1, x)
    return out


# ----------------------------------------------------------------------------- statistics


def mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else math.nan


def cluster_stats(values: list[float], clusters: list[int]) -> dict:
    """Mean with a standard error that treats each cluster (a session) as one draw.

    Trades inside a session share that session's trend, so they are not independent, and dividing
    by sqrt(trades) is the mistake the VRP study's overlap rule exists to prevent. This is the
    usual cluster-robust estimator for a mean:
        SE = sqrt( G/(G-1) * sum_g (sum_{i in g} (x_i - m))^2 ) / N
    verify.py [8] shows it recovers the true SE on a block-constant series and that the naive one
    is too small by sqrt(block size)."""
    n = len(values)
    if n < 2:
        return {"n": n, "mean": math.nan, "se": math.nan, "t": math.nan, "g": 0, "naive_se": math.nan}
    m = sum(values) / n
    sums: dict[int, float] = {}
    for v, g in zip(values, clusters):
        sums[g] = sums.get(g, 0.0) + (v - m)
    G = len(sums)
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    naive = math.sqrt(var / n)
    if G < 2:
        return {"n": n, "mean": m, "se": math.nan, "t": math.nan, "g": G, "naive_se": naive}
    se = math.sqrt(G / (G - 1.0) * sum(x * x for x in sums.values())) / n
    return {"n": n, "mean": m, "se": se, "t": m / se if se > 0 else math.nan, "g": G, "naive_se": naive}


def direction_edge(trades: list[Trade]) -> dict:
    """What the direction call is worth, with drift taken out.

    For each trade L = (gross R long - gross R short)/2 at that fill, whichever side the setup
    chose. `edge` = mean(side * L) is the gain over a coin flip on the same fills, exactly.
    `skill` removes drift: mean(side * (L - mean L)), the covariance between the call and what
    being long paid. A setup that is long most of the time in a rising market shows edge > 0 and
    skill near 0. Only skill is evidence the pattern knows the direction, so the verdict uses it."""
    if not trades:
        return {"n": 0, "dprime": [], "days": []}
    L = [t.side * (t.g - t.g_other) / 2.0 for t in trades]
    lbar = sum(L) / len(L)
    d = [t.side * x for t, x in zip(trades, L)]
    dp = [t.side * (x - lbar) for t, x in zip(trades, L)]
    days = [t.day for t in trades]
    return {"n": len(trades), "edge": cluster_stats(d, days), "skill": cluster_stats(dp, days),
            "drift": lbar, "long_share": sum(1 for t in trades if t.side == 1) / len(trades),
            "baseline": mean((t.g + t.g_other) / 2.0 for t in trades), "dprime": dp, "days": days}


def day_sums(values: list[float], clusters: list[int]) -> dict[int, float]:
    sums: dict[int, float] = {}
    for v, g in zip(values, clusters):
        sums[g] = sums.get(g, 0.0) + v
    return sums


_BITS = bytes.maketrans(b"01", b"\x00\x01")


def coin_flips(n: int, rng: random.Random) -> bytes:
    """n fair coin flips as a bytes object of 0s and 1s (one random integer, read bit by bit)."""
    return format(rng.getrandbits(n), "b").zfill(n).encode().translate(_BITS)


def flipped_sum(xs: list[float], total: float, flips: bytes) -> float:
    """sum of +x where the flip is 1 and -x where it is 0 = 2 * (sum of the selected) - total."""
    return 2.0 * sum(compress(xs, flips)) - total


def sign_flip_p(day_totals: list[float], runs: int, rng: random.Random) -> float:
    """One-sided p-value for sum(day_totals) > 0 when each session's sign is a coin flip. This is
    the coin-flip control: every session keeps its fills, stops, targets and trade count and only
    the direction of that session's calls is randomised. p = (1 + hits) / (1 + runs)."""
    xs = list(day_totals)
    obs = sum(xs)
    tol = 1e-9 * sum(abs(x) for x in xs)
    n = len(xs)
    hits = 0
    for _ in range(runs):
        if flipped_sum(xs, obs, coin_flips(n, rng)) >= obs - tol:
            hits += 1
    return (1 + hits) / (1 + runs)


def drop_best(values: list[float], frac: float = 0.01) -> float:
    """Mean after removing the best `frac` of the trades (at least one)."""
    k = max(1, int(round(frac * len(values))))
    kept = sorted(values)[:-k]
    return sum(kept) / len(kept) if kept else math.nan


def inv_norm(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation, |error| < 1.2e-9)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    lo, hi = 0.02425, 1 - 0.02425
    if p < lo:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > hi:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
