# Published intraday strategies on NQ: a batch test, pre-registration

Written 2026-10-01, before any real bar was scored. `registry.py` is this document as data.
Nothing below may be edited after a result exists; changes go in a dated addendum at the bottom.

## The question

Is any published intraday strategy worth adding to the bot, which trades one MNQ at a time on a
Lucid 50K funded account: flat by the close every day, a $2,000 end-of-day trailing loss limit?

## Where the strategies come from

The request was to mine two catalogs, Quantpedia and Papers With Backtest. Checked first:

- **Papers With Backtest:** its strategy library lists 51 strategies, every one a daily-to-yearly
  portfolio of stocks, crypto, currencies or bonds. Beyond that list it has summary pages for
  intraday papers, but those give no exact rules, their backtests run on daily bars, and none is
  on futures. Its code and data need a paid plan.
- **Quantpedia:** over 1,000 strategies, almost all monthly or daily holds, most behind a
  subscription. Its public pages hold four rules that are flat by the close and need only bars
  (the lunch effect, the two last-half-hour rules, the noise-area breakout) and five calendar
  effects whose daytime part can be traded.

A strategy that holds overnight cannot run on this account. So the batch is what those catalogs
point to: the published research on intraday effects in US equity index futures, plus the daytime
part of the well-known calendar effects. Every rule below can be traded flat-by-close with bars
and a calendar. What was found, what was taken, where a rule is this study's reading of a paper
that does not state it fully, and what was left out and why, is in `CATALOG.md`.

## The frame

- **Bars:** 5-minute. "The price at 10:00" is the close of the bar ending at 10:00; an order it
  triggers is filled at the open of the bar starting at 10:00.
- **Session:** 09:30 to 16:00 New York time. Everything is closed at 16:00.
- **Fills and costs:** market orders pay one tick beyond the bar's open, in and out. Stops pay a
  tick. Targets need a tick through. On set A that is the bot's real cost on MNQ: a tick each way
  and $1.00 a round trip, 1.00 point in all. The other sets are charged the same share of the
  day's range (see Data).
- **Scale:** a day's result is divided by that day's DATR, the mean regular-session range of the
  previous 20 sessions, so that 2016 and 2026 can be averaged.
- **Each strategy is run as its source states it.** Where a source leaves something open, the
  reading used is listed in `CATALOG.md`. No parameter was tuned on a result.

## The strategies

50 strategies in six groups.

**Intraday momentum: an earlier return predicts a later window**

| Key | Rule | Source |
|---|---|---|
| `gao` | Sign of yesterday's close -> 10:00, traded 15:30-16:00 | Gao, Han, Li & Zhou 2018, JFE |
| `gao_both` | The same, only when 15:00-15:30 agrees | Gao, Han, Li & Zhou 2018, JFE |
| `gao_highvix` | Gao, only when VIX is above its one-year median | Gao et al. 2018 (stronger in volatile markets) |
| `gao_both_hivix` | Gao_both, only when VIX is above its one-year median | Gao et al. 2018, agreement variant in volatile markets |
| `rod` | Sign of yesterday's close -> 15:30, traded 15:30-16:00 | Baltussen, Da, Lammers & Martens 2021, JFE |
| `rod_day` | Sign of 09:30 -> 15:30, traded 15:30-16:00 | Baltussen et al. 2021, daytime part |
| `first15_hold` | Sign of 09:30 -> 09:45, held 09:45-16:00 | Zhang, Lin & Zhang, index-return half of the up/down signal |
| `first30_hold` | Sign of yesterday's close -> 10:00, held 10:00-16:00 | intraday time-series momentum, held to the close |
| `first60_hold` | Sign of 09:30 -> 10:30, held 10:30-16:00 | intraday time-series momentum, held to the close |
| `morning_hold` | Sign of 09:30 -> 12:00, held 12:00-16:00 | intraday time-series momentum, held to the close |
| `big_day` | Up or down 2% on the day at 14:45: follow it to 16:00 | Shum, Hejazi, Haryanto & Rodier 2012, leveraged-ETF rebalancing |
| `vwap_trend` | Long above the session VWAP, short below, on 5-minute closes | Zarattini & Aziz 2023, VWAP trend |

**Overnight against the day**

| Key | Rule | Source |
|---|---|---|
| `gap_follow` | Follow the overnight move 09:30-16:00 | opening-gap continuation |
| `gap_fade` | Fade the overnight move 09:30-16:00 | Della Corte, Kosowski & Wang; Liu et al. 2025, single-market version |
| `gap_fade_30` | Fade the overnight move 09:30-10:00 | Iwanaga & Sakemoto 2025, intraday time-series reversal |
| `gap_fade_1h` | Fade a gap of at least 0.25 DATR, 09:30-10:30 | opening-gap fade |
| `biggap_follow` | Follow a gap of at least 0.5 DATR, 09:30-16:00 | gap-and-go |
| `biggap_fade` | Fade a gap of at least 0.5 DATR, 09:30-16:00 | Grant, Wolf & Yu 2005, large opening moves reverse |
| `ovn_last30` | Follow the overnight move 15:30-16:00 | Rosa 2022; Liu & Tse 2017 |
| `ovn_last30_big` | The same, only for a gap of at least 0.25 DATR | Rosa 2022, threshold version |
| `night_drift` | Long 02:00-03:00 every day | Boyarchenko, Larsen & Whelan, the overnight drift (NY Fed) |

**Breakouts**

| Key | Rule | Source |
|---|---|---|
| `orb5_10r` | First 5-minute candle's direction, stop its other end, target 10R | Zarattini & Aziz 2023 |
| `orb5_close` | The same with no target, out at the close | Zarattini & Aziz 2023, no target |
| `orb30` | First close outside the 30-minute range by 15:00, stop the far side, held to 16:00 | opening-range breakout (Crabel) |
| `orb60` | First close outside the 60-minute range by 15:00, stop the far side, held to 16:00 | opening-range breakout (Crabel) |
| `orb30_hivix` | Orb30, only when VIX is above its one-year median | Lundstrom 2017, breakouts pay in volatile markets |
| `noise` | Noise-area breakout on the half-hour, reverse at the opposite boundary | Zarattini, Aziz & Barbon 2024 |
| `noise_vwap` | Noise-area breakout with the VWAP trailing stop, 14-day lookback | Zarattini, Aziz & Barbon 2024 |
| `noise_vwap_90` | The same with a 90-day lookback | the NQ variant published by Quantitativo |

**Clock: the same side over the same window every day**

| Key | Rule | Source |
|---|---|---|
| `long_first30` | Long 09:30-10:00 | time-of-day seasonality |
| `lunch_short` | Short 11:00-12:00 | Vojtko & Dujava 2024, lunch effect (Quantpedia) |
| `lunch_long` | Long 12:00-14:00 | Vojtko & Dujava 2024, lunch effect (Quantpedia) |
| `long_last30` | Long 15:30-16:00 | end-of-day seasonality |
| `short_last30` | Short 15:30-16:00 | end-of-day seasonality |
| `long_day` | Long 09:30-16:00 every day | the daytime return itself |

**Calendar: special days**

| Key | Rule | Source |
|---|---|---|
| `tom` | Long 09:30-16:00 on the last and first three trading days of a month | turn of the month (McConnell & Xu), daytime part |
| `opex_week` | Long 09:30-16:00 in monthly option-expiration week | option-expiration week (Stivers & Sun), daytime part |
| `pre_holiday` | Long 09:30-16:00 the day before an exchange holiday | pre-holiday effect, daytime part |
| `payday` | Long 09:30-16:00 on the first trading day on or after the 16th | payday anomaly (Ma & Pratt), daytime part |
| `opex_am_short` | Short 09:30-12:00 on monthly option-expiration day (the third Friday) | Baltussen, Terstegge & Whelan 2023, the derivative payoff bias |
| `fomc_pre` | Long 09:30-13:55 on FOMC statement days | Lucca & Moench 2015, daytime part |
| `fomc_pre_hivix` | The same, only when VIX is above its one-year median | Lucca & Moench; Quantpedia on FOMC drift and uncertainty |
| `fomc_after` | On FOMC days follow 14:00-14:30 to the close | post-announcement drift |
| `fomc_reversal` | On FOMC days fade yesterday's close -> 14:00, from 14:05 to the close | Baglioni & Ribeiro 2025, the FOMC announcement reversal |
| `monday` | Long 09:30-16:00 on Mondays | day of the week |
| `friday` | Long 09:30-16:00 on Fridays | day of the week |

**Yesterday into today**

| Key | Rule | Source |
|---|---|---|
| `down3_long` | Long 09:30-16:00 after three lower closes in a row | short-term reversal, daytime part |
| `yday_follow` | Follow yesterday's daytime return 09:30-16:00 | daily momentum, daytime part |
| `yday_fade` | Fade yesterday's daytime return 09:30-16:00 | daily reversal, daytime part |
| `same_half_hour` | Each half hour takes the side of the same half hour yesterday, held while they agree | Heston, Korajczyk & Sadka 2010, index version |

A follow / fade pair on the same signal is listed as two strategies on purpose: after costs they
are not each other's negative, and the correction below counts both.

## Data

| Set | Series | Span | Use |
|---|---|---|---|
| A | NQ, NinjaTrader 1-minute dump (the bot's series) | 2021-01 to 2026-09 | the verdict |
| B | ES, Databento, back-adjusted | 2021-01 to 2026-08 | replication |
| C | NQ, LSE 5-minute file, roll weeks dropped | 2016-07 to 2020-12 | earlier era |
| D | ES, Databento, back-adjusted | 2013 to 2020 | earlier era |

Session rules as in `ta_setups` (75 of 78 bars, no 0.8% gap between one bar's close and the next
bar's open, 1,500 bars of unbroken history), plus the 16:00 bar must exist. The run prints how
many days each rule refused, and names every refused day that was an ordinary full trading day.
A strategy that needs yesterday's close only trades when yesterday was the previous exchange
trading day and was itself a usable session.

Four facts about the data that bear on a rule:

- **Costs outside set A.** A tick and a commission are fixed in points, but the day's range was
  far smaller before 2021 and is smaller on ES. Charged at its own tick, a round trip would cost
  several times more of the day's range in sets B, C and D than the bot pays now, and would bury
  any effect there for a reason that has nothing to do with trading MNQ today. So in sets B, C and
  D a round trip is charged the share of the day's range that it costs on a median day of set A.
  The run prints that share and what each set would have paid at its own tick. Set A pays its
  real ticks and commission.
- **Sets A, B and D are back-adjusted**, so their old prices sit above the real index: NQ by about
  29% in early 2021, falling to nothing by September 2026; ES by about 44% in 2013 and 21% in
  2021. Points, signs and ranges are unaffected, and those are what every rule but one uses. The
  exception is `big_day`: its 2% is 2% of the adjusted price, which is about 2.6% of the real
  index on NQ in 2021 and about 2.9% on ES in 2013. On set C, which is not adjusted, it is exact.
- **FOMC statement days** are the scheduled meetings from March 2013, when every statement moved
  to 14:00 (the Board announced it on 2013-03-13; January 2013 was still 14:15). The strategies
  on FOMC days therefore start in March 2013.
- **VIX** is the Cboe close published by FRED. A day's filter uses closes up to the day before.

## The test

For each strategy, the daily net result on set A, one number per session, zero when it did not
trade. t is its mean over its standard error.

Running many strategies and keeping the best is the oldest way to fool yourself, so every p-value
is corrected for the whole batch with White's reality check. Days are redrawn with replacement
5,000 times, the same days for every strategy. In every draw each strategy's t is worked out
afresh from the days drawn, after its results have been centred on the mean of the days it
traded. A strategy's corrected p is the share of draws in which the best t of the draw is at
least its own.

A strategy **survives the statistics** by any of three routes:

- **Route 1, strong now.** Corrected p at or below 0.05 on set A.
- **Route 2, there before and still there.** Corrected p at or below 0.10 on the data before 2021
  (sets C and D pooled by date: the mean of the markets trading that date), then on set A a
  positive mean with t at or above the one-sided 5% point shared across the candidates.
- **Route 3, there all along.** Corrected p at or below 0.05 on the whole sample (the pooled data
  before 2021 followed by set A) with a positive mean before 2021, then on set A a t at or above
  1.645, the one-sided 5% point. Without that last test a strategy that worked before 2021 and
  has since died would pass on its history alone about half the time.

A survivor must also **replicate**: on set B its mean daily result before costs is positive. This
guards against an artifact of the NQ file. It is not independent evidence against luck, because
ES and NQ move together.

And it must **fit the account**. On set A at one MNQ, a fresh account with a $2,000 end-of-day
trailing limit (locking at +$100) opened on the first session of every month: no more than 25% of
those accounts hit the limit within 120 sessions, and the median account is in profit at 120.
The monthly accounts overlap (set A holds about ten separate 120-session stretches), so that
share describes this history; it is not a probability with a tight error bar.

Only a strategy that clears all three is reported as "can go to paper trading". Nothing here puts
anything on the live account.

## What this test can and cannot see

Measured in `verify.py` [7] before the run: fifty independent daily series at the real sample
sizes (about 2,000 sessions before 2021 and 1,440 after), one of them given a true Sharpe ratio
after costs, 40,000 simulated batches a line. The simulation works from the t-statistics; it gave
the same answer as the real decision function in 98 of 100 direct trials.

| The planted strategy's true Sharpe ratio | It passes some route |
|---|---|
| none: pure noise, and anything at all passes | 7.9% |
| 0.5 before and after 2021 | 9.8% |
| 0.75 before and after 2021 | 33% |
| 1.0 before and after 2021 | 65% |
| 1.5 before and after 2021 | 97% |
| 2.0 before and after 2021 | 99.9% |
| 1.0 since 2021 only | 26% |
| 1.5 since 2021 only | 70% |
| 2.0 since 2021 only | 96% |
| 2.0 or 3.0 before 2021, nothing since | 5.0% |

So the three routes together let a batch of pure noise through about one time in thirteen. They
find a Sharpe ratio of 1.5 nearly every time if it was there before 2021 as well, and seven times
in ten if it has only been there since. A Sharpe ratio of 1.0 is found two times in three with
the older data behind it and one time in four without. A small edge, a Sharpe ratio near 0.5, is
missed nine times in ten. A strategy that died after 2020 gets through one time in twenty.

"Nothing clears the bar" therefore means no strategy here is strong enough to carry an account on
its own; it does not rule out a small edge. That is the right bar for this account: a Sharpe
ratio of 0.5 either earns too little to matter at one contract or, sized up until it matters,
runs into the $2,000 trailing limit.

One thing no correction can see: a strategy that makes a small steady gain on nearly every trade
and takes a rare loss many times larger looks strong in any sample that happens to hold no such
loss. On simulated series built that way the false-alarm rate was 8%, not 5%. No rule in the
batch is built like that, but a survivor with fewer than about 100 trade days and almost no
losing days will be reported as unproven, whatever its p-value. The run also prints the bar
itself (the 95th percentile of the best t under chance, for each sample); it should sit near 3.1,
and one far above that would mean a strategy of that kind is raising it for all the others.

## Reported, with no bearing on the verdict

Gross results, results on sets B, C and D, every strategy's uncorrected t (so a near miss can be
seen), dollars a year on one MNQ, the direction call against its coin-flip twin, the share of
profit from the best day (the funded account's payout rule caps a single day at 40% of profit),
the number of days that closed at or beyond the account's $1,200 daily loss limit, correlation
with the bot's own daily result, and a map of the mean move in each half hour of the day.

The account simulation uses each day's closed result. It does not model the daily loss limit
cutting a position during the day, and it knows nothing of an open loss that later recovered.

## Harness checks, run before real data (`verify.py`)

142 checks, all passing, on random walks and hand-worked bars only:

- the exchange calendar against published holiday lists, and every calendar flag against a plain
  restatement on all 3,521 trading days of 2013-2026;
- what each day may know (yesterday's close, the 20-day range, the VIX flag), on every session;
- fills and costs, long and short, with stops and targets, on hand-worked bars;
- every strategy against a second implementation written a different way, comparing the decision
  bar, entry, exit, side, stop and target of every plan, on a walk whose bars open away from the
  last close;
- no look-ahead: everything after a cut replaced, and the file ending at the cut, at six random
  cuts over the whole history; then every bar of 48 sessions used as a cut (4,128 cuts). Three
  strategies written to cheat (by the close, by an hour, by one bar) are each caught;
- the reality check against a plain restatement, draw for draw, and the account simulation on
  series with a known answer; among twenty noise series of which six trade rarely and lose big
  when they lose, it accepts something in 4.3% of 300 batches (a simpler version that was tried
  first accepted 13.7%);
- every threshold of the decision on p-values and t-statistics set by hand, and the runner's
  cost and pooling arithmetic on hand cases;
- the whole decision on twenty pairs of zero-edge walks (something passed in two) and twenty
  pairs with a planted effect (found in all twenty);
- eleven deliberate bugs put into the code one at a time; each makes at least one check fail.

## Changes made before the freeze

A second agent reviewed the code before any real bar was scored. It found no look-ahead and no
rule that differed from its description. It did find the following, all fixed before the freeze:

- **Route 3 let a dead edge through.** As first written it needed only a positive mean on set A,
  which a strategy with nothing left clears half the time. It now needs t at or above 1.645 there.
- **The correction was too kind to rarely-traded strategies.** Each redraw was scaled by the
  full-sample spread; for a strategy that trades a few dozen days and loses big on a few of them
  that makes the corrected p too small. Each redraw now uses its own t. While fixing this a second
  problem showed up and was fixed: a rarely-traded strategy that loses every time made the bar
  higher for all the others, because its idle days were being shifted along with its trade days.
- **Costs would have buried the older data.** A fixed tick is several times more of the day's
  range before 2021 than now. Sets B, C and D are now charged today's share of the range.
- **The breakout rules read their own fill** to set the stop distance. The stop is now a price
  fixed at the decision. A fill already beyond that price is stopped at once instead of skipped.
- **The half-hour rule paid for nothing:** it closed and reopened the same position at every half
  hour. It now holds while consecutive half hours agree.
- **Three calendar facts:** the January 2013 FOMC statement came out at 14:15, so the list starts
  in March 2013; when the third Friday is a holiday, option expiration is the Thursday; the ES
  data starts in 2013 rather than with a few scattered sessions from 2011.
- **The check suite could pass with deliberate bugs in the code** (a price read one bar late, a
  stop in the wrong place, short trades charged nothing, a threshold set wrong). It was rewritten
  until each such bug fails a check, and the look-ahead test now uses every bar as a cut.

The reviewer then went over the fixes. It confirmed each one, found every one of its own
deliberate bugs caught by the new suite, and measured the decision independently with the real
bootstrap: pure noise passes 8.5% of the time (plus or minus 0.8%), against the 7.9% above; a
Sharpe ratio of 1.0 and of 1.5 in both eras is found 63% and 97% of the time; one that exists
only since 2021, 26%, 73% and 96% at 1.0, 1.5 and 2.0; a dead one passes 4.5% to 6.3%. It also
checked that centring only the traded days keeps the false-alarm rate at or under 5% for dense,
sparse, fat-tailed and lopsided series, with the one exception described above.
