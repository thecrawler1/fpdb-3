"""Load a data page on first access, then invalidate it after imported hands."""

from PySide6.QtCore import QEvent, QObject, QTimer
from shiboken6 import isValid


class AutomaticLoading(QObject):
    def __init__(self, page, callback):
        super().__init__(page)
        self.page = page
        self.callback = callback
        self.dirty = True
        self.pending = False
        page.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and self.dirty:
            self.schedule()
        return False

    def schedule(self):
        if self.pending:
            return
        self.pending = True
        QTimer.singleShot(0, self.load)

    def load(self):
        self.pending = False
        if not isValid(self.page) or not self.page.isVisible() or not self.dirty:
            return
        self.dirty = False
        self.page.setProperty("fpdb_auto_loading", True)
        try:
            self.callback()
        finally:
            self.page.setProperty("fpdb_auto_loading", False)

    def invalidate(self):
        if not isValid(self.page):
            return
        self.dirty = True
        if self.page.isVisible():
            self.schedule()


def install_automatic_loading(page, callback):
    page._fpdb_auto_loader = AutomaticLoading(page, callback)
