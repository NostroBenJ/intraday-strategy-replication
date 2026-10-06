"""The batch: every strategy that is run, as data. PREREGISTRATION.md is the authority.

Each entry: key, family, one-line rule, source, and the function. Frozen before any real bar was
scored. A mirror pair (follow / fade the same signal) is listed as two entries on purpose: after
costs they are not each other's negative, and the correction for running many counts both.
"""
from __future__ import annotations

import strategies as st

O, C = st.OPEN, st.CLOSE


def _e(key, family, rule, source, fn):
    return {"key": key, "family": family, "rule": rule, "source": source, "fn": fn}


STRATEGIES = [
    # ---- intraday momentum: an earlier return predicts a later window
    _e("gao", "momentum", "sign of yesterday's close -> 10:00, traded 15:30-16:00",
       "Gao, Han, Li & Zhou 2018, JFE", st.gao()),
    _e("gao_both", "momentum", "the same, only when 15:00-15:30 agrees",
       "Gao, Han, Li & Zhou 2018, JFE", st.gao(combined=True)),
    _e("gao_highvix", "momentum", "gao, only when VIX is above its one-year median",
       "Gao et al. 2018 (stronger in volatile markets)", st.with_vix(st.gao(), True)),
    _e("gao_both_hivix", "momentum", "gao_both, only when VIX is above its one-year median",
       "Gao et al. 2018, agreement variant in volatile markets", st.with_vix(st.gao(combined=True), True)),
    _e("rod", "momentum", "sign of yesterday's close -> 15:30, traded 15:30-16:00",
       "Baltussen, Da, Lammers & Martens 2021, JFE", st.rest_of_day()),
    _e("rod_day", "momentum", "sign of 09:30 -> 15:30, traded 15:30-16:00",
       "Baltussen et al. 2021, daytime part", st.rest_of_day(from_open=True)),
    _e("first15_hold", "momentum", "sign of 09:30 -> 09:45, held 09:45-16:00",
       "Zhang, Lin & Zhang, index-return half of the up/down signal", st.early_to_close(585, True)),
    _e("first30_hold", "momentum", "sign of yesterday's close -> 10:00, held 10:00-16:00",
       "intraday time-series momentum, held to the close", st.early_to_close(600, False)),
    _e("first60_hold", "momentum", "sign of 09:30 -> 10:30, held 10:30-16:00",
       "intraday time-series momentum, held to the close", st.early_to_close(630, True)),
    _e("morning_hold", "momentum", "sign of 09:30 -> 12:00, held 12:00-16:00",
       "intraday time-series momentum, held to the close", st.early_to_close(720, True)),
    _e("big_day", "momentum", "up or down 2% on the day at 14:45: follow it to 16:00",
       "Shum, Hejazi, Haryanto & Rodier 2012, leveraged-ETF rebalancing", st.big_day()),
    _e("vwap_trend", "momentum", "long above the session VWAP, short below, on 5-minute closes",
       "Zarattini & Aziz 2023, VWAP trend", st.vwap_trend()),
    # ---- overnight against the day
    _e("gap_follow", "overnight", "follow the overnight move 09:30-16:00",
       "opening-gap continuation", st.overnight(1)),
    _e("gap_fade", "overnight", "fade the overnight move 09:30-16:00",
       "Della Corte, Kosowski & Wang; Liu et al. 2025, single-market version", st.overnight(-1)),
    _e("gap_fade_30", "overnight", "fade the overnight move 09:30-10:00",
       "Iwanaga & Sakemoto 2025, intraday time-series reversal", st.overnight(-1, 0.0, 600)),
    _e("gap_fade_1h", "overnight", "fade a gap of at least 0.25 DATR, 09:30-10:30",
       "opening-gap fade", st.overnight(-1, 0.25, 630)),
    _e("biggap_follow", "overnight", "follow a gap of at least 0.5 DATR, 09:30-16:00",
       "gap-and-go", st.overnight(1, 0.5)),
    _e("biggap_fade", "overnight", "fade a gap of at least 0.5 DATR, 09:30-16:00",
       "Grant, Wolf & Yu 2005, large opening moves reverse", st.overnight(-1, 0.5)),
    _e("ovn_last30", "overnight", "follow the overnight move 15:30-16:00",
       "Rosa 2022; Liu & Tse 2017", st.overnight(1, 0.0, C, 930)),
    _e("ovn_last30_big", "overnight", "the same, only for a gap of at least 0.25 DATR",
       "Rosa 2022, threshold version", st.overnight(1, 0.25, C, 930)),
    _e("night_drift", "overnight", "long 02:00-03:00 every day",
       "Boyarchenko, Larsen & Whelan, the overnight drift (NY Fed)", st.clock(120, 180, 1)),
    # ---- breakouts
    _e("orb5_10r", "breakout", "first 5-minute candle's direction, stop its other end, target 10R",
       "Zarattini & Aziz 2023", st.orb_first_candle(10.0)),
    _e("orb5_close", "breakout", "the same with no target, out at the close",
       "Zarattini & Aziz 2023, no target", st.orb_first_candle(None)),
    _e("orb30", "breakout", "first close outside the 30-minute range by 15:00, stop the far side, held to 16:00",
       "opening-range breakout (Crabel)", st.opening_range(30)),
    _e("orb60", "breakout", "first close outside the 60-minute range by 15:00, stop the far side, held to 16:00",
       "opening-range breakout (Crabel)", st.opening_range(60)),
    _e("orb30_hivix", "breakout", "orb30, only when VIX is above its one-year median",
       "Lundstrom 2017, breakouts pay in volatile markets", st.with_vix(st.opening_range(30), True)),
    _e("noise", "breakout", "noise-area breakout on the half-hour, reverse at the opposite boundary",
       "Zarattini, Aziz & Barbon 2024", st.noise_area(False)),
    _e("noise_vwap", "breakout", "noise-area breakout with the VWAP trailing stop, 14-day lookback",
       "Zarattini, Aziz & Barbon 2024", st.noise_area(True)),
    _e("noise_vwap_90", "breakout", "the same with a 90-day lookback",
       "the NQ variant published by Quantitativo", st.noise_area(True, 90)),
    # ---- clock: the same side over the same window every day
    _e("long_first30", "clock", "long 09:30-10:00", "time-of-day seasonality", st.clock(O, 600, 1)),
    _e("lunch_short", "clock", "short 11:00-12:00", "Vojtko & Dujava 2024, lunch effect (Quantpedia)", st.clock(660, 720, -1)),
    _e("lunch_long", "clock", "long 12:00-14:00", "Vojtko & Dujava 2024, lunch effect (Quantpedia)", st.clock(720, 840, 1)),
    _e("long_last30", "clock", "long 15:30-16:00", "end-of-day seasonality", st.clock(930, C, 1)),
    _e("short_last30", "clock", "short 15:30-16:00", "end-of-day seasonality", st.clock(930, C, -1)),
    _e("long_day", "clock", "long 09:30-16:00 every day", "the daytime return itself", st.clock(O, C, 1)),
    # ---- calendar: long the regular session on special days
    _e("tom", "calendar", "long 09:30-16:00 on the last and first three trading days of a month",
       "turn of the month (McConnell & Xu), daytime part", st.clock(O, C, 1, "tom")),
    _e("opex_week", "calendar", "long 09:30-16:00 in monthly option-expiration week",
       "option-expiration week (Stivers & Sun), daytime part", st.clock(O, C, 1, "opex_week")),
    _e("pre_holiday", "calendar", "long 09:30-16:00 the day before an exchange holiday",
       "pre-holiday effect, daytime part", st.clock(O, C, 1, "pre_holiday")),
    _e("payday", "calendar", "long 09:30-16:00 on the first trading day on or after the 16th",
       "payday anomaly (Ma & Pratt), daytime part", st.payday()),
    _e("opex_am_short", "calendar", "short 09:30-12:00 on monthly option-expiration day (the third Friday)",
       "Baltussen, Terstegge & Whelan 2023, the derivative payoff bias", st.clock(O, 720, -1, "opex")),
    _e("fomc_pre", "calendar", "long 09:30-13:55 on FOMC statement days",
       "Lucca & Moench 2015, daytime part", st.clock(O, 835, 1, "fomc")),
    _e("fomc_pre_hivix", "calendar", "the same, only when VIX is above its one-year median",
       "Lucca & Moench; Quantpedia on FOMC drift and uncertainty", st.with_vix(st.clock(O, 835, 1, "fomc"), True)),
    _e("fomc_after", "calendar", "on FOMC days follow 14:00-14:30 to the close",
       "post-announcement drift", st.fomc_after(30)),
    _e("fomc_reversal", "calendar", "on FOMC days fade yesterday's close -> 14:00, from 14:05 to the close",
       "Baglioni & Ribeiro 2025, the FOMC announcement reversal", st.fomc_reversal(845)),
    _e("monday", "calendar", "long 09:30-16:00 on Mondays", "day of the week", st.clock(O, C, 1, "dow0")),
    _e("friday", "calendar", "long 09:30-16:00 on Fridays", "day of the week", st.clock(O, C, 1, "dow4")),
    # ---- yesterday into today
    _e("down3_long", "daily", "long 09:30-16:00 after three lower closes in a row",
       "short-term reversal, daytime part", st.after_down_days(3)),
    _e("yday_follow", "daily", "follow yesterday's daytime return 09:30-16:00",
       "daily momentum, daytime part", st.yesterday(1)),
    _e("yday_fade", "daily", "fade yesterday's daytime return 09:30-16:00",
       "daily reversal, daytime part", st.yesterday(-1)),
    _e("same_half_hour", "daily", "each half hour takes the side of the same half hour yesterday, held while they agree",
       "Heston, Korajczyk & Sadka 2010, index version", st.same_half_hour()),
]

assert len({s["key"] for s in STRATEGIES}) == len(STRATEGIES)
