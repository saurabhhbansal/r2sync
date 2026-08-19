"""Threaded IPC server providing JSON-RPC API and event broadcasting over local loopback."""

import json
import logging
import os
import secrets
import socket
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from r2sync.config import APP_VERSION, IPC_DEFAULT_PORT, IPC_HOST
from r2sync.core.backup_engine import BackupEngine
from r2sync.core.credentials import (
    delete_r2_credentials,
    get_r2_credentials,
    has_r2_credentials,
    save_r2_credentials,
)
from r2sync.core.db import Database
from r2sync.core.models import (
    BackupJob,
    BackupRun,
    RemoteDatasetInfo,
    SyncConflict,
    SyncDataset,
    SyncProgressEvent,
    TransferProgressEvent,
)
from r2sync.core.r2_client import CloudflareR2Client
from r2sync.core.rclone_engine import RcloneBinaryManager
from r2sync.core.scheduler import JobScheduler
from r2sync.core.sync_engine import SyncEngine
from r2sync.utils.paths import get_ipc_token_path

logger = logging.getLogger(__name__)


class IPCServer:
    """Local IPC Server for communication between r2sync GUI and background service."""

    def __init__(
        self,
        db: Database,
        backup_engine: BackupEngine,
        scheduler: JobScheduler,
        sync_engine: Optional[SyncEngine] = None,
        host: str = IPC_HOST,
        port: int = IPC_DEFAULT_PORT,
    ):
        self.db = db
        self.backup_engine = backup_engine
        self.sync_engine = sync_engine or SyncEngine(db=db, rclone_engine=backup_engine.rclone_engine)
        self.scheduler = scheduler
        self.host = host
        self.port = port
        self.r2_client = CloudflareR2Client(backup_engine.rclone_engine)

        self._server_socket: Optional[socket.socket] = None
        self._clients: List[socket.socket] = []
        self._clients_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._server_thread: Optional[threading.Thread] = None
        self.auth_token = self._generate_or_load_token()

        self.backup_engine.add_progress_listener(self._on_job_progress)
        self.backup_engine.add_completion_listener(self._on_job_completed)
        self.sync_engine.add_progress_listener(self._on_sync_progress)
        self.sync_engine.add_completion_listener(self._on_sync_completed)


    def _generate_or_load_token(self) -> str:
        token_path = get_ipc_token_path()
        token = secrets.token_hex(32)
        try:
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(token)
            if hasattr(os, "chmod") and sys.platform != "win32":
                os.chmod(token_path, 0o600)
        except Exception as e:
            logger.warning(f"Could not persist IPC auth token: {e}")
        return token

    def start(self) -> None:
        self._stop_event.clear()
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(10)
        self._server_socket.settimeout(1.0)

        self._server_thread = threading.Thread(target=self._accept_loop, name="r2sync-ipc-server", daemon=True)
        self._server_thread.start()
        logger.info(f"IPC Server listening on {self.host}:{self.port}")

    def stop(self) -> None:
        self._stop_event.set()
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass

        with self._clients_lock:
            for client in self._clients:
                try:
                    client.close()
                except Exception:
                    pass
            self._clients.clear()

        if self._server_thread:
            self._server_thread.join(timeout=3.0)
            self._server_thread = None
            logger.info("IPC Server stopped.")

    def _accept_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                client_sock, _ = self._server_socket.accept()
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock,),
                    daemon=True,
                )
                client_thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if not self._stop_event.is_set():
                    logger.debug(f"IPC accept error: {e}")

    def _handle_client(self, client_sock: socket.socket) -> None:
        with self._clients_lock:
            self._clients.append(client_sock)

        client_file = client_sock.makefile("r", encoding="utf-8", errors="replace")

        try:
            for line in client_file:
                if not line or self._stop_event.is_set():
                    break
                line = line.strip()
                if not line:
                    continue

                try:
                    req = json.loads(line)
                    req_id = req.get("id")
                    method = req.get("method")
                    params = req.get("params", {})
                    token = req.get("auth_token")

                    if token != self.auth_token:
                        resp = {"id": req_id, "error": "Unauthorized: Invalid IPC token", "result": None}
                        client_sock.sendall((json.dumps(resp) + chr(10)).encode("utf-8"))
                        continue

                    result, err = self._dispatch_method(method, params)
                    resp = {"id": req_id, "result": result, "error": err}
                    client_sock.sendall((json.dumps(resp) + chr(10)).encode("utf-8"))

                except json.JSONDecodeError:
                    resp = {"id": None, "error": "Malformed JSON", "result": None}
                    client_sock.sendall((json.dumps(resp) + chr(10)).encode("utf-8"))

        except Exception as e:
            logger.debug(f"Client disconnected: {e}")
        finally:
            with self._clients_lock:
                if client_sock in self._clients:
                    self._clients.remove(client_sock)
            try:
                client_sock.close()
            except Exception:
                pass

    def _broadcast_event(self, event_type: str, data: Any) -> None:
        payload = json.dumps({"event": event_type, "data": data}) + chr(10)
        encoded = payload.encode("utf-8")

        with self._clients_lock:
            dead_clients = []
            for client in self._clients:
                try:
                    client.sendall(encoded)
                except Exception:
                    dead_clients.append(client)
            for dead in dead_clients:
                if dead in self._clients:
                    self._clients.remove(dead)

    def _on_job_progress(self, progress: TransferProgressEvent) -> None:
        self._broadcast_event("job_progress", progress.to_dict())

    def _on_job_completed(self, run: BackupRun) -> None:
        self._broadcast_event("job_completed", run.to_dict())

    def _on_sync_progress(self, progress: SyncProgressEvent) -> None:
        self._broadcast_event("sync_progress", progress.to_dict())

    def _on_sync_completed(self, dataset: SyncDataset, result: Dict[str, Any]) -> None:
        self._broadcast_event("sync_completed", {"dataset": dataset.to_dict(), "result": result})


    def _dispatch_method(self, method: str, params: Dict[str, Any]) -> tuple[Any, Optional[str]]:
        try:
            if method == "ping":
                return {
                    "status": "ok",
                    "version": APP_VERSION,
                    "service_running": True,
                    "rclone_installed": RcloneBinaryManager.is_installed(),
                    "has_credentials": has_r2_credentials(),
                }, None

            elif method == "get_summary_stats":
                return self.db.get_summary_stats(), None

            elif method == "list_jobs":
                jobs = self.db.list_jobs()
                return [j.to_dict() for j in jobs], None

            elif method == "get_job":
                job_id = params.get("id")
                job = self.db.get_job(job_id)
                return job.to_dict() if job else None, None

            elif method == "create_job":
                job = BackupJob.from_dict(params.get("job", {}))
                job_id = self.db.create_job(job)
                self.scheduler.update_all_next_runs()
                return job_id, None

            elif method == "update_job":
                job = BackupJob.from_dict(params.get("job", {}))
                success = self.db.update_job(job)
                self.scheduler.update_all_next_runs()
                return success, None

            elif method == "delete_job":
                job_id = params.get("id")
                success = self.db.delete_job(job_id)
                return success, None

            elif method == "run_job_now":
                job_id = params.get("id")
                job = self.db.get_job(job_id)
                if not job:
                    return False, f"Job {job_id} not found"
                self.backup_engine.trigger_job_async(job)
                return True, None

            elif method == "cancel_job":
                job_id = params.get("id")
                success = self.backup_engine.cancel_job(job_id)
                return success, None

            elif method == "list_runs":
                limit = params.get("limit", 50)
                offset = params.get("offset", 0)
                job_id = params.get("job_id")
                runs = self.db.list_runs(limit=limit, offset=offset, job_id=job_id)
                return [r.to_dict() for r in runs], None

            elif method == "list_transfers":
                run_id = params.get("run_id")
                limit = params.get("limit", 200)
                transfers = self.db.list_transfers_for_run(run_id=run_id, limit=limit)
                return [t.to_dict() for t in transfers], None

            elif method == "list_activities":
                limit = params.get("limit", 100)
                category = params.get("category")
                logs = self.db.list_activities(limit=limit, category=category)
                return [l.to_dict() for l in logs], None

            elif method == "get_active_runs":
                active = self.db.get_active_runs()
                return [r.to_dict() for r in active], None

            elif method == "test_r2_connection":
                account_id = params.get("account_id")
                access_key_id = params.get("access_key_id")
                secret_access_key = params.get("secret_access_key")
                default_bucket = params.get("default_bucket")
                from r2sync.core.models import R2Credentials
                test_creds = R2Credentials(
                    account_id=account_id,
                    access_key_id=access_key_id,
                    secret_access_key=secret_access_key,
                    default_bucket=default_bucket,
                )
                return self.r2_client.test_connection(test_creds), None

            elif method == "list_buckets":
                buckets = self.r2_client.list_buckets()
                return [b.to_dict() for b in buckets], None

            elif method == "get_bucket_details":
                bucket_name = params.get("bucket_name")
                details = self.r2_client.get_bucket_details(bucket_name)
                return details.to_dict(), None

            elif method == "create_bucket":
                bucket_name = params.get("bucket_name")
                res = self.r2_client.create_bucket(bucket_name)
                return res, None

            elif method == "save_credentials":
                account_id = params.get("account_id")
                access_key_id = params.get("access_key_id")
                secret_access_key = params.get("secret_access_key")
                default_bucket = params.get("default_bucket")
                success = save_r2_credentials(
                    account_id=account_id,
                    access_key_id=access_key_id,
                    secret_access_key=secret_access_key,
                    default_bucket=default_bucket,
                )
                return success, None

            elif method == "has_credentials":
                return has_r2_credentials(), None

            elif method == "get_settings":
                return self.db.get_all_settings(), None

            elif method == "set_setting":
                key = params.get("key")
                val = params.get("value")
                self.db.set_setting(key, val)
                return True, None

            elif method == "download_rclone":
                exe = RcloneBinaryManager.download_and_install()
                return {"installed": True, "path": str(exe), "version": RcloneBinaryManager.get_version(exe)}, None

            elif method == "get_rclone_status":
                installed = RcloneBinaryManager.is_installed()
                ver = RcloneBinaryManager.get_version() if installed else "Not installed"
                return {"installed": installed, "version": ver}, None

            # ---------------------------------------------------------
            # Multi-PC Sync Methods
            # ---------------------------------------------------------

            elif method == "list_sync_datasets":
                datasets = self.db.list_sync_datasets()
                return [d.to_dict() for d in datasets], None

            elif method == "get_sync_dataset":
                dataset_id = params.get("id")
                dataset = self.db.get_sync_dataset(dataset_id)
                return dataset.to_dict() if dataset else None, None

            elif method == "create_sync_dataset":
                name = params.get("name")
                local_path = params.get("local_path")
                bucket_name = params.get("bucket_name")
                schedule_mode = params.get("schedule_mode", "realtime")
                schedule_interval_minutes = params.get("schedule_interval_minutes", 15)
                max_delete_threshold = params.get("max_delete_threshold", 50)
                bandwidth_limit = params.get("bandwidth_limit")
                exclude_patterns = params.get("exclude_patterns", [])
                initial_action = params.get("initial_action", "merge")

                dataset = self.sync_engine.create_and_init_dataset(
                    name=name,
                    local_path=local_path,
                    bucket_name=bucket_name,
                    schedule_mode=schedule_mode,
                    schedule_interval_minutes=schedule_interval_minutes,
                    max_delete_threshold=max_delete_threshold,
                    bandwidth_limit=bandwidth_limit,
                    exclude_patterns=exclude_patterns,
                    initial_action=initial_action,
                )
                return dataset.to_dict(), None

            elif method == "update_sync_dataset":
                dataset_data = params.get("dataset", {})
                dataset = SyncDataset.from_dict(dataset_data)
                success = self.db.update_sync_dataset(dataset)
                if dataset.enabled and not dataset.paused and dataset.schedule_mode == "realtime":
                    if os.path.exists(dataset.local_path):
                        self.sync_engine.watcher_manager.start_watching(dataset.dataset_id, dataset.local_path, dataset.exclude_patterns)
                else:
                    self.sync_engine.watcher_manager.stop_watching(dataset.dataset_id)
                return success, None

            elif method == "delete_sync_dataset":
                dataset_id = params.get("id")
                delete_remote = params.get("delete_remote_files", False)
                success = self.sync_engine.delete_dataset(dataset_id, delete_remote_files=delete_remote)
                return success, None

            elif method == "pause_sync_dataset":
                dataset_id = params.get("id")
                dataset = self.db.get_sync_dataset(dataset_id)
                if dataset:
                    dataset.paused = True
                    dataset.status = "paused"
                    self.db.update_sync_dataset(dataset)
                    self.sync_engine.watcher_manager.stop_watching(dataset_id)
                    return True, None
                return False, f"Dataset {dataset_id} not found"

            elif method == "resume_sync_dataset":
                dataset_id = params.get("id")
                dataset = self.db.get_sync_dataset(dataset_id)
                if dataset:
                    dataset.paused = False
                    dataset.status = "waiting"
                    self.db.update_sync_dataset(dataset)
                    if dataset.schedule_mode == "realtime" and os.path.exists(dataset.local_path):
                        self.sync_engine.watcher_manager.start_watching(dataset_id, dataset.local_path, dataset.exclude_patterns)
                    self.sync_engine.trigger_sync_async(dataset_id)
                    return True, None
                return False, f"Dataset {dataset_id} not found"

            elif method == "sync_dataset_now":
                dataset_id = params.get("id")
                force_resync = params.get("force_resync", False)
                dataset = self.db.get_sync_dataset(dataset_id)
                if not dataset:
                    return False, f"Dataset {dataset_id} not found"
                self.sync_engine.trigger_sync_async(dataset_id, force_resync=force_resync)
                return True, None

            elif method == "cancel_sync_dataset":
                dataset_id = params.get("id")
                success = self.sync_engine.cancel_sync(dataset_id)
                return success, None

            elif method == "discover_remote_datasets":
                bucket_name = params.get("bucket_name")
                discovered = self.sync_engine.discover_remote_datasets(bucket_name)
                return [d.to_dict() for d in discovered], None

            elif method == "join_remote_dataset":
                remote_info_data = params.get("remote_info", {})
                remote_info = RemoteDatasetInfo.from_dict(remote_info_data)
                local_path = params.get("local_path")
                schedule_mode = params.get("schedule_mode", "realtime")
                schedule_interval_minutes = params.get("schedule_interval_minutes", 15)
                max_delete_threshold = params.get("max_delete_threshold", 50)
                bandwidth_limit = params.get("bandwidth_limit")
                exclude_patterns = params.get("exclude_patterns", [])

                dataset = self.sync_engine.join_remote_dataset(
                    remote_info=remote_info,
                    local_path=local_path,
                    schedule_mode=schedule_mode,
                    schedule_interval_minutes=schedule_interval_minutes,
                    max_delete_threshold=max_delete_threshold,
                    bandwidth_limit=bandwidth_limit,
                    exclude_patterns=exclude_patterns,
                )
                return dataset.to_dict(), None

            elif method == "list_sync_devices":
                dataset_id = params.get("dataset_id")
                devices = self.db.list_sync_devices(dataset_id)
                return [d.to_dict() for d in devices], None

            elif method == "refresh_sync_devices":
                dataset_id = params.get("dataset_id")
                devices = self.sync_engine.refresh_connected_devices(dataset_id)
                return [d.to_dict() for d in devices], None

            elif method == "remove_sync_device":
                dataset_id = params.get("dataset_id")
                device_id = params.get("device_id")
                success = self.sync_engine.remove_device(dataset_id, device_id)
                return success, None

            elif method == "list_conflicts":
                dataset_id = params.get("dataset_id")
                include_resolved = params.get("include_resolved", False)
                conflicts = self.db.list_conflicts(dataset_id, include_resolved=include_resolved)
                return [c.to_dict() for c in conflicts], None

            elif method == "resolve_conflict":
                conflict_id = params.get("conflict_id")
                resolution = params.get("resolution")
                success = self.sync_engine.resolve_conflict(conflict_id, resolution)
                return success, None

            elif method == "check_folder_overlap":
                candidate_path = params.get("path")
                exclude_id = params.get("exclude_dataset_id")
                overlap = self.sync_engine.check_folder_overlap(candidate_path, exclude_id)
                return overlap, None

            elif method == "get_device_identity":
                return {
                    "device_id": self.db.get_or_create_device_id(),
                    "device_name": self.db.get_device_name(),
                }, None

            elif method == "set_device_name":
                name = params.get("name", "")
                self.db.set_device_name(name)
                return True, None

            else:
                return None, f"Unknown method: {method}"


        except Exception as e:
            logger.error(f"Error handling IPC method {method}: {e}", exc_info=True)
            return None, str(e)
