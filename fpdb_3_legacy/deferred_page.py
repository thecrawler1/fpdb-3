"""Paint a tab immediately while importing its dependencies off the GUI thread."""

from importlib import import_module
from time import perf_counter

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from fpdb_3_legacy.background_tasks import TaskWorker, retain_until_finished
from fpdb_3_legacy.i18n import gettext as _
from fpdb_3_legacy.ui_work_priority import begin_interactive_load, end_interactive_load


class DeferredPage(QWidget):
    ready = Signal()
    load_failed = Signal()

    def __init__(self, module, build, parent=None, *, preload=False):
        super().__init__(parent)
        self.module = module
        self.build = build
        self._preload = preload
        self._created_at = perf_counter()
        self._import_seconds = self._construct_seconds = 0.0
        self._ready = False
        self._opened_at = None
        self._invalidated = False
        self._interactive_token = None
        self.page = None
        self._closed = False
        self._worker = None
        self._layout = QVBoxLayout(self)
        self.message = QLabel(_("Loading results…"))
        self._layout.addWidget(self.message)
        self.retry = QPushButton(_("Retry"))
        self.retry.clicked.connect(self.load)
        self.retry.hide()
        self._layout.addWidget(self.retry)
        QTimer.singleShot(0, self.load)

    @property
    def _fpdb_auto_loader(self):
        return getattr(self.page, "_fpdb_auto_loader", None)

    def load(self):
        if self._closed or self.page is not None or (self._worker is not None and self._worker.isRunning()):
            return
        self.retry.hide()
        self.message.setText(_("Loading results…"))
        self._interactive_token = begin_interactive_load()
        self._import_started = perf_counter()
        self._worker = TaskWorker(lambda: import_module(self.module))
        self._worker.completed.connect(self._loaded, Qt.ConnectionType.QueuedConnection)
        self._worker.error.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        self._worker.start()

    def _loaded(self, module):
        if self._closed:
            return
        self._import_seconds = perf_counter() - self._import_started
        self._import_timing = dict(getattr(self._worker, "timing", {}))
        emitted = self._import_timing.get("emitted_at", perf_counter())
        self._import_delivery_seconds = max(0, perf_counter() - emitted)
        construct_started = perf_counter()
        try:
            self.page = self.build(module)
        except Exception as error:
            self._failed(str(error))
            return
        self._construct_seconds = perf_counter() - construct_started
        ready = getattr(self.page, "results_ready", None)
        if ready is not None:
            ready.connect(self._report_ready)
        failed = getattr(self.page, "results_failed", None)
        if failed is not None:
            failed.connect(self._page_failed)
        self.message.hide()
        self.retry.hide()
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self.page)
        if self._preload:
            self.page.preload()
        if self._invalidated:
            loader = self._fpdb_auto_loader
            if loader is not None:
                loader.invalidate()

    def _report_ready(self):
        from fpdb_3_legacy.loggingFpdb import get_logger

        first_load = not self._ready
        self._ready = True
        self._finish_priority()
        metrics = getattr(self.page, "load_metrics", {})
        total_seconds = perf_counter() - self._created_at if first_load else metrics.get("total_seconds", 0)
        get_logger("results_loading").warning(
            "[PERF] Results ready preload=%s total_s=%.3f import_s=%.3f construct_s=%.3f "
            "setup_s=%.3f query_s=%.3f prepare_render_s=%.3f",
            self._preload, total_seconds, self._import_seconds, self._construct_seconds,
            metrics.get("setup_seconds", 0), metrics.get("query_seconds", 0),
            metrics.get("prepare_and_render_seconds", 0),
        )
        self._report_stages()
        self._report_open()
        self.ready.emit()

    def _finish_priority(self):
        if self._interactive_token is not None:
            end_interactive_load(self._interactive_token)
            self._interactive_token = None

    def _page_failed(self):
        self._finish_priority()
        self.load_failed.emit()

    def _report_stages(self):
        from fpdb_3_legacy.loggingFpdb import get_logger

        timing = getattr(self, "_import_timing", {})
        construction = getattr(self.page, "construction_metrics", {})
        task_start = timing.get("task_started_at", 0)
        task_end = timing.get("task_finished_at", task_start)
        get_logger("results_loading").warning(
            "[PERF] Results stages import_task_s=%.3f import_cpu_s=%.3f import_delivery_s=%.3f "
            "construct_cpu_s=%.3f styles_s=%.3f controls_s=%.3f table_graph_s=%.3f",
            task_end - task_start, timing.get("task_cpu_seconds", 0),
            getattr(self, "_import_delivery_seconds", 0), construction.get("total_cpu_seconds", 0),
            construction.get("build_styles", 0), construction.get("build_controls", 0),
            construction.get("build_table_graph", 0),
        )

    def showEvent(self, event):
        super().showEvent(event)
        self._opened_at = perf_counter()
        if self._ready:
            QTimer.singleShot(0, self._report_open)

    def _report_open(self):
        if self._closed or self._opened_at is None or not self._ready:
            return
        if getattr(self.page, "_loading", False) or getattr(self._fpdb_auto_loader, "dirty", False):
            return
        from fpdb_3_legacy.loggingFpdb import get_logger

        get_logger("results_loading").warning("[PERF] Results access wait_s=%.3f", perf_counter() - self._opened_at)
        self._opened_at = None

    def invalidate_results(self):
        """Remember imports even while the Results module is still loading."""
        self._invalidated = True
        loader = self._fpdb_auto_loader
        if loader is not None:
            loader.invalidate()

    def _failed(self, message):
        if not self._closed:
            self.message.setText(_("Could not load results: ") + message)
            self.retry.show()
            self._page_failed()

    def shutdown_workers(self):
        self._closed = True
        self._finish_priority()
        if self._worker is not None:
            self._worker.cancel()
            retain_until_finished((self._worker,))
        if self.page is not None:
            self.page.shutdown_workers()

    def close_owned_database(self):
        self.shutdown_workers()
        if self.page is not None:
            self.page.close_owned_database()

    def closeEvent(self, event):
        self.close_owned_database()
        super().closeEvent(event)
