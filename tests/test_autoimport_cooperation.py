"""Real monitored imports cooperate without changing transactions or offsets."""

import sqlite3
from pathlib import Path
from threading import Lock, get_ident
from types import SimpleNamespace

import pytest
from PySide6.QtTest import QSignalSpy

from fpdb_3_legacy import GuiAutoImport
from fpdb_3_legacy.GuiAutoImport import AutoImportThread

pytestmark = pytest.mark.qt


@pytest.fixture
def public_history(importer, legacy_config, tmp_path):
    for site in legacy_config.supported_sites.values():
        site.enabled = False
    site = legacy_config.supported_sites["PokerStars"]
    site.enabled = True
    site.screen_name = "Hero"
    original = (Path(__file__).parent / "fixtures/hands/pokerstars/review/nl_3bet_6max.txt").read_text()
    folder = tmp_path / "HandHistory"
    folder.mkdir()
    source = folder / "HH20261011.txt"
    source.write_text("\n\n".join(original.replace("2810000001", str(2810000001 + i)) for i in range(17)))
    importer.setMode("auto")
    importer.caller = SimpleNamespace(addText=lambda *_args: None)
    importer.setCallHud(False)
    return folder, source, original


def run_worker(qtbot, importer, lock=None):
    worker = AutoImportThread(importer, db_write_lock=lock)
    errors = QSignalSpy(worker.error)
    worker.start()
    try:
        qtbot.waitUntil(worker.isFinished, timeout=10000)
        assert errors.count() == 0, errors.at(0) if errors.count() else None
        return worker.new_hands
    finally:
        assert worker.wait(10000)


def test_gui_path_registration_defers_identification_until_worker(
    qtbot, monkeypatch, importer, fresh_db, public_history,
):
    folder, source, _ = public_history
    gui_thread = get_ident()
    walks, reads = [], []
    original_walk = GuiAutoImport.Importer.os.walk
    original_identify = importer.idsite.processFile

    def walk(*args, **kwargs):
        walks.append(get_ident())
        return original_walk(*args, **kwargs)

    def identify(path):
        reads.append((path, get_ident()))
        return original_identify(path)

    monkeypatch.setattr(GuiAutoImport.Importer.os, "walk", walk)
    monkeypatch.setattr(importer.idsite, "processFile", identify)
    gui = SimpleNamespace(
        doAutoImportBool=True,
        config=SimpleNamespace(reload=lambda: None),
        importer=importer,
        _configured_import_directories=lambda: {("PokerStars", "hh"): str(folder)},
        addText=lambda *_args: None,
    )
    GuiAutoImport.GuiAutoImport.updatePaths(gui)
    assert importer.dirlist[("PokerStars", "hh")][0] == str(folder)
    assert not importer.filelist
    assert walks == reads == []
    assert run_worker(qtbot, importer) == 17
    assert fresh_db.getHandCount() == 17
    assert walks and all(thread != gui_thread for thread in walks)
    assert reads == [(str(source), walks[0])]
    assert importer.cooperative_callback is None


@pytest.fixture
def replay_observation(monkeypatch, importer, fresh_db, public_history):
    folder, source, original = public_history
    assert importer.addImportFile(str(source))
    assert importer._import_despatch(importer.filelist[str(source)])[0] == 17
    assert fresh_db.getHandCount() == 17
    # A fresh-launch replay has no saved sizes or character positions.
    importer.clearFileList()
    importer.addImportDirectory(str(folder), monitor=True, site=("PokerStars", "hh"), defer_scan=True)
    importer.setFakeCacheHHC(True)
    lock = Lock()
    gui_thread = get_ident()
    sleeps = []
    previous_calls = []
    previous = lambda: previous_calls.append(get_ident())
    importer.cooperative_callback = previous
    original_sleep = GuiAutoImport.time.sleep

    def sleep(seconds):
        if get_ident() != gui_thread:
            sleeps.append((seconds, importer.database._in_transaction, lock.locked()))
        original_sleep(seconds)

    monkeypatch.setattr(GuiAutoImport.time, "sleep", sleep)
    commits, batches = [], []
    original_commit = importer.database.commit

    def commit(force=False):
        depth = importer.database._in_transaction
        if force or depth == 0:
            commits.append(depth)
        return original_commit(force=force)

    monkeypatch.setattr(importer.database, "commit", commit)
    original_import = importer._import_hh_file

    def import_hh(fpdbfile):
        start = len(commits)
        result = original_import(fpdbfile)
        batches.append((result[:2], commits[start:]))
        return result

    monkeypatch.setattr(importer, "_import_hh_file", import_hh)
    hud = []

    def send_hand_id(hand_id):
        assert importer.database._in_transaction == 0
        # Independent reader must see the hand before the HUD is notified.
        with sqlite3.connect(fresh_db.db_path) as reader:
            assert reader.execute("SELECT id FROM Hands WHERE id=?", (hand_id,)).fetchone() == (hand_id,)
        hud.append(hand_id)

    importer.zmq_sender = SimpleNamespace(send_hand_id=send_hand_id)
    importer.setCallHud(True)
    try:
        yield SimpleNamespace(
            source=source, original=original, lock=lock, sleeps=sleeps,
            previous=previous, previous_calls=previous_calls, hud=hud, batches=batches,
        )
    finally:
        importer.setCallHud(False)
        importer.zmq_sender = None


def test_worker_duplicate_replay_yields_and_resumes_without_intermediate_commit(
    qtbot, importer, fresh_db, replay_observation,
):
    observed = replay_observation
    source = observed.source
    assert run_worker(qtbot, importer, observed.lock) == 0
    assert fresh_db.getHandCount() == 17
    assert observed.hud == []
    assert observed.sleeps and all(seconds == .001 and held for seconds, _, held in observed.sleeps)
    assert any(depth > 0 for _, depth, _ in observed.sleeps)
    assert importer.cooperative_callback is observed.previous
    assert observed.previous_calls == []
    hhc = importer.getCachedHHC(str(source))
    assert hhc.numHands == 17
    assert hhc.cooperative_callback is not None and hhc.cooperative_callback is not observed.previous
    offset = importer.pos_in_file[str(source)]
    assert offset == hhc.getLastCharacterRead() and offset > 0
    # Enough appended hands to exercise cooperation in all insertion loops.
    with source.open("a") as stream:
        stream.write("\n\n" + "\n\n".join(
            observed.original.replace("2810000001", str(2810000001 + i)) for i in range(17, 34)
        ))
    assert run_worker(qtbot, importer, observed.lock) == 17
    assert fresh_db.getHandCount() == 34 and len(observed.hud) == 17
    assert importer.getCachedHHC(str(source)).numHands == 17
    resumed = importer.pos_in_file[str(source)]
    assert resumed > offset
    assert run_worker(qtbot, importer, observed.lock) == 0
    assert importer.pos_in_file[str(source)] == resumed
    assert fresh_db.getHandCount() == 34 and len(observed.hud) == 17
    assert importer.cooperative_callback is observed.previous
    # Both the duplicate-only replay and appended-hand batch stay atomic.
    assert observed.batches == [((0, 17), [0]), ((17, 0), [0])]


@pytest.mark.parametrize("failure", ["offline", "error"])
def test_worker_restores_callback_and_writer_lock_on_early_exit(qtbot, monkeypatch, importer, failure):
    previous = lambda: None
    importer.cooperative_callback = previous
    lock = Lock()
    if failure == "offline":
        monkeypatch.setattr(importer.database, "ensure_connection", lambda: False)
    else:
        def fail():
            raise ValueError("cycle failed")

        monkeypatch.setattr(importer, "autoSummaryGrab", fail)
    worker = AutoImportThread(importer, db_write_lock=lock)
    signal = worker.db_offline if failure == "offline" else worker.error
    with qtbot.waitSignal(signal, timeout=10000):
        worker.start()
    assert worker.wait(10000)
    assert importer.cooperative_callback is previous
    assert not lock.locked()
