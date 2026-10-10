"""Calendar boundaries, hand-weighted rates and curve/table accounting."""

import sqlite3
from datetime import date, timezone
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from fpdb_3_legacy.period_results import (
    group_results,
    parse_result_rows,
    period_end,
    period_start,
    preset_dates,
    profit_curves,
    results_query,
    summarize_results,
)
from fpdb_3_legacy.sql_queries_cash_profit import cash_profit_queries


def hand(number, timestamp="2026-10-01 12:00:00", profit=100, ev=50, bb=10, vpip=1, pfr=0, showdown=True,
         vpip_chance=1, pfr_chance=1):
    return parse_result_rows([(number, timestamp, profit, ev, bb, vpip, vpip_chance, pfr, pfr_chance,
                               showdown, "holdem", "nl")])[0]


def test_mixed_stakes_normalize_each_hand_and_do_not_average_daily_rates():
    hands = [hand(1, profit=100, ev=50, bb=10), hand(2, profit=100, ev=0, bb=20)]
    result = summarize_results(hands)
    assert result.profit == 200 and result.ev == 50
    assert result.bb_per_100 == 750  # (10 BB + 5 BB) / 2 * 100
    assert result.ev_bb_per_100 == 250
    assert profit_curves(hands, in_bb=True)[0] == [0, 10, 15]


def test_percentages_use_opportunities_and_totals_are_weighted_by_counts():
    hands = [hand(1, vpip=1, pfr=1)]
    hands += [hand(i, timestamp="2026-10-02 12:00:00", vpip=0, pfr=0) for i in range(2, 10)]
    hands.append(hand(10, timestamp="2026-10-02 12:00:00", vpip=0, pfr=0, vpip_chance=0, pfr_chance=0))
    days = group_results(hands, "day", timezone.utc)
    assert {day.vpip for day in days} == {D(0), D(100)}
    total = summarize_results(hands)
    assert total.vpip == total.pfr == D(100) / 9  # Not (100 + 0) / 2.
    assert len(total.hands) == 10


@pytest.mark.parametrize("grouping, start, end", [
    ("day", date(2026, 1, 1), date(2026, 1, 2)),
    ("week", date(2025, 12, 29), date(2026, 1, 5)),
    ("month", date(2026, 1, 1), date(2026, 2, 1)),
    ("year", date(2026, 1, 1), date(2027, 1, 1)),
])
def test_calendar_grouping_and_cross_year_monday_week(grouping, start, end):
    assert period_start(date(2026, 1, 1), grouping) == start
    assert period_end(start, grouping) == end
    rows = group_results([hand(1, "2026-01-01 12:00:00")], grouping, timezone.utc)
    assert (rows[0].start, rows[0].end) == (start, end)


def test_local_midnight_and_dst_use_actual_local_dates_and_half_open_bounds():
    zone = ZoneInfo("America/New_York")
    days = group_results([hand(1, "2026-03-08 04:59:59"), hand(2, "2026-03-08 05:00:00")], "day", zone)
    assert [day.start for day in days] == [date(2026, 3, 8), date(2026, 3, 7)]
    sql, params = results_query(7, date(2026, 3, 8), date(2026, 3, 8), zone)
    assert "h.startTime >= ?" in sql and "h.startTime < ?" in sql
    assert params == (7, "2026-03-08 05:00:00", "2026-03-09 04:00:00")  # 23-hour day.


def test_leap_month_and_presets():
    assert period_end(date(2024, 2, 1), "month") == date(2024, 3, 1)
    assert preset_dates(date(2024, 2, 15), "month") == (date(2024, 2, 1), date(2024, 2, 29))
    assert preset_dates(date(2026, 1, 1), "seven") == (date(2025, 12, 26), date(2026, 1, 1))
    assert preset_dates(date(2026, 1, 1), "all") == (None, None)


def test_four_curves_start_at_zero_and_split_net_in_showdown_and_nonshowdown():
    hands = [hand(2, profit=-50, ev=0, showdown=False), hand(1, profit=100, ev=150)]
    net, sd, nsd, ev = profit_curves(hands)
    assert net == [0, 1, .5] and sd == [0, 1, 1] and nsd == [0, 0, -.5]
    assert ev == [0, 1.5, 1.5]
    assert all(a + b == c for a, b, c in zip(sd, nsd, net))
    result = summarize_results(hands)
    assert net[-1] == float(result.profit / 100)
    assert ev[-1] == float(result.ev / 100)
    assert [h.hand_id for h in result.hands] == [1, 2]


def test_missing_ev_uses_actual_profit_but_a_real_zero_ev_stays_zero():
    assert hand(1, profit=100, ev=None).ev == 100
    assert hand(2, profit=100, ev=0).ev == 0


def test_invalid_blinds_do_not_invent_bb_rates_or_partially_plotted_curves():
    rows = [hand(1, bb=0), hand(2, bb=-1)]
    assert summarize_results(rows).bb_per_100 is None
    assert len(profit_curves(rows)[0]) == 3
    with pytest.raises(ValueError, match="every hand"):
        profit_curves(rows, in_bb=True)
    result = summarize_results([*rows, hand(3, bb=10)])
    assert result.bb_hands == 1 and result.bb_per_100 == 1000


def test_invalid_date_ranges_are_rejected_and_server_queries_are_parameterized():
    with pytest.raises(ValueError, match="Start date"):
        results_query(1, date(2026, 10, 2), date(2026, 10, 1), timezone.utc)
    sql, params = results_query(7, None, None, timezone.utc, "%s")
    assert "hp.playerId = %s" in sql and params == (7,)
    assert "gt.currency = 'USD'" in sql and "hp.tourneysPlayersId IS NULL" in sql


def test_usd_cash_population_and_legacy_graph_share_true_big_blind_units():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE Hands(id INTEGER, startTime TEXT, gametypeId INTEGER);
        CREATE TABLE Players(id INTEGER, siteId INTEGER);
        CREATE TABLE Gametypes(id INTEGER, bigBlind INTEGER, currency TEXT, type TEXT, category TEXT, limitType TEXT);
        CREATE TABLE HandsPlayers(handId INTEGER, playerId INTEGER, totalProfit INTEGER, allInEV INTEGER,
          street0VPI INTEGER, street0VPIChance INTEGER, street0Aggr INTEGER, street0AggrChance INTEGER,
          sawShowdown INTEGER, tourneysPlayersId INTEGER, splashWinnings INTEGER);
        INSERT INTO Players VALUES(7,1);
        INSERT INTO Gametypes VALUES(1,100,'USD','ring','holdem','nl'),(2,100,'EUR','ring','holdem','nl');
        INSERT INTO Hands VALUES(1,'2026-10-01 00:00:00',1),(2,'2026-10-01 12:00:00',2),
                                (3,'2026-10-01 13:00:00',1),(4,'2026-10-02 00:00:00',1);
        INSERT INTO HandsPlayers VALUES(1,7,100,50,1,1,1,1,1,NULL,0),(2,7,999,999,1,1,1,1,1,NULL,0),
                                      (3,7,999,999,1,1,1,1,1,5,0),(4,7,999,999,1,1,1,1,1,NULL,0);
    """)
    sql, params = results_query(7, date(2026, 10, 1), date(2026, 10, 1), timezone.utc)
    hands = parse_result_rows(db.execute(sql, params).fetchall())
    assert [h.hand_id for h in hands] == [1]  # Midnight included, next midnight excluded.
    legacy = cash_profit_queries()["getRingProfitAllHandsPlayerIdSiteInBB"]
    replacements = {"<player_test>": "(7)", "<site_test>": "(1)", "<startdate_test>": "2026-09-30",
                    "<enddate_test>": "2026-10-02", "<limit_test>": "", "<game_test>": "",
                    "<currency_test>": "AND gt.currency='USD'"}
    for key, value in replacements.items():
        legacy = legacy.replace(key, value)
    rows = db.execute(legacy).fetchall()
    assert rows[0][1] / 100 == profit_curves(hands, in_bb=True)[0][-1] == 1
    db.close()
