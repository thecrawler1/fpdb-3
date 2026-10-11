"""Clipboard and layout persistence on real sorted/hidden Qt tables."""

import csv
from io import StringIO

import pytest
from PySide6.QtCore import QSettings, QSortFilterProxyModel, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QLineEdit, QTableView

from fpdb_3_legacy.table_cards import render_table_cards, table_card_icon
from fpdb_3_legacy.table_clipboard import copy_table, table_text
from fpdb_3_legacy.table_columns import install_column_controls

pytestmark = pytest.mark.qt


def review_table(qtbot, settings):
    view = QTableView()
    qtbot.addWidget(view)
    source = QStandardItemModel(view)
    source.setHorizontalHeaderLabels(["Date", "Hands", "Net", "HandId"])
    for date, cards, net, handid in (("2026-10-01", "Ah Ks", 0, "42"), ("2026-10-02", "Qh Jc", 12.5, "43")):
        hand = QStandardItem("")
        hand.setData(table_card_icon(render_table_cards([cards])), Qt.ItemDataRole.DecorationRole)
        hand.setData(cards, Qt.ItemDataRole.UserRole + 1)
        amount = QStandardItem()
        amount.setData(net, Qt.ItemDataRole.DisplayRole)
        source.appendRow([QStandardItem(date), hand, amount, QStandardItem(handid)])
    proxy = QSortFilterProxyModel(view)
    proxy.setSourceModel(source)
    view.setModel(proxy)
    view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    controls = install_column_controls(view, "review", essential=("Date", "Hands", "Net"), settings=settings)
    return view, controls, source, proxy


def test_copy_respects_sort_visual_order_hidden_ids_and_numeric_zero(qapp, qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "copy.ini"), QSettings.Format.IniFormat)
    view, _controls, _source, proxy = review_table(qtbot, settings)
    proxy.sort(0, Qt.SortOrder.DescendingOrder)
    view.horizontalHeader().moveSection(1, 0)
    view.show()
    view.setFocus()
    view.selectRow(0)
    qapp.clipboard().setText("sentinel")
    qtbot.keyClick(view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert qapp.clipboard().text() == "Qh Jc\t2026-10-02\t12.5\n"
    copy_table(view, selected=False, headers=True)
    rows = list(csv.reader(StringIO(qapp.clipboard().text()), delimiter="\t"))
    assert rows == [["Hands", "Date", "Net"], ["Qh Jc", "2026-10-02", "12.5"], ["Ah Ks", "2026-10-01", "0"]]
    view.clearSelection()
    assert table_text(view) == ""


def test_copy_inside_a_cell_editor_keeps_native_text_selection(qapp, qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "editor.ini"), QSettings.Format.IniFormat)
    view, _controls, _source, proxy = review_table(qtbot, settings)
    view.show()
    view.edit(proxy.index(0, 0))
    editor = view.findChild(QLineEdit)
    assert editor is not None
    editor.setSelection(0, 4)
    qtbot.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert qapp.clipboard().text() == "2026"


def test_column_width_and_order_survive_auto_size_reload_and_new_view(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    view, controls, source, _proxy = review_table(qtbot, settings)
    header = view.horizontalHeader()
    header.resizeSection(1, 222)
    header.moveSection(1, 0)
    controls.resize_to_contents()
    assert header.sectionSize(1) == 222
    settings.sync()
    second, restored, _source, _proxy = review_table(qtbot, settings)
    assert second.horizontalHeader().logicalIndex(0) == 1
    assert second.columnWidth(1) == 222
    source.clear()
    source.setHorizontalHeaderLabels(["Date", "Hands", "Net", "HandId"])
    assert header.logicalIndex(0) == 1 and header.sectionSize(1) == 222
    restored.reset()
    assert second.horizontalHeader().logicalIndex(0) == 0
    assert settings.value("review/widths", None) is None
