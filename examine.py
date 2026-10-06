"""A closer look at the strategies that cleared the batch. POST-HOC: written on 2026-10-01 AFTER
results/batch.txt existed. Nothing here changes the verdict; it describes what passed.

    py -3.14 examine.py            -> results/examine.txt

For each survivor on set A (NQ 2021-2026, one MNQ): its trades, where the profit sits, the part of
the sample that came after the source was published, the worst open loss inside a day against the
account's daily limit, and the account with and without the bot beside it.
"""
from __future__ import annotations

import math
import statistics
import sys
from datetime import date
from pathlib import Path

import batch
import core
import data
import registry
import run_batch

HERE = Path(__file__).resolve().parent
KEYS = ["noise", "noise_vwap", "noise_vwap_90", "monday"]
CONTEXT = ["first60_hold", "orb30", "long_day"]             # not survivors: shown for comparison only
PUBLISHED = date(2024, 5, 1)                                # "Beat the Market": sample ends April 2024, posted May 2024
MNQ = run_batch.MNQ
_lines: list[str] = []


def say(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def walk_day(bars, day, plans):
    """One day's plans filled in order. -> (trades, worst open equity of the day in points,
    counting what was already banked that day and the open trade's worst moment)."""
    trades, banked, worst = [], 0.0, 0.0
    for p in sorted(plans, key=lambda p: p.k):
        t = batch.execute(bars, day, p)
        px = bars.o[p.k] + p.side * bars.tick
        _, _, _, _, mae, _ = core.run_exit(bars, p.k, p.x, p.side, px, batch.NO_STOP if p.stop_px is None else
                                           max(0.0, core.round_up((px - p.stop_px) * p.side, bars.tick)), None)
        worst = min(worst, banked - mae)
        banked += t.pts
        trades.append(t)
    return trades, worst


def main() -> int:
    data.idle_priority()
    ftm = run_batch.load_bot()
    sets = run_batch.load()
    bars, days_all = sets["NQ 2021-26"]
    A = run_batch.split(days_all, None, None)
    dates = [d.date for d in A]
    years = (dates[-1] - dates[0]).days / 365.25
    fn = {s["key"]: s["fn"] for s in registry.STRATEGIES}
    bot = [(ftm.get(d, 0.0) - (1.0 if d in ftm else 0.0)) * MNQ for d in dates]      # one MNQ, a point of costs a traded day
    say("THE SURVIVORS, TAKEN APART (post-hoc; NQ 2021-2026, one MNQ, real costs)")
    say(f"{len(A):,} sessions, {dates[0]} .. {dates[-1]}")
    say()

    usd, worst_open, all_trades = {}, {}, {}
    for key in KEYS + CONTEXT:
        day_usd, day_worst, trades = [], [], []
        for d in A:
            tr, w = walk_day(bars, d, fn[key](d, bars))
            trades += tr
            day_usd.append(sum(t.pts for t in tr) * MNQ)
            day_worst.append(w * MNQ)
        usd[key], worst_open[key], all_trades[key] = day_usd, day_worst, trades

    say("1. TRADES")
    say(f"  {'key':<14} {'trades':>6} {'a year':>6} {'days in':>7} {'win %':>6} {'avg win':>8} {'avg loss':>8} {'PF':>5} "
        f"{'long %':>6} {'$ long':>8} {'$ short':>8} {'held min':>8}")
    for key in KEYS + CONTEXT:
        tr = all_trades[key]
        d_ = [t.pts * MNQ for t in tr]
        wins, losses = [x for x in d_ if x > 0], [x for x in d_ if x <= 0]
        say(f"  {key:<14} {len(tr):>6,} {len(tr) / years:>6.0f} {sum(1 for x in usd[key] if x):>7,} {len(wins) / len(tr):>6.0%} "
            f"{statistics.mean(wins):>+8.0f} {statistics.mean(losses):>+8.0f} {sum(wins) / -sum(losses):>5.2f} "
            f"{sum(1 for t in tr if t.side == 1) / len(tr):>6.0%} {sum(t.pts * MNQ for t in tr if t.side == 1):>+8,.0f} "
            f"{sum(t.pts * MNQ for t in tr if t.side == -1):>+8,.0f} {statistics.mean((t.x - t.k) * bars.tf for t in tr):>8.0f}")
    say()

    say("2. WHERE THE PROFIT SITS")
    say(f"  {'key':<14} {'total $':>9} {'best day':>9} {'best 5 days':>11} {'without best 1% of days':>23} {'days up':>8} {'worst day':>9}")
    for key in KEYS + CONTEXT:
        x = usd[key]
        live = sorted(v for v in x if v)
        k1 = max(1, round(0.01 * len(x)))
        say(f"  {key:<14} {sum(x):>+9,.0f} {max(x):>+9,.0f} {sum(live[-5:]) / sum(x):>11.0%} {sum(x) - sum(sorted(x)[-k1:]):>+23,.0f} "
            f"{sum(1 for v in live if v > 0) / len(live):>8.0%} {min(x):>+9,.0f}")
    say()

    say(f"3. BEFORE AND AFTER PUBLICATION ({PUBLISHED}: the noise-area paper's sample ends April 2024)")
    say(f"  {'key':<14} | {'before: sessions':>16} {'$ a year':>9} {'Sharpe':>6} {'t':>6} | {'after: sessions':>15} {'$ a year':>9} {'Sharpe':>6} {'t':>6}")
    cut = next(i for i, d in enumerate(dates) if d >= PUBLISHED)
    for key in KEYS + CONTEXT:
        cells = []
        for lo, hi in ((0, cut), (cut, len(dates))):
            x = usd[key][lo:hi]
            s = batch.tstat(x)
            yrs = (dates[hi - 1] - dates[lo]).days / 365.25
            cells.append(f"{hi - lo:>16,} {sum(x) / yrs:>+9,.0f} {s['sharpe']:>+6.2f} {s['t']:>+6.2f}")
        say(f"  {key:<14} | {cells[0]} | {cells[1][1:]}")
    say("  (in dollars, so a wide-ranging year counts for more than it does in the batch's DATR units)")
    say()

    say("4. INSIDE THE DAY: the worst open loss against the $1,200 daily limit (the batch only saw closes)")
    say(f"  {'key':<14} {'worst moment':>12} {'days at -$1,200 or worse':>24} {'of which closed above -$1,200':>29} {'days at -$600':>13}")
    for key in KEYS + CONTEXT:
        w = worst_open[key]
        hit = [i for i, v in enumerate(w) if v <= -run_batch.DAILY_LIMIT]
        say(f"  {key:<14} {min(w):>+12,.0f} {len(hit):>24} {sum(1 for i in hit if usd[key][i] > -run_batch.DAILY_LIMIT):>29} "
            f"{sum(1 for v in w if v <= -600):>13}")
    say("  (a day that touches the limit is closed out there, so its later recovery would not have been earned)")
    say()

    say("5. HOW ALIKE THEY ARE: correlation of daily dollars (bot = the reference trade list at one MNQ)")
    names = KEYS + CONTEXT + ["bot"]
    series = dict(usd)
    series["bot"] = bot
    say("  " + " " * 14 + "".join(f"{n[:11]:>12}" for n in names))
    for a in names:
        say(f"  {a:<14}" + "".join(f"{statistics.correlation(series[a], series[b]):>+12.2f}" for b in names))
    say()

    say("6. THE ACCOUNT ($2,000 trailing limit on closes, a fresh account each month): alone, and beside the bot")
    say(f"  {'what runs':<34} {'$ a year':>9} {'worst DD':>9} {'worst day':>9} {'bust<=60':>8} {'<=120':>6} {'<=250':>6} {'median @120':>11} {'best day share':>14}")
    combos = [("the bot alone", ["bot"])] + [(k, [k]) for k in KEYS] + [(f"bot + {k}", ["bot", k]) for k in KEYS] + \
             [("bot + noise_vwap + monday", ["bot", "noise_vwap", "monday"]), ("noise_vwap + monday", ["noise_vwap", "monday"])]
    first_bot = next(i for i, d in enumerate(dates) if d in ftm)
    for label, parts in combos:
        x = [sum(series[p][i] for p in parts) for i in range(len(dates))]
        if "bot" in parts:                                   # the bot's list starts in July 2021
            x, dts = x[first_bot:], dates[first_bot:]
        else:
            dts = dates
        yrs = (dts[-1] - dts[0]).days / 365.25
        fit = batch.account_fit(x, dts)
        say(f"  {label:<34} {sum(x) / yrs:>+9,.0f} {batch.drawdown(x):>9,.0f} {min(x):>+9,.0f} {fit[60]['bust']:>8.0%} "
            f"{fit[120]['bust']:>6.0%} {fit[250]['bust']:>6.0%} {fit[120]["median"]:>+11,.0f} {(max(x) / sum(x) if sum(x) > 0 else math.nan):>14.0%}")
    say("  (the bot's line is its reference backtest at one MNQ less a point a traded day; it is context, not a test of the bot)")
    say()

    say("7. DIRECTION: the call against a coin flip on the same fills (drift removed)")
    for key in KEYS + CONTEXT:
        s = run_batch.skill(all_trades[key])
        say(f"  {key:<14} skill {s['mean']:+.4f} DATR a trade, t {s['t']:+.2f}")
    say()

    say("8. NQ AND ES SIDE BY SIDE, in DATR units after today's cost: each year's total (t), then before and after publication")
    es_bars, es_all = sets["ES"]
    B = run_batch.split(es_all, run_batch.ERA, None)
    kappa = run_batch.round_trip(bars) / statistics.median(d.datr for d in A)
    net_es = run_batch.net_today(kappa, es_bars)
    yrs_ = sorted({d.year for d in dates})
    say(f"  {'key':<14} {'mkt':<3} " + " ".join(f"{y:>14}" for y in yrs_) + f" | {'to Apr 2024':>16} {'from May 2024':>16}")
    for key in KEYS:
        for mkt, days_, xs in (("NQ", A, run_batch.per_day(all_trades[key], A, lambda t: t.pts / t.unit)),
                               ("ES", B, run_batch.per_day(batch.run(es_bars, B, fn[key]), B, net_es))):
            cells = []
            for y in yrs_:
                x = [v for d, v in zip(days_, xs) if d.date.year == y]
                s = batch.tstat(x)
                cells.append(f"{sum(x):>+7.2f} ({s['t']:>+5.2f})")
            halves = []
            for part in (lambda d: d.date < PUBLISHED, lambda d: d.date >= PUBLISHED):
                x = [v for d, v in zip(days_, xs) if part(d)]
                s = batch.tstat(x)
                halves.append(f"t {s['t']:>+5.2f} Sh {s['sharpe']:>+5.2f}")
            say(f"  {key:<14} {mkt:<3} " + " ".join(cells) + " | " + "  ".join(halves))
    (HERE / "results" / "examine.txt").write_text("\n".join(_lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
