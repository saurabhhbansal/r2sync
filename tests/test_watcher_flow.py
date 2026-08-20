"""Regression tests for the watcher -> debounce -> scheduler -> rclone event path.

These cover the bugs that made a newly created file fail to reach R2 even though
the watcher had noticed it.
"""

import struct
import threading
import time

import pytest

from r2sync.core.db import Database
from r2sync.core.models import SyncDataset, SyncScheduleMode, SyncStatus
from r2sync.core.sync_engine import SyncEngine
from r2sync.core.watcher import (
    FILE_ACTION_ADDED,
    FILE_ACTION_MODIFIED,
    FILE_ACTION_REMOVED,
    FILE_ACTION_RENAMED_NEW_NAME,
    FILE_ACTION_RENAMED_OLD_NAME,
    DebouncedWatcherManager,
    PollingDirectoryWatcher,
    parse_file_notify_information,
)


# ---------------------------------------------------------------------------
# FILE_NOTIFY_INFORMATION decoding (the Windows watcher's event source)
# ---------------------------------------------------------------------------

def _encode_notify_records(records):
    """Build a ReadDirectoryChangesW-shaped buffer from (action, name) pairs."""
    out = bytearray()
    offsets = []
    for action, name in records:
        name_bytes = name.encode("utf-16-le")
        entry = bytearray()
        entry += struct.pack("<III", 0, action, len(name_bytes))
        entry += name_bytes
        # Records are DWORD aligned.
        while len(entry) % 4:
            entry += b"\x00"
        offsets.append(len(out))
        out += entry

    # Patch NextEntryOffset on every record but the last.
    for idx, off in enumerate(offsets):
        next_off = 0 if idx == len(offsets) - 1 else offsets[idx + 1] - off
        struct.pack_into("<I", out, off, next_off)
    return bytes(out)


def test_parse_file_notify_information_all_actions():
    records = [
        (FILE_ACTION_ADDED, "new file.txt"),
        (FILE_ACTION_MODIFIED, "sub dir\\report.docx"),
        (FILE_ACTION_REMOVED, "gone.bin"),
        (FILE_ACTION_RENAMED_OLD_NAME, "old.txt"),
        (FILE_ACTION_RENAMED_NEW_NAME, "new.txt"),
    ]
    buf = _encode_notify_records(records)
    parsed = parse_file_notify_information(buf, len(buf))

    assert parsed == [
        (FILE_ACTION_ADDED, "new file.txt"),
        (FILE_ACTION_MODIFIED, "sub dir/report.docx"),
        (FILE_ACTION_REMOVED, "gone.bin"),
        (FILE_ACTION_RENAMED_OLD_NAME, "old.txt"),
        (FILE_ACTION_RENAMED_NEW_NAME, "new.txt"),
    ]


def test_parse_file_notify_information_unicode_and_spaces():
    name = "Projets Été/résumé final (v2).pdf".replace("/", "\\")
    buf = _encode_notify_records([(FILE_ACTION_ADDED, name)])
    parsed = parse_file_notify_information(buf, len(buf))
    assert parsed == [(FILE_ACTION_ADDED, "Projets Été/résumé final (v2).pdf")]


def test_parse_file_notify_information_handles_overflow_and_garbage():
    # A zero-byte read is how Windows signals a dropped/overflowed buffer.
    assert parse_file_notify_information(b"", 0) == []
    # A truncated record must not raise; it is simply ignored.
    buf = _encode_notify_records([(FILE_ACTION_ADDED, "truncated.txt")])
    assert parse_file_notify_information(buf, 8) == []


# ---------------------------------------------------------------------------
# Debounce + watcher lifecycle
# ---------------------------------------------------------------------------

def test_ensure_watching_preserves_pending_change(tmp_path):
    """A sync finishing must not cancel a change made while it was running.

    ``_run_sync_worker`` re-attaches the watcher after every sync. When that
    used ``start_watching`` it tore the watcher down and cancelled the debounce
    timer that was holding the user's change, losing it permanently.
    """
    fired = []
    mgr = DebouncedWatcherManager(
        on_change_triggered=fired.append, debounce_seconds=0.4, supervise=False
    )
    folder = tmp_path / "data"
    folder.mkdir()

    assert mgr.start_watching("ds", str(folder))
    mgr._on_raw_change("ds")
    assert mgr.has_pending_change("ds")

    # Simulate the end-of-sync re-attach.
    assert mgr.ensure_watching("ds", str(folder))
    assert mgr.has_pending_change("ds"), "the pending change was cancelled"

    time.sleep(0.8)
    assert fired == ["ds"]
    mgr.stop_all()


def test_ensure_watching_is_noop_for_live_watcher(tmp_path):
    mgr = DebouncedWatcherManager(on_change_triggered=lambda d: None, supervise=False)
    folder = tmp_path / "data"
    folder.mkdir()

    mgr.start_watching("ds", str(folder))
    first = mgr._watchers["ds"]
    mgr.ensure_watching("ds", str(folder))
    assert mgr._watchers["ds"] is first
    mgr.stop_all()


def test_ensure_watching_restarts_when_target_changed(tmp_path):
    mgr = DebouncedWatcherManager(on_change_triggered=lambda d: None, supervise=False)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()

    mgr.start_watching("ds", str(a))
    first = mgr._watchers["ds"]
    mgr.ensure_watching("ds", str(b))
    assert mgr._watchers["ds"] is not first
    assert mgr._registrations["ds"]["folder_path"] == str(b)
    mgr.stop_all()


def test_missing_folder_is_registered_and_picked_up_later(tmp_path):
    """A drive that is not mounted yet must not silently lose its watcher."""
    mgr = DebouncedWatcherManager(on_change_triggered=lambda d: None, supervise=False)
    folder = tmp_path / "not-mounted-yet"

    assert mgr.start_watching("ds", str(folder)) is False
    assert "ds" in mgr._registrations
    assert mgr.is_watching("ds") is False

    folder.mkdir()
    revived = mgr.check_health()
    assert revived == ["ds"]
    assert mgr.is_watching("ds")
    mgr.stop_all()


def test_supervisor_revives_a_dead_watcher(tmp_path):
    fired = []
    mgr = DebouncedWatcherManager(
        on_change_triggered=fired.append, debounce_seconds=0.1, supervise=False
    )
    folder = tmp_path / "data"
    folder.mkdir()
    mgr.start_watching("ds", str(folder))

    # Kill the watcher thread the way a native watcher failure would.
    mgr._watchers["ds"].stop()
    assert mgr.is_watching("ds") is False

    assert mgr.check_health() == ["ds"]
    assert mgr.is_watching("ds")

    # A watcher that was down means changes were missed, so a reconcile fires.
    deadline = time.time() + 5
    while time.time() < deadline and not fired:
        time.sleep(0.05)
    assert fired == ["ds"]
    mgr.stop_all()


def test_native_watcher_failure_falls_back_to_polling(tmp_path):
    """A dead native watcher must degrade to polling, not to no watching at all."""
    mgr = DebouncedWatcherManager(on_change_triggered=lambda d: None, supervise=False)
    folder = tmp_path / "data"
    folder.mkdir()
    mgr.start_watching("ds", str(folder))

    mgr._on_watcher_failed("ds", "simulated ReadDirectoryChangesW failure")

    assert mgr._registrations["ds"]["force_polling"] is True
    assert isinstance(mgr._watchers["ds"], PollingDirectoryWatcher)
    assert mgr.is_watching("ds")
    mgr.stop_all()


def test_polling_watcher_detects_create_modify_delete_and_rename(tmp_path):
    events = threading.Semaphore(0)
    fired = []

    def on_change(ds):
        fired.append(ds)
        events.release()

    folder = tmp_path / "Mes Documents"
    folder.mkdir()
    (folder / "seed.txt").write_text("seed")

    watcher = PollingDirectoryWatcher("ds", str(folder), on_change, poll_interval=0.15)
    watcher.start()
    try:
        # create
        (folder / "nouveau fichier.txt").write_text("bonjour")
        assert events.acquire(timeout=3), "create was not detected"

        # modify (same size, new content, so mtime+size keying matters)
        time.sleep(0.05)
        (folder / "nouveau fichier.txt").write_text("au revoir")
        assert events.acquire(timeout=3), "modify was not detected"

        # rename
        (folder / "nouveau fichier.txt").rename(folder / "renommé.txt")
        assert events.acquire(timeout=3), "rename was not detected"

        # delete
        (folder / "renommé.txt").unlink()
        assert events.acquire(timeout=3), "delete was not detected"
    finally:
        watcher.stop()


def test_polling_watcher_notices_same_mtime_size_change(tmp_path):
    """Snapshot keys on (mtime, size); a size change alone must still register."""
    folder = tmp_path / "d"
    folder.mkdir()
    target = folder / "f.bin"
    target.write_bytes(b"a" * 10)

    watcher = PollingDirectoryWatcher("ds", str(folder), lambda d: None, poll_interval=5)
    snap1 = watcher._snapshot()

    import os
    st = target.stat()
    target.write_bytes(b"a" * 20)
    os.utime(target, (st.st_atime, st.st_mtime))  # restore the original mtime

    assert watcher._snapshot() != snap1


def test_rapid_successive_changes_coalesce_into_one_sync():
    fired = []
    # The debounce window is comfortably longer than the burst so this stays
    # deterministic on a slow CI runner.
    mgr = DebouncedWatcherManager(
        on_change_triggered=fired.append, debounce_seconds=2.0, supervise=False
    )
    for _ in range(50):
        mgr._on_raw_change("ds")
        time.sleep(0.005)
    assert fired == [], "the burst fired before it had finished coalescing"
    time.sleep(2.6)
    assert fired == ["ds"]
    mgr.stop_all()


# ---------------------------------------------------------------------------
# SyncEngine queueing
# ---------------------------------------------------------------------------

@pytest.fixture
def engine(tmp_path):
    db = Database(db_path=tmp_path / "t.sqlite")
    local = tmp_path / "folder"
    local.mkdir()
    db.create_sync_dataset(SyncDataset(
        dataset_id="ds1",
        name="Docs",
        bucket_name="bkt",
        local_path=str(local),
        schedule_mode=SyncScheduleMode.REALTIME.value,
        status=SyncStatus.WAITING.value,
    ))
    eng = SyncEngine(db=db)
    yield eng
    eng.stop_all_watchers()
    db.close()


def test_change_during_sync_is_queued_not_dropped(engine, monkeypatch):
    """The headline bug: a file created mid-sync used to be discarded."""
    started = threading.Event()
    release = threading.Event()
    runs = []

    def fake_execute(dataset, resync_mode, force_resync):
        runs.append(dataset.dataset_id)
        started.set()
        release.wait(timeout=5)
        return {"success": True, "files_transferred": 1}

    monkeypatch.setattr(engine, "_execute_sync", fake_execute)

    assert engine.trigger_sync_async("ds1") is True
    assert started.wait(timeout=3)

    # The watcher fires while the first sync is still running.
    assert engine.trigger_sync_async("ds1") is False
    assert engine.has_pending_sync("ds1")

    release.set()
    deadline = time.time() + 5
    while time.time() < deadline and len(runs) < 2:
        time.sleep(0.05)

    assert len(runs) == 2, "the mid-sync change never produced a follow-up sync"


def test_only_one_sync_per_dataset_runs_at_a_time(engine, monkeypatch):
    concurrent = []
    peak = []
    lock = threading.Lock()
    release = threading.Event()

    def fake_execute(dataset, resync_mode, force_resync):
        with lock:
            concurrent.append(1)
            peak.append(len(concurrent))
        release.wait(timeout=5)
        with lock:
            concurrent.pop()
        return {"success": True}

    monkeypatch.setattr(engine, "_execute_sync", fake_execute)

    accepted = [engine.trigger_sync_async("ds1") for _ in range(8)]
    time.sleep(0.3)
    release.set()
    time.sleep(0.5)

    assert accepted.count(True) == 1
    assert max(peak) == 1


def test_queued_followup_keeps_the_strongest_request(engine, monkeypatch):
    """A coalesced follow-up must not weaken a force_resync into a normal run."""
    started = threading.Event()
    release = threading.Event()
    calls = []

    def fake_execute(dataset, resync_mode, force_resync):
        calls.append((resync_mode, force_resync))
        started.set()
        release.wait(timeout=5)
        return {"success": True}

    monkeypatch.setattr(engine, "_execute_sync", fake_execute)

    engine.trigger_sync_async("ds1")
    assert started.wait(timeout=3)
    engine.trigger_sync_async("ds1")                                   # plain
    engine.trigger_sync_async("ds1", resync_mode="path2", force_resync=True)

    release.set()
    deadline = time.time() + 5
    while time.time() < deadline and len(calls) < 2:
        time.sleep(0.05)

    assert calls[1] == ("path2", True)


def test_worker_exception_does_not_wedge_the_dataset(engine, monkeypatch):
    """One failure used to block every future sync of that dataset forever."""
    calls = []

    def boom(dataset, resync_mode, force_resync):
        calls.append("boom")
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(engine, "_execute_sync", boom)
    engine.trigger_sync_async("ds1")
    time.sleep(0.5)

    assert engine.is_dataset_syncing("ds1") is False

    monkeypatch.setattr(
        engine, "_execute_sync", lambda d, r, f: calls.append("ok") or {"success": True}
    )
    engine.trigger_sync_async("ds1")
    time.sleep(0.5)

    assert calls == ["boom", "ok"]


def test_offline_defers_the_dataset_for_the_scheduler(engine, monkeypatch):
    """Being offline must schedule a retry, not silently give up."""
    monkeypatch.setattr("r2sync.core.sync_engine.check_internet_connection", lambda: False)
    monkeypatch.setattr(
        "r2sync.core.sync_engine.get_r2_credentials",
        lambda: type("C", (), {"access_key_id": "a", "secret_access_key": "b"})(),
    )

    engine.trigger_sync_async("ds1")
    time.sleep(0.5)

    assert engine.is_dataset_syncing("ds1") is False
    assert "ds1" in engine.take_deferred_syncs()
    # take_* drains the queue so the scheduler does not retry endlessly.
    assert engine.take_deferred_syncs() == []


def test_cancelling_a_sync_does_not_immediately_restart_it(engine, monkeypatch):
    """Cancel must beat the new coalescing queue, or it would look like a no-op."""
    started = threading.Event()
    release = threading.Event()
    runs = []

    def fake_execute(dataset, resync_mode, force_resync):
        runs.append(1)
        started.set()
        release.wait(timeout=5)
        return {"success": False, "error_message": "canceled"}

    monkeypatch.setattr(engine, "_execute_sync", fake_execute)
    monkeypatch.setattr(engine.rclone_engine, "cancel_bisync", lambda ds: True)

    engine.trigger_sync_async("ds1")
    assert started.wait(timeout=3)

    engine.trigger_sync_async("ds1")          # a change lands mid-sync
    assert engine.has_pending_sync("ds1")

    engine.cancel_sync("ds1")                 # ...then the user cancels
    assert engine.has_pending_sync("ds1") is False

    release.set()
    time.sleep(0.8)
    assert len(runs) == 1, "the cancelled sync was restarted anyway"
    assert engine.is_dataset_syncing("ds1") is False
    # The cancel flag is cleared, so the next explicit request still works.
    assert engine.is_cancel_requested("ds1") is False


def test_concurrent_dataset_syncs_are_capped(tmp_path, monkeypatch):
    """Service startup queues every dataset at once; they must not all run together."""
    db = Database(db_path=tmp_path / "many.sqlite")
    folder = tmp_path / "f"
    folder.mkdir()
    for i in range(6):
        db.create_sync_dataset(SyncDataset(
            dataset_id=f"ds{i}", name=f"n{i}", bucket_name="b",
            local_path=str(folder), schedule_mode=SyncScheduleMode.REALTIME.value,
        ))

    engine = SyncEngine(db=db)
    release = threading.Event()
    live = []
    peak = []
    lock = threading.Lock()

    def fake_execute(dataset, resync_mode, force_resync):
        with lock:
            live.append(dataset.dataset_id)
            peak.append(len(live))
        release.wait(timeout=5)
        with lock:
            live.remove(dataset.dataset_id)
        return {"success": True}

    monkeypatch.setattr(engine, "_execute_sync", fake_execute)
    try:
        started = [engine.trigger_sync_async(f"ds{i}") for i in range(6)]
        time.sleep(0.4)

        assert max(peak) <= engine.max_concurrent_syncs
        assert started.count(True) == engine.max_concurrent_syncs

        # The ones held back are deferred, not lost: the scheduler retries them.
        deferred = engine.take_deferred_syncs()
        assert len(deferred) == 6 - engine.max_concurrent_syncs

        release.set()
        time.sleep(0.5)
    finally:
        release.set()
        engine.stop_all_watchers()
        db.close()
