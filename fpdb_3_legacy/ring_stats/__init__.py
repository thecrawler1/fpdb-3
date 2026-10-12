"""Shared statistics modules and the lazily loaded main statistics widget."""

from __future__ import annotations

__all__ = ["GuiRingPlayerStats"]


def __getattr__(name: str):
    if name == "GuiRingPlayerStats":
        from fpdb_3_legacy.ring_stats.main_widget import GuiRingPlayerStats

        globals()[name] = GuiRingPlayerStats
        return GuiRingPlayerStats
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
