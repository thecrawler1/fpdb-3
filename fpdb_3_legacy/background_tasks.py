"""Small Qt workers for non-UI setup and data preparation."""

from threading import BoundedSemaphore, Event
from time import perf_counter, thread_time

from PySide6.QtCore import QCoreApplication, QThread, QTimer, Signal

from fpdb_3_legacy.cooperative_work import TaskCancelled, context

_retained = {}
_next_token = 0


def _thread_cpu_time():
    """CPU clocks are diagnostic only; unsupported clocks must not fail a task."""
    try:
        return thread_time()
    except (OSError, RuntimeError, NotImplementedError):
        return None


def retain_until_finished(workers, cleanup=None):
    """Retain running QThreads without making tab close wait on their work."""
    global _next_token
    workers = tuple(workers)
    _next_token += 1
    token = _next_token
    _retained[token] = (workers, cleanup)
    app = QCoreApplication.instance()
    if app is not None and not getattr(app, "_fpdb_task_cleanup_installed", False):
        app._fpdb_task_cleanup_installed = True
        app.aboutToQuit.connect(drain_background_tasks)

    def poll():
        if token not in _retained:
            return
        if any(worker.isRunning() for worker in workers):
            QTimer.singleShot(25, poll)
            return
        _retained.pop(token)
        if cleanup is not None:
            cleanup()

    QTimer.singleShot(0, poll)


def drain_background_tasks():
    """Application exit drains retained threads before releasing their resources."""
    retained = tuple(_retained.values())
    _retained.clear()
    for workers, _cleanup in retained:
        for worker in workers:
            worker.wait()
    for _workers, cleanup in retained:
        if cleanup is not None:
            cleanup()


class TaskWorker(QThread):
    """Run a bounded task and expose its scheduling milestones in ``timing``.

    ``*_at`` values are monotonic ``perf_counter()`` timestamps in seconds.
    Missing milestones mean that the worker has not reached that stage (or was
    cancelled first). ``emitted_at`` is recorded immediately before a completed
    or error signal is emitted, so a queued GUI receiver can subtract it from
    its own ``perf_counter()`` reading to measure delivery delay. The optional
    ``task_cpu_seconds`` measures only this worker thread during the task.
    """

    _slots = BoundedSemaphore(2)
    completed = Signal(object)
    error = Signal(str)

    def __init__(self, task):
        super().__init__()
        self.task = task
        self.result = None
        self.cancelled = Event()
        self.timing = {}

    def start(self):
        self.timing.clear()
        self.timing["started_at"] = perf_counter()
        super().start()
        retain_until_finished((self,))

    def cancel(self):
        self.cancelled.set()
        self.requestInterruption()

    def _run_task(self):
        cpu_started = _thread_cpu_time()
        self.timing["task_started_at"] = perf_counter()
        try:
            return self.task()
        finally:
            self.timing["task_finished_at"] = perf_counter()
            cpu_finished = _thread_cpu_time()
            if cpu_started is not None and cpu_finished is not None:
                self.timing["task_cpu_seconds"] = max(0.0, cpu_finished - cpu_started)

    def run(self):
        self.timing["worker_entered_at"] = perf_counter()
        context.cancelled = self.cancelled
        acquired = False
        try:
            while not acquired:
                if self.cancelled.is_set():
                    return
                acquired = self._slots.acquire(timeout=.05)
            self.timing["slot_acquired_at"] = perf_counter()
            if self.cancelled.is_set():
                return
            self.result = self._run_task()
        except TaskCancelled:
            pass
        except Exception as error:  # Worker boundary: report to the GUI.
            if not self.cancelled.is_set():
                self.timing["emitted_at"] = perf_counter()
                self.error.emit(str(error))
        else:
            if not self.cancelled.is_set():
                self.timing["emitted_at"] = perf_counter()
                self.completed.emit(self.result)
        finally:
            context.cancelled = None
            if acquired:
                self._slots.release()
