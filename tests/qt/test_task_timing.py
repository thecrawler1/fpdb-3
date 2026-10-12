"""Separate worker scheduling, task work and queued GUI delivery delays."""

from threading import Event
from time import perf_counter, sleep

import pytest
from PySide6.QtCore import QObject, Qt, Slot

from fpdb_3_legacy import background_tasks

pytestmark = pytest.mark.qt

MILESTONES = (
    "started_at", "worker_entered_at", "slot_acquired_at",
    "task_started_at", "task_finished_at", "emitted_at",
)


@pytest.fixture
def workers(qapp):
    owned = []
    yield owned
    for worker in owned:
        worker.cancel()
        worker.wait()
    background_tasks.drain_background_tasks()


def assert_ordered(timing):
    stamps = [timing[key] for key in MILESTONES]
    assert all(isinstance(stamp, float) for stamp in stamps)
    assert stamps == sorted(stamps)


def test_blocked_slots_are_separate_from_task_time(qtbot, workers):
    # Occupy both real shared slots without replacing the production semaphore.
    slots = background_tasks.TaskWorker._slots
    acquired = 0
    try:
        for _ in range(2):
            assert slots.acquire(timeout=3)
            acquired += 1
        invoked = Event()
        worker = background_tasks.TaskWorker(lambda: (invoked.set(), "done")[1])
        workers.append(worker)
        assert worker.timing == {}
        worker.start()
        qtbot.waitUntil(lambda: "worker_entered_at" in worker.timing, timeout=3000)
        qtbot.wait(100)
        assert not invoked.is_set()
        assert "slot_acquired_at" not in worker.timing
        assert "task_started_at" not in worker.timing
        released_at = perf_counter()
        slots.release()
        acquired -= 1
        assert worker.wait(3000)
        timing = worker.timing
        assert_ordered(timing)
        assert timing["slot_acquired_at"] >= released_at
        slot_wait = timing["slot_acquired_at"] - timing["worker_entered_at"]
        assert slot_wait >= 0.09
        assert timing["task_finished_at"] - timing["task_started_at"] < slot_wait
        assert timing["task_cpu_seconds"] >= 0
        assert worker.result == "done"
    finally:
        for _ in range(acquired):
            slots.release()


def test_queued_gui_delivery_does_not_inflate_task_time(qtbot, workers):
    delivered = []
    task_done = Event()
    worker = background_tasks.TaskWorker(lambda: (task_done.set(), "result")[1])
    workers.append(worker)

    class Receiver(QObject):
        @Slot(object)
        def receive(self, result):
            delivered.append((result, perf_counter(), worker.timing.copy()))

    receiver = Receiver()
    worker.completed.connect(receiver.receive, Qt.ConnectionType.QueuedConnection)
    worker.start()
    # Block the GUI without pumping events: the task can finish and emit, but
    # its receiver cannot run. This reproduces the ambiguous old import timer.
    assert task_done.wait(3)
    assert worker.wait(3000)
    blocked_at = perf_counter()
    sleep(0.1)
    assert not delivered
    assert worker.timing["emitted_at"] <= blocked_at
    qtbot.waitUntil(lambda: bool(delivered), timeout=3000)
    result, received_at, timing = delivered[0]
    assert result == "result"
    assert_ordered(timing)
    delivery_wait = received_at - timing["emitted_at"]
    assert delivery_wait >= 0.09
    assert timing["task_finished_at"] - timing["task_started_at"] < delivery_wait


@pytest.mark.parametrize("fails", [False, True])
def test_unavailable_cpu_clock_preserves_result_and_error_delivery(qtbot, workers, monkeypatch, fails):
    def unavailable():
        raise OSError("Thread CPU clock unavailable")

    monkeypatch.setattr(background_tasks, "thread_time", unavailable)

    def task():
        if fails:
            raise ValueError("task failed")
        return "done"

    worker = background_tasks.TaskWorker(task)
    workers.append(worker)
    signal = worker.error if fails else worker.completed
    with qtbot.waitSignal(signal, timeout=3000) as received:
        worker.start()
    assert worker.wait(3000)
    assert received.args == ["task failed" if fails else "done"]
    assert_ordered(worker.timing)
    assert "task_cpu_seconds" not in worker.timing
