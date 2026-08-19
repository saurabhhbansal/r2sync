"""Multi-PC cloud synchronization orchestration engine."""

import logging
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from r2sync.config import (
    CLOUDFLARE_PRICING_INFO_URL,
    CLOUDFLARE_R2_STORAGE_PRICE_PER_GB_MONTH,
    SYNC_PROTOCOL_VERSION,
    SYNC_R2_ROOT,
)
from r2sync.core.credentials import get_r2_credentials
from r2sync.core.db import Database
from r2sync.core.models import (
    ConflictResolution,
    Device,
    R2Credentials,
    RemoteDatasetInfo,
    SyncConflict,
    SyncDataset,
    SyncProgressEvent,
    SyncScheduleMode,
    SyncStatus,
)
from r2sync.core.rclone_engine import RcloneBinaryManager, RcloneEngine
from r2sync.core.watcher import DebouncedWatcherManager
from r2sync.notifications.notifier import NotificationManager
from r2sync.utils.paths import get_dataset_bisync_dir
from r2sync.utils.system import check_internet_connection

logger = logging.getLogger(__name__)


def check_paths_overlap(path_a: str, path_b: str) -> bool:
    """Check if two directory paths are identical or nested within each other."""
    try:
        norm_a = os.path.abspath(os.path.normpath(path_a))
        norm_b = os.path.abspath(os.path.normpath(path_b))

        if norm_a == norm_b:
            return True

        # Check if norm_a is parent of norm_b or vice-versa
        try:
            rel = os.path.relpath(norm_b, norm_a)
            if not rel.startswith(".."):
                return True
        except ValueError:
            pass

        try:
            rel = os.path.relpath(norm_a, norm_b)
            if not rel.startswith(".."):
                return True
        except ValueError:
            pass

        return False
    except Exception:
        return False


class SyncEngine:
    """Orchestrates multi-PC bidirectional sync, change watching, conflicts, and device metadata."""

    def __init__(
        self,
        db: Database,
        rclone_engine: Optional[RcloneEngine] = None,
        notifier: Optional[NotificationManager] = None,
    ):
        self.db = db
        self.rclone_engine = rclone_engine or RcloneEngine()
        self.notifier = notifier or NotificationManager()
        self.watcher_manager = DebouncedWatcherManager(
            on_change_triggered=self._on_watcher_change_event
        )

        self._active_syncs: Dict[str, Dict[str, Any]] = {}
        self._progress_listeners: List[Callable[[SyncProgressEvent], None]] = []
        self._completion_listeners: List[Callable[[SyncDataset, Dict[str, Any]], None]] = []
        self._lock = threading.Lock()

    def add_progress_listener(self, listener: Callable[[SyncProgressEvent], None]) -> None:
        with self._lock:
            self._progress_listeners.append(listener)

    def remove_progress_listener(self, listener: Callable[[SyncProgressEvent], None]) -> None:
        with self._lock:
            if listener in self._progress_listeners:
                self._progress_listeners.remove(listener)

    def add_completion_listener(self, listener: Callable[[SyncDataset, Dict[str, Any]], None]) -> None:
        with self._lock:
            self._completion_listeners.append(listener)

    def remove_completion_listener(self, listener: Callable[[SyncDataset, Dict[str, Any]], None]) -> None:
        with self._lock:
            if listener in self._completion_listeners:
                self._completion_listeners.remove(listener)

    def _broadcast_progress(self, event: SyncProgressEvent) -> None:
        with self._lock:
            listeners = list(self._progress_listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception as e:
                logger.debug(f"Error in sync progress listener: {e}")

    def _broadcast_completion(self, dataset: SyncDataset, result: Dict[str, Any]) -> None:
        with self._lock:
            listeners = list(self._completion_listeners)
        for listener in listeners:
            try:
                listener(dataset, result)
            except Exception as e:
                logger.debug(f"Error in sync completion listener: {e}")

    def is_dataset_syncing(self, dataset_id: str) -> bool:
        with self._lock:
            return dataset_id in self._active_syncs

    def cancel_sync(self, dataset_id: str) -> bool:
        logger.info(f"Requested cancellation of sync dataset: {dataset_id}")
        return self.rclone_engine.cancel_bisync(dataset_id)

    def check_folder_overlap(self, candidate_path: str, exclude_dataset_id: Optional[str] = None) -> List[str]:
        """Check if candidate_path overlaps with existing backup jobs or sync datasets."""
        overlapping = []

        # Check backup jobs
        backup_jobs = self.db.list_jobs()
        for j in backup_jobs:
            if j.source_path and check_paths_overlap(candidate_path, j.source_path):
                overlapping.append(f"Backup Job: '{j.name}' ({j.source_path})")

        # Check sync datasets
        sync_datasets = self.db.list_sync_datasets()
        for s in sync_datasets:
            if exclude_dataset_id and s.dataset_id == exclude_dataset_id:
                continue
            if s.local_path and check_paths_overlap(candidate_path, s.local_path):
                overlapping.append(f"Sync Dataset: '{s.name}' ({s.local_path})")

        return overlapping

    def start_all_watchers(self) -> None:
        """Start real-time filesystem watchers for all enabled, active datasets."""
        datasets = self.db.list_sync_datasets()
        for d in datasets:
            if d.enabled and not d.paused and d.schedule_mode == SyncScheduleMode.REALTIME.value:
                if os.path.exists(d.local_path):
                    self.watcher_manager.start_watching(d.dataset_id, d.local_path, d.exclude_patterns)

    def stop_all_watchers(self) -> None:
        self.watcher_manager.stop_all()

    def _on_watcher_change_event(self, dataset_id: str) -> None:
        """Invoked when local filesystem watcher fires after debouncing."""
        dataset = self.db.get_sync_dataset(dataset_id)
        if dataset and dataset.enabled and not dataset.paused:
            logger.info(f"Local watcher triggering sync for dataset '{dataset.name}' ({dataset_id})")
            self.trigger_sync_async(dataset_id)

    # ---------------------------------------------------------
    # Dataset Lifecycle: Create / Join / Sync
    # ---------------------------------------------------------

    def create_and_init_dataset(
        self,
        name: str,
        local_path: str,
        bucket_name: str,
        schedule_mode: str = SyncScheduleMode.REALTIME.value,
        schedule_interval_minutes: int = 15,
        max_delete_threshold: int = 50,
        bandwidth_limit: Optional[str] = None,
        exclude_patterns: Optional[List[str]] = None,
        initial_action: str = "merge",  # "merge", "replace", "new"
    ) -> SyncDataset:
        """Create a brand new Sync dataset, register device, and perform initial synchronization."""
        import uuid

        dataset_id = uuid.uuid4().hex
        remote_prefix = f"{SYNC_R2_ROOT}/{dataset_id}"

        dataset = SyncDataset(
            dataset_id=dataset_id,
            name=name.strip(),
            bucket_name=bucket_name.strip(),
            remote_prefix=remote_prefix,
            local_path=os.path.abspath(local_path.strip()),
            schedule_mode=schedule_mode,
            schedule_interval_minutes=schedule_interval_minutes,
            max_delete_threshold=max_delete_threshold,
            bandwidth_limit=bandwidth_limit,
            exclude_patterns=exclude_patterns or [],
            status=SyncStatus.WAITING.value,
            enabled=True,
            paused=False,
            initial_sync_done=False,
        )

        # Save to SQLite
        self.db.create_sync_dataset(dataset)

        # Register local device
        dev_id = self.db.get_or_create_device_id()
        dev_name = self.db.get_device_name()
        current_dev = Device(
            device_id=dev_id,
            device_name=dev_name,
            dataset_id=dataset_id,
            is_current_device=True,
            status="online",
        )
        self.db.upsert_sync_device(current_dev)

        # Launch initial sync in background
        self.trigger_sync_async(dataset_id, resync_mode="path1", force_resync=True)
        return dataset

    def join_remote_dataset(
        self,
        remote_info: RemoteDatasetInfo,
        local_path: str,
        schedule_mode: str = SyncScheduleMode.REALTIME.value,
        schedule_interval_minutes: int = 15,
        max_delete_threshold: int = 50,
        bandwidth_limit: Optional[str] = None,
        exclude_patterns: Optional[List[str]] = None,
    ) -> SyncDataset:
        """Join an existing remote dataset discovered on Cloudflare R2 ('Set Up This PC')."""
        if remote_info.protocol_version > SYNC_PROTOCOL_VERSION:
            raise ValueError(
                f"Dataset protocol version {remote_info.protocol_version} is newer than supported version {SYNC_PROTOCOL_VERSION}. Please update r2sync."
            )

        local_p = os.path.abspath(local_path.strip())
        os.makedirs(local_p, exist_ok=True)

        remote_prefix = f"{SYNC_R2_ROOT}/{remote_info.dataset_id}"

        dataset = SyncDataset(
            dataset_id=remote_info.dataset_id,
            name=remote_info.name,
            bucket_name=remote_info.bucket_name,
            remote_prefix=remote_prefix,
            local_path=local_p,
            schedule_mode=schedule_mode,
            schedule_interval_minutes=schedule_interval_minutes,
            max_delete_threshold=max_delete_threshold,
            bandwidth_limit=bandwidth_limit,
            exclude_patterns=exclude_patterns or [],
            status=SyncStatus.WAITING.value,
            enabled=True,
            paused=False,
            initial_sync_done=False,
        )

        self.db.create_sync_dataset(dataset)

        # Register local device
        dev_id = self.db.get_or_create_device_id()
        dev_name = self.db.get_device_name()
        current_dev = Device(
            device_id=dev_id,
            device_name=dev_name,
            dataset_id=remote_info.dataset_id,
            is_current_device=True,
            status="online",
        )
        self.db.upsert_sync_device(current_dev)

        # Launch initial download sync in background (path2: R2 -> local)
        self.trigger_sync_async(remote_info.dataset_id, resync_mode="path2", force_resync=True)
        return dataset

    def trigger_sync_async(
        self,
        dataset_id: str,
        resync_mode: Optional[str] = None,
        force_resync: bool = False,
    ) -> None:
        """Trigger synchronization of a dataset asynchronously in a background thread."""
        with self._lock:
            if dataset_id in self._active_syncs:
                logger.info(f"Sync for dataset {dataset_id} is already in progress.")
                return
            self._active_syncs[dataset_id] = {"started_at": time.time()}

        thread = threading.Thread(
            target=self._run_sync_worker,
            args=(dataset_id, resync_mode, force_resync),
            name=f"sync-worker-{dataset_id[:8]}",
            daemon=True,
        )
        thread.start()

    def _run_sync_worker(
        self,
        dataset_id: str,
        resync_mode: Optional[str] = None,
        force_resync: bool = False,
    ) -> None:
        dataset = self.db.get_sync_dataset(dataset_id)
        if not dataset:
            with self._lock:
                self._active_syncs.pop(dataset_id, None)
            return

        creds = get_r2_credentials()

        # Pre-check 1: Credentials
        if not creds or not creds.access_key_id or not creds.secret_access_key:
            self.db.update_sync_status(dataset_id, SyncStatus.ERROR.value, last_error="Missing R2 credentials")
            self.db.add_activity("ERROR", "sync", f"Sync failed for '{dataset.name}': Missing R2 credentials")
            with self._lock:
                self._active_syncs.pop(dataset_id, None)
            return

        # Pre-check 2: Local path
        if not os.path.exists(dataset.local_path):
            self.db.update_sync_status(dataset_id, SyncStatus.ERROR.value, last_error=f"Folder missing: {dataset.local_path}")
            self.db.add_activity("ERROR", "sync", f"Sync paused for '{dataset.name}': Local directory does not exist")
            with self._lock:
                self._active_syncs.pop(dataset_id, None)
            return

        # Pre-check 3: Internet Connection
        if not check_internet_connection():
            self.db.update_sync_status(dataset_id, SyncStatus.OFFLINE.value, last_error="Waiting for network connection...")
            with self._lock:
                self._active_syncs.pop(dataset_id, None)
            return

        # Pre-check 4: Rclone binary
        if not RcloneBinaryManager.is_installed():
            try:
                RcloneBinaryManager.download_and_install()
            except Exception as e:
                self.db.update_sync_status(dataset_id, SyncStatus.ERROR.value, last_error=f"Rclone missing: {e}")
                with self._lock:
                    self._active_syncs.pop(dataset_id, None)
                return

        self.db.update_sync_status(dataset_id, SyncStatus.SYNCING.value)
        self.db.add_activity("INFO", "sync", f"Starting synchronization for '{dataset.name}'")

        dev_id = self.db.get_or_create_device_id()
        dev_name = self.db.get_device_name()
        current_dev = Device(
            device_id=dev_id,
            device_name=dev_name,
            dataset_id=dataset_id,
            is_current_device=True,
            status="syncing",
            last_seen_at=datetime.now().isoformat(),
        )

        # Upload metadata & device registration to R2
        try:
            self.rclone_engine.upload_dataset_metadata(dataset, current_dev, creds)
            self.rclone_engine.register_remote_device(dataset, current_dev, creds)
        except Exception as e:
            logger.debug(f"Could not update remote metadata for {dataset_id}: {e}")

        # Progress Callback
        def on_progress(p: SyncProgressEvent):
            self._broadcast_progress(p)

        # Execute Bisync
        result = self.rclone_engine.run_bisync(
            dataset=dataset,
            resync_mode=resync_mode,
            force_resync=force_resync,
            progress_cb=on_progress,
            creds=creds,
        )

        now_str = datetime.now().isoformat()
        current_dev.status = "online"
        current_dev.last_sync_at = now_str
        current_dev.last_seen_at = now_str
        self.db.upsert_sync_device(current_dev)

        try:
            self.rclone_engine.register_remote_device(dataset, current_dev, creds)
        except Exception:
            pass

        # Check for generated conflict files or bisync conflict reports
        self._scan_and_record_conflicts(dataset)

        unresolved = self.db.count_unresolved_conflicts(dataset_id)

        if result.get("success"):
            # Update local dataset state
            dataset.initial_sync_done = True
            final_status = SyncStatus.CONFLICT.value if unresolved > 0 else SyncStatus.SYNCED.value

            # Calculate local files and size
            cnt, sz = self._calc_folder_stats(dataset.local_path, dataset.exclude_patterns)
            self.db.update_sync_status(
                dataset_id=dataset_id,
                status=final_status,
                last_sync_at=now_str,
                last_error=None,
                total_files=cnt,
                total_bytes=sz,
            )

            # Update dataset record in memory
            dataset.status = final_status
            dataset.last_sync_at = now_str
            dataset.total_files = cnt
            dataset.total_bytes = sz

            mb = round(result.get("bytes_transferred", 0) / (1024 * 1024), 2)
            msg = f"Sync '{dataset.name}' completed: {result.get('files_transferred', 0)} files ({mb} MB) synced in {result.get('duration_seconds', 0.0)}s"
            self.db.add_activity("INFO", "sync", msg)

            if unresolved > 0:
                self.notifier.show_toast(
                    title=f"Conflict in {dataset.name}",
                    message=f"{unresolved} file conflict(s) detected and saved as conflict copies.",
                    notification_type="warning",
                )
            elif result.get("files_transferred", 0) > 0 or result.get("files_deleted", 0) > 0:
                self.notifier.show_toast(
                    title=f"Sync Completed: {dataset.name}",
                    message=f"Synced {result.get('files_transferred', 0)} files in {result.get('duration_seconds', 0.0)}s.",
                    notification_type="success",
                )

            # Start watcher if realtime mode and not already running
            if dataset.schedule_mode == SyncScheduleMode.REALTIME.value and not dataset.paused:
                self.watcher_manager.start_watching(dataset_id, dataset.local_path, dataset.exclude_patterns)

        elif result.get("mass_deletion_triggered"):
            self.db.update_sync_status(
                dataset_id=dataset_id,
                status=SyncStatus.NEEDS_ATTENTION.value,
                last_error=result.get("error_message"),
            )
            dataset.status = SyncStatus.NEEDS_ATTENTION.value
            msg = f"Potentially dangerous change detected in '{dataset.name}': Deletion safety threshold reached. Sync paused to protect your files."
            self.db.add_activity("WARNING", "sync", msg)
            self.notifier.show_toast(
                title=f"Sync Paused: {dataset.name}",
                message="Potentially dangerous change: Deletion safety threshold reached.",
                notification_type="warning",
            )

        else:
            err_msg = result.get("error_message") or "Unknown synchronization error"
            final_status = SyncStatus.CONFLICT.value if unresolved > 0 else SyncStatus.ERROR.value
            self.db.update_sync_status(dataset_id, final_status, last_error=err_msg)
            dataset.status = final_status
            self.db.add_activity("ERROR", "sync", f"Sync failed for '{dataset.name}': {err_msg}")
            self.notifier.show_toast(
                title=f"Sync Failed: {dataset.name}",
                message=err_msg[:100],
                notification_type="error",
            )

        with self._lock:
            self._active_syncs.pop(dataset_id, None)

        self._broadcast_completion(dataset, result)

    def _calc_folder_stats(self, local_path: str, exclude_patterns: List[str]) -> Tuple[int, int]:
        """Compute total non-excluded file count and total size in bytes."""
        total_files = 0
        total_bytes = 0
        try:
            for root, dirs, files in os.walk(local_path):
                rel_root = os.path.relpath(root, local_path)
                if rel_root != "." and (rel_root.startswith(".r2sync_trash") or rel_root.startswith(".git")):
                    dirs[:] = []
                    continue
                for f in files:
                    if f.startswith("~$") or f.endswith(".tmp") or f.endswith(".partial"):
                        continue
                    full_p = os.path.join(root, f)
                    try:
                        total_bytes += os.path.getsize(full_p)
                        total_files += 1
                    except OSError:
                        pass
        except Exception:
            pass
        return total_files, total_bytes

    def _scan_and_record_conflicts(self, dataset: SyncDataset) -> None:
        """Scan dataset folder for deterministic conflict files and record them in the database."""
        base = Path(dataset.local_path)
        if not base.exists():
            return

        now_str = datetime.now().isoformat()

        try:
            for root, _, files in os.walk(str(base)):
                for f in files:
                    if "conflict" in f.lower() or ".conflict." in f.lower():
                        full_conflict_path = os.path.join(root, f)
                        rel_conflict_path = os.path.relpath(full_conflict_path, str(base))

                        # Attempt to derive original relative path
                        # e.g., 'report (conflict - Laptop - 2026-08-19).docx' -> 'report.docx'
                        # or 'report.conflict.docx' -> 'report.docx'
                        orig_rel = rel_conflict_path
                        if " (conflict" in rel_conflict_path:
                            before = rel_conflict_path.split(" (conflict")[0]
                            ext = os.path.splitext(rel_conflict_path)[1]
                            orig_rel = before + ext

                        orig_full = os.path.join(str(base), orig_rel)
                        local_mtime = now_str
                        local_size = 0
                        if os.path.exists(orig_full):
                            try:
                                local_size = os.path.getsize(orig_full)
                                local_mtime = datetime.fromtimestamp(os.path.getmtime(orig_full)).isoformat()
                            except Exception:
                                pass

                        remote_size = 0
                        if os.path.exists(full_conflict_path):
                            try:
                                remote_size = os.path.getsize(full_conflict_path)
                            except Exception:
                                pass

                        # Check if conflict already logged
                        existing = [
                            c for c in self.db.list_conflicts(dataset.dataset_id, include_resolved=False)
                            if c.conflict_file_path == full_conflict_path or c.relative_path == orig_rel
                        ]

                        if not existing:
                            conflict = SyncConflict(
                                dataset_id=dataset.dataset_id,
                                relative_path=orig_rel,
                                local_path=orig_full,
                                local_modified_at=local_mtime,
                                local_size_bytes=local_size,
                                remote_device_name="Connected Computer",
                                remote_modified_at=now_str,
                                remote_size_bytes=remote_size,
                                conflict_file_path=full_conflict_path,
                                detected_at=now_str,
                                resolved=False,
                            )
                            self.db.create_conflict(conflict)
                            self.db.add_activity("WARNING", "conflict", f"File conflict detected in '{orig_rel}'", job_id=None)
        except Exception as e:
            logger.debug(f"Error scanning conflicts for {dataset.dataset_id}: {e}")

    # ---------------------------------------------------------
    # Conflict Resolution
    # ---------------------------------------------------------

    def resolve_conflict(self, conflict_id: int, resolution: str) -> bool:
        """Resolve a file conflict with Keep Local, Keep Remote, or Keep Both."""
        conflict = self.db.get_conflict(conflict_id)
        if not conflict:
            return False

        dataset = self.db.get_sync_dataset(conflict.dataset_id)
        local_file = conflict.local_path
        conflict_file = conflict.conflict_file_path

        try:
            if resolution == ConflictResolution.KEEP_LOCAL.value:
                # Keep local original, remove the conflict file
                if conflict_file and os.path.exists(conflict_file):
                    os.remove(conflict_file)
                self.db.resolve_conflict_db(conflict_id, "keep_local")
                self.db.add_activity("INFO", "conflict", f"Resolved conflict on '{conflict.relative_path}' (Kept local version)")

            elif resolution == ConflictResolution.KEEP_REMOTE.value:
                # Replace local original with the conflict file version
                if conflict_file and os.path.exists(conflict_file):
                    shutil.move(conflict_file, local_file)
                self.db.resolve_conflict_db(conflict_id, "keep_remote")
                self.db.add_activity("INFO", "conflict", f"Resolved conflict on '{conflict.relative_path}' (Kept remote version)")

            elif resolution == ConflictResolution.KEEP_BOTH.value:
                # Retain both files on disk, simply mark conflict resolved in DB
                self.db.resolve_conflict_db(conflict_id, "keep_both")
                self.db.add_activity("INFO", "conflict", f"Resolved conflict on '{conflict.relative_path}' (Kept both versions)")

            # If no more unresolved conflicts, update dataset status
            remaining = self.db.count_unresolved_conflicts(conflict.dataset_id)
            if remaining == 0 and dataset and dataset.status == SyncStatus.CONFLICT.value:
                self.db.update_sync_status(conflict.dataset_id, SyncStatus.SYNCED.value)

            # Trigger quick reconciliation sync
            self.trigger_sync_async(conflict.dataset_id)
            return True

        except Exception as e:
            logger.error(f"Failed to resolve conflict {conflict_id}: {e}")
            return False

    # ---------------------------------------------------------
    # Remote Device & Discovery Operations
    # ---------------------------------------------------------

    def discover_remote_datasets(self, bucket_name: Optional[str] = None) -> List[RemoteDatasetInfo]:
        """Discover available datasets on connected Cloudflare R2 bucket."""
        creds = get_r2_credentials()
        if not creds:
            return []
        bkt = bucket_name or creds.default_bucket or ""
        if not bkt:
            buckets = self.rclone_engine.list_buckets(creds)
            if buckets:
                bkt = buckets[0]
            else:
                return []

        return self.rclone_engine.discover_remote_datasets(bkt, creds)

    def refresh_connected_devices(self, dataset_id: str) -> List[Device]:
        """Fetch remote device registrations from R2 and synchronize into local SQLite."""
        dataset = self.db.get_sync_dataset(dataset_id)
        if not dataset:
            return []
        creds = get_r2_credentials()
        if not creds:
            return self.db.list_sync_devices(dataset_id)

        try:
            remote_devices = self.rclone_engine.fetch_remote_devices(dataset, creds)
            curr_dev_id = self.db.get_or_create_device_id()

            for dev in remote_devices:
                if dev.device_id == curr_dev_id:
                    dev.is_current_device = True
                self.db.upsert_sync_device(dev)
        except Exception as e:
            logger.debug(f"Error fetching remote devices for {dataset_id}: {e}")

        return self.db.list_sync_devices(dataset_id)

    def remove_device(self, dataset_id: str, device_id: str) -> bool:
        """Remove a computer registration from R2 and local DB without deleting shared files."""
        dataset = self.db.get_sync_dataset(dataset_id)
        if not dataset:
            return False
        creds = get_r2_credentials()
        if creds:
            try:
                self.rclone_engine.remove_remote_device(dataset, device_id, creds)
            except Exception as e:
                logger.warning(f"Could not delete remote device file in R2: {e}")

        self.db.delete_sync_device(device_id, dataset_id)
        self.db.add_activity("INFO", "sync", f"Removed computer '{device_id}' from dataset '{dataset.name}'")
        return True

    def delete_dataset(self, dataset_id: str, delete_remote_files: bool = False) -> bool:
        """Delete local dataset configuration. Optionally purge remote R2 data."""
        dataset = self.db.get_sync_dataset(dataset_id)
        if not dataset:
            return False

        self.watcher_manager.stop_watching(dataset_id)
        self.cancel_sync(dataset_id)

        if delete_remote_files:
            creds = get_r2_credentials()
            if creds:
                try:
                    exe = RcloneBinaryManager.get_executable_path()
                    env = self.rclone_engine._build_env(creds)
                    flags = 0x08000000 if sys.platform == "win32" else 0
                    subprocess.run(
                        [str(exe), "purge", f"r2:{dataset.bucket_name}/{dataset.remote_prefix}"],
                        env=env,
                        capture_output=True,
                        timeout=30,
                        creationflags=flags,
                    )
                except Exception as e:
                    logger.warning(f"Error purging remote dataset files: {e}")

        # Delete local bisync state directory
        workdir = get_dataset_bisync_dir(dataset_id)
        if workdir.exists():
            shutil.rmtree(str(workdir), ignore_errors=True)

        self.db.delete_sync_dataset(dataset_id)
        self.db.add_activity("INFO", "sync", f"Deleted sync dataset '{dataset.name}'")
        return True
