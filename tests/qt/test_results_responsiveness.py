"""Regression budgets for the click-to-open path and Qt's event-loop latency."""

from datetime import datetime, timedelta, timezone
from time import perf_counter, sleep

import pytest
from PySide6.QtCore import QTimer

from fpdb_3_legacy.GuiResultsViewer import GuiResultsViewer

pytestmark = pytest.mark.qt


def heartbeat(qtbot):
    """Measure stalls, not just how quickly a background query finishes."""
    ticks = [perf_counter()]
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(perf_counter()))
    timer.start()
    return timer, ticks


def assert_responsive(ticks):
    gaps = [later - earlier for earlier, later in zip(ticks, ticks[1:])]
    assert len(gaps) >= 3, "Qt must continue handling events while loading"
    assert max(gaps) < .25, f"Results froze Qt for {max(gaps):.3f}s"


def test_slow_database_setup_does_not_block_results_open(monkeypatch, qtbot, legacy_config, fresh_db):
    import fpdb_3_legacy.GuiResultsViewer as module

    class SlowDatabase(module.Database.Database):
        def __init__(self, *args, **kwargs):
            sleep(.6)  # Connection/schema initialization was on the click handler.
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(module.Database, "Database", SlowDatabase)
    timer, ticks = heartbeat(qtbot)
    started = perf_counter()
    widget = GuiResultsViewer(legacy_config, fresh_db.sql)
    qtbot.addWidget(widget)
    widget.show()
    opening = perf_counter() - started
    try:
        qtbot.waitUntil(lambda: widget.db is not None and not widget._loading, timeout=5000)
        qtbot.wait(50)
        assert opening < .25, f"Opening Results took {opening:.3f}s"
        assert_responsive(ticks)
    finally:
        timer.stop()
        widget.close_owned_database()


def test_large_history_processing_does_not_freeze_qt(qtbot, legacy_config, fresh_db):
    widget = GuiResultsViewer(legacy_config, db=fresh_db, zone=timezone.utc, autoload=False)
    qtbot.addWidget(widget)
    widget.show()
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [(i, stamp + timedelta(seconds=i), 100, 50, 10, 1, 1, 0, 1, False, "holdem", "nl")
            for i in range(100_000)]
    timer, ticks = heartbeat(qtbot)
    try:
        started = perf_counter()
        widget._receive_rows(widget._generation, rows)
        callback_time = perf_counter() - started
        qtbot.waitUntil(lambda: len(widget.total.hands) == len(rows), timeout=10000)
        qtbot.wait(60)
        assert callback_time < .25, f"Result delivery blocked Qt for {callback_time:.3f}s"
        assert widget.total.profit == 10_000_000
        started = perf_counter()
        widget.select_total()
        selection_time = perf_counter() - started
        assert selection_time < .25, f"Selecting Total blocked Qt for {selection_time:.3f}s"
        qtbot.waitUntil(lambda: bool(widget.graph.listDataItems()), timeout=10000)
        assert widget.graph.listDataItems()[0].getOriginalDataset()[1][-1] == 100_000
        qtbot.wait(40)
        assert_responsive(ticks)
    finally:
        timer.stop()
        widget.close()
