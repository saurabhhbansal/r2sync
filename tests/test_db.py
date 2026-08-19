import pytest
from r2sync.core.db import Database
from r2sync.core.models import BackupJob, BackupMode, BackupRun, FileTransfer, JobScheduleType, RunStatus


@pytest.fixture
def db(tmp_path):
    db_file = tmp_path / "test_db.sqlite"
    return Database(db_file)


def test_settings_crud(db):
    assert db.get_setting("theme") is None
    assert db.get_setting("theme", "dark") == "dark"

    db.set_setting("theme", "light")
    assert db.get_setting("theme") == "light"

    all_s = db.get_all_settings()
    assert all_s.get("theme") == "light"


def test_backup_jobs_crud(db):
    job = BackupJob(
        name="Docs Backup",
        source_path="/home/user/docs",
        bucket_name="my-bucket",
        remote_prefix="docs",
        schedule_type=JobScheduleType.DAILY.value,
        schedule_time_of_day="03:00",
        backup_mode=BackupMode.SYNC.value,
        exclude_patterns=["*.tmp", ".git/"],
    )

    job_id = db.create_job(job)
    assert job_id > 0
    assert job.id == job_id

    fetched = db.get_job(job_id)
    assert fetched is not None
    assert fetched.name == "Docs Backup"
    assert fetched.source_path == "/home/user/docs"
    assert fetched.bucket_name == "my-bucket"
    assert fetched.schedule_time_of_day == "03:00"
    assert fetched.exclude_patterns == ["*.tmp", ".git/"]
    assert fetched.enabled is True

    # Update
    fetched.name = "Renamed Docs"
    fetched.schedule_interval_minutes = 120
    assert db.update_job(fetched) is True

    updated = db.get_job(job_id)
    assert updated.name == "Renamed Docs"
    assert updated.schedule_interval_minutes == 120

    # List
    jobs = db.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].name == "Renamed Docs"

    # Status update
    db.update_job_status(job_id, last_run_at="2026-08-18T00:00:00", last_status="completed")
    after_status = db.get_job(job_id)
    assert after_status.last_run_at == "2026-08-18T00:00:00"
    assert after_status.last_status == "completed"

    # Delete
    assert db.delete_job(job_id) is True
    assert db.get_job(job_id) is None


def test_backup_runs_and_transfers(db):
    job = BackupJob(name="Test", source_path="/test", bucket_name="bkt")
    job_id = db.create_job(job)

    run = BackupRun(
        job_id=job_id,
        job_name="Test",
        status=RunStatus.RUNNING.value,
    )
    run_id = db.create_run(run)
    assert run_id > 0

    # Add transfers
    t1 = FileTransfer(
        run_id=run_id,
        job_id=job_id,
        file_path="file1.txt",
        size_bytes=1024,
        transferred_bytes=1024,
        status="transferred",
    )
    db.add_transfer(t1)

    t2 = FileTransfer(
        run_id=run_id,
        job_id=job_id,
        file_path="old.tmp",
        size_bytes=512,
        status="deleted",
    )
    db.add_transfer(t2)

    transfers = db.list_transfers_for_run(run_id)
    assert len(transfers) == 2
    assert transfers[0].file_path == "file1.txt"
    assert transfers[1].status == "deleted"

    # Complete run
    run.status = RunStatus.COMPLETED.value
    run.bytes_transferred = 1024
    run.files_transferred = 1
    run.duration_seconds = 2.5
    assert db.update_run(run) is True

    fetched_run = db.get_run(run_id)
    assert fetched_run.status == RunStatus.COMPLETED.value
    assert fetched_run.bytes_transferred == 1024

    # Summary stats
    stats = db.get_summary_stats()
    assert stats["total_jobs"] == 1
    assert stats["total_runs"] == 1
    assert stats["completed_runs"] == 1
    assert stats["total_bytes_transferred"] == 1024
    assert stats["total_files_transferred"] == 1
