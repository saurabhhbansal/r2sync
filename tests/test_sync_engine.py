"""Unit tests for Multi-PC Sync models, database operations, and SyncEngine."""

import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from r2sync.core.db import Database
from r2sync.core.models import (
    ConflictResolution,
    Device,
    RemoteDatasetInfo,
    SyncConflict,
    SyncDataset,
    SyncScheduleMode,
    SyncStatus,
)
from r2sync.core.sync_engine import SyncEngine, check_paths_overlap


@pytest.fixture
def db_fixture(tmp_path):
    db_file = tmp_path / "test_sync.db"
    db = Database(db_path=db_file)
    yield db
    db.close()


def test_device_identity_generation(db_fixture):
    dev_id1 = db_fixture.get_or_create_device_id()
    assert len(dev_id1) >= 16

    # Subsequent call returns identical ID
    dev_id2 = db_fixture.get_or_create_device_id()
    assert dev_id1 == dev_id2

    # Device Name customization
    default_name = db_fixture.get_device_name()
    assert len(default_name) > 0

    db_fixture.set_device_name("Gaming-Rig")
    assert db_fixture.get_device_name() == "Gaming-Rig"


def test_sync_dataset_crud(db_fixture):
    dataset = SyncDataset(
        dataset_id="test-dataset-1234",
        name="Work Documents",
        bucket_name="my-sync-bucket",
        remote_prefix="r2sync/v1/datasets/test-dataset-1234",
        local_path="/tmp/work_docs",
        schedule_mode=SyncScheduleMode.REALTIME.value,
        schedule_interval_minutes=15,
        max_delete_threshold=50,
        status=SyncStatus.WAITING.value,
    )

    created_id = db_fixture.create_sync_dataset(dataset)
    assert created_id == "test-dataset-1234"

    fetched = db_fixture.get_sync_dataset("test-dataset-1234")
    assert fetched is not None
    assert fetched.name == "Work Documents"
    assert fetched.bucket_name == "my-sync-bucket"
    assert fetched.schedule_mode == "realtime"

    # Update status
    db_fixture.update_sync_status(
        dataset_id="test-dataset-1234",
        status=SyncStatus.SYNCED.value,
        total_files=42,
        total_bytes=1048576,
    )

    updated = db_fixture.get_sync_dataset("test-dataset-1234")
    assert updated.status == SyncStatus.SYNCED.value
    assert updated.total_files == 42
    assert updated.total_bytes == 1048576

    # List datasets
    all_datasets = db_fixture.list_sync_datasets()
    assert len(all_datasets) == 1

    # Delete dataset
    assert db_fixture.delete_sync_dataset("test-dataset-1234") is True
    assert db_fixture.get_sync_dataset("test-dataset-1234") is None


def test_sync_devices_management(db_fixture):
    dev1 = Device(
        device_id="dev-desktop-1",
        device_name="Desktop-PC",
        dataset_id="dataset-abc",
        is_current_device=True,
        status="online",
    )
    dev2 = Device(
        device_id="dev-laptop-2",
        device_name="Laptop",
        dataset_id="dataset-abc",
        is_current_device=False,
        status="online",
    )

    db_fixture.upsert_sync_device(dev1)
    db_fixture.upsert_sync_device(dev2)

    devices = db_fixture.list_sync_devices("dataset-abc")
    assert len(devices) == 2

    # Update heartbeat
    db_fixture.update_device_heartbeat("dev-laptop-2", "dataset-abc", "syncing")
    devices = db_fixture.list_sync_devices("dataset-abc")
    lap = next(d for d in devices if d.device_id == "dev-laptop-2")
    assert lap.status == "syncing"

    # Delete device
    db_fixture.delete_sync_device("dev-laptop-2", "dataset-abc")
    devices = db_fixture.list_sync_devices("dataset-abc")
    assert len(devices) == 1


def test_folder_overlap_detection(db_fixture):
    # Test path overlap utility
    assert check_paths_overlap("/home/user/docs", "/home/user/docs") is True
    assert check_paths_overlap("/home/user/docs", "/home/user/docs/sub") is True
    assert check_paths_overlap("/home/user/docs/sub", "/home/user/docs") is True
    assert check_paths_overlap("/home/user/docs", "/home/user/photos") is False

    # Test engine overlap check against DB
    dataset = SyncDataset(
        dataset_id="ds-1",
        name="Docs",
        bucket_name="bkt",
        remote_prefix="pfx",
        local_path="/tmp/test_overlap_docs",
    )
    db_fixture.create_sync_dataset(dataset)

    engine = SyncEngine(db=db_fixture)
    overlaps = engine.check_folder_overlap("/tmp/test_overlap_docs/subfolder")
    assert len(overlaps) == 1
    assert "Sync Dataset: 'Docs'" in overlaps[0]


def test_conflicts_recording_and_resolution(db_fixture):
    with tempfile.TemporaryDirectory() as tmp_dir:
        orig_file = Path(tmp_dir) / "notes.txt"
        orig_file.write_text("Local original content")

        conflict_file = Path(tmp_dir) / "notes (conflict - Laptop - 2026-08-19).txt"
        conflict_file.write_text("Remote incoming conflicting content")

        dataset = SyncDataset(
            dataset_id="ds-conflict-test",
            name="Conflicted Folder",
            bucket_name="bkt",
            remote_prefix="pfx",
            local_path=tmp_dir,
        )
        db_fixture.create_sync_dataset(dataset)

        conflict = SyncConflict(
            dataset_id="ds-conflict-test",
            relative_path="notes.txt",
            local_path=str(orig_file),
            conflict_file_path=str(conflict_file),
            remote_device_name="Laptop",
        )
        c_id = db_fixture.create_conflict(conflict)
        assert c_id > 0
        assert db_fixture.count_unresolved_conflicts("ds-conflict-test") == 1

        engine = SyncEngine(db=db_fixture)

        # Resolve KEEP_LOCAL: removes conflict file, keeps local original
        assert engine.resolve_conflict(c_id, ConflictResolution.KEEP_LOCAL.value) is True
        assert not conflict_file.exists()
        assert orig_file.read_text() == "Local original content"
        assert db_fixture.count_unresolved_conflicts("ds-conflict-test") == 0


# ---------------------------------------------------------------------------
# Reattaching a folder to the data it already has in R2
# ---------------------------------------------------------------------------


def _dataset(tmp_path, name="Photos", dataset_id="ds-existing"):
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    return SyncDataset(
        dataset_id=dataset_id,
        name=name,
        bucket_name="bkt",
        remote_prefix=f"r2sync/v1/datasets/{dataset_id}",
        local_path=str(folder),
    ), folder


def _engine(db, monkeypatch):
    engine = SyncEngine(db=db)
    monkeypatch.setattr(engine.watcher_manager, "stop_watching", lambda *a, **kw: None)
    monkeypatch.setattr(engine, "cancel_sync", lambda *a, **kw: None)
    monkeypatch.setattr(engine, "trigger_sync_async", lambda ds_id, **kw: None)
    return engine


def test_readding_a_folder_reuses_its_remote_prefix_instead_of_uploading_again(
    db_fixture, monkeypatch, tmp_path
):
    """The regression that costs storage and bandwidth, end to end.

    A fresh dataset id points at an empty prefix, so the whole folder uploads
    a second time and the first copy is orphaned in the bucket.
    """
    dataset, folder = _dataset(tmp_path)
    db_fixture.create_sync_dataset(dataset)
    engine = _engine(db_fixture, monkeypatch)

    engine.delete_dataset(dataset.dataset_id)

    triggered = {}
    monkeypatch.setattr(engine, "trigger_sync_async",
                        lambda ds_id, **kw: triggered.update(dataset_id=ds_id, **kw))
    readded = engine.create_and_init_dataset(
        name="Photos", local_path=str(folder), bucket_name="bkt"
    )

    assert readded.dataset_id == "ds-existing"
    assert readded.remote_prefix == "r2sync/v1/datasets/ds-existing"
    # --resync never deletes, so "newer" leaves both sides intact.
    assert triggered["resync_mode"] == "newer"


def test_reattachment_survives_a_differently_spelled_path(db_fixture, monkeypatch, tmp_path):
    """rclone and the folder picker disagree on Windows; see _canonical_fs_path."""
    dataset, folder = _dataset(tmp_path)
    db_fixture.create_sync_dataset(dataset)
    engine = _engine(db_fixture, monkeypatch)
    engine.delete_dataset(dataset.dataset_id)

    trailing = str(folder) + os.sep
    assert engine._detached_dataset_for(trailing, "bkt") is not None


def test_purging_the_remote_data_leaves_nothing_to_reattach_to(
    db_fixture, monkeypatch, tmp_path
):
    """Deleting the objects too means a re-add really is a first upload."""
    dataset, folder = _dataset(tmp_path)
    db_fixture.create_sync_dataset(dataset)
    engine = _engine(db_fixture, monkeypatch)
    monkeypatch.setattr("r2sync.core.sync_engine.get_r2_credentials", lambda: None)

    engine.delete_dataset(dataset.dataset_id, delete_remote_files=True)

    readded = engine.create_and_init_dataset(
        name="Photos", local_path=str(folder), bucket_name="bkt"
    )
    assert readded.dataset_id != "ds-existing"


def test_a_different_folder_is_not_reattached(db_fixture, monkeypatch, tmp_path):
    dataset, _ = _dataset(tmp_path)
    db_fixture.create_sync_dataset(dataset)
    engine = _engine(db_fixture, monkeypatch)
    engine.delete_dataset(dataset.dataset_id)

    other = tmp_path / "Music"
    other.mkdir()
    readded = engine.create_and_init_dataset(
        name="Music", local_path=str(other), bucket_name="bkt"
    )
    assert readded.dataset_id != "ds-existing"


def test_a_different_bucket_is_not_reattached(db_fixture, monkeypatch, tmp_path):
    """The same folder backed up to another bucket has no data there yet."""
    dataset, folder = _dataset(tmp_path)
    db_fixture.create_sync_dataset(dataset)
    engine = _engine(db_fixture, monkeypatch)
    engine.delete_dataset(dataset.dataset_id)

    readded = engine.create_and_init_dataset(
        name="Photos", local_path=str(folder), bucket_name="other-bucket"
    )
    assert readded.dataset_id != "ds-existing"


def test_asking_for_a_new_copy_does_not_reattach(db_fixture, monkeypatch, tmp_path):
    dataset, folder = _dataset(tmp_path)
    db_fixture.create_sync_dataset(dataset)
    engine = _engine(db_fixture, monkeypatch)
    engine.delete_dataset(dataset.dataset_id)

    readded = engine.create_and_init_dataset(
        name="Photos", local_path=str(folder), bucket_name="bkt", initial_action="new"
    )
    assert readded.dataset_id != "ds-existing"


def test_replace_still_makes_the_remote_match_the_local_folder(
    db_fixture, monkeypatch, tmp_path
):
    """initial_action reached create_and_init_dataset and was ignored entirely."""
    dataset, folder = _dataset(tmp_path)
    db_fixture.create_sync_dataset(dataset)
    engine = _engine(db_fixture, monkeypatch)
    engine.delete_dataset(dataset.dataset_id)

    triggered = {}
    monkeypatch.setattr(engine, "trigger_sync_async",
                        lambda ds_id, **kw: triggered.update(dataset_id=ds_id, **kw))
    engine.create_and_init_dataset(name="Photos", local_path=str(folder),
                                   bucket_name="bkt", initial_action="replace")

    assert triggered["resync_mode"] == "path1"


def test_reattaching_consumes_the_record_so_the_next_add_is_a_new_dataset(
    db_fixture, monkeypatch, tmp_path
):
    dataset, folder = _dataset(tmp_path)
    db_fixture.create_sync_dataset(dataset)
    engine = _engine(db_fixture, monkeypatch)
    engine.delete_dataset(dataset.dataset_id)

    first = engine.create_and_init_dataset(
        name="Photos", local_path=str(folder), bucket_name="bkt"
    )
    assert first.dataset_id == "ds-existing"
    db_fixture.delete_sync_dataset(first.dataset_id)

    second = engine.create_and_init_dataset(
        name="Photos", local_path=str(folder), bucket_name="bkt"
    )
    assert second.dataset_id != "ds-existing"


def test_adding_a_folder_never_reaches_for_credentials_or_the_network(
    db_fixture, monkeypatch, tmp_path
):
    """Adding a folder answers over IPC on a fifteen-second budget.

    Looking the dataset up in R2 instead cost a credential-store hit plus an
    rclone call per dataset, and timed the call out when the credential store
    was slow to answer -- which is exactly what happened on Windows.
    """
    engine = _engine(db_fixture, monkeypatch)

    def forbidden(*a, **kw):
        raise AssertionError("adding a folder must not touch credentials or R2")

    monkeypatch.setattr("r2sync.core.sync_engine.get_r2_credentials", forbidden)
    monkeypatch.setattr(engine, "discover_remote_datasets", forbidden)

    folder = tmp_path / "New"
    folder.mkdir()
    assert engine.create_and_init_dataset(
        name="New", local_path=str(folder), bucket_name="bkt"
    ) is not None


# ---------------------------------------------------------------------------
# Connectivity probing
# ---------------------------------------------------------------------------


def test_connectivity_check_does_not_touch_the_global_socket_timeout(monkeypatch):
    """It used to call socket.setdefaulttimeout and never put it back.

    That is process-global, so a single connectivity check imposed its 3-second
    timeout on every socket the GUI and daemon opened afterwards.
    """
    import socket as socket_mod
    from r2sync.utils import system

    monkeypatch.setattr(system.socket, "create_connection",
                        lambda addr, timeout=None: MagicMock())

    before = socket_mod.getdefaulttimeout()
    assert system.check_internet_connection() is True
    assert socket_mod.getdefaulttimeout() == before


def test_a_blocked_dns_port_does_not_report_the_machine_as_offline(monkeypatch):
    """Port 53 to a public resolver is routinely blocked while 443 is fine.

    The old check probed only 1.1.1.1:53, so those networks marked every
    dataset Offline even though R2 was reachable the whole time.
    """
    from r2sync.utils import system

    reached = []

    def only_443(addr, timeout=None):
        host, port = addr
        reached.append(port)
        if port != 443:
            raise OSError("blocked")
        return MagicMock()

    monkeypatch.setattr(system.socket, "create_connection", only_443)
    assert system.check_internet_connection() is True
    assert 443 in reached


def test_genuinely_offline_is_still_reported_as_offline(monkeypatch):
    from r2sync.utils import system

    def unreachable(addr, timeout=None):
        raise OSError("network is unreachable")

    monkeypatch.setattr(system.socket, "create_connection", unreachable)
    assert system.check_internet_connection() is False


# ---------------------------------------------------------------------------
# Which computers are shown as present
# ---------------------------------------------------------------------------


def test_a_computer_that_stopped_reporting_is_shown_as_offline(db_fixture):
    """Nothing ever revised the stored status, so a switched-off PC stayed online."""
    from datetime import datetime, timedelta

    stale = (datetime.now() - timedelta(hours=6)).isoformat()
    db_fixture.upsert_sync_device(Device(
        device_id="other-pc", device_name="Laptop", dataset_id="ds1",
        status="online", last_seen_at=stale,
    ))

    listed = db_fixture.list_sync_devices("ds1")
    assert [d.status for d in listed] == ["offline"]


def test_a_recent_heartbeat_outranks_a_stale_stored_status(db_fixture):
    """The reported symptom: this PC showing itself offline while it was running.

    Fetching device registrations from R2 wrote back an older status and an
    older timestamp over the row the heartbeat maintains locally.
    """
    from datetime import datetime

    db_fixture.upsert_sync_device(Device(
        device_id="this-pc", device_name="Desktop", dataset_id="ds1",
        is_current_device=True, status="offline",
        last_seen_at=datetime.now().isoformat(),
    ))

    listed = db_fixture.list_sync_devices("ds1")
    assert [d.status for d in listed] == ["online"]


def test_a_syncing_computer_keeps_saying_syncing(db_fixture):
    from datetime import datetime

    db_fixture.upsert_sync_device(Device(
        device_id="this-pc", device_name="Desktop", dataset_id="ds1",
        status="syncing", last_seen_at=datetime.now().isoformat(),
    ))
    assert db_fixture.list_sync_devices("ds1")[0].status == "syncing"


def test_a_device_that_never_reported_is_left_alone(db_fixture):
    """No timestamp is not evidence of absence; do not invent one."""
    from r2sync.core.models import presence_status

    assert presence_status("online", None) == "online"
    assert presence_status("offline", "not a timestamp") == "offline"


def test_refreshing_from_r2_does_not_age_this_computers_own_heartbeat(db_fixture, monkeypatch):
    """The remote copy is only rewritten at the start and end of a sync."""
    from datetime import datetime, timedelta

    dataset = SyncDataset(
        dataset_id="ds1", name="Docs", bucket_name="bkt",
        remote_prefix="r2sync/v1/datasets/ds1", local_path="/tmp/docs",
    )
    db_fixture.create_sync_dataset(dataset)

    dev_id = db_fixture.get_or_create_device_id()
    fresh = datetime.now().isoformat()
    db_fixture.upsert_sync_device(Device(
        device_id=dev_id, device_name="Desktop", dataset_id="ds1",
        is_current_device=True, status="online", last_seen_at=fresh,
    ))

    engine = SyncEngine(db=db_fixture)
    monkeypatch.setattr("r2sync.core.sync_engine.get_r2_credentials",
                        lambda: MagicMock())
    stale = (datetime.now() - timedelta(hours=8)).isoformat()
    monkeypatch.setattr(
        engine.rclone_engine, "fetch_remote_devices",
        lambda ds, creds=None: [Device(
            device_id=dev_id, device_name="Desktop", dataset_id="ds1",
            status="online", last_seen_at=stale,
        )],
    )

    devices = engine.refresh_connected_devices("ds1")

    assert [d.status for d in devices] == ["online"], \
        "this PC aged itself out by fetching its own registration back from R2"
