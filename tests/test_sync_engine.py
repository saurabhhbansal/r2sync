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
def db_fixture():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path=path)
    yield db
    if os.path.exists(path):
        os.remove(path)


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
