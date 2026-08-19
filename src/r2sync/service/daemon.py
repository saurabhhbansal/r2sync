"""Background service engine orchestrating database, scheduler, engine, and IPC."""

import logging
import os
import signal
import sys
import threading
import time
from typing import Optional

from r2sync.core.backup_engine import BackupEngine
from r2sync.core.db import Database
from r2sync.core.models import SyncStatus
from r2sync.core.rclone_engine import RcloneBinaryManager, RcloneEngine
from r2sync.core.scheduler import JobScheduler
from r2sync.core.sync_engine import SyncEngine
from r2sync.notifications.notifier import NotificationManager
from r2sync.service.ipc_server import IPCServer
from r2sync.utils.logging import setup_logger
from r2sync.utils.paths import get_service_pid_path

logger = setup_logger(name="r2sync.service", file_prefix="service")


class ServiceDaemon:
    """Core daemon managing background backup and sync operations."""

    def __init__(self):
        self.db = Database()
        self.notifier = NotificationManager()
        self.rclone_engine = RcloneEngine()
        self.backup_engine = BackupEngine(
            db=self.db,
            rclone_engine=self.rclone_engine,
            notifier=self.notifier,
        )
        self.sync_engine = SyncEngine(
            db=self.db,
            rclone_engine=self.rclone_engine,
            notifier=self.notifier,
        )
        self.scheduler = JobScheduler(
            db=self.db,
            job_runner_cb=self._on_scheduler_trigger,
            sync_runner_cb=self._on_sync_trigger,
            heartbeat_cb=self._on_heartbeat_tick,
        )
        self.ipc_server = IPCServer(
            db=self.db,
            backup_engine=self.backup_engine,
            sync_engine=self.sync_engine,
            scheduler=self.scheduler,
        )
        self._stop_event = threading.Event()

    def _on_scheduler_trigger(self, job) -> None:
        logger.info(f"Scheduler triggered backup for job: {job.name} (ID: {job.id})")
        self.backup_engine.trigger_job_async(job)

    def _on_sync_trigger(self, dataset_id: str) -> None:
        logger.info(f"Scheduler triggered sync for dataset ID: {dataset_id}")
        self.sync_engine.trigger_sync_async(dataset_id)

    def _on_heartbeat_tick(self) -> None:
        datasets = self.db.list_sync_datasets()
        dev_id = self.db.get_or_create_device_id()
        for d in datasets:
            if d.enabled:
                self.db.update_device_heartbeat(dev_id, d.dataset_id, "online")


    def _write_pid(self) -> None:
        try:
            pid_path = get_service_pid_path()
            with open(pid_path, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
        except Exception as e:
            logger.warning(f"Could not write PID file: {e}")

    def _cleanup_pid(self) -> None:
        try:
            pid_path = get_service_pid_path()
            if pid_path.exists():
                pid_path.unlink()
        except Exception:
            pass

    def start(self) -> None:
        logger.info("Initializing r2sync background service...")
        self._write_pid()

        # Check Rclone binary
        if not RcloneBinaryManager.is_installed():
            logger.info("Rclone binary not detected. Attempting automatic download...")
            try:
                RcloneBinaryManager.download_and_install()
            except Exception as e:
                logger.warning(f"Initial Rclone download failed (will retry on first backup run): {e}")

        # Start Scheduler & IPC
        self.scheduler.start()
        self.ipc_server.start()

        # Recover active sync datasets on service restart
        datasets = self.db.list_sync_datasets()
        for d in datasets:
            if d.status == SyncStatus.SYNCING.value:
                self.db.update_sync_status(d.dataset_id, SyncStatus.WAITING.value)
            if d.enabled and not d.paused and d.schedule_mode == "realtime":
                if os.path.exists(d.local_path):
                    self.sync_engine.watcher_manager.start_watching(d.dataset_id, d.local_path, d.exclude_patterns)

        self.db.add_activity(
            level="INFO",
            category="service",
            message="r2sync background service started.",
        )
        logger.info("r2sync background service is active.")

    def stop(self) -> None:
        logger.info("Stopping r2sync background service...")
        self._stop_event.set()
        self.sync_engine.stop_all_watchers()
        self.scheduler.stop()
        self.ipc_server.stop()
        self._cleanup_pid()

        self.db.add_activity(
            level="INFO",
            category="service",
            message="r2sync background service stopped.",
        )
        logger.info("r2sync background service stopped cleanly.")

    def run_forever(self) -> None:
        self.start()

        def handle_signal(sig, frame):
            logger.info(f"Received shutdown signal {sig}")
            self.stop()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            while not self._stop_event.is_set():
                time.sleep(1.0)
        except (KeyboardInterrupt, SystemExit):
            self.stop()
