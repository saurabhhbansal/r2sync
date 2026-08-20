"""Regression tests for scheduled/periodic reconciliation of sync datasets."""

from datetime import datetime, timedelta


from r2sync.core.db import Database
from r2sync.core.models import SyncDataset, SyncScheduleMode
from r2sync.core.scheduler import JobScheduler, sync_dataset_is_due


def _ds(mode, **kw):
    return SyncDataset(
        dataset_id=kw.pop("dataset_id", f"ds-{mode}"),
        name=mode,
        bucket_name="bkt",
        local_path="/tmp/x",
        schedule_mode=mode,
        **kw,
    )


NOW = datetime(2026, 8, 20, 12, 0, 0)


def test_never_synced_datasets_are_due_in_every_automatic_mode():
    for mode in (
        SyncScheduleMode.REALTIME.value,
        SyncScheduleMode.INTERVAL.value,
        SyncScheduleMode.DAILY.value,
    ):
        assert sync_dataset_is_due(_ds(mode), NOW) is True, mode


def test_manual_datasets_are_never_scheduled():
    assert sync_dataset_is_due(_ds(SyncScheduleMode.MANUAL.value), NOW) is False


def test_daily_datasets_reconcile_once_per_day():
    """'daily' fell through every branch of the old tick and never reconciled."""
    ds = _ds(SyncScheduleMode.DAILY.value)

    yesterday = (NOW - timedelta(days=1)).timestamp()
    assert sync_dataset_is_due(ds, NOW, last_attempt_ts=yesterday) is True

    this_morning = NOW.replace(hour=1).timestamp()
    assert sync_dataset_is_due(ds, NOW, last_attempt_ts=this_morning) is False


def test_interval_datasets_honour_their_configured_interval():
    ds = _ds(SyncScheduleMode.INTERVAL.value, schedule_interval_minutes=30)

    ten_min_ago = (NOW - timedelta(minutes=10)).timestamp()
    assert sync_dataset_is_due(ds, NOW, last_attempt_ts=ten_min_ago) is False

    forty_min_ago = (NOW - timedelta(minutes=40)).timestamp()
    assert sync_dataset_is_due(ds, NOW, last_attempt_ts=forty_min_ago) is True


def test_realtime_datasets_still_get_a_safety_net_reconcile():
    ds = _ds(SyncScheduleMode.REALTIME.value)

    five_min_ago = (NOW - timedelta(minutes=5)).timestamp()
    assert sync_dataset_is_due(ds, NOW, last_attempt_ts=five_min_ago) is False

    two_hours_ago = (NOW - timedelta(hours=2)).timestamp()
    assert sync_dataset_is_due(ds, NOW, last_attempt_ts=two_hours_ago) is True


def test_persisted_last_sync_prevents_a_restart_stampede():
    """After a service restart the in-memory clock is empty; last_sync_at fills in."""
    just_synced = (NOW - timedelta(minutes=1)).isoformat()
    ds = _ds(SyncScheduleMode.REALTIME.value, last_sync_at=just_synced)
    assert sync_dataset_is_due(ds, NOW, last_attempt_ts=None) is False

    stale = (NOW - timedelta(hours=6)).isoformat()
    ds_stale = _ds(SyncScheduleMode.REALTIME.value, last_sync_at=stale)
    assert sync_dataset_is_due(ds_stale, NOW, last_attempt_ts=None) is True


def test_paused_and_disabled_datasets_are_never_due():
    assert sync_dataset_is_due(_ds(SyncScheduleMode.REALTIME.value, paused=True), NOW) is False
    assert sync_dataset_is_due(_ds(SyncScheduleMode.REALTIME.value, enabled=False), NOW) is False


def test_scheduler_tick_reconciles_every_automatic_mode(tmp_path):
    db = Database(db_path=tmp_path / "s.sqlite")
    for mode in ("realtime", "interval", "daily", "manual"):
        db.create_sync_dataset(_ds(mode))

    fired = []
    sched = JobScheduler(db=db, job_runner_cb=lambda j: None, sync_runner_cb=fired.append)
    sched._tick()

    assert sorted(fired) == ["ds-daily", "ds-interval", "ds-realtime"]
    db.close()


def test_scheduler_retries_deferred_datasets_immediately(tmp_path):
    """A dataset deferred while offline is retried on the very next tick."""
    db = Database(db_path=tmp_path / "s.sqlite")
    db.create_sync_dataset(
        _ds(SyncScheduleMode.INTERVAL.value,
            dataset_id="ds-offline",
            schedule_interval_minutes=240,
            last_sync_at=datetime.now().isoformat())
    )

    fired = []
    deferred = ["ds-offline"]
    sched = JobScheduler(
        db=db,
        job_runner_cb=lambda j: None,
        sync_runner_cb=fired.append,
        deferred_provider=lambda: list(deferred),
    )

    # Not otherwise due (4h interval, just synced) but deferred, so it runs.
    sched._tick()
    assert fired == ["ds-offline"]

    deferred.clear()
    fired.clear()
    sched._tick()
    assert fired == []
    db.close()
