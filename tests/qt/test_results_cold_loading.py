"""Verify cold imports and actual default-autoload paints across a process boundary."""

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

pytestmark = pytest.mark.qt


@pytest.mark.parametrize("theme", ["dark_lightgreen.xml", "none"])
def test_results_cold_process_reaches_painted_table_and_graph(theme):
    repo = Path(__file__).resolve().parents[2]
    command = [sys.executable, str(repo / "tools/benchmark_results_loading.py"), "--hands", "3"]
    if theme == "none":
        command.extend(["--theme", "none", "--profile"])
    child = subprocess.run(
        command,
        cwd=repo, capture_output=True, text=True, timeout=90, check=False,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    report = json.loads(child.stdout)
    assert report["success"], report
    assert report["mode"] == "cold"
    assert report["pid"] != report["parent_pid"]
    assert report["modules_present_before_click"] == []
    assert report["theme"] == theme
    assert report["application_stylesheet_applied"] == (theme != "none")
    assert report["theme_application_seconds"] >= 0
    assert report["profile_enabled"] == (theme == "none")
    if theme == "none":
        assert "Results click-to-ready cProfile" in child.stderr
        assert "Ordered by: cumulative time" in child.stderr
    assert report["temporary_fixture_removed"]
    assert report["loaded_hands"] == 3
    assert report["table_rows"] > 0
    assert len(report["graph_points"]) == 4
    assert all(points >= 2 for points in report["graph_points"])
    for stage in ("import", "setup_discovery", "query_worker", "graph_render"):
        assert report["stage_calls"][stage] == 1
        span = report["stage_spans_from_click_seconds"][stage][0]
        assert 0 <= span["start"] <= span["end"]
    marks = report["milestones_from_click_seconds"]
    assert 0 <= marks["construct_start"] <= marks["construct_end"] <= marks["data_ready"]
    assert marks["data_ready"] <= marks["curve_paint_complete"] <= marks["graph_paint_complete"]
    assert marks["data_ready"] <= marks["table_paint_complete"] <= marks["ready"]
    assert marks["graph_paint_complete"] <= marks["ready"]
    # Deliberately no latency ceiling: this records a baseline, not a speed gate.


def test_results_preloaded_5000_hands_show_without_requery_under_250ms():
    repo = Path(__file__).resolve().parents[2]
    child = subprocess.run(
        [sys.executable, str(repo / "tools/benchmark_results_loading.py"),
         "--mode", "preloaded", "--hands", "5000"],
        cwd=repo, capture_output=True, text=True, timeout=90, check=False,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    report = json.loads(child.stdout)
    assert report["success"], report
    assert report["mode"] == "preloaded"
    assert report["theme"] == "dark_lightgreen.xml"
    assert report["application_stylesheet_applied"]
    assert report["pid"] != report["parent_pid"]
    assert report["modules_present_before_preload"] == []
    assert "fpdb_3_legacy.GuiResultsViewer" in report["modules_present_before_click"]
    assert report["temporary_fixture_removed"]
    assert report["same_preloaded_wrapper_shown"]
    assert report["preload_data_ready_while_hidden"]
    assert report["preload_seconds"] > 0
    before, after = report["preload_snapshot"], report["final_snapshot"]
    assert before == after, "Showing the preloaded page queried/rebuilt or changed its data"
    assert after["loaded_hands"] == after["total_hands"] == 5000
    assert sum(after["period_hands"]) == 5000
    assert Decimal(after["profit"]) == Decimal(after["ev"]) == -800 * 5000
    assert after["stage_calls"]["query_worker"] == 1
    assert after["stage_calls"]["table_rebuild"] > 0
    assert len(after["graph_points"]) == 4
    assert all(points >= 2 for points in after["graph_points"])
    marks = report["milestones_from_click_seconds"]
    assert marks["data_ready"] <= marks["preload_end"] <= 0
    assert 0 <= marks["table_paint_complete"] <= marks["ready"]
    assert 0 <= marks["curve_paint_complete"] <= marks["graph_paint_complete"] <= marks["ready"]
    # Requested local "practically instant" budget; intentionally strict in CI too.
    assert report["seconds"]["total_readiness"] < 0.250, report


@pytest.mark.parametrize("profile", [False, True])
@pytest.mark.parametrize("mode", ["application", "launcher"])
def test_results_actual_application_click_before_preload_reaches_paints(profile, mode):
    """Keep production global hooks and startup around the real sidebar click."""
    repo = Path(__file__).resolve().parents[2]
    command = [sys.executable, str(repo / "tools/benchmark_results_loading.py"),
               "--mode", mode, "--hands", "5000"]
    if profile:
        command.append("--profile")
    child = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=120, check=False)
    assert child.returncode == 0, child.stdout + child.stderr
    report = json.loads(child.stdout)
    assert report["success"], report
    assert report["mode"] == mode
    assert report["application_entrypoint"] == "fpdb_3_legacy/fpdb.pyw"
    assert report["application_class"] == "fpdb"
    if mode == "launcher":
        assert_real_launcher(report, child.stderr, repo)
    assert report["pid"] != report["parent_pid"]
    assert report["temporary_fixture_removed"]
    assert report["config_and_database_isolated"]
    assert not report["desktop_settings"]
    assert not report["desktop_environment_preserved"]
    assert report["table_settings_isolated"]
    assert report["theme"] == "dark_lightgreen.xml"
    assert report["application_stylesheet_applied"]
    assert report["autoimport_gui_created"]
    assert "fpdb._start_background_auto_import" not in report["disabled_callbacks"]
    assert "GuiAutoImport._launch_hud" in report["disabled_callbacks"]
    assert "GuiAutoImport.start_swc_native_capture" in report["disabled_callbacks"]
    assert report["click_state"]["navigation_enabled"]
    assert not report["click_state"]["preload_data_ready"]
    assert report["modules_present_before_click"] == []
    assert report["loaded_hands"] == 5000
    assert report["table_rows"] > 0
    assert len(report["graph_points"]) == 4
    assert all(points > 1 for points in report["graph_points"])
    assert report["stage_calls"]["query_worker"] == 1
    marks = report["milestones_from_click_seconds"]
    assert marks["navigation_enabled"] <= 0 <= marks["tab_results_returned"]
    assert 0 <= marks["construct_start"] <= marks["construct_end"] <= marks["data_ready"]
    assert marks["data_ready"] <= marks["table_paint_complete"] <= marks["ready"]
    assert marks["data_ready"] <= marks["curve_paint_complete"] <= marks["graph_paint_complete"] <= marks["ready"]
    assert report["qt_event_counts"]["Paint"] > 0
    assert any("Results ready" in entry["message"] for entry in report["application_perf_logs"])
    # Preserve the entrypoint's legacy/package logging aliases for diagnosis.
    assert set(report["logging_module_aliases"]) == {"loggingFpdb", "fpdb_3_legacy.loggingFpdb"}
    assert report["profile_enabled"] == profile
    if profile:
        assert_application_profile(report, child.stderr, mode)
    else:
        assert report["seconds"]["qt_painted_readiness"] < .5, report["seconds"]


def assert_real_launcher(report, stderr, repo):
    assert report["launcher_entrypoint"] == "fpdb_3_legacy.legacy_launcher.main"
    assert report["launcher_main_module"] == "__main__"
    assert report["true_main_block"]
    assert Path(report["launcher_cwd"]) == repo / "fpdb_3_legacy"
    assert Path(report["launcher_sys_path_0"]) == repo / "fpdb_3_legacy"
    assert "FPDB launch identity:" in stderr
    assert "role='main'" in stderr


def assert_application_profile(report, stderr, mode):
    assert f"Results {mode}-startup-to-ready cProfile" in stderr
    assert report["profile"]["largest_cumulative"]
    assert report["profile"]["largest_self"]
    groups = report["profile"]["overhead_groups"]
    assert all(groups[name]["functions"] for name in
               ("tab_profiler_and_stalls", "qt_event_hooks", "logging", "benchmark"))
    assert any(row["function"] == "watch_ui_stalls" for row in groups["tab_profiler_and_stalls"]["functions"])
    if mode == "launcher":
        assert any(row["function"] == "main" and row["file"].endswith("legacy_launcher.py")
                   for row in report["profile"]["largest_cumulative"])


def test_results_application_reports_autoimport_isolation():
    repo = Path(__file__).resolve().parents[2]
    child = subprocess.run(
        [sys.executable, str(repo / "tools/benchmark_results_loading.py"),
         "--mode", "application", "--hands", "3", "--isolate-autoimport"],
        cwd=repo, capture_output=True, text=True, timeout=120, check=False,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    report = json.loads(child.stdout)
    assert report["success"]
    assert report["loaded_hands"] == 3
    assert "fpdb._start_background_auto_import" in report["disabled_callbacks"]
    assert not report["autoimport_gui_created"]
    assert not report["click_state"]["preload_data_ready"]


@pytest.mark.parametrize("mode", ["application", "launcher"])
def test_results_desktop_settings_preserves_desktop_but_never_writes_personal_fpdb(tmp_path, mode):
    """Use a fake desktop HOME with personal sentinels, never the test user's files."""
    home = tmp_path / "desktop-home"
    sentinels = {
        ".fpdb/HUD_config.xml": b"personal config must never be loaded",
        ".fpdb/themes/personal.xml": b"personal theme must never be rewritten",
        ".config/fpdb/table-columns.conf": b"[personal]\nwidth=777\n",
        ".qt_material/theme/primary/icon.svg": b"personal generated theme resource",
        "fpdb_logs/logger_config.json": json.dumps({
            "loggers": {"results_loading": {"level": 30, "enabled": True}},
        }).encode(),
    }
    for name, content in sentinels.items():
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    before = {path.relative_to(home): path.read_bytes() for path in home.rglob("*") if path.is_file()}
    environment = os.environ.copy()
    environment.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                       XDG_DATA_HOME=str(home / ".local/share"), XDG_CACHE_HOME=str(home / ".cache"))
    repo = Path(__file__).resolve().parents[2]
    child = subprocess.run(
        [sys.executable, str(repo / "tools/benchmark_results_loading.py"),
         "--mode", mode, "--hands", "3", "--desktop-settings"],
        cwd=repo, capture_output=True, text=True, timeout=120, check=False, env=environment,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    report = json.loads(child.stdout)
    assert report["success"]
    assert report["desktop_settings"]
    assert report["desktop_environment_preserved"]
    assert report["personal_logger_settings_copied"]
    assert report["desktop_environment_source_pid"] is None
    assert {"HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"}.issubset(report["desktop_environment_keys"])
    assert report["config_and_database_isolated"]
    assert report["table_settings_isolated"]
    fixture_root = Path(report["fpdb_config_root"]).parents[1]
    assert Path(report["table_settings_file"]).is_relative_to(fixture_root)
    assert Path(report["log_directory"]).is_relative_to(fixture_root)
    assert not fixture_root.is_relative_to(home)
    assert report["temporary_fixture_removed"]
    assert report["loaded_hands"] == 3
    after = {path.relative_to(home): path.read_bytes() for path in home.rglob("*") if path.is_file()}
    assert after == before, "Desktop mode changed or created a personal fpdb/settings/theme/log file"


def private_config_template(personal, repo):
    database = personal / "private.db3"
    database.write_bytes(b"not a public SQLite database; must never be opened")
    source = personal / "HUD_config.xml"
    tree = ET.parse(repo / "HUD_config.xml.example")
    document = tree.getroot()
    document.find("general").set("qt_material_theme", "light_amber.xml")
    document.find("general").set("benchmark_ui_option", "preserved")
    for site in document.iter("site"):
        site.set("screen_name", "PRIVATE-HERO-SENTINEL")
        site.set("HH_path", str(personal / "histories"))
        site.set("TS_path", str(personal / "summaries"))
        ET.SubElement(site, "hero_alias", name="PRIVATE-ALIAS-SENTINEL")
        if site.get("site_name") in ("PokerStars", "WinningPoker"):
            site.set("enabled", "True")
    profiles = ET.SubElement(document, "hero_profiles")
    hero = ET.SubElement(profiles, "hero_profile", name="PRIVATE-PROFILE-SENTINEL", default="True")
    ET.SubElement(hero, "link", site_name="PokerStars", alias="PRIVATE-ALIAS-SENTINEL")
    for node in document.iter("database"):
        node.set("db_path", str(personal))
        node.set("db_name", database.name)
        node.set("db_pass", "PRIVATE-PASSWORD-SENTINEL")
    extra = ET.SubElement(document, "benchmark_paths", log_file=str(personal / "private.log"),
                          HUDLogs=str(personal / "hud"), theme_dir=str(personal / "themes"),
                          relative_path="relative/history", username="PRIVATE-USER-SENTINEL",
                          password="PRIVATE-PASSWORD-SENTINEL")
    ET.SubElement(extra, "hero_aliases").text = "PRIVATE-ALIAS-SENTINEL"
    ET.SubElement(extra, "alias").text = "PRIVATE-ALIAS-SENTINEL"
    ET.SubElement(document.find("supported_databases"), "database", db_server="mysql",
                  db_name="PRIVATE-DB-SENTINEL", db_pass="PRIVATE-PASSWORD-SENTINEL")
    document.find("import").set("interval", "37")
    tree.write(source, encoding="utf-8", xml_declaration=True)
    return source


def assert_sanitized_template(clone, personal, fixture):
    from tools.benchmark_results_loading import config_path_field

    cloned = ET.parse(clone).getroot()
    xml = clone.read_text()
    assert "PRIVATE-" not in xml
    assert str(personal) not in xml
    assert cloned.find("general").get("benchmark_ui_option") == "preserved"
    assert cloned.find("general").get("qt_material_theme") == "light_amber.xml"
    assert cloned.find("import").get("interval") == "37"
    assert all(site.get("screen_name") == "Hero" for site in cloned.iter("site"))
    assert all(alias.get("name") == "Hero" for alias in cloned.iter("hero_alias"))
    assert cloned.find("benchmark_paths/hero_aliases").text == "Hero"
    assert cloned.find("benchmark_paths/alias").text == "Hero"
    assert next(site for site in cloned.iter("site") if site.get("site_name") == "WinningPoker").get("enabled") == "True"
    assert all(db.get("db_server") == "sqlite" and db.get("db_name") == "results-benchmark.db3"
               and Path(db.get("db_path")).is_relative_to(fixture) for db in cloned.iter("database"))
    for node in cloned.iter():
        for key, value in node.attrib.items():
            if config_path_field(key, value, node.tag):
                assert Path(value).is_relative_to(fixture), (node.tag, key)


def test_results_config_template_anonymizes_and_redirects_before_real_launcher(tmp_path):
    from tools.benchmark_results_loading import write_config

    repo = Path(__file__).resolve().parents[2]
    personal = tmp_path / "personal"
    personal.mkdir()
    source = private_config_template(personal, repo)
    before = {path: path.read_bytes() for path in personal.rglob("*") if path.is_file()}
    fixture = tmp_path / "sanitized"
    fixture.mkdir()
    assert_sanitized_template(write_config(fixture, source), personal, fixture)
    child = subprocess.run(
        [sys.executable, str(repo / "tools/benchmark_results_loading.py"),
         "--mode", "launcher", "--config-template", str(source), "--hands", "3"],
        cwd=repo, capture_output=True, text=True, timeout=120, check=False,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    report = json.loads(child.stdout)
    assert report["success"]
    assert report["true_main_block"]
    assert report["config_template_used"] and report["config_template_anonymized"]
    assert report["theme"] == "light_amber.xml"
    assert report["loaded_hands"] == 3
    assert report["config_and_database_isolated"]
    assert report["table_settings_isolated"]
    assert "PRIVATE-" not in child.stdout + child.stderr
    assert {path: path.read_bytes() for path in personal.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("click_during_import", [False, True], ids=["cold_startup", "fresh_under_load"])
def test_results_launcher_during_public_restart_autoimport_under_500ms(click_during_import):
    """Both prioritized cold startup and a fresh under-load widget stay responsive."""
    repo = Path(__file__).resolve().parents[2]
    command = [sys.executable, str(repo / "tools/benchmark_results_loading.py"),
               "--mode", "launcher", "--hands", "2000", "--monitored-hands", "2000", "--timeout", "90"]
    if click_during_import:
        command.append("--click-during-import")
    child = subprocess.run(
        command,
        cwd=repo, capture_output=True, text=True, timeout=150, check=False,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    report = json.loads(child.stdout)
    assert report["success"] and report["error"] is None
    assert report["true_main_block"]
    assert not report["click_state"]["preload_data_ready"]
    assert report["click_during_import"] == click_during_import
    if click_during_import:
        assert "fpdb_3_legacy.GuiResultsViewer" in report["modules_present_before_click"]
        assert report["startup_cached_results_discarded"]
        assert report["startup_cached_results_ready"]
        assert report["startup_stage_calls"]["query_worker"] == 1
        assert not report["click_state"]["preload_page_existed"]
    else:
        assert report["modules_present_before_click"] == []
        assert not report["startup_cached_results_discarded"]
    assert report["loaded_hands"] == 2000
    assert report["stage_calls"]["query_worker"] == 1
    assert_monitored_duplicates(report)
    assert_fresh_paint_sequence(report)
    assert_restart_scheduling(report, click_during_import)
    assert report["seconds"]["qt_painted_readiness"] < .5, {
        "seconds": report["seconds"], "autoimport": report["autoimport"],
    }


def assert_monitored_duplicates(report):
    observation = report["autoimport"]
    assert observation["monitored_hands"] == 2000
    assert observation["global_lock_files_isolated"]
    assert observation["first_cycle_completed"]
    assert observation["database_hands_after_cycle"] == 2000
    cycle = observation["cycles"][0]
    assert cycle["counts"] == dict(stored=0, duplicates=2000, partial=0, skipped=0, errors=0)
    assert cycle["new_hands"] == 0
    assert cycle["worker_cpu_seconds"] > 0
    assert cycle["end_from_click_seconds"] > cycle["start_from_click_seconds"]


def assert_fresh_paint_sequence(report):
    marks = report["milestones_from_click_seconds"]
    assert 0 <= marks["construct_start"] <= marks["construct_end"] <= marks["data_ready"]
    assert marks["data_ready"] <= marks["table_paint_complete"] <= marks["ready"]
    assert marks["data_ready"] <= marks["curve_paint_complete"] <= marks["graph_paint_complete"] <= marks["ready"]
    for label, spans in report["stage_spans_from_click_seconds"].items():
        assert all(0 <= span["start"] <= span["end"] for span in spans), label


def assert_restart_scheduling(report, click_during_import):
    observation = report["autoimport"]
    cycle = observation["cycles"][0]
    marks = report["milestones_from_click_seconds"]
    if click_during_import:
        assert observation["worker_running_at_click"]
        assert cycle["overlap_click_to_paints_seconds"] > 0
        assert cycle["overlap_with_results_stages_seconds"]["construct"] > 0
        assert cycle["end_from_click_seconds"] > marks["ready"]
        assert cycle["files"][0]["start_from_click_seconds"] < marks["construct_end"]
    else:
        assert not observation["worker_running_at_click"]
        assert cycle["start_from_click_seconds"] >= max(marks["table_paint_complete"], marks["graph_paint_complete"])
        assert cycle["overlap_click_to_paints_seconds"] == 0
        assert cycle["overlap_with_results_stages_seconds"]["import"] == 0
        assert cycle["overlap_with_results_stages_seconds"]["construct"] == 0
