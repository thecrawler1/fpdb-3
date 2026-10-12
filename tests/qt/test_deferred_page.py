"""Deferred imports must leave Qt responsive and build widgets on its GUI thread."""

import ast
from pathlib import Path
from threading import Event
from time import perf_counter, sleep
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QTabWidget, QWidget
from shiboken6 import isValid

from fpdb_3_legacy import deferred_page
from fpdb_3_legacy.automatic_loading import install_automatic_loading
from fpdb_3_legacy.background_tasks import TaskWorker

pytestmark = pytest.mark.qt


class LoadedChild(QWidget):
    """A lightweight page with the lifecycle hooks used by DeferredPage."""

    def shutdown_workers(self):
        pass

    def close_owned_database(self):
        pass


@pytest.fixture
def make_page(qtbot):
    pages = []

    def create(module, build):
        page = deferred_page.DeferredPage(module, build)
        pages.append(page)
        qtbot.addWidget(page)
        return page

    yield create
    # Wait for real workers even when an assertion fails, before Qt deletes them.
    for page in pages:
        worker = page._worker
        page.close()
        if worker is not None and isValid(worker):
            worker.wait()


def test_delayed_import_keeps_gui_responsive_and_builds_on_main_thread(
    monkeypatch, qtbot, qapp, make_page,
):
    imported = SimpleNamespace(name="delayed_module")
    import_started = Event()
    import_finished = Event()
    import_threads = []
    requested_modules = []
    built = []
    ticks = []

    def delayed_import(name):
        requested_modules.append(name)
        import_threads.append(QThread.currentThread())
        import_started.set()
        sleep(.6)
        import_finished.set()
        return imported

    def build(module):
        built.append((module, QThread.currentThread()))
        return LoadedChild()

    monkeypatch.setattr(deferred_page, "import_module", delayed_import)
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(
        lambda: ticks.append((perf_counter(), import_started.is_set() and not import_finished.is_set()))
    )
    timer.start()
    try:
        started = perf_counter()
        page = make_page("delayed_module", build)
        page.show()
        opening = perf_counter() - started
        assert opening < .25, f"Initial show blocked Qt for {opening:.3f}s"
        assert page.page is None
        assert page.message.isVisible()
        assert not page.retry.isVisible()
        qtbot.waitUntil(lambda: page.page is not None, timeout=5000)
        qtbot.wait(30)

        assert isinstance(page._worker, TaskWorker)
        assert isinstance(page._worker, QThread)
        assert requested_modules == ["delayed_module"]
        assert import_threads[0] != qapp.thread()
        assert built == [(imported, qapp.thread())]
        assert page.page.thread() == qapp.thread()
        assert page.page.parentWidget() is page
        assert page.layout().indexOf(page.page) >= 0
        assert page.page.isVisible()
        assert not page.message.isVisible()
        assert not page.retry.isVisible()

        during_import = [stamp for stamp, importing in ticks if importing]
        assert len(during_import) >= 3, "Qt timer must fire throughout the slow import"
        gaps = [later - earlier for earlier, later in zip(during_import, during_import[1:])]
        gaps.extend((during_import[0] - started, perf_counter() - during_import[-1]))
        assert max(gaps) < .25, f"Deferred import stalled Qt for {max(gaps):.3f}s"
    finally:
        timer.stop()


def test_loaded_child_auto_loader_receives_invalidation(monkeypatch, qtbot, make_page):
    imported = SimpleNamespace(name="automatic_module")
    loads = []
    monkeypatch.setattr(deferred_page, "import_module", lambda _name: imported)

    def build(module):
        assert module is imported
        child = LoadedChild()
        install_automatic_loading(child, lambda: loads.append(True))
        return child

    page = make_page("automatic_module", build)
    assert page._fpdb_auto_loader is None
    page.show()
    qtbot.waitUntil(lambda: len(loads) == 1)
    assert page._fpdb_auto_loader is page.page._fpdb_auto_loader

    page._fpdb_auto_loader.invalidate()
    qtbot.waitUntil(lambda: len(loads) == 2)
    page.hide()
    page._fpdb_auto_loader.invalidate()
    qtbot.wait(30)
    assert len(loads) == 2
    page.show()
    qtbot.waitUntil(lambda: len(loads) == 3)


def test_import_error_shows_retry_and_retry_loads_child(monkeypatch, qtbot, qapp, make_page):
    imported = SimpleNamespace(name="retry_module")
    attempts = []
    built = []

    def flaky_import(name):
        attempts.append((name, QThread.currentThread()))
        sleep(.05)
        if len(attempts) == 1:
            raise ImportError("simulated missing dependency")
        return imported

    def build(module):
        built.append((module, QThread.currentThread()))
        return LoadedChild()

    monkeypatch.setattr(deferred_page, "import_module", flaky_import)
    page = make_page("retry_module", build)
    page.show()
    qtbot.waitUntil(lambda: page.retry.isVisible())
    qtbot.waitUntil(lambda: not page._worker.isRunning())
    failed_worker = page._worker
    assert page.page is None
    assert built == []
    assert page.message.isVisible()
    assert "simulated missing dependency" in page.message.text()

    qtbot.mouseClick(page.retry, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: page.page is not None)
    assert page._worker is not failed_worker
    assert [name for name, _thread in attempts] == ["retry_module", "retry_module"]
    assert all(thread != qapp.thread() for _name, thread in attempts)
    assert built == [(imported, qapp.thread())]
    assert page.page.isVisible()
    assert not page.retry.isVisible()
    assert not page.message.isVisible()


def test_close_during_import_is_responsive_and_does_not_build_child(monkeypatch, qtbot, make_page):
    import_started = Event()
    import_finished = Event()
    built = []
    finished_at = []
    ticks = []

    def delayed_import(_name):
        import_started.set()
        sleep(.6)
        finished_at.append(perf_counter())
        import_finished.set()
        return SimpleNamespace(name="closed_module")

    def build(module):
        built.append(module)
        return LoadedChild()

    monkeypatch.setattr(deferred_page, "import_module", delayed_import)
    page = make_page("closed_module", build)
    page.show()
    qtbot.waitUntil(import_started.is_set)
    assert not import_finished.is_set()
    assert page.page is None
    worker = page._worker
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(perf_counter()) if not import_finished.is_set() else None)
    timer.start()
    try:
        closing_started = perf_counter()
        page.close()
        closing_time = perf_counter() - closing_started
        qtbot.waitUntil(import_finished.is_set)
        qtbot.waitUntil(lambda: not isValid(worker) or not worker.isRunning())
        # Deliver any queued completion signal after closing the wrapper.
        qtbot.wait(50)
    finally:
        timer.stop()

    assert closing_time < .25, f"Closing during import blocked Qt for {closing_time:.3f}s"
    assert len(ticks) >= 3, "Qt timer must keep firing after close while import finishes"
    boundaries = [closing_started, *ticks, finished_at[0]]
    gaps = [later - earlier for earlier, later in zip(boundaries, boundaries[1:])]
    assert max(gaps) < .25, f"Closing during import stalled Qt for {max(gaps):.3f}s"
    assert built == []
    assert page.page is None
    assert not page.isVisible()


def test_actual_tab_results_defers_import_and_borrows_owner_database(monkeypatch, qtbot, qapp):
    """Execute the production tab handler without starting the full application."""
    source_path = Path(deferred_page.__file__).with_name("fpdb.pyw")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    handlers = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in ("tab_results", "_ensure_results_page", "_discard_results_page")
    ]
    assert len(handlers) == 3
    namespace = {}
    exec(compile(ast.Module(body=handlers, type_ignores=[]), str(source_path), "exec"), namespace)

    built = []
    imports = []
    import_started = Event()

    class ResultsStub(LoadedChild):
        hands_requested = Signal(object)
        import_requested = Signal()

        def __init__(self, config, sql, *, db):
            super().__init__()
            self.db = db
            built.append((config, sql, db, QThread.currentThread()))

        def preload(self):
            pass

    def delayed_import(name):
        imports.append((name, QThread.currentThread()))
        import_started.set()
        sleep(.6)
        return SimpleNamespace(GuiResultsViewer=ResultsStub)

    monkeypatch.setattr(deferred_page, "import_module", delayed_import)

    class Owner(QWidget):
        def __init__(self):
            super().__init__()
            self.config = object()
            self.sql = object()
            self.db = object()
            self.opened = []
            self.hand_requests = []
            self.import_requests = []
            self.threads = []
            self.nb = QTabWidget(self)

        def open_tab(self, name, build, **options):
            self.opened.append((name, options))
            self.page = build()
            qtbot.addWidget(self.page)
            self.page.show()

        def _open_result_hands(self, hand_ids):
            self.hand_requests.append(hand_ids)

        def tab_bulk_import(self, widget):
            self.import_requests.append(widget)

    Owner._ensure_results_page = namespace["_ensure_results_page"]
    Owner._discard_results_page = namespace["_discard_results_page"]
    owner = Owner()
    qtbot.addWidget(owner)
    owner.show()
    started = perf_counter()
    namespace["tab_results"](owner, None)
    opening = perf_counter() - started
    try:
        assert opening < .25, f"Results tab handler blocked Qt for {opening:.3f}s"
        assert owner.opened == [("Results", {"allow_multiple": False})]
        assert isinstance(owner.page, deferred_page.DeferredPage)
        assert owner.page.page is None
        assert built == []
        qtbot.waitUntil(import_started.is_set)
        qtbot.waitUntil(lambda: owner.page.page is not None, timeout=5000)
        assert [name for name, _thread in imports] == ["fpdb_3_legacy.GuiResultsViewer"]
        assert imports[0][1] != qapp.thread()
        assert built == [(owner.config, owner.sql, owner.db, qapp.thread())]
        assert owner.page.page.db is owner.db
        assert owner.page.page.isVisible()

        owner.page.page.hands_requested.emit([17, 23])
        owner.page.page.import_requested.emit()
        assert owner.hand_requests == [[17, 23]]
        assert owner.import_requests == [None]
    finally:
        worker = owner.page._worker
        owner.page.close()
        if worker is not None and isValid(worker):
            worker.wait()
