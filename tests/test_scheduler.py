from datetime import datetime, timedelta
from r2sync.core.models import BackupJob, JobScheduleType
from r2sync.core.scheduler import calculate_next_run


def test_interval_schedule_calculation():
    base = datetime(2026, 8, 18, 10, 0, 0)
    job = BackupJob(
        name="Interval Job",
        source_path="/test",
        bucket_name="bkt",
        schedule_type=JobScheduleType.INTERVAL.value,
        schedule_interval_minutes=30,
    )

    # If never run, scheduled in 30m
    next_dt = calculate_next_run(job, from_time=base)
    assert next_dt == base + timedelta(minutes=30)

    # If ran 10m ago, scheduled in 20m
    job.last_run_at = (base - timedelta(minutes=10)).isoformat()
    next_dt = calculate_next_run(job, from_time=base)
    assert next_dt == base + timedelta(minutes=20)


def test_daily_schedule_calculation():
    base = datetime(2026, 8, 18, 10, 0, 0)
    job = BackupJob(
        name="Daily Job",
        source_path="/test",
        bucket_name="bkt",
        schedule_type=JobScheduleType.DAILY.value,
        schedule_time_of_day="14:30",
    )

    # Time today is before 14:30 -> scheduled for today 14:30
    next_dt = calculate_next_run(job, from_time=base)
    assert next_dt == datetime(2026, 8, 18, 14, 30, 0)

    # If current time is 15:00 -> scheduled for tomorrow 14:30
    late_base = datetime(2026, 8, 18, 15, 0, 0)
    next_dt_late = calculate_next_run(job, from_time=late_base)
    assert next_dt_late == datetime(2026, 8, 19, 14, 30, 0)


def test_manual_schedule_calculation():
    job = BackupJob(
        name="Manual Job",
        source_path="/test",
        bucket_name="bkt",
        schedule_type=JobScheduleType.MANUAL.value,
    )
    assert calculate_next_run(job) is None
