#!/usr/bin/env python3
"""Public-data review of larger study controls, workspace subtabs and charts."""

import argparse
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def wait_for_widgets(app, seconds=.4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)


def main():
    from PySide6.QtWidgets import QApplication

    from fpdb_3_legacy.GuiGraphViewer import GuiGraphViewer
    from fpdb_3_legacy.GuiResearchBrowser import GuiResearchBrowser
    from fpdb_3_legacy.GuiStudyDashboard import GuiStudyDashboard
    from fpdb_3_legacy.GuiStudyExplorer import GuiStudyExplorer
    from fpdb_3_legacy.research_study_explorer import StudyExplorerModel
    from fpdb_3_legacy.ThemeManager import ThemeManager
    from tools.capture_design_review import public_database

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    theme = ThemeManager()
    theme.set_qt_material_theme("dark_lightgreen.xml", save=False, apply_to_ui=True)
    with tempfile.TemporaryDirectory(prefix="fpdb-automatic-") as temporary:
        config, sql, db, _ids, _importer = public_database(Path(__file__).resolve().parent.parent, temporary)
        explorer = GuiStudyExplorer(state_path=Path(temporary) / "studies.json")
        explorer.resize(1360, 960)
        explorer.show()
        wait_for_widgets(app)
        explorer.grab().save(str(args.out / "study-selector.png"))
        explorer.close()
        selection = StudyExplorerModel(state_path=Path(temporary) / "studies.json").open_study("preflop_rfi", remember=False)
        dashboard = GuiStudyDashboard(config, sql, db=db, selection=selection)
        dashboard.resize(1360, 960)
        dashboard.show()
        wait_for_widgets(app, 1)
        dashboard.grab().save(str(args.out / "study-analysis-tabs.png"))
        dashboard.pane_switcher.set_active(2)
        wait_for_widgets(app)
        dashboard.grab().save(str(args.out / "study-hands-tab.png"))
        dashboard.close()
        browser = GuiResearchBrowser(config, sql, None, db=db)
        browser.resize(1360, 960)
        browser.show()
        wait_for_widgets(app, 1)
        browser.grab().save(str(args.out / "research-results-tab.png"))
        browser.close()
        graph = GuiGraphViewer(sql, config, None, theme.get_theme_colors())
        graph.resize(1360, 960)
        graph.show()
        wait_for_widgets(app)
        graph.grab().save(str(args.out / "automatic-profit-graph.png"))
        graph.close_owned_database()
        graph.close()
        db.disconnect()
    print(f"Automatic-workspace captures saved to {args.out}; public data only.")


if __name__ == "__main__":
    main()
