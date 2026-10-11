#!/usr/bin/env python
from __future__ import annotations

# Copyright 2010-2011 Maxime Grandchamp
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
# In the "official" distribution you can find the license in agpl-3.0.txt.
#
# This code once was in GuiReplayer.py and was split up in this and the former by zarturo.
# import L10n
# _ = L10n.get_translation()
import contextlib
from collections import OrderedDict
from decimal import Decimal
from functools import partial
from io import StringIO
from typing import Any

from PySide6.QtCore import QCoreApplication, QRegularExpression, QSize, QSortFilterProxyModel, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDoubleValidator,
    QIntValidator,
    QRegularExpressionValidator,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fpdb_3_legacy import SQL, Card, Configuration, Database, Deck, Filters, GuiReplayer, Hand
from fpdb_3_legacy.analytics_query import escape_literal_percent
from fpdb_3_legacy.design_system import current_palette
from fpdb_3_legacy.hand_review_dialog import add_review_action
from fpdb_3_legacy.hand_share_dialog import add_share_actions
from fpdb_3_legacy.hand_viewer_filters import build_filter_clauses, required_analytics_subsystems
from fpdb_3_legacy.holdem_classes import RANKS, grid_labels
from fpdb_3_legacy.i18n import gettext as _
from fpdb_3_legacy.localized_formats import format_currency, format_datetime, format_number
from fpdb_3_legacy.loggingFpdb import get_logger
from fpdb_3_legacy.review_widgets import EmptyState, FilterChips, labeled_control, review_stylesheet, text_label
from fpdb_3_legacy.table_cards import card_tokens, render_table_cards, table_card_icon
from fpdb_3_legacy.table_columns import install_column_controls

log = get_logger("gui_hand_viewer")


class PagedHandProxy(QSortFilterProxyModel):
    """Ask the viewer to sort its complete ID list, never just this page."""

    sort_requested = Signal(int, object)

    def sort(self, column, order=Qt.SortOrder.AscendingOrder) -> None:
        self.sort_requested.emit(column, order)


class StartingHandPickerDialog(QDialog):
    """A multi-select 13x13 Hold'em class picker with common shortcuts."""

    def __init__(self, selected: set[str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Starting-hand range"))
        self._buttons: dict[str, QPushButton] = {}
        self._selected = set(selected or ())
        layout = QVBoxLayout(self)
        shortcuts = QHBoxLayout()
        for label, predicate in (
            (_("Pairs"), lambda hand: len(hand) == 2),
            (_("Suited"), lambda hand: hand.endswith("s")),
            (_("Offsuit"), lambda hand: hand.endswith("o")),
            (_("Broadway"), lambda hand: hand[0] in "AKQJT" and hand[1] in "AKQJT"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, match=predicate: self._select_matching(match))
            shortcuts.addWidget(button)
        clear = QPushButton(_("Clear"))
        clear.clicked.connect(lambda: self._select_matching(lambda _hand: False))
        shortcuts.addWidget(clear)
        invert = QPushButton(_("Invert"))
        invert.clicked.connect(self._invert)
        shortcuts.addWidget(invert)
        layout.addLayout(shortcuts)

        grid = QGridLayout()
        grid.setSpacing(2)
        grid.addWidget(QLabel(""), 0, 0)
        for column, rank in enumerate(RANKS, start=1):
            grid.addWidget(QLabel(rank), 0, column)
            grid.addWidget(QLabel(rank), column, 0)
        for row, hand_labels in enumerate(grid_labels(), start=1):
            for column, hand in enumerate(hand_labels, start=1):
                button = QPushButton(hand)
                button.setCheckable(True)
                button.setChecked(hand in self._selected)
                button.setFixedSize(52, 35)
                button.setStyleSheet("padding:0; min-width:0; min-height:0;")
                button.toggled.connect(lambda checked, value=hand: self._set_selected(value, checked))
                self._buttons[hand] = button
                grid.addWidget(button, row, column)
        layout.addLayout(grid)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def _set_selected(self, hand: str, selected: bool) -> None:
        if selected:
            self._selected.add(hand)
        else:
            self._selected.discard(hand)

    def _select_matching(self, predicate) -> None:
        self._selected = {hand for hand in self._buttons if predicate(hand)}
        for hand, button in self._buttons.items():
            button.setChecked(hand in self._selected)

    def _invert(self) -> None:
        self._select_matching(lambda hand: hand not in self._selected)

    def selected_hands(self) -> set[str]:
        return set(self._selected)


class GuiHandViewer(QSplitter):
    def __init__(self, config, querylist, mainwin) -> None:
        QSplitter.__init__(self, mainwin)
        self.config = config
        self.main_window = mainwin
        self.sql = querylist
        self.replayer: Any = None
        self._page_loading = False

        self.db = Database.Database(self.config, sql=self.sql)

        filters_display = {
            "Heroes": True,
            "Sites": True,
            "Games": True,
            "Currencies": False,
            "Limits": True,
            "LimitSep": True,
            "LimitType": True,
            "Positions": True,
            "Type": True,
            "UseType": "ring",
            "Seats": False,
            "SeatSep": False,
            "Dates": True,
            "Cards": False,
            "Groups": False,
            "GroupsAll": False,
            "Button1": True,
            "Button2": False,
        }

        self.filters = Filters.Filters(self.db, display=filters_display)
        self.filters.registerButton1Name("Load Hands")
        self.filters.registerButton1Callback(self.loadHands)
        self.filters.registerCardsCallback(self.filter_cards_cb)

        self._starting_hands: set[str] = set()
        self.filterPanel = QWidget()
        self.filterPanelLayout = QVBoxLayout(self.filterPanel)
        self.filterPanelLayout.setContentsMargins(0, 0, 0, 0)
        self.filterPanelLayout.addWidget(self.filters)
        self.advancedFilters = self._build_advanced_filters()
        self.filterPanelLayout.addWidget(self.advancedFilters)
        self.filterPanelLayout.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("filterSidebar")
        scroll.setWidget(self.filterPanel)
        # Without this the scroll area leaves the filter widget at a collapsed
        # height, squashing list-heavy frames (e.g. the CATEGORY checkboxes) to a
        # few pixels tall. Matches GuiTourneyPlayerStats.
        scroll.setWidgetResizable(True)

        self.handsFrame = QFrame()
        self.handsFrame.setObjectName("handsSurface")
        self.handsFrame.setStyleSheet(review_stylesheet())
        self.handsVBox = QVBoxLayout()
        self.handsFrame.setLayout(self.handsVBox)
        toolbar = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(text_label(_("Hands"), "title"))
        heading.addWidget(text_label(_("Choose a hand to review"), "caption"))
        toolbar.addLayout(heading)
        self.handSearch = QLineEdit()
        self.handSearch.setPlaceholderText(_("Find hand ID…"))
        self.handSearch.setToolTip(_("Search internal or site hand ID across all loaded pages. Partial IDs are accepted."))
        self.handSearch.setAccessibleName(_("Find hand ID"))
        self.handSearch.setClearButtonEnabled(True)
        self.handSearch.setMaximumWidth(240)
        self.handSearch.setMaxLength(31)
        self.handSearch.setValidator(QRegularExpressionValidator(QRegularExpression(r"#?[0-9]{0,30}"), self))
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self.handSearch.textChanged.connect(lambda _text: self._search_timer.start())
        self._search_timer.timeout.connect(self._apply_id_search)
        toolbar.addStretch()
        self.filtersButton = QPushButton(_("Filters"))
        self.filtersButton.setCheckable(True)
        self.filtersButton.toggled.connect(scroll.setVisible)
        toolbar.addWidget(self.filtersButton)
        self.loadButton = QPushButton(_("Load hands"))
        self.loadButton.clicked.connect(self.loadHands)
        toolbar.addWidget(self.loadButton)
        self.columnsButton = QToolButton()
        self.columnsButton.setText(_("Columns"))
        self.columnsButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar.addWidget(self.columnsButton)
        self.replayButton = QPushButton(_("Replay"))
        self.replayButton.setProperty("primaryAction", True)
        self.replayButton.clicked.connect(self._replay_selected)
        self.handsVBox.addLayout(toolbar)
        search_row = QHBoxLayout()
        search_row.addWidget(labeled_control(_("Find a hand"), self.handSearch))
        search_row.addStretch()
        self.reviewHint = text_label(_("Double-click to replay · Ctrl+C to copy"), "caption")
        search_row.addWidget(self.reviewHint, 0, Qt.AlignmentFlag.AlignBottom)
        self.handsVBox.addLayout(search_row)
        self.active_hand_filters = FilterChips()
        self.handsVBox.addWidget(self.active_hand_filters)
        self.handStatusLabel = QLabel()
        self.handStatusLabel.setWordWrap(True)
        self.handStatusLabel.hide()
        self.handsVBox.addWidget(self.handStatusLabel)
        scroll.hide()

        self.addWidget(scroll)
        self.addWidget(self.handsFrame)
        self.setStretchFactor(0, 0)
        self.setStretchFactor(1, 1)

        self.deck_instance = Deck.Deck(self.config, height=42, width=30)
        self.cardImages = self.init_card_images()

        # !Dict of colnames and their column idx in the model/ListStore
        self.colnum = {
            "Date": 0,
            "Flags": 1,
            "Stakes": 2,
            "Players": 3,
            "Pos": 4,
            "Street0": 5,
            "Action0": 6,
            "Street1-4": 7,
            "Action1-4": 8,
            "Combo": 9,
            "Won": 10,
            "Bet": 11,
            "Net": 12,
            "Game": 13,
            "HandId": 14,
            "Total Pot": 15,
            "Rake": 16,
            "SiteHandNo": 17,
            "Splash": 18,
        }
        self.view = QTableView()
        self.view.setIconSize(QSize(700, 160))
        self.view.horizontalHeader().setMinimumSectionSize(90)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.view.horizontalHeader().setStretchLastSection(False)
        self.view.setSelectionBehavior(QTableView.SelectRows)
        self.handsVBox.addWidget(self.view)
        self.empty_state = EmptyState(self.view)
        self.selectionBar = QWidget()
        self.selectionBar.setObjectName("handSelectionBar")
        selection_layout = QHBoxLayout(self.selectionBar)
        selection_layout.setContentsMargins(0, 10, 0, 4)
        selection_text = QVBoxLayout()
        selection_text.setSpacing(2)
        self.selectedHandLabel = text_label(_("Select a hand"), "heading")
        self.selectedHandDetails = text_label(_("Its cards and result will appear here."), "caption")
        selection_text.addWidget(self.selectedHandLabel)
        selection_text.addWidget(self.selectedHandDetails)
        selection_layout.addLayout(selection_text)
        selection_layout.addStretch()
        selection_layout.addWidget(self.replayButton)
        self.handsVBox.addWidget(self.selectionBar)
        self.model = QStandardItemModel(0, len(self.colnum), self.view)
        self.filterModel = PagedHandProxy()
        self.filterModel.setSourceModel(self.model)
        self.filterModel.setSortRole(Qt.ItemDataRole.UserRole)

        self.view.setModel(self.filterModel)
        self.view.verticalHeader().hide()
        self.model.setHorizontalHeaderLabels(
            [
                "Date",
                "Flags",
                "Stakes",
                "Players",
                "Position",
                "Cards",
                "Preflop Action",
                "Board",
                "Postflop Action",
                "Made hand",
                "Won",
                "Bet",
                "Net",
                "Game",
                "HandId",
                "Total Pot",
                "Rake",
                "SiteHandId",
                "Splash",
            ],
        )
        self.columnControls = install_column_controls(
            self.view, "cash-hands", essential=("Date", "Stakes", "Pos", "Street0", "Street1-4", "Net", "Total Pot"),
            keys={index: key for key, index in self.colnum.items()},
        )
        self.columnsButton.setMenu(self.columnControls.menu())
        self.replayButton.setEnabled(False)
        self.view.selectionModel().currentRowChanged.connect(self._update_selected_hand)
        for key, description in {
            "Date": _("When the hand was played, in your display time zone."),
            "Street0": _("Hero's starting cards. Double-click the row to replay the hand."),
            "Street1-4": _("Community cards; multiple boards are stacked."),
            "Net": _("Hero's net result after contributions and collected money."),
            "Total Pot": _("Total pot for the hand, not just the amount won by Hero."),
            "Pos": _("Hero's position: SB, BB, BTN, CO, HJ, LJ, MP or UTG."),
        }.items():
            self.model.setHeaderData(self.colnum[key], Qt.Orientation.Horizontal, description, Qt.ItemDataRole.ToolTipRole)

        self.view.doubleClicked.connect(self.row_activated)
        setattr(self.view, "contextMenuEvent", self.contextMenu)

        def resize_rows(_index, start, end) -> None:
            for row in range(start, end + 1):
                self.view.resizeRowToContents(row)

        self.filterModel.rowsInserted.connect(
            resize_rows,
        )
        setattr(self.filterModel, "filterAcceptsRow", lambda row, sourceParent: self.is_row_in_card_filter(row))

        # Pagination state: the full list of hand ids is kept and only one page
        # is reconstructed/rendered at a time (each hand is rebuilt from the DB,
        # which is expensive on large databases such as GGPoker).
        self.all_handids: list[Any] = []
        self._loaded_handids: list[Any] = []
        self._hand_numbers: dict[Any, str] | None = None
        self._active_search = ""
        self.hands: OrderedDict[Any, Any] = OrderedDict()
        self._rendered_page: int | None = None
        self.page = 0
        self.page_size = 100
        self._sort_column = self.colnum["Date"]
        self._sort_order = Qt.SortOrder.DescendingOrder
        self._sort_keys = {}
        self.filterModel.sort_requested.connect(self._sort_hands)

        self.pagerBox = QHBoxLayout()
        self.prevPageButton = QPushButton(_("◀ Prev"))
        self.nextPageButton = QPushButton(_("Next ▶"))
        self.pageLabel = QLabel("")
        self.pageSpin = QSpinBox()
        self.pageSpin.setKeyboardTracking(False)
        self.pageSpin.setPrefix(_("Page "))
        self.pageSpin.setAccessibleName(_("Go to page"))
        self.pageSpin.valueChanged.connect(self._jump_to_page)
        self.pageSizeCombo = QComboBox()
        self.pageSizeCombo.setAccessibleName(_("Hands per page"))
        for size in (25, 50, 100, 250):
            self.pageSizeCombo.addItem(str(size), size)
        saved_size = self.columnControls.settings.value("cash-hands/page-size", 100, type=int)
        self.page_size = saved_size if saved_size in (25, 50, 100, 250) else 100
        self.pageSizeCombo.setCurrentIndex(self.pageSizeCombo.findData(self.page_size))
        self.pageSizeCombo.currentIndexChanged.connect(self._change_page_size)
        self.prevPageButton.clicked.connect(self.prev_page)
        self.nextPageButton.clicked.connect(self.next_page)
        self.pagerBox.addWidget(self.prevPageButton)
        self.pagerBox.addWidget(self.nextPageButton)
        self.pagerBox.addWidget(self.pageSpin)
        self.pagerBox.addWidget(self.pageLabel)
        self.pagerBox.addStretch(1)
        self.pagerBox.addWidget(QLabel(_("Hands per page")))
        self.pagerBox.addWidget(self.pageSizeCombo)
        # Flag filters (applied at the SQL level on the next Load Hands).
        self.flagAllIn = QCheckBox("AI")
        self.flagShowdown = QCheckBox("SD")
        self.flagRunItTwice = QCheckBox("RIT")
        self.flagCashout = QCheckBox("CO$")
        self.flagBombPot = QCheckBox("Bomb")
        self.flagDoubleBoard = QCheckBox("2xB")
        _flag_tips = {
            "AI": "went all-in",
            "SD": "saw showdown",
            "RIT": "run it twice/three",
            "CO$": "EV cashout",
            "Bomb": "bomb pot",
            "2xB": "double board",
        }
        self.flagFilters = QGroupBox(_("Hand features"))
        flags_layout = QGridLayout(self.flagFilters)
        for index, cb in enumerate((
            self.flagAllIn,
            self.flagShowdown,
            self.flagRunItTwice,
            self.flagCashout,
            self.flagBombPot,
            self.flagDoubleBoard,
        )):
            cb.setToolTip(_("Filter: ") + _flag_tips[cb.text()])
            cb.setText(_({"AI": "All-in", "SD": "Showdown", "RIT": "Run it twice", "CO$": "Cashout",
                          "Bomb": "Bomb pot", "2xB": "Double board"}[cb.text()]))
            cb.stateChanged.connect(self._hand_features_changed)
            flags_layout.addWidget(cb, index // 2, index % 2)
        self.flagSplashPot = QComboBox()
        self.flagSplashPot.addItem(_("All hands"), "all")
        self.flagSplashPot.addItem(_("Splash pots only"), "only")
        self.flagSplashPot.addItem(_("Exclude splash pots"), "exclude")
        self.flagSplashPot.setToolTip(_("Filter: splash pot"))
        self.flagSplashPot.currentIndexChanged.connect(self._hand_features_changed)
        flags_layout.addWidget(QLabel(_("Splash pot")), 3, 0)
        flags_layout.addWidget(self.flagSplashPot, 3, 1)
        self.flagFilters.hide()
        self.filtersButton.toggled.connect(self.flagFilters.setVisible)
        self.filterPanelLayout.insertWidget(0, self.flagFilters)
        self.handsVBox.addLayout(self.pagerBox)
        self._update_pager()

        self.columnControls.resize_to_contents()
        self.view.setSortingEnabled(True)

    def _replay_selected(self) -> None:
        index = self.view.currentIndex()
        if index.isValid():
            self.row_activated(index)

    def _update_selected_hand(self, _current=None, _previous=None) -> None:
        index = self.view.currentIndex()
        self.replayButton.setEnabled(index.isValid() and not self._page_loading)
        if not index.isValid():
            self.selectedHandLabel.setText(_("Select a hand"))
            self.selectedHandDetails.setText(_("Its cards and result will appear here."))
            return
        value = lambda key, role=Qt.ItemDataRole.DisplayRole: index.siblingAtColumn(self.colnum[key]).data(role)
        self.selectedHandLabel.setText(_("Hand #{0}").format(value('SiteHandNo') or value('HandId')))
        suits = {"h": "♥", "d": "♦", "c": "♣", "s": "♠"}
        cards = " ".join(card[0] + suits.get(card[-1], "?") for card in (value('Street0', Qt.ItemDataRole.UserRole + 1) or "").split())
        self.selectedHandDetails.setText(f"{cards} · {value('Pos')} · " + _("Net {0}").format(value('Net')))

    def _hand_features_changed(self) -> None:
        self._update_hand_filter_chips()
        self.loadHands(None)

    def _clear_hand_features(self) -> None:
        for checkbox in self._feature_checkboxes():
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.blockSignals(False)
        self.flagSplashPot.blockSignals(True)
        self.flagSplashPot.setCurrentIndex(0)
        self.flagSplashPot.blockSignals(False)
        self.loadHands(None)

    def _feature_checkboxes(self):
        return (self.flagAllIn, self.flagShowdown, self.flagRunItTwice,
                self.flagCashout, self.flagBombPot, self.flagDoubleBoard)

    def _update_hand_filter_chips(self) -> None:
        entries = []
        labels = [checkbox.text() for checkbox in self._feature_checkboxes() if checkbox.isChecked()]
        if self.flagSplashPot.currentData() != "all":
            labels.append(self.flagSplashPot.currentText())
        if labels:
            label = ", ".join(labels[:2]) + (f" +{len(labels) - 2}" if len(labels) > 2 else "")
            entries.append(("features", label, self._clear_hand_features))
        if self.handSearch.text().lstrip("#"):
            entries.append(("id", _("Hand ID: ") + self.handSearch.text(), self.handSearch.clear))
        self.active_hand_filters.set_entries(entries, self._clear_review_filters)
        if labels:
            self.active_hand_filters.buttons['features'].setToolTip(_("Clear hand features: ") + ", ".join(labels))

    def _clear_review_filters(self) -> None:
        self.handSearch.blockSignals(True)
        self.handSearch.clear()
        self.handSearch.blockSignals(False)
        self._search_timer.stop()
        self._clear_hand_features()

    def _update_hand_empty_state(self) -> None:
        if self.filterModel.rowCount():
            self.empty_state.hide()
        elif self.handSearch.text().lstrip("#"):
            self.empty_state.show_message(_("No matching hand"), _("Clear the ID search to return to your loaded hand list."),
                                          _("Clear search"), self.handSearch.clear)
        elif not self._loaded_handids:
            self.empty_state.show_message(_("No hands to review"), _("Open filters, choose a Hero and date range, then load hands."),
                                          _("Open filters"), lambda: self.filtersButton.setChecked(True))
        else:
            self.empty_state.show_message(_("No hands available on this page"), _("Try loading the page again or adjust the filters."),
                                          _("Reload page"), self.render_page)

    def _build_advanced_filters(self) -> QGroupBox:
        group = QGroupBox(_("Advanced review filters"))
        grid = QGridLayout(group)
        self.startingHandButton = QPushButton(_("Choose hands…"))
        self.startingHandSummary = QLabel(_("All starting hands"))
        self.startingHandButton.clicked.connect(self._choose_starting_hands)
        grid.addWidget(QLabel(_("Hold'em starting hand")), 0, 0)
        grid.addWidget(self.startingHandButton, 0, 1)
        grid.addWidget(self.startingHandSummary, 0, 2)

        self.exactCard1 = QComboBox()
        self.exactCard2 = QComboBox()
        cards = [f"{rank}{suit}" for rank in "AKQJT98765432" for suit in "shdc"]
        for selector in (self.exactCard1, self.exactCard2):
            selector.addItem(_("Any card"), None)
            for card in cards:
                selector.addItem(card, card)
        grid.addWidget(QLabel(_("Exact known cards")), 1, 0)
        exact_layout = QHBoxLayout()
        exact_layout.addWidget(self.exactCard1)
        exact_layout.addWidget(self.exactCard2)
        grid.addLayout(exact_layout, 1, 1, 1, 2)

        self.preflopFilter = QComboBox()
        for label, value in (
            (_("Any"), ""),
            (_("VPIP"), "vpip"),
            (_("Did not VPIP"), "not_vpip"),
            (_("RFI"), "rfi"),
            (_("Limp"), "limp"),
            (_("Call open"), "call_open"),
            (_("3-bet"), "three_bet"),
            (_("4-bet"), "four_bet"),
            (_("Squeeze"), "squeeze"),
            (_("Faced open"), "faced_open"),
            (_("Faced 3-bet"), "faced_three_bet"),
            (_("Went all-in"), "all_in"),
        ):
            self.preflopFilter.addItem(label, value)
        grid.addWidget(QLabel(_("Preflop")), 2, 0)
        grid.addWidget(self.preflopFilter, 2, 1, 1, 2)

        self.postflopFilter = QComboBox()
        for label, value in (
            (_("Any"), ""),
            (_("Saw flop"), "saw_flop"),
            (_("Saw turn"), "saw_turn"),
            (_("Saw river"), "saw_river"),
            (_("Bet"), "bet"),
            (_("Called"), "call"),
            (_("Raised"), "raise"),
            (_("Checked"), "check"),
            (_("Folded"), "fold"),
            (_("Continuation bet"), "cbet"),
            (_("Faced c-bet"), "faced_cbet"),
            (_("Check-raise"), "check_raise"),
            (_("Showdown"), "showdown"),
        ):
            self.postflopFilter.addItem(label, value)
        grid.addWidget(QLabel(_("Postflop")), 3, 0)
        grid.addWidget(self.postflopFilter, 3, 1, 1, 2)

        self.potMinBB = QLineEdit()
        self.potMinBB.setPlaceholderText(_("min BB"))
        self.potMaxBB = QLineEdit()
        self.potMaxBB.setPlaceholderText(_("max BB"))
        self.netMinBB = QLineEdit()
        self.netMinBB.setPlaceholderText(_("min BB"))
        self.netMaxBB = QLineEdit()
        self.netMaxBB.setPlaceholderText(_("max BB"))
        self.stackMinBB = QLineEdit()
        self.stackMinBB.setPlaceholderText(_("min BB"))
        self.stackMaxBB = QLineEdit()
        self.stackMaxBB.setPlaceholderText(_("max BB"))
        self.playersMin = QLineEdit()
        self.playersMin.setPlaceholderText(_("min"))
        self.playersMax = QLineEdit()
        self.playersMax.setPlaceholderText(_("max"))
        for widget in (
            self.potMinBB,
            self.potMaxBB,
            self.netMinBB,
            self.netMaxBB,
            self.stackMinBB,
            self.stackMaxBB,
        ):
            widget.setValidator(QDoubleValidator(-1_000_000, 1_000_000, 4, widget))
        for widget in (self.playersMin, self.playersMax):
            widget.setValidator(QIntValidator(0, 100, widget))
        for row, label, low, high in (
            (4, _("Final pot (BB)"), self.potMinBB, self.potMaxBB),
            (5, _("Net result (BB)"), self.netMinBB, self.netMaxBB),
            (6, _("Effective stack (BB)"), self.stackMinBB, self.stackMaxBB),
            (7, _("Players in hand"), self.playersMin, self.playersMax),
        ):
            bounds = QHBoxLayout()
            bounds.addWidget(low)
            bounds.addWidget(high)
            grid.addWidget(QLabel(label), row, 0)
            grid.addLayout(bounds, row, 1, 1, 2)

        self.sizingBucketFilter = QComboBox()
        self.sizingBucketFilter.addItem(_("Any sizing"), "")
        for label, value in (
            (_("Under 25% pot"), "under_25"),
            (_("25–50% pot"), "25_50"),
            (_("50–75% pot"), "50_75"),
            (_("75–100% pot"), "75_100"),
            (_("100–150% pot"), "100_150"),
            (_("Over 150% pot"), "over_150"),
        ):
            self.sizingBucketFilter.addItem(label, value)
        grid.addWidget(QLabel(_("Bet / raise sizing")), 8, 0)
        grid.addWidget(self.sizingBucketFilter, 8, 1, 1, 2)

        self.applyAdvancedFilters = QPushButton(_("Apply review filters"))
        self.applyAdvancedFilters.clicked.connect(lambda: self.loadHands(None))
        grid.addWidget(self.applyAdvancedFilters, 9, 0, 1, 3)
        return group

    def _choose_starting_hands(self) -> None:
        dialog = StartingHandPickerDialog(self._starting_hands, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._starting_hands = dialog.selected_hands()
            count = len(self._starting_hands)
            self.startingHandSummary.setText(
                _("All starting hands") if not count else _("{} classes selected").format(count)
            )

    @staticmethod
    def _optional_number(widget, cast):
        text = widget.text().strip()
        if not text:
            return None
        if cast is float:
            text = text.replace(",", ".")
        return cast(text)

    def _advanced_filter_values(self) -> dict[str, Any]:
        values = {
            "starting_hands": sorted(self._starting_hands),
            "exact_card_1": self.exactCard1.currentData(),
            "exact_card_2": self.exactCard2.currentData(),
            "preflop": self.preflopFilter.currentData(),
            "postflop": self.postflopFilter.currentData(),
            "pot_min_bb": self._optional_number(self.potMinBB, float),
            "pot_max_bb": self._optional_number(self.potMaxBB, float),
            "net_min_bb": self._optional_number(self.netMinBB, float),
            "net_max_bb": self._optional_number(self.netMaxBB, float),
            "stack_min_bb": self._optional_number(self.stackMinBB, float),
            "stack_max_bb": self._optional_number(self.stackMaxBB, float),
            "sizing_bucket": self.sizingBucketFilter.currentData(),
            "players_min": self._optional_number(self.playersMin, int),
            "players_max": self._optional_number(self.playersMax, int),
        }
        for minimum, maximum, label in (
            ("pot_min_bb", "pot_max_bb", "final pot"),
            ("net_min_bb", "net_max_bb", "net result"),
            ("stack_min_bb", "stack_max_bb", "effective stack"),
            ("players_min", "players_max", "players in hand"),
        ):
            low, high = values[minimum], values[maximum]
            if low is not None and high is not None and low > high:
                raise ValueError(_("The minimum cannot exceed the maximum for {}.").format(label))
        return values

    def _analytics_filter_warning(self, filters: dict[str, Any]) -> str:
        """Explain when selected filters depend on analytics rows that are not readable."""
        required = required_analytics_subsystems(filters)
        if not required:
            return ""
        try:
            from fpdb_3_legacy.analytics_lifecycle import subsystem_statuses

            statuses = subsystem_statuses(self.db)
        except Exception:  # noqa: BLE001 - do not silently return a misleading empty result
            log.warning("Could not verify analytics status for Hand Viewer filters", exc_info=True)
            return _(
                "The analytics status needed by these filters could not be verified. "
                "No results were queried; check the database and rebuild analytics data before retrying.",
            )

        stale = [statuses[name] for name in required if statuses[name].is_stale]
        if not stale:
            return ""
        older = [status.name for status in stale if status.recorded_version < status.code_version]
        newer = [status.name for status in stale if status.recorded_version > status.code_version]
        messages = []
        if older:
            messages.append(
                _("These filters need missing or outdated analytics data: {names}.").format(
                    names=", ".join(older),
                )
            )
            messages.append(_("Use Database → Rebuild Analytics Data, then retry the filter."))
        if newer:
            messages.append(
                _("These analytics rows were created by a newer fpdb version: {names}.").format(
                    names=", ".join(newer),
                )
            )
            messages.append(_("Upgrade fpdb before using these filters."))
        messages.append(_("No hands were queried, to avoid presenting an incomplete result as empty."))
        return "\n\n".join(messages)

    def close_owned_database(self) -> None:
        """Release the connection created for this tab."""
        self._search_timer.stop()
        with contextlib.suppress(Exception):
            if self.replayer is not None:
                self.replayer.close()
                self.replayer = None
        with contextlib.suppress(Exception):
            self.db.disconnect()

    def init_card_images(self):
        suits = ("s", "h", "d", "c")
        ranks = (14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2)

        card_images = [0] * 53
        for j in range(13):
            for i in range(4):
                loc = Card.cardFromValueSuit(ranks[j], suits[i])
                card_image = self.deck_instance.card(suits[i], ranks[j])
                card_images[loc] = card_image
        back_image = self.deck_instance.back()
        card_images[0] = back_image
        return card_images

    def loadHands(self, checkState) -> None:
        if self._page_loading:
            return
        hand_ids = self.get_hand_ids_from_date_range(
            self.filters.getDates()[0],
            self.filters.getDates()[1],
        )
        # ! print(hand_ids)
        self.reload_hands(hand_ids)

    def get_hand_ids_from_date_range(self, start, end):
        q = self.db.sql.query["handsInRangeSessionFilter"]
        q = q.replace("<datetest>", "between '" + start + "' and '" + end + "'")

        # Apply filters
        q = self.filters.replace_placeholders_with_filter_values(q)

        # Flag filters (AI / SD / RIT) appended as extra WHERE conditions.
        extra = []
        if getattr(self, "flagRunItTwice", None) and self.flagRunItTwice.isChecked():
            # RIT only: a bomb-pot double board also stores multiple boards but is
            # not "run it twice", so exclude it here.
            extra.append("h.runItTwice = 1 AND h.bombPot = 0")
        if getattr(self, "flagAllIn", None) and self.flagAllIn.isChecked():
            extra.append("hp.wentAllIn = 1")
        if getattr(self, "flagShowdown", None) and self.flagShowdown.isChecked():
            extra.append("hp.sawShowdown = 1")
        if getattr(self, "flagCashout", None) and self.flagCashout.isChecked():
            extra.append("EXISTS (SELECT 1 FROM HandsCashout hco WHERE hco.handId = h.id)")
        if getattr(self, "flagBombPot", None) and self.flagBombPot.isChecked():
            extra.append("h.bombPot > 0")
        if getattr(self, "flagDoubleBoard", None) and self.flagDoubleBoard.isChecked():
            # In FPDB a true double-board hand is a bomb pot with two stored
            # boards. A shared-flop run-it-twice also has two Boards rows, but
            # is deliberately excluded from this filter.
            extra.append("h.bombPot > 0 AND (SELECT COUNT(*) FROM Boards b WHERE b.handId = h.id) >= 2")
        splash_condition = self._splash_filter_condition()
        if splash_condition:
            extra.append(splash_condition)
        placeholder = getattr(self.db.sql, "query", {}).get("placeholder", "%s")
        try:
            advanced_values = self._advanced_filter_values() if hasattr(self, "_advanced_filter_values") else {}
        except ValueError as exc:
            QMessageBox.warning(self, _("Invalid review filter"), str(exc))
            return []
        analytics_warning = self._analytics_filter_warning(advanced_values)
        if analytics_warning:
            QMessageBox.warning(self, _("Analytics data unavailable"), analytics_warning)
            return []
        advanced, advanced_params = build_filter_clauses(advanced_values, placeholder)
        extra.extend(advanced)
        if extra:
            q = q + " AND " + " AND ".join(extra)
        q = escape_literal_percent(q, placeholder)

        # Diagnostic: log the fully-assembled query and the active filter state so
        # missing-hands issues (e.g. a category excluded by date/game/limit/position)
        # can be traced. Enable DEBUG logging for "gui_hand_viewer" to see it.
        log.debug("Load Hands SQL:\n%s", q)
        log.debug(
            "Load Hands filters | dates=%s..%s games=%s limits=%s positions=%s",
            start,
            end,
            sorted(self.filters.getGames()) if hasattr(self.filters, "getGames") else "?",
            self.filters.getLimits() if hasattr(self.filters, "getLimits") else "?",
            self.filters.getPositions() if hasattr(self.filters, "getPositions") else "?",
        )

        c = self.db.get_cursor()
        if advanced_params:
            c.execute(q, advanced_params)
        else:
            c.execute(q)
        result = [r[0] for r in c.fetchall()]
        log.info("Load Hands matched %d hand(s) for dates %s..%s", len(result), start, end)
        return result

    def _splash_filter_condition(self) -> str | None:
        """Return the SQL condition for the selected splash-pot mode."""
        mode = "all"
        selector = getattr(self, "flagSplashPot", None)
        if selector is not None and hasattr(selector, "currentData"):
            mode = selector.currentData() or "all"
        return {
            "only": "h.splashPot > 0",
            "exclude": "(h.splashPot = 0 OR h.splashPot IS NULL)",
        }.get(mode)

    def rankedhand(self, hand, game):
        ranks = {
            "0": 0,
            "2": 2,
            "3": 3,
            "4": 4,
            "5": 5,
            "6": 6,
            "7": 7,
            "8": 8,
            "9": 9,
            "T": 10,
            "J": 11,
            "Q": 12,
            "K": 13,
            "A": 14,
        }
        suits = {"x": 0, "s": 1, "c": 2, "d": 3, "h": 4}

        if game == "holdem":
            card1 = ranks[hand[0]]
            card2 = ranks[hand[3]]
            suit1 = suits[hand[1]]
            suit2 = suits[hand[4]]
            if card1 < card2:
                (card1, card2) = (card2, card1)
                (suit1, suit2) = (suit2, suit1)
            if suit1 == suit2:
                suit1 += 4
            return card1 * 14 * 14 + card2 * 14 + suit1
        return 0

    def reload_hands(self, handids) -> None:
        if self._page_loading:
            return
        self.hands = OrderedDict()
        self._loaded_handids = list(dict.fromkeys(handids))
        self.all_handids = list(self._loaded_handids)
        self._hand_numbers = None
        self._active_search = ""
        self._rendered_page = None
        self._search_timer.stop()
        self.handSearch.blockSignals(True)
        self.handSearch.clear()
        self.handSearch.blockSignals(False)
        self._set_hand_status("")
        self._sort_keys = {}
        self.page = 0
        self.model.removeRows(0, self.model.rowCount())
        if len(self.all_handids) == 0:
            self._update_pager()
            return
        self._sort_hands(self._sort_column, self._sort_order)

    def _sort_hands(self, column, order) -> bool:
        if column < 0 or self._page_loading:
            return False
        if not self.all_handids:
            self._sort_column, self._sort_order = column, order
            return True
        previous = (self._sort_column, self._sort_order, self.page, list(self.all_handids))
        from fpdb_3_legacy.hand_table_sort import load_sort_keys

        name = next(key for key, index in self.colnum.items() if index == column)
        if name not in self._sort_keys:
            heroes = {site: self.config.get_hero_aliases(site) or [hero]
                      for site, hero in self.filters.getHeroes().items()}
            try:
                keys = load_sort_keys(self.db, self._loaded_handids, name, heroes)
            except Exception as error:  # noqa: BLE001 - DB-driver errors must leave the current table usable.
                self._set_hand_status(_("Could not sort hands: ") + str(error))
                self._restore_sort_indicator()
                return False
            if keys is None:
                keys = self._reconstructed_sort_keys(column)
                if keys is None:
                    self._restore_sort_indicator()
                    return False
            self._sort_keys[name] = keys
        self._sort_column, self._sort_order = column, order
        keys = self._sort_keys[name]
        self.all_handids.sort(key=lambda handid: (keys.get(handid, ""), handid),
                              reverse=order == Qt.SortOrder.DescendingOrder)
        self.page = 0
        if not self.render_page():
            self._sort_column, self._sort_order, self.page, self.all_handids = previous
            self._restore_sort_indicator()
            self._update_pager()
            return False
        return True

    def _restore_sort_indicator(self) -> None:
        header = self.view.horizontalHeader()
        header.blockSignals(True)
        header.setSortIndicator(self._sort_column, self._sort_order)
        header.blockSignals(False)

    def _reconstructed_sort_keys(self, column):
        keys = {}
        progress = QProgressDialog(_("Sorting hands"), _("Cancel"), 0, len(self._loaded_handids), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(250)
        self._page_loading = True
        try:
            for index, handid in enumerate(self._loaded_handids):
                if progress.wasCanceled():
                    self._set_hand_status(_("Sorting canceled. Previous order kept."))
                    return None
                try:
                    hand = self.hands.get(handid) or self.importhand(handid)
                    items = self._hand_row_items(handid, hand, decorate=False)
                    keys[handid] = items[column].text() if items else ""
                except Exception:  # noqa: BLE001 - a damaged hand must not abort the whole sort.
                    log.exception("Could not build sort value for hand %s", handid)
                    keys[handid] = ""
                progress.setValue(index + 1)
                if index % 25 == 0:
                    QCoreApplication.processEvents()
            return keys
        finally:
            self._page_loading = False
            progress.close()
            progress.deleteLater()

    def _apply_id_search(self) -> None:
        if self._page_loading:
            self._search_timer.start()
            return
        text = self.handSearch.text().lstrip("#")
        if text and self._hand_numbers is None:
            from fpdb_3_legacy.hand_table_sort import load_hand_numbers

            try:
                self._hand_numbers = load_hand_numbers(self.db, self._loaded_handids)
            except Exception as error:  # noqa: BLE001 - retain the current table on a search query failure.
                self._set_hand_status(_("Could not search hands: ") + str(error))
                self._restore_search_text()
                return
        previous, page = list(self.all_handids), self.page
        self.all_handids = [handid for handid in self._loaded_handids
                            if not text or text in str(handid) or text in (self._hand_numbers or {}).get(handid, "")]
        self.page = 0
        if self.all_handids:
            if not self._sort_hands(self._sort_column, self._sort_order):
                self.all_handids, self.page = previous, page
                self._restore_search_text()
                self._update_pager()
                return
        else:
            self.model.removeRows(0, self.model.rowCount())
            self._rendered_page = None
            self._update_pager()
            self._set_hand_status(_("No hand IDs match this search."))
        self._active_search = text

    def _restore_search_text(self) -> None:
        self._search_timer.stop()
        self.handSearch.blockSignals(True)
        self.handSearch.setText(self._active_search)
        self.handSearch.blockSignals(False)

    def _set_hand_status(self, text: str) -> None:
        self.handStatusLabel.setText(text)
        self.handStatusLabel.setVisible(bool(text))

    def page_count(self) -> int:
        if not self.all_handids:
            return 1
        return (len(self.all_handids) + self.page_size - 1) // self.page_size

    def render_page(self) -> bool:
        """Reconstruct and display only the current page of hands."""
        if self._page_loading:
            return False
        self._page_loading = True
        self.loadButton.setEnabled(False)
        self.handSearch.setEnabled(False)
        self.pageSizeCombo.setEnabled(False)
        self.view.horizontalHeader().setEnabled(False)
        self.replayButton.setEnabled(False)
        self._update_pager()
        start = self.page * self.page_size
        page_ids = self.all_handids[start : start + self.page_size]
        progress = QProgressDialog(_("Loading hands"), _("Cancel"), 0, len(page_ids), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(250)
        progress.setValue(0)
        previous_cache = self.hands.copy()
        rows, skipped = [], 0
        selected = self._selected_hand_id()
        try:
            for idx, handid in enumerate(page_ids):
                if progress.wasCanceled():
                    self.hands = previous_cache
                    if self._rendered_page is not None:
                        self.page = self._rendered_page
                    self._set_hand_status(_("Loading canceled. Previous page kept.") if self.model.rowCount()
                                          else _("Loading canceled."))
                    return False
                try:
                    if handid not in self.hands:
                        self.hands[handid] = self.importhand(handid)
                    self.hands.move_to_end(handid)
                    items = self._hand_row_items(handid, self.hands[handid])
                    if items:
                        rows.append(items)
                    else:
                        skipped += 1
                except Exception as e:  # noqa: BLE001 - skip a bad hand, keep loading the rest.
                    log.exception(f"Skipping hand {handid}: {e}")
                    self.hands.pop(handid, None)
                    skipped += 1
                progress.setValue(idx + 1)
                if idx % 25 == 0:
                    QCoreApplication.processEvents()
            self.model.removeRows(0, self.model.rowCount())
            for items in rows:
                self.model.appendRow(items)
            self._rendered_page = self.page
            self._trim_hand_cache()
            self.columnControls.resize_to_contents()
            self._restore_hand_selection(selected)
            if skipped:
                self._set_hand_status(_("{0} hands could not be loaded on this page.").format(skipped))
            elif self.handSearch.text().lstrip("#"):
                self._set_hand_status(_("{0} matching hands from {1} loaded hands.").format(
                    len(self.all_handids), len(self._loaded_handids)))
            else:
                self._set_hand_status("")
            return True
        finally:
            progress.close()
            progress.deleteLater()
            self._page_loading = False
            self.loadButton.setEnabled(True)
            self.handSearch.setEnabled(True)
            self.pageSizeCombo.setEnabled(True)
            self.view.horizontalHeader().setEnabled(True)
            self.replayButton.setEnabled(self.view.currentIndex().isValid())
            self._update_pager()

    def _trim_hand_cache(self) -> None:
        limit = max(300, self.page_size * 3)
        while len(self.hands) > limit:
            self.hands.popitem(last=False)

    def _selected_hand_id(self):
        current = self.view.currentIndex()
        return current.siblingAtColumn(self.colnum['HandId']).data() if current.isValid() else None

    def _restore_hand_selection(self, handid) -> None:
        header = self.view.horizontalHeader()
        column = next((header.logicalIndex(visual) for visual in range(header.count())
                       if not self.view.isColumnHidden(header.logicalIndex(visual))), 0)
        chosen = self.filterModel.index(0, column)
        for row in range(self.model.rowCount()):
            if self.model.item(row, self.colnum['HandId']).text() == str(handid):
                chosen = self.filterModel.mapFromSource(self.model.index(row, column))
                break
        if chosen.isValid():
            self.view.setCurrentIndex(chosen)

    def refresh_theme(self, colors=None, theme_colors=None) -> None:
        """Redraw cached card icons and financial colours after a palette change."""
        if not getattr(self, "hands", None):
            return
        current = self.view.currentIndex()
        selected = current.siblingAtColumn(self.colnum["HandId"]).data() if current.isValid() else None
        self.render_page()
        if selected is not None:
            for row in range(self.model.rowCount()):
                if self.model.item(row, self.colnum["HandId"]).text() == str(selected):
                    self.view.setCurrentIndex(self.filterModel.mapFromSource(self.model.index(row, 0)))
                    break

    def _update_pager(self) -> None:
        self._update_hand_empty_state()
        self._update_hand_filter_chips()
        self._update_selected_hand()
        primary = not bool(self._loaded_handids)
        if self.loadButton.property("primaryAction") != primary:
            self.loadButton.setProperty("primaryAction", primary)
            self.loadButton.style().unpolish(self.loadButton)
            self.loadButton.style().polish(self.loadButton)
        total = len(self.all_handids)
        pages = self.page_count()
        self.pageLabel.setText(_("of {0} pages · {1} shown / {2} hands").format(pages, self.model.rowCount(), total))
        self.prevPageButton.setEnabled(not self._page_loading and self.page > 0)
        self.nextPageButton.setEnabled(not self._page_loading and self.page < pages - 1)
        self.pageSpin.blockSignals(True)
        self.pageSpin.setRange(1, pages)
        self.pageSpin.setValue(self.page + 1)
        self.pageSpin.blockSignals(False)
        self.pageSpin.setEnabled(not self._page_loading and bool(total))

    def _jump_to_page(self, value) -> None:
        if not self._page_loading and value - 1 != self.page:
            self.page = max(0, min(value - 1, self.page_count() - 1))
            self.render_page()

    def _change_page_size(self) -> None:
        if self._page_loading:
            return
        previous_size, previous_page = self.page_size, self.page
        selected = self._selected_hand_id()
        anchor = next((index for index, handid in enumerate(self.all_handids) if str(handid) == str(selected)),
                      self.page * self.page_size)
        self.page_size = self.pageSizeCombo.currentData()
        self.page = min(anchor // self.page_size, self.page_count() - 1)
        if self.render_page():
            self.columnControls.settings.setValue("cash-hands/page-size", self.page_size)
        else:
            self.page_size, self.page = previous_size, previous_page
            self.pageSizeCombo.blockSignals(True)
            self.pageSizeCombo.setCurrentIndex(self.pageSizeCombo.findData(self.page_size))
            self.pageSizeCombo.blockSignals(False)
            self._update_pager()

    def prev_page(self) -> None:
        if not self._page_loading and self.page > 0:
            self.page -= 1
            self.render_page()

    def next_page(self) -> None:
        if not self._page_loading and self.page < self.page_count() - 1:
            self.page += 1
            self.render_page()

    def addHandRow(self, handid, hand) -> None:
        items = self._hand_row_items(handid, hand)
        if items:
            self.model.appendRow(items)

    def _hand_row_items(self, handid, hand, *, decorate=True):
        hero = hand.hero or self.filters.get_hero_for_site(hand.sitename, hand)
        if not hero:
            log.warning(f"Hero not found for site: {hand.sitename}")
            return

        won = hand.collectees.get(hero, 0)
        if not hasattr(hand, "net_collected") or not hand.net_collected:
            hand.calculate_net_collected()
        bet = 0
        if hero in hand.pot.committed:
            # Pot.removeMoney already removes uncalled bets from committed.
            bet = hand.pot.committed[hero]
        net = hand.net_collected.get(hero, 0)
        pos = hand.get_player_position(hero)
        nbplayers = len(hand.players)
        totalpot = hand.totalpot
        rake = hand.rake if hand.rake is not None else Decimal("0.00")
        sitehandid = hand.handid
        currency = str(hand.gametype.get("currency", "USD"))
        splash = getattr(hand, "splashPot", 0) or 0
        splash_won = (getattr(hand, "splashWinnings", {}) or {}).get(hero, 0) or 0
        base = hand.gametype["base"]
        category = hand.gametype.get("category", "")

        # Hero cards, board run(s) and per-street action depend on the game base.
        board_runs = []
        if base == "hold":
            holestr = hand.join_holecards(hero)
            single = (
                list(hand.board.get("FLOP", [])) + list(hand.board.get("TURN", [])) + list(hand.board.get("RIVER", []))
            )
            runs = []
            for run in (1, 2, 3):
                rc = (
                    list(hand.board.get(f"FLOP{run}", []))
                    + list(hand.board.get(f"TURN{run}", []))
                    + list(hand.board.get(f"RIVER{run}", []))
                )
                if rc:
                    runs.append(rc)
            board_runs = runs if runs else ([single] if single else [])
            # The street the first decision is taken on, which is not preflop
            # in every game: All-in or Fold deals the flop first and has no
            # preflop at all, so its whole first round belongs in this column.
            first_street = hand.actionStreets[1] if len(hand.actionStreets) > 1 else "PREFLOP"
            pre_actions = hand.get_actions_short(hero, first_street)
            later_streets = [s for s in ("FLOP", "TURN", "RIVER") if s != first_street]
            post_actions = "" if "F" in pre_actions else hand.get_actions_short_streets(hero, *later_streets)
        elif base == "stud":
            holestr = " ".join(hand.holecards["THIRD"][hero][0]) + " " + " ".join(hand.holecards["THIRD"][hero][1])
            later = []
            for s in ("FOURTH", "FIFTH", "SIXTH", "SEVENTH"):
                later.extend(hand.holecards[s][hero][0])
            board_runs = [later] if later else []
            pre_actions = hand.get_actions_short(hero, "THIRD")
            post_actions = (
                ""
                if "F" in pre_actions
                else hand.get_actions_short_streets(hero, "FOURTH", "FIFTH", "SIXTH", "SEVENTH")
            )
        else:  # draw
            holestr = hand.join_holecards(hero, street="DEAL")
            pre_actions = hand.get_actions_short(hero, "DEAL")
            post_actions = ""

        combo = (getattr(hand, "showdownStrings", {}) or {}).get(hero, "") or ""

        values = {
            "Date": self._format_datetime(hand),
            "Flags": self._hand_flags(hand),
            "Stakes": hand.getStakesAsString(),
            "Players": str(nbplayers),
            "Pos": self._format_position(pos),
            "Street0": holestr,
            "Action0": pre_actions,
            "Street1-4": "",
            "Action1-4": post_actions,
            "Combo": combo,
            "Won": format_number(won),
            "Bet": format_number(bet),
            "Net": format_number(net),
            "Game": self._format_game(hand),
            "HandId": str(handid),
            "Total Pot": format_number(totalpot),
            "Rake": format_number(rake),
            "SiteHandNo": str(sitehandid),
            "Splash": self._format_splash(splash, splash_won, currency),
        }
        money_values = {"Won": won, "Bet": bet, "Net": net, "Total Pot": totalpot, "Rake": rake}

        ordered = sorted(self.colnum.items(), key=lambda kv: kv[1])
        modelrow = [QStandardItem(str(values.get(name, ""))) for name, _idx in ordered]

        try:
            net_f = float(net)
        except (TypeError, ValueError):
            net_f = 0.0
        colors = current_palette()
        win_color, lose_color, neutral = (QColor(colors[role]) for role in ("success", "danger", "text"))

        for name, idx in ordered:
            item = modelrow[idx]
            item.setEditable(False)
            if name == "Street0":
                if decorate:
                    item.setData(table_card_icon(self.render_cards(holestr)), Qt.ItemDataRole.DecorationRole)
                item.setData("", Qt.ItemDataRole.DisplayRole)
                item.setData(holestr, Qt.ItemDataRole.UserRole + 1)
            elif name == "Street1-4":
                flat = " ".join(c for run in board_runs for c in run)
                if decorate:
                    item.setData(table_card_icon(self.render_boards(board_runs)), Qt.ItemDataRole.DecorationRole)
                item.setData("", Qt.ItemDataRole.DisplayRole)
                item.setData(flat, Qt.ItemDataRole.UserRole + 1)
            elif name in ("Bet", "Net", "Won", "Total Pot", "Rake"):
                try:
                    item.setData(float(money_values[name]), Qt.ItemDataRole.UserRole)
                except (TypeError, ValueError):
                    pass
            elif name == "Splash":
                try:
                    item.setData(float(Decimal(str(splash)) / 100), Qt.ItemDataRole.UserRole)
                except (TypeError, ValueError, ArithmeticError):
                    pass
            if name in ("Won", "Net"):
                try:
                    v = float(money_values[name])
                    currency = str(hand.gametype.get("currency", "USD"))
                    item.setData(format_currency(money_values[name], currency), Qt.ItemDataRole.DisplayRole)
                    item.setForeground(QBrush(win_color if v > 0 else lose_color if v < 0 else neutral))
                except (TypeError, ValueError):
                    pass
            elif name == "Flags":
                item.setForeground(QBrush(QColor(colors["warning"])))
            elif name == "Game":
                # Keep the raw category for the card filter / sorting.
                item.setData(category, Qt.ItemDataRole.UserRole)

        # Subtle row tint by result.
        if net_f > 0:
            tint = QColor(colors["result_positive_bg"])
        elif net_f < 0:
            tint = QColor(colors["result_negative_bg"])
        else:
            tint = None
        tip = self._hand_tooltip(hand, hero, won, net)
        for item in modelrow:
            if tint is not None:
                item.setBackground(QBrush(tint))
            item.setToolTip(tip)

        return modelrow

    _GAME_NAMES = {
        "holdem": "HE",
        "6_holdem": "6HE",
        "omahahi": "O",
        "omahahilo": "O8",
        "5_omahahi": "5O",
        "5_omaha8": "5O8",
        "6_omahahi": "6O",
        "cour_hi": "C",
        "cour_hilo": "C8",
        "razz": "Razz",
        "studhi": "Stud",
        "studhilo": "Stud8",
        "27_1draw": "27SD",
        "27_3draw": "27TD",
        "a5_3draw": "A5TD",
        "badugi": "Badugi",
        "fusion": "Fusion",
    }
    _LIMIT_NAMES = {"nl": "NL", "pl": "PL", "fl": "FL", "cn": "CN", "cp": "CP"}
    _POSITION_NAMES = {
        "S": "SB",
        "B": "BB",
        "0": "BTN",
        "1": "CO",
        "2": "HJ",
        "3": "LJ",
        "4": "MP",
        "5": "MP",
        "6": "UTG",
        "7": "UTG",
        "8": "Other",
        "9": "Unknown",
    }

    def _format_game(self, hand) -> str:
        cat = hand.gametype.get("category", "")
        lim = hand.gametype.get("limitType", "")
        return f"{self._LIMIT_NAMES.get(lim, str(lim).upper())}{self._GAME_NAMES.get(cat, cat)}"

    def _format_position(self, pos) -> str:
        return self._POSITION_NAMES.get(str(pos), str(pos))

    @staticmethod
    def _format_splash(splash, splash_won, currency: str) -> str:
        """Format the room drop and, when present, the hero's collected share."""
        try:
            drop_text = format_currency(Decimal(str(splash)) / 100, currency)
            if splash_won:
                won_text = format_currency(splash_won, currency)
                return f"{drop_text} ({won_text} won)"
            return drop_text
        except (TypeError, ValueError, ArithmeticError):
            return ""

    def _format_datetime(self, hand) -> str:
        st = getattr(hand, "startTime", None)
        if not st:
            return ""
        try:
            return format_datetime(st)
        except (AttributeError, TypeError, ValueError):
            return str(st)

    def _hand_flags(self, hand) -> str:
        flags: list[str] = []
        try:
            rit = int(hand.runItTimes)
        except (TypeError, ValueError):
            rit = 0
        bomb_pot = bool(getattr(hand, "bombPot", 0))
        if rit >= 2 and bomb_pot:
            flags.extend(("BOMB", "2xB"))
        elif rit >= 2:
            flags.append(f"RIT×{rit}")
        elif bomb_pot:
            flags.append("BOMB")
        cashed = bool(getattr(hand, "cashedOut", False))
        allin = False
        for acts in hand.actions.values():
            for a in acts:
                if len(a) > 1 and a[1] == "cashout":
                    cashed = True
                if a and isinstance(a[-1], bool) and a[-1]:
                    allin = True
        if cashed:
            flags.append("CO$")
        if allin:
            flags.append("AI")
        if getattr(hand, "shown", None):
            flags.append("SD")
        return " ".join(flags)

    def render_boards(self, runs):
        """Render one or more run boards stacked vertically (run-it-twice/three)."""
        return render_table_cards(runs)

    def _hand_tooltip(self, hand, hero, won, net) -> str:
        lines = [
            f"{hand.sitename} #{hand.handid}",
            f"{self._format_game(hand)} {hand.getStakesAsString()}",
        ]
        combo = (getattr(hand, "showdownStrings", {}) or {}).get(hero)
        if combo:
            lines.append(f"Hero: {combo}")
        currency = str(hand.gametype.get("currency", "USD"))
        try:
            lines.append(f"Won {format_currency(won, currency)}  ·  Net {format_currency(net, currency)}")
        except (TypeError, ValueError):
            pass
        return "\n".join(lines)

    def copyHandToClipboard(self, checkState, hand) -> None:
        handText = StringIO()
        hand.writeHand(handText)
        QApplication.clipboard().setText(handText.getvalue())

    def contextMenu(self, event) -> None:
        index = self.view.currentIndex()
        if index.row() < 0:
            return
        hand_id = int(index.sibling(index.row(), self.colnum["HandId"]).data())
        hand = self.hands[hand_id]
        m = QMenu()
        copyAction = m.addAction(_("Copy hand history"))
        if copyAction is not None:
            copyAction.triggered.connect(partial(self.copyHandToClipboard, hand=hand))
        m.addSeparator()
        add_share_actions(m, hand, self)
        m.addSeparator()
        add_review_action(m, hand, self, fpdb_hand_id=hand_id, config=self.config)
        m.move(event.globalPos())
        m.exec()

    def filter_cards_cb(self, card) -> None:
        if hasattr(self, "hands"):
            self.filterModel.invalidateFilter()

    def is_row_in_card_filter(self, rownum):
        """Returns true if the cards of the given row are in the card filter."""
        # Does work but all cards that should NOT be displayed have to be clicked.
        card_filter = self.filters.getCards()

        # if the filter is not active, show all hands
        if not card_filter:
            return True

        hcs = self.model.data(
            self.model.index(rownum, self.colnum["Street0"]),
            Qt.ItemDataRole.UserRole + 1,
        ).split(" ")

        if "0x" in hcs:  # if cards are unknown return True
            return True

        gt = self.model.data(self.model.index(rownum, self.colnum["Game"]), Qt.ItemDataRole.UserRole)

        if gt not in ("holdem", "omahahi", "omahahilo"):
            return True

        # Holdem: Compare the real start cards to the selected filter (ie. AhKh = AKs)
        value1 = Card.card_map[hcs[0][0]]
        value2 = Card.card_map[hcs[1][0]]
        idx = Card.twoStartCards(value1, hcs[0][1], value2, hcs[1][1])
        abbr = Card.twoStartCardString(idx)

        # if the filter is active, only show hands that are in it.
        return card_filter.get(abbr, False)

    def row_activated(self, index) -> None:
        try:
            hand_id = int(index.sibling(index.row(), self.colnum["HandId"]).data())
            handlist = list(self.all_handids)
            hand_index = handlist.index(hand_id)

            if getattr(self, "replayer", None) is not None and self.replayer.isVisible():
                self.replayer.handlist = handlist
                self.replayer.play_hand(hand_index)
                self.replayer.raise_()
                self.replayer.activateWindow()
                return

            self.replayer = GuiReplayer.GuiReplayer(
                self.config,
                self.sql,
                self.main_window,
                handlist,
                db=self.db,
            )
            self.replayer.play_hand(hand_index)
            self.replayer.raise_()
            self.replayer.activateWindow()
        except Exception as exc:
            log.exception("Unable to open hand replayer")
            QMessageBox.critical(self, "FPDB Replayer", f"Unable to open hand replayer:\n{exc}")

    def importhand(self, handid=1):
        h = Hand.hand_factory(handid, self.config, self.db)

        # Safely get the hero for this hand's sitename
        h.hero = self.filters.get_hero_for_site(h.sitename, h)
        if h.hero is None:
            log.warning(f"No hero found for site {h.sitename}")
        return h

    def render_cards(self, cardstring):
        return render_table_cards([card_tokens(cardstring)])


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    # Launch the hand viewer GUI like the original
    config = Configuration.Config()

    settings = {}

    settings.update(config.get_db_parameters())
    settings.update(config.get_import_parameters())
    settings.update(config.get_default_paths())

    from PySide6.QtWidgets import QMainWindow

    app = QApplication([])
    sql = SQL.Sql(db_server=settings["db-server"])
    main_window = QMainWindow()
    i = GuiHandViewer(config, sql, main_window)
    main_window.setCentralWidget(i)
    main_window.show()
    main_window.resize(1400, 800)
    app.exec()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
