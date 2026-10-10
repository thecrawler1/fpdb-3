#!/usr/bin/env python3
"""Capture the production Results view with deterministic public synthetic data."""

import argparse
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def demo_rows():
    today = datetime.now(timezone.utc).date()
    rows = []
    for day in range(1, today.day + 1):
        start = datetime(today.year, today.month, day, 12, tzinfo=timezone.utc)
        for i in range(100):
            blind = 2 if i % 2 else 5
            profit = (((i * 7 + day * 3) % 19) - 9) * blind
            ev = profit + ((i % 5) - 2) * blind if i % 10 == 0 else profit
            vpip = (i + day) % 7 < 2
            rows.append((day * 1000 + i, start + timedelta(seconds=i * 61), profit, ev, blind,
                         int(vpip), 1, int(vpip and (i + day) % 3 != 0), 1, i % 3 == 0, "holdem", "nl"))
    return rows


def main():
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from fpdb_3_legacy.GuiResultsViewer import GuiResultsViewer
    from fpdb_3_legacy.period_results import parse_result_rows
    from fpdb_3_legacy.ThemeManager import ThemeManager

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    ThemeManager().set_qt_material_theme("dark_purple.xml", save=False, apply_to_ui=True)
    config = SimpleNamespace(get_supported_sites=lambda: ["PokerStars"], get_hero_aliases=lambda _site: ["Hero"])
    db = SimpleNamespace(get_player_id=lambda *_args: 1, get_player_name_by_id=lambda _id: "Hero", rollback=lambda: None)
    viewer = GuiResultsViewer(config, db=db, zone=timezone.utc, autoload=False)
    viewer.raw_hands = parse_result_rows(demo_rows())
    viewer._populate_filters()
    viewer._rebuild_table()
    viewer.resize(1360, 920)
    viewer.show()
    for _ in range(3):
        app.processEvents()
    viewer.grab().save(str(args.out / "daily.png"))
    viewer.select_total()
    app.processEvents()
    viewer.grab().save(str(args.out / "total.png"))
    viewer.units_combo.setCurrentIndex(1)
    app.processEvents()
    viewer.grab().save(str(args.out / "total-bb.png"))
    for grouping in ("week", "month", "year"):
        viewer.group_combo.setCurrentIndex(viewer.group_combo.findData(grouping))
        app.processEvents()
        viewer.grab().save(str(args.out / f"{grouping}.png"))
    viewer.close()
    print(f"Captured six Results views in {args.out}; no personal database was opened.")


if __name__ == "__main__":
    main()
