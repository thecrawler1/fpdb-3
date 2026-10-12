"""First visible Results page must load imported hands without a Refresh click."""

import gc
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import get_ident

import pytest
from PySide6.QtCore import Qt

from fpdb_3_legacy.Database import Database
from fpdb_3_legacy.deferred_page import DeferredPage
from fpdb_3_legacy.GuiResultsViewer import prepare_results_database

pytestmark = pytest.mark.qt


@pytest.fixture
def imported_first_load_hand(importer, fresh_db, legacy_config):
    """Use only the public, synthetic review hand and a temporary database."""
    for site in legacy_config.supported_sites.values():
        site.enabled = False
    site = legacy_config.supported_sites["PokerStars"]
    site.enabled = True
    site.screen_name = "Hero"
    fixture = Path(__file__).parents[1] / "fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
    importer.addImportFile(str(fixture), "PokerStars")
    assert importer.runImport()[0] == 1
    cursor = fresh_db.get_cursor()
    try:
        cursor.execute("SELECT id FROM Hands")
        hand_ids = [row[0] for row in cursor.fetchall()]
        assert len(hand_ids) == 1
        stamp = datetime.now(timezone.utc).replace(day=1, hour=12, minute=0, second=0, microsecond=0)
        cursor.execute("UPDATE Hands SET startTime=? WHERE id=?", (stamp.strftime("%Y-%m-%d %H:%M:%S"), hand_ids[0]))
        cursor.execute("SELECT id FROM Players WHERE name=?", ("Hero",))
        hero_id = cursor.fetchone()[0]
    finally:
        cursor.close()
    fresh_db.commit()
    assert fresh_db.db_path and fresh_db.db_path != ":memory:"
    return hand_ids[0], hero_id


@pytest.mark.parametrize("owns_database", [False, True], ids=["application-db", "owned-db"])
def test_deferred_results_first_show_loads_public_hand(
    qtbot, monkeypatch, legacy_config, fresh_db, imported_first_load_hand, owns_database,
):
    hand_id, hero_id = imported_first_load_hand
    gui_thread = get_ident()
    borrowed = []
    original = Database.worker_connection

    @contextmanager
    def observe_connection(db):
        with original(db) as connection:
            borrowed.append((db, connection, get_ident()))
            yield connection

    monkeypatch.setattr(Database, "worker_connection", observe_connection)
    # Match the application tab with its borrowed database, plus standalone use.
    # Autoload stays True; showing the wrapper is the only load trigger.
    wrapper = DeferredPage(
        "fpdb_3_legacy.GuiResultsViewer",
        lambda module: module.GuiResultsViewer(legacy_config, db=None if owns_database else fresh_db, zone=timezone.utc),
    )
    qtbot.addWidget(wrapper)
    wrapper.resize(1280, 900)
    try:
        wrapper.show()
        qtbot.waitUntil(lambda: wrapper.page is not None or not wrapper.retry.isHidden(), timeout=10000)
        assert wrapper.page is not None, wrapper.message.text()
        viewer = wrapper.page
        qtbot.waitUntil(
            lambda: viewer._has_load_error or (
                viewer._setup_complete and not viewer._loading
                and len(viewer.raw_hands) == 1 and bool(viewer.graph.listDataItems())
            ),
            timeout=10000,
        )
        assert not viewer._has_load_error, viewer.status.text()
        assert viewer._results_current, viewer.status.text()
        assert viewer.hero_combo.currentData() == hero_id
        assert viewer.interval_combo.currentData() == "month"
        assert [hand.hand_id for hand in viewer.raw_hands] == [hand_id]
        assert len(viewer.total.hands) == 1
        assert viewer.total.profit == viewer.total.ev == -800
        assert viewer.model.rowCount() == viewer.total_model.rowCount() == 1
        for model in (viewer.model, viewer.total_model):
            assert model.index(0, 1).data(Qt.ItemDataRole.UserRole) == 1
            assert model.index(0, 4).data(Qt.ItemDataRole.UserRole) == -800
            assert model.index(0, 6).data(Qt.ItemDataRole.UserRole) == -800
        curves = viewer.graph.listDataItems()
        assert len(curves) == 4
        assert list(curves[0].getOriginalDataset()[1]) == [0, -8]
        assert curves[1].getData()[1][-1] + curves[2].getData()[1][-1] == -8
        assert list(curves[3].getOriginalDataset()[1]) == [0, -8]
        assert viewer.retry_button.isHidden()
        # Both setup discovery and the result query must actually borrow a
        # dedicated connection; never silently pass through a shared fallback.
        assert len(borrowed) >= 2
        assert all(db is viewer.db and connection is not None
                   and connection is not db.connection and thread != gui_thread
                   for db, connection, thread in borrowed)
    finally:
        wrapper.close_owned_database()
        wrapper.close()


class GuiThreadOnly:
    """Fail on any worker access to the GUI's original connection or cursor."""

    def __init__(self, target):
        self._target = target
        self._owner = get_ident()
        self.worker_accesses = []

    def __getattr__(self, name):
        if get_ident() != self._owner:
            self.worker_accesses.append(name)
            raise AssertionError(f"Worker touched main shared database resource: {name}")
        return getattr(self._target, name)


def test_prepare_results_database_isolates_borrowed_worker_connection(
    monkeypatch, fresh_db, legacy_config, imported_first_load_hand,
):
    _, hero_id = imported_first_load_hand
    connection_guard = GuiThreadOnly(fresh_db.connection)
    cursor_guard = GuiThreadOnly(fresh_db.cursor)
    borrowed = []
    original = fresh_db.worker_connection

    @contextmanager
    def observe_connection():
        with original() as connection:
            assert connection is not None
            assert connection is not connection_guard._target
            borrowed.append((connection, get_ident()))
            yield connection

    # Restore the guards before fresh_db teardown. The real discovery methods
    # run on the facade with the real pool/SQL, with no mocked hero responses.
    with monkeypatch.context() as patch:
        patch.setattr(fresh_db, "connection", connection_guard)
        patch.setattr(fresh_db, "cursor", cursor_guard)
        patch.setattr(fresh_db, "worker_connection", observe_connection)
        with ThreadPoolExecutor(max_workers=1) as executor:
            result_db, heroes = executor.submit(
                prepare_results_database, legacy_config, fresh_db.sql, fresh_db,
            ).result(timeout=10)
        assert result_db is fresh_db
        assert heroes == [("Hero · PokerStars", hero_id)]
        assert fresh_db.connection is connection_guard
        assert fresh_db.cursor is cursor_guard
        assert not connection_guard.worker_accesses
        assert not cursor_guard.worker_accesses
    assert len(borrowed) == 1
    assert borrowed[0][1] != get_ident()
    # The same connection is returned to the real pool, ready for the query.
    with fresh_db.worker_connection() as connection:
        assert connection is borrowed[0][0]
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM Hands")
            assert cursor.fetchone()[0] == 1
        finally:
            cursor.close()


@pytest.mark.parametrize("failure", ["discovery", "cursor"])
def test_prepare_failure_preserves_borrowed_and_gui_connections(
    monkeypatch, fresh_db, legacy_config, imported_first_load_hand, failure,
):
    import fpdb_3_legacy.GuiResultsViewer as module

    connection_guard = GuiThreadOnly(fresh_db.connection)
    cursor_guard = GuiThreadOnly(fresh_db.cursor)
    original = fresh_db.worker_connection
    borrowed = []

    class FailingCursorConnection:
        def cursor(self):
            raise ValueError("worker cursor failed")

    @contextmanager
    def observe_connection():
        with original() as connection:
            assert connection is not None and connection is not connection_guard._target
            borrowed.append(connection)
            yield FailingCursorConnection() if failure == "cursor" else connection

    def fail_discovery(config, reader):
        assert reader.connection is borrowed[0]
        assert reader.cursor is not cursor_guard._target
        reader.cursor.execute("SELECT COUNT(*) FROM Hands")
        assert reader.cursor.fetchone()[0] == 1
        raise ValueError("hero discovery failed")

    with monkeypatch.context() as patch:
        patch.setattr(fresh_db, "connection", connection_guard)
        patch.setattr(fresh_db, "cursor", cursor_guard)
        patch.setattr(fresh_db, "worker_connection", observe_connection)
        patch.setattr(module, "discover_heroes", fail_discovery)
        message = "hero discovery failed" if failure == "discovery" else "worker cursor failed"
        with ThreadPoolExecutor(max_workers=1) as executor:
            with pytest.raises(ValueError, match=message):
                executor.submit(
                    module.prepare_results_database, legacy_config, fresh_db.sql, fresh_db,
                ).result(timeout=10)
        # Exception tracebacks can retain the facade; exercise its destructor
        # before checking that neither borrowed resource has been closed.
        gc.collect()
        assert fresh_db.connection is connection_guard
        assert fresh_db.cursor is cursor_guard
        assert not connection_guard.worker_accesses
        assert not cursor_guard.worker_accesses
        fresh_db.cursor.execute("SELECT COUNT(*) FROM Hands")
        assert fresh_db.cursor.fetchone()[0] == 1
        cursor = fresh_db.get_cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM Hands")
            assert cursor.fetchone()[0] == 1
        finally:
            cursor.close()
    assert len(borrowed) == 1
    with fresh_db.worker_connection() as connection:
        assert connection is borrowed[0]
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM Hands")
            assert cursor.fetchone()[0] == 1
        finally:
            cursor.close()
