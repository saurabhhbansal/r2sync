import os
import pytest
from unittest.mock import MagicMock
from r2sync.core.backup_engine import BackupEngine
from r2sync.core.db import Database
from r2sync.core.models import BackupJob, BackupMode, BackupRun, FileTransfer, JobScheduleType, RunStatus, TransferProgressEvent
from r2sync.core.rclone_engine import RcloneEngine
from r2sync.notifications.notifier import NotificationManager


class MockRcloneEngine:
    def __init__(self):
        self.canceled = False
        self.should_fail = False

    def cancel_run(self, job_id: int) -> bool:
        self.canceled = True
        return True

    def is_job_running(self, job_id: int) -> bool:
        return False

    def run_backup(self, job, run_record, progress_cb=None, file_transfer_cb=None, log_cb=None, creds=None, speed_profile=None):
        if self.should_fail:
            run_record.status = RunStatus.FAILED.value
            run_record.error_message = "Mock network error"
            return run_record

        if progress_cb:
            event = TransferProgressEvent(
                job_id=job.id,
                run_id=run_record.id,
                percentage=100.0,
                bytes_transferred=5000,
                total_bytes=5000,
                speed_bytes_per_sec=1000.0,
                files_transferred=2,
                total_files=2,
            )
            progress_cb(event)

        if file_transfer_cb:
            ft = FileTransfer(
                run_id=run_record.id,
                job_id=job.id,
                file_path="fileA.txt",
                size_bytes=2500,
                transferred_bytes=2500,
                status="transferred",
            )
            file_transfer_cb(ft)

        run_record.status = RunStatus.COMPLETED.value
        run_record.bytes_transferred = 5000
        run_record.files_transferred = 2
        run_record.duration_seconds = 1.2
        return run_record


@pytest.fixture
def backup_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("R2SYNC_DATA_DIR", str(tmp_path))
    db = Database(tmp_path / "test_backup.sqlite")
    mock_rclone = MockRcloneEngine()
    notifier = NotificationManager()
    engine = BackupEngine(db, mock_rclone, notifier)

    # Mock credentials in environment/vault
    from r2sync.core.credentials import save_r2_credentials
    save_r2_credentials("test_acc", "test_ak", "test_sk", "test_bkt")

    # Create dummy source dir
    src_dir = tmp_path / "source_folder"
    src_dir.mkdir()
    (src_dir / "sample.txt").write_text("hello world")

    return {"db": db, "engine": engine, "mock_rclone": mock_rclone, "src_dir": str(src_dir)}


def test_backup_engine_success_flow(backup_setup):
    db = backup_setup["db"]
    engine = backup_setup["engine"]
    src_dir = backup_setup["src_dir"]

    job = BackupJob(
        name="Source Backup",
        source_path=src_dir,
        bucket_name="test_bkt",
        backup_mode=BackupMode.SYNC.value,
    )
    job_id = db.create_job(job)
    job.id = job_id

    progress_events = []
    completed_events = []

    engine.add_progress_listener(lambda p: progress_events.append(p))
    engine.add_completion_listener(lambda c: completed_events.append(c))

    # Run backup synchronously via internal runner
    final_run = engine._run_job_with_retries(job, max_retries=1)

    assert final_run.status == RunStatus.COMPLETED.value
    assert final_run.bytes_transferred == 5000
    assert len(progress_events) == 1
    assert len(completed_events) == 1

    # Verify DB state
    updated_job = db.get_job(job_id)
    assert updated_job.last_status == "completed"
    assert updated_job.last_run_at is not None

    transfers = db.list_transfers_for_run(final_run.id)
    assert len(transfers) == 1
    assert transfers[0].file_path == "fileA.txt"

    activities = db.list_activities()
    assert len(activities) >= 2


def test_backup_cancelation(backup_setup):
    engine = backup_setup["engine"]
    mock_rclone = backup_setup["mock_rclone"]

    assert engine.cancel_job(10) is True
    assert mock_rclone.canceled is True
