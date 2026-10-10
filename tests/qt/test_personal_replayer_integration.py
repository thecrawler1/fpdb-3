"""Keep personal sound controls compatible with upstream share/solver features."""

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, QRectF, QSettings, Qt
from PySide6.QtGui import QContextMenuEvent, QFont, QFontMetrics, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QMenu, QTableView, QWidget

from fpdb_3_legacy import replayer_audio
from fpdb_3_legacy.GuiHandViewer import GuiHandViewer
from fpdb_3_legacy.GuiReplayer import (
    CONTROL_RESERVED_HEIGHT,
    GuiReplayer,
    TableState,
    build_replay_layout,
    order_players_clockwise,
    replay_is_phase,
    replay_settled_pots,
)
from fpdb_3_legacy.GuiTourHandViewer import TourHandViewer
from fpdb_3_legacy.PokerStarsToFpdb import PokerStars
from fpdb_3_legacy.replayer_style import replay_font

pytestmark = pytest.mark.qt


def test_sound_controls_coexist_with_sharing_and_solver_review(
    qtbot, importer, fresh_db, legacy_config, tmp_path, monkeypatch
):
    settings = QSettings(str(tmp_path / "sound.ini"), QSettings.Format.IniFormat)
    settings.setValue("sound/volume", 12)
    monkeypatch.setattr(replayer_audio, "QSettings", lambda *args: settings)
    monkeypatch.setattr(replayer_audio, "prepare_sounds", lambda config: {})
    fixture = Path(__file__).parent.parent / "fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
    source = tmp_path / "hand.txt"
    source.write_bytes(fixture.read_bytes())
    importer.addImportFile(str(source), "PokerStars")
    assert importer.runImport()[0] == 1
    cursor = fresh_db.get_cursor()
    cursor.execute("SELECT id FROM Hands")
    hand_id = cursor.fetchone()[0]
    cursor.close()
    replayer = GuiReplayer(legacy_config, fresh_db.sql, MagicMock(), [hand_id], db=fresh_db)
    qtbot.addWidget(replayer)
    replayer.play_hand(0)
    assert replayer.shareButton.isEnabled()
    assert replayer.reviewButton.isEnabled()
    assert replayer.soundCheck.isChecked()

    sounds = []
    monkeypatch.setattr(replayer.audio, "play", sounds.append)
    qtbot.mouseClick(replayer.nextButton, Qt.MouseButton.LeftButton)
    assert len(sounds) == 1
    qtbot.mouseClick(replayer.prevButton, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(replayer.endButton, Qt.MouseButton.LeftButton)
    assert len(sounds) == 1
    assert replayer.preflop_actions_shown() > 0

    qtbot.mouseClick(replayer.soundCheck, Qt.MouseButton.LeftButton, pos=QPoint(8, replayer.soundCheck.height() // 2))
    assert not replayer.audio.enabled
    assert settings.value("sound/enabled", type=bool) is False
    replayer.soundCheck.setChecked(True)
    assert replayer.audio.volume == 100
    assert not hasattr(replayer, "soundVolume")
    assert not hasattr(replayer, "playPauseButton")
    assert not hasattr(replayer, "playTimer")
    assert not replayer.previousHandButton.isEnabled()
    assert not replayer.nextHandButton.isEnabled()
    replayer.close()


@pytest.mark.parametrize("size", [(800, 600), (1280, 720), (1600, 900)])
def test_replayer_controls_reserve_real_space(qtbot, legacy_config, monkeypatch, size):
    monkeypatch.setattr(replayer_audio, "prepare_sounds", lambda config: {})
    fixture = Path(__file__).parent.parent / "fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
    hand = PokerStars(config=legacy_config, in_path=str(fixture), autostart=True).getProcessedHands()[0]
    monkeypatch.setattr("fpdb_3_legacy.GuiReplayer.Hand.hand_factory", lambda *args: hand)
    replayer = GuiReplayer(legacy_config, None, None, [1, 2], db=object())
    qtbot.addWidget(replayer)
    replayer.play_hand(0)
    replayer.resize(*size)
    qtbot.waitUntil(lambda: replayer.size().width() == size[0])
    replayer.layout().activate()
    replayer.controls.layout().activate()
    qtbot.wait(1)
    layout = build_replay_layout(*size, [player[1] for player in hand.players], hand.hero, "holdem")
    assert replayer.controls.y() >= size[1] - CONTROL_RESERVED_HEIGHT
    controls = [
        replayer.stateSlider, *replayer.streetButtons.values(), replayer.startButton,
        replayer.prevButton, replayer.nextButton, replayer.endButton,
        replayer.previousHandButton, replayer.nextHandButton,
        replayer.showCards, replayer.soundCheck, replayer.bigBlindCheck, replayer.deckTypeCombo,
    ]
    rects = []
    for widget in controls:
        rect = widget.rect().translated(widget.mapTo(replayer, QPoint(0, 0)))
        assert replayer.rect().contains(rect)
        assert rect.top() >= replayer.controls.y()
        assert all(not rect.intersects(other) for other in rects), (widget, rect, rects)
        rects.append(rect)
    for seat in layout.seats.values():
        assert seat.cards_rect.bottom() < replayer.controls.y()
        assert seat.panel_rect.bottom() < replayer.controls.y()
    qtbot.mouseClick(replayer.nextHandButton, Qt.MouseButton.LeftButton)
    assert replayer.handidx == 1
    assert replayer.previousHandButton.isEnabled()
    assert not replayer.nextHandButton.isEnabled()
    qtbot.keyClick(replayer, Qt.Key.Key_Right)
    assert replayer.stateSlider.value() == 1
    qtbot.keyClick(replayer, Qt.Key.Key_Space)
    assert replayer.stateSlider.value() == 2
    qtbot.keyClick(replayer, Qt.Key.Key_Space)
    assert replayer.stateSlider.value() == 3
    qtbot.wait(800)
    assert replayer.stateSlider.value() == 3
    replayer.close()


@pytest.fixture
def history_replayer(qtbot, legacy_config, monkeypatch, tmp_path):
    settings = QSettings(str(tmp_path / "replayer.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(replayer_audio, "QSettings", lambda *args: settings)
    monkeypatch.setattr(replayer_audio, "prepare_sounds", lambda config: {})
    fixture = Path(__file__).parent.parent / "fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
    hand = PokerStars(config=legacy_config, in_path=str(fixture), autostart=True).getProcessedHands()[0]
    monkeypatch.setattr("fpdb_3_legacy.GuiReplayer.Hand.hand_factory", lambda *args: hand)
    replayer = GuiReplayer(legacy_config, None, None, [1], db=object())
    qtbot.addWidget(replayer)
    replayer.play_hand(0)
    return replayer


def test_history_preserves_indices_without_stale_phase_actions(history_replayer):
    replayer = history_replayer
    events = replayer._history_events()
    blind_entries = [event for event in events if event.action == "big blind"]
    assert len(blind_entries) == 1
    for index, state in enumerate(replayer.states):
        indexed = [entry for entry in events if entry.state_index == index]
        if replay_is_phase(replayer.states, index):
            assert any(entry.kind == "phase" for entry in indexed)
            assert not any(entry.kind == "action" for entry in indexed)
        else:
            acted = [player for player in state.players.values() if player.justacted and player.action]
            assert len([entry for entry in indexed if entry.kind == "action"]) == len(acted)
    preflop = next(state for state in replayer.states if state.street == "PREFLOP")
    assert any(player.justacted and player.action == "big blind" for player in preflop.players.values())
    assert blind_entries[0].state_index == 2


def test_status_identifies_deal_and_complete_frames(history_replayer):
    replayer = history_replayer
    flop = next(index for index, state in enumerate(replayer.states) if state.street == "FLOP")
    replayer.stateSlider.setValue(flop)
    frame = replayer._frame_from_state(replayer.states[flop])
    assert replayer._current_action_summary(frame) == "Flop dealt"
    replayer.end_clicked(False)
    frame = replayer._frame_from_state(replayer.states[-1])
    assert replayer._current_action_summary(frame) == "Hand complete · Player3 collected $17.50"


def test_call_text_uses_action_amount_not_accumulated_street_contribution(history_replayer):
    replayer = history_replayer
    call = next(entry for entry in replayer._history_events() if entry.action == "calls")
    assert call.text == "Hero: calls $5.53"
    replayer.stateSlider.setValue(call.state_index)
    state = replayer.states[call.state_index]
    assert state.players["Hero"].chips == 8  # Canonical state remains untouched.
    frame = replayer._frame_from_state(state)
    assert replayer._current_action_summary(frame) == "Hero calls $5.53"


def test_actor_emphasis_and_metrics_exclude_phase_copies(history_replayer, monkeypatch):
    replayer = history_replayer
    replayer._ensure_replayer_assets()
    monkeypatch.setattr(replayer, "_draw_cards", lambda *args, **kwargs: None)
    monkeypatch.setattr(replayer, "_draw_chip_amount", lambda *args, **kwargs: None)
    painter = MagicMock()
    painter.fontMetrics.return_value.horizontalAdvance.return_value = 40
    painter.fontMetrics.return_value.elidedText.side_effect = lambda text, *args: text
    layout = build_replay_layout(1280, 720, list(replayer.states[2].players), replayer.Heroes, "holdem")
    for index, has_badge in ((2, True), (3, False)):
        replayer.stateSlider.setValue(index)
        frame = replayer._frame_from_state(replayer.states[index])
        player = next(player for player in frame.players if player.action == "big blind")
        # Explicitly exercise the stale flag even when frame conversion clears it.
        player.justacted = True
        painter.reset_mock()
        replayer._draw_player(painter, player, layout.seats[player.name], layout, frame.street, False)
        # The stack is always bold. Only a genuine action frame has a status
        # badge; phase copies must not keep announcing the previous actor.
        badges = [call for call in painter.drawText.call_args_list if call.args[-1] == "big blind"]
        assert bool(badges) == has_badge
        if has_badge:
            assert painter.setFont.call_args_list[-1].args[0].weight() == QFont.Weight.Bold
    metrics = MagicMock(side_effect=AssertionError("Phase frame must not imply a hero turn"))
    monkeypatch.setattr(replayer, "_hero_decision_metrics", metrics)
    replayer._draw_summary(painter, frame, layout, 3)
    metrics.assert_not_called()


@pytest.mark.parametrize("size", [(800, 600), (1280, 720)])
def test_compact_history_access_and_exact_seek(qtbot, history_replayer, size):
    replayer = history_replayer
    replayer.resize(*size)
    qtbot.wait(1)
    button_rect = replayer.actionsButton.rect().translated(replayer.actionsButton.mapTo(replayer, QPoint(0, 0)))
    assert replayer.rect().contains(button_rect)
    qtbot.mouseClick(replayer.actionsButton, Qt.MouseButton.LeftButton)
    assert replayer.historyDialog.isVisible()
    phase_row = next(
        row for row in range(replayer.historyList.count())
        if replayer.historyList.item(row).text() == "— Flop dealt —"
    )
    item = replayer.historyList.item(phase_row)
    replayer.historyList.scrollToItem(item)
    qtbot.wait(1)
    qtbot.mouseClick(
        replayer.historyList.viewport(), Qt.MouseButton.LeftButton,
        pos=replayer.historyList.visualItemRect(item).center(),
    )
    assert replayer.stateSlider.value() == item.data(Qt.ItemDataRole.UserRole)
    assert replayer.states[replayer.stateSlider.value()].street == "FLOP"
    replayer.stateSlider.setValue(3)
    assert replayer.historyList.currentItem().data(Qt.ItemDataRole.UserRole) == 3
    replayer.historyDialog.close()


def test_wide_timeline_seeks_to_original_state(qtbot, history_replayer):
    replayer = history_replayer
    replayer.resize(1600, 900)
    replayer.end_clicked(False)
    qtbot.wait(1)
    replayer.grab()
    rect, index = next((rect, index) for rect, index in replayer._timeline_hit_regions if index == 11)
    qtbot.mouseClick(replayer, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
    assert replayer.stateSlider.value() == index


def test_transport_press_feedback_preserves_hit_area_and_release_click(qtbot, history_replayer):
    replayer = history_replayer
    button = replayer.nextButton
    assert button.height() >= 44
    assert not button.icon().isNull()
    assert button.accessibleName()
    original_rect = button.geometry()
    qtbot.mousePress(button, Qt.MouseButton.LeftButton)
    qtbot.wait(100)
    assert button.press_progress > .9
    assert button.iconSize().width() < 30
    assert button.geometry() == original_rect
    assert replayer.stateSlider.value() == 0
    qtbot.mouseRelease(button, Qt.MouseButton.LeftButton)
    assert replayer.stateSlider.value() == 1
    qtbot.wait(160)
    assert button.press_progress == 0
    assert button.iconSize().width() == 30


def test_larger_type_preserves_original_card_dimensions(history_replayer):
    font = replay_font("DejaVu Sans", 10, QFont.Weight.Bold)
    assert font.pointSizeF() == 15
    layout = build_replay_layout(1280, 720, [f"p{i}" for i in range(6)], "p0", "holdem")
    assert (layout.card_width, layout.card_height) == (56, 72)


def test_big_blind_toggle_converts_history_and_stacks_without_changing_state(qtbot, history_replayer):
    replayer = history_replayer
    before = [(state.pot, state.newpot, [(p.stack, p.chips) for p in state.players.values()]) for state in replayer.states]
    replayer.big_blind_amount = Decimal("0.02")
    replayer.actions_clicked()
    replayer.bigBlindCheck.setChecked(True)
    assert replayer._format_amount(Decimal(2)) == "100 BB"
    assert next(e.text for e in replayer._history_events() if e.action == "calls") == "Hero: calls 276.50 BB"
    assert replayer.historyList.item(1).text().endswith("25 BB")
    after = [(state.pot, state.newpot, [(p.stack, p.chips) for p in state.players.values()]) for state in replayer.states]
    assert before == after
    replayer.bigBlindCheck.setChecked(False)
    assert replayer._format_amount(Decimal(2)) == "$2.00"
    replayer.historyDialog.close()


def test_result_plaque_shows_total_stack_and_preserves_separate_award_and_financial_labels(history_replayer, monkeypatch):
    replayer = history_replayer
    replayer._ensure_replayer_assets()
    replayer.end_clicked(False)
    replayer.bigBlindCheck.setChecked(True)
    state = replayer.states[-1]
    player = next(p for p in replayer._frame_from_state(state).players if p.action == "collected")
    before = (state.players[player.name].stack, state.players[player.name].chips)
    assert before == (Decimal(72), Decimal("17.50"))
    player.cashout = Decimal("1.25")
    player.splash = Decimal("2.50")
    layout = build_replay_layout(1280, 720, list(state.players), replayer.Heroes, "holdem")
    monkeypatch.setattr(replayer, "_draw_cards", lambda *args, **kwargs: None)
    chips = MagicMock()
    monkeypatch.setattr(replayer, "_draw_chip_amount", chips)
    painter = MagicMock()
    painter.setFont.side_effect = lambda font: setattr(painter.fontMetrics, "return_value", QFontMetrics(font))
    replayer._draw_player(painter, player, layout.seats[player.name], layout, state.street, True)
    labels = [call.args[-1] for call in painter.drawText.call_args_list]
    assert "89.50 BB" in labels
    assert "cashout 1.25 BB  +2.50 BB splash" in labels
    assert chips.call_args.args[1] == Decimal("17.50")
    assert (state.players[player.name].stack, state.players[player.name].chips) == before


def test_long_nickname_uses_entire_name_row_and_elides_before_stack_row(history_replayer, monkeypatch):
    replayer = history_replayer
    replayer._ensure_replayer_assets()
    player = replayer._frame_from_state(replayer.states[0]).players[0]
    original_name = player.name
    player.name = "A very long player nickname that must never run into the stack"
    layout = build_replay_layout(1280, 720, [original_name], original_name, "holdem")
    monkeypatch.setattr(replayer, "_draw_cards", lambda *args, **kwargs: None)
    painter = MagicMock()
    painter.setFont.side_effect = lambda font: setattr(painter.fontMetrics, "return_value", QFontMetrics(font))
    seat = layout.seats[original_name]
    replayer._draw_player(painter, player, seat, layout, "PREFLOP", False)
    name_call, stack_call = painter.drawText.call_args_list[:2]
    assert name_call.args[-1].endswith("…")
    assert name_call.args[0].width() == seat.panel_rect.width() - 24
    assert name_call.args[0].bottom() < stack_call.args[0].top()
    assert stack_call.args[-1] == replayer._format_amount(player.stack)


def test_central_piles_do_not_double_count_outstanding_bets(history_replayer):
    replayer = history_replayer
    preflop = replayer.states[6]
    assert preflop.newpot == Decimal("3.97")
    assert replay_settled_pots(preflop) == []
    flop = next(state for state in replayer.states if state.street == "FLOP")
    assert replay_settled_pots(flop) == [("Pot", Decimal("17.50"))]
    assert replay_settled_pots(replayer.states[-1]) == []


def test_settled_side_piles_keep_all_in_caps_and_return_uncalled_chips(history_replayer):
    state = TableState(history_replayer.replay_model.hand)
    state.startPhase("PREFLOP")
    state.updateForAction(("Hero", "bets", Decimal(120)))
    state.updateForAction(("Player3", "calls", Decimal(80)))
    state.updateForAction(("Player1", "calls", Decimal(100)))
    assert replay_settled_pots(state) == []
    state.startPhase("FLOP")
    assert replay_settled_pots(state) == [("Main pot", Decimal(240)), ("Side pot 1", Decimal(40))]
    assert state.players["Hero"].stack == 20


def test_stud_replay_has_no_fake_big_blind_conversion(history_replayer):
    hand = history_replayer.replay_model.hand
    hand.gametype["base"] = "stud"
    history_replayer._configure_replay_units(hand)
    assert not history_replayer.bigBlindCheck.isEnabled()
    assert history_replayer.big_blind_amount is None


def test_winning_chip_stack_clears_dealer_and_card_slots(qtbot, history_replayer):
    replayer = history_replayer
    replayer.resize(1280, 720)
    replayer.end_clicked(False)
    qtbot.wait(1)
    replayer.grab()
    bounds = next(bounds for bounds, text in replayer._chip_regions if text.startswith("Won:"))
    players = order_players_clockwise(replayer._frame_from_state(replayer.states[-1]).players, replayer.Heroes)
    layout = build_replay_layout(1280, 720, [player.name for player in players], replayer.Heroes, "holdem")
    winner = next(player for player in players if player.action == "collected")
    seat = layout.seats[winner.name]
    diameter = max(24, int(32 * layout.card_width / 70))
    dealer = QRectF(seat.dealer_pos.x() - diameter / 2, seat.dealer_pos.y() - diameter / 2, diameter, diameter)
    assert not bounds.intersects(dealer)
    assert all(not bounds.intersects(other.cards_rect) for other in layout.seats.values())


@pytest.mark.parametrize("viewer_class", [GuiHandViewer, TourHandViewer])
def test_hand_viewer_context_menu_accepts_a_real_qt_event(qtbot, legacy_config, monkeypatch, viewer_class):
    fixture = Path(__file__).parent.parent / "fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
    hand = PokerStars(config=legacy_config, in_path=str(fixture), autostart=True).getProcessedHands()[0]
    host = QWidget()
    qtbot.addWidget(host)
    host.view = QTableView(host)
    model = QStandardItemModel(host)
    model.appendRow(QStandardItem("7"))
    host.view.setModel(model)
    host.view.setCurrentIndex(model.index(0, 0))
    host.hands = {7: hand}
    host.colnum = {"HandId": 0}
    host.config = legacy_config
    host.copyHandToClipboard = lambda *args, **kwargs: None
    menus = []

    class RecordingMenu(QMenu):
        def exec(self):
            menus.append(self)

    monkeypatch.setattr(sys.modules[viewer_class.__module__], "QMenu", RecordingMenu)
    position = QPoint(70, 80)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(4, 4), position)
    viewer_class.contextMenu(host, event)
    assert len(menus) == 1
    assert menus[0].pos() == position
    assert any("Solver review" in action.text() for action in menus[0].actions())
