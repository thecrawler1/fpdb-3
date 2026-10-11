"""Compact calendar results, selected-period curves and access to existing hands."""

from __future__ import annotations

import contextlib
from datetime import date, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
from PySide6.QtCore import QDate, QSortFilterProxyModel, Qt, QTimer, QTimeZone, Signal
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
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

from fpdb_3_legacy import Card, Database
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
from fpdb_3_legacy.ring_stats.base import DbWorker
from fpdb_3_legacy.ring_stats.styles import get_modern_qss, get_theme_palette
from fpdb_3_legacy.ring_stats.views.dashboard_view import ProfitGraphWidget
from fpdb_3_legacy.table_columns import install_column_controls

PERIOD_ROLE = int(Qt.ItemDataRole.UserRole) + 1
HEADINGS = ("Period", "Hands", "VPIP", "PFR", "Profit ($)", "bb/100", "EV ($)", "EV bb/100")


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


class GuiResultsViewer(QWidget):
    hands_requested = Signal(list)

    def __init__(self, config, querylist=None, *, db=None, zone: tzinfo | None = None, autoload=True):
        super().__init__()
        self.conf = config
        self.db = db if db is not None else Database.Database(config, sql=querylist)
        self._owns_db = db is None
        self.zone = zone or local_zone()
        self._workers: list[DbWorker] = []
        self._generation = 0
        self._closed = False
        self._db_closed = False
        self.raw_hands: tuple[ResultHand, ...] = ()
        self.filtered_hands: tuple[ResultHand, ...] = ()
        self.periods: list[PeriodResult] = []
        self.total = summarize_results(())
        self.selection: date | str | None = None
        self.setObjectName("resultsViewer")
        self.setStyleSheet(get_modern_qss())
        self._build_controls()
        self._build_table_and_graph()
        self._populate_heroes()
        self._set_preset()
        self._connect_controls()
        self._rebuild_table()
        if autoload:
            QTimer.singleShot(0, self.refresh)

    def _build_controls(self) -> None:
        layout = QVBoxLayout(self)
        self.main_layout = layout
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
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
        for title, control in (("Hero", self.hero_combo), ("Group by", self.group_combo), ("Period", self.interval_combo)):
            toolbar.addWidget(QLabel(_(title)))
            toolbar.addWidget(control)
        self.from_date, self.to_date = QDateEdit(), QDateEdit()
        for control in (self.from_date, self.to_date):
            control.setCalendarPopup(True)
            control.setDisplayFormat("dd/MM/yyyy")
            toolbar.addWidget(control)
        toolbar.addStretch()
        self.more_filters = QToolButton()
        self.more_filters.setText(_("More filters"))
        self.more_filters.setCheckable(True)
        self.columns_button = QToolButton()
        self.columns_button.setText(_("Columns"))
        self.columns_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.refresh_button = QPushButton(_("Refresh"))
        toolbar.addWidget(self.more_filters)
        toolbar.addWidget(self.columns_button)
        toolbar.addWidget(self.refresh_button)
        layout.addLayout(toolbar)
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
        self.status = QLabel()
        layout.addWidget(self.status)

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
        table_layout.addWidget(self.table)
        self.total_model = QStandardItemModel(0, len(HEADINGS), self)
        self.total_table = self._table(self.total_model)
        self.total_table.setObjectName("calendarResultsTotal")
        self.total_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.total_table.horizontalHeader().hide()
        self.total_table.setFixedHeight(48)
        table_layout.addWidget(self.total_table)
        self.splitter.addWidget(table_panel)
        graph_panel = QWidget()
        graph_layout = QVBoxLayout(graph_panel)
        graph_layout.setContentsMargins(0, 8, 0, 0)
        options = QHBoxLayout()
        self.units_combo = QComboBox()
        self.units_combo.addItem("$", False)
        self.units_combo.addItem("BB", True)
        options.addWidget(QLabel(_("Graph")))
        options.addWidget(self.units_combo)
        self.line_checks = []
        for name in ("Profit", "Showdown", "Non-showdown", "All-in EV"):
            check = QCheckBox(_(name))
            check.setChecked(True)
            self.line_checks.append(check)
            options.addWidget(check)
        options.addStretch()
        self.reset_graph_button = QPushButton(_("Reset view"))
        self.reset_graph_button.clicked.connect(lambda: self.graph.getViewBox().autoRange())
        options.addWidget(self.reset_graph_button)
        self.hands_button = QPushButton(_("View hands"))
        options.addWidget(self.hands_button)
        graph_layout.addLayout(options)
        self.graph = ProfitGraphWidget()
        graph_layout.addWidget(self.graph, 1)
        self.splitter.addWidget(graph_panel)
        self.splitter.setSizes([300, 360])
        self._connect_view_actions()

    def _connect_view_actions(self) -> None:
        self.column_controls = install_column_controls(
            self.table, "calendar-results", essential=HEADINGS, keys=dict(enumerate(HEADINGS)),
        )
        self.column_controls.visibility_changed.connect(lambda column, visible: self.total_table.setColumnHidden(column, not visible))
        self.columns_button.setMenu(self.column_controls.menu())
        self.table.horizontalHeader().sectionResized.connect(self._sync_total_columns)
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
        self.setStyleSheet(get_modern_qss())
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
        seen = {self.hero_combo.itemData(i) for i in range(self.hero_combo.count())}
        self.hero_combo.blockSignals(True)
        for site in self.conf.get_supported_sites():
            aliases = self.conf.get_hero_aliases(site)
            ids = [self.db.get_player_id(self.conf, site, alias) for alias in aliases]
            if not any(ids):
                ids = self.db.get_hero_player_ids(site)
            for player_id in ids:
                if player_id is not None and player_id not in seen:
                    seen.add(player_id)
                    name = self.db.get_player_name_by_id(player_id)
                    self.hero_combo.addItem(f"{name} · {site}", int(player_id))
        self.db.rollback()
        if self.hero_combo.count() and self.hero_combo.currentIndex() < 0:
            self.hero_combo.setCurrentIndex(0)
        self.hero_combo.blockSignals(False)

    def _connect_controls(self) -> None:
        self.refresh_button.clicked.connect(self.refresh)
        self.hero_combo.currentIndexChanged.connect(self.refresh)
        self.interval_combo.currentIndexChanged.connect(self._interval_changed)
        self.group_combo.currentIndexChanged.connect(self._regroup)
        self.more_filters.toggled.connect(self.filter_panel.setVisible)
        self.game_combo.currentIndexChanged.connect(self._rebuild_table)
        self.limit_combo.currentIndexChanged.connect(self._rebuild_table)

    def _set_preset(self) -> None:
        key = self.interval_combo.currentData()
        custom = key == "custom"
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
        if self._closed:
            return
        self._generation += 1
        generation = self._generation
        previous_selection = self.selection
        self.raw_hands = ()
        self._rebuild_table()
        self.selection = previous_selection
        player_id = self.hero_combo.currentData()
        if player_id is None:
            self._populate_heroes()
            player_id = self.hero_combo.currentData()
        if player_id is None:
            self.status.setText(_("No configured Hero found. Import hands and check the site screen name."))
            return
        start = end = None
        if self.interval_combo.currentData() != "all":
            start, end = self.from_date.date().toPython(), self.to_date.date().toPython()
        try:
            query, params = results_query(player_id, start, end, self.zone, self.db.sql.query["placeholder"])
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.status.setText(_("Loading results…"))
        self._workers = [worker for worker in self._workers if not worker.isFinished()]
        worker = DbWorker(self.db, "calendarResults", query, params)
        self._workers.append(worker)

        def loaded(_name, rows, _columns):
            self._receive_rows(generation, rows)

        def failed(message):
            if not self._closed and generation == self._generation:
                self.status.setText(_("Could not load results: ") + message)

        worker.finished.connect(loaded)
        worker.error.connect(failed)
        worker.start()

    def _receive_rows(self, generation, rows) -> None:
        if self._closed or generation != self._generation:
            return
        try:
            self.raw_hands = parse_result_rows(rows)
        except (ValueError, TypeError, ArithmeticError) as error:
            self.status.setText(_("Could not read result data: ") + str(error))
            return
        self._populate_filters()
        self.status.setText("" if self.raw_hands else _("No USD cash hands in this period. Try All history or another interval."))
        self._rebuild_table()

    def _populate_filters(self) -> None:
        games = sorted({hand.game for hand in self.raw_hands})
        stakes = sorted({(hand.big_blind, hand.limit_type, hand.stake_key) for hand in self.raw_hands})
        game_options = [(str(Card.games.get(game, (game,))[0]), game) for game in games]
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

    def _rebuild_table(self) -> None:
        game, stake = self.game_combo.currentData(), self.limit_combo.currentData()
        self.filtered_hands = tuple(h for h in self.raw_hands if (game is None or h.game == game) and (stake is None or h.stake_key == stake))
        self.periods = group_results(self.filtered_hands, self.group_combo.currentData(), self.zone)
        self.total = summarize_results(self.filtered_hands)
        self.table.selectionModel().blockSignals(True)
        self.model.clear()
        self.model.setHorizontalHeaderLabels([_(heading) for heading in HEADINGS])
        for result in self.periods:
            self.model.appendRow(self._items(result))
        self.total_model.clear()
        self.total_model.appendRow(self._items(self.total))
        self.table.selectionModel().blockSignals(False)
        self._sync_total_columns()
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

    def _render_graph(self) -> None:
        result = self.selected_result()
        self.hands_button.setEnabled(bool(result.hands))
        if not result.hands:
            self.graph.clear()
            self.graph.setTitle(_("No results"))
            self.graph.setLabel("bottom", _("Hands"))
            self.graph.setLabel("left", "BB" if self.units_combo.currentData() else "$")
            if self.raw_hands:
                self.status.setText(_("No hands match these filters."))
            return
        try:
            curves = profit_curves(result.hands, in_bb=bool(self.units_combo.currentData()))
        except ValueError as error:
            self.graph.clear()
            self.status.setText(str(error))
            return
        self.graph.plot_profit_data(tuple(np.asarray(curve) for curve in curves), [h.hand_id for h in result.hands],
                                    units="BB" if self.units_combo.currentData() else "$",
                                    title=f"{self._label(result)} · {len(result.hands)} " + _("hands"), show_all_lines=True)
        if self.graph.plotItem.legend is not None:
            self.graph.plotItem.legend.hide()
        palette = get_theme_palette()
        for check, key, fallback in zip(self.line_checks, ("graph_up", "graph_showdown", "graph_down", "graph_ev"),
                                        ("#48bb78", "#3182ce", "#f56565", "#dd6b20")):
            check.setStyleSheet(f"color:{palette.get(key, fallback)}")
        self.status.clear()
        self._line_visibility()

    def _line_visibility(self) -> None:
        for curve, check in zip(self.graph.listDataItems(), self.line_checks):
            curve.setVisible(check.isChecked())

    def open_hands(self) -> None:
        hands = self.selected_result().hands
        if hands:
            self.hands_requested.emit([hand.hand_id for hand in reversed(hands)])

    def shutdown_workers(self) -> None:
        self._closed = True
        self._generation += 1
        for worker in self._workers:
            worker.wait()
        self._workers.clear()

    def close_owned_database(self) -> None:
        self.shutdown_workers()
        if self._owns_db and not self._db_closed:
            with contextlib.suppress(Exception):
                self.db.disconnect()
            self._db_closed = True

    def closeEvent(self, event) -> None:
        self.close_owned_database()
        super().closeEvent(event)
