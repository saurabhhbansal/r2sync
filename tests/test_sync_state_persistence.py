"""Regression tests for the state a sync leaves behind in the database.

Two defects lived here. A successful sync could not clear the error message
left by an earlier failure, so healthy datasets stayed decorated with a stale
"Sync was canceled or interrupted." indefinitely -- visible in the UI, in
``r2sync-cli status`` and in the DB row, long after the sync in question had
completed 100%. And a run blocked by another run's lock file was recorded as a
hard failure, which raised an error toast for every scheduler tick that landed
during a long sync.
"""

import pytest

from r2sync.core.db import Database
from r2sync.core.models import (
    R2Credentials,
    SyncDataset,
    SyncScheduleMode,
    SyncStatus,
)
from r2sync.core.sync_engine import SyncEngine


@pytest.fixture
def db(tmp_path):
    database = Database(db_path=tmp_path / "state.sqlite")
    yield database
    database.close()


@pytest.fixture
def dataset(db, tmp_path):
    local = tmp_path / "folder"
    local.mkdir()
    ds = SyncDataset(
        dataset_id="ds-state", name="Stateful", bucket_name="bkt",
        remote_prefix="r2sync/v1/datasets/ds-state", local_path=str(local),
        schedule_mode=SyncScheduleMode.MANUAL.value,
        status=SyncStatus.WAITING.value,
    )
    db.create_sync_dataset(ds)
    return ds


# ---------------------------------------------------------------------------
# last_error must be clearable
# ---------------------------------------------------------------------------

def test_a_successful_sync_clears_a_previous_error(db, dataset):
    db.update_sync_status(
        dataset.dataset_id, SyncStatus.ERROR.value,
        last_error="Sync was canceled or interrupted.",
    )
    assert db.get_sync_dataset(dataset.dataset_id).last_error

    db.update_sync_status(
        dataset.dataset_id, SyncStatus.SYNCED.value, last_error=None,
    )

    assert db.get_sync_dataset(dataset.dataset_id).last_error is None, (
        "passing last_error=None must clear the column, otherwise a dataset can "
        "never shed the message from a failure it has since recovered from"
    )


def test_omitting_last_error_leaves_it_untouched(db, dataset):
    db.update_sync_status(
        dataset.dataset_id, SyncStatus.ERROR.value, last_error="disk full",
    )

    # Most callers say nothing about the error field; they must not wipe it.
    db.update_sync_status(dataset.dataset_id, SyncStatus.SYNCING.value)

    assert db.get_sync_dataset(dataset.dataset_id).last_error == "disk full"


def test_initial_sync_done_survives_a_successful_run(db, dataset):
    db.update_sync_status(
        dataset.dataset_id, SyncStatus.SYNCED.value, initial_sync_done=True,
    )

    reloaded = db.get_sync_dataset(dataset.dataset_id)
    assert reloaded.initial_sync_done is True, (
        "without this every later sync re-runs a full --resync, which is slow "
        "and never propagates deletions"
    )


# ---------------------------------------------------------------------------
# End to end through _execute_sync
# ---------------------------------------------------------------------------

def _engine_with_scripted_bisync(db, result):
    engine = SyncEngine(db=db)
    engine.notifier = _RecordingNotifier()
    engine.rclone_engine.run_bisync = lambda **kw: dict(result)
    return engine


class _RecordingNotifier:
    def __init__(self):
        self.toasts = []

    def show_toast(self, title="", message="", notification_type="info"):
        self.toasts.append((notification_type, title, message))


@pytest.fixture
def patched_environment(monkeypatch):
    monkeypatch.setattr(
        "r2sync.core.sync_engine.get_r2_credentials",
        lambda: R2Credentials(account_id="a", access_key_id="k",
                              secret_access_key="s", default_bucket="bkt"),
    )
    monkeypatch.setattr(
        "r2sync.core.sync_engine.check_internet_connection", lambda: True
    )
    monkeypatch.setattr(
        "r2sync.core.rclone_engine.RcloneBinaryManager.is_installed", lambda: True
    )


def test_recovering_from_a_failure_wipes_the_error_message(db, dataset, patched_environment):
    db.update_sync_status(
        dataset.dataset_id, SyncStatus.ERROR.value,
        last_error="Sync was canceled or interrupted.",
    )

    engine = _engine_with_scripted_bisync(db, {
        "success": True, "bytes_transferred": 10, "files_transferred": 1,
        "duration_seconds": 1.0,
    })
    engine.watcher_manager.ensure_watching = lambda *a, **kw: None
    engine._execute_sync(db.get_sync_dataset(dataset.dataset_id), None, False)

    row = db.get_sync_dataset(dataset.dataset_id)
    assert row.status == SyncStatus.SYNCED.value
    assert row.last_error is None
    assert row.initial_sync_done is True


def test_a_lock_collision_does_not_look_like_a_failed_sync(db, dataset, patched_environment):
    db.update_sync_status(dataset.dataset_id, SyncStatus.SYNCED.value, last_error=None)

    engine = _engine_with_scripted_bisync(db, {
        "success": False,
        "lock_conflict": True,
        "error_message": "Another sync of this folder is still running; it will be retried.",
    })
    engine.watcher_manager.ensure_watching = lambda *a, **kw: None
    engine._execute_sync(db.get_sync_dataset(dataset.dataset_id), None, False)

    row = db.get_sync_dataset(dataset.dataset_id)
    assert row.status != SyncStatus.ERROR.value, (
        "a scheduler tick landing during a long sync is a collision, not a fault"
    )
    assert row.status != SyncStatus.SYNCING.value, "the row must not be left mid-sync"
    assert row.last_error is None
    assert not any(kind == "error" for kind, _, _ in engine.notifier.toasts)

    # ...and the dataset is queued for the next tick rather than forgotten.
    assert dataset.dataset_id in engine.take_deferred_syncs()


def test_a_genuine_failure_is_still_recorded(db, dataset, patched_environment):
    engine = _engine_with_scripted_bisync(db, {
        "success": False,
        "error_message": "Sync failed: permission denied",
    })
    engine.watcher_manager.ensure_watching = lambda *a, **kw: None
    engine._execute_sync(db.get_sync_dataset(dataset.dataset_id), None, False)

    row = db.get_sync_dataset(dataset.dataset_id)
    assert row.status == SyncStatus.ERROR.value
    assert row.last_error == "Sync failed: permission denied"
    assert any(kind == "error" for kind, _, _ in engine.notifier.toasts)
