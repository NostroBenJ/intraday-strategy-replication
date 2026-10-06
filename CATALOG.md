# What the two catalogs hold, and what the batch took from them

Written 2026-10-01, before any real bar was scored. Two searches were run, one of Quantpedia and
one of Papers With Backtest plus the papers both sites point to.

**How the numbers below were obtained.** The search tools could not open PDFs directly, so paper
figures were read through a text proxy and summarised by a model. They are quoted as the sources
report them and were not checked against the PDFs. None of them is used as a threshold in the
batch; the batch measures every rule itself.

## Papers With Backtest

A catalog of research papers, each with a backtest the site ran itself. It has an MCP server at
`https://paperswithbacktest.com/api/mcp` (sign-in with a site account). A free account can search
the catalog and unlock one strategy; code and datasets need the paid "Backtester" plan.

- **The strategy library** lists 51 strategies. Every one is a daily-to-yearly portfolio of stocks,
  crypto, currencies or bonds. None is intraday and none trades futures.
- **Paper-summary pages** exist beyond that list, and some cover intraday papers. They give no
  exact rules, their backtests run on daily bars, and none is on futures:

| Page | Paper | What the site reports |
|---|---|---|
| market-intraday-momentum | Gao, Han, Li & Zhou 2018 | 3.14%/yr, Sharpe 0.41 |
| intraday-momentum-the-first-half-hour-return-predicts-the-last-half-hour-return | the same effect | Sharpe -0.23 |
| orb-trading-strategy | 5-minute opening range breakout on QQQ, 2010-2026 | Sharpe -0.06, out of sample -0.84 |
| the-fomc-announcement-reversal | Baglioni & Ribeiro 2025 | 0.43%/yr, Sharpe 0.29 |
| intraday-time-series-reversal | Iwanaga & Sakemoto 2025 | 16.91%/yr, Sharpe 1.24, max drawdown -78.9% |
| overnight-intraday-reversal-everywhere | overnight against intraday | -4.72%/yr |
| hedging-demand-and-market-intraday-momentum | Baltussen, Da, Lammers & Martens 2021 | backtest blank |
| intraday-time-series-momentum-global-evidence | Li, Sakkas & Urquhart 2022 | "cannot be run on daily data" |

An intraday rule cannot be tested on daily bars, so the site's own numbers for these pages say
little either way. What the batch took from Papers With Backtest is the list of papers, not the
backtests.

## Quantpedia

Over 1,000 strategies, almost all monthly or daily holds. Most pages are behind a subscription;
the public screener shows a single intraday row (Bitcoin). The public pages and blog posts were
read for anything that needs only bars and a calendar and is flat by the close.

| Item | Paper | As reported | Fits a flat-by-close account? |
|---|---|---|---|
| Lunch effect | Vojtko & Dujava 2024 | SPY hourly 2010-2024: short 11:00-12:00, long 12:00-14:00 | yes: `lunch_short`, `lunch_long` |
| First half-hour predicts the last | Gao, Han, Li & Zhou 2018 | SPY 1993-2013: 6.67%/yr, Sharpe 1.08, before costs | yes: `gao`, `gao_both` |
| Rest of day predicts the last half-hour | Baltussen, Da, Lammers & Martens 2021 | index futures 1974-2020: Sharpe 1.73, no costs | yes: `rod` |
| Noise-area breakout (2025 award, 4th place) | Zarattini, Aziz & Barbon 2024 | SPY 2007-2024: 19.6%/yr, Sharpe 1.33 after costs | yes: `noise_vwap` |
| Intraday market-wide ups and downs | Zhang, Lin & Zhang | 2012-2015: 23.75%/yr; rule details could not be read | half: the index-return signal only, `first15_hold` |
| FOMC meeting effect | Lucca & Moench 2015 | +49 bp in the 24 hours to the statement, 1994-2011 | half: the morning of the day, `fomc_pre` |
| FOMC drift only in high uncertainty | Quantpedia post | 109 bp when implied vol is above its median, 9.7 bp below | half: `fomc_pre_hivix` |
| Turn of the month | McConnell & Xu | 7.2%/yr 1926-2005, close to close | daytime part only: `tom` |
| Pre-holiday | Hansen & Lunde | 6.39%/yr 1896-2002, close to close | daytime part only: `pre_holiday` |
| Payday | Ma & Pratt | 2.57%/yr 1980-2010, close to close | daytime part only: `payday` |
| Option-expiration week | Stivers & Sun | 9.3%/yr 1988-2010, close to close | daytime part only: `opex_week` |
| Overnight-intraday reversal in commodities | Della Corte, Kosowski & Wang | 11 agricultural futures | no: a cross-section of commodities |
| Half-day reversal | Dunis, Laws & Rudy | S&P 500 stocks | no: stocks, held overnight |
| Overnight anomaly, sentiment and overnight | Vojtko & Hanicova | SPY overnight 13.62%/yr, daytime -0.44%/yr | no: held overnight |
| 0DTE and dealer gamma | Adams et al. 2025 | no trading rule | no: needs options positioning |
| GDX / GLD night against day | Quantpedia | GLD daytime "negligible" over 20 years | no |
| January barometer, Halloween, pre-election | several | multi-day to multi-month holds | no |

None of the calendar pages says whether the return is earned overnight or in the day session. The
batch can only trade the day session, so it measures that part.

## The papers both sites point to

| Paper | Rule | As reported | Later evidence | In the batch |
|---|---|---|---|---|
| Gao, Han, Li & Zhou 2018, JFE | yesterday's close -> 10:00 sets the side for 15:30-16:00; variant: only when 15:00-15:30 agrees | 6.67%/yr, Sharpe 1.08; all of it in the most volatile third of days | QuantConnect 2015-2020 Sharpe -0.63 | `gao`, `gao_both`, `gao_highvix`, `gao_both_hivix` |
| Baltussen, Da, Lammers & Martens 2021, JFE | yesterday's close -> 15:30 sets the side for 15:30-16:00 | Sharpe 1.73 gross; lives on negative-dealer-gamma days | a vendor test on SPX 2022-2026 finds it flat | `rod`, `rod_day` |
| Li, Sakkas & Urquhart 2022 | Gao's rule on 16 cash indices | Sharpe 1.26 gross | none | covered by `gao` |
| Rosa 2022, J. Futures Markets | the overnight return predicts the last half-hour | in sample 1997-2013 | out of sample 2014-2020 "the predictability disappears" | `ovn_last30`, `ovn_last30_big` |
| Liu & Tse 2017 | overnight return: first half-hour the other way, last half-hour the same way | no strategy figures | none | `gap_fade_30`, `ovn_last30` |
| Iwanaga & Sakemoto 2025 | intraday time-series reversal | see the Papers With Backtest page | none | `gap_fade_30` |
| Grant, Wolf & Yu 2005 | large opening moves in S&P futures reverse | significance "sharply reduced" after costs | Plastun et al. 2019 find the opposite | `biggap_fade` (and `biggap_follow` as its mirror) |
| Zarattini & Aziz 2023, "Can day trading really be profitable?" | first 5-minute candle's direction from the 09:35 open, stop its other end, target 10R | QQQ 2016-2023: Sharpe 1.12 with zero slippage | a replication breaks even at 2.2 cents a share of slippage | `orb5_10r`, `orb5_close` |
| Zarattini & Aziz 2023, VWAP | long above the session VWAP, short below | QQQ 2018-2023: Sharpe 2.1; bar size and slippage not shown | none | `vwap_trend` |
| Zarattini, Aziz & Barbon 2024, "Beat the market" | the noise-area breakout | SPY Sharpe 1.33; authors' futures appendix: ES 1.32, NQ 1.23 | a replication reports Sharpe near zero in 2025; Quantitativo's NQ version is flat 2010-2017 | `noise`, `noise_vwap`, `noise_vwap_90` |
| Shum, Hejazi, Haryanto & Rodier 2012 | up or down 2% by 14:45: follow it to the close | 0.60% a trade gross 2006-2011, nearly all from late 2008 | none | `big_day` |
| Baltussen, Terstegge & Whelan 2023 | third-Friday opening settlement is too high and reverses by noon | 16 bp reversal, 2003-2021 | Quantitativo finds the overnight leg much smaller on futures | `opex_am_short` |
| Lucca & Moench 2015; Kurov, Wolfe & Gilbert 2021 | pre-FOMC drift | 49 bp (1994-2011) | 9.2 bp in 2016-2019 | `fomc_pre`, `fomc_pre_hivix` |
| Baglioni & Ribeiro 2025 | the market reverses after the FOMC statement | Sharpe 0.29 on the site's daily-bar test; no windows given | none | `fomc_reversal` (the windows are this study's reading) |
| Lundstrom 2017 | opening-range breakouts earn far more in volatile markets | about 150 bp a day more in the top volatility state | none | `orb30_hivix` |
| Boyarchenko, Larsen & Whelan 2023, RFS | long ES 02:00-03:00 | 1.48 bp a day, Sharpe 1.1 gross, -0.5 after spreads | the authors' July 2026 note: about zero in 2021-2025 | `night_drift` |
| Heston, Korajczyk & Sadka 2010 | a stock's return in a half hour repeats in the same half hour on later days | a stock cross-section | no index-futures version was found | `same_half_hour` (the index version is this study's reading) |
| Vojtko & Dujava 2024 | lunch effect | see above | none | `lunch_short`, `lunch_long` |

Three studies of many rules at once frame what to expect:

- Marshall, Cahan & Cahan 2008: 7,846 rules on 5-minute SPY; none survives a data-snooping control.
- Schulmeister 2009: 2,580 models on 30-minute S&P futures, 1983-2007: 7.2%/yr gross, 2.6% net, and
  -0.7%/yr in 2004-2007.
- Mesfin 2026 (arXiv 2605.04004, not peer-reviewed): 14 intraday-momentum families on MNQ 5-minute
  bars, 2021-2025, walk-forward: none passes after costs.

## Where the batch's rule is this study's reading, not the paper's

A published rule was run as published wherever it was fully stated. These are the exceptions:

- **Volatility filter** (`gao_highvix`, `gao_both_hivix`, `orb30_hivix`, `fomc_pre_hivix`): the
  papers sort days by volatility after the fact. Here the filter has to be known before the open:
  yesterday's VIX close above the median of the previous 252 closes.
- **Thresholds the sources do not give** (`ovn_last30_big` 0.25 DATR, `biggap_follow` and
  `biggap_fade` 0.5 DATR, `gap_fade_1h` 0.25 DATR): round numbers chosen before any result.
- **`vwap_trend`**: the paper does not show its bar size; read here on 5-minute closes.
- **`fomc_reversal`**: the public summary gives no windows; here the move from yesterday's close
  to 14:00 is faded from 14:05 to the close.
- **`first15_hold`**: after Zhang, Lin & Zhang, whose exact thresholds could not be read.
- **`rod_day`**, `first30_hold`, `first60_hold`, `morning_hold`, `orb5_close`, `orb30`, `orb60`,
  `gap_follow`, `gap_fade`, `yday_follow`, `yday_fade`, `down3_long`, `fomc_after`, the clock
  windows and the two weekdays: plain versions of the same ideas, included so that a published
  rule can be compared with its obvious neighbours and with the day's own drift.
- **Position size**: every rule trades one contract. The papers that size by volatility or by
  account risk (Zarattini's) are run without it; the account's loss limit decides size here.
- **Calendar effects**: only the 09:30-16:00 part of each.

## Left out, and why

| What | Why |
|---|---|
| Anything held overnight (the overnight anomaly, half-day reversal, pre-announcement drift of Hu, Pan, Wang & Zhu) | the account must be flat at the close |
| Cross-sections (Della Corte et al., stock intraday momentum and reversal, Lou-Polk-Skouras, opening-range breakout on "stocks in play") | need many instruments at once; the bot trades one |
| Dealer-gamma and 0DTE conditioning (Barbon et al., Adams et al., the gamma filter in Baltussen et al.) | need options positioning data that does not exist here before 2026 |
| Sentiment and order-flow rules | need a news or order-flow feed |
| Gold and silver rules (GLD half-hour momentum, metals session effects) | the bot trades MNQ; metals hour-of-day was tested on 2026-09-28 and was smaller than costs |
| Market-on-close imbalance rules | need the imbalance feed |

## Tested here before, with the result

| Study | What | Result |
|---|---|---|
| `Downloads\intraday_momentum_gao` | Gao's rule on ES | fail: -0.87 bp a day net over the full sample, -1.35 bp a day after 2018 |
| vault note on the noise area | Zarattini's noise area on SPY | in sample Sharpe 1.83, out of sample 0.08 |
| `Downloads\ta_setups` (2026-09-30) | TEMA ribbon, slope turn, pin bar, EMA pullback on NQ | none to add; the one variant that confirmed was the exit and trend days, and did not fit the account |

The batch reruns Gao and the noise area anyway, on NQ and with the same costs as everything else,
so that all fifty stand on one footing.
