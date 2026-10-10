"""Keep personal sound controls compatible with upstream share/solver features."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QContextMenuEvent, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QMenu, QTableView, QWidget

from fpdb_3_legacy import replayer_audio
from fpdb_3_legacy.GuiHandViewer import GuiHandViewer
from fpdb_3_legacy.GuiReplayer import (
    CONTROL_RESERVED_HEIGHT,
    GuiReplayer,
    build_replay_layout,
    replay_is_phase,
)
from fpdb_3_legacy.GuiTourHandViewer import TourHandViewer
from fpdb_3_legacy.PokerStarsToFpdb import PokerStars

pytestmark = pytest.mark.qt


def test_sound_controls_coexist_with_sharing_and_solver_review(
    qtbot, importer, fresh_db, legacy_config, tmp_path, monkeypatch
):
    settings = QSettings(str(tmp_path / "sound.ini"), QSettings.Format.IniFormat)
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
    assert not replayer.soundVolume.isEnabled()
    assert settings.value("sound/enabled", type=bool) is False
    replayer.soundCheck.setChecked(True)
    replayer.soundVolume.setValue(48)
    assert replayer.audio.volume == 48
    assert settings.value("sound/volume", type=int) == 48
    replayer.play_clicked(False)
    assert replayer.playTimer.isActive()
    replayer.speedCombo.setCurrentIndex(3)
    assert replayer.playTimer.interval() == 350
    assert not replayer.previousHandButton.isEnabled()
    assert not replayer.nextHandButton.isEnabled()
    replayer.close()
    assert not replayer.playTimer.isActive()


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
        replayer.prevButton, replayer.playPauseButton, replayer.nextButton, replayer.endButton,
        replayer.previousHandButton, replayer.nextHandButton, replayer.speedCombo,
        replayer.showCards, replayer.soundCheck, replayer.soundVolume, replayer.deckTypeCombo,
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
    assert replayer.playing
    qtbot.keyClick(replayer, Qt.Key.Key_Space)
    assert not replayer.playing
    replayer.close()


@pytest.fixture
def history_replayer(qtbot, legacy_config, monkeypatch):
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
    painter = MagicMock()
    painter.fontMetrics.return_value.horizontalAdvance.return_value = 40
    painter.fontMetrics.return_value.elidedText.side_effect = lambda text, *args: text
    layout = build_replay_layout(1280, 720, list(replayer.states[2].players), replayer.Heroes, "holdem")
    for index, weight in ((2, QFont.Weight.Bold), (3, QFont.Weight.Normal)):
        replayer.stateSlider.setValue(index)
        frame = replayer._frame_from_state(replayer.states[index])
        player = next(player for player in frame.players if player.action == "big blind")
        # Explicitly exercise the stale flag even when frame conversion clears it.
        player.justacted = True
        painter.reset_mock()
        replayer._draw_player(painter, player, layout.seats[player.name], layout, frame.street, False)
        assert painter.setFont.call_args_list[1].args[0].weight() == weight
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
    replayer.play_clicked(False)
    qtbot.mouseClick(
        replayer.historyList.viewport(), Qt.MouseButton.LeftButton,
        pos=replayer.historyList.visualItemRect(item).center(),
    )
    assert replayer.stateSlider.value() == item.data(Qt.ItemDataRole.UserRole)
    assert replayer.states[replayer.stateSlider.value()].street == "FLOP"
    assert not replayer.playing
    replayer.stateSlider.setValue(3)
    assert replayer.historyList.currentItem().data(Qt.ItemDataRole.UserRole) == 3
    replayer.historyDialog.close()


def test_wide_timeline_seeks_to_original_state(qtbot, history_replayer):
    replayer = history_replayer
    replayer.resize(1600, 900)
    replayer.end_clicked(False)
    qtbot.wait(1)
    replayer.grab()
    rect, index = next((rect, index) for rect, index in replayer._timeline_hit_regions if index == 3)
    qtbot.mouseClick(replayer, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
    assert replayer.stateSlider.value() == 3


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
