"""Interactive priority follows real Results loads, errors and worker lifetimes."""

from datetime import datetime, timezone
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QDate, QObject, Signal
from PySide6.QtTest import QSignalSpy

from fpdb_3_legacy import GuiAutoImport, deferred_page, ui_work_priority
from fpdb_3_legacy.background_tasks import drain_background_tasks

pytestmark = pytest.mark.qt


class ControlledQuery(QObject):
    finished = Signal(str, list, list)
    error = Signal(str)

    def __init__(self, db, name, query, params):
        super().__init__()
        self.db, self.name, self.query, self.params = db, name, query, params
        self.started = self.done = False

    def start(self):
        self.started = True

    def isFinished(self):
        return self.done

    def finish(self, *, repeat=1, malformed=False):
        # Execute the production query against the temporary public database;
        # only delivery is controlled. Larger graphs derive from that same row.
        with self.db.worker_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(self.query, self.params)
                rows = list(cursor.fetchall())
                columns = [column[0] for column in cursor.description]
            finally:
                cursor.close()
        if repeat > 1:
            assert len(rows) == 1
            row = rows[0]
            rows = [(int(row[0]) + index, *row[1:]) for index in range(repeat)]
        if malformed:
            rows = [("malformed public row",)]
        self.done = True
        self.finished.emit(self.name, rows, columns)

    def fail(self):
        self.done = True
        self.error.emit("controlled query failure")


class ControlledTask(QObject):
    completed = Signal(object)
    error = Signal(str)

    def __init__(self, task):
        super().__init__()
        self.task = task
        self.started = self.done = self.cancelled = False

    def start(self):
        self.started = True

    def isFinished(self):
        return self.done

    def cancel(self):
        self.cancelled = True

    def finish(self):
        result = self.task()
        self.done = True
        self.completed.emit(result)

    def fail(self):
        self.done = True
        self.error.emit("controlled graph failure")


@pytest.fixture
def public_hand(qapp, importer, fresh_db, legacy_config):
    for site in legacy_config.supported_sites.values():
        site.enabled = False
    site = legacy_config.supported_sites["PokerStars"]
    site.enabled = True
    site.screen_name = "Hero"
    fixture = Path(__file__).parents[1] / "fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
    importer.setCallHud(False)
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


@pytest.fixture
def pages(qtbot, monkeypatch, legacy_config, fresh_db, public_hand):
    assert not ui_work_priority.interactive_load_pending()
    viewers, wrappers, gates = [], [], []

    def viewer():
        import fpdb_3_legacy.GuiResultsViewer as results

        monkeypatch.setattr(results, "DbWorker", ControlledQuery)
        monkeypatch.setattr(results, "TaskWorker", ControlledTask)
        widget = results.GuiResultsViewer(legacy_config, db=fresh_db, zone=timezone.utc, autoload=False)
        qtbot.addWidget(widget)
        viewers.append(widget)
        return widget

    def wrapper(import_task):
        monkeypatch.setattr(deferred_page, "import_module", import_task)
        widget = deferred_page.DeferredPage("public_results", lambda _module: viewer(), preload=True)
        qtbot.addWidget(widget)
        wrappers.append(widget)
        return widget

    yield viewer, wrapper, gates
    for widget in (*wrappers, *viewers):
        widget.close_owned_database()
        widget.close()
    for gate in gates:
        gate.set()
    drain_background_tasks()
    assert not ui_work_priority.interactive_load_pending(), "Closed Results left an interactive token active"


@pytest.mark.parametrize("outcome", ["ready", "error"])
def test_closing_one_pending_viewer_keeps_other_viewer_priority(pages, outcome):
    make_viewer, _, _ = pages
    first, second = make_viewer(), make_viewer()
    first.refresh()
    second.refresh()
    assert first._interactive_token is not second._interactive_token
    assert first._interactive_token is not None and second._interactive_token is not None
    query = first._workers[-1]
    first.close()
    assert first._interactive_token is None
    assert ui_work_priority.interactive_load_pending()
    query.finish()  # Late delivery from the closed page must not steal priority.
    assert ui_work_priority.interactive_load_pending()
    signal = second.results_ready if outcome == "ready" else second.results_failed
    seen = QSignalSpy(signal)
    if outcome == "ready":
        second._workers[-1].finish()
        assert len(second.raw_hands) == 1 and len(second.graph.listDataItems()) == 4
    else:
        second._workers[-1].fail()
        assert second._has_load_error
    assert seen.count() == 1
    assert second._interactive_token is None
    assert not ui_work_priority.interactive_load_pending()


def test_invalid_dates_release_only_that_viewers_pending_load(pages):
    make_viewer, _, _ = pages
    invalid, other = make_viewer(), make_viewer()
    invalid.refresh()
    obsolete = invalid._workers[-1]
    other.refresh()
    controls = (invalid.interval_combo, invalid.from_date, invalid.to_date)
    for control in controls:
        control.blockSignals(True)
    try:
        invalid.interval_combo.setCurrentIndex(invalid.interval_combo.findData("custom"))
        invalid.from_date.setDate(QDate(2026, 2, 2))
        invalid.to_date.setDate(QDate(2026, 2, 1))
    finally:
        for control in controls:
            control.blockSignals(False)
    failed = QSignalSpy(invalid.results_failed)
    invalid.refresh()
    assert failed.count() == 1 and "Start date" in invalid.status.text()
    assert invalid._interactive_token is None
    assert ui_work_priority.interactive_load_pending()
    obsolete.finish()
    assert ui_work_priority.interactive_load_pending()
    other._workers[-1].fail()
    assert not ui_work_priority.interactive_load_pending()


@pytest.mark.parametrize("failure", ["query", "parse", "inline_graph"])
def test_failure_releases_own_priority_and_retry_acquires_it_again(pages, monkeypatch, failure):
    import fpdb_3_legacy.GuiResultsViewer as results

    make_viewer, _, _ = pages
    failing, other = make_viewer(), make_viewer()
    failing.refresh()
    other.refresh()
    failed = QSignalSpy(failing.results_failed)
    with monkeypatch.context() as patch:
        if failure == "inline_graph":
            def bad_curve(*_args, **_kwargs):
                raise ValueError("controlled inline graph failure")

            patch.setattr(results, "profit_curves", bad_curve)
        if failure == "query":
            failing._workers[-1].fail()
        else:
            failing._workers[-1].finish(malformed=failure == "parse")
    assert failed.count() == 1
    assert failing._interactive_token is None
    assert ui_work_priority.interactive_load_pending()
    failing.refresh()
    assert failing._interactive_token is not None, "Retry did not reacquire interactive priority"
    other._workers[-1].fail()
    assert ui_work_priority.interactive_load_pending()
    ready = QSignalSpy(failing.results_ready)
    failing._workers[-1].finish()
    assert ready.count() == 1
    assert not ui_work_priority.interactive_load_pending()


@pytest.mark.parametrize("outcome", ["ready", "error", "close"])
def test_priority_covers_query_preparation_and_pending_graph(pages, outcome):
    make_viewer, _, _ = pages
    viewer = make_viewer()
    viewer.refresh()
    viewer._workers[-1].finish(repeat=1001)
    assert viewer._tasks[-1].category == "rows"
    assert ui_work_priority.interactive_load_pending()
    viewer._tasks[-1].finish()
    curve = viewer._tasks[-1]
    assert curve.category == "curve" and viewer._pending_curve is not None
    assert viewer._interactive_token is not None
    assert ui_work_priority.interactive_load_pending()
    if outcome == "ready":
        ready = QSignalSpy(viewer.results_ready)
        curve.finish()
        assert ready.count() == 1
        assert len(viewer.raw_hands) == 1001 and len(viewer.graph.listDataItems()) == 4
    elif outcome == "error":
        failed = QSignalSpy(viewer.results_failed)
        curve.fail()
        assert failed.count() == 1
    else:
        viewer.close()
        assert curve.cancelled
        curve.finish()  # Cancelled computation arriving late cannot regain priority.
    assert viewer._interactive_token is None
    assert not ui_work_priority.interactive_load_pending()


@pytest.mark.parametrize("outcome", ["ready", "error"])
def test_wrapper_and_child_release_both_tokens_on_query_outcome(qtbot, pages, outcome):
    _, make_wrapper, _ = pages
    wrapper = make_wrapper(lambda _name: object())
    qtbot.waitUntil(lambda: wrapper.page is not None or not wrapper.retry.isHidden(), timeout=5000)
    assert wrapper.page is not None, wrapper.message.text()
    child = wrapper.page
    assert child._workers[-1].started
    assert wrapper._interactive_token is not None and child._interactive_token is not None
    assert wrapper._interactive_token is not child._interactive_token
    assert ui_work_priority.interactive_load_pending()
    signal = wrapper.ready if outcome == "ready" else wrapper.load_failed
    seen = QSignalSpy(signal)
    if outcome == "ready":
        child._workers[-1].finish()
    else:
        child._workers[-1].fail()
    assert seen.count() == 1
    assert wrapper._interactive_token is child._interactive_token is None
    assert not ui_work_priority.interactive_load_pending()


@pytest.mark.parametrize("outcome", ["import_error", "close"])
def test_wrapper_releases_priority_before_blocked_import_finishes(qtbot, pages, outcome):
    _, make_wrapper, gates = pages
    entered, release = Event(), Event()
    gates.append(release)

    def import_task(_name):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("Import gate was not released")
        if outcome == "import_error":
            raise ImportError("controlled import failure")
        return object()

    wrapper = make_wrapper(import_task)
    failed = QSignalSpy(wrapper.load_failed)
    qtbot.waitUntil(entered.is_set, timeout=5000)
    assert wrapper._interactive_token is not None
    assert ui_work_priority.interactive_load_pending()
    if outcome == "close":
        wrapper.close()
        assert wrapper._worker.isRunning()
        assert wrapper._interactive_token is None
        assert not ui_work_priority.interactive_load_pending()
    release.set()
    qtbot.waitUntil(wrapper._worker.isFinished, timeout=5000)
    if outcome == "import_error":
        qtbot.waitUntil(lambda: failed.count() == 1, timeout=5000)
        assert "controlled import failure" in wrapper.message.text()
        assert not wrapper.retry.isHidden()
    else:
        qtbot.wait(10)
        assert wrapper.page is None and failed.count() == 0
    assert wrapper._interactive_token is None
    assert not ui_work_priority.interactive_load_pending()


def test_autoimport_worker_returns_to_baseline_sleep_after_results_complete(qtbot, pages, importer, monkeypatch):
    make_viewer, _, gates = pages
    viewer = make_viewer()
    viewer.refresh()
    first_slice, release = Event(), Event()
    gates.append(release)
    sleeps = []
    monkeypatch.setattr(GuiAutoImport.time, "sleep", sleeps.append)

    def cycle():
        importer._cooperate(8)
        first_slice.set()
        if not release.wait(5):
            raise TimeoutError("Results gate was not released")
        importer._cooperate(16)

    previous = importer.cooperative_callback
    monkeypatch.setattr(importer, "runUpdated", cycle)
    worker = GuiAutoImport.AutoImportThread(importer)
    errors = QSignalSpy(worker.error)
    worker.start()
    try:
        qtbot.waitUntil(first_slice.is_set, timeout=5000)
        assert sleeps == [.005]
        viewer._workers[-1].finish()
        assert not ui_work_priority.interactive_load_pending()
        release.set()
        qtbot.waitUntil(worker.isFinished, timeout=5000)
        assert sleeps == [.005, .001]
        assert errors.count() == 0
        assert importer.cooperative_callback is previous
    finally:
        release.set()
        assert worker.wait(10000)
