"""Automatic initial loading, invalidation and full-size workspace tabs."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QSplitter, QWidget

from fpdb_3_legacy.automatic_loading import install_automatic_loading
from fpdb_3_legacy.responsive_layout import WorkspaceTabs

pytestmark = pytest.mark.qt


def test_page_loads_on_access_and_only_reloads_after_invalidation(qtbot):
    page = QWidget()
    qtbot.addWidget(page)
    calls = []
    install_automatic_loading(page, lambda: calls.append(True))
    page.show()
    qtbot.waitUntil(lambda: len(calls) == 1)
    page.hide()
    page.show()
    qtbot.wait(20)
    assert len(calls) == 1
    page.hide()
    page._fpdb_auto_loader.invalidate()
    qtbot.wait(20)
    assert len(calls) == 1
    page.show()
    qtbot.waitUntil(lambda: len(calls) == 2)
    page._fpdb_auto_loader.invalidate()
    page._fpdb_auto_loader.invalidate()
    qtbot.waitUntil(lambda: len(calls) == 3)


def test_workspace_always_uses_subtabs_and_only_one_visible_pane(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    splitter = QSplitter(host)
    panes = [QWidget(), QWidget(), QWidget()]
    for pane in panes:
        splitter.addWidget(pane)
    workspace = WorkspaceTabs(host, splitter, panes, ("Context", "Analysis", "Hands"))
    workspace.resize(1000, 700)
    host.resize(1000, 700)
    host.show()
    workspace.show()
    workspace.set_active(1)
    assert workspace.is_switching()
    assert [pane.isVisibleTo(workspace) for pane in panes] == [False, True, False]
    assert splitter.isHidden()
    workspace.set_switching(False)
    assert workspace.bar.isVisibleTo(workspace)
    workspace.set_active(2)
    assert [pane.isVisibleTo(workspace) for pane in panes] == [False, False, True]


def test_profit_graph_loads_on_show_with_green_profit(importer, fresh_db, legacy_config, tmp_path, qtbot):
    from fpdb_3_legacy.GuiGraphViewer import GuiGraphViewer
    from fpdb_3_legacy.ring_stats.styles import get_theme_palette
    from fpdb_3_legacy.ThemeManager import ThemeManager

    for site in legacy_config.supported_sites.values():
        site.enabled = False
    legacy_config.supported_sites['PokerStars'].enabled = True
    legacy_config.supported_sites['PokerStars'].screen_name = "Hero"
    fixture = Path(__file__).parents[1] / "fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
    importer.addImportFile(str(fixture), "PokerStars")
    assert importer.runImport()[0] == 1
    widget = GuiGraphViewer(fresh_db.sql, legacy_config, None, ThemeManager().get_theme_colors())
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitUntil(lambda: widget.plot_widget is not None, timeout=10000)
    profit = widget.plot_widget.listDataItems()[-1]
    assert profit.opts['pen'].color().name() == get_theme_palette()['graph_up']
    assert profit.getData()[1][-1] == -8
    widget.close_owned_database()
