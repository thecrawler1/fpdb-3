#!/usr/bin/env python3
"""Measure cold-process Results click-to-painted readiness using public data.

    .venv/bin/python tools/benchmark_results_loading.py --hands 5000

The parent imports a public synthetic cash hand once, then replicates its full
Hands/HandsPlayers rows (not action/replayer/cache rows). This is a Results
loading fixture, not an importer throughput benchmark. All hands fall inside
the default current-month filter; the default selected day supplies the graph.
The child starts a fresh interpreter, opens the borrowed Database, and clicks a
Results button which creates the real DeferredPage and default-autoload viewer.
No Results/ring_stats/pyqtgraph imports are allowed before that click.
The real application theme defaults to dark_lightgreen.xml and is applied before
the click; use --theme none for an unthemed comparison. --profile prints a
cumulative cProfile report for click-to-ready to stderr. Qt-dispatched worker
callback coverage can vary; stage timers always measure worker execution.
--mode preloaded starts the real hidden DeferredPage(preload=True), waits for
table and graph data without requiring visibility/paints, then clicks to reveal
that same page. Import coldness is checked at preload start in this mode.
Preload time is separate from click-to-painted readiness; profiling starts at
preload start and continues through readiness when --profile is requested.
--mode application imports fpdb.pyw with its real Options, logging, theme and
main-window startup, then clicks the actual sidebar at its first enabled event
loop turn. It never waits for Results preload readiness. HUD/external capture
launches are disabled; the real background autoimport GUI remains enabled unless
--isolate-autoimport explicitly disables that startup callback. --profile in
this mode covers main-thread startup AND the event loop and reports global hook
costs (including the benchmark's own notify instrumentation) in JSON.
--desktop-settings preserves the original HOME/XDG desktop settings for Qt and
fontconfig, while fpdb config, logs, theme resources and table QSettings stay
temporary. The personal logger registry is copied read-only into the fixture.
--desktop-env-pid optionally takes only whitelisted desktop variables from a
running fpdb process; --platform still controls the benchmark's Qt backend.
--mode launcher calls legacy_launcher.main() unchanged, including its chdir,
sys.path insertion and runpy execution as __main__. Its real startup creates
the observed QApplication and main window; no manual startup is substituted.
--config-template reads an explicitly supplied XML profile once, retaining its
UI/theme/import options and enabled sites while anonymizing hero identities and
credentials and replacing all database/path settings with temporary public-data
locations. PokerStars is enabled for the fixture; HUD launches stay disabled.
The original XML and its databases are never modified or opened by fpdb.
--monitored-hands populates the temporary HH directory with public PokerStars
hands whose siteHandNo values already exist in the fixture database. The real
startup AutoImportThread parses these duplicates; its scheduling and overlap
with Results are reported.
Paint readiness is recorded immediately; the event loop then stays alive until
the first import cycle ends so its counts and overlap can be reported.
--click-during-import (launcher with monitored hands) waits only until the real
first worker is running, discards the startup Results cache, and clicks the real
sidebar to build a fresh widget under load. Dependencies stay warm; startup
construction/paints/samples are excluded from this second measurement.

stdout is one JSON document; diagnostics go to stderr. Timings are seconds from
perf_counter, include instrumentation overhead, and have no pass/fail latency
threshold. This is interpreter/import coldness, not an OS page-cache flush.
Qt paint completion measures CPU rendering, not compositor presentation.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import cProfile
import functools
import json
import logging
import os
import pstats
import re
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
MODULE = "fpdb_3_legacy.GuiResultsViewer"
FIXTURE = "tests/fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
DESKTOP_ENVIRONMENT = (
    "HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR",
    "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
    "QT_QPA_PLATFORM", "QT_QPA_PLATFORMTHEME", "QT_STYLE_OVERRIDE", "QT_PLUGIN_PATH",
    "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_FONT_DPI", "QT_SCALE_FACTOR",
    "QT_AUTO_SCREEN_SCALE_FACTOR", "QT_ENABLE_HIGHDPI_SCALING", "QT_SCREEN_SCALE_FACTORS",
    "QT_LOGGING_RULES", "PYTHONPATH", "PYTHONHOME", "PYTHONNOUSERSITE", "PYTHONPYCACHEPREFIX",
    "GTK_THEME", "GTK_PATH", "GTK_MODULES", "GDK_BACKEND", "FONTCONFIG_FILE",
    "FONTCONFIG_PATH", "FONTCONFIG_SYSROOT", "LANG", "LC_ALL", "LC_CTYPE",
)
sys.path.insert(0, str(REPO))


def desktop_environment(pid=None):
    if pid is None:
        return {key: os.environ.get(key) for key in DESKTOP_ENVIRONMENT}
    # /proc environ is NUL-separated binary. Never forward unselected entries.
    selected = {}
    for entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        key, separator, value = entry.partition(b"=")
        name = os.fsdecode(key)
        if separator and name in DESKTOP_ENVIRONMENT:
            selected[name] = os.fsdecode(value)
    return {key: selected.get(key) for key in DESKTOP_ENVIRONMENT}


def restore_desktop_environment(environment):
    for key, value in environment.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def isolate(root):
    """Redirect config, logging and Qt settings before any application imports."""
    for variable, name in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                           ("XDG_CACHE_HOME", "cache"), ("XDG_DATA_HOME", "data")):
        directory = root / name
        directory.mkdir(exist_ok=True)
        os.environ[variable] = str(directory)


def config_path_field(name, value="", tag=""):
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return (any(part in normalized for part in ("path", "directory", "folder", "archivebase"))
            or normalized.endswith(("dir", "filename"))
            or (normalized.endswith("file") and not normalized.endswith("profile"))
            or normalized in ("log", "hudlog", "hudlogs", "themebase")
            or tag.lower() in ("paths", "directories", "folders")
            or bool(re.match(r"^(?:/[^/]|~[/\\]|[A-Za-z]:[/\\]|\\\\|\.{1,2}[/\\]|file:|\$\{?\w+\}?[/\\])", value))
            or bool(re.search(r"[/\\][^/\\]+\.(?:xml|json|db3?|sqlite3?|log|txt|ini|conf|png|svg|jpg|csv)$", value, re.I)))


IDENTITY_FIELDS = {"screenname", "screennames", "hero", "heroalias", "heroaliases", "alias", "aliases"}


def normalized_field(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def identity_attribute(node, key):
    return normalized_field(key) in IDENTITY_FIELDS or (
        node.tag in ("hero_alias", "hero_profile") and key == "name")


def config_identity_pattern(document):
    identities = set()
    for node in document.iter():
        for key, value in node.attrib.items():
            if identity_attribute(node, key) and value:
                identities.add(value)
                identities.update(part.strip() for part in value.split(",") if part.strip())
        if normalized_field(node.tag) in IDENTITY_FIELDS and node.text and node.text.strip():
            identities.add(node.text.strip())
    if not identities:
        return None
    alternatives = "|".join(re.escape(value) for value in sorted(identities, key=len, reverse=True))
    return re.compile(r"(?<!\w)(?:" + alternatives + r")(?!\w)")


def temporary_config_path_factory(safe_paths):
    path_index = 0

    def safe_path(key, value):
        nonlocal path_index
        path_index += 1
        directory = safe_paths / f"path-{path_index}"
        directory.mkdir()
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        if normalized.endswith(("file", "filename")) or normalized in ("log", "hudlog"):
            return str(directory / "benchmark.txt")
        return str(directory)
    return safe_path


def credential_attribute(key):
    normalized = normalized_field(key)
    return any(part in normalized for part in ("password", "secret", "token", "apikey", "credential")) or normalized in (
        "user", "username", "dbuser", "pass", "passwd", "dbpass",
        "email", "emailaddress", "host", "server", "url", "endpoint")


def sanitize_config_attributes(node, identity_pattern, safe_path):
    for key, value in list(node.attrib.items()):
        if identity_attribute(node, key):
            node.set(key, "Hero")
        elif credential_attribute(key):
            node.set(key, "")
        elif config_path_field(key, value, node.tag):
            node.set(key, safe_path(key, value))
        elif identity_pattern:
            node.set(key, identity_pattern.sub("Hero", value))


def sanitize_config_text(node, identity_pattern, safe_path):
    if not node.text or not node.text.strip():
        return
    if normalized_field(node.tag) in IDENTITY_FIELDS:
        node.text = "Hero"
    elif config_path_field(node.tag, node.text.strip()):
        node.text = safe_path(node.tag, node.text)
    elif any(part in node.tag.lower() for part in ("password", "secret", "token", "credential")):
        node.text = ""
    elif identity_pattern:
        node.text = identity_pattern.sub("Hero", node.text)


def sanitize_config(document, safe_paths):
    identity_pattern = config_identity_pattern(document)
    safe_path = temporary_config_path_factory(safe_paths)
    for node in document.iter():
        sanitize_config_attributes(node, identity_pattern, safe_path)
        sanitize_config_text(node, identity_pattern, safe_path)


def replace_config_databases(document, root):
    containers = list(document.iter("supported_databases"))
    if not containers:
        containers = [ET.SubElement(document, "supported_databases")]
    for container in containers:
        container.attrib.clear()
        for node in list(container):
            container.remove(node)
        ET.SubElement(container, "database", db_name="results-benchmark.db3",
                      db_server="sqlite", db_path=str(root), default="True")
    # Legacy Config scans database tags globally, not only inside the container.
    for node in document.iter("database"):
        node.clear()
        node.attrib.update(db_name="results-benchmark.db3", db_server="sqlite",
                           db_path=str(root), default="True")


def ensure_public_pokerstars(document):
    sites = list(document.iter("site"))
    if not any(site.get("site_name") == "PokerStars" for site in sites):
        public_site = next(site for site in ET.parse(REPO / "HUD_config.xml.example").iter("site")
                           if site.get("site_name") == "PokerStars")
        supported = document.find("supported_sites")
        if supported is None:
            supported = ET.SubElement(document, "supported_sites")
        public_site = copy.deepcopy(public_site)
        supported.append(public_site)
        sites.append(public_site)
    if not any(node.get("site") == "PokerStars" for node in document.iter("hhc")):
        public_hhc = next(node for node in ET.parse(REPO / "HUD_config.xml.example").iter("hhc")
                          if node.get("site") == "PokerStars")
        converters = document.find("hhcs")
        if converters is None:
            converters = ET.SubElement(document, "hhcs")
        converters.append(copy.deepcopy(public_hhc))
    return sites


def configure_fixture_sites(document, root, config_template):
    sites = ensure_public_pokerstars(document)
    histories = root / "empty-hand-histories"
    histories.mkdir(exist_ok=True)
    for site in sites:
        if site.get("site_name") == "PokerStars":
            site.set("enabled", "True")
        elif config_template is None:
            site.set("enabled", "False")
        site.set("screen_name", "Hero")
        site.set("HH_path", str(histories))
        site.set("TS_path", str(histories))
        site.set("site_path", str(histories))


def configure_fixture_options(document, safe_paths, config_template, theme):
    for node in document.iter("import"):
        node.set("callFpdbHud", "False")
    for node in document.iter("general"):
        if theme is not None or config_template is None:
            node.set("qt_material_theme", theme or "dark_lightgreen.xml")
    for tag in ("raw_hands", "raw_tourneys"):
        for node in document.iter(tag):
            if config_template is None:
                node.set("save", "none")
            node.set("path", str(safe_paths))


def write_config(root, config_template=None, theme=None):
    """Clone only XML; never connect to a template's databases or source paths."""
    from defusedxml import ElementTree as SafeET

    tree = SafeET.parse(config_template or REPO / "HUD_config.xml.example")
    document = tree.getroot()
    safe_paths = root / "safe-config-paths"
    safe_paths.mkdir(exist_ok=True)
    sanitize_config(document, safe_paths)
    replace_config_databases(document, root)
    configure_fixture_sites(document, root, config_template)
    configure_fixture_options(document, safe_paths, config_template, theme)
    config_path = root / "HUD_config.xml"
    tree.write(config_path, encoding="utf-8", xml_declaration=True)
    return config_path


def replicate_rows(connection, hands):
    columns = {}
    templates = {}
    for table in ("Hands", "HandsPlayers"):
        columns[table] = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
        templates[table] = [dict(zip(columns[table], row))
                            for row in connection.execute(f'SELECT * FROM "{table}"')]
    if len(templates["Hands"]) != 1:
        raise RuntimeError("Expected exactly one imported cash hand")
    first = datetime.now(timezone.utc).replace(day=1, hour=12, minute=0, second=0, microsecond=0)
    days = datetime.now(timezone.utc).day
    source_id = templates["Hands"][0]["id"]
    for index in range(hands):
        stamp = (first + timedelta(days=index % days, seconds=index // days % 3600)).strftime("%Y-%m-%d %H:%M:%S")
        if index == 0:
            connection.execute("UPDATE Hands SET startTime=? WHERE id=?", (stamp, source_id))
            continue
        hand = templates["Hands"][0].copy()
        hand["id"] = source_id + index
        hand["siteHandNo"] = str(int(hand["siteHandNo"]) + index)
        hand["startTime"] = stamp
        insert_rows(connection, "Hands", columns["Hands"], [hand])
        players = [dict(row, handId=hand["id"]) for row in templates["HandsPlayers"]]
        insert_rows(connection, "HandsPlayers", columns["HandsPlayers"], players)


def insert_rows(connection, table, columns, rows):
    names = [name for name in columns if name != "id" or table == "Hands"]
    quoted = ", ".join(f'"{name}"' for name in names)
    placeholders = ", ".join("?" for _ in names)
    sql = f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})'
    connection.executemany(sql, [[row[name] for name in names] for row in rows])


def prepare_fixture(root, hands, config_template=None, theme=None, monitored_hands=0):
    from fpdb_3_legacy.Configuration import Config
    from fpdb_3_legacy.Database import Database
    from fpdb_3_legacy.Importer import Importer

    config_path = write_config(root, config_template, theme)
    config = Config(file=str(config_path), custom_log_dir=str(root))
    db = Database(config)
    importer = None
    try:
        assert Path(db.db_path).resolve().is_relative_to(root.resolve()), db.db_path
        db.recreate_tables()
        importer = Importer(None, {"threads": 1}, config, sql=db.sql)
        importer.database = db
        importer.setCallHud(False)
        importer.setMode("bulk")
        importer.addImportFile(str(REPO / FIXTURE), "PokerStars")
        imported = importer.runImport()
        if imported[0] != 1:
            raise RuntimeError(f"Public fixture import failed: {imported}")
        connection = db.connection
        replicate_rows(connection, hands)
        db.commit()
        actual = connection.execute("SELECT COUNT(*) FROM Hands").fetchone()[0]
        if actual != hands:
            raise RuntimeError(f"Expected {hands} hands, got {actual}")
        if monitored_hands:
            numbers = [row[0] for row in connection.execute("SELECT siteHandNo FROM Hands ORDER BY id")]
            public_hand = (REPO / FIXTURE).read_text()
            monitored = root / "empty-hand-histories/public-pokerstars.txt"
            with monitored.open("w", encoding="utf-8") as output:
                for index in range(monitored_hands):
                    output.write(re.sub(r"(?<=PokerStars Hand #)\d+", str(numbers[index % hands]), public_hand))
        return config_path
    finally:
        db.disconnect()
        # Importer owns this same disposable DB; its destructor may disconnect again.
        del importer


def cold_modules():
    prefixes = (MODULE, "fpdb_3_legacy.ring_stats", "pyqtgraph")
    return sorted(name for name in sys.modules
                  if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes))


class ColdProbe:
    def __init__(self, app, config, db, hands, timeout, layout, button, profile=False, mode="cold"):
        self.app, self.config, self.db = app, config, db
        self.hands, self.timeout = hands, timeout
        self.layout, self.button = layout, button
        self.marks, self.samples = {}, {}
        self.lock = threading.Lock()
        self.wrapper = self.viewer = self.error = None
        self.finished = False
        self.before_click = []
        self.profiler = cProfile.Profile() if profile else None
        self.mode = mode
        self.before_preload = []
        self.preload_snapshot = None
        self.same_wrapper = None
        self.completion_gate = None

    def mark(self, name):
        self.marks.setdefault(name, time.perf_counter())

    def timed(self, owner, name, label):
        if not hasattr(owner, name):
            return
        original = getattr(owner, name)

        @functools.wraps(original)
        def measured(*args, **kwargs):
            start = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                end = time.perf_counter()
                with self.lock:
                    self.samples.setdefault(label, []).append((start, end))
        setattr(owner, name, measured)

    def data_ready(self):
        viewer = self.viewer
        ready = (viewer is not None and len(viewer.raw_hands) == self.hands
                and len(viewer.total.hands) == self.hands and viewer.model.rowCount() > 0
                and viewer._results_current and not viewer._loading
                and viewer._pending_curve is None and len(viewer.graph.listDataItems()) >= 4
                and all(len(item.getData()[0]) > 0 for item in viewer.graph.listDataItems()))
        if ready:
            self.mark("data_ready")
        return ready

    def visible_ready(self):
        return (self.data_ready() and self.viewer.isVisible() and self.viewer.table.isVisible()
                and self.viewer.graph.isVisible())

    def painted(self, receiver):
        if "click" not in self.marks:
            return
        if self.wrapper is not None and receiver is self.wrapper:
            self.mark("deferred_page_paint")
        if self.visible_ready():
            if receiver is self.viewer.table.viewport():
                self.mark("table_paint_complete")
            if receiver is self.viewer.graph.viewport() and "curve_paint_complete" in self.marks:
                self.mark("graph_paint_complete")

    def build(self, module):
        self.instrument_results(module)
        self.mark("construct_start")
        self.viewer = module.GuiResultsViewer(self.config, db=self.db, zone=timezone.utc)
        self.mark("construct_end")
        return self.viewer

    def instrument_results(self, module):
        cls = module.GuiResultsViewer
        if self.mode == "preloaded" and not callable(getattr(cls, "preload", None)):
            raise RuntimeError("GuiResultsViewer.preload() API unavailable")
        for owner, name, label in (
            (module, "prepare_results_database", "setup_discovery"),
            (module, "results_query", "query_preparation"),
            (module.DbWorker, "run", "query_worker"),
            (module, "parse_result_rows", "row_preparation"),
            (module, "aggregate_results", "aggregation"),
            (module, "profit_curves", "curve_preparation"),
            (cls, "_populate_result_models", "table_model_render"),
            (cls, "_rebuild_table", "table_rebuild"),
            (cls, "_plot_result_curves", "graph_render"),
        ):
            self.timed(owner, name, label)
        self.observe_curves()

    def observe_curves(self):
        # Observe actual curve drawing as well as the graph viewport's Paint.
        import pyqtgraph as pg
        original_paint = pg.PlotCurveItem.paint

        def curve_paint(item, *args, **kwargs):
            result = original_paint(item, *args, **kwargs)
            if "click" in self.marks and self.visible_ready():
                if any(data.curve is item for data in self.viewer.graph.listDataItems()):
                    self.mark("curve_paint_complete")
            return result
        pg.PlotCurveItem.paint = curve_paint

    def clicked(self):
        self.before_click = cold_modules()
        self.mark("click")
        if self.mode == "cold" and self.before_click:
            self.error = f"Warm modules before click: {self.before_click}"
            self.app.quit()
            return
        if self.mode == "cold":
            self.start_loading()
        else:
            self.same_wrapper = self.wrapper is self.preloaded_wrapper
        self.layout.addWidget(self.wrapper, 1)
        self.wrapper.show()
        self.button.hide()

    def start_loading(self):
        from fpdb_3_legacy import deferred_page

        self.mark("load_start")
        if self.profiler is not None:
            self.profiler.enable()
        self.timed(deferred_page, "import_module", "import")
        if self.mode == "cold":
            self.wrapper = deferred_page.DeferredPage(MODULE, self.build)
            return
        self.before_preload = cold_modules()
        self.mark("preload_start")
        if self.before_preload:
            self.error = f"Warm modules before preload: {self.before_preload}"
            self.app.quit()
            return
        try:
            self.wrapper = deferred_page.DeferredPage(
                MODULE, self.build, preload=True, parent=self.button.window(),
            )
            self.wrapper.hide()
            self.wrapper.resize(self.button.window().size())
            self.preloaded_wrapper = self.wrapper
        except TypeError as error:
            self.error = f"DeferredPage preload API unavailable: {error}"
            self.app.quit()

    def snapshot(self):
        return {
            "stage_calls": {label: len(values) for label, values in self.samples.items()},
            "loaded_hands": len(self.viewer.raw_hands),
            "total_hands": len(self.viewer.total.hands),
            "profit": str(self.viewer.total.profit), "ev": str(self.viewer.total.ev),
            "period_hands": [len(period.hands) for period in self.viewer.periods],
            "graph_points": [len(item.getOriginalDataset()[0]) for item in self.viewer.graph.listDataItems()],
        }

    def click_when_preloaded(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        self.mark("preload_end")
        self.preload_was_hidden = not self.wrapper.isVisible() and not self.viewer.isVisible()
        if not self.preload_was_hidden:
            self.error = "Preloaded page became visible before the click"
            self.app.quit()
            return
        self.preload_snapshot = self.snapshot()
        QTest.mouseClick(self.button, Qt.MouseButton.LeftButton)

    def check(self):
        wrapper, viewer = self.wrapper, self.viewer
        if wrapper is not None and not wrapper.retry.isHidden():
            self.error = wrapper.message.text()
        if viewer is not None and viewer._has_load_error:
            self.error = viewer.status.text()
        self.data_ready()
        if self.error:
            self.app.quit()
            return
        if self.mode == "preloaded" and "click" not in self.marks:
            if self.data_ready():
                self.click_when_preloaded()
            return
        self.finish_when_painted()

    def finish_when_painted(self):
        if not self.visible_ready():
            return
        if all(key in self.marks for key in ("table_paint_complete", "graph_paint_complete")):
            # Allow another event-loop turn for queued show/autoload callbacks.
            if self.mode == "preloaded" and "paints_observed" not in self.marks:
                self.mark("paints_observed")
                return
            self.mark("ready")
            self.finished = True
            if self.completion_gate is None or self.completion_gate():
                self.app.quit()

    def expired(self):
        self.error = f"Readiness watchdog expired after {self.timeout}s"
        self.finished = False
        self.app.quit()

    def report(self):
        viewer, marks = self.viewer, self.marks
        origin = marks.get("click", marks.get("load_start", time.perf_counter()))
        result = {
            "success": self.finished, "error": self.error,
            "pid": os.getpid(), "hands": self.hands, "qt_platform": self.app.platformName(),
            "modules_present_before_click": self.before_click,
            "modules_present_before_preload": self.before_preload,
            "mode": self.mode,
            "seconds": {label: sum(end - start for start, end in values)
                        for label, values in self.samples.items()},
            "stage_calls": {label: len(values) for label, values in self.samples.items()},
            "stage_spans_from_click_seconds": {
                label: [{"start": start - origin, "end": end - origin}
                        for start, end in values] for label, values in self.samples.items()
            },
            "profile_enabled": self.profiler is not None,
            "milestones_from_load_start_seconds": {
                key: value - marks["load_start"] for key, value in marks.items()
                if key != "load_start"
            } if "load_start" in marks else {},
            "milestones_from_click_seconds": {key: value - origin for key, value in marks.items()
                                               if key != "click"} if "click" in marks else {},
            "table_rows": viewer.model.rowCount() if viewer else 0,
            "loaded_hands": len(viewer.raw_hands) if viewer else 0,
            "graph_points": [len(item.getData()[0]) for item in viewer.graph.listDataItems()] if viewer else [],
        }
        if "construct_end" in marks:
            result["seconds"]["construct"] = marks["construct_end"] - marks["construct_start"]
        if self.finished:
            result["seconds"]["total_readiness"] = marks["ready"] - marks["click"]
            result["seconds"]["qt_painted_readiness"] = max(marks["table_paint_complete"], marks["graph_paint_complete"]) - marks["click"]
        self.report_preload(result)
        return result

    def report_preload(self, result):
        if self.mode != "preloaded":
            return
        if "preload_end" in self.marks:
            result["preload_seconds"] = self.marks["preload_end"] - self.marks["preload_start"]
            result["preload_snapshot"] = self.preload_snapshot
            result["final_snapshot"] = self.snapshot()
            result["same_preloaded_wrapper_shown"] = self.same_wrapper
            result["preload_data_ready_while_hidden"] = self.preload_was_hidden
        else:
            result["preload_seconds"] = None

    def finish_profile(self):
        if self.profiler is not None:
            self.profiler.disable()
            phase = (f"{self.mode}-startup-to-ready" if self.mode in ("application", "launcher") else
                     "preload-to-ready" if self.mode == "preloaded" else "click-to-ready")
            print(f"\nResults {phase} cProfile (cumulative top 40; Qt worker callback coverage may vary):", file=sys.stderr)
            pstats.Stats(self.profiler, stream=sys.stderr).strip_dirs().sort_stats("cumulative").print_stats(40)

    def profile_summary(self):
        if self.profiler is None:
            return {}
        stats = pstats.Stats(self.profiler)
        rows = []
        groups = {name: [] for name in ("tab_profiler_and_stalls", "qt_event_hooks", "qt_font_and_style", "logging", "benchmark")}
        for (filename, line, function), (primitive, calls, own, cumulative, _callers) in stats.stats.items():
            row = dict(file=filename, line=line, function=function, calls=calls,
                       primitive_calls=primitive, self_seconds=own, cumulative_seconds=cumulative)
            rows.append(row)
            if "ui_instrumentation" in filename:
                groups["tab_profiler_and_stalls"].append(row)
            if function in ("eventFilter", "notify"):
                groups["qt_event_hooks"].append(row)
            if any(term in function.lower() for term in ("font", "stylesheet", "palette")):
                groups["qt_font_and_style"].append(row)
            if "logging" in filename:
                groups["logging"].append(row)
            if filename == __file__:
                groups["benchmark"].append(row)
        return {
            "scope": "main thread, including Qt event loop; worker imports/queries use wall timers",
            "largest_cumulative": sorted(rows, key=lambda row: row["cumulative_seconds"], reverse=True)[:40],
            "largest_self": sorted(rows, key=lambda row: row["self_seconds"], reverse=True)[:25],
            "overhead_groups": {name: {
                "self_seconds": sum(row["self_seconds"] for row in values),
                "functions": sorted(values, key=lambda row: row["cumulative_seconds"], reverse=True)[:20],
            } for name, values in groups.items()},
        }

    def shutdown(self):
        if self.wrapper is None:
            return
        self.wrapper.close_owned_database()
        workers = [self.wrapper._worker]
        if self.viewer is not None:
            workers += self.viewer._workers + self.viewer._tasks
        for worker in workers:
            if worker is not None:
                worker.wait()


def apply_theme(app, theme):
    start = time.perf_counter()
    if theme != "none":
        from fpdb_3_legacy.ThemeManager import ThemeManager

        manager = ThemeManager()
        # Keep palette lookups aligned with the explicitly requested theme,
        # without loading or saving personal settings or attaching a main window.
        if not manager.set_qt_material_theme(theme, save=False, apply_to_ui=False):
            raise RuntimeError(f"Unknown application theme: {theme}")
        if not manager._apply_theme_to_application(theme):
            raise RuntimeError(f"Could not apply application theme: {theme}")
        if not app.styleSheet():
            raise RuntimeError(f"Application stylesheet is empty after applying {theme}")
    warmed = cold_modules()
    if warmed:
        raise RuntimeError(f"Theme setup warmed cold Results dependencies: {warmed}")
    return time.perf_counter() - start


class AutoImportObservation:
    """Wall/worker-CPU observation of genuine startup cycles, without yielding."""

    def __init__(self, root, monitored_hands):
        self.root, self.monitored_hands = root, monitored_hands
        self.cycles, self.active, self.heartbeats, self.workers = [], {}, [], []
        self.lock = threading.Lock()
        self.running_at_click = False
        # A user's running fpdb otherwise owns /tmp/fpdb_global_lock.lck and
        # silently prevents this disposable application's startup import cycle.
        # Retain the real lock mechanism, but use fixture-owned lock files.
        import interlocks

        interlocks.LOCK_FILE_DIRECTORY = str(root)
        interlocks.owner_file_path = lambda name: str(root / (re.sub(r"[^A-Za-z0-9_.-]", "_", name) + ".owner"))
        if not monitored_hands:
            return
        from fpdb_3_legacy import GuiAutoImport
        from fpdb_3_legacy.Importer import Importer

        original_run = GuiAutoImport.AutoImportThread.run
        original_dispatch = Importer._import_despatch

        @functools.wraps(original_run)
        def run(worker):
            ident = threading.get_ident()
            cycle = dict(start=time.perf_counter(), end=None, worker_cpu_seconds=None,
                         thread_id=ident, files=[], new_hands=0)
            cpu = time.thread_time()
            with self.lock:
                self.cycles.append(cycle)
                self.workers.append(worker)
                self.active[ident] = cycle
            try:
                return original_run(worker)
            finally:
                with self.lock:
                    cycle.update(end=time.perf_counter(), worker_cpu_seconds=time.thread_time() - cpu,
                                 new_hands=worker.new_hands)
                    self.active.pop(ident, None)

        @functools.wraps(original_dispatch)
        def dispatch(importer, file):
            cycle = self.active.get(threading.get_ident())
            if cycle is None:
                return original_dispatch(importer, file)
            assert Path(file.path).resolve().is_relative_to(self.root), "AutoImport escaped public fixture"
            start, cpu = time.perf_counter(), time.thread_time()
            result = original_dispatch(importer, file)
            stored, duplicates, partial, skipped, errors = result[:5]
            with self.lock:
                cycle["files"].append(dict(
                    start=start, end=time.perf_counter(), worker_cpu_seconds=time.thread_time() - cpu,
                    stored=stored, duplicates=duplicates, partial=partial, skipped=skipped, errors=errors,
                ))
            return result

        GuiAutoImport.AutoImportThread.run = run
        Importer._import_despatch = dispatch

    def complete(self):
        with self.lock:
            return bool(self.cycles and self.cycles[0]["end"] is not None)

    def wait_for_workers(self, timeout):
        """Keep failed measurements from destroying a live Qt worker at exit."""
        with self.lock:
            workers = list(self.workers)
        deadline = time.perf_counter() + timeout
        for worker in workers:
            remaining = max(0, int((deadline - time.perf_counter()) * 1000))
            if not worker.wait(remaining):
                return False
        return True

    def clicked(self, window):
        page = getattr(window, "_automatic_import_page", None)
        worker = getattr(page, "import_thread", None)
        self.running_at_click = worker is not None and worker.isRunning()

    def heartbeat(self, probe):
        if "click" in probe.marks and "ready" not in probe.marks:
            self.heartbeats.append(time.perf_counter())

    def report(self, probe):
        origin = probe.marks.get("click", probe.marks.get("startup", time.perf_counter()))
        ready = probe.marks.get("ready", time.perf_counter())
        spans = dict(probe.samples)
        if "construct_end" in probe.marks:
            spans["construct"] = [(probe.marks["construct_start"], probe.marks["construct_end"])]
        with self.lock:
            cycles = []
            for cycle in self.cycles:
                end = cycle["end"] or time.perf_counter()
                files = cycle["files"]
                cycles.append(dict(
                    start_from_click_seconds=cycle["start"] - origin,
                    end_from_click_seconds=cycle["end"] - origin if cycle["end"] else None,
                    wall_seconds=end - cycle["start"], worker_cpu_seconds=cycle["worker_cpu_seconds"],
                    thread_id=cycle["thread_id"], new_hands=cycle["new_hands"],
                    counts={name: sum(file[name] for file in files) for name in
                            ("stored", "duplicates", "partial", "skipped", "errors")},
                    files=[dict(file, start_from_click_seconds=file["start"] - origin,
                                end_from_click_seconds=file["end"] - origin) for file in files],
                    overlap_click_to_paints_seconds=max(0, min(end, ready) - max(cycle["start"], origin)),
                    overlap_with_results_stages_seconds={
                        label: sum(max(0, min(end, stop) - max(cycle["start"], start)) for start, stop in values)
                        for label, values in spans.items()},
                ))
        for cycle in cycles:
            for file in cycle["files"]:
                file.pop("start")
                file.pop("end")
        ticks = [origin] + self.heartbeats + [ready]
        return dict(monitored_hands=self.monitored_hands, worker_running_at_click=self.running_at_click,
                    global_lock_files_isolated=True,
                    cycles=cycles, first_cycle_completed=self.complete() if self.monitored_hands else None,
                    max_main_poll_gap_until_ready_seconds=max((b - a for a, b in zip(ticks, ticks[1:])), default=0),
                    note="Worker wall and CPU times are observed, not cProfile-derived; overlap does not alone prove GIL starvation")


def instrument_application_import(probe):
    """Observe cold imports and construction without replacing the app builder."""
    from fpdb_3_legacy import deferred_page

    original_import = deferred_page.import_module
    instrumented = False

    def measured_import(name):
        nonlocal instrumented
        start = time.perf_counter()
        module = original_import(name)
        end = time.perf_counter()
        if name == MODULE:
            probe.samples.setdefault("import", []).append((start, end))
            if instrumented:
                return module
            instrumented = True
            probe.instrument_results(module)
            original_init = module.GuiResultsViewer.__init__

            @functools.wraps(original_init)
            def measured_init(viewer, *args, **kwargs):
                probe.mark("construct_start")
                original_init(viewer, *args, **kwargs)
                probe.viewer = viewer
                probe.mark("construct_end")
            module.GuiResultsViewer.__init__ = measured_init
        return module

    deferred_page.import_module = measured_import


def copy_desktop_logger_settings(root, desktop):
    personal_home = Path(desktop["HOME"] or Path.home())
    personal_registry = personal_home / "fpdb_logs/logger_config.json"
    if not personal_registry.is_file():
        return False
    log_root = root / "home/fpdb_logs"
    log_root.mkdir(exist_ok=True)
    (log_root / "logger_config.json").write_bytes(personal_registry.read_bytes())
    return True


def freeze_application_paths(root):
    """Import HOME-derived application constants before restoring desktop HOME."""
    import loggingFpdb
    import qt_material
    from qt_material.resources import generate

    from fpdb_3_legacy import Configuration, ThemeManager, table_columns

    assert Path(Configuration.CONFIG_PATH).resolve().is_relative_to(root)
    assert ThemeManager.CUSTOM_THEMES_DIR.resolve().is_relative_to(root)
    assert Path(generate.RESOURCES_PATH).resolve().is_relative_to(root)
    assert Path(qt_material.RESOURCES_PATH).resolve().is_relative_to(root)
    assert Path(loggingFpdb.get_log_config().config_file).resolve().is_relative_to(root)
    assert callable(table_columns.QSettings)


def audited_write_path(event, arguments):
    if event == "open":
        path, mode, flags = arguments
        if ((mode and any(char in mode for char in "wax+")) or
                flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            return path
    elif event in ("os.mkdir", "os.remove", "os.rmdir", "os.rename"):
        return arguments[0]
    return None


def protect_desktop_settings(desktop):
    personal_home = Path(desktop["HOME"] or Path.home())
    protected = [personal_home / name for name in (".fpdb", "fpdb_logs", ".qt_material")]
    protected += [Path(desktop.get("XDG_CONFIG_HOME") or personal_home / ".config") / "fpdb"]

    def protect_personal_settings(event, arguments):
        path = audited_write_path(event, arguments)
        if isinstance(path, (str, bytes, os.PathLike)):
            resolved = Path(os.fsdecode(path)).absolute()
            if any(resolved.is_relative_to(directory) for directory in protected):
                raise PermissionError(f"Benchmark blocked personal settings write: {resolved}")

    sys.addaudithook(protect_personal_settings)


def prepare_application_runtime(config_path, profile, desktop_settings):
    """Isolate all app writes, optionally restoring read-only desktop settings."""
    startup = time.perf_counter()
    profiler = cProfile.Profile() if profile else None
    if profiler is not None:
        profiler.enable()
    desktop = desktop_environment() if desktop_settings else {}
    root = config_path.parent.resolve()
    isolate(root)
    os.chdir(root)  # default-config lookup must never discover a checkout HUD_config
    # Default-config consumers, including singleton managers, must see the same
    # fixture as Options -c. Never let ConfigInitializer create a shipped default.
    default = Path(os.environ["HOME"]) / ".fpdb"
    default.mkdir(exist_ok=True)
    (default / "HUD_config.xml").write_bytes(config_path.read_bytes())
    sys.path.insert(0, str(REPO / "fpdb_3_legacy"))
    logger_settings_copied = False
    if desktop_settings:
        sys.dont_write_bytecode = True
        logger_settings_copied = copy_desktop_logger_settings(root, desktop)
        freeze_application_paths(root)
        restore_desktop_environment(desktop)
        protect_desktop_settings(desktop)
    sys.argv = [str(REPO / "fpdb_3_legacy/fpdb.pyw"), "-c", str(config_path), "--errorsToConsole"]
    os.environ["FPDB_PROFILE"] = "0"  # one explicitly scoped profiler below
    return dict(startup=startup, profiler=profiler, root=root, default=default,
                desktop=desktop, logger_settings_copied=logger_settings_copied)


def run_application(config_path, hands, timeout, theme, profile, isolate_autoimport, desktop_settings=False, mode="application", monitored_hands=0, click_during_import=False):
    """Use the shipped entrypoint namespace and intact fpdb class/handlers."""
    runtime = prepare_application_runtime(config_path, profile, desktop_settings)
    observation = AutoImportObservation(runtime["root"], monitored_hands)
    if mode == "launcher":
        return run_launcher(config_path, hands, timeout, profile, isolate_autoimport,
                            **runtime,
                            observation=observation, click_during_import=click_during_import)
    return run_manual_application(config_path, hands, timeout, theme, isolate_autoimport, runtime, observation)


def disable_external_launches(auto_cls):
    disabled = []
    for name in ("_launch_hud", "start_swc_native_capture"):
        if hasattr(auto_cls, name):
            setattr(auto_cls, name, lambda *args, **kwargs: None)
            disabled.append("GuiAutoImport." + name)
    return disabled


def isolate_table_settings(root):
    from PySide6.QtCore import QSettings

    from fpdb_3_legacy import table_columns

    table_settings_path = root / "table-columns.ini"
    table_columns.QSettings = lambda *_args, **_kwargs: QSettings(str(table_settings_path), QSettings.Format.IniFormat)
    return table_settings_path


def isolate_background_import(cls, disabled, isolate_autoimport):
    if isolate_autoimport:
        cls._start_background_auto_import = lambda self: None
        disabled.append("fpdb._start_background_auto_import")


def paint_application_class(created=None, navigation_enabled=None):
    """Build the Qt subclass lazily, preserving import coldness in the parent."""
    from PySide6.QtCore import QEvent, QTimer
    from PySide6.QtWidgets import QApplication

    class PaintApplication(QApplication):
        probe = None

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if created is not None:
                created(self)

        def notify(self, receiver, event):
            kind = event.type()
            result = super().notify(receiver, event)
            if self.probe is not None:
                self.probe.event_counts[int(kind)] += 1
                if kind == QEvent.Type.Paint:
                    self.probe.painted(receiver)
                elif (navigation_enabled is not None and kind == QEvent.Type.EnabledChange
                      and receiver.objectName() == "applicationNavigation" and receiver.isEnabled()):
                    QTimer.singleShot(0, navigation_enabled)
            return result
    return PaintApplication


class PerfLogCapture(logging.Handler):
    def __init__(self, messages):
        super().__init__()
        self.messages = messages

    def emit(self, record):
        message = record.getMessage()
        if "[PERF]" in message:
            self.messages.append(dict(logger=record.name, message=message))


def application_state(runtime, observation, hands, timeout, mode, isolate_autoimport):
    from PySide6.QtWidgets import QMessageBox

    state = dict(runtime=runtime, observation=observation, hands=hands, timeout=timeout, mode=mode,
                 isolate_autoimport=isolate_autoimport, window=None, click_state={}, dialogs=[],
                 perf_logs=[], disabled=[], report_extra={}, startup_cache_discarded=False)
    state["log_capture"] = PerfLogCapture(state["perf_logs"])
    state["message_box_type"] = QMessageBox
    state["table_settings_path"] = isolate_table_settings(runtime["root"])
    return state


def attach_application_probe(state, app, config):
    runtime, observation = state["runtime"], state["observation"]
    probe = ColdProbe(app, config, None, state["hands"], state["timeout"], None, None, mode=state["mode"])
    probe.profiler = runtime["profiler"]
    if observation.monitored_hands:
        probe.completion_gate = observation.complete
    elif not state["isolate_autoimport"]:
        probe.completion_gate = lambda: bool(getattr(state["window"], "_background_auto_import_started", False))
    probe.event_counts = Counter()
    probe.marks["startup"] = runtime["startup"]
    app.probe = probe
    state.update(app=app, probe=probe)
    instrument_application_import(probe)
    return probe


def apply_manual_theme(config, theme):
    from fpdb_3_legacy.ThemeManager import ThemeManager

    theme_start = time.perf_counter()
    theme_manager = ThemeManager()
    theme_manager.initialize(config=config)
    if theme != "none":
        theme_manager.set_qt_material_theme(theme, save=False, apply_to_ui=False)
        theme_manager._apply_theme_to_application(theme)
    return theme_manager, time.perf_counter() - theme_start


def dismiss_config_notice(widget, state, quit_on_error=False):
    if not isinstance(widget, state["message_box_type"]) or not widget.isVisible():
        return True
    # Config currently marks explicit -c files as example copies. Retain that
    # real startup behavior and acknowledge only its expected fixture notice.
    if widget.windowTitle() == "Config file":
        state["dialogs"].append(widget.windowTitle())
        widget.accept()
        return True
    state["probe"].error = f"Unexpected startup dialog: {widget.windowTitle()}: {widget.text()}"
    widget.reject()
    if quit_on_error:
        state["app"].quit()
    return False


def dismiss_startup_notices(state):
    for widget in state["app"].topLevelWidgets():
        dismiss_config_notice(widget, state)


def start_poll(callback, parent=None):
    from PySide6.QtCore import QTimer

    poll = QTimer(parent)
    poll.setInterval(10)
    poll.timeout.connect(callback)
    poll.start()
    return poll


def construct_manual_window(cls, state):
    from PySide6.QtCore import QTimer

    probe = state["probe"]
    notices = start_poll(functools.partial(dismiss_startup_notices, state))
    QTimer.singleShot(int(state["timeout"] * 1000), probe.expired)
    probe.mark("window_construct_start")
    window = cls()
    notices.stop()
    probe.mark("window_construct_end")
    state["window"] = window
    validate_application_paths(state)
    probe.config, probe.db = window.config, window.db
    return window


def validate_application_paths(state):
    from fpdb_3_legacy.ConfigInitializer import ConfigInitializer
    from fpdb_3_legacy.ConfigurationManager import ConfigurationManager

    window = state["window"]
    paths = (window.config.file, window.db.db_path, window.config.dir_log,
             ConfigInitializer.get_config().file, ConfigurationManager().get_config().file)
    for path in paths:
        assert Path(path).resolve().is_relative_to(state["runtime"]["root"]), path


def record_results_click(state):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window, probe, observation = state["window"], state["probe"], state["observation"]
    button = window.application_navigation.buttons["Results"][0]
    probe.config, probe.db, probe.button = window.config, window.db, button
    probe.mark("navigation_enabled")
    probe.before_click = cold_modules()
    existing = getattr(window, "_results_page", None)
    state["click_state"].update(preload_page_existed=existing is not None,
                                preload_data_ready=bool(existing is not None and existing._ready), navigation_enabled=True)
    probe.mark("load_start")
    probe.mark("click")
    observation.clicked(window)
    if state.get("click_during_import") and not observation.running_at_click:
        probe.error = "AutoImport stopped while discarding the Results cache"
        state["app"].quit()
        return
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    probe.mark("tab_results_returned")


def check_manual_application(state):
    window, probe = state["window"], state["probe"]
    if "click" not in probe.marks:
        button = window.application_navigation.buttons["Results"][0]
        if not window.application_navigation.isEnabled() or not button.isEnabled() or not button.isVisible():
            return
        record_results_click(state)
    probe.wrapper = window._results_page
    state["observation"].heartbeat(probe)
    probe.check()


def application_report(state):
    from PySide6.QtCore import QEvent

    app, probe, window = state["app"], state["probe"], state["window"]
    runtime = state["runtime"]
    desktop, startup = runtime["desktop"], runtime["startup"]
    result = probe.report()
    logging_modules = {name: getattr(module, "__file__", None) for name, module in sys.modules.items()
                       if name == "loggingFpdb" or name.endswith(".loggingFpdb")}
    result.update(
        theme=state["theme"],
        application_stylesheet_applied=bool(app.styleSheet()),
        application_entrypoint="fpdb_3_legacy/fpdb.pyw", application_class=window.__class__.__name__,
        startup_to_click_seconds=probe.marks.get("click", startup) - startup,
        window_construction_seconds=probe.marks["window_construct_end"] - probe.marks["window_construct_start"],
        startup_to_ready_seconds=probe.marks.get("ready", time.perf_counter()) - startup,
        click_state=state["click_state"], disabled_callbacks=state["disabled"],
        autoimport_gui_created=getattr(window, "_automatic_import_page", None) is not None,
        config_and_database_isolated=True,
        desktop_settings=bool(desktop),
        desktop_environment_preserved=bool(desktop) and all(os.environ.get(key) == value for key, value in desktop.items()),
        desktop_environment_keys=sorted(key for key, value in desktop.items() if value is not None),
        personal_logger_settings_copied=runtime["logger_settings_copied"],
        table_settings_isolated=True,
        table_settings_file=str(state["table_settings_path"]),
        fpdb_config_root=str(runtime["default"]),
        log_directory=str(window.config.dir_log),
        acknowledged_startup_dialogs=state["dialogs"],
        application_perf_logs=state["perf_logs"],
        logging_module_aliases=logging_modules,
        qt_event_counts={QEvent.Type(kind).name: count for kind, count in probe.event_counts.items()},
        profile=probe.profile_summary(),
        autoimport=state["observation"].report(probe),
    )
    result.update(state["report_extra"])
    return result


def finish_application(state):
    app, probe = state["app"], state["probe"]
    state["poll"].stop()
    probe.finish_profile()
    if not state["observation"].wait_for_workers(state["timeout"]):
        probe.finished = False
        probe.error = "AutoImport worker did not stop before benchmark teardown"
    logging.getLogger().removeHandler(state["log_capture"])
    result = application_report(state)
    probe.shutdown()
    app.probe = None
    state["window"].close()
    return result


def run_manual_application(config_path, hands, timeout, theme, isolate_autoimport, runtime, observation):
    from PySide6.QtCore import QTimer

    from fpdb_3_legacy.ConfigInitializer import ConfigInitializer
    from fpdb_3_legacy.ConfigurationManager import ConfigurationManager

    entrypoint_started = time.perf_counter()
    namespace = runpy.run_path(sys.argv[0], run_name="fpdb_results_benchmark_entrypoint")
    entrypoint_import = time.perf_counter() - entrypoint_started
    cls = namespace["fpdb"]
    state = application_state(runtime, observation, hands, timeout, "application", isolate_autoimport)
    config = ConfigInitializer.initialize(str(config_path), fallback_to_default=False)
    manager = ConfigurationManager()
    if manager.initialized:
        assert Path(manager.get_config().file).resolve().is_relative_to(runtime["root"])
    state["disabled"] = disable_external_launches(namespace["GuiAutoImport"].GuiAutoImport)
    isolate_background_import(cls, state["disabled"], isolate_autoimport)
    app = paint_application_class()([])
    probe = attach_application_probe(state, app, config)
    theme_manager, theme_seconds = apply_manual_theme(config, theme)
    theme_manager._main_window = construct_manual_window(cls, state)
    state["theme"] = theme
    state["report_extra"].update(entrypoint_import_seconds=entrypoint_import, theme_application_seconds=theme_seconds)
    logging.getLogger().addHandler(state["log_capture"])
    check = functools.partial(check_manual_application, state)
    state["poll"] = start_poll(check)
    QTimer.singleShot(0, check)
    QTimer.singleShot(int(timeout * 1000), probe.expired)
    app.exec()
    return finish_application(state)


def instrument_main_window(state):
    # runpy's live __main__ owns the real class. Wrap only its timing boundary;
    # discovery and clicking still use the application's top-level widgets.
    main_cls = sys.modules["__main__"].fpdb
    original_init = main_cls.__init__
    probe = state["probe"]

    @functools.wraps(original_init)
    def measured_window_init(window, *args, **kwargs):
        probe.mark("window_construct_start")
        original_init(window, *args, **kwargs)
        probe.mark("window_construct_end")

    main_cls.__init__ = measured_window_init
    isolate_background_import(main_cls, state["disabled"], state["isolate_autoimport"])


def initialize_launcher_application(state, app):
    from PySide6.QtCore import QTimer

    from fpdb_3_legacy.ConfigInitializer import ConfigInitializer

    probe = attach_application_probe(state, app, ConfigInitializer.get_config())
    probe.mark("application_created")
    instrument_main_window(state)
    check = functools.partial(check_launcher_application, state)
    state["poll"] = app.poll = start_poll(check, app)
    QTimer.singleShot(0, check)
    QTimer.singleShot(int(state["timeout"] * 1000), probe.expired)


def discover_launcher_window(state):
    for widget in state["app"].topLevelWidgets():
        if not dismiss_config_notice(widget, state, quit_on_error=True):
            return False
        if widget.__class__.__name__ == "fpdb":
            state["window"] = widget
            state.update(launcher_cwd=str(Path.cwd()), launcher_sys_path_0=sys.path[0],
                         main_module=widget.__class__.__module__)
    navigation = getattr(state["window"], "application_navigation", None)
    return navigation is not None and navigation.isEnabled()


def fail_launcher_measurement(state, message):
    state["probe"].error = message
    state["app"].quit()
    return False


def discard_startup_results(state, cached):
    probe = state["probe"]
    state["startup_cache_discarded"] = True
    state["startup_cache_ready"] = cached._ready
    state["startup_stage_calls"] = {label: len(values) for label, values in probe.samples.items()}
    state["window"]._discard_results_page()
    # Exclude all prior viewer data, construction and paints from fresh readiness.
    probe.marks = {key: value for key, value in probe.marks.items() if key in
                   ("startup", "application_created", "window_construct_start", "window_construct_end")}
    with probe.lock:
        probe.samples.clear()
    probe.viewer = probe.wrapper = None
    probe.finished = False
    state["observation"].heartbeats.clear()
    state["perf_logs"].clear()


def prepare_under_load_click(state):
    window, observation = state["window"], state["observation"]
    page = getattr(window, "_automatic_import_page", None)
    worker = getattr(page, "import_thread", None)
    if worker is None or not worker.isRunning():
        if observation.complete():
            return fail_launcher_measurement(state, "Missed the first AutoImport worker; refusing to measure after import")
        return False
    if observation.complete():
        return fail_launcher_measurement(state, "First AutoImport cycle ended before the under-load click")
    cached = getattr(window, "_results_page", None)
    if cached is None or not cached._ready:
        detail = cached.message.text() if cached is not None else "cache absent"
        return fail_launcher_measurement(state, f"Startup Results cache was not ready when AutoImport started: {detail}")
    discard_startup_results(state, cached)
    return True


def check_launcher_application(state):
    if not discover_launcher_window(state):
        return
    window, probe = state["window"], state["probe"]
    if "click" not in probe.marks:
        button = window.application_navigation.buttons["Results"][0]
        if not button.isEnabled() or not button.isVisible():
            return
        if state["click_during_import"] and not prepare_under_load_click(state):
            return
        validate_application_paths(state)
        # load_profile replaces root handlers; attach after its real setup.
        logging.getLogger().addHandler(state["log_capture"])
        record_results_click(state)
        if probe.error:
            return
    probe.wrapper = window._results_page
    state["observation"].heartbeat(probe)
    probe.check()


def record_launcher_report(state, launch_start):
    from fpdb_3_legacy.ThemeManager import ThemeManager

    state["theme"] = ThemeManager().get_qt_material_theme()
    marks, startup = state["probe"].marks, state["runtime"]["startup"]
    state["report_extra"].update(
        launcher_entrypoint="fpdb_3_legacy.legacy_launcher.main",
        launcher_main_module=state["main_module"], launcher_cwd=state["launcher_cwd"],
        launcher_sys_path_0=state["launcher_sys_path_0"], true_main_block=True,
        launcher_execution_seconds=time.perf_counter() - launch_start,
        startup_to_click_seconds=marks["click"] - startup if "click" in marks else None,
        click_during_import=state["click_during_import"],
        startup_cached_results_discarded=state["startup_cache_discarded"],
        startup_cached_results_ready=state.get("startup_cache_ready"),
        startup_stage_calls=state.get("startup_stage_calls", {}),
    )


def run_launcher(config_path, hands, timeout, profile, isolate_autoimport, *, startup,
                 profiler, root, default, desktop, logger_settings_copied, observation,
                 click_during_import=False):
    """Let the console launcher execute the actual __main__ startup and loop."""
    from PySide6 import QtWidgets

    from fpdb_3_legacy import GuiAutoImport, legacy_launcher

    runtime = dict(startup=startup, profiler=profiler, root=root, default=default,
                   desktop=desktop, logger_settings_copied=logger_settings_copied)
    state = application_state(runtime, observation, hands, timeout, "launcher", isolate_autoimport)
    state["click_during_import"] = click_during_import
    state["disabled"] = disable_external_launches(GuiAutoImport.GuiAutoImport)
    original_application = QtWidgets.QApplication
    QtWidgets.QApplication = paint_application_class(
        created=functools.partial(initialize_launcher_application, state),
        navigation_enabled=functools.partial(check_launcher_application, state),
    )
    sys.argv = [str(Path(sys.executable).parent / "fpdb_3_legacy"),
                "-c", str(config_path), "--errorsToConsole"]
    launch_start = time.perf_counter()
    try:
        legacy_launcher.main()  # exact console entrypoint: chdir + runpy(__main__)
    finally:
        QtWidgets.QApplication = original_application
        if profiler is not None:
            profiler.disable()
    record_launcher_report(state, launch_start)
    return finish_application(state)


def run_child(config_path, hands, timeout, theme, profile, mode):
    from PySide6.QtCore import QEvent, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

    from fpdb_3_legacy import deferred_page  # noqa: F401 -- deliberately lightweight pre-click import
    from fpdb_3_legacy.Configuration import Config
    from fpdb_3_legacy.Database import Database

    class PaintApplication(QApplication):
        probe = None

        def notify(self, receiver, event):
            is_paint = event.type() == QEvent.Type.Paint
            result = super().notify(receiver, event)
            if is_paint and self.probe is not None:
                self.probe.painted(receiver)
            return result

    app = PaintApplication([])
    app.setApplicationName("fpdb-results-cold-benchmark")
    theme_seconds = apply_theme(app, theme)
    config = Config(file=str(config_path), custom_log_dir=str(config_path.parent))
    db = Database(config)
    if not Path(db.db_path).resolve().is_relative_to(config_path.parent.resolve()):
        raise RuntimeError(f"Database escaped temporary fixture: {db.db_path}")
    window = QWidget()
    window.resize(1280, 900)
    layout = QVBoxLayout(window)
    button = QPushButton("Results")
    layout.addWidget(button)
    probe = ColdProbe(app, config, db, hands, timeout, layout, button, profile, mode)
    app.probe = probe
    button.clicked.connect(probe.clicked)
    poll = QTimer()
    poll.setInterval(10)
    poll.timeout.connect(probe.check)
    poll.start()
    window.show()
    if mode == "preloaded":
        QTimer.singleShot(0, probe.start_loading)
    else:
        QTimer.singleShot(0, lambda: QTest.mouseClick(button, Qt.MouseButton.LeftButton))
    QTimer.singleShot(int(timeout * 1000), probe.expired)
    app.exec()
    probe.finish_profile()
    poll.stop()
    result = probe.report()
    result.update(theme=theme, theme_application_seconds=theme_seconds,
                  application_stylesheet_applied=bool(app.styleSheet()))
    probe.shutdown()
    app.probe = None
    window.close()
    db.disconnect()
    return result


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hands", type=int, default=5000)
    parser.add_argument("--monitored-hands", type=int, default=0, help="public duplicate HHs parsed by the real startup AutoImportThread")
    parser.add_argument("--click-during-import", action="store_true", help="launcher: discard startup Results cache and measure a fresh click while the first AutoImport worker is running")
    parser.add_argument("--mode", choices=("cold", "preloaded", "application", "launcher"), default="cold")
    parser.add_argument("--timeout", type=float, default=60, help="readiness watchdog, not a performance threshold")
    parser.add_argument("--platform", default="offscreen", help="Qt platform (offscreen by default; xcb/wayland for desktop paints)")
    parser.add_argument("--theme", help="application qt_material theme; defaults to the template's saved theme; none opts out of manual theme setup")
    parser.add_argument("--config-template", type=Path, help="read-only XML source; clone UI/options with anonymized identities and temporary paths/database")
    parser.add_argument("--profile", action="store_true", help="print click-to-ready cumulative cProfile to stderr")
    parser.add_argument("--isolate-autoimport", action="store_true", help="application/launcher modes: disable background autoimport startup callback")
    parser.add_argument("--desktop-settings", action="store_true", help="application/launcher modes: preserve desktop HOME/XDG and read-only logger settings")
    parser.add_argument("--desktop-env-pid", type=int, help="with --desktop-settings, mirror whitelisted /proc/PID/environ variables")
    parser.add_argument("--child-config", type=Path, help=argparse.SUPPRESS)
    return parser


def validate_workload_options(args, parser):
    if args.hands < 1 or args.timeout <= 0:
        parser.error("--hands and --timeout must be positive")
    if args.monitored_hands < 0:
        parser.error("--monitored-hands must be nonnegative")
    if args.monitored_hands and (args.mode not in ("application", "launcher") or args.isolate_autoimport):
        parser.error("--monitored-hands requires application/launcher mode with background autoimport enabled")
    if args.click_during_import and (args.mode != "launcher" or not args.monitored_hands):
        parser.error("--click-during-import requires --mode launcher and positive --monitored-hands")


def validate_desktop_options(args, parser):
    if args.theme is not None and (Path(args.theme).name != args.theme or "/" in args.theme or "\\" in args.theme):
        parser.error("--theme must be a built-in theme name or none, not a file path")
    if args.desktop_settings and args.mode not in ("application", "launcher"):
        parser.error("--desktop-settings requires --mode application or launcher")
    if args.desktop_env_pid is not None and (not args.desktop_settings or args.desktop_env_pid <= 0):
        parser.error("--desktop-env-pid requires --desktop-settings and a positive PID")


def run_benchmark_child(args):
    if args.theme is None:
        args.theme = "dark_lightgreen.xml"
    if args.mode in ("application", "launcher"):
        return run_application(args.child_config, args.hands, args.timeout, args.theme,
                               args.profile, args.isolate_autoimport, args.desktop_settings, args.mode,
                               args.monitored_hands, args.click_during_import)
    return run_child(args.child_config, args.hands, args.timeout, args.theme, args.profile, args.mode)


def fixture_theme(config_path):
    general = ET.parse(config_path).getroot().find("general")
    theme = general.get("qt_material_theme", "dark_lightgreen.xml") if general is not None else "dark_lightgreen.xml"
    return theme if Path(theme).name == theme else "dark_lightgreen.xml"


def benchmark_child_command(args, config_path):
    command = [sys.executable, str(Path(__file__).resolve()), "--child-config", str(config_path),
               "--hands", str(args.hands), "--timeout", str(args.timeout), "--platform", args.platform,
               "--theme", args.theme, "--mode", args.mode]
    if args.monitored_hands:
        command.extend(["--monitored-hands", str(args.monitored_hands)])
    for enabled, flag in ((args.click_during_import, "--click-during-import"), (args.profile, "--profile"),
                          (args.isolate_autoimport, "--isolate-autoimport"), (args.desktop_settings, "--desktop-settings")):
        if enabled:
            command.append(flag)
    return command


def benchmark_child_environment(args, desktop):
    environment = os.environ.copy()
    if args.desktop_settings:
        for key, value in desktop.items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        environment["QT_QPA_PLATFORM"] = args.platform
    return environment


def execute_benchmark_child(args, config_path, desktop):
    child = subprocess.run(benchmark_child_command(args, config_path), cwd=REPO, text=True, capture_output=True,
                           timeout=args.timeout + 60, check=False, env=benchmark_child_environment(args, desktop))
    if child.stderr:
        print(child.stderr, file=sys.stderr, end="")
    if child.returncode not in (0, 1) or not child.stdout.strip():
        raise RuntimeError(f"Benchmark child exited {child.returncode}: {child.stdout}")
    return json.loads(child.stdout)


def validate_monitored_import(args, result, root):
    if not args.monitored_hands:
        return
    with sqlite3.connect(f"file:{root / 'results-benchmark.db3'}?mode=ro", uri=True) as connection:
        final_hands = connection.execute("SELECT COUNT(*) FROM Hands").fetchone()[0]
    result["autoimport"]["database_hands_after_cycle"] = final_hands
    if final_hands != args.hands:
        result.update(success=False, error="Monitored duplicate import changed fixture hand count")
    elif not result["autoimport"]["first_cycle_completed"]:
        result.update(success=False, error="Startup AutoImport cycle did not complete")
    else:
        counts = result["autoimport"]["cycles"][0]["counts"]
        if counts["duplicates"] != args.monitored_hands or any(counts[key] for key in ("stored", "partial", "skipped", "errors")):
            result.update(success=False, error="Startup AutoImport did not parse exactly the public duplicate workload")


def run_benchmark_parent(args, desktop):
    with tempfile.TemporaryDirectory(prefix="fpdb-results-benchmark-") as temporary:
        root = Path(temporary)
        isolate(root)
        start = time.perf_counter()
        config_path = prepare_fixture(root, args.hands, args.config_template, args.theme, args.monitored_hands)
        if args.theme is None:
            args.theme = fixture_theme(config_path)
        fixture_seconds = time.perf_counter() - start
        result = execute_benchmark_child(args, config_path, desktop)
        validate_monitored_import(args, result, root)
        result.update(fixture=FIXTURE, fixture_preparation_seconds=fixture_seconds,
                      config_template_used=args.config_template is not None,
                      config_template_anonymized=args.config_template is not None,
                      desktop_environment_source_pid=args.desktop_env_pid,
                      parent_pid=os.getpid(), temporary_fixture_removed=True,
                      fixture_strategy="one imported synthetic cash hand; replicated full Hands/HandsPlayers rows",
                      timing_notes="stage durations can overlap/nest; query_worker includes connection/execute/fetch/emit; Qt paints are CPU completion, not compositor presentation")
    return result


def main():
    parser = argument_parser()
    args = parser.parse_args()
    validate_workload_options(args, parser)
    validate_desktop_options(args, parser)
    desktop = desktop_environment(args.desktop_env_pid) if args.desktop_settings else {}
    if args.config_template is not None:
        args.config_template = args.config_template.expanduser().resolve()
    os.environ["QT_QPA_PLATFORM"] = args.platform
    with contextlib.redirect_stdout(sys.stderr):
        result = run_benchmark_child(args) if args.child_config else run_benchmark_parent(args, desktop)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
