"""Compact calendar results, selected-period curves and access to existing hands."""

from __future__ import annotations

import contextlib
from copy import copy
from datetime import date, datetime, timedelta, timezone, tzinfo
from time import perf_counter, thread_time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
from PySide6.QtCore import QDate, QIODevice, QSaveFile, QSortFilterProxyModel, Qt, QThread, QTimer, QTimeZone, Signal
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fpdb_3_legacy import Database
from fpdb_3_legacy.background_tasks import TaskWorker, retain_until_finished
from fpdb_3_legacy.i18n import gettext as _
from fpdb_3_legacy.localized_formats import format_currency, format_number
from fpdb_3_legacy.period_results import (
    PeriodResult,
    ResultHand,
    group_results,
    parse_result_rows,
    period_start,
    preset_dates,
    profit_curves,
    results_query,
    summarize_results,
)
from fpdb_3_legacy.results_export import results_csv
from fpdb_3_legacy.review_widgets import (
    EmptyState,
    FilterChips,
    SegmentedControl,
    game_label,
    labeled_control,
    review_stylesheet,
    text_label,
)
from fpdb_3_legacy.ring_stats.base import DbWorker
from fpdb_3_legacy.ring_stats.styles import get_modern_qss, get_theme_palette
from fpdb_3_legacy.ring_stats.views.dashboard_view import ProfitGraphWidget
from fpdb_3_legacy.table_columns import install_column_controls
from fpdb_3_legacy.ui_work_priority import begin_interactive_load, end_interactive_load

PERIOD_ROLE = int(Qt.ItemDataRole.UserRole) + 1
HEADINGS = ("Period", "Hands", "VPIP", "PFR", "Profit ($)", "bb/100", "EV ($)", "EV bb/100")
INLINE_HAND_LIMIT = 1000


def discover_heroes(config, db):
    heroes = []
    seen = set()
    for site in config.get_supported_sites():
        ids = [db.get_player_id(config, site, alias) for alias in config.get_hero_aliases(site)]
        if not any(ids):
            ids = db.get_hero_player_ids(site)
        for player_id in ids:
            if player_id is not None and player_id not in seen:
                seen.add(player_id)
                heroes.append((f"{db.get_player_name_by_id(player_id)} · {site}", int(player_id)))
    db.rollback()
    return heroes


def prepare_results_database(config, querylist, db):
    owned = db is None
    if owned:
        db = Database.Database(config, sql=querylist)
    try:
        # Hero discovery must not share the GUI's cursor or transaction.
        with db.worker_connection() as connection:
            cursor = connection.cursor()
            reader = copy(db)
            reader.connection = connection
            reader.cursor = cursor
            try:
                heroes = discover_heroes(config, reader)
            finally:
                # The facade borrows these resources. Database.__del__ must not
                # close a connection already returned to the worker pool (or the
                # copied GUI cursor if creating the worker cursor had failed).
                reader.cursor = None
                reader.connection = None
                cursor.close()
        return db, heroes
    except Exception:
        if owned:
            db.disconnect()
        raise


def aggregate_results(hands, game, stake, grouping, zone, *, cooperative=False):
    filtered = tuple(h for h in hands if (game is None or h.game == game) and (stake is None or h.stake_key == stake))
    return (filtered, group_results(filtered, grouping, zone, cooperative=cooperative),
            summarize_results(filtered, cooperative=cooperative))


class ResultNumberDelegate(QStyledItemDelegate):
    """Respect profit/loss colours even when the global theme styles item text."""

    def paint(self, painter, option, index) -> None:
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        if foreground is None:
            super().paint(painter, option, index)
            return
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        text, styled.text = styled.text, ""
        painter.save()
        styled.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        color = styled.palette.highlightedText().color() if styled.state & QStyle.StateFlag.State_Selected else foreground.color()
        painter.setPen(color)
        painter.setFont(styled.font)
        rect = styled.rect.adjusted(8, 0, -8, 0)
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         styled.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width()))
        painter.restore()


def local_zone() -> tzinfo:
    try:
        return ZoneInfo(bytes(QTimeZone.systemTimeZoneId()).decode())
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().tzinfo or timezone.utc


def _construction_cpu_time():
    """Keep unavailable diagnostic CPU clocks from affecting widget creation."""
    try:
        return thread_time()
    except (OSError, RuntimeError, NotImplementedError):
        return None


class GuiResultsViewer(QWidget):
    hands_requested = Signal(list)
    import_requested = Signal()
    results_ready = Signal()
    results_failed = Signal()

    def __init__(self, config, querylist=None, *, db=None, zone: tzinfo | None = None, autoload=True):
        construction_started = perf_counter()
        cpu_started = _construction_cpu_time()
        super().__init__()
        # Flat wall durations in seconds; optional <stage>_cpu_seconds entries
        # measure only this GUI thread. These are separate from async loading.
        self.construction_metrics = {}
        self.conf = config
        self.db = db
        self._querylist = querylist
        self._setup_complete = not autoload
        self._setup_worker = None
        self._setup_loading = False
        if not autoload and self.db is None:
            self.db = Database.Database(config, sql=querylist)
        self._owns_db = db is None
        self.zone = zone or local_zone()
        self._workers: list[DbWorker] = []
        self._tasks: list[TaskWorker] = []
        self._view_generation = 0
        self._curve_generation = 0
        self._curve_cache = {}
        self._pending_curve = None
        self._curve_requests = {}
        self._generation = 0
        # Old hands remain visible during a query, but must not become actionable.
        self._data_generation = None
        self._closed = False
        self._db_closed = False
        self._loading = False
        self._results_current = True
        self._request_status = ""
        self._has_load_error = False
        self._graph_context = None
        self._initialize_load_metrics()
        self._custom_date_timer = QTimer(self)
        self._custom_date_timer.setSingleShot(True)
        self._custom_date_timer.setInterval(300)
        self._custom_date_timer.timeout.connect(self.refresh)
        self.raw_hands: tuple[ResultHand, ...] = ()
        self.filtered_hands: tuple[ResultHand, ...] = ()
        self.periods: list[PeriodResult] = []
        self.total = summarize_results(())
        self.selection: date | str | None = None
        self._build_results_ui()
        if autoload:
            from fpdb_3_legacy.automatic_loading import install_automatic_loading

            install_automatic_loading(self, self.refresh)
        self._record_construction_stage("total", construction_started, cpu_started)

    def _record_construction_stage(self, stage, started, cpu_started):
        self.construction_metrics[stage] = perf_counter() - started
        cpu_finished = _construction_cpu_time()
        if cpu_started is not None and cpu_finished is not None:
            self.construction_metrics[f"{stage}_cpu_seconds"] = max(0.0, cpu_finished - cpu_started)

    @contextlib.contextmanager
    def _construction_stage(self, stage):
        started = perf_counter()
        cpu_started = _construction_cpu_time()
        try:
            yield
        finally:
            self._record_construction_stage(stage, started, cpu_started)

    def _build_results_ui(self):
        with self._construction_stage("build_styles"):
            self.setObjectName("resultsViewer")
            self.setStyleSheet(get_modern_qss() + review_stylesheet())
        with self._construction_stage("build_controls"):
            self._build_controls()
        with self._construction_stage("build_table_graph"):
            self._build_table_and_graph()
        with self._construction_stage("heroes"):
            if self._setup_complete:
                self._populate_heroes()
        with self._construction_stage("initial_table"):
            self._set_preset()
            self._connect_controls()
            self._rebuild_table()

    def _build_controls(self) -> None:
        layout = QVBoxLayout(self)
        self.main_layout = layout
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(text_label(_("Results"), "title"))
        heading.addWidget(text_label(_("Cash performance, period by period"), "caption"))
        toolbar.addLayout(heading)
        toolbar.addStretch()
        self.hero_combo = QComboBox()
        self.hero_combo.setMaximumWidth(280)
        self.group_combo = QComboBox()
        for title, key in (("Day", "day"), ("Week", "week"), ("Month", "month"), ("Year", "year")):
            self.group_combo.addItem(_(title), key)
        self.interval_combo = QComboBox()
        for title, key in (("Today", "today"), ("Yesterday", "yesterday"), ("Last 7 days", "seven"),
                           ("This month", "month"), ("This year", "year"), ("All history", "all"), ("Custom", "custom")):
            self.interval_combo.addItem(_(title), key)
        self.interval_combo.setCurrentIndex(3)
        controls = QHBoxLayout()
        controls.setSpacing(16)
        self.group_segments = SegmentedControl(self.group_combo)
        for title, control in (("Hero", self.hero_combo), ("Group by", self.group_segments), ("Date range", self.interval_combo)):
            controls.addWidget(labeled_control(_(title), control))
        self._build_custom_dates()
        self._build_actions(toolbar)
        layout.addLayout(toolbar)
        controls.addStretch()
        controls.addWidget(self.more_filters, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(controls)
        layout.addWidget(self.date_panel)
        self.filter_panel = QWidget()
        filters = QHBoxLayout(self.filter_panel)
        filters.setContentsMargins(0, 0, 0, 0)
        self.game_combo, self.limit_combo = QComboBox(), QComboBox()
        self.game_combo.addItem(_("All games"), None)
        self.limit_combo.addItem(_("All limits"), None)
        for title, control in (("Game", self.game_combo), ("Limit", self.limit_combo)):
            filters.addWidget(QLabel(_(title)))
            filters.addWidget(control)
        filters.addStretch()
        self.filter_panel.hide()
        layout.addWidget(self.filter_panel)
        self.active_filters = FilterChips()
        layout.addWidget(self.active_filters)
        self._build_status(layout)

    def _build_status(self, layout) -> None:
        self.status = QLabel()
        self.status.setProperty("reviewText", "caption")
        self.status.setWordWrap(True)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, 1)
        self.retry_button = QToolButton()
        self.retry_button.setText(_("Retry"))
        self.retry_button.clicked.connect(self.refresh)
        self.retry_button.hide()
        status_row.addWidget(self.retry_button)
        layout.addLayout(status_row)

    def _build_actions(self, toolbar) -> None:
        self.more_filters = QToolButton()
        self.more_filters.setText(_("Filters"))
        self.more_filters.setCheckable(True)
        self.columns_button = QToolButton()
        self.columns_button.setText(_("Columns"))
        self.columns_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.refresh_button = QPushButton(_("Refresh"))
        self.export_button = QPushButton(_("Export CSV"))
        self.export_button.setToolTip(_("Export all filtered periods and Total in the current table order."))
        toolbar.addWidget(self.columns_button)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.export_button)

    def _build_custom_dates(self) -> None:
        self.from_date, self.to_date = QDateEdit(), QDateEdit()
        self.date_panel = QWidget()
        layout = QHBoxLayout(self.date_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        for label, control in (("From", self.from_date), ("To", self.to_date)):
            control.setCalendarPopup(True)
            control.setDisplayFormat("dd/MM/yyyy")
            control.setAccessibleName(_(label))
            layout.addWidget(QLabel(_(label)))
            layout.addWidget(control)
        layout.addStretch()

    def _build_table_and_graph(self) -> None:
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_layout.addWidget(self.splitter, 1)
        table_panel = QWidget()
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        self.model = QStandardItemModel(0, len(HEADINGS), self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.table = self._table(self.proxy)
        self.table.setObjectName("calendarResultsTable")
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        self.empty_state = EmptyState(self.table)
        table_layout.addWidget(self.table)
        self.total_model = QStandardItemModel(0, len(HEADINGS), self)
        self.total_table = self._table(self.total_model)
        self.total_table.setObjectName("calendarResultsTotal")
        self.total_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.total_table.horizontalHeader().hide()
        self.total_table.setFixedHeight(48)
        table_layout.addWidget(self.total_table)
        self.splitter.addWidget(table_panel)
        self._build_graph_panel()
        self.splitter.setSizes([300, 360])
        self._connect_view_actions()

    def _build_graph_panel(self) -> None:
        graph_panel = QWidget()
        self.graph_panel = graph_panel
        graph_layout = QVBoxLayout(graph_panel)
        graph_layout.setContentsMargins(0, 8, 0, 0)
        options = QHBoxLayout()
        self.units_combo = QComboBox()
        self.units_combo.addItem("$", False)
        self.units_combo.addItem("BB", True)
        self.selection_label = text_label("", "heading")
        self.selection_label.setWordWrap(True)
        options.addWidget(self.selection_label, 1)
        self.units_segments = SegmentedControl(self.units_combo)
        options.addWidget(self.units_segments)
        self.all_periods_button = QPushButton(_("All periods"))
        self.all_periods_button.setCheckable(True)
        self.all_periods_button.clicked.connect(self.select_total)
        options.addWidget(self.all_periods_button)
        legend = QHBoxLayout()
        self.line_checks = []
        for name in ("Profit", "Showdown", "Non-showdown", "All-in EV"):
            check = QCheckBox(_(name))
            check.setChecked(True)
            self.line_checks.append(check)
            legend.addWidget(check)
        legend.addStretch()
        self.reset_graph_button = QPushButton(_("Reset view"))
        self.reset_graph_button.clicked.connect(lambda: self.graph.getViewBox().autoRange())
        options.addWidget(self.reset_graph_button)
        self.hands_button = QPushButton(_("View hands"))
        self.hands_button.setProperty("primaryAction", True)
        options.addWidget(self.hands_button)
        graph_layout.addLayout(options)
        graph_layout.addLayout(legend)
        self.graph = ProfitGraphWidget()
        graph_layout.addWidget(self.graph, 1)
        self.splitter.addWidget(graph_panel)

    def _connect_view_actions(self) -> None:
        self.column_controls = install_column_controls(
            self.table, "calendar-results", essential=HEADINGS, keys=dict(enumerate(HEADINGS)),
        )
        self.column_controls.visibility_changed.connect(lambda column, visible: self.total_table.setColumnHidden(column, not visible))
        self.columns_button.setMenu(self.column_controls.menu())
        self.table.horizontalHeader().sectionResized.connect(self._sync_total_columns)
        self.table.horizontalHeader().sectionMoved.connect(self._sync_total_columns)
        self.table.selectionModel().currentRowChanged.connect(self._period_selected)
        self.table.clicked.connect(self._period_selected)
        self.table.doubleClicked.connect(lambda _index: self.open_hands())
        self.total_table.clicked.connect(lambda _index: self.select_total())
        self.hands_button.clicked.connect(self.open_hands)
        self.units_combo.currentIndexChanged.connect(self._render_graph)
        for check in self.line_checks:
            check.toggled.connect(self._line_visibility)

    def refresh_theme(self, colors=None, theme_colors=None) -> None:
        """Update local styles, financial text and plotted colours together."""
        self.setStyleSheet(get_modern_qss() + review_stylesheet())
        self._rebuild_table()

    @staticmethod
    def _table(model) -> QTableView:
        view = QTableView()
        view.setModel(model)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setAlternatingRowColors(True)
        view.setShowGrid(False)
        view.verticalHeader().hide()
        view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        delegate = ResultNumberDelegate(view)
        for column in (4, 5, 6, 7):
            view.setItemDelegateForColumn(column, delegate)
        return view

    def _populate_heroes(self) -> None:
        self._set_heroes(discover_heroes(self.conf, self.db))

    def _set_heroes(self, heroes) -> None:
        seen = {self.hero_combo.itemData(i) for i in range(self.hero_combo.count())}
        self.hero_combo.blockSignals(True)
        for label, player_id in heroes:
            if player_id not in seen:
                seen.add(player_id)
                self.hero_combo.addItem(label, player_id)
        if self.hero_combo.count() and self.hero_combo.currentIndex() < 0:
            self.hero_combo.setCurrentIndex(0)
        self.hero_combo.blockSignals(False)

    def _connect_controls(self) -> None:
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button.clicked.connect(self._choose_export_path)
        self.hero_combo.currentIndexChanged.connect(self.refresh)
        self.interval_combo.currentIndexChanged.connect(self._interval_changed)
        self.group_combo.currentIndexChanged.connect(self._regroup)
        self.more_filters.toggled.connect(self.filter_panel.setVisible)
        self.game_combo.currentIndexChanged.connect(self._rebuild_table)
        self.limit_combo.currentIndexChanged.connect(self._rebuild_table)
        self.from_date.dateChanged.connect(self._custom_dates_changed)
        self.to_date.dateChanged.connect(self._custom_dates_changed)

    def _custom_dates_changed(self) -> None:
        if self.interval_combo.currentData() != "custom":
            return
        self._load_started = None
        self._finish_interactive_load()
        self._generation += 1  # Reject a reply for dates that were just edited.
        self._custom_date_timer.stop()
        if self.from_date.date() > self.to_date.date():
            self._request_status = _("Start date must not be after end date")
            border = get_theme_palette()['danger']
            self.from_date.setStyleSheet(f"border-color:{border};")
            self.to_date.setStyleSheet(f"border-color:{border};")
        else:
            self.from_date.setStyleSheet("")
            self.to_date.setStyleSheet("")
            self._request_status = _("Updating dates…")
            self._custom_date_timer.start()
        self._loading = False
        self._has_load_error = False
        self._results_current = False
        self._update_status()

    def _set_preset(self) -> None:
        key = self.interval_combo.currentData()
        custom = key == "custom"
        if not custom:
            self.from_date.setStyleSheet("")
            self.to_date.setStyleSheet("")
        self.date_panel.setVisible(custom)
        self.from_date.setVisible(custom)
        self.to_date.setVisible(custom)
        if not custom:
            start, end = preset_dates(datetime.now(self.zone).date(), key)
            if start is not None and end is not None:
                self.from_date.setDate(QDate(start.year, start.month, start.day))
                self.to_date.setDate(QDate(end.year, end.month, end.day))

    def _interval_changed(self) -> None:
        self._set_preset()
        self.refresh()

    def refresh(self) -> None:
        if self._closed or self._setup_loading:
            return
        self._begin_load_timing()
        if not self._setup_complete:
            self._start_setup()
            return
        self._custom_date_timer.stop()
        self._generation += 1
        generation = self._generation
        self._invalidate_graph_request(discard=True)
        self._results_current = False
        self._loading = False
        self._has_load_error = False
        player_id = self.hero_combo.currentData()
        if player_id is None:
            self._start_setup()
            return
        start = end = None
        if self.interval_combo.currentData() != "all":
            start, end = self.from_date.date().toPython(), self.to_date.date().toPython()
        try:
            query, params = results_query(player_id, start, end, self.zone, self.db.sql.query["placeholder"])
        except ValueError as error:
            self._request_status = str(error)
            self._update_status()
            self._load_started = None
            self._finish_interactive_load()
            self.results_failed.emit()
            return
        self._loading = True
        self._request_status = _("Loading results…")
        if self.raw_hands:
            self._request_status += " " + _("Displaying previous results.")
        self._update_status()
        self._workers = [worker for worker in self._workers if not worker.isFinished()]
        worker = DbWorker(self.db, "calendarResults", query, params)
        self._query_started = perf_counter()
        self._workers.append(worker)

        def loaded(_name, rows, _columns):
            self._receive_rows(generation, rows)

        def failed(message):
            self._fail_results(generation, _("Could not load results: ") + message)

        connection = Qt.ConnectionType.QueuedConnection if isinstance(worker, QThread) else Qt.ConnectionType.AutoConnection
        worker.finished.connect(loaded, connection)
        worker.error.connect(failed, connection)
        worker.start()

    def preload(self) -> None:
        """Prepare the default snapshot before the Results tab is first opened."""
        if self._closed or self._preloaded:
            return
        self._preloaded = True
        loader = getattr(self, "_fpdb_auto_loader", None)
        if loader is not None:
            loader.dirty = False
        self.refresh()

    def _initialize_load_metrics(self):
        self.load_metrics = {}
        self._load_started = None
        self._query_started = None
        self._prepare_started = None
        self._preloaded = False
        self._interactive_token = None

    def _begin_load_timing(self):
        if self._load_started is None:
            self._interactive_token = begin_interactive_load()
            self._load_started = perf_counter()
            self._query_started = self._prepare_started = None
            self.load_metrics = {}

    def _report_results_ready(self) -> None:
        if not self._loading and self._pending_curve is None and self._has_load_error:
            self._load_started = None
            self._finish_interactive_load()
        if self._loading or self._has_load_error or self._pending_curve is not None or self._load_started is None:
            return
        now = perf_counter()
        self.load_metrics["total_seconds"] = now - self._load_started
        if self._prepare_started is not None:
            self.load_metrics["prepare_and_render_seconds"] = now - self._prepare_started
        self._load_started = None
        self._finish_interactive_load()
        self.results_ready.emit()

    def _finish_interactive_load(self):
        if self._interactive_token is not None:
            end_interactive_load(self._interactive_token)
            self._interactive_token = None

    def _start_task(self, task, completed, failed, *, category="table"):
        self._tasks = [worker for worker in self._tasks if not worker.isFinished()]
        if category in ("table", "rows"):
            for previous in self._tasks:
                if getattr(previous, "category", None) == category:
                    cancel = getattr(previous, "cancel", None)
                    if cancel is not None:
                        cancel()
        worker = TaskWorker(task)
        worker.category = category
        self._tasks.append(worker)
        connection = Qt.ConnectionType.QueuedConnection if isinstance(worker, QThread) else Qt.ConnectionType.AutoConnection
        worker.completed.connect(completed, connection)
        worker.error.connect(failed, connection)
        worker.start()
        return worker

    def _start_setup(self):
        if self._setup_loading:
            return
        self._setup_loading = True
        self._loading = True
        self._request_status = _("Loading results…")
        self._update_status()
        config, querylist, db = self.conf, self._querylist, self.db
        self._setup_started = perf_counter()
        self._setup_worker = self._start_task(
            lambda: prepare_results_database(config, querylist, db), self._finish_setup, self._setup_failed,
            category="setup",
        )

    def _finish_setup(self, result):
        self.db, heroes = result
        self.load_metrics["setup_seconds"] = perf_counter() - self._setup_started
        self._setup_loading = False
        if self._closed:
            return
        self._setup_complete = True
        self._set_heroes(heroes)
        if self.hero_combo.currentData() is not None:
            self.refresh()
        else:
            self._loading = False
            self._results_current = False
            self._has_load_error = False
            self._request_status = _("No configured Hero found. Import hands and check the site screen name.")
            self._update_status()
            self._report_results_ready()

    def _setup_failed(self, message):
        self._setup_loading = False
        self._fail_results(self._generation, _("Could not load results: ") + message)

    def _fail_results(self, generation, message) -> None:
        if self._closed or generation != self._generation:
            return
        self._loading = False
        self._has_load_error = True
        self._load_started = None
        self._finish_interactive_load()
        self._results_current = False
        self._request_status = message
        if self.raw_hands:
            self._request_status += " " + _("Displaying previous results.")
        self._update_status()
        self.results_failed.emit()

    def _receive_rows(self, generation, rows) -> None:
        if self._closed or generation != self._generation:
            return
        now = perf_counter()
        if self._query_started is not None:
            self.load_metrics["query_seconds"] = now - self._query_started
        self._prepare_started = now
        self._invalidate_graph_request(discard=True)
        if len(rows) > INLINE_HAND_LIMIT:
            state = (self.game_combo.currentData(), self.limit_combo.currentData(), self.group_combo.currentData())
            zone = self.zone

            def prepare():
                parsed = parse_result_rows(rows, cooperative=True)
                return parsed, aggregate_results(parsed, *state, zone, cooperative=True)

            def completed(result):
                if self._closed or generation != self._generation:
                    return
                parsed, prepared = result
                self._accept_rows(parsed)
                current = (self.game_combo.currentData(), self.limit_combo.currentData(), self.group_combo.currentData())
                self._rebuild_table(prepared=prepared if state == current else None)

            self._start_task(prepare, completed,
                             lambda message: self._fail_results(generation, _("Could not read result data: ") + message),
                             category="rows")
            return
        try:
            parsed = parse_result_rows(rows)
        except (ValueError, TypeError, ArithmeticError, IndexError) as error:
            self._fail_results(generation, _("Could not read result data: ") + str(error))
            return
        self._accept_rows(parsed)
        self._rebuild_table()

    def _accept_rows(self, parsed):
        self._invalidate_graph_request(discard=True)
        self.raw_hands = parsed
        self._data_generation = self._generation
        self._curve_cache.clear()
        self._loading = False
        self._results_current = True
        self._has_load_error = False
        self._request_status = ""
        self._populate_filters()

    def _populate_filters(self) -> None:
        games = sorted({hand.game for hand in self.raw_hands})
        stakes = sorted({(hand.big_blind, hand.limit_type, hand.stake_key) for hand in self.raw_hands})
        game_options = [(game_label(game), game) for game in games]
        stake_options = [(f"{kind.upper()} · BB {format_currency(blind / 100, 'USD')}" if blind > 0 else f"{kind.upper()} · BB —", key)
                         for blind, kind, key in stakes]
        for combo, title, options in ((self.game_combo, "All games", game_options), (self.limit_combo, "All limits", stake_options)):
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(_(title), None)
            for text, key in options:
                combo.addItem(text, key)
            combo.setCurrentIndex(max(0, combo.findData(selected)))
            combo.blockSignals(False)

    def _regroup(self) -> None:
        if isinstance(self.selection, date):
            self.selection = period_start(self.selection, self.group_combo.currentData())
        self._rebuild_table()

    def _label(self, result: PeriodResult) -> str:
        if result.start is None:
            return _("Total")
        grouping = self.group_combo.currentData()
        if grouping == "month":
            return result.start.strftime("%m/%Y")
        if grouping == "year":
            return str(result.start.year)
        if grouping == "week":
            assert result.end is not None
            return f"{result.start:%d/%m/%Y}–{result.end - timedelta(days=1):%d/%m/%Y}"
        return result.start.strftime("%d/%m/%Y")

    def _items(self, result: PeriodResult) -> list[QStandardItem]:
        percent = lambda value: f"{format_number(value, 1)}%" if value is not None else "—"
        rate = lambda value: format_number(value, 2, show_plus=True) if value is not None else "—"
        values = [self._label(result), str(len(result.hands)), percent(result.vpip), percent(result.pfr),
                  format_currency(result.profit / 100, "USD", show_plus=result.profit > 0), rate(result.bb_per_100),
                  format_currency(result.ev / 100, "USD", show_plus=result.ev > 0), rate(result.ev_bb_per_100)]
        raw = [result.start.toordinal() if result.start else 0, len(result.hands), result.vpip, result.pfr,
               result.profit, result.bb_per_100, result.ev, result.ev_bb_per_100]
        items = []
        palette = get_theme_palette()
        for column, (text, value) in enumerate(zip(values, raw)):
            item = QStandardItem(text)
            item.setData(float(value) if value is not None else None, Qt.ItemDataRole.UserRole)
            item.setData(result.start.isoformat() if result.start else "total", PERIOD_ROLE)
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if column == 0 else Qt.AlignmentFlag.AlignRight))
            if column in (4, 5, 6, 7) and value is not None and value != 0:
                item.setForeground(QColor(palette.get("graph_up", "#48bb78") if value > 0 else palette.get("graph_down", "#f56565")))
            if column in (5, 7) and result.bb_hands < len(result.hands):
                item.setToolTip(_("BB rates use only hands with a valid big blind: ") + f"{result.bb_hands}/{len(result.hands)}")
            items.append(item)
        return items

    def _rebuild_table(self, *_args, prepared=None) -> None:
        self._view_generation += 1
        if prepared is None:
            state = (self.game_combo.currentData(), self.limit_combo.currentData(), self.group_combo.currentData())
            hands, zone = self.raw_hands, self.zone
            if len(hands) > INLINE_HAND_LIMIT:
                self._start_table_aggregation(hands, state, zone)
                return
            prepared = aggregate_results(hands, *state, zone)
        self.filtered_hands, self.periods, self.total = prepared
        self._update_filter_chips()
        self._populate_result_models()
        self._restore_period_selection()

    def _start_table_aggregation(self, hands, state, zone) -> None:
        view_generation = self._view_generation
        generation = self._generation
        data_generation = self._data_generation
        if data_generation == generation and not self._has_load_error:
            self._begin_load_timing()
            self._loading = True
            self._results_current = False
            self._request_status = _("Loading results…")
        self._update_status()

        def completed(result):
            if (not self._closed and generation == self._generation
                    and data_generation == self._data_generation and view_generation == self._view_generation):
                if data_generation == generation and not self._has_load_error:
                    self._loading = False
                    self._results_current = True
                    self._request_status = ""
                self._rebuild_table(prepared=result)

        def failed(message):
            if (view_generation == self._view_generation and data_generation == self._data_generation
                    and data_generation == generation):
                self._fail_results(generation, message)

        self._start_task(lambda: aggregate_results(hands, *state, zone, cooperative=True), completed, failed)

    def _populate_result_models(self) -> None:
        self.table.selectionModel().blockSignals(True)
        self.model.clear()
        self.model.setHorizontalHeaderLabels([_(heading) for heading in HEADINGS])
        descriptions = (
            _("Click a period to show its profit curves. All periods includes the complete filtered selection."),
            _("Number of hands in this filtered period."),
            _("Voluntary preflop participation, measured over recorded VPIP opportunities."),
            _("Preflop raise frequency, measured over recorded PFR opportunities."),
            _("Net profit in US dollars."),
            _("Big blinds won per 100 hands, using each hand's own big blind."),
            _("All-in adjusted expected profit in US dollars."),
            _("All-in adjusted big blinds per 100 hands."),
        )
        for column, description in enumerate(descriptions):
            self.model.setHeaderData(column, Qt.Orientation.Horizontal, description, Qt.ItemDataRole.ToolTipRole)
        for result in self.periods:
            self.model.appendRow(self._items(result))
        self.total_model.clear()
        self.total_model.appendRow(self._items(self.total))
        self.table.selectionModel().blockSignals(False)
        self._sync_total_columns()

    def _restore_period_selection(self) -> None:
        if self.selection == "total":
            self.select_total()
            return
        available = {period.start for period in self.periods}
        if self.selection not in available:
            self.selection = self.periods[0].start if self.periods else None
        for row in range(self.proxy.rowCount()):
            if self.proxy.index(row, 0).data(PERIOD_ROLE) == str(self.selection):
                self.table.selectRow(row)
                self.table.setCurrentIndex(self.proxy.index(row, 0))
                break
        self._render_graph()

    def _sync_total_columns(self, *_args) -> None:
        source, target = self.table.horizontalHeader(), self.total_table.horizontalHeader()
        for visual in range(source.count()):
            logical = source.logicalIndex(visual)
            if logical < target.count():
                target.moveSection(target.visualIndex(logical), visual)
        for column in range(len(HEADINGS)):
            self.total_table.setColumnHidden(column, self.table.isColumnHidden(column))
            self.total_table.setColumnWidth(column, self.table.columnWidth(column))

    def _period_selected(self, current, _previous=None) -> None:
        if not current.isValid():
            return
        chosen = date.fromisoformat(current.siblingAtColumn(0).data(PERIOD_ROLE))
        if self.selection == chosen:
            return
        self.selection = chosen
        self.total_table.clearSelection()
        self._render_graph()

    def select_total(self) -> None:
        self.selection = "total"
        self.table.clearSelection()
        self.total_table.selectRow(0)
        self._render_graph()

    def selected_result(self) -> PeriodResult:
        if self.selection == "total":
            return self.total
        return next((period for period in self.periods if period.start == self.selection), summarize_results(()))

    def _invalidate_graph_request(self, *, discard=False) -> None:
        self._curve_generation += 1
        self._pending_curve = None
        if discard:
            self._curve_requests.clear()
            for worker in self._tasks:
                if getattr(worker, "category", None) == "curve":
                    cancel = getattr(worker, "cancel", None)
                    if cancel is not None:
                        cancel()

    def _render_graph(self) -> None:
        result = self.selected_result()
        self._update_graph_selection(result)
        if not result.hands:
            self._clear_empty_graph()
            return
        in_bb = bool(self.units_combo.currentData())
        cache_key = (id(result.hands), in_bb)
        request_key = (self._generation, self._data_generation, *cache_key)
        if self._pending_curve == request_key:
            return
        self._invalidate_graph_request()
        cached = self._curve_cache.get(cache_key)
        if cached is None and len(result.hands) > INLINE_HAND_LIMIT:
            self._start_curve_request(result, in_bb, cache_key, request_key)
            return
        try:
            curves = cached[1] if cached is not None else profit_curves(result.hands, in_bb=in_bb)
        except ValueError as error:
            self.graph.clear()
            self.status.setText(str(error))
            self._load_started = None
            self._finish_interactive_load()
            self.results_failed.emit()
            return
        self._plot_result_curves(result, curves)

    def _update_graph_selection(self, result) -> None:
        self._update_status()
        self._update_empty_state()
        self.graph_panel.setVisible(bool(self.filtered_hands))
        self.total_table.setVisible(bool(self.filtered_hands))
        self.all_periods_button.setChecked(self.selection == "total")
        heading = _("All periods") if self.selection == "total" else self._label(result)
        self.selection_label.setText(heading + _(" · {0} hands").format(len(result.hands)))

    def _clear_empty_graph(self) -> None:
        self._invalidate_graph_request()
        self.graph.clear()
        self.graph.setTitle(_("No results"), color=get_theme_palette()['muted_text'])
        self.graph.setLabel("bottom", _("Hands"))
        self.graph.setLabel("left", "BB" if self.units_combo.currentData() else "$")
        self._graph_context = None
        self._report_results_ready()

    def _start_curve_request(self, result, in_bb, cache_key, request_key) -> None:
        self._begin_load_timing()
        curve_generation = self._curve_generation
        generation = self._generation
        data_generation = self._data_generation
        self._pending_curve = request_key
        self.graph.clear()
        self.graph.setTitle(_("Loading results…"), color=get_theme_palette()['muted_text'])
        self.graph.setLabel("left", "BB" if in_bb else "$")
        self._graph_context = None
        existing = self._curve_requests.get(request_key)
        if existing is not None:
            # Re-selecting an in-flight curve makes its existing reply current.
            existing["generation"] = curve_generation
            return
        request = {"generation": curve_generation}
        self._curve_requests[request_key] = request

        def is_current():
            return (not self._closed and generation == self._generation
                    and data_generation == self._data_generation and request["generation"] == self._curve_generation
                    and self._pending_curve == request_key)

        def forget_request():
            if self._curve_requests.get(request_key) is request:
                del self._curve_requests[request_key]

        def completed(curves):
            forget_request()
            if not is_current():
                return
            self._pending_curve = None
            if len(self._curve_cache) >= 8:
                self._curve_cache.clear()
            self._curve_cache[cache_key] = (result.hands, curves)
            self._render_graph()

        def failed(message):
            forget_request()
            if is_current():
                self._pending_curve = None
                self.status.setText(message)
                self.graph.clear()
                self._load_started = None
                self._finish_interactive_load()
                self.results_failed.emit()

        self._start_task(lambda: tuple(np.asarray(curve) for curve in profit_curves(result.hands, in_bb=in_bb, cooperative=True)),
                         completed, failed, category="curve")

    def _plot_result_curves(self, result, curves) -> None:
        self.graph.plot_profit_data(tuple(np.asarray(curve) for curve in curves), [h.hand_id for h in result.hands],
                                    units="BB" if self.units_combo.currentData() else "$",
                                     title=f"{self._label(result)} · {len(result.hands)} " + _("hands"), show_all_lines=True)
        context = (self.hero_combo.currentData(), self.selection, self.units_combo.currentData(),
                   tuple(hand.hand_id for hand in result.hands))
        if context != self._graph_context:
            self.graph.getViewBox().autoRange()
        self._graph_context = context
        if self.graph.plotItem.legend is not None:
            self.graph.plotItem.legend.hide()
        self.graph.plotItem.titleLabel.hide()
        palette = get_theme_palette()
        for check, key, fallback in zip(self.line_checks, ("graph_up", "graph_showdown", "graph_down", "graph_ev"),
                                        ("#48bb78", "#3182ce", "#f56565", "#dd6b20")):
            check.setStyleSheet(f"color:{palette.get(key, fallback)}")
        self._line_visibility()
        self._report_results_ready()

    def _update_filter_chips(self) -> None:
        entries = []
        for key, caption, combo in (("game", _("Game"), self.game_combo), ("limit", _("Limit"), self.limit_combo)):
            if combo.currentData() is not None:
                entries.append((key, f"{caption}: {combo.currentText()}", lambda widget=combo: widget.setCurrentIndex(0)))
        self.active_filters.set_entries(entries, self._clear_result_filters)
        self.more_filters.setText(_("Filters") + (f" ({len(entries)})" if entries else ""))

    def _clear_result_filters(self) -> None:
        for combo in (self.game_combo, self.limit_combo):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._rebuild_table()

    def _update_empty_state(self) -> None:
        if self.model.rowCount():
            self.empty_state.hide()
        elif self._loading:
            self.empty_state.show_message(_("Loading results…"), _("Your results will appear here when the query finishes."))
        elif self._has_load_error:
            self.empty_state.show_message(_("Results could not be loaded"), _("Try the query again."), _("Retry"), self.refresh)
        elif not self.hero_combo.count():
            self.empty_state.show_message(_("Import your first hands"),
                                          _("Import hand histories, then choose your Hero to start reviewing results."),
                                          _("Import hands"), self.import_requested.emit)
        elif self.raw_hands and not self.filtered_hands:
            self.empty_state.show_message(_("No matches for these filters"), _("Clear the game and limit filters to return to your results."),
                                          _("Clear filters"), self._clear_result_filters)
        else:
            self.empty_state.show_message(_("No cash hands in this date range"), _("Try a wider date range to find your imported hands."),
                                          _("Show all history"), lambda: self.interval_combo.setCurrentIndex(self.interval_combo.findData("all")))

    def _update_status(self) -> None:
        self.retry_button.setVisible(self._has_load_error)
        self._update_empty_state()
        self.hands_button.setEnabled(self._results_current and bool(self.selected_result().hands))
        self.export_button.setEnabled(self._results_current and bool(self.filtered_hands))
        if self._request_status:
            self.status.setText(self._request_status)
        elif not self.raw_hands:
            self.status.setText(_("No USD cash hands in this period. Try All history or another interval."))
        elif not self.filtered_hands:
            self.status.setText(_("No hands match these filters."))
        else:
            self.status.setText(_("{0} hands · {1} periods").format(len(self.filtered_hands), len(self.periods)))

    def _choose_export_path(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, _("Export results"), "results.csv", _("CSV files (*.csv)"))
        if path:
            self.export_csv(path)

    def export_csv(self, path: str) -> bool:
        if not self._results_current or not self.filtered_hands:
            return False
        periods = {period.start.isoformat(): period for period in self.periods}
        ordered = [periods[self.proxy.index(row, 0).data(PERIOD_ROLE)] for row in range(self.proxy.rowCount())]
        content = results_csv(ordered, self.total, self._label).encode("utf-8-sig")
        output = QSaveFile(path)
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            self.status.setText(_("Could not export results: ") + output.errorString())
            return False
        if output.write(content) != len(content):
            output.cancelWriting()
            self.status.setText(_("Could not export results: ") + output.errorString())
            return False
        if not output.commit():
            self.status.setText(_("Could not export results: ") + output.errorString())
            return False
        self.status.setText(_("Exported {0} periods and Total.").format(len(ordered)))
        return True

    def _line_visibility(self) -> None:
        for curve, check in zip(self.graph.listDataItems(), self.line_checks):
            curve.setVisible(check.isChecked())

    def open_hands(self) -> None:
        if not self._results_current:
            return
        hands = self.selected_result().hands
        if hands:
            self.hands_requested.emit([hand.hand_id for hand in reversed(hands)])

    def shutdown_workers(self) -> None:
        self._closed = True
        self._finish_interactive_load()
        self._custom_date_timer.stop()
        self._generation += 1
        for worker in self._tasks:
            cancel = getattr(worker, "cancel", None)
            if cancel is not None:
                cancel()
        workers = [worker for worker in (*self._workers, *self._tasks) if isinstance(worker, QThread)]
        retain_until_finished(workers)

    def close_owned_database(self) -> None:
        self.shutdown_workers()
        if self._owns_db and not self._db_closed:
            self._db_closed = True
            db, setup = self.db, self._setup_worker

            def disconnect():
                database = db
                if database is None and setup is not None and setup.result is not None:
                    database = setup.result[0]
                if database is not None:
                    with contextlib.suppress(Exception):
                        database.disconnect()

            workers = [worker for worker in (*self._workers, *self._tasks) if isinstance(worker, QThread)]
            retain_until_finished(workers, disconnect)

    def closeEvent(self, event) -> None:
        self.close_owned_database()
        super().closeEvent(event)
