"""Shared ring-stats imports must not initialize the full statistics UI."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def run_cold_import(code, tmp_path):
    env = os.environ.copy()
    env.update(
        QT_QPA_PLATFORM="offscreen",
        PYTHONDONTWRITEBYTECODE="1",
        HOME=str(tmp_path),
        XDG_CONFIG_HOME=str(tmp_path / "config"),
        XDG_CACHE_HOME=str(tmp_path / "cache"),
        XDG_DATA_HOME=str(tmp_path / "data"),
    )
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "statement",
    [
        "import fpdb_3_legacy.ring_stats",
        "from fpdb_3_legacy.ring_stats.base import DbWorker",
        "from fpdb_3_legacy.ring_stats.styles import get_modern_qss",
        "from fpdb_3_legacy.ring_stats.views.dashboard_view import ProfitGraphWidget",
    ],
)
def test_shared_imports_do_not_load_main_widget_dependencies(statement, tmp_path):
    run_cold_import(
        f"""
        import sys
        {statement}
        unnecessary = (
            "fpdb_3_legacy.Filters",
            "fpdb_3_legacy.ring_stats.main_widget",
            "fpdb_3_legacy.ring_stats.controller",
            "fpdb_3_legacy.ring_stats.views.positional_view",
            "fpdb_3_legacy.ring_stats.views.starting_hands_view",
            "fpdb_3_legacy.ring_stats.views.table_view",
        )
        loaded = [name for name in unnecessary if name in sys.modules]
        assert not loaded, loaded
        """,
        tmp_path,
    )


def test_main_widget_lazy_export_and_legacy_import_are_compatible(tmp_path):
    run_cold_import(
        """
        import sys
        import fpdb_3_legacy.ring_stats as package

        assert package.__all__ == ["GuiRingPlayerStats"]
        assert "GuiRingPlayerStats" not in vars(package)
        assert "fpdb_3_legacy.ring_stats.main_widget" not in sys.modules
        try:
            package.missing_export
        except AttributeError:
            pass
        else:
            raise AssertionError("unknown exports must raise AttributeError")
        assert "fpdb_3_legacy.ring_stats.main_widget" not in sys.modules

        from fpdb_3_legacy.ring_stats import GuiRingPlayerStats
        from fpdb_3_legacy.ring_stats.main_widget import GuiRingPlayerStats as direct
        from fpdb_3_legacy.GuiRingPlayerStats import GuiRingPlayerStats as legacy
        from PySide6.QtWidgets import QSplitter

        assert GuiRingPlayerStats is direct is legacy is package.GuiRingPlayerStats
        assert vars(package)["GuiRingPlayerStats"] is direct
        assert issubclass(GuiRingPlayerStats, QSplitter)
        namespace = {}
        exec("from fpdb_3_legacy.ring_stats import *", namespace)
        assert namespace["GuiRingPlayerStats"] is direct
        """,
        tmp_path,
    )


def test_controller_submodule_import_remains_available(tmp_path):
    run_cold_import(
        """
        import sys
        from fpdb_3_legacy.ring_stats import controller

        assert controller is sys.modules["fpdb_3_legacy.ring_stats.controller"]
        assert "fpdb_3_legacy.ring_stats.main_widget" not in sys.modules
        """,
        tmp_path,
    )
