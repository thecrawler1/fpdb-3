"""Exact, history-local decision arithmetic independent from Qt and card equity."""

from copy import deepcopy
from decimal import Decimal as D
from types import SimpleNamespace as NS

from fpdb_3_legacy.replayer_decision import action_decision, hero_decision


def player(name, stack, *, start=100, chips=0, action=None, acted=False, folded=False):
    return NS(name=name, startStack=D(start), stack=D(stack), chips=D(chips), action=action, justacted=acted, folded=folded)


def state(street, *players, ended=False):
    return NS(street=street, players={p.name: p for p in players}, ended=ended)


def test_spr_restarts_on_turn_and_river_and_is_stable_through_bets_and_result():
    flop = state("FLOP", player("Hero", 90), player("Villain", 90))
    flop_call = state("FLOP", player("Hero", 80, chips=10), player("Villain", 80, chips=10))
    turn = state("TURN", player("Hero", 80), player("Villain", 80))
    turn_bet = state("TURN", player("Hero", 60, chips=20, action="bets", acted=True), player("Villain", 80))
    river = state("RIVER", player("Hero", 60), player("Villain", 60))
    ended = deepcopy(river)
    ended.ended = True
    states = [flop, flop_call, turn, turn_bet, river, ended]
    assert hero_decision(states, 0, "Hero").spr == (D("4.5"),)
    assert hero_decision(states, 2, "Hero").spr == (D(2),)
    assert hero_decision(states, 3, "Hero").spr == (D(2),)
    assert hero_decision(states, 4, "Hero").spr == (D(".75"),)
    assert hero_decision(states, 5, "Hero").spr == (D(".75"),)
    assert hero_decision(states, 5, "Hero").mode == "neutral"


def test_call_five_into_fifteen_requires_25_percent_and_reports_half_pot_sizing():
    before = state("TURN", player("Hero", 95), player("Villain", 95))
    bet = state("TURN", player("Hero", 95), player("Villain", 90, chips=5, action="bets", acted=True))
    metrics = hero_decision([before, bet], 1, "Hero")
    assert metrics.mode == "call"
    assert metrics.call_amount == 5
    assert metrics.pot_odds_pct == 25
    assert metrics.bet_pct == 50


def test_half_pot_hero_bet_has_pure_mdf_and_bluff_fold_threshold():
    before = state("TURN", player("Hero", 95), player("Villain", 95))
    bet = state("TURN", player("Hero", 90, chips=5, action="bets", acted=True), player("Villain", 95))
    metrics = hero_decision([before, bet], 1, "Hero")
    assert metrics.mode == "bet"
    assert metrics.bet_amount == 5
    assert metrics.bet_pct == 50
    assert round(metrics.mdf_pct, 2) == D("66.67")
    assert round(metrics.fold_equity_pct, 2) == D("33.33")


def test_raise_uses_new_investment_not_total_chips_already_in_front():
    before = state("TURN", player("Hero", 90, chips=5, action="bets"), player("Villain", 80, chips=15, action="raises"))
    raised = state("TURN", player("Hero", 60, chips=35, action="raises", acted=True), player("Villain", 80, chips=15))
    metrics = hero_decision([before, raised], 1, "Hero")
    assert metrics.bet_amount == 30
    assert metrics.bet_pct == 100
    assert metrics.mdf_pct == metrics.fold_equity_pct == 50


def test_short_allin_call_excludes_side_money_hero_cannot_win():
    before = state("TURN", player("Hero", 5, start=10), player("Villain", 105, start=110))
    bet = state("TURN", player("Hero", 5, start=10), player("Villain", 5, start=110, chips=100, action="bets", acted=True))
    metrics = hero_decision([before, bet], 1, "Hero")
    assert metrics.call_amount == 5
    assert metrics.pot_odds_pct == 25  # Only 20 can be won after the call.


def test_mdf_caps_uncallable_excess_and_handles_hero_allin_bets():
    before = state("TURN", player("Hero", 95), player("Villain", 5, start=10))
    bet = state("TURN", player("Hero", 45, chips=50, action="bets", acted=True), player("Villain", 5, start=10))
    metrics = hero_decision([before, bet], 1, "Hero")
    assert metrics.bet_amount == 50
    assert round(metrics.mdf_pct, 2) == D("66.67")  # Only five more can be lost.
    before.players["Hero"].startStack = D(10)
    before.players["Hero"].stack = D(5)
    bet.players["Hero"].startStack = D(10)
    bet.players["Hero"].stack = D(0)
    bet.players["Hero"].chips = D(5)
    assert hero_decision([before, bet], 1, "Hero").mode == "bet"


def test_multiway_spr_is_per_opponent_and_mdf_is_not_assigned_individually():
    before = state("TURN", player("Hero", 80), player("Short", 40, start=50), player("Deep", 60, start=70))
    bet = deepcopy(before)
    bet.players["Hero"].stack -= 10
    bet.players["Hero"].chips = D(10)
    bet.players["Hero"].action = "bets"
    bet.players["Hero"].justacted = True
    metrics = hero_decision([before, bet], 1, "Hero")
    assert metrics.effective == (("Short", D(40)), ("Deep", D(60)))
    assert metrics.spr == (D(1), D("1.5"))
    assert metrics.mdf_pct is metrics.fold_equity_pct is None


def test_folded_opponent_is_excluded_from_effective_matchups_but_dead_money_counts():
    current = state("TURN", player("Hero", 90), player("Villain", 90), player("Folded", 20, start=30, action="folds", folded=True))
    metrics = hero_decision([current], 0, "Hero")
    assert metrics.street_pot == 30
    assert metrics.effective == (("Villain", D(90)),)
    assert metrics.spr == (D(3),)


def test_fold_and_completion_clear_decision_values_but_keep_street_spr():
    before = state("TURN", player("Hero", 95), player("Villain", 95))
    after = state("TURN", player("Hero", 95, action="folds", folded=True), player("Villain", 90, chips=5, action="bets"))
    metrics = hero_decision([before, after], 1, "Hero")
    assert metrics.spr == (D("9.5"),)
    assert metrics.mode == "neutral"
    assert metrics.pot_odds_pct is metrics.mdf_pct is None


def test_no_pot_missing_hero_and_future_states_do_not_invent_metrics():
    current = state("PREFLOP", player("Hero", 100), player("Villain", 100))
    future = state("TURN", player("Hero", 1), player("Villain", 1))
    assert hero_decision([current, future], 0, "Hero") == hero_decision([current], 0, "Hero")
    assert not hero_decision([current], 0, "Hero").spr
    assert not hero_decision([current], 0, "Missing").effective


def test_action_odds_switch_to_opponent_after_hero_bet_without_using_future_size():
    before = state("TURN", player("Hero", 95), player("Villain", 95))
    bet = state("TURN", player("Hero", 90, chips=5, action="bets", acted=True), player("Villain", 95))
    future = state("TURN", player("Hero", 90, chips=5, action="bets"), player("Villain", 90, chips=5, action="calls", acted=True))
    actor, metrics = action_decision([before, bet, future], 1, "Hero")
    assert actor == "Villain"
    assert metrics.call_amount == 5 and metrics.pot_odds_pct == 25
    assert metrics.spr == (D("9.5"),)
    future.players["Villain"].chips = D(80)
    future.players["Villain"].action = "raises"
    assert action_decision([before, bet, future], 1, "Hero") == (actor, metrics)


def test_action_identity_does_not_cross_streets_and_result_clears_odds():
    before = state("FLOP", player("Hero", 95), player("Villain", 95))
    turn = state("TURN", player("Hero", 90, chips=5, action="bets", acted=True), player("Villain", 95))
    actor, metrics = action_decision([before, turn], 0, "Hero")
    assert actor is None and metrics.pot_odds_pct is None
    assert metrics.spr == (D("9.5"),)
    before.ended = True
    assert action_decision([before, turn], 0, "Hero")[0] is None
