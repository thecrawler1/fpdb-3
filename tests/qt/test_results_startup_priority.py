"""Results readiness gates the actual startup handlers before history replay."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QWidget

from fpdb_3_legacy import deferred_page

pytestmark = pytest.mark.qt


class DeferredResults(QObject):
    """Only the readiness contract needed by the startup owner; no database."""

    ready = Signal()
    load_failed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self._ready = False

    def become_ready(self):
        self._ready = True
        self.ready.emit()


@pytest.fixture
def startup(qtbot, monkeypatch):
    path = Path(deferred_page.__file__).with_name("fpdb.pyw")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    actual = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "fpdb")
    names = {"_start_background_auto_import", "_prioritize_startup_results", "_release_startup_results_priority",
             "_auto_import_user_choice"}
    methods = [node for node in actual.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {method.name for method in methods} == names
    cls = ast.ClassDef(
        name="Owner", bases=[ast.Name(id="QWidget", ctx=ast.Load())],
        keywords=[], body=methods, decorator_list=[],
    )
    namespace = {"QWidget": QWidget}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), "exec"), namespace)
    owner = namespace["Owner"]()
    qtbot.addWidget(owner)
    owner.quitting = False
    owner.config = object()
    results = DeferredResults(owner)
    button = QCheckBox(owner)
    import_page = SimpleNamespace(startButton=button)
    ensured_results, ensured_import, started, timers = [], [], [], []

    def ensure_results():
        ensured_results.append(results)
        return results

    def ensure_import():
        ensured_import.append(import_page)
        return import_page

    owner._ensure_results_page = ensure_results
    owner._ensure_auto_import = ensure_import
    button.toggled.connect(started.append)
    button.clicked.connect(owner._auto_import_user_choice)
    monkeypatch.setattr(QTimer, "singleShot", lambda delay, callback: timers.append((delay, callback)))
    yield SimpleNamespace(
        owner=owner, results=results, button=button, timers=timers, started=started,
        ensured_results=ensured_results, ensured_import=ensured_import,
    )
    owner.quitting = True


@pytest.mark.parametrize("signal", ["ready", "load_failed"])
def test_readiness_or_failure_releases_import_once_after_grace(startup, signal):
    owner = startup.owner
    owner._start_background_auto_import()
    owner._start_background_auto_import()
    assert startup.ensured_results == [startup.results]
    assert startup.ensured_import == startup.started == []
    assert [delay for delay, _ in startup.timers] == [1500]
    backstop = startup.timers[0][1]
    getattr(startup.results, signal).emit()
    assert [delay for delay, _ in startup.timers] == [1500, 50]
    assert startup.ensured_import == startup.started == []
    # A real Qt heartbeat can progress during the paint grace period.
    progress = []
    heartbeat = QTimer(owner)
    heartbeat.setSingleShot(True)
    heartbeat.timeout.connect(lambda: progress.append(True))
    heartbeat.start(0)
    QCoreApplication.processEvents()
    assert progress == [True]
    assert not startup.button.isChecked()
    startup.results.ready.emit()
    startup.results.load_failed.emit()
    backstop()
    assert [delay for delay, _ in startup.timers] == [1500, 50]
    grace = startup.timers[1][1]
    grace()
    grace()
    backstop()
    owner._start_background_auto_import()
    assert startup.started == [True]
    assert len(startup.ensured_import) == 1


def test_backstop_releases_unready_results_without_waiting_1500ms(startup):
    startup.owner._start_background_auto_import()
    assert not startup.results._ready
    startup.timers[0][1]()
    assert [delay for delay, _ in startup.timers] == [1500, 50]
    assert startup.started == []
    startup.timers[1][1]()
    startup.results.become_ready()
    startup.timers[0][1]()
    assert startup.started == [True]
    assert len(startup.ensured_import) == 1
    assert [delay for delay, _ in startup.timers] == [1500, 50]


def test_already_ready_results_only_schedule_the_paint_grace(startup):
    startup.results._ready = True
    startup.owner._start_background_auto_import()
    assert [delay for delay, _ in startup.timers] == [50]
    assert startup.started == []
    startup.timers[0][1]()
    assert startup.started == [True]


@pytest.mark.parametrize("guard", ["quitting", "missing_config"])
def test_startup_guard_does_not_create_results_or_importer(startup, guard):
    if guard == "quitting":
        startup.owner.quitting = True
    else:
        startup.owner.config = None
    startup.owner._start_background_auto_import()
    assert startup.ensured_results == startup.ensured_import == startup.timers == []


@pytest.mark.parametrize("phase", ["waiting", "grace"])
def test_quitting_suppresses_pending_release_or_import(startup, phase):
    startup.owner._start_background_auto_import()
    if phase == "grace":
        startup.results.become_ready()
    startup.owner.quitting = True
    startup.results.ready.emit()
    startup.results.load_failed.emit()
    for _, callback in list(startup.timers):
        callback()
    assert startup.ensured_import == startup.started == []
    assert [delay for delay, _ in startup.timers] == ([1500] if phase == "waiting" else [1500, 50])


@pytest.mark.parametrize("phase", ["waiting", "grace"])
def test_manual_start_then_stop_is_not_overridden_by_pending_startup(startup, phase):
    startup.owner._start_background_auto_import()
    if phase == "grace":
        startup.results.become_ready()
    startup.button.click()
    startup.button.click()
    assert startup.started == [True, False]
    startup.results.become_ready()
    for _, callback in list(startup.timers):
        callback()
    startup.owner._start_background_auto_import()
    assert not startup.button.isChecked()
    assert startup.started == [True, False]
