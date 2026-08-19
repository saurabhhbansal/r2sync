"""Job scheduling engine for r2sync."""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from r2sync.core.db import Database
from r2sync.core.models import BackupJob, JobScheduleType

logger = logging.getLogger(__name__)


def calculate_next_run(job: BackupJob, from_time: Optional[datetime] = None) -> Optional[datetime]:
    """Calculate the next scheduled execution datetime for a backup job."""
    if not job.enabled or job.schedule_type == JobScheduleType.MANUAL.value:
        return None

    base_time = from_time or datetime.now()

    if job.schedule_type == JobScheduleType.INTERVAL.value:
        mins = max(1, job.schedule_interval_minutes)
        if job.last_run_at:
            try:
                last_dt = datetime.fromisoformat(job.last_run_at)
                next_dt = last_dt + timedelta(minutes=mins)
                # If next_dt is in the past, schedule immediately (or base_time + 10s)
                if next_dt <= base_time:
                    return base_time + timedelta(seconds=5)
                return next_dt
            except Exception:
                pass
        return base_time + timedelta(minutes=mins)

    elif job.schedule_type == JobScheduleType.DAILY.value:
        try:
            target_hour, target_min = map(int, job.schedule_time_of_day.split(":"))
        except Exception:
            target_hour, target_min = 2, 0

        target_today = base_time.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
        if target_today > base_time:
            return target_today
        else:
            return target_today + timedelta(days=1)

    elif job.schedule_type == JobScheduleType.WEEKLY.value:
        try:
            target_hour, target_min = map(int, job.schedule_time_of_day.split(":"))
        except Exception:
            target_hour, target_min = 2, 0

        allowed_days = job.schedule_days_of_week or [0, 1, 2, 3, 4, 5, 6]
        # Current weekday: Monday is 0 and Sunday is 6
        current_weekday = base_time.weekday()

        # Check today first if time hasn't passed
        target_today = base_time.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
        if current_weekday in allowed_days and target_today > base_time:
            return target_today

        # Check next 7 days
        for day_offset in range(1, 8):
            candidate_date = (base_time + timedelta(days=day_offset)).replace(
                hour=target_hour, minute=target_min, second=0, microsecond=0
            )
            if candidate_date.weekday() in allowed_days:
                return candidate_date

        return None

    return None


class JobScheduler:
    """Background scheduler ticking periodically to execute due backup and sync jobs."""

    def __init__(
        self,
        db: Database,
        job_runner_cb: Callable[[BackupJob], None],
        sync_runner_cb: Optional[Callable[[str], None]] = None,
        heartbeat_cb: Optional[Callable[[], None]] = None,
        tick_interval_seconds: float = 10.0,
    ):
        self.db = db
        self.job_runner_cb = job_runner_cb
        self.sync_runner_cb = sync_runner_cb
        self.heartbeat_cb = heartbeat_cb
        self.tick_interval_seconds = tick_interval_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_heartbeat = 0.0
        self._sync_last_reconcile: Dict[str, float] = {}

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, name="r2sync-scheduler", daemon=True)
            self._thread.start()
            logger.info("Scheduler service started.")

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            if self._thread:
                self._thread.join(timeout=5.0)
                self._thread = None
                logger.info("Scheduler service stopped.")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def update_all_next_runs(self) -> None:
        """Recalculate next_run_at for all enabled backup jobs."""
        jobs = self.db.list_jobs()
        now = datetime.now()
        for job in jobs:
            if job.id and job.enabled:
                next_dt = calculate_next_run(job, now)
                next_str = next_dt.isoformat() if next_dt else None
                self.db.update_job_status(job.id, next_run_at=next_str)

    def _run_loop(self) -> None:
        self.update_all_next_runs()

        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error(f"Error in scheduler tick: {e}", exc_info=True)

            self._stop_event.wait(self.tick_interval_seconds)

    def _tick(self) -> None:
        now = datetime.now()
        now_ts = time.time()

        # 1. Tick Backup Jobs
        jobs = self.db.list_jobs()
        for job in jobs:
            if not job.enabled or not job.id:
                continue

            should_run = False
            if job.next_run_at:
                try:
                    next_run_dt = datetime.fromisoformat(job.next_run_at)
                    if now >= next_run_dt:
                        should_run = True
                except Exception:
                    should_run = True
            else:
                next_dt = calculate_next_run(job, now)
                if next_dt:
                    self.db.update_job_status(job.id, next_run_at=next_dt.isoformat())
                    if now >= next_dt:
                        should_run = True

            if should_run:
                logger.info(f"Triggering scheduled backup for job {job.name} (ID: {job.id})")
                future_next = calculate_next_run(job, now + timedelta(seconds=30))
                self.db.update_job_status(
                    job.id,
                    next_run_at=future_next.isoformat() if future_next else None,
                )
                try:
                    self.job_runner_cb(job)
                except Exception as e:
                    logger.error(f"Failed to trigger job {job.name}: {e}", exc_info=True)

        # 2. Tick Sync Datasets (Interval & Periodic Reconciliation)
        if self.sync_runner_cb:
            datasets = self.db.list_sync_datasets()
            for d in datasets:
                if not d.enabled or d.paused:
                    continue

                should_sync = False
                last_run_ts = self._sync_last_reconcile.get(d.dataset_id, 0.0)

                if d.schedule_mode == "interval":
                    interval_sec = max(60, d.schedule_interval_minutes * 60)
                    if now_ts - last_run_ts >= interval_sec:
                        should_sync = True
                elif d.schedule_mode == "realtime":
                    # Periodic 30-min reconciliation scan
                    if now_ts - last_run_ts >= 1800:
                        should_sync = True

                if should_sync:
                    self._sync_last_reconcile[d.dataset_id] = now_ts
                    try:
                        self.sync_runner_cb(d.dataset_id)
                    except Exception as e:
                        logger.error(f"Scheduler failed to trigger sync for dataset {d.name}: {e}")

        # 3. Heartbeat tick (every 60s)
        if self.heartbeat_cb and (now_ts - self._last_heartbeat >= 60.0):
            self._last_heartbeat = now_ts
            try:
                self.heartbeat_cb()
            except Exception as e:
                logger.debug(f"Heartbeat tick error: {e}")

