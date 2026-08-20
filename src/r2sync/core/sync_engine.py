"""Multi-PC cloud synchronization orchestration engine."""

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from r2sync.config import (
    CLOUDFLARE_PRICING_INFO_URL,
    CLOUDFLARE_R2_STORAGE_PRICE_PER_GB_MONTH,
    SYNC_MAX_CONCURRENT_DATASETS,
    SYNC_PROTOCOL_VERSION,
    SYNC_R2_ROOT,
)
from r2sync.core.credentials import get_r2_credentials
from r2sync.core.prescan import BackgroundEstimator, scan_local_tree
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
from r2sync.core.rclone_engine import RcloneBinaryManager, RcloneEngine, _canonical_fs_path
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
        # Datasets that changed while their sync was already in flight. Without
        # this, a file created during a running sync was simply dropped: the
        # debounced watcher event hit the "already syncing" guard and nothing
        # ever re-queued it.
        self._pending_syncs: Dict[str, Dict[str, Any]] = {}
        # Datasets that could not sync right now (offline) and must be
        # retried by the scheduler once conditions allow.
        self._deferred_syncs: Set[str] = set()
        # Datasets whose in-flight sync the user cancelled; suppresses the
        # automatic retry and follow-up paths for that run.
        self._cancel_requested: Set[str] = set()
        self.max_concurrent_syncs = max(1, SYNC_MAX_CONCURRENT_DATASETS)
        self._progress_listeners: List[Callable[[SyncProgressEvent], None]] = []
        self._completion_listeners: List[Callable[[SyncDataset, Dict[str, Any]], None]] = []
        self._lock = threading.RLock()

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
        """Stop the running sync and make sure nothing immediately restarts it.

        The retry and follow-up paths added for change coalescing would
        otherwise relaunch the transfer the instant the process was killed,
        making Cancel look like it did nothing.
        """
        logger.info(f"Requested cancellation of sync dataset: {dataset_id}")
        with self._lock:
            self._cancel_requested.add(dataset_id)
            self._pending_syncs.pop(dataset_id, None)
            self._deferred_syncs.discard(dataset_id)
        return self.rclone_engine.cancel_bisync(dataset_id)

    def is_cancel_requested(self, dataset_id: str) -> bool:
        with self._lock:
            return dataset_id in self._cancel_requested

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

    @staticmethod
    def dataset_wants_watcher(dataset: SyncDataset) -> bool:
        """True when this dataset should have a live filesystem watcher attached."""
        return bool(
            dataset.enabled
            and not dataset.paused
            and dataset.schedule_mode == SyncScheduleMode.REALTIME.value
        )

    def start_all_watchers(self) -> int:
        """Attach real-time watchers to every enabled, unpaused realtime dataset.

        Registration happens even when the folder is not present yet (an
        unmounted network or removable drive right after boot): the watcher
        manager keeps the registration and its supervisor attaches as soon as
        the path appears.
        """
        started = 0
        for d in self.db.list_sync_datasets():
            if not self.dataset_wants_watcher(d):
                continue
            if self.watcher_manager.start_watching(d.dataset_id, d.local_path, d.exclude_patterns):
                started += 1
            else:
                logger.warning(
                    f"Watcher for dataset '{d.name}' is pending: {d.local_path} is not available yet."
                )
        logger.info(f"Started {started} real-time watcher(s).")
        return started

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
        """Create a Sync dataset, register device, and perform initial synchronization.

        A folder this computer has synced before is reattached to the data it
        already has in R2 rather than started over -- see
        :meth:`_find_reattachable_dataset`.
        """
        import uuid

        local_abs = os.path.abspath(local_path.strip())

        # "new" is the caller saying it wants a second, independent copy.
        existing = (
            None if initial_action == "new"
            else self._find_reattachable_dataset(bucket_name.strip(), local_abs, name.strip())
        )
        dataset_id = existing.dataset_id if existing else uuid.uuid4().hex
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

        # "merge" and "replace" only ever differed when the other side already
        # held data, and until reattachment existed it never did: every add
        # made an empty prefix, so this argument has been accepted and ignored
        # since it was introduced. Reattaching gives it something to decide.
        # --resync never deletes, so "newer" keeps both sides.
        if existing is not None:
            resync_mode = "path1" if initial_action == "replace" else "newer"
            self.db.add_activity(
                "INFO", "sync",
                f"'{dataset.name}' reconnected to the copy already in R2 "
                f"({existing.total_files:,} files); no re-upload needed.",
            )
        else:
            resync_mode = "path1"

        # Launch initial sync in background
        self.trigger_sync_async(dataset_id, resync_mode=resync_mode, force_resync=True)
        return dataset

    def _find_reattachable_dataset(
        self, bucket_name: str, local_path: str, name: str
    ) -> Optional[RemoteDatasetInfo]:
        """The dataset in R2 this folder already syncs to, if there is one.

        Adding a folder used to mint a fresh dataset id unconditionally, which
        pointed at an empty prefix. Removing a sync and adding the same folder
        back therefore uploaded the whole folder a second time and left the
        first copy orphaned in the bucket -- still stored, still billed, no
        longer shown anywhere. Every dataset already publishes enough identity
        to recognise its own folder, so match on that instead of asking the
        user to pick their dataset out of a list; they have no way to know
        which one it is.

        Deliberately conservative. Only datasets this computer created are
        considered, and only an unambiguous match is returned: reattaching to
        the wrong dataset would merge two unrelated folders, which is far worse
        than uploading twice. Anything unexpected -- no credentials, no
        network, a bucket that will not list -- falls back to creating a new
        dataset, exactly as before.
        """
        try:
            remote = self.discover_remote_datasets(bucket_name)
        except Exception as e:
            logger.debug(f"Could not look for an existing remote dataset: {e}")
            return None

        dev_id = self.db.get_or_create_device_id()
        mine = [r for r in remote if r.created_by_device_id and r.created_by_device_id == dev_id]
        if not mine:
            return None

        target = _canonical_fs_path(local_path)
        candidates = [r for r in mine if r.local_path and _canonical_fs_path(r.local_path) == target]

        if not candidates:
            # Datasets created before the folder was published carry no path to
            # compare, and their name is the only identity left. Names are the
            # user's own words, so this is weaker than a path match -- it is a
            # fallback for existing datasets, not the intended route.
            wanted = name.strip().casefold()
            candidates = [
                r for r in mine if not r.local_path and r.name.strip().casefold() == wanted
            ]

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            logger.info(
                f"{len(candidates)} remote datasets match '{name}'; creating a new one rather "
                "than guessing which to reattach to."
            )
        return None

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
    ) -> bool:
        """Queue a synchronization of a dataset on a background worker thread.

        Exactly one sync per dataset runs at a time. A request that arrives
        while a sync is already running is *coalesced into a follow-up run*
        rather than discarded, so a file created mid-sync still reaches R2.

        Returns True if a worker was started now, False if the request was
        folded into the in-flight run or deferred behind the concurrency limit.
        """
        with self._lock:
            if dataset_id in self._active_syncs:
                pending = self._pending_syncs.setdefault(
                    dataset_id, {"resync_mode": None, "force_resync": False}
                )
                # A follow-up must be at least as strong as the strongest
                # request that was folded into it.
                pending["force_resync"] = pending["force_resync"] or force_resync
                pending["resync_mode"] = pending["resync_mode"] or resync_mode
                logger.info(
                    f"Sync for dataset {dataset_id} already in progress; "
                    "queued a follow-up run for the newer changes."
                )
                return False

            if len(self._active_syncs) >= self.max_concurrent_syncs:
                # Hold the dataset for the next scheduler tick instead of
                # adding another rclone process to an already-saturated link.
                self._deferred_syncs.add(dataset_id)
                logger.info(
                    f"Deferring sync for dataset {dataset_id}: "
                    f"{len(self._active_syncs)} sync(s) already running."
                )
                return False

            self._active_syncs[dataset_id] = {"started_at": time.time()}

        thread = threading.Thread(
            target=self._run_sync_worker,
            args=(dataset_id, resync_mode, force_resync),
            name=f"sync-worker-{dataset_id[:8]}",
            daemon=True,
        )
        thread.start()
        return True

    def has_pending_sync(self, dataset_id: str) -> bool:
        """True when a follow-up run is queued behind the current sync."""
        with self._lock:
            return dataset_id in self._pending_syncs

    def _finish_sync(self, dataset_id: str) -> None:
        """Release the per-dataset slot and start any coalesced follow-up run."""
        with self._lock:
            self._active_syncs.pop(dataset_id, None)
            pending = self._pending_syncs.pop(dataset_id, None)
            cancelled = dataset_id in self._cancel_requested
            self._cancel_requested.discard(dataset_id)

        if cancelled:
            logger.info(f"Sync for dataset {dataset_id} was cancelled; not re-queuing.")
            return

        if pending:
            logger.info(f"Running coalesced follow-up sync for dataset {dataset_id}")
            self.trigger_sync_async(
                dataset_id,
                resync_mode=pending.get("resync_mode"),
                force_resync=bool(pending.get("force_resync")),
            )

    def _run_sync_worker(
        self,
        dataset_id: str,
        resync_mode: Optional[str] = None,
        force_resync: bool = False,
    ) -> None:
        """Run one synchronization pass for a dataset.

        The whole body is wrapped so the per-dataset slot in ``_active_syncs``
        is always released. Previously an exception anywhere in here left the
        dataset permanently marked "syncing", and every later watcher event or
        scheduler tick for it was silently ignored for the lifetime of the
        process.
        """
        dataset: Optional[SyncDataset] = None
        result: Dict[str, Any] = {}
        try:
            dataset = self.db.get_sync_dataset(dataset_id)
            if not dataset:
                return
            result = self._execute_sync(dataset, resync_mode, force_resync)
        except Exception as e:
            logger.error(f"Unhandled error syncing dataset {dataset_id}: {e}", exc_info=True)
            result = {"success": False, "error_message": str(e)}
            try:
                self.db.update_sync_status(dataset_id, SyncStatus.ERROR.value, last_error=str(e))
                self.db.add_activity("ERROR", "sync", f"Sync failed unexpectedly: {e}")
            except Exception:
                logger.debug("Could not persist sync failure state", exc_info=True)
        finally:
            self._finish_sync(dataset_id)

        if dataset is not None:
            self._broadcast_completion(dataset, result)

    def _execute_sync(
        self,
        dataset: SyncDataset,
        resync_mode: Optional[str],
        force_resync: bool,
    ) -> Dict[str, Any]:
        dataset_id = dataset.dataset_id
        creds = get_r2_credentials()

        # Pre-check 1: Credentials
        if not creds or not creds.access_key_id or not creds.secret_access_key:
            self.db.update_sync_status(dataset_id, SyncStatus.ERROR.value, last_error="Missing R2 credentials")
            self.db.add_activity("ERROR", "sync", f"Sync failed for '{dataset.name}': Missing R2 credentials")
            return {"success": False, "error_message": "Missing R2 credentials"}

        # Pre-check 2: Local path
        if not os.path.exists(dataset.local_path):
            self.db.update_sync_status(dataset_id, SyncStatus.ERROR.value, last_error=f"Folder missing: {dataset.local_path}")
            self.db.add_activity("ERROR", "sync", f"Sync paused for '{dataset.name}': Local directory does not exist")
            return {"success": False, "error_message": f"Folder missing: {dataset.local_path}"}

        # Pre-check 3: Internet Connection. The dataset stays marked dirty so
        # the scheduler retries it as soon as the link comes back, instead of
        # waiting for the next unrelated filesystem change.
        if not check_internet_connection():
            self.db.update_sync_status(dataset_id, SyncStatus.OFFLINE.value, last_error="Waiting for network connection...")
            self.mark_needs_sync(dataset_id)
            return {"success": False, "offline": True, "error_message": "Waiting for network connection..."}

        # Pre-check 4: Rclone binary
        if not RcloneBinaryManager.is_installed():
            try:
                RcloneBinaryManager.download_and_install()
            except Exception as e:
                self.db.update_sync_status(dataset_id, SyncStatus.ERROR.value, last_error=f"Rclone missing: {e}")
                return {"success": False, "error_message": f"Rclone missing: {e}"}

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

        # Independent size estimate for the progress UI. It runs beside the
        # transfer and is never awaited, so it cannot delay the first byte.
        estimator = BackgroundEstimator(self.rclone_engine, dataset, creds).start()

        speed_prof = self.db.get_setting("speed_profile") or "turbo"

        def on_progress(p: SyncProgressEvent):
            est = estimator.estimate
            if est and not p.estimated_total_bytes:
                p.estimated_total_bytes = est.union_bytes
                p.estimated_total_files = est.union_files
            self._broadcast_progress(p)

        try:
            result = self.rclone_engine.run_bisync(
                dataset=dataset,
                resync_mode=resync_mode,
                force_resync=force_resync,
                progress_cb=on_progress,
                creds=creds,
                speed_profile=speed_prof,
                estimate=estimator.estimate,
            )

            # A critical bisync abort leaves the workdir listings unusable, so
            # every later incremental run would fail the same way. Rebuild the
            # baseline once. "newer" is used rather than the default "path1"
            # because recovery must not silently discard the other computer's
            # work; --resync never deletes, so both sides survive.
            if (
                result.get("needs_resync")
                and not result.get("did_resync")
                and not self.is_cancel_requested(dataset_id)
            ):
                logger.warning(
                    f"Bisync state for '{dataset.name}' is stale; rebuilding the baseline."
                )
                self.db.add_activity(
                    "WARNING", "sync",
                    f"Rebuilding synchronization baseline for '{dataset.name}' "
                    "(previous state was unusable).",
                )
                result = self.rclone_engine.run_bisync(
                    dataset=dataset,
                    resync_mode="newer",
                    force_resync=True,
                    progress_cb=on_progress,
                    creds=creds,
                    speed_profile=speed_prof,
                    estimate=estimator.estimate,
                )

            # bisync aborts when 100% of the tracked files changed on one side.
            # For a small folder that is just the user editing everything they
            # have, so retry once with --force. The --max-delete ceiling is
            # unaffected, so mass-deletion protection still applies.
            if (
                result.get("all_changed_abort")
                and not result.get("mass_deletion_triggered")
                and not self.is_cancel_requested(dataset_id)
            ):
                logger.warning(
                    f"Bisync reported that every file changed in '{dataset.name}'; "
                    "retrying once with --force."
                )
                self.db.add_activity(
                    "WARNING", "sync",
                    f"Every tracked file changed in '{dataset.name}'; retrying the sync.",
                )
                result = self.rclone_engine.run_bisync(
                    dataset=dataset,
                    resync_mode=resync_mode,
                    force_resync=force_resync,
                    progress_cb=on_progress,
                    creds=creds,
                    speed_profile=speed_prof,
                    estimate=estimator.estimate,
                    force=True,
                )
        finally:
            estimator.stop()

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
                # Persisting this is what lets the next run be a fast
                # incremental bisync. Without it every single sync re-ran with
                # --resync, which is slower and never propagates deletions.
                initial_sync_done=True,
            )

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

        elif result.get("empty_source_abort"):
            # Not treated as a plain error: the folder may simply be an
            # unmounted drive, and the user needs to decide before r2sync
            # propagates "everything is gone" to their other computers.
            self.db.update_sync_status(
                dataset_id=dataset_id,
                status=SyncStatus.NEEDS_ATTENTION.value,
                last_error=result.get("error_message"),
            )
            dataset.status = SyncStatus.NEEDS_ATTENTION.value
            self.db.add_activity(
                "WARNING", "sync",
                f"Sync paused for '{dataset.name}': one side of the folder is now empty.",
            )
            self.notifier.show_toast(
                title=f"Sync Paused: {dataset.name}",
                message="One side of this folder is now empty. Confirm before syncing.",
                notification_type="warning",
            )

        elif result.get("lock_conflict"):
            # A run of these same paths is still holding the bisync workdir
            # lock. That is a scheduling collision, not a fault in the dataset:
            # leave the previous status and error alone, keep the dataset marked
            # dirty, and let the scheduler pick it up on the next tick. It used
            # to be recorded as a hard error and raise a "Sync Failed" toast for
            # every attempt that landed during a long-running sync.
            logger.info(
                f"Sync for '{dataset.name}' skipped: another run holds the bisync lock. "
                "Queued for the next scheduler tick."
            )
            # _execute_sync flipped the row to "syncing" on the way in; without
            # this the dataset would sit on that status forever.
            waiting = SyncStatus.WAITING.value
            if dataset.status in (SyncStatus.SYNCED.value, SyncStatus.CONFLICT.value):
                waiting = dataset.status
            self.db.update_sync_status(dataset_id, waiting)
            dataset.status = waiting
            self.mark_needs_sync(dataset_id)

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

        # Re-attach the watcher without disturbing a debounce timer that may be
        # holding a change the user made while this sync was running.
        if self.dataset_wants_watcher(dataset):
            self.watcher_manager.ensure_watching(
                dataset_id, dataset.local_path, dataset.exclude_patterns
            )

        return result

    def mark_needs_sync(self, dataset_id: str) -> None:
        """Remember that a dataset still has unsynced work.

        Used when a sync cannot proceed right now (no network, or the service
        just started) so the next scheduler tick picks it back up rather than
        waiting for a new filesystem event that may never come.

        This deliberately does *not* go through ``_pending_syncs``: that path
        re-runs immediately when the current worker finishes, which for a
        still-offline dataset would spin. The scheduler's tick provides the
        backoff instead.
        """
        with self._lock:
            self._deferred_syncs.add(dataset_id)

    def take_deferred_syncs(self) -> List[str]:
        """Pop and return dataset ids that were deferred (e.g. while offline)."""
        with self._lock:
            deferred = sorted(self._deferred_syncs)
            self._deferred_syncs.clear()
        return deferred

    def _calc_folder_stats(self, local_path: str, exclude_patterns: List[str]) -> Tuple[int, int]:
        """Compute total non-excluded file count and total size in bytes.

        Shares the pre-scan's walker so the count matches what actually gets
        synchronized. This number also drives the deletion-safety percentage
        handed to bisync, so counting excluded files here would loosen that
        guard.
        """
        files, size, _complete = scan_local_tree(local_path, exclude_patterns)
        return files, size

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
