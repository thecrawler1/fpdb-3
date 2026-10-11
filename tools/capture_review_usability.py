#!/usr/bin/env python3
"""Review pagination/search/export with public hands in an isolated database."""

import argparse
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from PySide6.QtWidgets import QApplication

    from fpdb_3_legacy.ThemeManager import ThemeManager
    from tools.capture_design_review import public_database, workspace

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    ThemeManager().set_qt_material_theme("dark_lightgreen.xml", save=False, apply_to_ui=True)
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="fpdb-review-") as temporary:
        config, sql, db, _ids, importer = public_database(root, temporary)
        original = (root / "tests/fixtures/hands/pokerstars/review/nl_3bet_6max.txt").read_text()
        source = Path(temporary) / "review.txt"
        source.write_text("\n".join(original.replace("2810000001", str(2810000001 + index)) for index in range(1, 31)))
        importer.addImportFile(str(source), "PokerStars")
        assert importer.runImport()[0] == 30
        cursor = db.get_cursor()
        cursor.execute("SELECT id FROM Hands ORDER BY id")
        ids = [row[0] for row in cursor.fetchall()]
        cursor.close()
        db.commit()
        owner, hands, results = workspace(config, sql, db, ids, temporary)
        owner.show()
        app.processEvents()
        owner.grab().save(str(args.out / "results-export.png"))
        assert results.export_csv(str(args.out / "public-results.csv"))
        results.interval_combo.blockSignals(True)
        results.interval_combo.setCurrentIndex(results.interval_combo.findData("custom"))
        results.interval_combo.blockSignals(False)
        results._set_preset()
        app.processEvents()
        owner.grab().save(str(args.out / "custom-dates.png"))
        results.game_combo.setCurrentIndex(1)
        results.limit_combo.setCurrentIndex(1)
        app.processEvents()
        owner.grab().save(str(args.out / "active-filters.png"))
        capture_hands(owner, hands, app, args.out)
        owner.close()
        hands.close_owned_database()
        results.close()
        db.disconnect()
    print(f"Usability review saved to {args.out}; public/synthetic data only.")


def capture_hands(owner, hands, app, out):
    hands.pageSizeCombo.setCurrentIndex(hands.pageSizeCombo.findData(25))
    owner.nb.setCurrentIndex(1)
    app.processEvents()
    owner.grab().save(str(out / "hands-pages.png"))
    for search, filename in (("2810000005", "hand-search.png"), ("99999999999999", "empty-search.png")):
        hands.handSearch.setText(search)
        hands._search_timer.stop()
        hands._apply_id_search()
        app.processEvents()
        owner.grab().save(str(out / filename))
    hands.handSearch.clear()
    hands._search_timer.stop()
    hands._apply_id_search()
    hands.filtersButton.setChecked(True)
    app.processEvents()
    owner.grab().save(str(out / "hand-filters.png"))


if __name__ == "__main__":
    main()
