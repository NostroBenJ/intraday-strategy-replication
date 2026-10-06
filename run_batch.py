"""Run the whole batch.

    py -3.14 run_batch.py          -> results/batch.txt, results/batch.json

Rules, routes and gates are in PREREGISTRATION.md. Run verify.py first. Stdlib only; the process
drops itself to IDLE priority.
"""
from __future__ import annotations

import csv
import json
import math
import random
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import batch
import core
import data
import registry
import strategies as st

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
FTM = Path(r"C:\Users\jontr\dev\ftm-port\data\reference_ftm_trades.csv")
SEED = 20261001
RC_RUNS = 5000
ERA = date(2021, 1, 1)
ES_FROM = date(2013, 1, 1)   # the ES file is complete from 2013; the scattered sessions before it are not used
ALPHA_NOW = 0.05             # route 1: corrected p on NQ 2021-2026
ALPHA_BEFORE = 0.10          # route 2: corrected p on the data before 2021, then confirmation
ALPHA_ALL = 0.05             # route 3: corrected p on the whole sample, then still there on NQ 2021-2026
MNQ = 2.0                    # dollars a point
BUST_MAX, HORIZON = 0.25, 120
DAILY_LIMIT = 1200.0         # the account's daily loss limit, counted on closed results only

_lines: list[str] = []


def say(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def load():
    vix = batch.load_vix()
    nt = data.load_nq_nt()
    data.build_sessions(nt, ERA, date(2026, 12, 31), to_the_close=True)
    lse = data.clip(data.load_nq_lse(), date(2020, 12, 31))
    data.build_sessions(lse, date(2016, 7, 1), date(2020, 12, 31), data.roll_window_days(2016, 2020), to_the_close=True)
    es = data.load_es()
    data.build_sessions(es, ES_FROM, date(2026, 12, 31), to_the_close=True)
    out = {}
    for name, bars in (("NQ 2021-26", nt), ("NQ 2016-20", lse), ("ES", es)):
        out[name] = (bars, batch.build_days(bars, vix))
    return out


def load_bot() -> dict:
    """The bot's own daily result in points, by entry date. Read before anything is computed, so a
    problem with the file stops the run before a result exists."""
    ftm = defaultdict(float)
    with open(FTM, newline="") as f:
        for row in csv.DictReader(f):
            ftm[datetime.strptime(row["entry_time"][:10], "%Y-%m-%d").date()] += float(row["points"])
    return ftm


def split(days, lo: date | None, hi: date | None):
    return [d for d in days if d.datr is not None and (lo is None or d.date >= lo) and (hi is None or d.date < hi)]


def per_day(trades, days, value) -> list[float]:
    """One number per session of `days`, in order: the day's total, zero when nothing traded."""
    tot: dict[int, float] = {}
    for t in trades:
        tot[t.day] = tot.get(t.day, 0.0) + value(t)
    return [tot.get(d.s.ordinal, 0.0) for d in days]


def round_trip(bars) -> float:
    """A market order in and a market order out, in points: two ticks and the commission."""
    return bars.commission_pts + 2 * bars.tick


def net_today(kappa: float, bars):
    """A trade's result in DATR units when a standard round trip is charged `kappa` of the day's
    range instead of the instrument's own ticks. A trade that paid less than a standard round trip
    in its own points (a target has no exit slippage) is charged the same fraction of kappa."""
    rt = round_trip(bars)
    return lambda t: t.gross / t.unit - kappa * (t.gross - t.pts) / rt


def pooled(days_c, xs_c, days_d, xs_d) -> tuple[list, list]:
    """Two markets' daily series as one: the mean of the markets trading each calendar date.
    -> (dates in order, one value per date)"""
    by: dict[date, list[float]] = defaultdict(list)
    for day, x in zip(days_c, xs_c):
        by[day.date].append(x)
    for day, x in zip(days_d, xs_d):
        by[day.date].append(x)
    dates = sorted(by)
    return dates, [sum(by[d]) / len(by[d]) for d in dates]


def scheduled_short(d: date) -> bool:
    """A day the futures session is short for a reason known in advance: an exchange holiday, the
    Friday after Thanksgiving, 3 July, Christmas Eve."""
    return (not batch.is_trading_day(d) or (d.month, d.day) in ((12, 24), (7, 3))
            or d == batch._nth(d.year, 11, 3, 4) + timedelta(days=1))


def skill(trades) -> dict:
    """The direction call against its coin-flip twin, drift removed, one cluster per session.
    Meaningless for a strategy that is always on one side (it is then exactly zero)."""
    if len(trades) < 2:
        return {"mean": math.nan, "t": math.nan}
    L = [t.side * (t.gross - t.twin) / 2.0 / t.unit for t in trades]
    lbar = sum(L) / len(L)
    s = core.cluster_stats([t.side * (x - lbar) for t, x in zip(trades, L)], [t.day for t in trades])
    return {"mean": s["mean"], "t": s["t"]}


def body() -> dict:
    t0 = time.time()
    ftm = load_bot()
    sets = load()
    nq_bars, nq_all = sets["NQ 2021-26"]
    lse_bars, lse_all = sets["NQ 2016-20"]
    es_bars, es_all = sets["ES"]
    A = split(nq_all, None, None)                       # NQ 2021-2026: the instrument and era the bot trades
    B = split(es_all, ERA, None)                        # ES 2021-2026
    C = split(lse_all, None, None)                      # NQ 2016-2020
    D = split(es_all, None, ERA)                        # ES before 2021

    # Costs. Set A pays its real ticks and commission. A tick is a far larger share of the day's range
    # in the older and the smaller-ranged sets, so B, C and D are charged what set A pays instead: the
    # same share of the day's range as a round trip costs on a median day of set A.
    med = lambda days: statistics.median(d.datr for d in days)
    kappa = round_trip(nq_bars) / med(A)
    net = lambda t: t.pts / t.unit
    gross = lambda t: t.gross / t.unit
    net_es, net_lse = net_today(kappa, es_bars), net_today(kappa, lse_bars)

    say("PUBLISHED INTRADAY STRATEGIES ON NQ AND ES - THE BATCH")
    say(f"{len(registry.STRATEGIES)} strategies. Daily result in DATR units (points / the 20-day mean regular-session range), net of costs.")
    for lab, days in (("A  NQ 2021-2026", A), ("B  ES 2021-2026", B), ("C  NQ 2016-2020", C), ("D  ES 2013-2020", D)):
        say(f"  {lab:<16} {len(days):>5,} sessions  {days[0].date} .. {days[-1].date}")
    refused = {}
    for lab, bars in (("NQ 2021-2026", nq_bars), ("NQ 2016-2020", lse_bars), ("ES", es_bars)):
        say(f"  days refused, {lab}: " + (", ".join(f"{v} {k}" for k, v in sorted(bars.dropped.items())) or "none"))
        odd = sorted((d, why) for why, ds in bars.dropped_days.items() if why not in ("weekend", "roll window")
                     for d in ds if not scheduled_short(d))
        refused[lab] = {why: [str(d) for d in ds] for why, ds in bars.dropped_days.items()}
        if odd:
            say(f"    of these, on an ordinary full trading day ({len(odd)}): "
                + "; ".join(f"{d} {why}" for d, why in odd[:60]) + (f"; and {len(odd) - 60} more" if len(odd) > 60 else ""))
    say()
    say(f"COSTS: a round trip on set A is {round_trip(nq_bars):.2f} points, {kappa:.2%} of its median day's range ({med(A):.0f} points).")
    say("  At their own ticks the other sets would pay " + ", ".join(
        f"{round_trip(b_) / med(d_):.2%} ({lab}, median range {med(d_):.0f})"
        for lab, b_, d_ in (("ES 2021-2026", es_bars, B), ("NQ 2016-2020", lse_bars, C), ("ES 2013-2020", es_bars, D))) + ".")
    say(f"  Sets B, C and D are charged {kappa:.2%} of the day's range a round trip instead, so that every era is judged at today's cost.")
    say()

    rows = []
    serA, serPre = {}, {}
    pre_dates: list = []
    posA = {d.s.ordinal: i for i, d in enumerate(A)}
    for s in registry.STRATEGIES:
        fn = s["fn"]
        a_tr = batch.run(nq_bars, A, fn)
        b_tr = batch.run(es_bars, B, fn)
        c_tr = batch.run(lse_bars, C, fn)
        d_tr = batch.run(es_bars, D, fn)
        a_net = per_day(a_tr, A, net)
        c_net, d_net = per_day(c_tr, C, net_lse), per_day(d_tr, D, net_es)
        pre_dates, pre = pooled(C, c_net, D, d_net)      # before 2021: one number per calendar date
        dollars = [0.0] * len(A)
        for t in a_tr:
            dollars[posA[t.day]] += t.pts * MNQ
        serA[s["key"]], serPre[s["key"]] = a_net, pre
        rows.append({"key": s["key"], "family": s["family"], "rule": s["rule"], "source": s["source"],
                     "trades_a": len(a_tr), "per_day": len(a_tr) / len(A),
                     "A": batch.tstat(a_net), "A_gross": batch.tstat(per_day(a_tr, A, gross)),
                     "B": batch.tstat(per_day(b_tr, B, net_es)), "B_gross": batch.tstat(per_day(b_tr, B, gross)),
                     "C": batch.tstat(c_net), "D": batch.tstat(d_net), "pre": batch.tstat(pre),
                     "all": batch.tstat(pre + a_net),
                     "skill": skill(a_tr), "dollars": dollars,
                     "cost_pts": statistics.mean(t.gross - t.pts for t in a_tr) if a_tr else math.nan})
    dec = batch.decide(serA, serPre, RC_RUNS, random.Random(SEED), ALPHA_NOW, ALPHA_BEFORE, ALPHA_ALL)
    q95 = lambda rc: rc["best"][min(len(rc["best"]) - 1, int(0.95 * len(rc["best"])))]
    say(f"best of {len(rows)} under pure chance, 95th percentile of t: NQ 2021-2026 {q95(dec['now']):+.2f}; "
        f"before 2021 {q95(dec['before']):+.2f}; whole sample {q95(dec['all']):+.2f}   ({RC_RUNS:,} draws, seed {SEED})")
    say()

    years = (A[-1].date - A[0].date).days / 365.25
    dates = [d.date for d in A]
    say("RESULTS (t = mean daily result over its standard error; p = corrected for running the whole batch)")
    say(f"  {'key':<15} {'tr/day':>6} | {'NQ 21-26 gross':>14} {'net':>8} {'t':>6} {'Sharpe':>6} {'p':>6} {'$/yr 1 MNQ':>10} | "
        f"{'ES 21-26 t':>10} | {'NQ 16-20 t':>10} {'ES 13-20 t':>10} {'before t':>8} {'p':>6} | {'whole t':>7} {'p':>6}")
    fam = None
    for r in rows:
        if r["family"] != fam:
            fam = r["family"]
            say(f"  -- {fam}")
        k = r["key"]
        r["pA"], r["pPre"], r["pAll"] = dec["now"]["p"][k], dec["before"]["p"][k], dec["all"]["p"][k]
        r["usd_year"] = sum(r["dollars"]) / years
        a = r["A"]
        say(f"  {k:<15} {r['per_day']:>6.2f} | {r['A_gross']['mean']:>+14.4f} {a['mean']:>+8.4f} {a['t']:>+6.2f} {a['sharpe']:>+6.2f} "
            f"{r['pA']:>6.3f} {r['usd_year']:>+10,.0f} | {r['B']['t']:>+10.2f} | {r['C']['t']:>+10.2f} {r['D']['t']:>+10.2f} "
            f"{r['pre']['t']:>+8.2f} {r['pPre']:>6.3f} | {r['all']['t']:>+7.2f} {r['pAll']:>6.3f}")
    say()

    # ---- the three routes
    names = lambda ks: ", ".join(ks) or "none"
    say(f"ROUTE 1 (strong now: corrected p <= {ALPHA_NOW} on NQ 2021-2026): {names(dec['route1'])}")
    say(f"ROUTE 2 (there before and still there: corrected p <= {ALPHA_BEFORE} before 2021, then confirmed on NQ 2021-2026"
        + (f" at t >= {dec['z2']:.2f}" if dec["cand2"] else "") + f"): candidates {names(dec['cand2'])}; confirmed {names(dec['route2'])}")
    say(f"ROUTE 3 (there all along: corrected p <= {ALPHA_ALL} on the whole sample and positive before 2021, then t >= "
        f"{batch.Z_STILL_THERE:.3f} on NQ 2021-2026): candidates {names(dec['cand3'])}; confirmed {names(dec['route3'])}")
    by_key = {r["key"]: r for r in rows}
    survivors = {}
    for k in dec["passed"]:
        r = by_key[k]
        r["es_gross_ok"] = r["B_gross"]["mean"] > 0
        if r["es_gross_ok"]:
            survivors[k] = r
        else:
            say(f"  {k} does not replicate: on ES 2021-2026 its mean result before costs is "
                f"{r['B_gross']['mean']:+.4f} (t {r['B_gross']['t']:+.2f})")
    say()

    # ---- account fit: for survivors, and for context the five best by NQ 2021-2026 t
    rank = sorted(rows, key=lambda r: -(r["A"]["t"] if r["A"]["t"] == r["A"]["t"] else -9))
    show = list(survivors.values()) + [r for r in rank if r["key"] not in survivors][:5]
    say("ACCOUNT FIT on one MNQ, NQ 2021-2026 (survivors first, then the five best of the rest for context)")
    say(f"  {'key':<15} {'$ a year':>9} {'worst DD':>9} {'worst day':>9} {'days<=-1200':>11} {'best day share':>14} "
        f"{'bust<=60':>8} {'<=120':>6} {'<=250':>6} {'median @120':>11} {'corr w/ bot':>11}  fits")
    for r in show:
        usd = r["dollars"]
        fit = batch.account_fit(usd, dates)
        total = sum(usd)
        share = max(usd) / total if total > 0 else math.nan
        both = [(x, ftm[d]) for x, d in zip(usd, dates) if d in ftm]
        xs, ys = [x for x, _ in both], [y for _, y in both]
        corr = statistics.correlation(xs, ys) if len(both) > 2 and len(set(xs)) > 1 and len(set(ys)) > 1 else math.nan
        ok = r["key"] in survivors and fit[HORIZON]["bust"] <= BUST_MAX and fit[HORIZON]["median"] > 0
        bad_days = sum(1 for x in usd if x <= -DAILY_LIMIT)
        r["fit"] = {"usd_year": total / years, "dd": batch.drawdown(usd), "worst_day": min(usd), "days_past_daily_limit": bad_days,
                    "best_day_share": share, "bust": {str(k): v["bust"] for k, v in fit.items()},
                    "median120": fit[HORIZON]["median"], "corr_bot": corr, "ok": ok}
        say(f"  {r['key']:<15} {total / years:>+9,.0f} {batch.drawdown(usd):>9,.0f} {min(usd):>+9,.0f} {bad_days:>11} {share:>14.0%} "
            f"{fit[60]['bust']:>8.0%} {fit[120]['bust']:>6.0%} {fit[250]['bust']:>6.0%} {fit[HORIZON]['median']:>+11,.0f} {corr:>+11.2f}  "
            f"{'YES' if ok else ('no' if r['key'] in survivors else '-')}")
    say()

    # ---- descriptive: where the day's drift sits. No verdict depends on this.
    say("MAP (descriptive): mean move of each half hour, long, BEFORE costs, in DATR units x 100, with its t")
    say(f"  {'window':<13} {'NQ 2021-26':>16} {'ES 2021-26':>16} {'NQ 2016-20':>16} {'ES 2013-20':>16}")
    hh = {}
    for T in st.HALF_HOURS:
        fn = st.clock(T, T + 30, 1)
        cells = []
        for bars_, days_ in ((nq_bars, A), (es_bars, B), (lse_bars, C), (es_bars, D)):
            s_ = batch.tstat(per_day(batch.run(bars_, days_, fn), days_, gross))
            cells.append((s_["mean"] * 100, s_["t"]))
        hh[f"{T // 60:02d}:{T % 60:02d}"] = cells
        say(f"  {T // 60:02d}:{T % 60:02d}-{(T + 30) // 60:02d}:{(T + 30) % 60:02d}   "
            + " ".join(f"{m:>+8.2f} ({t:>+5.2f})" for m, t in cells))
    say()

    passed = [k for k, r in survivors.items() if r.get("fit", {}).get("ok")]
    say("VERDICT: " + (f"can go to paper trading: {', '.join(passed)}" if passed else
                       ("survived the statistics but does not fit the account: " + ", ".join(survivors) if survivors
                        else "nothing in the batch clears the bar")))
    say(f"\nran in {time.time() - t0:.0f} s")
    slim = [{k: v for k, v in r.items() if k not in ("dollars", "fn")} for r in rows]
    return {"rows": slim, "kappa": kappa, "route1": dec["route1"], "route2_candidates": dec["cand2"], "route2": dec["route2"],
            "route3_candidates": dec["cand3"], "route3": dec["route3"], "survivors": list(survivors), "passed": passed,
            "map": hh, "refused": refused,
            # the daily series, kept so that a follow-up never has to rerun the batch
            "daily_A": {"dates": [str(d) for d in dates], "dollars": {r["key"]: r["dollars"] for r in rows}, "net": serA},
            "daily_before": {"dates": [str(d) for d in pre_dates], "net": serPre}}


def main() -> int:
    data.idle_priority()
    OUT.mkdir(exist_ok=True)
    try:
        result = body()
        (OUT / "batch.json").write_text(json.dumps(result, default=str), encoding="utf-8")
    finally:
        # whatever was printed is saved, even if the run stopped half way
        (OUT / "batch.txt").write_text("\n".join(_lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
