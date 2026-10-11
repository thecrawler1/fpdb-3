#!/usr/bin/env python3
"""Real Qt design review using public hands, never the personal database."""

import argparse
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def public_database(root, temporary):
    from fpdb_3_legacy import SQL, Configuration, Database
    from fpdb_3_legacy.Importer import Importer

    config = Configuration.Config(file=str(root / "HUD_config.xml.example"), custom_log_dir=temporary)
    params = config.get_db_parameters()
    params.update({"db-server": "sqlite", "db-backend": 4, "db-name": str(Path(temporary) / "public.sqlite"),
                   "db-databaseName": str(Path(temporary) / "public.sqlite"), "db-path": ""})
    config.get_db_parameters = lambda: params
    for site in config.supported_sites.values():
        site.enabled = False
    config.supported_sites["PokerStars"].enabled = True
    config.supported_sites["PokerStars"].screen_name = "Hero"
    config.get_hero_aliases = lambda _site: ["Hero"]
    sql = SQL.Sql(db_server="sqlite")
    db = Database.Database(config, sql=sql)
    db.recreate_tables()
    importer = Importer(caller=None, settings={"testData": False, "threads": 1}, config=config, sql=sql)
    importer.database = db
    fixture = root / "tests/fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
    importer.addImportFile(str(fixture), "PokerStars")
    assert importer.runImport()[0] == 1
    cursor = db.get_cursor()
    cursor.execute("SELECT id FROM Hands ORDER BY id")
    ids = [row[0] for row in cursor.fetchall()]
    cursor.close()
    db.commit()
    return config, sql, db, ids, importer


def workspace(config, sql, db, ids, temporary):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QTabWidget, QWidget

    from fpdb_3_legacy.app_navigation import ApplicationNavigation
    from fpdb_3_legacy.GuiHandViewer import GuiHandViewer
    from fpdb_3_legacy.GuiResultsViewer import GuiResultsViewer
    from fpdb_3_legacy.period_results import parse_result_rows
    from tools.capture_results_review import demo_rows

    owner = QMainWindow()
    owner.nb = QTabWidget()
    owner.nb_tab_names = ["Results", "Hand Viewer"]
    results = GuiResultsViewer(config, sql, db=db, autoload=False)
    results.raw_hands = parse_result_rows(demo_rows())
    results._populate_filters()
    results._rebuild_table()
    hands = GuiHandViewer(config, sql, None)
    hands.columnControls.settings = QSettings(str(Path(temporary) / "columns.ini"), QSettings.Format.IniFormat)
    hands.columnControls.reset()
    hands.reload_hands(ids)
    hands.view.setCurrentIndex(hands.filterModel.index(0, 0))
    owner.nb.addTab(results, "Results")
    owner.nb.addTab(hands, "Hand Viewer")
    owner.display_tab = lambda name: owner.nb.setCurrentIndex(owner.nb_tab_names.index(name))
    owner.tab_hand_viewer = lambda _: owner.display_tab("Hand Viewer")
    owner.tab_results = lambda _: owner.display_tab("Results")
    central = QWidget()
    layout = QHBoxLayout(central)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(ApplicationNavigation(owner))
    layout.addWidget(owner.nb, 1)
    owner.setCentralWidget(central)
    owner.resize(1560, 980)
    return owner, hands, results


def capture(owner, hands, app, out):
    owner.show()
    for _ in range(3):
        app.processEvents()
    owner.grab().save(str(out / "results-shell.png"))
    owner.nb.setCurrentIndex(1)
    for _ in range(3):
        app.processEvents()
    owner.grab().save(str(out / "hands-minimal.png"))
    menu = hands.columnsButton.menu()
    menu.popup(hands.columnsButton.mapToGlobal(hands.columnsButton.rect().bottomLeft()))
    app.processEvents()
    menu.grab().save(str(out / "columns.png"))
    menu.hide()
    hands.filtersButton.setChecked(True)
    app.processEvents()
    owner.grab().save(str(out / "hands-filters.png"))
    owner.nb.setCurrentIndex(0)
    results = owner.nb.widget(0)
    results.more_filters.setChecked(True)
    app.processEvents()
    results.limit_combo.showPopup()
    app.processEvents()
    results.limit_combo.view().window().grab().save(str(out / "limits-popup.png"))
    results.limit_combo.hidePopup()


def main():
    from PySide6.QtWidgets import QApplication

    from fpdb_3_legacy.ThemeManager import ThemeManager

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    ThemeManager().set_qt_material_theme("dark_lightgreen.xml", save=False, apply_to_ui=True)
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="fpdb-design-") as temporary:
        config, sql, db, ids, _importer = public_database(root, temporary)
        owner, hands, results = workspace(config, sql, db, ids, temporary)
        capture(owner, hands, app, args.out)
        hands.close_owned_database()
        results.close()
        db.disconnect()
        owner.close()
    print(f"Design captures saved to {args.out}; only public/synthetic hands were used.")


if __name__ == "__main__":
    main()
