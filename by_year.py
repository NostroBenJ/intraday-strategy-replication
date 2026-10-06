"""Year-by-year view of strategies from results/batch.json. Descriptive only: written before the
run, used after it, and nothing in the verdict depends on it.

    py -3.14 by_year.py gao noise_vwap        the named strategies
    py -3.14 by_year.py --top 8               the best eight by whole-sample t
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import batch

HERE = Path(__file__).resolve().parent


def main() -> int:
    j = json.loads((HERE / "results" / "batch.json").read_text(encoding="utf-8"))
    rows = {r["key"]: r for r in j["rows"]}
    args = sys.argv[1:]
    if args[:1] == ["--top"]:
        n = int(args[1]) if len(args) > 1 else 8
        finite = lambda r: r["all"]["t"] if r["all"]["t"] == r["all"]["t"] else -9.0
        keys = [r["key"] for r in sorted(j["rows"], key=lambda r: -finite(r))[:n]]
    else:
        keys = args
    before, now = j["daily_before"], j["daily_A"]
    years = sorted({d[:4] for d in before["dates"]} | {d[:4] for d in now["dates"]})
    print("Net result by year in DATR units (sum), with the year's t. Before 2021: NQ and ES pooled, at today's cost.")
    print("From 2021: NQ at its real cost, and dollars on one MNQ.\n")
    print(f"  {'year':<6}" + "".join(f"{k:>24}" for k in keys))
    for y in years:
        cells = []
        for k in keys:
            if k not in rows:
                cells.append(f"{'?':>24}")
                continue
            src = before if y < "2021" else now
            xs = [x for d, x in zip(src["dates"], src["net"][k]) if d[:4] == y]
            s = batch.tstat(xs)
            usd = ""
            if y >= "2021":
                usd = f" ${sum(x for d, x in zip(now['dates'], now['dollars'][k]) if d[:4] == y):>+7,.0f}"
            t = s["t"] if s["t"] == s["t"] else 0.0
            cells.append(f"{sum(xs):>+8.2f} ({t:>+5.2f}){usd:>9}")
        print(f"  {y:<6}" + "".join(f"{c:>24}" for c in cells))
    print()
    for k in keys:
        if k in rows:
            r = rows[k]
            print(f"  {k:<15} NQ 2021-26 t {r['A']['t']:+.2f} (Sharpe {r['A']['sharpe']:+.2f}), before 2021 t {r['pre']['t']:+.2f}, "
                  f"whole t {r['all']['t']:+.2f}; ES 2021-26 gross t {r['B_gross']['t']:+.2f}; {r['per_day']:.2f} trades a day; "
                  f"corrected p now {r['pA']:.3f}, before {r['pPre']:.3f}, whole {r['pAll']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
