# Published intraday strategies on NQ: result

Run once on 2026-10-01 at 03:13 EDT on the code frozen at 03:12 (`FROZEN.txt`). Output:
`results/batch.txt`. The follow-up look at the survivors is `results/examine.txt`; it was written
after the result existed and changes nothing in the verdict.

## Answer

**Nothing here should go on the funded account. Two things are worth watching on a simulator:
the noise-area breakout with the VWAP stop, and a plain long on Mondays.**

Four of the 50 rules cleared every pre-registered gate: three versions of one published idea
(Zarattini, Aziz & Barbon's noise-area breakout) and the Monday long. Under the rules written
before the run, that makes them paper-trading candidates. Taken apart afterwards, the case for the
noise-area rules is weaker than the pass suggests:

- **Their pass rests on the years the paper was built on.** The paper's sample ends in April 2024.
  Up to then the VWAP version has a Sharpe ratio of 1.5 on NQ and 1.8 on ES. Since May 2024 it is
  0.9 on NQ (t 1.35, not significant) and -0.2 on ES. The ES figures are the same collapse the
  August replication on SPY found (Sharpe 1.83 in sample, 0.08 after).
- **Since publication it would not have fitted the account.** At one MNQ from May 2024 it made
  $8,879 with a $4,050 drawdown, and 30% of accounts opened monthly hit the $2,000 limit within
  120 sessions. Before publication the drawdown was $1,084 and no account busted.
- **Its profit is in a handful of days.** 71% of the 2021-2026 total came from the best 14 days.

The Monday long has the cleanest numbers and the weakest reason: no paper predicts it, and
day-of-week effects have a long record of vanishing. It is positive in every year from 2019 and
has been stronger, not weaker, since 2024.

## The verdict as registered

| | NQ 2021-26 t | corrected p | before 2021 t | whole sample t | corrected p | ES 2021-26 t | route |
|---|---|---|---|---|---|---|---|
| `noise` (reverse at the opposite boundary) | +3.02 | 0.049 | +0.74 | +2.49 | 0.225 | +1.53 | 1 |
| `noise_vwap` (the paper's final rule) | +2.82 | 0.094 | +1.91 | +3.28 | 0.022 | +2.16 | 3 |
| `noise_vwap_90` (90-day lookback) | +2.07 | 0.517 | +2.83 | +3.50 | 0.011 | +2.17 | 2, 3 |
| `monday` (long 09:30-16:00 on Mondays) | +3.36 | 0.015 | +1.23 | +3.06 | 0.045 | +2.89 | 1, 3 |

All four also made money before costs on ES 2021-2026 and met the account gate on set A. The bar
under pure chance (95th percentile of the best of 50) was 3.02, 3.06 and 3.03 for the three
samples, where it should be.

Three cautions that follow from the pre-registration itself:

- The three routes together pass a batch of pure noise about one time in thirteen.
- `noise` passes at 0.049 on 5,000 redraws. The Monte Carlo error on that is about 0.003, so
  it sits on the line.
- The three noise rules are one bet: their daily results correlate 0.75 to 0.87.

## What the pass does not show

The eras were split at 2021 because that is where the bot's data starts. For a published rule the
split that matters is its publication date, and the pre-registration did not have that gate. It
should have. The numbers, in DATR units after today's cost:

| | NQ to Apr 2024 | NQ from May 2024 | ES to Apr 2024 | ES from May 2024 |
|---|---|---|---|---|
| `noise` | t +2.48, Sharpe 1.38 | t +1.77, Sharpe 1.15 | t +1.62, Sharpe 0.89 | t +0.43, Sharpe 0.28 |
| `noise_vwap` | t +2.67, Sharpe 1.49 | t +1.35, Sharpe 0.88 | t +3.23, Sharpe 1.78 | t -0.28, Sharpe -0.19 |
| `noise_vwap_90` | t +3.36, Sharpe 1.87 | t -0.13, Sharpe -0.09 | t +2.77, Sharpe 1.52 | t +0.30, Sharpe 0.20 |
| `monday` (no publication date applies) | t +1.98, Sharpe 1.10 | t +2.84, Sharpe 1.85 | t +1.79, Sharpe 0.98 | t +2.37, Sharpe 1.56 |

Whether anything is left of the noise-area edge on NQ is open. 595 sessions at a Sharpe ratio of
0.9 cannot tell a modest edge from none, and the sister market says none.

## The survivors at one MNQ, NQ 2021-2026

| | `noise_vwap` | `noise` | `noise_vwap_90` | `monday` |
|---|---|---|---|---|
| Trades a year | 219 | 150 | 200 | 46 |
| Win rate | 41% | 58% | 39% | 60% |
| Average win / loss | +$177 / -$97 | +$217 / -$221 | +$199 / -$108 | +$274 / -$255 |
| Dollars a year | +3,599 | +4,767 | +2,214 | +2,962 |
| Worst drawdown | -4,050 | -2,933 | -5,814 | -2,666 |
| Worst closed day | -690 | -1,890 | -1,297 | -1,168 |
| Worst moment inside a day | -748 | -2,222 | -1,329 | -1,478 |
| Days that touched the $1,200 daily limit | 0 | 2 | 1 | 3 |
| Total without the best 14 days | +5,814 of +20,308 | +11,142 of +26,902 | -1,950 of +12,493 | +5,020 of +16,714 |
| Accounts busting within 120 sessions | 11% | 15% | 19% | 16% |
| Direction against a coin flip (t) | +3.23 | +3.23 | +2.40 | always long |
| Correlation with the bot's daily result | +0.32 | +0.35 | +0.30 | +0.07 |

The noise-area direction call does beat a coin flip on the same fills, so unlike an earlier
ribbon variant this is not only the exit. It is intraday momentum, the same thing the bot's
opening-range breakout trades, which is why the two lose on the same days.

(The private copy also stacks each survivor beside the bot's reference backtest. Those figures are
another author's strategy and are left out of this public copy.)

## What the batch says about the famous effects

Most of the published intraday effects are gone or wrong-way on NQ after costs:

| Effect | NQ 2021-26 | Before 2021 | Reading |
|---|---|---|---|
| First half-hour predicts the last (Gao et al. 2018) | t -2.53 | t -1.26 | wrong-way; loses before costs too |
| Rest of day predicts the last half-hour (Baltussen et al. 2021) | t -1.67 | t +1.13 | gone |
| Overnight move predicts the last half-hour (Rosa 2022) | t -1.27 | t -1.42 | gone, as Rosa found |
| Lunch effect, short 11:00-12:00 (Vojtko & Dujava 2024) | t -3.37 | t -2.37 | wrong-way: NQ rises in that hour |
| Lunch effect, long 12:00-14:00 | t +0.11 | t +0.44 | nothing |
| Overnight drift 02:00-03:00 (NY Fed) | t -0.58 | t +2.77 | was real, gone since 2021, as its authors say |
| Payday | t -0.42 | t +3.04 | was there, not since |
| Pre-FOMC drift, morning of the day | t +0.29 | t -1.73 | nothing in the day session |
| FOMC reversal | t -0.92 | t +2.37 | not since 2021 |
| Third-Friday morning reversal | t +1.66 | t +0.64 | positive, far from significant |
| First 5-minute candle breakout (Zarattini & Aziz 2023) | t +1.20 to +1.48 | t +1.61 to +1.72 | positive both eras, whole-sample t 2.1 to 2.2: a near miss |
| VWAP trend (Zarattini & Aziz 2023) | t +0.45 | t +0.53 | 7.5 trades a day; costs take the gross edge |
| Same half hour as yesterday | t -1.63 | t -3.03 | nothing; costs make it a loser |
| Turn of month, option-expiration week, pre-holiday | t +1.09, -1.24, +0.38 | t -0.20, +1.41, +0.79 | nothing in the day session |

Plain intraday momentum made money on NQ in 2021-2026 in every form tried (first 15 minutes held
to the close $5,153 a year, first hour $4,454, opening-range breakouts about $2,600) but none of
those forms is significant after the correction, and none fits the account: 34% to 58% of accounts
bust within 120 sessions. All of them have weakened since mid-2024: the 30-minute opening-range
breakout went from a Sharpe ratio of 1.0 to 0.2, the first-hour rule from 1.2 to 0.6.

The half-hour map shows no window with a reliable drift.

## What I would do

1. **Add nothing to the live bot.**
2. **If you want a forward record, paper-trade two things at one MNQ:** `noise_vwap` and
   `monday`. Not the other two noise versions; they are the same bet and worse.
3. **Know what a paper trade can settle.** It can show whether real fills match the model, and it
   can catch a clear failure. It cannot prove an edge of this size: a year at a Sharpe ratio of
   0.9 is a t of 0.9. Set the stopping rule before starting: out for good if the simulated account
   is ever $2,000 below its high.
4. **Watch the bot's live results against its backtest month by month.** Generic intraday momentum
   has faded since 2024 and the bot trades the same thing.

## Limits

- The test finds a true Sharpe ratio of 1.5 nearly always, of 1.0 two times in three with the
  older data behind it, and of 0.5 one time in ten. A small edge in the rules that failed is not
  ruled out.
- Fills are modelled: the open of the next 5-minute bar plus a tick. No live fill was compared.
- The account simulation uses closed daily results; section 4 of `examine.txt` adds the worst
  moment inside each day.
- `big_day` used a 2% threshold on back-adjusted prices, which is about 2.6% of the real index in
  2021. It traded on 8% of days and showed nothing.
- Days refused by the session rules are listed in `batch.txt`. On NQ 2021-2026, three ordinary
  trading days were refused for missing bars.

## Files

| File | What |
|---|---|
| `PREREGISTRATION.md`, `CATALOG.md` | the rules, and what the two catalogs hold |
| `registry.py`, `strategies.py`, `batch.py`, `run_batch.py` | the 50 strategies and the test |
| `verify.py`, `verify_output.txt` | 142 checks on synthetic data |
| `results/batch.txt`, `results/batch.json` | the run |
| `examine.py`, `results/examine.txt` | the survivors taken apart (post-hoc) |
| `by_year.py` | year-by-year view of any strategy from the saved run |
