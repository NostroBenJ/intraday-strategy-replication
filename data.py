"""Bar series, sessions and the indicator cache. Stdlib only.

Three series feed the study (PREREGISTRATION.md, "Data"):

  NQ-NT   NinjaTrader's 1-minute NQ dump the FTM bot is validated on, 2021-01-04 .. 2026-09-25.
          Back-adjusted by NinjaTrader, so it has no roll jumps. Aggregated here to 5 minutes.
  NQ-LSE  the LSE vendor's 5-minute NQ file, used for 2016-07-01 .. 2020-12-31 only. It is not
          roll-adjusted and around each quarterly roll it flips between the two contracts bar by
          bar, so every session from the Thursday eight days before expiry through expiry Friday
          is dropped (roll_window_days).
  ES      Databento per-contract bars, back-adjusted by prep_es.py. Complete from 2013; the file
          starts in 2010 but 2010-2012 is mostly holes, which the session rules below reject.

Times: a bar is stamped at its open, in New York wall-clock minutes. Nothing here ever compares a
bar to "now"; a bar is used only after its close (core.py).
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import core

NY = ZoneInfo("America/New_York")
HERE = Path(__file__).resolve().parent
NT_1M = Path(r"C:\Users\jontr\dev\ftm-port\data\nq_1m_eth_nt.csv")
LSE_NQ_5M = Path(r"C:\Users\jontr\Downloads\quantdesk\nq_f_5m_lse.csv")
TA = Path(r"C:\Users\jontr\Downloads\ta_setups\data")     # built by ta_setups/prep_es.py
ES_5M_ADJ = TA / "es_5m_adj.csv"
ES_1M_RTH_ADJ = TA / "es_1m_rth_adj.csv"

# micro contracts: tick, $ per point, commission in points ($1.00 round trip, as in orb_nq)
CONTRACT = {"NQ": (0.25, 2.0, 0.50), "ES": (0.25, 5.0, 0.20)}

RTH_OPEN, RTH_CLOSE = 570, 960            # 09:30, 16:00 ET in minutes of the day
LAST_ENTRY_MIN = 900                      # no position opens after the 15:00 bar
JUMP = 0.008                              # a bar-to-bar jump this large inside RTH drops the day
WARM_BARS = 1500                          # bars of history every session needs behind it
COMPLETE = 0.96                           # share of the session's bars that must exist (75 of 78)


@dataclass
class Session:
    day: date
    ordinal: int              # date ordinal, the cluster id
    first_sig: int            # index of the 09:30 bar: the first bar that may raise a signal
    last_sig: int             # last bar whose close is at or before 15:00
    last_entry: int           # last bar on which a position may open (opens by 15:00)
    exit_i: int               # the time-exit bar; positions close at its open


@dataclass
class Bars:
    name: str
    tf: int                   # minutes per bar
    tick: float
    point_value: float
    commission_pts: float
    t: list[int] = field(default_factory=list)      # bar open, minutes since 0001-01-01 (ET clock)
    mod: list[int] = field(default_factory=list)    # minute of the ET day
    o: list[float] = field(default_factory=list)
    h: list[float] = field(default_factory=list)
    l: list[float] = field(default_factory=list)
    c: list[float] = field(default_factory=list)
    v: list[float] = field(default_factory=list)
    sessions: list[Session] = field(default_factory=list)
    dropped: dict = field(default_factory=dict)
    dropped_days: dict = field(default_factory=dict)   # reason -> the dates refused for it
    cache: dict = field(default_factory=dict)
    # 1-minute bars inside each bar, regular session only: (start index per bar [len + 1], o, h, l).
    # Used for one thing: which of two prices a bar reached first (core.first_touch).
    fine: tuple | None = None
    span_scale: float = 1.0   # how much longer 1,500 bars take than on the 24-hour chart

    def __len__(self) -> int:
        return len(self.t)

    def add(self, t: int, o: float, h: float, l: float, c: float, v: float) -> None:
        self.t.append(t)
        self.mod.append(t % 1440)
        self.o.append(o)
        self.h.append(h)
        self.l.append(l)
        self.c.append(c)
        self.v.append(v)

    def day_of(self, i: int) -> date:
        return date.fromordinal(self.t[i] // 1440)


def exit_minute(tf: int) -> int:
    """Open of the last bar that starts at or before 15:55 on this timeframe's grid."""
    return RTH_OPEN + ((955 - RTH_OPEN) // tf) * tf


# ----------------------------------------------------------------------------- loading


def _new(name: str, sym: str, tf: int) -> Bars:
    tick, pv, comm = CONTRACT[sym]
    return Bars(name=name, tf=tf, tick=tick, point_value=pv, commission_pts=comm)


def _aggregate(rows, name: str, sym: str, tf: int) -> Bars:
    """rows: iterable of (t_open in ET minutes, o, h, l, c, v), in time order, any finer grid that
    divides tf. Buckets sit on the clock grid, so 09:30 is always a bar boundary."""
    bars = _new(name, sym, tf)
    cur = None
    prev_t = None
    for t, o, h, l, c, v in rows:
        if prev_t is not None and t <= prev_t:
            raise ValueError(f"{name}: rows out of order or duplicated at minute {t}")
        prev_t = t
        b = t - t % tf
        if cur is None or b != cur[0]:
            if cur is not None:
                bars.add(*cur)
            cur = [b, o, h, l, c, v]
        else:
            if h > cur[2]:
                cur[2] = h
            if l < cur[3]:
                cur[3] = l
            cur[4] = c
            cur[5] += v
    if cur is not None:
        bars.add(*cur)
    return bars


def _nt_rows(path: Path):
    """NinjaTrader stamps a bar at its CLOSE in the platform's (Eastern) clock."""
    with open(path, newline="") as f:
        rd = csv.reader(f)
        next(rd)
        memo: dict[str, int] = {}
        for r in rd:
            s = r[0]
            d = memo.get(s[:10])
            if d is None:
                d = memo[s[:10]] = date(int(s[:4]), int(s[5:7]), int(s[8:10])).toordinal() * 1440
            t = d + int(s[11:13]) * 60 + int(s[14:16]) - 1
            yield t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])


def _utc_rows(path: Path):
    """LSE and Databento files: ISO UTC stamp at the bar's open. The UTC offset is looked up once
    per UTC date at noon; clock changes happen at 06:00-07:00 UTC on a Sunday, before the market
    reopens, so every bar that exists on that date is already on the new offset."""
    with open(path, newline="") as f:
        rd = csv.reader(f)
        next(rd)
        memo: dict[str, int] = {}
        for r in rd:
            s = r[0]
            base = memo.get(s[:10])
            if base is None:
                y, m, d = int(s[:4]), int(s[5:7]), int(s[8:10])
                off = datetime(y, m, d, 12, tzinfo=timezone.utc).astimezone(NY).utcoffset()
                base = memo[s[:10]] = date(y, m, d).toordinal() * 1440 + int(off.total_seconds() // 60)
            t = base + int(s[11:13]) * 60 + int(s[14:16])
            yield t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])


def attach_fine(bars: Bars, minutes) -> None:
    """minutes: (t, o, h, l) 1-minute bars in time order. Files each under the bar that holds it."""
    fs = [0] * (len(bars) + 1)
    fo: list[float] = []
    fh: list[float] = []
    fl: list[float] = []
    q, n, tf = 0, len(minutes), bars.tf
    for i, t in enumerate(bars.t):
        while q < n and minutes[q][0] < t:
            q += 1
        fs[i] = len(fo)
        while q < n and minutes[q][0] < t + tf:
            m = minutes[q]
            fo.append(m[1])
            fh.append(m[2])
            fl.append(m[3])
            q += 1
    fs[len(bars)] = len(fo)
    bars.fine = (fs, fo, fh, fl)


def _rth(t: int) -> bool:
    return RTH_OPEN <= t % 1440 < RTH_CLOSE


def load_nq_nt(tf: int = 5) -> Bars:
    minutes: list[tuple] = []

    def rows():
        for r in _nt_rows(NT_1M):
            if _rth(r[0]):
                minutes.append(r[:4])
            yield r

    bars = _aggregate(rows(), "NQ-NT", "NQ", tf)
    if tf > 1:
        attach_fine(bars, minutes)
    return bars


def load_nq_lse(tf: int = 5) -> Bars:
    return _aggregate(_utc_rows(LSE_NQ_5M), "NQ-LSE", "NQ", tf)          # no 1-minute history


def load_es(tf: int = 5) -> Bars:
    bars = _aggregate(_utc_rows(ES_5M_ADJ), "ES", "ES", tf)
    if ES_1M_RTH_ADJ.exists():
        attach_fine(bars, [r[:4] for r in _utc_rows(ES_1M_RTH_ADJ) if _rth(r[0])])
    return bars


# ----------------------------------------------------------------------------- sessions


def third_friday(y: int, m: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(4 - d.weekday()) % 7)
    return d + timedelta(days=14)


def roll_window_days(first_year: int, last_year: int, after: int = 0) -> set[date]:
    """Every date from the Thursday eight days before a quarterly expiry through expiry Friday,
    plus `after` calendar days beyond it.
    ASSUMPTION (data): the LSE file's roll and its bar-by-bar flipping between the two contracts
    fall inside this window. Measured: 2017-2019 it steps at 00:00 UTC on the Friday a week before
    expiry and flips for up to four sessions; 2021-2026 it steps between the Sunday open and
    Tuesday 00:00 UTC of expiry week (compared bar for bar with the NinjaTrader series).
    The 24-hour chart has forgotten the step by the Monday after expiry (two sessions is 552 bars).
    The regular-session chart has only 156 bars in those two sessions, so it gets `after` = 5:
    it resumes on the Thursday."""
    out: set[date] = set()
    for y in range(first_year, last_year + 1):
        for m in (3, 6, 9, 12):
            ex = third_friday(y, m)
            for k in range(-after, 9):
                out.add(ex - timedelta(days=k))
    return out


def build_sessions(bars: Bars, start: date, end: date, excluded: set[date] | None = None,
                   to_the_close: bool = False) -> None:
    """Fill bars.sessions with the usable regular sessions in [start, end] and bars.dropped with
    the reason every other day was refused. Rules (pre-registered):
      * a weekday with at least 96% of its bars (75 of 78 at 5 minutes), including the 09:30 bar
        and the time-exit bar
      * no jump above 0.8% between consecutive bars inside the session
      * 1,500 bars of history behind it, spanning no more than the calendar time those bars
        normally take plus holidays - so no indicator is read across a hole in the file
      * not in `excluded` (the LSE roll windows)

    `to_the_close` is the batch study's session: a position may open on any bar up to 15:55 and
    everything is closed at the open of the 16:00 bar, which must exist (futures trade on to
    17:00). Without it the session is ta_setups': no entry after 15:00, flat at 15:55."""
    tf = bars.tf
    expected = (RTH_CLOSE - RTH_OPEN) // tf
    need = math.ceil(COMPLETE * expected)
    x_min = exit_minute(tf)
    max_span = max(5, 12 * tf / 5) * 1440 * bars.span_scale        # minutes
    t, mod, o, c = bars.t, bars.mod, bars.o, bars.c
    drops: dict[str, int] = {}
    drop_days: dict[str, list[date]] = {}
    sessions: list[Session] = []
    n = len(t)
    i = 0
    lo, hi = start.toordinal(), end.toordinal()
    while i < n:
        if not RTH_OPEN <= mod[i] < RTH_CLOSE:
            i += 1
            continue
        d_ord = t[i] // 1440
        j = i
        while j < n and t[j] // 1440 == d_ord and RTH_OPEN <= mod[j] < RTH_CLOSE:
            j += 1
        first, last = i, j - 1
        i = j
        if not lo <= d_ord <= hi:
            continue
        d = date.fromordinal(d_ord)
        why = None
        if d.weekday() >= 5:
            why = "weekend"
        elif excluded is not None and d in excluded:
            why = "roll window"
        elif last - first + 1 < need or mod[first] != RTH_OPEN:
            why = "incomplete session"
        elif first < WARM_BARS or t[first] - t[first - WARM_BARS] > max_span:
            why = "history has a hole or is too short"
        elif any(abs(o[k] / c[k - 1] - 1.0) > JUMP for k in range(first + 1, last + 1)):
            why = "jump inside the session"
        if to_the_close:
            nxt = last + 1
            exit_i = nxt if nxt < n and mod[nxt] == RTH_CLOSE and t[nxt] // 1440 == d_ord else None
        else:
            exit_i = next((k for k in range(last, first, -1) if mod[k] == x_min), None)
        if why is None and exit_i is None:
            why = "no time-exit bar"
        if why is not None:
            drops[why] = drops.get(why, 0) + 1
            drop_days.setdefault(why, []).append(d)
            continue
        cutoff = RTH_CLOSE - tf if to_the_close else LAST_ENTRY_MIN
        last_sig = max(k for k in range(first, exit_i) if mod[k] + tf <= cutoff)
        last_entry = max(k for k in range(first, exit_i) if mod[k] <= cutoff)
        sessions.append(Session(day=d, ordinal=d_ord, first_sig=first, last_sig=last_sig,
                                last_entry=last_entry, exit_i=exit_i))
    bars.sessions = sessions
    bars.dropped = drops
    bars.dropped_days = drop_days


# ----------------------------------------------------------------------------- indicators


def rth_only(src: Bars) -> Bars:
    """The regular-session chart: the same series with every bar outside 09:30-16:00 on a weekday
    removed, as a series of its own. On it "the previous bar" of a 09:30 bar is yesterday's 15:55
    bar, the first true range of the day holds the overnight gap, and every lookback counts
    regular-session bars - which is what an RTH-only chart shows. Sessions are not carried over;
    call build_sessions on the result."""
    b = Bars(name=src.name + "-rth", tf=src.tf, tick=src.tick, point_value=src.point_value,
             commission_pts=src.commission_pts)
    keep = [i for i in range(len(src)) if RTH_OPEN <= src.mod[i] < RTH_CLOSE
            and date.fromordinal(src.t[i] // 1440).weekday() < 5]
    for i in keep:
        b.add(src.t[i], src.o[i], src.h[i], src.l[i], src.c[i], src.v[i])
    if src.fine is not None and keep:
        fs, fo, fh, fl = src.fine
        # 1-minute bars exist only inside regular-session bars, so each kept bar's block still
        # ends where the next kept bar's begins
        b.fine = ([fs[i] for i in keep] + [fs[keep[-1] + 1]], fo, fh, fl)
    # 1,500 regular-session bars take 276/78 times the calendar time 1,500 24-hour bars do
    b.span_scale = 276.0 / 78.0
    return b


def col(bars: Bars, kind: str, n: int) -> list[float]:
    """A cached indicator column over every bar of the series given.
    kind: ema | tema | hma | wma | atr | adx | pdi | mdi."""
    key = (kind, n)
    got = bars.cache.get(key)
    if got is not None:
        return got
    h, l, c = bars.h, bars.l, bars.c
    if kind in core.MOVING_AVERAGES:
        out = core.MOVING_AVERAGES[kind](c, n)
    elif kind == "atr":
        out = core.atr(h, l, c, n)
    elif kind in ("adx", "pdi", "mdi"):
        a, p, m = core.adx(h, l, c, n)
        bars.cache[("adx", n)], bars.cache[("pdi", n)], bars.cache[("mdi", n)] = a, p, m
        return bars.cache[key]
    else:
        raise KeyError(kind)
    bars.cache[key] = out
    return out


def build_indicators(bars: Bars, spec: dict) -> dict:
    """The indicator columns one variant needs, computed on `bars`. spec = {setup, params, exit}.
    (A variant's "basis" and "tf" choose WHICH series it runs on; that is the caller's job.)"""
    p, ex, name = spec["params"], spec["exit"], spec["setup"]
    ind: dict = {"atr": col(bars, "atr", 14)}
    if name in ("ribbon_align", "slope_turn"):
        lines = [col(bars, p["kind"], n) for n in p["lengths"]]
        ind["ribbon"] = lines
        if ex.get("flag"):
            key = ("state", name, p["kind"], tuple(p["lengths"]))
            if key not in bars.cache:
                if name == "ribbon_align":
                    bars.cache[key] = [core.line_order([ln[i] for ln in lines]) for i in range(len(bars))]
                else:
                    bars.cache[key] = [0] + [core.slope_state(lines, i) for i in range(1, len(bars))]
            ind["state"] = bars.cache[key]
    elif name == "ema_pullback":
        ind["touch"] = col(bars, "ema", p["touch"])
        if p["trend"] == "adx":
            ind["adx"] = col(bars, "adx", 14)
            ind["pdi"] = col(bars, "pdi", 14)
            ind["mdi"] = col(bars, "mdi", 14)
        else:
            ind["fast"] = col(bars, "ema", p["fast"])
            ind["slow"] = col(bars, "ema", p["slow"])
    if ex.get("trend"):
        ind["trend_ema"] = col(bars, "ema", ex.get("trend_len", 200))
    return ind


def clip(bars: Bars, last_day: date) -> Bars:
    """Cut the series after `last_day` (New York date of the bar's open), in place. The search
    uses this so that nothing after its cut-off date is even in memory."""
    limit = (last_day.toordinal() + 1) * 1440
    n = next((i for i, t in enumerate(bars.t) if t >= limit), len(bars))
    for name in ("t", "mod", "o", "h", "l", "c", "v"):
        del getattr(bars, name)[n:]
    if bars.fine is not None:
        fs, fo, fh, fl = bars.fine
        bars.fine = (fs[:n + 1], fo, fh, fl)
    bars.cache.clear()
    bars.sessions = [s for s in bars.sessions if s.exit_i < n]
    return bars


def run(bars: Bars, spec: dict, sessions: list[Session] | None = None, exit_: dict | None = None) -> list[core.Trade]:
    """Simulate one variant over bars.sessions (or the sessions given), with its own exit or the
    one passed in."""
    use = spec if exit_ is None else {**spec, "exit": exit_}
    return core.simulate(bars, bars.sessions if sessions is None else sessions, core.SETUPS[spec["setup"]],
                         spec["params"], build_indicators(bars, use), use["exit"])


def idle_priority() -> None:
    """IDLE priority: this PC is traded on. The handle must be typed; untyped, ctypes passes the
    pseudo-handle as a 32-bit int and SetPriorityClass fails silently (flowbot/archive.py)."""
    import ctypes
    try:
        k = ctypes.windll.kernel32
    except AttributeError:
        return
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k.GetPriorityClass.argtypes = [ctypes.c_void_p]
    h = k.GetCurrentProcess()
    if not k.SetPriorityClass(h, 0x40) or k.GetPriorityClass(h) != 0x40:
        raise OSError("could not set IDLE priority")
