# intraday-strategy-replication

Fifty published intraday trading rules for US equity-index futures, rebuilt and tested on 5-minute
bars under one frozen pre-registration, with White's reality check correcting every p-value for the
whole batch. Sources: the intraday papers that Quantpedia and Papers With Backtest point to
(Gao et al. 2018, Baltussen et al. 2021, Zarattini, Aziz & Barbon 2024, the NY Fed overnight drift,
and others), plus the daytime part of the well-known calendar effects. [`CATALOG.md`](CATALOG.md)
lists every source, what was taken from it and what was left out.

All rules are flat by the close. The question the study answers is a practical one: is any of them
worth trading on a single micro Nasdaq contract (MNQ) in a small account with a $2,000 trailing loss
limit?

## Answer: nothing to trade, two things to watch

Four of the 50 cleared every pre-registered gate: three versions of the Zarattini, Aziz & Barbon
noise-area breakout, and a plain long on Mondays. Taken apart afterwards, the noise-area pass rests
on the paper's own sample.

| `noise_vwap` (the paper's final rule) | to April 2024 (paper's sample) | from May 2024 |
|---|---|---|
| NQ | Sharpe 1.49, t +2.67 | Sharpe 0.88, t +1.35 |
| ES | Sharpe 1.78, t +3.23 | Sharpe −0.19, t −0.28 |

- On ES the edge vanishes after publication, matching an earlier replication on SPY (Sharpe 1.83
  in sample, 0.08 after). On NQ, 595 sessions at a Sharpe of 0.9 cannot tell a modest edge from none.
- 71% of its 2021-2026 profit came from the best 14 days, and since publication 30% of monthly
  accounts would have hit the $2,000 limit within 120 sessions.
- The Monday long has the cleanest numbers (t +3.36, positive every year since 2019) and the weakest
  reason: no paper predicts it, and day-of-week effects have a long record of vanishing.

Most of the famous effects are gone or wrong-way on NQ after costs: first half-hour predicts the
last (t −2.53), the lunch-hour short (t −3.37), the NY Fed 02:00 drift (real before 2021, gone
since), payday, and the pre-FOMC drift in the day session. Full write-up: [`RESULT.md`](RESULT.md).

## How the test was kept honest

- **Pre-registered and frozen.** [`PREREGISTRATION.md`](PREREGISTRATION.md) fixed the 50 rules, the
  costs, the gates and the decision before any real bar was scored, and [`FROZEN.txt`](FROZEN.txt)
  holds the SHA-256 of the plan and every code file at that moment (2026-10-01 03:12 EDT). The run
  happened once, a minute later. The frozen files are published unchanged.
- **Corrected for the batch.** White's reality check, 5,000 day-level redraws shared across all
  strategies, each strategy's t recomputed in every draw after centring on the days it traded. The
  bar under pure chance (95th percentile of the best of 50) came out at 3.02-3.06, where it should.
- **Three routes, all pre-registered**, so an edge that worked before 2021 and has since died cannot
  pass on its history alone, plus a replication gate on ES and an account gate.
- **The checks were checked.** `verify.py` runs 142 checks on synthetic data before any real data:
  every strategy against a second implementation written a different way, look-ahead tests at
  4,128 cut points that catch three strategies written to cheat, the reality check against a plain
  restatement, the full decision on zero-edge and planted-edge data, and **eleven deliberate bugs**
  put into the code one at a time, each of which must make a check fail.
- **What went wrong is written down.** The eras were split at 2021, not at each paper's publication
  date; for a published rule the publication date is the split that matters. `RESULT.md` says so
  and reports the publication split separately.

## Data (not included)

| set | series | span | use |
|---|---|---|---|
| A | NQ 1-minute (NinjaTrader export), resampled to 5-minute | 2021-2026 | the verdict |
| B | ES, Databento, back-adjusted | 2021-2026 | replication |
| C | NQ 5-minute, licensed vendor file | 2016-2020 | earlier era |
| D | ES, Databento, back-adjusted | 2013-2020 | earlier era |

Market data is licensed and never committed; the input paths are constants in `data.py`, which is
left exactly as frozen. The daily VIX file is FRED's public series: save
`https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS` as `data/vix_fred.csv`. A fresh download
will not match the hash in `FROZEN.txt`, because FRED revises and extends the file.
`run_batch.py` also reads a private reference trade list for one correlation column (`FTM` at the
top); a CSV with just the header `entry_time,points` is enough to run without it.

## Files

| file | what |
|---|---|
| `PREREGISTRATION.md`, `CATALOG.md` | the rules, and what the two catalogs hold |
| `registry.py`, `strategies.py` | the 50 strategies |
| `core.py`, `data.py`, `batch.py`, `run_batch.py` | bars, fills and costs, the reality check, the runner |
| `verify.py`, `verify_output.txt` | the 142 checks and their output at the freeze |
| `results/batch.txt`, `results/batch.json` | the run |
| `examine.py`, `results/examine.txt` | the survivors taken apart afterwards (post hoc, no bearing on the verdict) |
| `by_year.py` | year-by-year view of any strategy from the saved run |

Python 3.12+ (developed on 3.14), standard library only. `python verify.py` takes about 20 minutes;
`python run_batch.py` about 70 seconds once the data is in place.

The study was run for a personal account and its notes say so; the private reference strategy that
`examine.py` compares against is another author's and its figures are left out of this copy.
Research code, not trading advice.
