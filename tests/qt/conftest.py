"""Qt review tests must never write the user's table-layout preferences."""

import pytest
from PySide6.QtCore import QSettings


@pytest.fixture(autouse=True)
def isolated_column_settings(monkeypatch, tmp_path):
    from fpdb_3_legacy import table_columns

    settings = QSettings(str(tmp_path / "table-columns.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(table_columns, "QSettings", lambda *_args, **_kwargs: settings)
