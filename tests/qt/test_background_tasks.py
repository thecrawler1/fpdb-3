"""Real background-worker scheduling, cancellation and shutdown lifetimes."""

from threading import Event, Lock, Thread

import pytest
from PySide6.QtTest import QSignalSpy

from fpdb_3_legacy import background_tasks
from fpdb_3_legacy.cooperative_work import checkpoint

pytestmark = pytest.mark.qt


@pytest.fixture
def worker_resources(qapp):
    """Release every task gate before waiting, even after a failed assertion."""
    workers = []
    gates = []
    yield workers, gates
    try:
        for worker in workers:
            worker.cancel()
        for gate in gates:
            gate.set()
        for worker in workers:
            worker.wait()
    finally:
        background_tasks.drain_background_tasks()


def test_real_workers_run_at_most_two_tasks(qtbot, worker_resources):
    workers, gates = worker_resources
    lock = Lock()
    entered = []
    active = 0
    peak = 0

    def task(index):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            entered.append(index)
        try:
            if not gates[index].wait(5):
                raise TimeoutError("Task gate was not released")
            return index
        finally:
            with lock:
                active -= 1

    def entered_count():
        with lock:
            return len(entered)

    gates.extend(Event() for _ in range(5))
    workers.extend(background_tasks.TaskWorker(lambda index=index: task(index)) for index in range(5))
    completed = [QSignalSpy(worker.completed) for worker in workers]
    errors = [QSignalSpy(worker.error) for worker in workers]
    for worker in workers:
        worker.start()

    qtbot.waitUntil(lambda: entered_count() >= 2, timeout=3000)
    qtbot.wait(150)
    assert entered_count() == 2
    assert all(worker.isRunning() for worker in workers)
    with lock:
        first = entered[0]
    gates[first].set()
    qtbot.waitUntil(lambda: entered_count() >= 3, timeout=3000)
    qtbot.wait(150)
    assert entered_count() == 3
    with lock:
        assert active == 2
        assert peak == 2

    for gate in gates:
        gate.set()
    qtbot.waitUntil(lambda: all(worker.isFinished() for worker in workers), timeout=3000)
    qtbot.waitUntil(lambda: all(spy.count() == 1 for spy in completed), timeout=3000)
    assert [worker.result for worker in workers] == list(range(5))
    assert [spy.at(0)[0] for spy in completed] == list(range(5))
    assert all(spy.count() == 0 for spy in errors)
    assert sorted(entered) == list(range(5))
    assert peak == 2


def test_cancelling_pending_worker_never_invokes_task(qtbot, worker_resources):
    workers, gates = worker_resources
    gates.extend(Event() for _ in range(2))
    started = [Event(), Event()]
    invoked = Event()

    def blocking_task(index):
        started[index].set()
        if not gates[index].wait(5):
            raise TimeoutError("Task gate was not released")

    workers.extend(background_tasks.TaskWorker(lambda index=index: blocking_task(index)) for index in range(2))
    for worker in workers:
        worker.start()
    qtbot.waitUntil(lambda: all(event.is_set() for event in started), timeout=3000)

    pending = background_tasks.TaskWorker(invoked.set)
    workers.append(pending)
    completed = QSignalSpy(pending.completed)
    errors = QSignalSpy(pending.error)
    pending.start()
    qtbot.waitUntil(pending.isRunning, timeout=3000)
    assert not invoked.is_set()
    pending.cancel()
    qtbot.waitUntil(pending.isFinished, timeout=3000)
    # The pending thread must stop while both semaphore slots are still occupied.
    assert all(worker.isRunning() for worker in workers[:2])
    for gate in gates:
        gate.set()
    qtbot.waitUntil(lambda: all(worker.isFinished() for worker in workers), timeout=3000)
    qtbot.wait(20)
    assert not invoked.is_set()
    assert pending.result is None
    assert completed.count() == 0
    assert errors.count() == 0


def test_cooperative_cancellation_stops_loop_without_result_or_signals(qtbot, worker_resources):
    workers, gates = worker_resources
    started = Event()
    stopped = Event()
    fallback_stop = Event()
    gates.append(fallback_stop)

    def looping_task():
        try:
            while not fallback_stop.is_set():
                checkpoint()
                started.set()
            return "finished without cancellation checkpoint"
        finally:
            stopped.set()

    worker = background_tasks.TaskWorker(looping_task)
    workers.append(worker)
    completed = QSignalSpy(worker.completed)
    errors = QSignalSpy(worker.error)
    worker.start()
    qtbot.waitUntil(started.is_set, timeout=3000)
    assert worker.isRunning()
    worker.cancel()
    qtbot.waitUntil(worker.isFinished, timeout=3000)
    qtbot.wait(20)
    assert stopped.is_set()
    assert not fallback_stop.is_set()
    assert worker.result is None
    assert completed.count() == 0
    assert errors.count() == 0


def test_drain_waits_for_worker_and_runs_registered_cleanup_once(qtbot, worker_resources):
    workers, gates = worker_resources
    release = Event()
    gates.append(release)
    started = Event()
    task_finished = Event()
    drain_started = Event()
    drain_returned = Event()
    returned_before_release = []
    cleaned = []

    def task():
        started.set()
        if not release.wait(5):
            raise TimeoutError("Task gate was not released")
        task_finished.set()
        return "drained"

    worker = background_tasks.TaskWorker(task)
    workers.append(worker)
    worker.start()
    qtbot.waitUntil(started.is_set, timeout=3000)
    background_tasks.retain_until_finished(
        (worker,),
        lambda: cleaned.append((task_finished.is_set(), worker.isFinished())),
    )

    def release_after_drain_starts():
        try:
            if drain_started.wait(3):
                returned_before_release.append(drain_returned.wait(0.15))
        finally:
            release.set()

    releaser = Thread(target=release_after_drain_starts)
    releaser.start()
    try:
        drain_started.set()
        background_tasks.drain_background_tasks()
        drain_returned.set()
    finally:
        release.set()
        releaser.join()

    assert returned_before_release == [False]
    assert worker.isFinished()
    assert worker.result == "drained"
    assert cleaned == [(True, True)]
    assert not background_tasks._retained
    # Previously queued retention polls must not repeat the cleanup callback.
    qtbot.wait(50)
    background_tasks.drain_background_tasks()
    assert cleaned == [(True, True)]
