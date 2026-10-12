"""Construction diagnostics on the real Results widget and public cash data."""

from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from time import perf_counter

import pytest
from PySide6.QtCore import QObject, QTimer

from fpdb_3_legacy.GuiResultsViewer import GuiResultsViewer

pytestmark = pytest.mark.qt
STAGES = ("build_styles", "build_controls", "build_table_graph", "heroes", "initial_table", "total")


@pytest.fixture
def public_hand(importer, fresh_db, legacy_config):
    for site in legacy_config.supported_sites.values():
        site.enabled = False
    site = legacy_config.supported_sites["PokerStars"]
    site.enabled = True
    site.screen_name = "Hero"
    fixture = Path(__file__).parents[1] / "fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
    importer.addImportFile(str(fixture), "PokerStars")
    assert importer.runImport()[0] == 1
    stamp = datetime.now(timezone.utc).replace(day=1, hour=12, minute=0, second=0, microsecond=0)
    cursor = fresh_db.get_cursor()
    try:
        cursor.execute("UPDATE Hands SET startTime=?", (stamp.strftime("%Y-%m-%d %H:%M:%S"),))
        cursor.execute("SELECT id FROM Hands")
        hand_id = cursor.fetchone()[0]
    finally:
        cursor.close()
    fresh_db.commit()
    return hand_id


@pytest.mark.parametrize("autoload", [False, True])
def test_constructor_metrics_survive_real_first_load(qtbot, legacy_config, fresh_db, public_hand, autoload):
    started = perf_counter()
    viewer = GuiResultsViewer(legacy_config, db=fresh_db, zone=timezone.utc, autoload=autoload)
    finished = perf_counter()
    qtbot.addWidget(viewer)
    snapshot = viewer.construction_metrics.copy()
    assert set(snapshot) == set(STAGES) | {f"{stage}_cpu_seconds" for stage in STAGES}
    assert all(isinstance(value, float) and isfinite(value) and value >= 0 for value in snapshot.values())
    assert sum(snapshot[stage] for stage in STAGES[:-1]) <= snapshot["total"] <= finished - started
    assert sum(snapshot[f"{stage}_cpu_seconds"] for stage in STAGES[:-1]) <= snapshot["total_cpu_seconds"]
    # The diagnostics must accompany actual QObject/widget construction, not
    # replace any builders or synchronous/automatic initialization paths.
    assert isinstance(viewer.hero_combo, QObject)
    assert viewer._custom_date_timer.parent() is viewer
    assert viewer._custom_date_timer in viewer.findChildren(QTimer)
    assert viewer.layout() is viewer.main_layout
    assert viewer.interval_combo.currentData() == "month"
    assert viewer._setup_complete is (not autoload)
    assert viewer.model.columnCount() == 8
    assert viewer.graph.getPlotItem() is not None
    viewer.resize(1280, 900)
    try:
        with qtbot.waitSignal(viewer.results_ready, timeout=10000):
            viewer.show()
            if not autoload:
                viewer.refresh()
        assert not viewer._has_load_error, viewer.status.text()
        assert [hand.hand_id for hand in viewer.raw_hands] == [public_hand]
        assert viewer.model.rowCount() == 1
        assert len(viewer.graph.listDataItems()) == 4
        assert viewer.construction_metrics == snapshot
    finally:
        viewer.close_owned_database()
        viewer.close()


def test_constructor_metrics_work_without_thread_cpu_clock(qtbot, monkeypatch, legacy_config, fresh_db):
    import fpdb_3_legacy.GuiResultsViewer as module

    def unavailable():
        raise OSError("Thread CPU clock unavailable")

    monkeypatch.setattr(module, "thread_time", unavailable)
    viewer = GuiResultsViewer(legacy_config, db=fresh_db, zone=timezone.utc, autoload=False)
    qtbot.addWidget(viewer)
    try:
        assert set(viewer.construction_metrics) == set(STAGES)
        assert all(isfinite(value) and value >= 0 for value in viewer.construction_metrics.values())
        assert viewer.model.columnCount() == 8
        assert viewer.layout() is viewer.main_layout
    finally:
        viewer.close_owned_database()
        viewer.close()
