"""Public PokerStars files are imported incrementally across successive cycles."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from fpdb_3_legacy.GuiAutoImport import AutoImportThread

pytestmark = pytest.mark.qt


def test_completed_hands_appended_to_a_monitored_file_are_imported_once(importer, fresh_db, legacy_config, tmp_path):
    for site in legacy_config.supported_sites.values():
        site.enabled = False
    legacy_config.supported_sites['PokerStars'].enabled = True
    legacy_config.supported_sites['PokerStars'].screen_name = "Hero"
    original = (Path(__file__).parents[1] / "fixtures/hands/pokerstars/review/nl_3bet_6max.txt").read_text()
    folder = tmp_path / "HandHistory"
    folder.mkdir()
    source = folder / "HH20261011.txt"
    source.write_text(original)
    importer.setMode("auto")
    importer.caller = SimpleNamespace(addText=lambda *_args: None)
    importer.setCallHud(False)
    importer.addImportDirectory(str(folder), monitor=True, site=("PokerStars", "hh"), filter="PokerStarsToFpdb")
    first = AutoImportThread(importer)
    first.run()
    assert fresh_db.getHandCount() == 1 and first.new_hands == 1
    with source.open("a") as stream:
        stream.write("\n" + original.replace("2810000001", "2810000002"))
    second = AutoImportThread(importer)
    second.run()
    assert fresh_db.getHandCount() == 2 and second.new_hands == 1
    third = AutoImportThread(importer)
    third.run()
    assert fresh_db.getHandCount() == 2 and third.new_hands == 0
