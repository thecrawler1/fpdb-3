"""Keep personal sound controls compatible with upstream share/solver features."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QContextMenuEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QMenu, QTableView, QWidget

from fpdb_3_legacy import replayer_audio
from fpdb_3_legacy.GuiHandViewer import GuiHandViewer
from fpdb_3_legacy.GuiReplayer import CONTROL_RESERVED_HEIGHT, GuiReplayer, build_replay_layout
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
    replayer.close()


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
