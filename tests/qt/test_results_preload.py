"""Exercise the application's Results cache with real Qt ownership and queries."""

import ast
import contextlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Signal
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget
from shiboken6 import isValid

from fpdb_3_legacy import deferred_page
from fpdb_3_legacy.automatic_loading import install_automatic_loading
from fpdb_3_legacy.background_tasks import drain_background_tasks
from fpdb_3_legacy.ui_instrumentation import TabOpenProfiler, perf_level

pytestmark = pytest.mark.qt


@pytest.fixture
def owner(qtbot, legacy_config, fresh_db):
    """Run production handlers without importing the application entry point."""
    path = Path(deferred_page.__file__).with_name("fpdb.pyw")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = {
        "_ensure_results_page", "_discard_results_page", "_schedule_results_preload",
        "_preload_results", "paintEvent", "tab_results", "close_tab",
        "refresh_live_views", "open_tab", "add_and_display_tab", "display_tab",
        "reload_config",
    }
    methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {method.name for method in methods} == names
    cls = ast.ClassDef(name="Owner", bases=[ast.Name(id="QWidget", ctx=ast.Load())],
                       keywords=[], body=methods, decorator_list=[])
    namespace = {
        "QWidget": QWidget, "contextlib": contextlib, "time": time,
        "TabOpenProfiler": TabOpenProfiler, "perf_level": perf_level,
        "log": logging.getLogger(__name__),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), "exec"), namespace)
    window = namespace["Owner"]()
    qtbot.addWidget(window)
    window.config, window.sql, window.db = legacy_config, fresh_db.sql, fresh_db
    window.quitting = False
    window.threads = []
    window.nb_tab_names = []
    window.nb = QTabWidget(window)
    QVBoxLayout(window).addWidget(window.nb)
    window._results_page = None
    window._results_preload_ready = False
    window._results_first_paint = False
    window._open_result_hands = lambda _ids: None
    window.tab_bulk_import = lambda _widget: None
    yield window
    window.quitting = True
    window._discard_results_page()
    drain_background_tasks()


@pytest.fixture
def results_stub(monkeypatch):
    class Results(QWidget):
        hands_requested = Signal(object)
        import_requested = Signal()

        def __init__(self, config, sql, *, db):
            super().__init__()
            self.config, self.sql, self.db = config, sql, db
            self.loads = 0
            self.closed = False
            install_automatic_loading(self, self.refresh)

        def refresh(self):
            self.loads += 1

        def preload(self):
            self._fpdb_auto_loader.dirty = False
            self.refresh()

        def shutdown_workers(self):
            self.closed = True

        def close_owned_database(self):
            self.shutdown_workers()

    monkeypatch.setattr(deferred_page, "import_module", lambda _name: SimpleNamespace(GuiResultsViewer=Results))
    return Results


def test_preload_waits_for_first_paint_and_profile_ready(owner, results_stub, qtbot):
    owner._schedule_results_preload()
    qtbot.wait(180)
    assert owner._results_page is None
    owner.show()
    qtbot.waitUntil(lambda: owner._results_first_paint)
    assert owner._results_page is None
    owner._results_preload_ready = True
    owner._schedule_results_preload()
    qtbot.waitUntil(lambda: owner._results_page is not None and owner._results_page.page is not None)
    wrapper = owner._results_page
    assert wrapper.parentWidget() is owner
    assert not wrapper.isVisible()
    assert not wrapper.page.isVisible()
    assert wrapper.page.loads == 1
    assert owner.threads == [wrapper]
    assert owner.nb.count() == 0
    owner.tab_results(None)
    owner.tab_results(None)
    qtbot.wait(30)
    assert owner.nb.count() == 1
    assert owner.nb.currentWidget() is wrapper
    assert owner._results_page is wrapper
    assert wrapper.page.loads == 1


def test_import_before_child_construction_stays_dirty(owner, results_stub, qtbot):
    wrapper = owner._ensure_results_page()
    assert wrapper.page is None
    owner.refresh_live_views()
    qtbot.waitUntil(lambda: wrapper.page is not None)
    assert wrapper.page.loads == 1
    assert wrapper._fpdb_auto_loader.dirty
    owner.show()
    owner.tab_results(None)
    qtbot.waitUntil(lambda: wrapper.page.loads == 2)
    assert not wrapper._fpdb_auto_loader.dirty


def test_close_reopen_clears_cache_before_delete_later(owner, results_stub, qtbot):
    owner.show()
    owner.tab_results(None)
    old = owner._results_page
    qtbot.waitUntil(lambda: old.page is not None)
    owner.close_tab(owner.nb.indexOf(old))
    assert owner._results_page is None
    assert old not in owner.threads
    assert old._closed and old.page.closed
    # Reopening in the same event-loop turn must not reuse a deleteLater widget.
    owner.tab_results(None)
    replacement = owner._results_page
    assert replacement is not old
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(old)
    assert isValid(replacement)
    qtbot.waitUntil(lambda: replacement.page is not None)
    assert replacement.page.db is owner.db


@pytest.mark.parametrize("changed", ["config", "sql", "db"])
def test_changed_context_retires_open_cache(owner, results_stub, qtbot, changed):
    owner.show()
    owner.tab_results(None)
    old = owner._results_page
    qtbot.waitUntil(lambda: old.page is not None)
    setattr(owner, changed, object())
    owner.tab_results(None)
    replacement = owner._results_page
    assert replacement is not old
    assert old._closed
    assert owner.threads == [replacement]
    assert owner.nb.count() == 1
    qtbot.waitUntil(lambda: replacement.page is not None)
    assert replacement.page.config is owner.config
    assert replacement.page.sql is owner.sql
    assert replacement.page.db is owner.db


def test_deleted_hidden_cache_is_rebuilt(owner, results_stub, qtbot):
    old = owner._ensure_results_page()
    qtbot.waitUntil(lambda: old.page is not None)
    old.close_owned_database()
    old.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(old)
    replacement = owner._ensure_results_page()
    assert replacement is not old
    assert owner.threads == [replacement]
    qtbot.waitUntil(lambda: replacement.page is not None)


def test_configuration_reload_retires_hidden_cache(owner, results_stub, qtbot):
    old = owner._ensure_results_page()
    qtbot.waitUntil(lambda: old.page is not None)
    new_config = object()
    manager = SimpleNamespace(
        initialized=True,
        reload_config=lambda: (True, "Configuration changed", []),
        get_config=lambda: new_config,
    )
    owner.reload_config.__func__.__globals__["ConfigurationManager"] = lambda: manager
    owner.info_box = lambda *_args: None
    owner.nb.addTab(QWidget(), "Help")
    owner.nb_tab_names.append("Help")
    owner.show()
    qtbot.waitUntil(lambda: owner._results_first_paint)
    owner._results_preload_ready = True
    owner.reload_config()
    assert owner.config is new_config
    assert old._closed
    assert owner._results_page is None
    assert old not in owner.threads
    qtbot.waitUntil(lambda: owner._results_page is not None and owner._results_page.page is not None)
    assert owner._results_page.page.config is new_config
    assert owner._results_page.page.db is owner.db
    assert not owner._results_page.isVisible()


@pytest.fixture
def public_results_hand(importer, fresh_db, legacy_config):
    for site in legacy_config.supported_sites.values():
        site.enabled = False
    site = legacy_config.supported_sites["PokerStars"]
    site.enabled, site.screen_name = True, "Hero"
    path = Path(__file__).parents[1] / "fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
    importer.addImportFile(str(path), "PokerStars")
    assert importer.runImport()[0] == 1
    cursor = fresh_db.get_cursor()
    try:
        cursor.execute("SELECT id FROM Hands")
        hand_id = cursor.fetchone()[0]
        stamp = datetime.now(timezone.utc).replace(day=1, hour=12, minute=0, second=0, microsecond=0)
        cursor.execute("UPDATE Hands SET startTime=? WHERE id=?", (stamp.strftime("%Y-%m-%d %H:%M:%S"), hand_id))
    finally:
        cursor.close()
    fresh_db.commit()
    return hand_id


def test_real_hidden_results_fully_load_and_click_has_no_queries(
    owner, qtbot, monkeypatch, fresh_db, public_results_hand,
):
    from fpdb_3_legacy.GuiResultsViewer import GuiResultsViewer

    assert callable(getattr(GuiResultsViewer, "preload", None)), "Main-agent dependency: GuiResultsViewer.preload()"
    requests = []
    statements = []
    original = fresh_db.worker_connection

    @contextlib.contextmanager
    def observe_connection():
        with original() as connection:
            requests.append(connection)
            connection.set_trace_callback(statements.append)
            try:
                yield connection
            finally:
                connection.set_trace_callback(None)

    monkeypatch.setattr(fresh_db, "worker_connection", observe_connection)
    owner.show()
    owner._preload_results()
    wrapper = owner._results_page
    qtbot.waitUntil(lambda: wrapper.page is not None, timeout=10000)
    viewer = wrapper.page
    qtbot.waitUntil(lambda: viewer._setup_complete and not viewer._loading
                   and len(viewer.raw_hands) == 1 and bool(viewer.graph.listDataItems()), timeout=10000)
    assert viewer.db is fresh_db
    assert not wrapper.isVisible() and not viewer.isVisible()
    assert viewer._results_current and not viewer._has_load_error
    assert [hand.hand_id for hand in viewer.raw_hands] == [public_results_hand]
    assert viewer.model.rowCount() == viewer.total_model.rowCount() == 1
    assert len(viewer.graph.listDataItems()) == 4
    assert len(requests) >= 2
    before_click = len(requests)
    sql_before_click = len(statements)
    owner.tab_results(None)
    owner.tab_results(None)
    qtbot.wait(150)
    assert owner._results_page is wrapper
    assert owner.nb.currentWidget() is wrapper
    assert viewer.isVisible()
    assert len(requests) == before_click
    assert len(statements) == sql_before_click
    assert not viewer._fpdb_auto_loader.dirty

    wrapper.hide()
    owner.refresh_live_views()
    qtbot.wait(30)
    assert viewer._fpdb_auto_loader.dirty
    assert len(requests) == before_click
    wrapper.show()
    qtbot.waitUntil(lambda: len(requests) > before_click and not viewer._loading)
    assert not viewer._fpdb_auto_loader.dirty
    assert viewer._results_current
    assert viewer.db is fresh_db
