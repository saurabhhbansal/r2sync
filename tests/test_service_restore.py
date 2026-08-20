"""Regression tests for sync state surviving a service (or Windows) restart."""

import os
import sys
from unittest.mock import patch

import pytest

from r2sync.core.db import Database
from r2sync.core.models import SyncDataset, SyncScheduleMode, SyncStatus
from r2sync.core.sync_engine import SyncEngine


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    monkeypatch.setenv("R2SYNC_DATA_DIR", str(tmp_path / "appdata"))
    from r2sync.service.daemon import ServiceDaemon

    # Building a ServiceDaemon binds an IPC port and may fetch rclone; only the
    # dataset-restoration logic is under test here.
    with patch("r2sync.service.ipc_server.IPCServer.start"), \
         patch("r2sync.service.ipc_server.IPCServer.stop"):
        d = ServiceDaemon()
        yield d
        d.sync_engine.stop_all_watchers()


def _make(db, tmp_path, **kw):
    folder = tmp_path / kw.pop("folder", "shared")
    if kw.pop("create_folder", True):
        folder.mkdir(parents=True, exist_ok=True)
    ds = SyncDataset(
        dataset_id=kw.pop("dataset_id", "ds1"),
        name=kw.pop("name", "Shared"),
        bucket_name="bkt",
        local_path=str(folder),
        schedule_mode=kw.pop("schedule_mode", SyncScheduleMode.REALTIME.value),
        **kw,
    )
    db.create_sync_dataset(ds)
    return ds


def test_enabled_realtime_datasets_get_their_watchers_back(daemon, tmp_path):
    _make(daemon.db, tmp_path, dataset_id="ds1", folder="Docs partagés")
    _make(daemon.db, tmp_path, dataset_id="ds2", name="Photos", folder="Photos")

    assert daemon.restore_sync_state() == 2
    assert daemon.sync_engine.watcher_manager.is_watching("ds1")
    assert daemon.sync_engine.watcher_manager.is_watching("ds2")


def test_paused_and_disabled_datasets_are_not_watched(daemon, tmp_path):
    _make(daemon.db, tmp_path, dataset_id="ds-paused", folder="p", paused=True)
    _make(daemon.db, tmp_path, dataset_id="ds-off", folder="o", enabled=False)
    _make(daemon.db, tmp_path, dataset_id="ds-manual", folder="m",
          schedule_mode=SyncScheduleMode.MANUAL.value)

    assert daemon.restore_sync_state() == 0
    for ds_id in ("ds-paused", "ds-off", "ds-manual"):
        assert daemon.sync_engine.watcher_manager.is_watching(ds_id) is False


def test_restore_queues_a_reconcile_for_changes_made_while_down(daemon, tmp_path):
    """Edits made while the service was stopped are invisible to a new watcher."""
    _make(daemon.db, tmp_path, dataset_id="ds1")
    _make(daemon.db, tmp_path, dataset_id="ds2", name="B", folder="b",
          schedule_mode=SyncScheduleMode.INTERVAL.value)

    daemon.restore_sync_state()
    assert sorted(daemon.sync_engine.take_deferred_syncs()) == ["ds1", "ds2"]


def test_dataset_stuck_in_syncing_is_reset_on_start(daemon, tmp_path):
    """A crash mid-sync must not leave the dataset permanently 'syncing'."""
    _make(daemon.db, tmp_path, dataset_id="ds1", status=SyncStatus.SYNCING.value)

    daemon.restore_sync_state()

    assert daemon.db.get_sync_dataset("ds1").status == SyncStatus.WAITING.value


def test_unavailable_folder_is_registered_for_later_attachment(daemon, tmp_path):
    """Network/removable drive not mounted yet at boot: keep the registration."""
    _make(daemon.db, tmp_path, dataset_id="ds1", folder="Z-drive", create_folder=False)

    assert daemon.restore_sync_state() == 0
    mgr = daemon.sync_engine.watcher_manager
    assert "ds1" in mgr._registrations
    assert mgr.is_watching("ds1") is False

    # The drive appears; the supervisor attaches without any user action.
    os.makedirs(daemon.db.get_sync_dataset("ds1").local_path, exist_ok=True)
    assert mgr.check_health() == ["ds1"]
    assert mgr.is_watching("ds1")


def test_restore_is_idempotent_across_repeated_starts(daemon, tmp_path):
    _make(daemon.db, tmp_path, dataset_id="ds1")

    assert daemon.restore_sync_state() == 1
    assert daemon.restore_sync_state() == 1
    assert daemon.sync_engine.watcher_manager.is_watching("ds1")
    # A second start replaces rather than duplicates the watcher.
    assert len(daemon.sync_engine.watcher_manager._watchers) == 1


def test_start_all_watchers_covers_every_eligible_dataset(tmp_path):
    db = Database(db_path=tmp_path / "s.sqlite")
    folder = tmp_path / "f"
    folder.mkdir()
    for i in range(3):
        db.create_sync_dataset(SyncDataset(
            dataset_id=f"ds{i}", name=f"n{i}", bucket_name="b",
            local_path=str(folder), schedule_mode=SyncScheduleMode.REALTIME.value,
        ))

    eng = SyncEngine(db=db)
    try:
        assert eng.start_all_watchers() == 3
        assert all(eng.watcher_manager.is_watching(f"ds{i}") for i in range(3))
    finally:
        eng.stop_all_watchers()
        db.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry only")
def test_service_autostart_round_trip():
    from r2sync.utils.system import (
        get_windows_service_autostart,
        set_windows_service_autostart,
    )

    original = get_windows_service_autostart()
    try:
        assert set_windows_service_autostart(True)
        assert get_windows_service_autostart() is True
        assert set_windows_service_autostart(False)
        assert get_windows_service_autostart() is False
    finally:
        set_windows_service_autostart(original)


def test_service_executable_resolution_points_at_the_service():
    from r2sync.utils.system import get_service_executable

    cmd = get_service_executable()
    assert cmd[-1] == "--standalone"
    joined = " ".join(cmd)
    assert "r2sync-service" in joined or "r2sync.service.main" in joined


def test_sync_resumes_when_the_network_arrives_after_boot(tmp_path, monkeypatch):
    """Cold boot often reaches the service before the NIC is up.

    The engine defers the dataset instead of giving up, and the scheduler
    retries it on the next tick, so no user action is needed once the link
    comes back.
    """
    import threading
    import time

    from r2sync.core.scheduler import JobScheduler

    folder = tmp_path / "shared"
    folder.mkdir()
    db = Database(db_path=tmp_path / "n.sqlite")
    db.create_sync_dataset(SyncDataset(
        dataset_id="ds1", name="Shared", bucket_name="bkt", local_path=str(folder),
        schedule_mode=SyncScheduleMode.REALTIME.value, initial_sync_done=True,
    ))

    online = threading.Event()
    monkeypatch.setattr(
        "r2sync.core.sync_engine.check_internet_connection", lambda: online.is_set()
    )
    monkeypatch.setattr(
        "r2sync.core.sync_engine.get_r2_credentials",
        lambda: type("C", (), {"access_key_id": "a", "secret_access_key": "b"})(),
    )
    monkeypatch.setattr(
        "r2sync.core.rclone_engine.RcloneBinaryManager.is_installed", lambda: True
    )

    engine = SyncEngine(db=db)
    # Stub only the transfer itself, so the real offline pre-check still runs.
    transfers = []
    monkeypatch.setattr(
        engine.rclone_engine, "run_bisync",
        lambda **kw: transfers.append(kw["dataset"].dataset_id) or {"success": True},
    )
    monkeypatch.setattr(engine.rclone_engine, "upload_dataset_metadata", lambda *a, **k: True)
    monkeypatch.setattr(engine.rclone_engine, "register_remote_device", lambda *a, **k: True)

    sched = JobScheduler(
        db=db,
        job_runner_cb=lambda j: None,
        sync_runner_cb=engine.trigger_sync_async,
        deferred_provider=engine.take_deferred_syncs,
    )

    try:
        # Boot while the network is still down.
        engine.trigger_sync_async("ds1")
        time.sleep(0.5)
        assert transfers == [], "no transfer should be attempted while offline"
        assert db.get_sync_dataset("ds1").status == SyncStatus.OFFLINE.value
        assert "ds1" in engine._deferred_syncs

        # Network arrives; the next scheduler tick picks the dataset back up
        # without any filesystem change or user action.
        online.set()
        sched._tick()
        time.sleep(0.8)

        assert transfers == ["ds1"]
        assert db.get_sync_dataset("ds1").status == SyncStatus.SYNCED.value
    finally:
        engine.stop_all_watchers()
        db.close()
