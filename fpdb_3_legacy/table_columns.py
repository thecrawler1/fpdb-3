"""Progressive disclosure for tables, with persistent visibility and density."""

import contextlib
from typing import Any

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import QMenu

from fpdb_3_legacy.i18n import gettext as _

TECHNICAL_COLUMNS = {"handid", "sitehandid", "sitehandno", "gametypeid", "playerid", "recordid", "flags"}


def _namespace(view) -> str:
    if view.objectName():
        return view.objectName()
    parent = view.parent()
    while parent is not None:
        name = parent.__class__.__name__
        if not name.startswith("Q"):
            return f"{name}/{view.__class__.__name__}"
        parent = parent.parent()
    return view.__class__.__name__


class ColumnControls(QObject):
    visibility_changed = Signal(int, bool)

    def __init__(self, view, namespace, *, essential=None, keys=None, settings=None):
        super().__init__(view)
        self.view = view
        self.namespace = namespace
        self.essential = set(essential) if essential is not None else None
        self.keys = keys or {}
        self.settings = settings or QSettings("fpdb", "table-columns")
        self.model: Any = None
        header = view.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._open_menu)
        self.bind_model()

    def bind_model(self) -> None:
        model = self.view.model()
        if model is self.model:
            return
        if self.model is not None:
            for signal in (self.model.modelReset, self.model.columnsInserted, self.model.headerDataChanged):
                with contextlib.suppress(RuntimeError, TypeError):
                    signal.disconnect(self.apply)
        self.model = model
        if model is not None:
            model.modelReset.connect(self.apply)
            model.columnsInserted.connect(self.apply)
            model.headerDataChanged.connect(self.apply)
        self.apply()

    def key(self, column) -> str:
        return self.keys.get(column) or str(self.model.headerData(column, Qt.Orientation.Horizontal) or f"Column {column + 1}")

    def apply(self, *_args) -> None:
        if self.model is None:
            return
        saved: Any = self.settings.value(f"{self.namespace}/hidden", None)
        if isinstance(saved, str):
            saved = [saved]
        for column in range(self.model.columnCount()):
            key = self.key(column)
            if saved is not None:
                hidden = key in saved
            elif self.essential is not None:
                hidden = key not in self.essential
            else:
                normalized = key.lower().replace(" ", "").replace("_", "")
                hidden = self.view.isColumnHidden(column) or normalized in TECHNICAL_COLUMNS
            self.view.setColumnHidden(column, hidden)
            self.visibility_changed.emit(column, not hidden)
        if self.model.columnCount() and all(self.view.isColumnHidden(i) for i in range(self.model.columnCount())):
            self.view.setColumnHidden(0, False)
            self.visibility_changed.emit(0, True)
        density = self.settings.value(f"{self.namespace}/row-height", 40, type=int)
        self.view.verticalHeader().setDefaultSectionSize(density)

    def save(self) -> None:
        hidden = [self.key(i) for i in range(self.model.columnCount()) if self.view.isColumnHidden(i)]
        self.settings.setValue(f"{self.namespace}/hidden", hidden)

    def set_visible(self, column: int, visible: bool) -> None:
        if not visible and sum(not self.view.isColumnHidden(i) for i in range(self.model.columnCount())) <= 1:
            return
        self.view.setColumnHidden(column, not visible)
        self.visibility_changed.emit(column, visible)
        self.save()

    def reset(self) -> None:
        self.settings.remove(f"{self.namespace}/hidden")
        for column in range(self.model.columnCount()):
            self.view.setColumnHidden(column, False)
        self.apply()

    def show_all(self) -> None:
        for column in range(self.model.columnCount()):
            self.view.setColumnHidden(column, False)
            self.visibility_changed.emit(column, True)
        self.save()

    def set_density(self, height: int) -> None:
        self.settings.setValue(f"{self.namespace}/row-height", height)
        self.view.verticalHeader().setDefaultSectionSize(height)

    def populate_menu(self, menu) -> None:
        menu.clear()
        if self.model is None:
            return
        for column in range(self.model.columnCount()):
            label = str(self.model.headerData(column, Qt.Orientation.Horizontal) or self.key(column))
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(not self.view.isColumnHidden(column))
            action.setData(column)
            action.triggered.connect(lambda checked, i=column: self.set_visible(i, checked))
        menu.addSeparator()
        menu.addAction(_("Show all columns"), self.show_all)
        menu.addAction(_("Reset columns"), self.reset)
        menu.addSeparator()
        menu.addAction(_("Compact rows"), lambda: self.set_density(40))
        menu.addAction(_("Comfortable rows"), lambda: self.set_density(50))

    def menu(self) -> QMenu:
        menu = QMenu(self.view)
        menu.aboutToShow.connect(lambda: self.populate_menu(menu))
        self.populate_menu(menu)
        return menu

    def _open_menu(self, point) -> None:
        menu = self.menu()
        menu.exec(self.view.horizontalHeader().mapToGlobal(point))
        menu.deleteLater()


def install_column_controls(view, namespace=None, *, essential=None, keys=None, settings=None) -> ColumnControls:
    controller = getattr(view, "_fpdb_column_controls", None)
    if controller is None:
        controller = ColumnControls(view, namespace or _namespace(view), essential=essential, keys=keys, settings=settings)
        view._fpdb_column_controls = controller
    else:
        explicit = namespace is not None or essential is not None or keys is not None
        if namespace is not None:
            controller.namespace = namespace
        if essential is not None:
            controller.essential = set(essential)
        if keys is not None:
            controller.keys = keys
        controller.bind_model()
        if explicit:
            controller.apply()
    return controller
