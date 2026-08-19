"""High-level backup orchestration engine with retries and state management."""

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from r2sync.core.credentials import get_r2_credentials
from r2sync.core.db import Database
from r2sync.core.models import (
    ActivityLog,
    BackupJob,
    BackupRun,
    FileTransfer,
    RunStatus,
    TransferProgressEvent,
)
from r2sync.core.rclone_engine import RcloneBinaryManager, RcloneEngine, RcloneNotFoundError
from r2sync.notifications.notifier import NotificationManager
from r2sync.utils.system import check_internet_connection

logger = logging.getLogger(__name__)


class BackupEngine:
    """Orchestrates backup runs, handles retries, persists state, and notifies listeners."""

    def __init__(
        self,
        db: Database,
        rclone_engine: Optional[RcloneEngine] = None,
        notifier: Optional[NotificationManager] = None,
    ):
        self.db = db
        self.rclone_engine = rclone_engine or RcloneEngine()
        self.notifier = notifier or NotificationManager()
        self._running_jobs: Dict[int, BackupRun] = {}
        self._progress_listeners: List[Callable[[TransferProgressEvent], None]] = []
        self._completion_listeners: List[Callable[[BackupRun], None]] = []
        self._lock = threading.Lock()

    def add_progress_listener(self, listener: Callable[[TransferProgressEvent], None]) -> None:
        with self._lock:
            self._progress_listeners.append(listener)

    def remove_progress_listener(self, listener: Callable[[TransferProgressEvent], None]) -> None:
        with self._lock:
            if listener in self._progress_listeners:
                self._progress_listeners.remove(listener)

    def add_completion_listener(self, listener: Callable[[BackupRun], None]) -> None:
        with self._lock:
            self._completion_listeners.append(listener)

    def remove_completion_listener(self, listener: Callable[[BackupRun], None]) -> None:
        with self._lock:
            if listener in self._completion_listeners:
                self._completion_listeners.remove(listener)

    def _broadcast_progress(self, event: TransferProgressEvent) -> None:
        with self._lock:
            listeners = list(self._progress_listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception as e:
                logger.debug(f"Error in progress listener: {e}")

    def _broadcast_completion(self, run: BackupRun) -> None:
        with self._lock:
            listeners = list(self._completion_listeners)
        for listener in listeners:
            try:
                listener(run)
            except Exception as e:
                logger.debug(f"Error in completion listener: {e}")

    def is_job_running(self, job_id: int) -> bool:
        with self._lock:
            return job_id in self._running_jobs

    def cancel_job(self, job_id: int) -> bool:
        logger.info(f"Requested cancelation of job ID {job_id}")
        return self.rclone_engine.cancel_run(job_id)

    def trigger_job_async(self, job: BackupJob, max_retries: int = 2) -> None:
        """Launch a backup job in a background worker thread."""
        if not job.id:
            logger.error("Cannot run a job without an ID")
            return

        with self._lock:
            if job.id in self._running_jobs:
                logger.warning(f"Job {job.name} (ID: {job.id}) is already running")
                return

        thread = threading.Thread(
            target=self._run_job_with_retries,
            args=(job, max_retries),
            name=f"backup-worker-{job.id}",
            daemon=True,
        )
        thread.start()

    def _run_job_with_retries(self, job: BackupJob, max_retries: int = 2) -> BackupRun:
        job_id = job.id or 0
        run_record = BackupRun(
            job_id=job_id,
            job_name=job.name,
            status=RunStatus.PENDING.value,
        )
        run_id = self.db.create_run(run_record)
        run_record.id = run_id

        with self._lock:
            self._running_jobs[job_id] = run_record

        self.db.add_activity(
            level="INFO",
            category="backup",
            message=f"Starting backup job '{job.name}'",
            job_id=job_id,
            run_id=run_id,
        )

        creds = get_r2_credentials()
        attempt = 0
        final_run = run_record

        while attempt <= max_retries:
            attempt += 1

            # Pre-check 1: Credentials
            if not creds or not creds.access_key_id or not creds.secret_access_key:
                final_run.status = RunStatus.FAILED.value
                final_run.error_message = "Cloudflare R2 credentials are missing or incomplete."
                break

            # Pre-check 2: Source Path
            if not os.path.exists(job.source_path):
                final_run.status = RunStatus.FAILED.value
                final_run.error_message = f"Source directory does not exist: {job.source_path}"
                break

            # Pre-check 3: Rclone Binary
            if not RcloneBinaryManager.is_installed():
                try:
                    logger.info("Rclone not installed. Downloading binary...")
                    RcloneBinaryManager.download_and_install()
                except Exception as e:
                    final_run.status = RunStatus.FAILED.value
                    final_run.error_message = f"Failed to install Rclone engine: {e}"
                    break

            # Pre-check 4: Network connectivity
            if not check_internet_connection():
                if attempt <= max_retries:
                    logger.warning(f"No internet connection. Retrying in 15 seconds (attempt {attempt}/{max_retries})...")
                    time.sleep(15)
                    continue
                else:
                    final_run.status = RunStatus.FAILED.value
                    final_run.error_message = "No internet connection available."
                    break

            # Execute backup
            speed_prof = self.db.get_setting("speed_profile") or "turbo"

            def on_progress(p: TransferProgressEvent):
                self._broadcast_progress(p)

            def on_file_transfer(ft: FileTransfer):
                self.db.add_transfer(ft)

            final_run = self.rclone_engine.run_backup(
                job=job,
                run_record=run_record,
                progress_cb=on_progress,
                file_transfer_cb=on_file_transfer,
                creds=creds,
                speed_profile=speed_prof,
            )

            # If completed or canceled, do not retry
            if final_run.status in (RunStatus.COMPLETED.value, RunStatus.CANCELED.value):
                break

            # If failed, retry with backoff if attempts remain
            if attempt <= max_retries:
                logger.warning(f"Job '{job.name}' failed on attempt {attempt}. Retrying in 10s...")
                time.sleep(10)

        # Update database with final run record
        self.db.update_run(final_run)
        self.db.update_job_status(
            job_id=job_id,
            last_run_at=datetime.now().isoformat(),
            last_status=final_run.status,
        )

        # Log completion
        if final_run.status == RunStatus.COMPLETED.value:
            mb = round(final_run.bytes_transferred / (1024 * 1024), 2)
            msg = f"Backup '{job.name}' completed: {final_run.files_transferred} files ({mb} MB) in {final_run.duration_seconds}s"
            self.db.add_activity("INFO", "backup", msg, job_id=job_id, run_id=run_id)
            self.notifier.show_toast(
                title=f"Backup Completed: {job.name}",
                message=f"Transferred {final_run.files_transferred} files ({mb} MB) in {final_run.duration_seconds}s.",
                notification_type="success",
            )
        elif final_run.status == RunStatus.CANCELED.value:
            msg = f"Backup '{job.name}' was canceled."
            self.db.add_activity("WARNING", "backup", msg, job_id=job_id, run_id=run_id)
        else:
            msg = f"Backup '{job.name}' failed: {final_run.error_message}"
            self.db.add_activity("ERROR", "backup", msg, job_id=job_id, run_id=run_id)
            self.notifier.show_toast(
                title=f"Backup Failed: {job.name}",
                message=final_run.error_message or "An error occurred during synchronization.",
                notification_type="error",
            )

        with self._lock:
            self._running_jobs.pop(job_id, None)

        self._broadcast_completion(final_run)
        return final_run
