"""Copy the displayed table order and visible columns as spreadsheet-friendly TSV."""

import csv
from io import StringIO

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication


def table_text(view, *, selected=True, headers=False) -> str:
    model = view.model()
    if model is None:
        return ""
    indexes = view.selectionModel().selectedIndexes() if selected else []
    cells = {(index.row(), index.column()) for index in indexes}
    if selected and not cells:
        return ""
    rows = sorted({row for row, _column in cells}) if selected else range(model.rowCount())
    header = view.horizontalHeader()
    columns = [header.logicalIndex(visual) for visual in range(header.count())]
    columns = [column for column in columns if not view.isColumnHidden(column)
               and (not selected or any(col == column for _row, col in cells))]
    output = StringIO(newline="")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    if headers:
        writer.writerow([model.headerData(column, Qt.Orientation.Horizontal) for column in columns])
    for row in rows:
        if view.isRowHidden(row):
            continue
        values = []
        for column in columns:
            index = model.index(row, column)
            value = index.data(Qt.ItemDataRole.DisplayRole)
            if value in (None, "") and index.data(Qt.ItemDataRole.DecorationRole) is not None:
                value = index.data(Qt.ItemDataRole.UserRole + 1)
            values.append(("" if value is None else str(value)) if not selected or (row, column) in cells else "")
        writer.writerow(values)
    return output.getvalue()


def copy_table(view, *, selected=True, headers=False) -> None:
    text = table_text(view, selected=selected, headers=headers)
    if text:
        QApplication.clipboard().setText(text)


class TableCopyFilter(QObject):
    def eventFilter(self, view, event):
        if event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress) and event.matches(QKeySequence.StandardKey.Copy):
            if event.type() == QEvent.Type.KeyPress:
                copy_table(view)
            event.accept()
            return True
        return False


def install_table_copy(view) -> None:
    if hasattr(view, "_fpdb_copy_filter"):
        return
    event_filter = TableCopyFilter(view)
    view.installEventFilter(event_filter)
    view._fpdb_copy_filter = event_filter
