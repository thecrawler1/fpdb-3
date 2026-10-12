"""Isolate Qt object lifetimes and the user's table-layout preferences."""

import gc

import pytest
from PySide6.QtCore import QSettings


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_teardown(item):
    yield
    if item.get_closest_marker("qt"):
        # pytest-qt deletes widgets but leaves cyclic Python/graphics wrappers.
        # Collect them on the GUI thread at the test boundary, not in a later
        # data worker when a large allocation happens to trigger cyclic GC.
        gc.collect()


@pytest.fixture(autouse=True)
def isolated_column_settings(monkeypatch, tmp_path):
    from fpdb_3_legacy import table_columns

    settings = QSettings(str(tmp_path / "table-columns.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(table_columns, "QSettings", lambda *_args, **_kwargs: settings)
