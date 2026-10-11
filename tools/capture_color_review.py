#!/usr/bin/env python3
"""Colour review on real Qt widgets, using public/synthetic data only."""

import argparse
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from fpdb_3_legacy.ring_stats.styles import get_modern_qss
    from fpdb_3_legacy.ring_stats.views.starting_hands_view import StartingHandsTab
    from fpdb_3_legacy.table_cards import render_table_cards, table_card_icon
    from fpdb_3_legacy.ThemeManager import ThemeManager
    from tools.capture_design_review import public_database, workspace

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--light", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    ThemeManager().set_qt_material_theme("light_lightgreen.xml" if args.light else "dark_lightgreen.xml",
                                        save=False, apply_to_ui=True)
    with tempfile.TemporaryDirectory(prefix="fpdb-colours-") as temporary:
        config, sql, db, ids, _importer = public_database(Path(__file__).resolve().parent.parent, temporary)
        owner, hands, results = workspace(config, sql, db, ids, temporary)
        owner.show()
        results.select_total()
        app.processEvents()
        owner.grab().save(str(args.out / "results.png"))
        results.more_filters.setChecked(True)
        app.processEvents()
        results.limit_combo.showPopup()
        app.processEvents()
        results.limit_combo.view().window().grab().save(str(args.out / "limits.png"))
        results.limit_combo.hidePopup()
        # Repeat a public row with synthetic cards to review a dense table.
        for index in range(14):
            row = [hands.model.item(0, column).clone() for column in range(hands.model.columnCount())]
            cards = ("3d Qd", "7h 5d", "Ad Ah", "8c 2c", "Ks Jh")[index % 5]
            board = ("8d Tc Ad Td 8s", "Kh 8h 5c Qh 8c", "Ac 7h 2s")[index % 3]
            for column, tokens in (("Street0", cards), ("Street1-4", board)):
                row[hands.colnum[column]].setData(table_card_icon(render_table_cards([tokens])), Qt.ItemDataRole.DecorationRole)
            hands.model.appendRow(row)
        hands.view.resizeColumnsToContents()
        owner.nb.setCurrentIndex(1)
        hands.view.setCurrentIndex(hands.filterModel.index(3, 0))
        app.processEvents()
        owner.grab().save(str(args.out / "hands.png"))
        heatmap = StartingHandsTab()
        heatmap.setStyleSheet(get_modern_qss())
        heatmap.update_holdem_data({hand: {"n": 20, "net": ((i % 17) - 8) * 2.5, "vpip": i % 100}
                                   for i, hand in enumerate(heatmap.holdem_cells)})
        heatmap.resize(1120, 820)
        heatmap.show()
        app.processEvents()
        heatmap.grab().save(str(args.out / "heatmap.png"))
        heatmap.close()
        owner.close()
        hands.close_owned_database()
        results.close()
        db.disconnect()
    print(f"Colour review saved to {args.out}; public/synthetic data only.")


if __name__ == "__main__":
    main()
