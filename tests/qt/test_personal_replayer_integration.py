"""Keep personal sound controls compatible with upstream share/solver features."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt

from fpdb_3_legacy import replayer_audio
from fpdb_3_legacy.GuiReplayer import GuiReplayer

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

    qtbot.mouseClick(
        replayer.soundCheck, Qt.MouseButton.LeftButton, pos=QPoint(8, replayer.soundCheck.height() // 2)
    )
    assert not replayer.audio.enabled
    assert not replayer.soundVolume.isEnabled()
    assert settings.value("sound/enabled", type=bool) is False
    replayer.soundCheck.setChecked(True)
    replayer.soundVolume.setValue(48)
    assert replayer.audio.volume == 48
    assert settings.value("sound/volume", type=int) == 48
    replayer.play_clicked(False)
    assert replayer.playTimer.isActive()
    replayer.close()
    assert not replayer.playTimer.isActive()
