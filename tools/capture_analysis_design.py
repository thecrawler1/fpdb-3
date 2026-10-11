#!/usr/bin/env python3
"""Capture shared analysis filters and Study Explorer with public data only."""

import argparse
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def filter_window(config, sql, db, app, out, *, tournament=False):
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

    from fpdb_3_legacy.Filters import Filters
    from fpdb_3_legacy.responsive_layout import wrap_in_scroll
    from fpdb_3_legacy.ring_stats.views.dashboard_view import ProfitGraphWidget

    display = {"Heroes": True, "Sites": True, "Games": not tournament, "Currencies": not tournament,
               "Limits": not tournament, "LimitSep": True, "LimitType": True, "UseType": "tour" if tournament else "ring",
               "Seats": True, "Dates": True, "Groups": not tournament, "GroupsAll": not tournament, "Button1": True}
    filters = Filters(db, display)
    filters.registerButton1Name("Refresh statistics")
    filters.registerButton1Callback(lambda: None)
    owner = QWidget()
    layout = QHBoxLayout(owner)
    sidebar = wrap_in_scroll(filters)
    sidebar.setObjectName("filterSidebar")
    sidebar.setFixedWidth(340)
    layout.addWidget(sidebar)
    content = QVBoxLayout()
    heading = QLabel("Tournament statistics" if tournament else "Cash statistics")
    heading.setStyleSheet("font-size:20px; font-weight:600;")
    content.addWidget(heading)
    graph = ProfitGraphWidget()
    graph.plot_profit_data([1, -2, 4, -1, 3, 2, -3, 4, 1], list(range(9)), units="$", title="Public sample")
    content.addWidget(graph, 1)
    layout.addLayout(content, 1)
    owner.resize(1280, 960)
    owner.show()
    app.processEvents()
    name = "tournament" if tournament else "cash"
    owner.grab().save(str(out / f"{name}-filters.png"))
    filters.date_preset.setCurrentIndex(filters.date_preset.findData("custom"))
    app.processEvents()
    owner.grab().save(str(out / f"{name}-custom-dates.png"))
    owner.close()


def main():
    from PySide6.QtWidgets import QApplication

    from fpdb_3_legacy.GuiStudyExplorer import GuiStudyExplorer
    from fpdb_3_legacy.ThemeManager import ThemeManager
    from tools.capture_design_review import public_database

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    ThemeManager().set_qt_material_theme("dark_lightgreen.xml", save=False, apply_to_ui=True)
    with tempfile.TemporaryDirectory(prefix="fpdb-analysis-design-") as temporary:
        config, sql, db, _ids, _importer = public_database(Path(__file__).resolve().parent.parent, temporary)
        filter_window(config, sql, db, app, args.out)
        filter_window(config, sql, db, app, args.out, tournament=True)
        explorer = GuiStudyExplorer(state_path=Path(temporary) / "studies.json")
        explorer.resize(1400, 980)
        explorer.show()
        app.processEvents()
        explorer.grab().save(str(args.out / "study-explorer.png"))
        explorer.resize(820, 720)
        app.processEvents()
        explorer.grab().save(str(args.out / "study-explorer-narrow.png"))
        explorer.close()
        db.disconnect()
    print(f"Analysis design captured in {args.out}; public data only.")


if __name__ == "__main__":
    main()
