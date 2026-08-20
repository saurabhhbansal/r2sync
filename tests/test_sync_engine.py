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
# Reattaching a folder to the dataset it already has in R2
# ---------------------------------------------------------------------------


def _engine_with_remote(db, remote, monkeypatch):
    """A SyncEngine whose bucket contains ``remote``, with no rclone anywhere."""
    engine = SyncEngine(db=db)
    monkeypatch.setattr(engine, "discover_remote_datasets", lambda bucket_name=None: list(remote))
    return engine


def _remote_info(db, **kw):
    defaults = dict(
        dataset_id="ds-existing",
        name="Photos",
        bucket_name="bkt",
        created_by_device_id=db.get_or_create_device_id(),
        local_path="/home/u/Photos",
        total_files=900,
    )
    defaults.update(kw)
    return RemoteDatasetInfo(**defaults)


def test_a_folder_this_pc_already_synced_is_matched_by_its_path(db_fixture, monkeypatch):
    """The headline case: remove a sync, add the same folder, do not re-upload."""
    existing = _remote_info(db_fixture)
    engine = _engine_with_remote(db_fixture, [existing], monkeypatch)

    found = engine._find_reattachable_dataset("bkt", "/home/u/Photos", "Photos")
    assert found is not None and found.dataset_id == "ds-existing"


def test_reattachment_ignores_how_the_path_is_spelled(db_fixture, monkeypatch):
    """rclone and the folder picker disagree on Windows; see _canonical_fs_path."""
    existing = _remote_info(db_fixture, local_path="//?/C:/Users/me/Photos")
    engine = _engine_with_remote(db_fixture, [existing], monkeypatch)

    assert engine._find_reattachable_dataset("bkt", r"C:\Users\me\Photos", "Photos") is not None


def test_a_different_folder_is_not_reattached(db_fixture, monkeypatch):
    existing = _remote_info(db_fixture)
    engine = _engine_with_remote(db_fixture, [existing], monkeypatch)

    assert engine._find_reattachable_dataset("bkt", "/home/u/Music", "Music") is None


def test_another_computers_dataset_is_never_reattached(db_fixture, monkeypatch):
    """That is what "Set Up This PC" is for, and it downloads rather than merges."""
    existing = _remote_info(db_fixture, created_by_device_id="some-other-pc")
    engine = _engine_with_remote(db_fixture, [existing], monkeypatch)

    assert engine._find_reattachable_dataset("bkt", "/home/u/Photos", "Photos") is None


def test_datasets_without_a_published_path_fall_back_to_the_name(db_fixture, monkeypatch):
    """Anything created before local_path was recorded still has to be findable."""
    legacy = _remote_info(db_fixture, local_path="")
    engine = _engine_with_remote(db_fixture, [legacy], monkeypatch)

    assert engine._find_reattachable_dataset("bkt", "/home/u/Photos", "photos") is not None
    assert engine._find_reattachable_dataset("bkt", "/home/u/Photos", "Videos") is None


def test_an_ambiguous_match_creates_a_new_dataset_instead_of_guessing(db_fixture, monkeypatch):
    """Merging two unrelated folders is worse than uploading one of them twice."""
    a = _remote_info(db_fixture, dataset_id="ds-a", local_path="")
    b = _remote_info(db_fixture, dataset_id="ds-b", local_path="")
    engine = _engine_with_remote(db_fixture, [a, b], monkeypatch)

    assert engine._find_reattachable_dataset("bkt", "/home/u/Photos", "Photos") is None


def test_a_bucket_that_cannot_be_listed_still_lets_the_folder_be_added(db_fixture, monkeypatch):
    """Offline, or without credentials, adding a folder must not fail."""
    engine = SyncEngine(db=db_fixture)

    def boom(bucket_name=None):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(engine, "discover_remote_datasets", boom)
    assert engine._find_reattachable_dataset("bkt", "/home/u/Photos", "Photos") is None


def test_readding_a_folder_reuses_its_remote_prefix_instead_of_uploading_again(
    db_fixture, monkeypatch, tmp_path
):
    """Delete a sync, add the same folder back: it must land on the same data.

    A fresh dataset id points at an empty prefix, so the whole folder uploads
    a second time and the first copy is orphaned in the bucket. This is the
    regression that costs the user storage and bandwidth, so assert on the
    prefix rather than on the lookup helper.
    """
    folder = tmp_path / "Photos"
    folder.mkdir()
    existing = _remote_info(db_fixture, local_path=str(folder))
    engine = _engine_with_remote(db_fixture, [existing], monkeypatch)

    triggered = {}
    monkeypatch.setattr(engine, "trigger_sync_async",
                        lambda ds_id, **kw: triggered.update(dataset_id=ds_id, **kw))

    ds = engine.create_and_init_dataset(name="Photos", local_path=str(folder), bucket_name="bkt")

    assert ds.dataset_id == "ds-existing"
    assert ds.remote_prefix.endswith("ds-existing")
    # --resync never deletes, so "newer" leaves both sides intact.
    assert triggered["resync_mode"] == "newer"


def test_replace_still_makes_the_remote_match_the_local_folder(
    db_fixture, monkeypatch, tmp_path
):
    """initial_action reached create_and_init_dataset and was ignored entirely."""
    folder = tmp_path / "Photos"
    folder.mkdir()
    existing = _remote_info(db_fixture, local_path=str(folder))
    engine = _engine_with_remote(db_fixture, [existing], monkeypatch)

    triggered = {}
    monkeypatch.setattr(engine, "trigger_sync_async",
                        lambda ds_id, **kw: triggered.update(dataset_id=ds_id, **kw))

    engine.create_and_init_dataset(name="Photos", local_path=str(folder),
                                   bucket_name="bkt", initial_action="replace")

    assert triggered["resync_mode"] == "path1"


def test_asking_for_a_new_copy_does_not_reattach(db_fixture, monkeypatch, tmp_path):
    folder = tmp_path / "Photos"
    folder.mkdir()
    existing = _remote_info(db_fixture, local_path=str(folder))
    engine = _engine_with_remote(db_fixture, [existing], monkeypatch)
    monkeypatch.setattr(engine, "trigger_sync_async", lambda ds_id, **kw: None)

    ds = engine.create_and_init_dataset(name="Photos", local_path=str(folder),
                                        bucket_name="bkt", initial_action="new")

    assert ds.dataset_id != "ds-existing"
