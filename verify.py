"""Verification for the batch study. No market file is opened; no real outcome is read.

    py -3.14 verify.py            all checks (about twenty minutes: [5] to [7] simulate)
    py -3.14 verify.py --fast     thins [5] and skips the long simulations in [6] and [7]

The fill engine itself (core.py) was verified and reviewed in ta_setups and is copied here
unchanged. What is new in this folder is checked here:

  [1] the exchange calendar by rule against known holiday lists, and every calendar flag against a
      plain restatement over every trading day of 2013-2026
  [2] what a Day knows: yesterday's close, the 20-day range, the pre-open bar, the lookback chain,
      the VIX flag on every session
  [3] a Plan's fill, cost and coin-flip twin on hand-worked bars, long and short
  [4] every strategy against a second implementation written a different way, on a walk whose
      bars open away from the last close, comparing the decision bar, entry, exit, side, stop and
      target of every plan
  [5] no look-ahead: far (everything after six random cuts scrambled; the file ending there) and
      near (every bar of a block of sessions used as a cut); three strategies written to cheat
      must be caught; damaged bars must not break anything
  [6] the reality check and the account simulation on series where the answer is known, and the
      size of the reality check on rarely-traded, lopsided series
  [7] the decision (batch.decide, the three routes): every threshold on p-values and t-statistics
      set by hand, and the runner's own arithmetic; then the whole thing on pairs of zero-edge
      walks and pairs with a planted effect, and its false-alarm rate and power at the real
      sample sizes
  [8] the suite against itself: eleven deliberate bugs, each of which must make a check fail
"""
from __future__ import annotations

import bisect
import contextlib
import io
import math
import random
import statistics
import sys
import types
from datetime import date, timedelta
from operator import itemgetter

import batch
import core
import data
import registry
import strategies as st
from batch import Plan

OK = True
QUIET = {"on": False, "fails": 0}
EVER = (date(2000, 1, 1), date(2100, 1, 1))
GRID = list(range(0, 1020, 5)) + list(range(1080, 1440, 5))        # 00:00-16:55, 18:00-23:55
FAKE_VIX = {date(2020, 1, 1) + timedelta(days=i): 10.0 + (i * 7919 % 13) for i in range(2500)}


def check(label: str, cond, detail: str = "") -> None:
    global OK
    if QUIET["on"]:
        QUIET["fails"] += not cond
        return
    OK = OK and bool(cond)
    print(f"  [{'ok' if cond else 'FAIL'}] {label}{'  ' + detail if detail else ''}")


def failures(run) -> int:
    """Run checks without printing them or touching the verdict; -> how many failed. A crash counts
    as a failure: it is used on deliberately broken code."""
    QUIET["on"], QUIET["fails"] = True, 0
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            run()
    except Exception:
        QUIET["fails"] += 1
    finally:
        QUIET["on"] = False
    return QUIET["fails"]


def close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def sg(x: float) -> int:
    return (x > 0) - (x < 0)


def walk(days: int, seed: int, plant: float = 0.0, start: date = date(2022, 1, 3), gap: int = 0) -> data.Bars:
    """A one-tick-at-a-time random walk on the real session grid and the real exchange calendar.
    `plant` tilts the last half hour toward the sign of the first half-hour return (measured from
    yesterday's 16:00): each step goes that way with probability 0.5 + plant.
    `gap` makes every bar open up to that many ticks away from the last close, so that "the close
    of the bar before" and "the open of this bar" are different numbers, as they are in a market."""
    rng = random.Random(seed)
    b = data._new("TICK", "NQ", 5)
    closed = set()
    for y in range(start.year, start.year + 4):
        closed |= batch.equity_holidays(y)
    x = 80000
    prev_close = None
    d, made = start, 0
    while made < days:
        if d.weekday() < 5 and d not in closed:
            base = d.toordinal() * 1440
            tilt, x10 = 0.0, None
            for m in GRID:
                if m == 600:
                    x10 = x
                if m == 930 and plant and prev_close is not None and x10 is not None:
                    tilt = plant * (1 if x10 > prev_close else -1 if x10 < prev_close else 0)
                if m == 960:
                    prev_close, tilt = x, 0.0
                if gap:
                    x += rng.randint(-gap, gap)
                n = 60 if 570 <= m < 960 else 12
                o = hi = lo = x
                for _ in range(n):
                    x += 1 if rng.random() < 0.5 + tilt else -1
                    hi, lo = max(hi, x), min(lo, x)
                b.add(base + m, o * 0.25, hi * 0.25, lo * 0.25, x * 0.25, float(rng.randint(50, 500)))
            made += 1
        d += timedelta(days=1)
    data.build_sessions(b, *EVER, to_the_close=True)
    return b


def copy_bars(src: data.Bars, n: int | None = None) -> data.Bars:
    b = data._new(src.name, "NQ", src.tf)
    n = len(src) if n is None else n
    b.t, b.mod = src.t[:n], src.mod[:n]
    b.o, b.h, b.l, b.c, b.v = src.o[:n], src.h[:n], src.l[:n], src.c[:n], src.v[:n]
    return b


def scrambled(src: data.Bars, seed: int) -> data.Bars:
    """The same bar grid with every price and every volume replaced by something else."""
    rng = random.Random(seed)
    s = copy_bars(src)
    for j in range(len(s)):
        f, g = 1.0 + rng.uniform(-0.02, 0.02), 1.0 + rng.uniform(-0.02, 0.02)
        s.o[j] *= f
        s.c[j] *= g
        s.h[j] = max(s.o[j], s.c[j]) * 1.002
        s.l[j] = min(s.o[j], s.c[j]) * 0.998
        s.v[j] = float(rng.randint(1, 5000))
    return s


def splice(src: data.Bars, other: data.Bars, cut: int) -> data.Bars:
    """`src` up to and including bar `cut`, `other` after it. Same grid, so the same sessions."""
    b = data._new(src.name, "NQ", src.tf)
    b.t, b.mod = src.t, src.mod
    for col in ("o", "h", "l", "c", "v"):
        setattr(b, col, getattr(src, col)[:cut + 1] + getattr(other, col)[cut + 1:])
    b.sessions = src.sessions
    return b


# ----------------------------------------------------------------------------- [1] calendar


def t_calendar() -> None:
    print("[1] the exchange calendar")
    D = date
    check("Easter Sunday: 2019-04-21, 2021-04-04, 2024-03-31, 2026-04-05",
          [batch.easter(y) for y in (2019, 2021, 2024, 2026)] == [D(2019, 4, 21), D(2021, 4, 4), D(2024, 3, 31), D(2026, 4, 5)])
    check("NYSE holidays 2024 by rule match the published list",
          batch.equity_holidays(2024) == {D(2024, 1, 1), D(2024, 1, 15), D(2024, 2, 19), D(2024, 3, 29), D(2024, 5, 27),
                                          D(2024, 6, 19), D(2024, 7, 4), D(2024, 9, 2), D(2024, 11, 28), D(2024, 12, 25)})
    check("2022: New Year's Day on a Saturday is not kept on the Friday; Juneteenth and Christmas move to Monday",
          batch.equity_holidays(2022) == {D(2022, 1, 17), D(2022, 2, 21), D(2022, 4, 15), D(2022, 5, 30), D(2022, 6, 20),
                                          D(2022, 7, 4), D(2022, 9, 5), D(2022, 11, 24), D(2022, 12, 26)})
    check("2021: Independence Day kept on Monday 5 July, Christmas on Friday 24 December, no Juneteenth yet",
          batch.equity_holidays(2021) == {D(2021, 1, 1), D(2021, 1, 18), D(2021, 2, 15), D(2021, 4, 2), D(2021, 5, 31),
                                          D(2021, 7, 5), D(2021, 9, 6), D(2021, 11, 25), D(2021, 12, 24)})
    check("special closures: 2018-12-05 and 2025-01-09", D(2018, 12, 5) in batch.equity_holidays(2018)
          and D(2025, 1, 9) in batch.equity_holidays(2025))
    days = [d for d in (D(2023, 12, 1) + timedelta(days=i) for i in range(119))
            if d.weekday() < 5 and d not in batch.equity_holidays(d.year)]              # ends Thursday 28 March 2024
    f = batch.calendar_flags(days)
    has = lambda flag: sorted(d for d in days if flag in f[d])
    check("turn of the month around January 2024: 29 Dec, then 2, 3, 4 Jan; 31 Jan, then 1, 2, 5 Feb",
          [d for d in has("tom") if D(2023, 12, 20) < d < D(2024, 2, 10)]
          == [D(2023, 12, 29), D(2024, 1, 2), D(2024, 1, 3), D(2024, 1, 4), D(2024, 1, 31), D(2024, 2, 1), D(2024, 2, 2), D(2024, 2, 5)])
    check("monthly expiration: 19 Jan 2024; its week is 16-19 Jan (Monday the 15th is a holiday)",
          D(2024, 1, 19) in has("opex") and [d for d in has("opex_week") if d.month == 1 and d.year == 2024]
          == [D(2024, 1, 16), D(2024, 1, 17), D(2024, 1, 18), D(2024, 1, 19)])
    apr = [d for d in (D(2022, 4, 1) + timedelta(days=i) for i in range(30))
           if d.weekday() < 5 and d not in batch.equity_holidays(2022)]
    fa = batch.calendar_flags(apr)
    check("April 2022: the third Friday is Good Friday, so expiration is Thursday the 14th; the week is 11-14 April",
          [d for d in apr if "opex" in fa[d]] == [D(2022, 4, 14)]
          and [d for d in apr if "opex_week" in fa[d]] == [D(2022, 4, 11), D(2022, 4, 12), D(2022, 4, 13), D(2022, 4, 14)])
    check("pre-holiday: Friday 12 Jan 2024 (before MLK Monday) and Thursday 28 Mar 2024 (before Good Friday)",
          D(2024, 1, 12) in has("pre_holiday") and D(2024, 3, 28) in has("pre_holiday") and D(2024, 1, 11) not in has("pre_holiday"))
    check("FOMC statement days: 31 Jan and 20 Mar 2024; not the Sunday meeting of 2020-03-15, not January 2013 (14:15); 108 in all",
          D(2024, 1, 31) in has("fomc") and D(2024, 3, 20) in has("fomc") and D(2020, 3, 15) not in batch.FOMC
          and D(2013, 1, 30) not in batch.FOMC and min(batch.FOMC) == D(2013, 3, 20)
          and len(batch.FOMC) == 7 + 8 * 11 + 7 + 6, f"{len(batch.FOMC)} dates")
    check("day of week and first/last of the month", "dow4" in f[D(2024, 1, 19)] and "mfirst" in f[D(2024, 1, 2)]
          and "mlast" in f[D(2024, 1, 31)] and "mfirst" not in f[D(2024, 1, 3)])
    # every flag restated from the list of trading days alone, over every trading day of 2013-2026
    hol = set()
    for y in range(2012, 2028):
        hol |= batch.equity_holidays(y)
    td = [d for d in (D(2013, 1, 1) + timedelta(days=i) for i in range((D(2026, 12, 31) - D(2013, 1, 1)).days + 1))
          if d.weekday() < 5 and d not in hol]
    flags = batch.calendar_flags(td)
    month: dict = {}
    for d in td:
        month.setdefault((d.year, d.month), []).append(d)
    bad = 0
    for d in td:
        m = month[(d.year, d.month)]
        want = {f"dow{d.weekday()}"}
        if d == m[0]:
            want.add("mfirst")
        if d == m[-1]:
            want.add("mlast")
        if d == m[-1] or d in m[:3]:
            want.add("tom")
        third = [x for x in (D(d.year, d.month, k) for k in range(1, 29)) if x.weekday() == 4][2]
        ex = third
        while ex in hol:
            ex -= timedelta(days=1)
        if d == ex:
            want.add("opex")
        if d.isocalendar()[:2] == third.isocalendar()[:2]:
            want.add("opex_week")
        nxt = d + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        if nxt in hol:
            want.add("pre_holiday")
        if d in batch.FOMC:
            want.add("fomc")
        bad += want != set(flags[d])
    check("every flag of every trading day 2013-2026 matches a restatement from the list of trading days", bad == 0,
          f"{len(td):,} days, {bad} differ")


# ----------------------------------------------------------------------------- [2] the day


def t_days(b: data.Bars, days: list) -> None:
    print("[2] what a Day knows")
    by = {d.date: d for d in days}
    d = days[40]
    s = d.s
    check("session runs 09:30 to the 16:00 bar; signals to 15:50, entries to 15:55",
          (b.mod[s.first_sig], b.mod[s.last_sig], b.mod[s.last_entry], b.mod[s.exit_i]) == (570, 950, 955, 960))
    check("yesterday's close is the open of yesterday's 16:00 bar, and yesterday is the previous trading day",
          d.prev is days[39] and d.prev_close == b.o[days[39].s.exit_i])
    rng_of = [max(b.h[x.s.first_sig:x.s.exit_i]) - min(b.l[x.s.first_sig:x.s.exit_i]) for x in days]
    bad = 0
    for i, x in enumerate(days):
        past = rng_of[max(0, i - 20):i]
        want = sum(past) / len(past) if len(past) >= 15 else None
        bad += (x.datr is None) != (want is None) or (want is not None and not close(x.datr, want))
    check("DATR on every session: the mean high-low range of the previous 20 sessions, today excluded; none until 15 exist",
          bad == 0 and days[14].datr is None and days[15].datr is not None, f"{len(days)} sessions, {bad} differ")
    check("the pre-open bar is the 09:25 bar of the same date", b.mod[d.pre] == 565 and b.t[d.pre] // 1440 == s.ordinal)
    check("the day's bars start at 00:00 of its own date, and every clock time from 00:00 to 16:00 is found",
          b.mod[d.first_bar] == 0 and b.t[d.first_bar] // 1440 == s.ordinal and d.at[0] == d.first_bar
          and all(m in d.at for m in range(0, 965, 5)))
    check("half-hour moves from the open are stored for 10:00 .. 16:00, each the close of the bar ending there",
          sorted(d.move) == list(range(600, 961, 30)) and close(d.move[600], abs(b.c[d.at[600] - 1] / d.open - 1))
          and close(d.move[960], abs(b.c[s.exit_i - 1] / d.open - 1)))
    check("on this walk a bar's open is not the last close (so a price read off the wrong bar shows)",
          sum(1 for i in range(1, len(b)) if b.o[i] != b.c[i - 1]) > 0.5 * len(b))
    after = by[date(2022, 2, 22)]
    check("across an exchange holiday, yesterday is the last trading day before it",
          after.prev is by[date(2022, 2, 18)] and "pre_holiday" in by[date(2022, 2, 18)].flags)
    b2 = copy_bars(b)
    victim = days[60].s
    for col in (b2.t, b2.mod, b2.o, b2.h, b2.l, b2.c, b2.v):
        del col[victim.first_sig + 5:victim.first_sig + 20]
    data.build_sessions(b2, *EVER, to_the_close=True)
    d2 = batch.build_days(b2)
    nxt = next(x for x in d2 if x.date == days[61].date)
    check("after a dropped session there is no 'yesterday' (so no overnight signal) but the lookback chain goes on",
          nxt.prev is None and nxt.prev_close is None and nxt.back is not None and nxt.back.date == days[59].date)
    dv = batch.build_days(b, FAKE_VIX)
    keys = sorted(FAKE_VIX)
    bad = 0
    for x in dv:
        hist = [k for k in keys if k < x.date][-252:]
        med = statistics.median(FAKE_VIX[k] for k in hist)
        want = "vix_high" if FAKE_VIX[hist[-1]] > med else "vix_low"
        ok = want in x.flags and ("vix_high" in x.flags) != ("vix_low" in x.flags)
        bad += not (ok and x.vix == FAKE_VIX[batch.step_trading_day(x.date, -1)])
    check("VIX flag on every session: the last close before today against the median of the 252 closes before today",
          bad == 0 and 0.2 < sum("vix_high" in x.flags for x in dv) / len(dv) < 0.8, f"{len(dv)} sessions, {bad} differ")


# ----------------------------------------------------------------------------- [3] fills


def t_fills() -> None:
    print("[3] a plan's fill, cost and twin (NQ micro: tick 0.25, commission 0.50 point)")
    b = data._new("FIX", "NQ", 5)
    base = date(2024, 1, 3).toordinal() * 1440 + 570
    rows = [(100, 100.5, 99.5, 100), (100, 101, 99.75, 100.5), (100.5, 104, 100, 103), (103, 103.5, 102, 102.5),
            (102.5, 103, 96, 97), (97, 98, 96.5, 97.5)]
    for n, (o, h, l, c) in enumerate(rows):
        b.add(base + 5 * n, o, h, l, c, 1.0)
    s = data.Session(day=date(2024, 1, 3), ordinal=1, first_sig=0, last_sig=3, last_entry=4, exit_i=5)
    day = batch.Day(s=s, n=0, date=s.day, at={}, open=100.0, datr=10.0)
    ex = lambda **kw: batch.execute(b, day, Plan(**kw))
    t = ex(sig=0, k=1, x=3, side=1)
    check("long 1 -> 3 with no stop: filled 100.25, out at 103.00: gross +3.00, net 3.00 - 0.25 - 0.25 - 0.50 = +2.00",
          close(t.gross, 3.0) and close(t.pts, 2.0) and t.why == "time" and t.x == 3)
    check("the twin of a no-stop trade is its exact negative before costs", close(t.twin, -3.0))
    t = ex(sig=0, k=1, x=3, side=-1)
    check("short 1 -> 3 with no stop: filled 99.75, out at 103.00: gross -3.00, net -3.00 - 0.25 - 0.25 - 0.50 = -4.00",
          close(t.gross, -3.0) and close(t.pts, -4.0) and close(t.twin, 3.0) and t.why == "time")
    t = ex(sig=0, k=1, x=5, side=1, stop=3.1)
    check("a stop is rounded up to the tick (3.10 -> 3.25) and fills a tick worse: net -3.25 - 0.25 - 0.50 = -4.00",
          t.why == "stop" and t.x == 4 and close(t.pts, -4.0) and close(t.gross, -3.0))
    check("...and its twin, short from 99.75 with the same 3.25, is stopped at 103.00 on bar 2: gross -3.00", close(t.twin, -3.0))
    t = ex(sig=0, k=1, x=5, side=-1, stop=3.0)
    check("a short's stop: from 99.75, stop 102.75, hit on bar 2 (high 104.00): net -3.00 - 0.25 - 0.50 = -3.75",
          t.why == "stop" and t.x == 2 and close(t.pts, -3.75) and close(t.gross, -2.75))
    t = ex(sig=0, k=1, x=5, side=1, stop=10.0, target=3.0)
    check("a target needs a tick through: 103.25 + 0.25 = 103.50 is traded on bar 2 (high 104.00): gross +3.25",
          t.why == "target" and t.x == 2 and close(t.gross, 3.25) and close(t.pts, 2.5))
    t = ex(sig=3, k=4, x=5, side=-1, stop=10.0, target=5.0)
    check("a short's target: from 102.25, target 97.25, a tick through is 97.00 (low 96.00): net +5.00 - 0.50 = +4.50",
          t.why == "target" and t.x == 4 and close(t.pts, 4.5) and close(t.gross, 5.25))
    t = ex(sig=0, k=1, x=5, side=1, stop_px=99.0)
    check("a stop given as a price (99.00): 1.25 from the 100.25 fill, hit on bar 4: net -1.25 - 0.25 - 0.50 = -2.00",
          t.why == "stop" and t.x == 4 and close(t.pts, -2.0))
    t = ex(sig=0, k=1, x=5, side=1, stop_px=99.0, target_r=2.0)
    check("a target of 2R on that stop is 2.50: 102.75, a tick through traded on bar 2: net +2.50 - 0.25 - 0.50 = +2.00",
          t.why == "target" and t.x == 2 and close(t.pts, 2.0))
    t = ex(sig=0, k=1, x=5, side=-1, stop_px=101.0, target_r=2.0)
    check("the same for a short: stop 101.00 is 1.25 above the 99.75 fill and is hit on bar 1 itself (high 101.00)",
          t.why == "stop" and t.x == 1 and close(t.pts, -2.0))
    t = ex(sig=0, k=1, x=5, side=1, stop_px=100.5)
    check("a stop price the fill is already beyond is hit at once: in and out at the open, two ticks and the commission, -1.00",
          t.why == "stop" and t.x == 1 and close(t.pts, -1.0) and t.gross == 0.0 and t.twin == 0.0)
    t = ex(sig=0, k=1, x=5, side=-1, stop_px=99.75)
    check("...the same for a short whose stop price is exactly its fill (99.75)", t.why == "stop" and t.x == 1 and close(t.pts, -1.0))
    for bad in (dict(sig=1, k=1, x=3, side=1), dict(sig=0, k=3, x=3, side=1), dict(sig=0, k=1, x=6, side=1),
                dict(sig=0, k=1, x=3, side=1, stop=1.0, stop_px=99.0), dict(sig=0, k=1, x=3, side=1, target_r=2.0)):
        try:
            ex(**bad)
            raised = False
        except ValueError:
            raised = True
        check(f"refused: {', '.join(f'{k} {v}' for k, v in bad.items())}", raised)


# ----------------------------------------------------------------------------- [4] second implementation


def t_second(b: data.Bars, days: list, dv: list) -> None:
    print("[4] every strategy against a second implementation: decision bar, entry, exit, side, stop and target")
    fn = {s["key"]: s["fn"] for s in registry.STRATEGIES}
    done = set()
    bar = {(t // 1440, m): i for i, (t, m) in enumerate(zip(b.t, b.mod))}
    by_date = {d.date: d for d in days}
    index = {d.date: i for i, d in enumerate(days)}

    def B(d, minute):                       # the bar that STARTS at a clock time
        return bar[(d.s.ordinal, minute)]

    def C(d, minute):                       # the price at a clock time: the close of the bar that ENDS there
        return b.c[bar[(d.s.ordinal, minute - 5)]]

    def O(d):                               # the session's first print
        return b.o[B(d, 570)]

    def Y(d):                               # yesterday: the previous exchange trading day, if it was a session
        return by_date.get(batch.step_trading_day(d.date, -1))

    def YC(d):                              # yesterday's 16:00 price, the one everything was closed at
        y = Y(d)
        return None if y is None else b.o[B(y, 960)]

    def one(d, t_in, t_out, side, stop_px=None, target_r=None):
        if side == 0:
            return []
        return [(bar[(d.s.ordinal, t_in - 5)], B(d, t_in), B(d, t_out), side, None, None, stop_px, target_r)]

    def got(f, d):
        return [(p.sig, p.k, p.x, p.side, p.stop, p.target, p.stop_px, p.target_r) for p in f(d, b)]

    def same(key, expect, label, use=None):
        f = use or fn[key]
        bad = n = 0
        for d in days:
            if d.datr is None:
                continue
            have = got(f, d)
            n += len(have)
            bad += have != expect(d)
        done.add(key)
        check(f"{key:<15} {label}", bad == 0 and n > 0, f"{n} plans, {bad} days differ")

    def gap(d):
        return None if YC(d) is None else C(d, 570) - YC(d)

    same("gao", lambda d: [] if YC(d) is None else one(d, 930, 960, sg(C(d, 600) - YC(d))), "sign(10:00 - yesterday's close), 15:30-16:00")
    same("gao_both", lambda d: [] if YC(d) is None or sg(C(d, 930) - C(d, 900)) != sg(C(d, 600) - YC(d))
         else one(d, 930, 960, sg(C(d, 600) - YC(d))), "only when 15:00-15:30 agrees")
    same("rod", lambda d: [] if YC(d) is None else one(d, 930, 960, sg(C(d, 930) - YC(d))), "sign(15:30 - yesterday's close)")
    same("rod_day", lambda d: one(d, 930, 960, sg(C(d, 930) - O(d))), "sign(15:30 - open)")
    same("first15_hold", lambda d: one(d, 585, 960, sg(C(d, 585) - O(d))), "sign(09:45 - open), held 09:45-16:00")
    same("first30_hold", lambda d: [] if YC(d) is None else one(d, 600, 960, sg(C(d, 600) - YC(d))), "held 10:00-16:00")
    same("first60_hold", lambda d: one(d, 630, 960, sg(C(d, 630) - O(d))), "sign(10:30 - open), held 10:30-16:00")
    same("morning_hold", lambda d: one(d, 720, 960, sg(C(d, 720) - O(d))), "sign(12:00 - open), held 12:00-16:00")
    same("gap_follow", lambda d: [] if gap(d) is None else one(d, 570, 960, sg(gap(d))), "follow the overnight move (09:25 close - yesterday's close)")
    same("gap_fade", lambda d: [] if gap(d) is None else one(d, 570, 960, -sg(gap(d))), "fade it")
    same("gap_fade_30", lambda d: [] if gap(d) is None else one(d, 570, 600, -sg(gap(d))), "fade it 09:30-10:00")
    same("gap_fade_1h", lambda d: [] if gap(d) is None or abs(gap(d)) < 0.25 * d.datr else one(d, 570, 630, -sg(gap(d))),
         "0.25 DATR or more, 09:30-10:30")
    same("biggap_follow", lambda d: [] if gap(d) is None or abs(gap(d)) < 0.5 * d.datr else one(d, 570, 960, sg(gap(d))),
         "0.5 DATR or more, followed")
    same("biggap_fade", lambda d: [] if gap(d) is None or abs(gap(d)) < 0.5 * d.datr else one(d, 570, 960, -sg(gap(d))),
         "0.5 DATR or more, faded")
    same("ovn_last30", lambda d: [] if gap(d) is None else one(d, 930, 960, sg(gap(d))), "follow it 15:30-16:00")
    same("ovn_last30_big", lambda d: [] if gap(d) is None or abs(gap(d)) < 0.25 * d.datr else one(d, 930, 960, sg(gap(d))),
         "the same for 0.25 DATR or more")
    # a 2% day never happens on this walk, so the rule is checked at a threshold that does fire
    same("big_day", lambda d: [] if YC(d) is None or abs(C(d, 885) / YC(d) - 1) < 0.0003
         else one(d, 885, 960, sg(C(d, 885) - YC(d))), "move on the day at 14:45 beyond a threshold (0.03% here, 2% registered)",
         use=st.big_day(885, 0.0003))
    check("big_day         registered at 14:45 and 2%, and silent on a walk that never moves 2%",
          not any(fn["big_day"](d, b) for d in days if d.datr is not None))

    def vwap(d):
        first, last = B(d, 570), B(d, 960)
        out, pos, k0, s0 = [], 0, None, None
        for i in range(first, last - 1):                      # closes up to 15:50: the last change is at 15:55
            num = sum((b.h[q] + b.l[q] + b.c[q]) / 3 * b.v[q] for q in range(first, i + 1))
            vw = num / sum(b.v[q] for q in range(first, i + 1))
            new = 1 if b.c[i] > vw else -1 if b.c[i] < vw else pos
            if new != pos:
                if pos:
                    out.append((s0, k0, i + 1, pos, None, None, None, None))
                pos, k0, s0 = new, i + 1, i
        if pos:
            out.append((s0, k0, last, pos, None, None, None, None))
        return out
    same("vwap_trend", vwap, "side of the session VWAP on every 5-minute close")

    for key, t_in, t_out, side, flag in (("long_first30", 570, 600, 1, None), ("lunch_short", 660, 720, -1, None),
                                         ("opex_am_short", 570, 720, -1, "opex"),
                                         ("lunch_long", 720, 840, 1, None), ("night_drift", 120, 180, 1, None),
                                         ("long_last30", 930, 960, 1, None), ("short_last30", 930, 960, -1, None),
                                         ("long_day", 570, 960, 1, None), ("tom", 570, 960, 1, "tom"),
                                         ("opex_week", 570, 960, 1, "opex_week"), ("pre_holiday", 570, 960, 1, "pre_holiday"),
                                         ("fomc_pre", 570, 835, 1, "fomc"), ("monday", 570, 960, 1, "dow0"),
                                         ("friday", 570, 960, 1, "dow4")):
        same(key, lambda d, a=t_in, z=t_out, sd=side, fl=flag: one(d, a, z, sd) if fl is None or fl in d.flags else [],
             f"{'long' if side == 1 else 'short'} {t_in // 60:02d}:{t_in % 60:02d}-{t_out // 60:02d}:{t_out % 60:02d}"
             + (f" on {flag} days" if flag else ""))
    same("fomc_after", lambda d: one(d, 870, 960, sg(C(d, 870) - C(d, 840))) if "fomc" in d.flags else [], "follow 14:00-14:30")
    same("fomc_reversal", lambda d: one(d, 845, 960, -sg(C(d, 840) - YC(d))) if "fomc" in d.flags and YC(d) is not None else [],
         "fade yesterday's close -> 14:00, from 14:05")

    def payday(d):
        for k in range(16, 24):
            x = date(d.date.year, d.date.month, k)
            if x.weekday() < 5 and x not in batch.equity_holidays(x.year):
                return one(d, 570, 960, 1) if d.date == x else []
        return []
    same("payday", payday, "first trading day on or after the 16th")
    yret = lambda y: b.o[B(y, 960)] - b.o[B(y, 570)]            # yesterday's session as it was traded: open to the 16:00 price
    same("yday_follow", lambda d: [] if Y(d) is None else one(d, 570, 960, sg(yret(Y(d)))), "yesterday's daytime sign")
    same("yday_fade", lambda d: [] if Y(d) is None else one(d, 570, 960, -sg(yret(Y(d)))), "the reverse")

    def down3(d):
        c, x = [], d
        for _ in range(4):
            x = Y(x)
            if x is None:
                return []
            c.append(b.o[B(x, 960)])
        return one(d, 570, 960, 1) if c[0] < c[1] < c[2] < c[3] else []
    same("down3_long", down3, "three lower closes in a row")

    def half(d):
        y = Y(d)
        if y is None:
            return []
        marks = list(range(570, 960, 30))
        sides = [sg(C(y, T + 30) - C(y, T)) for T in marks]
        out, start = [], 0
        for n in range(1, len(marks) + 1):
            if n == len(marks) or sides[n] != sides[start]:    # the run that began at `start` ends here
                out += one(d, marks[start], marks[n - 1] + 30, sides[start])
                start = n
        return out
    same("same_half_hour", half, "yesterday's half-hour signs, a position held while they agree")
    hh = [len(fn["same_half_hour"](d, b)) for d in days if d.datr is not None and d.prev is not None]
    check("same_half_hour  trades fewer than thirteen times a day because agreeing half hours are merged",
          1 <= min(hh) and max(hh) <= 13 and 5 < sum(hh) / len(hh) < 8.5, f"mean {sum(hh) / len(hh):.1f} a day")

    def orb5(target_r):
        def f(d):
            i = B(d, 570)
            side = sg(b.c[i] - b.o[i])
            if side == 0:
                return []
            return [(i, B(d, 575), B(d, 960), side, None, None, b.l[i] if side == 1 else b.h[i], target_r)]
        return f
    same("orb5_10r", orb5(10.0), "first candle's direction from 09:35, stop at its other end, target 10R")
    same("orb5_close", orb5(None), "the same, no target")

    def orb(minutes):
        def f(d):
            first = B(d, 570)
            n = minutes // 5
            hi = max(b.h[first + q] for q in range(n))
            lo = min(b.l[first + q] for q in range(n))
            i = first + n
            while b.mod[i] + 5 <= 900:
                if b.c[i] > hi or b.c[i] < lo:
                    side = 1 if b.c[i] > hi else -1
                    return [(i, i + 1, B(d, 960), side, None, None, lo if side == 1 else hi, None)]
                i += 1
            return []
        return f
    same("orb30", orb(30), "first close outside the 30-minute range by 15:00, stop at the far side")
    same("orb60", orb(60), "first close outside the 60-minute range by 15:00, stop at the far side")

    def noise(vwap_stop, look=14):
        def f(d):
            i = index[d.date]
            if YC(d) is None or i < look:
                return []
            hist = days[i - look:i][::-1]
            first = B(d, 570)
            ref_up, ref_lo = max(O(d), YC(d)), min(O(d), YC(d))
            out, pos, k0, s0 = [], 0, None, None
            for T in range(600, 960, 30):
                sigma = sum(abs(C(h, T) / O(h) - 1) for h in hist) / look
                up, lo = ref_up * (1 + sigma), ref_lo * (1 - sigma)
                p = C(d, T)
                j = B(d, T)                                    # entry bar; everything up to j - 1 is known
                num = sum((b.h[q] + b.l[q] + b.c[q]) / 3 * b.v[q] for q in range(first, j))
                vw = num / sum(b.v[q] for q in range(first, j))
                new = pos
                if pos == 0:
                    new = 1 if p > up else -1 if p < lo else 0
                elif vwap_stop:
                    if pos == 1 and p < max(up, vw):
                        new = -1 if p < lo else 0
                    elif pos == -1 and p > min(lo, vw):
                        new = 1 if p > up else 0
                else:
                    if pos == 1 and p < lo:
                        new = -1
                    elif pos == -1 and p > up:
                        new = 1
                if new != pos:
                    if pos:
                        out.append((s0, k0, j, pos, None, None, None, None))
                    pos, k0, s0 = new, j, bar[(d.s.ordinal, T - 5)]
            if pos:
                out.append((s0, k0, B(d, 960), pos, None, None, None, None))
            return out
        return f
    same("noise", noise(False), "noise area, reverse at the opposite boundary")
    same("noise_vwap", noise(True), "noise area with the VWAP stop")
    same("noise_vwap_90", noise(True, 90), "the same on a 90-day lookback")

    for a_, b_ in (("gao_highvix", "gao"), ("gao_both_hivix", "gao_both"), ("orb30_hivix", "orb30"), ("fomc_pre_hivix", "fomc_pre")):
        x_ = {d.date: fn[a_](d, b) for d in dv if d.datr is not None}
        y_ = {d.date: fn[b_](d, b) for d in dv if d.datr is not None}
        done.add(a_)
        check(f"{a_:<15} equals {b_} on high-VIX days and is empty otherwise",
              all(x_[d.date] == (y_[d.date] if "vix_high" in d.flags else []) for d in dv if d.datr is not None)
              and any(x_.values()) and any(not v for k, v in x_.items() if y_[k]))
    untested = set(fn) - done
    check("every registered strategy has a second implementation above", not untested,
          f"missing: {sorted(untested)}" if untested else f"{len(fn)} strategies")


# ----------------------------------------------------------------------------- [5] look-ahead


def cheat(day, bars):
    """Written to cheat: at 10:00 it trades on where the session will close."""
    k, x = day.at.get(600), day.s.exit_i
    if k is None:
        return []
    return [Plan(sig=k - 1, k=k, x=x, side=st.sign(bars.o[x] - bars.o[k]) or 1)]


def cheat_one_bar(day, bars):
    """Written to cheat by one bar: at 10:00 it trades on where its own entry bar will close."""
    k, x = day.at.get(600), day.s.exit_i
    if k is None:
        return []
    return [Plan(sig=k - 1, k=k, x=x, side=st.sign(bars.c[k] - bars.o[k]) or 1)]


def cheat_hour(day, bars):
    """Written to cheat by an hour: at 10:00 it trades on the price at 11:00."""
    k, x = day.at.get(600), day.s.exit_i
    if k is None:
        return []
    return [Plan(sig=k - 1, k=k, x=x, side=st.sign(bars.o[k + 12] - bars.o[k]) or 1)]


CHEATS = [("CHEAT (the close)", cheat), ("CHEAT (one bar)", cheat_one_bar), ("CHEAT (an hour)", cheat_hour)]


def view(plans, cut: int) -> list:
    """What had been decided by the close of bar `cut`: every field of every plan whose decision bar
    is at or before it, and the exit bar only where the exit had been decided by then."""
    return [(p.sig, p.k, p.side, p.stop, p.target, p.stop_px, p.target_r, p.x if p.x - 1 <= cut else None)
            for p in plans if p.sig <= cut]


def decisions(b: data.Bars, fn, cut: int) -> list:
    out = []
    for d in batch.build_days(b, FAKE_VIX):
        if d.datr is None or d.first_bar - 1 > cut:
            continue
        out += view(fn(d, b), cut)
    return out


def t_far(b: data.Bars) -> None:
    print("[5] no look-ahead, far: everything after six random cuts scrambled, and the file ending there")
    rng = random.Random(5)
    last = b.sessions[-1].exit_i
    cuts = sorted(rng.sample(range(b.sessions[30].first_sig, last - 400), 6))
    scr = scrambled(b, 55)
    held = caught = 0
    for key, fn in [(s["key"], s["fn"]) for s in registry.STRATEGIES] + CHEATS[:1]:
        ok = True
        for cut in cuts:
            full = decisions(b, fn, cut)
            if decisions(splice(b, scr, cut), fn, cut) != full:
                ok = False
            # the file simply ending at the cut: a day cut before its 16:00 bar stops being a session,
            # so every plan of the sessions that are still whole must be unchanged
            short = copy_bars(b, cut + 1)
            data.build_sessions(short, *EVER, to_the_close=True)
            whole = [x for x in b.sessions if x.exit_i <= cut]          # sessions the short file still holds
            edge = whole[-1].exit_i if whole else -1
            if decisions(short, fn, cut) != [p for p in full if p[0] < edge]:
                ok = False
        if key.startswith("CHEAT"):
            caught += not ok
        else:
            held += ok
            if not ok:
                check(f"{key:<15} decisions unchanged", False)
    check(f"all {len(registry.STRATEGIES)} strategies: every decision before a cut is unchanged by what follows it", held == len(registry.STRATEGIES))
    check("a strategy written to trade on the coming close is caught", caught == 1)


PRE = (115, 120, 125, 175, 180, 185, 560, 565)        # the bars around the night trade and the last two before the open


def near_lookahead(b: data.Bars, sample: list, fns: list) -> tuple[dict, dict, int]:
    """Every bar of the sample sessions is used as a cut: everything after it is replaced, the Days
    are rebuilt, and each strategy is re-run on that session. Whatever it had decided by the cut
    must be unchanged. -> (cuts at which a strategy's decisions changed, decisions tested at their
    own decision bar, number of cuts)."""
    scr = scrambled(b, 77)
    base = {(key, d.n): fn(d, b) for key, fn in fns for d in sample}
    leak = {key: 0 for key, _ in fns}
    own = {key: 0 for key, _ in fns}
    n_cuts = 0
    for d in sample:
        for cut in [d.at[m] for m in PRE] + list(range(d.s.first_sig, d.s.exit_i)):
            n_cuts += 1
            s = splice(b, scr, cut)
            ds = batch.build_days(s, FAKE_VIX)[d.n]
            for key, fn in fns:
                plans = base[(key, d.n)]
                own[key] += sum(1 for p in plans if p.sig == cut)
                try:
                    leak[key] += view(fn(ds, s), cut) != view(plans, cut)
                except Exception:
                    leak[key] += 1
    return leak, own, n_cuts


def t_near(full: bool) -> None:
    b = walk(150, 21, gap=2)
    days = batch.build_days(b, FAKE_VIX)
    block = [d for d in days if d.n >= 96]                    # 90 sessions behind it: the longest lookback is alive
    if full:
        sample = block
    else:                                                     # a thin sample: three plain days and one of each special kind
        want = [block[0], block[1], block[2]] + [next((d for d in block if f in d.flags), None)
                                                 for f in ("fomc", "opex", "pre_holiday")]
        sample = sorted({d.n: d for d in want if d is not None}.values(), key=lambda d: d.n)
    print(f"    near: every bar of {len(sample)} sessions ({sample[0].date} .. {sample[-1].date}) used as a cut")
    fns = [(s["key"], s["fn"]) for s in registry.STRATEGIES] + [("big_day at 0.03%", st.big_day(885, 0.0003))] + CHEATS
    leak, own, n_cuts = near_lookahead(b, sample, fns)
    real = [key for key, _ in fns if not key.startswith("CHEAT")]
    bad = [key for key in real if leak[key]]
    check(f"all {len(real)} strategies: nothing decided by a bar changes when everything after that bar is replaced",
          not bad, f"{n_cuts:,} cuts" + (f"; changed: {bad}" if bad else ""))
    for key, _ in CHEATS:
        check(f"{key} is caught", leak[key] > 0, f"at {leak[key]:,} cuts")
    if full:
        thin = [key for key in real if own[key] == 0 and key != "big_day"]
        check("every strategy had at least one decision tested at its own decision bar (big_day through its 0.03% version)",
              not thin, f"fewest: {min(own[k] for k in real if k != 'big_day')}" + (f"; none for {thin}" if thin else ""))


def t_damaged(b: data.Bars) -> None:
    rng = random.Random(9)
    drop = set()
    for s in rng.sample(b.sessions[40:], 25):
        drop.update(rng.sample(range(s.first_sig + 1, s.exit_i - 1), 2))
    keep = [i for i in range(len(b)) if i not in drop]
    dmg = data._new("DMG", "NQ", 5)
    for col in ("t", "mod", "o", "h", "l", "c", "v"):
        src = getattr(b, col)
        setattr(dmg, col, [src[i] for i in keep])
    for i in rng.sample(range(len(dmg)), 400):
        dmg.v[i] = 0.0
    data.build_sessions(dmg, *EVER, to_the_close=True)
    days = batch.build_days(dmg, FAKE_VIX)
    crashed, trades = [], 0
    for s in registry.STRATEGIES:
        try:
            trades += len(batch.run(dmg, days, s["fn"]))
        except Exception as e:
            crashed.append(f"{s['key']}: {type(e).__name__}")
    check("with two bars missing in each of 25 sessions and 400 bars of zero volume, every strategy still runs and every plan fills",
          not crashed and len(dmg.sessions) == len(b.sessions), f"{trades:,} trades" + (f"; {crashed}" if crashed else ""))


# ----------------------------------------------------------------------------- [6] statistics


def rc_unstudentized(series: dict, runs: int, rng: random.Random) -> dict:
    """The reality check as it was first written here: every draw's sum divided by the FULL-SAMPLE
    standard deviation. Kept only to show what the draw's own t fixes."""
    n = len(next(iter(series.values())))
    stats_ = {k: batch.tstat(v) for k, v in series.items()}
    cols = [([x - s["mean"] for x in series[k]], s["sd"] * math.sqrt(n)) for k, s in stats_.items() if s["sd"] and s["sd"] > 0]
    best = []
    for _ in range(runs):
        pick = itemgetter(*[rng.randrange(n) for _ in range(n)])
        best.append(max(sum(pick(c)) / sc for c, sc in cols))
    return {k: (1 + sum(1 for x in best if x >= s["t"])) / (1 + runs) for k, s in stats_.items()}


def t_stats(full: bool) -> None:
    print("[6] the reality check and the account simulation")
    rng = random.Random(3)
    n = 1000
    noise_ = {f"n{i}": [rng.gauss(0, 1) for _ in range(n)] for i in range(30)}
    rc = batch.reality_check(dict(noise_), 1000, random.Random(1))
    raw = min(1.0 - core.norm_cdf(t) for t in rc["t"].values())
    check("thirty noise series: the best one's corrected p is far above its uncorrected p, and is not accepted",
          min(rc["p"].values()) > 0.05 and min(rc["p"].values()) > 5 * raw,
          f"best t {max(rc['t'].values()):+.2f}: p alone {raw:.3f}, corrected {min(rc['p'].values()):.2f}")
    edge = dict(noise_)
    edge["edge"] = [rng.gauss(0.15, 1) for _ in range(n)]
    rc = batch.reality_check(edge, 1000, random.Random(1))
    check("add one series with a real mean of 0.15 sd a day: it is the only one the corrected test accepts",
          rc["p"]["edge"] <= 0.05 and all(v > 0.05 for k, v in rc["p"].items() if k != "edge"),
          f"t {rc['t']['edge']:+.2f}, corrected p {rc['p']['edge']:.3f}")
    q95 = rc["best"][int(0.95 * 1000)]
    k31 = core.inv_norm(0.95 ** (1 / 31))
    check("the 95th percentile of the best-of-31 t under chance is the best-of-31 normal point", abs(q95 - k31) < 0.2,
          f"{q95:.2f} against {k31:.2f}")
    odd = {"zeros": [0.0] * 200, "const": [0.01] * 200, "one": [0.0] * 199 + [1.0], "noise": [rng.gauss(0, 1) for _ in range(200)]}
    rc = batch.reality_check(odd, 300, random.Random(1))
    check("a series that never trades or never varies has no t and a corrected p of 1; a single winning day has t 1.0 and is not accepted",
          rc["p"]["zeros"] == 1.0 and rc["p"]["const"] == 1.0 and close(rc["t"]["one"], 1.0, 1e-9) and rc["p"]["one"] > 0.1,
          f"one winning day: t {rc['t']['one']:.2f}, corrected p {rc['p']['one']:.2f}")
    r = random.Random(8)
    small = {"dense": [r.gauss(0.1, 1) for _ in range(40)], "loser": [r.gauss(-0.3, 1) for _ in range(40)],
             "sparse": [r.gauss(0.5, 1) if i % 7 == 0 else 0.0 for i in range(40)], "idle": [0.0] * 40}
    rc = batch.reality_check(small, 60, random.Random(4))
    g, want = random.Random(4), []
    for _ in range(60):
        idx = [g.randrange(40) for _ in range(40)]
        top = -math.inf
        for x in small.values():
            live = [v for v in x if v != 0.0]
            if not live:
                continue
            m = sum(live) / len(live)                         # centred on the days it traded; idle days stay zero
            draw = [x[i] - m if x[i] != 0.0 else 0.0 for i in idx]
            if max(draw) - min(draw) > 1e-12:
                top = max(top, statistics.mean(draw) / (statistics.stdev(draw) / math.sqrt(40)))
        want.append(top)
    want.sort()
    p_want = {k: (1 + sum(1 for v in want if v >= statistics.mean(x) / (statistics.stdev(x) / math.sqrt(40)))) / 61
              for k, x in small.items() if k != "idle"}
    check("the reality check equals a plain restatement, draw for draw: each draw's own t, centred on the traded days",
          all(close(a, b_, 1e-9) for a, b_ in zip(rc["best"], want)) and all(close(rc["p"][k], v) for k, v in p_want.items())
          and rc["p"]["idle"] == 1.0)
    losers = {f"d{i}": [rng.gauss(0, 1) for _ in range(400)] for i in range(10)}
    for i in range(8):                                       # eight strategies that trade 10 days in 400 and lose every time
        x = [0.0] * 400
        for j in rng.sample(range(400), 10):
            x[j] = -1.0 + rng.gauss(0, 0.3)
        losers[f"s{i}"] = x
    rc = batch.reality_check(losers, 1000, random.Random(1))
    q95, k18 = rc["best"][int(0.95 * 1000)], core.inv_norm(0.95 ** (1 / 18))
    check("eight rarely-traded strategies that lose every time do not raise the bar for the other ten",
          abs(q95 - k18) < 0.3 and all(rc["p"][f"s{i}"] == 1.0 for i in range(8)), f"95th percentile of the best t {q95:.2f} against {k18:.2f}")
    s = batch.tstat([1.0, 2.0, 3.0, 4.0])
    check("t-statistic by hand: mean 2.5, sd 1.29099, t 3.873", close(s["mean"], 2.5) and close(s["t"], 2.5 / (1.2909944487 / 2), 1e-6))
    check("drawdown: +1, -3, +1, -2, +5 has a worst peak-to-trough of -4", batch.drawdown([1, -3, 1, -2, 5]) == -4)
    dts = [date(2024, 1, 2) + timedelta(days=i) for i in range(70)]
    up = batch.account_fit([50.0] * 70, dts, horizons=(20,))
    dn = batch.account_fit([-150.0] * 70, dts, horizons=(20,))
    check("account: +$50 a day never busts; -$150 a day reaches the -$2,000 limit in every account",
          up[20]["bust"] == 0 and up[20]["median"] == 1000 and dn[20]["bust"] == 1 and dn[20]["median"] == -2000)
    feb = [date(2024, 1, 31)] + [date(2024, 2, 1) + timedelta(days=i) for i in range(12)]
    # opened 1 February. Closes +900, +1,800, +2,200: the limit has locked at +$100. Then -700 three times: 1,500, 800, 100 -> bust.
    saw = batch.account_fit([0.0, 900.0, 900.0, 400.0, -700.0, -700.0, -700.0] + [0.0] * 6, feb, horizons=(10,))
    check("account: the limit trails the closing high and locks at +$100 (up to +2,200, back to +100: bust)",
          saw[10] == {"n": 1, "bust": 1.0, "median": -2000.0}, f"{saw[10]}")
    hold = batch.account_fit([0.0, 900.0, 900.0, 400.0, -700.0, -700.0, -650.0] + [0.0] * 6, feb, horizons=(10,))
    check("...and +$150 is still alive", hold[10]["bust"] == 0.0 and hold[10]["median"] == 150.0)
    mid = batch.account_fit([-5000.0] + [10.0] * 39, [date(2024, 1, 15) + timedelta(days=i) for i in range(40)], horizons=(10,))
    check("accounts open on the first session of a month only: a loss on a mid-month first day belongs to no account",
          mid[10]["n"] == 1 and mid[10]["bust"] == 0.0 and mid[10]["median"] == 100.0)
    if not full:
        return
    # the size of the corrected test when some series trade rarely and lose big when they lose
    trials, fire, fire_old = 300, 0, 0
    for trial in range(trials):
        r = random.Random(4000 + trial)
        ser = {f"d{i}": [r.gauss(0, 1) for _ in range(600)] for i in range(14)}
        for i in range(6):
            x = [0.0] * 600
            for j in r.sample(range(600), 30):
                x[j] = 1.0 - r.expovariate(1.0)             # mean zero: many small wins, a few large losses
            ser[f"s{i}"] = x
        up_ = {k for k, v in ser.items() if sum(v) > 0}
        p_new = batch.reality_check(ser, 200, random.Random(trial))["p"]
        p_old = rc_unstudentized(ser, 200, random.Random(trial))
        fire += any(p_new[k] <= 0.05 for k in up_)
        fire_old += any(p_old[k] <= 0.05 for k in up_)
    check(f"size with 6 rarely-traded lopsided series among 20, all pure noise: at most 9% of {trials} batches accept something",
          fire <= 0.09 * trials, f"{fire} of {trials} ({fire / trials:.1%})")
    check("dividing every draw by the full-sample spread instead accepts noise more often, which is why it is not used",
          fire_old > fire, f"{fire_old} of {trials} ({fire_old / trials:.1%})")


# ----------------------------------------------------------------------------- [7] the decision


N_BEFORE, N_NOW, K = 2000, 1440, 50


def routes_from_t(tb: list, ta: list, tw: list) -> tuple[set, set, set]:
    """The three routes worked out from t-statistics alone (before, now, whole sample), with the
    best-of-K points of K independent normal series standing in for the bootstrap."""
    k = len(tb)
    c95, c90 = core.inv_norm(0.95 ** (1 / k)), core.inv_norm(0.90 ** (1 / k))
    r1 = {i for i in range(k) if ta[i] >= c95}
    c2 = [i for i in range(k) if tb[i] >= c90]
    z2 = core.inv_norm(1 - 0.05 / len(c2)) if c2 else math.inf
    r2 = {i for i in c2 if ta[i] >= z2}
    r3 = {i for i in range(k) if tw[i] >= c95 and tb[i] > 0 and ta[i] >= batch.Z_STILL_THERE}
    return r1, r2, r3


def decide_on(cases: dict) -> dict:
    """batch.decide with the three reality checks replaced by numbers set by hand. cases: key ->
    dict(pn, tn: corrected p and t on set A; pb: corrected p before 2021; pa: corrected p on the
    whole sample; un, ub: is the mean positive now / before, default yes)."""
    now = {k: [1.0, 2.0] if c.get("un", True) else [-1.0, -2.0] for k, c in cases.items()}
    before = {k: [1.0, 2.0] if c.get("ub", True) else [-1.0, -2.0] for k, c in cases.items()}
    fakes = iter([{"p": {k: c.get("pn", 1.0) for k, c in cases.items()}, "t": {k: c.get("tn", 0.0) for k, c in cases.items()}, "best": []},
                  {"p": {k: c.get("pb", 1.0) for k, c in cases.items()}, "t": {k: 0.0 for k in cases}, "best": []},
                  {"p": {k: c.get("pa", 1.0) for k, c in cases.items()}, "t": {k: 0.0 for k in cases}, "best": []}])
    orig = batch.reality_check
    batch.reality_check = lambda series, runs, rng: next(fakes)
    try:
        return batch.decide(now, before, 1, random.Random(0))
    finally:
        batch.reality_check = orig


def t_decide() -> None:
    print("[7] the decision's own thresholds, on corrected p-values and t-statistics set by hand")
    d = decide_on({"a": dict(pn=0.05), "b": dict(pn=0.051), "c": dict(pn=0.01, un=False)})
    check("route 1: corrected p 0.050 on set A passes, 0.051 does not, and a negative mean never does",
          d["route1"] == ["a"] and d["passed"] == ["a"])
    d = decide_on({"a": dict(pb=0.10, tn=1.65), "b": dict(pb=0.101, tn=3.0), "c": dict(pb=0.01, tn=3.0, ub=False)})
    check("route 2: corrected p 0.100 before 2021 makes a candidate, 0.101 or a negative mean before does not; one candidate is confirmed at t 1.65",
          d["cand2"] == ["a"] and d["route2"] == ["a"] and close(d["z2"], 1.6449, 1e-3))
    d = decide_on({"a": dict(pb=0.10, tn=1.64)})
    check("route 2: ...and not at t 1.64", d["cand2"] == ["a"] and d["route2"] == [] and d["passed"] == [])
    d = decide_on({"a": dict(pb=0.05, tn=1.97), "b": dict(pb=0.05, tn=1.95)})
    check("route 2: two candidates share the 5%: each needs t 1.96, so 1.97 passes and 1.95 does not",
          d["cand2"] == ["a", "b"] and d["route2"] == ["a"] and close(d["z2"], 1.95996, 1e-4))
    d = decide_on({"a": dict(pa=0.05, tn=1.65), "b": dict(pa=0.051, tn=3.0), "c": dict(pa=0.01, tn=3.0, ub=False),
                   "d": dict(pa=0.01, tn=1.64)})
    check("route 3: corrected p 0.050 on the whole sample with a positive mean before 2021, then t 1.645 on set A; 1.64 is not enough",
          d["cand3"] == ["a", "d"] and d["route3"] == ["a"] and d["passed"] == ["a"])
    import inspect

    import run_batch
    sig = inspect.signature(batch.decide).parameters
    check("the registered thresholds are the ones in the code: 0.05 now, 0.10 before, 0.05 whole, t 1.645, 5,000 redraws, "
          "a quarter of accounts within 120 sessions, $2 a point, eras split at 2021, ES from 2013",
          (sig["a_now"].default, sig["a_before"].default, sig["a_all"].default) == (0.05, 0.10, 0.05)
          and (run_batch.ALPHA_NOW, run_batch.ALPHA_BEFORE, run_batch.ALPHA_ALL) == (0.05, 0.10, 0.05)
          and close(batch.Z_STILL_THERE, 1.6448536, 1e-6) and run_batch.RC_RUNS == 5000
          and (run_batch.BUST_MAX, run_batch.HORIZON, run_batch.MNQ) == (0.25, 120, 2.0)
          and (run_batch.ERA, run_batch.ES_FROM) == (date(2021, 1, 1), date(2013, 1, 1)))
    nq, es = data._new("a", "NQ", 5), data._new("b", "ES", 5)
    trade = lambda gross, pts, unit, day=1: batch.Trade(day=day, k=1, x=2, side=1, pts=pts, gross=gross, twin=0.0, why="time", unit=unit)
    f = run_batch.net_today(0.004, es)
    check("the runner's cost for the older sets: a round trip is 1.00 point on NQ and 0.70 on ES; an ES trade that paid a full one "
          "is charged 0.4% of the day's range, one that left on a target (0.45) 0.45/0.70 of that",
          close(run_batch.round_trip(nq), 1.0) and close(run_batch.round_trip(es), 0.70)
          and close(f(trade(3.0, 2.3, 20.0)), 0.15 - 0.004) and close(f(trade(3.0, 2.55, 20.0)), 0.15 - 0.004 * 0.45 / 0.70))
    ns = types.SimpleNamespace
    d1, d2, d3 = date(2019, 1, 2), date(2019, 1, 3), date(2019, 1, 4)
    check("the runner pools two markets by date: the mean where both traded, the one value where one did",
          run_batch.pooled([ns(date=d1), ns(date=d2)], [1.0, 3.0], [ns(date=d2), ns(date=d3)], [5.0, 7.0]) == ([d1, d2, d3], [1.0, 4.0, 7.0]))
    days_ = [ns(s=ns(ordinal=10)), ns(s=ns(ordinal=11)), ns(s=ns(ordinal=12))]
    check("the runner's daily series: a day's trades are summed, a day without a trade is zero",
          run_batch.per_day([trade(1.0, 1.0, 2.0, 10), trade(3.0, 3.0, 2.0, 10), trade(5.0, 5.0, 2.0, 12)], days_, lambda t: t.pts / t.unit)
          == [2.0, 0.0, 2.5])
    check("short futures days known in advance: an exchange holiday, the Friday after Thanksgiving, 3 July, Christmas Eve; not a plain Wednesday",
          all(run_batch.scheduled_short(x) for x in (date(2024, 1, 15), date(2024, 11, 29), date(2024, 7, 3), date(2024, 12, 24)))
          and not run_batch.scheduled_short(date(2024, 3, 13)))


def t_controls(runs: int) -> None:
    print(f"    the whole decision (three routes) on {runs} pairs of zero-edge walks and {runs} pairs with a planted last-half-hour effect")
    fired = found = 0
    best_t = []
    for r in range(runs):
        for plant in (0.0, 0.03):
            ser = []
            for seed in (500 + r, 900 + r):                 # "before" and "now": two separate walks
                b = walk(300, seed, plant)
                days = batch.build_days(b, FAKE_VIX)
                ser.append({s["key"]: batch.daily(batch.run(b, days, s["fn"]), days, lambda t: t.gross / t.unit)
                            for s in registry.STRATEGIES})
            dec = batch.decide(ser[1], ser[0], 500, random.Random(r))
            if plant:
                found += "gao" in dec["passed"]
            else:
                fired += bool(dec["passed"])
                best_t.append(max(t for t in dec["now"]["t"].values() if t == t))
    check(f"zero edge: some route accepts something in at most 5 of {runs} pairs (expected 1 or 2)", fired <= 5,
          f"fired {fired}; best raw t per walk averaged {statistics.mean(best_t):+.2f}")
    check(f"planted effect: the Gao strategy passes a route in at least {runs - 3} of {runs} pairs", found >= runs - 3, f"found {found}")


def t_power(trials: int, sims: int) -> None:
    """What the decision can see at the real sample sizes: fifty independent daily series, about
    2,000 sessions before 2021 and 1,440 after, one of them given a true Sharpe ratio in each era."""
    print(f"    false alarms and power at the real sample sizes ({K} daily series, {N_BEFORE:,} sessions before 2021, {N_NOW:,} after)")
    wb, wa = math.sqrt(N_BEFORE / (N_BEFORE + N_NOW)), math.sqrt(N_NOW / (N_BEFORE + N_NOW))
    cases = [("pure noise", 0.0, 0.0), ("Sharpe 1.0 in both eras", 1.0, 1.0), ("Sharpe 1.5 in both eras", 1.5, 1.5),
             ("Sharpe 2.0 before 2021, none since", 2.0, 0.0)]
    agree = total = 0
    real = {}
    for label, sb, sn in cases:
        hit = 0
        for trial in range(trials):
            rng = random.Random(7000 + trial)
            before = {i: [rng.gauss(0, 1) for _ in range(N_BEFORE)] for i in range(K)}
            now = {i: [rng.gauss(0, 1) for _ in range(N_NOW)] for i in range(K)}
            before[0] = [x + sb / math.sqrt(252) for x in before[0]]
            now[0] = [x + sn / math.sqrt(252) for x in now[0]]
            dec = batch.decide(now, before, 300, random.Random(trial))
            r1, r2, r3 = routes_from_t([batch.tstat(before[i])["t"] for i in range(K)], [batch.tstat(now[i])["t"] for i in range(K)],
                                       [batch.tstat(before[i] + now[i])["t"] for i in range(K)])
            got = bool(dec["passed"]) if label == "pure noise" else 0 in dec["passed"]
            fast = bool(r1 | r2 | r3) if label == "pure noise" else 0 in (r1 | r2 | r3)
            hit += got
            total += 1
            agree += got == fast
        real[label] = hit
    check(f"the routes worked out from the t-statistics alone give the same answer as batch.decide in at least 90% of {total} trials",
          agree >= 0.9 * total, f"{agree} of {total}; batch.decide passed " + ", ".join(f"{v}/{trials} ({k})" for k, v in real.items()))

    def sim(sb: float, sn: float, seed: int) -> dict:
        rng = random.Random(seed)
        mb, mn = sb * math.sqrt(N_BEFORE / 252), sn * math.sqrt(N_NOW / 252)
        out = {"any": 0, "edge": 0, "r1": 0, "r2": 0, "r3": 0}
        for _ in range(sims):
            tb = [rng.gauss(0, 1) for _ in range(K)]
            ta = [rng.gauss(0, 1) for _ in range(K)]
            tb[0] += mb
            ta[0] += mn
            r1, r2, r3 = routes_from_t(tb, ta, [wb * x + wa * y for x, y in zip(tb, ta)])
            out["any"] += bool(r1 | r2 | r3)
            out["edge"] += 0 in (r1 | r2 | r3)
            out["r1"] += (0 in r1) if (sb or sn) else bool(r1)
            out["r2"] += (0 in r2) if (sb or sn) else bool(r2)
            out["r3"] += (0 in r3) if (sb or sn) else bool(r3)
        return {k: v / sims for k, v in out.items()}

    print(f"    from the t-statistics, {sims:,} simulated batches a line:")
    null = sim(0.0, 0.0, 1)
    print(f"      pure noise: something passes in {null['any']:.1%}   (route 1 {null['r1']:.1%}, route 2 {null['r2']:.1%}, route 3 {null['r3']:.1%})")
    table = {}
    for label, pairs in (("the same edge before and after 2021", [(s, s) for s in (0.5, 0.75, 1.0, 1.5, 2.0)]),
                         ("an edge that exists only since 2021", [(0.0, s) for s in (1.0, 1.5, 2.0)]),
                         ("an edge that died after 2020", [(s, 0.0) for s in (1.0, 2.0, 3.0)])):
        for sb, sn in pairs:
            r = sim(sb, sn, 2)
            table[(sb, sn)] = r["edge"]
            print(f"      {label}, Sharpe {max(sb, sn):.2f}: it passes in {r['edge']:.1%}   (route 1 {r['r1']:.1%}, route 2 {r['r2']:.1%}, route 3 {r['r3']:.1%})")
    check("pure noise gets through some route in at most 10% of batches", null["any"] <= 0.10, f"{null['any']:.1%}")
    check("an edge that died after 2020 gets through in at most 8% of batches, however strong it was", max(table[(s, 0.0)] for s in (1.0, 2.0, 3.0)) <= 0.08,
          ", ".join(f"{table[(s, 0.0)]:.1%}" for s in (1.0, 2.0, 3.0)))
    check("a Sharpe ratio of 1.5 in both eras is found in at least 90% of batches, and power rises with the Sharpe ratio",
          table[(1.5, 1.5)] >= 0.9 and table[(0.5, 0.5)] < table[(1.0, 1.0)] < table[(1.5, 1.5)] <= table[(2.0, 2.0)],
          ", ".join(f"{s}: {table[(s, s)]:.0%}" for s in (0.5, 0.75, 1.0, 1.5, 2.0)))


# ----------------------------------------------------------------------------- [8] the suite against itself


def t_mutants(b: data.Bars, days: list, dv: list) -> None:
    print("[8] the suite against itself: each deliberate bug must make a check fail")
    second = lambda: t_second(b, days, dv)

    def swapped(keys, wrap):
        """Run the second-implementation checks with some registered functions replaced."""
        saved = {s["key"]: s["fn"] for s in registry.STRATEGIES if s["key"] in keys}
        for s in registry.STRATEGIES:
            if s["key"] in keys:
                s["fn"] = wrap(s["fn"])
        try:
            return failures(second)
        finally:
            for s in registry.STRATEGIES:
                if s["key"] in saved:
                    s["fn"] = saved[s["key"]]

    orig = st.seen
    st.seen = lambda bars, day, minute: (lambda j, c: (None, None) if j is None else (j, bars.o[j + 1]))(*orig(bars, day, minute))
    try:
        n = failures(second)
    finally:
        st.seen = orig
    check("every decision reads the open of its own entry bar instead of the close before it", n > 0, f"{n} checks fail")

    orig = batch.bisect
    batch.bisect = types.SimpleNamespace(bisect_left=bisect.bisect_right)
    try:
        n = failures(lambda: t_days(b, days))
    finally:
        batch.bisect = orig
    check("the VIX flag includes today's own close", n > 0, f"{n} checks fail")

    mid = lambda inner: lambda day, bars: [Plan(p.sig, p.k, p.x, p.side, stop_px=p.stop_px + p.side * 2.0) for p in inner(day, bars)]
    n = swapped({"orb30", "orb60"}, mid)
    check("the opening-range stop is two points inside the far side of the range", n > 0, f"{n} checks fail")
    n = swapped({"orb5_10r"}, lambda inner: lambda day, bars: [Plan(p.sig, p.k, p.x, p.side, stop_px=p.stop_px, target_r=5.0)
                                                               for p in inner(day, bars)])
    check("the first-candle target is 5R instead of 10R", n > 0, f"{n} checks fail")
    early = lambda inner: lambda day, bars: [Plan(p.sig - 1, p.k, p.x, p.side) for p in inner(day, bars)]
    n = swapped({"rod", "first60_hold", "lunch_long"}, early)
    check("a plan declares its decision bar one bar earlier than the bar it read", n > 0, f"{n} checks fail")

    def unmerged(inner):
        def f(day, bars):
            out = []
            for p in inner(day, bars):                       # cut every held position back into half hours
                for k in range(p.k, p.x, 6):
                    out.append(Plan(k - 1, k, k + 6, p.side))
            return out
        return f
    n = swapped({"same_half_hour"}, unmerged)
    check("same_half_hour closes and reopens at every half hour", n > 0, f"{n} checks fail")

    orig = batch.execute

    def free_shorts(bars, day, plan):
        t = orig(bars, day, plan)
        if plan.side == -1:
            t.pts += 2 * bars.tick + bars.commission_pts
        return t
    batch.execute = free_shorts
    try:
        n = failures(t_fills)
    finally:
        batch.execute = orig
    check("short trades pay no slippage and no commission", n > 0, f"{n} checks fail")

    orig = batch.reality_check

    def uncentred(series, runs, rng):
        n_ = len(next(iter(series.values())))
        stats_ = {k: batch.tstat(v) for k, v in series.items()}
        best = []
        for _ in range(runs):
            pick = itemgetter(*[rng.randrange(n_) for _ in range(n_)])
            best.append(max((sum(pick(series[k])) / (s["sd"] * math.sqrt(n_)) for k, s in stats_.items() if s["sd"] and s["sd"] > 0),
                            default=-math.inf))
        best.sort()
        return {"best": best, "p": {k: 1.0 if s["t"] != s["t"] else (1 + sum(1 for x in best if x >= s["t"])) / (1 + runs)
                                    for k, s in stats_.items()}, "t": {k: s["t"] for k, s in stats_.items()}}
    batch.reality_check = uncentred
    try:
        n = failures(lambda: t_stats(False))
    finally:
        batch.reality_check = orig
    check("the reality check redraws the raw series without centring them", n > 0, f"{n} checks fail")

    def idle_days_centred(series, runs, rng):
        """The studentized check, but with every day shifted by the full-series mean, idle days too."""
        n_ = len(next(iter(series.values())))
        stats_ = {k: batch.tstat(v) for k, v in series.items()}
        cols = []
        for k, s in stats_.items():
            if s["sd"] and s["sd"] > 0:
                c = [x - s["mean"] for x in series[k]]
                cols.append((c, [x * x for x in c]))
        best = []
        for _ in range(runs):
            pick = itemgetter(*[rng.randrange(n_) for _ in range(n_)])
            top = -math.inf
            for c, c2 in cols:
                s1, s2 = sum(pick(c)), sum(pick(c2))
                var = (s2 - s1 * s1 / n_) / (n_ - 1)
                if var > 1e-12 * s2 / n_:
                    top = max(top, s1 / math.sqrt(var * n_))
            best.append(top)
        best.sort()
        return {"best": best, "p": {k: 1.0 if s["t"] != s["t"] else (1 + sum(1 for x in best if x >= s["t"])) / (1 + runs)
                                    for k, s in stats_.items()}, "t": {k: s["t"] for k, s in stats_.items()}}
    batch.reality_check = idle_days_centred
    try:
        n = failures(lambda: t_stats(False))
    finally:
        batch.reality_check = orig
    check("the reality check shifts the days a strategy did not trade as well as the days it did", n > 0, f"{n} checks fail")

    orig = batch.decide
    batch.decide = lambda now, before, runs, rng, a_now=0.05, a_before=0.10, a_all=0.05: orig(now, before, runs, rng, 0.10, a_before, a_all)
    try:
        n = failures(t_decide)
    finally:
        batch.decide = orig
    check("route 1 accepts a corrected p of 0.10", n > 0, f"{n} checks fail")
    orig = batch.Z_STILL_THERE
    batch.Z_STILL_THERE = 0.0
    try:
        n = failures(t_decide)
    finally:
        batch.Z_STILL_THERE = orig
    check("route 3 asks only for a positive t on set A (the hole the review found)", n > 0, f"{n} checks fail")


def main() -> int:
    full = "--fast" not in sys.argv
    t_calendar()
    b = walk(300, 11, gap=2)
    days = batch.build_days(b)
    dv = batch.build_days(b, FAKE_VIX)
    t_days(b, days)
    t_fills()
    t_second(b, days, dv)
    t_far(b)
    t_near(full)
    t_damaged(b)
    t_stats(full)
    t_decide()
    if full:
        t_controls(20)
        t_power(25, 40000)
    t_mutants(b, days, dv)
    print("\n" + ("all checks passed" if OK else "SOMETHING FAILED"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
