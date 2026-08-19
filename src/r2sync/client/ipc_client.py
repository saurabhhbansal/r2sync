"""Thread-safe IPC Client for r2sync GUI communicating with r2sync-service daemon."""

import json
import logging
import socket
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from r2sync.config import IPC_DEFAULT_PORT, IPC_HOST
from r2sync.core.models import BackupJob, BackupRun, TransferProgressEvent
from r2sync.utils.paths import get_ipc_token_path

logger = logging.getLogger(__name__)


class IPCClient:
    """Client interface for sending commands to r2sync background service."""

    def __init__(self, host: str = IPC_HOST, port: int = IPC_DEFAULT_PORT):
        self.host = host
        self.port = port
        self._req_id = 0
        self._lock = threading.Lock()
        self._event_listeners: Dict[str, List[Callable[[Any], None]]] = {
            "job_progress": [],
            "job_completed": [],
            "sync_progress": [],
            "sync_completed": [],
        }

        self._event_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._event_socket: Optional[socket.socket] = None

    def _get_auth_token(self) -> Optional[str]:
        token_path = get_ipc_token_path()
        if token_path.exists():
            try:
                with open(token_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                pass
        return None

    def is_service_running(self) -> bool:
        try:
            res = self.call("ping", timeout=2.0)
            return isinstance(res, dict) and res.get("status") == "ok"
        except Exception:
            return False

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 15.0) -> Any:
        """Send a synchronous JSON-RPC call to the IPC server and return result."""
        with self._lock:
            self._req_id += 1
            current_id = self._req_id

        token = self._get_auth_token()
        payload = {
            "id": current_id,
            "method": method,
            "params": params or {},
            "auth_token": token,
        }

        req_bytes = (json.dumps(payload) + chr(10)).encode("utf-8")

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((self.host, self.port))
            sock.sendall(req_bytes)

            file_obj = sock.makefile("r", encoding="utf-8", errors="replace")
            for line in file_obj:
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if "event" in data:
                        continue
                    if data.get("id") == current_id:
                        if data.get("error"):
                            raise RuntimeError(data.get("error"))
                        return data.get("result")
                except json.JSONDecodeError:
                    continue

            raise ConnectionError(f"No response received for method {method}")
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def add_event_listener(self, event_type: str, callback: Callable[[Any], None]) -> None:
        if event_type not in self._event_listeners:
            self._event_listeners[event_type] = []
        self._event_listeners[event_type].append(callback)
        self.start_event_stream()

    def remove_event_listener(self, event_type: str, callback: Callable[[Any], None]) -> None:
        if event_type in self._event_listeners:
            if callback in self._event_listeners[event_type]:
                self._event_listeners[event_type].remove(callback)

    def start_event_stream(self) -> None:
        if self._event_thread and self._event_thread.is_alive():
            return
        self._stop_event.clear()
        self._event_thread = threading.Thread(target=self._listen_events_loop, name="r2sync-ipc-events", daemon=True)
        self._event_thread.start()

    def stop_event_stream(self) -> None:
        self._stop_event.set()
        if self._event_socket:
            try:
                self._event_socket.close()
            except Exception:
                pass
        if self._event_thread:
            self._event_thread.join(timeout=2.0)
            self._event_thread = None

    def _listen_events_loop(self) -> None:
        while not self._stop_event.is_set():
            token = self._get_auth_token()
            if not token:
                time.sleep(2)
                continue

            try:
                self._event_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._event_socket.settimeout(5.0)
                self._event_socket.connect((self.host, self.port))

                payload = {"id": 0, "method": "ping", "params": {}, "auth_token": token}
                self._event_socket.sendall((json.dumps(payload) + chr(10)).encode("utf-8"))

                file_obj = self._event_socket.makefile("r", encoding="utf-8", errors="replace")
                while not self._stop_event.is_set():
                    try:
                        line = file_obj.readline()
                        if not line:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            if "event" in data:
                                ev_type = data.get("event")
                                ev_data = data.get("data")
                                listeners = list(self._event_listeners.get(ev_type, []))
                                for listener in listeners:
                                    try:
                                        listener(ev_data)
                                    except Exception as e:
                                        logger.debug(f"Event dispatch error: {e}")
                        except json.JSONDecodeError:
                            continue
                    except socket.timeout:
                        continue
            except Exception as e:
                logger.debug(f"Event stream disconnected: {e}")
            finally:
                if self._event_socket:
                    try:
                        self._event_socket.close()
                    except Exception:
                        pass
                self._event_socket = None

            if not self._stop_event.is_set():
                time.sleep(3)

    def get_summary_stats(self) -> Dict[str, Any]:
        return self.call("get_summary_stats")

    def list_jobs(self) -> List[Dict[str, Any]]:
        return self.call("list_jobs")

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        return self.call("get_job", {"id": job_id})

    def create_job(self, job_dict: Dict[str, Any]) -> int:
        return self.call("create_job", {"job": job_dict})

    def update_job(self, job_dict: Dict[str, Any]) -> bool:
        return self.call("update_job", {"job": job_dict})

    def delete_job(self, job_id: int) -> bool:
        return self.call("delete_job", {"id": job_id})

    def run_job_now(self, job_id: int) -> bool:
        return self.call("run_job_now", {"id": job_id})

    def cancel_job(self, job_id: int) -> bool:
        return self.call("cancel_job", {"id": job_id})

    def list_runs(self, limit: int = 50, offset: int = 0, job_id: Optional[int] = None) -> List[Dict[str, Any]]:
        return self.call("list_runs", {"limit": limit, "offset": offset, "job_id": job_id})

    def list_transfers(self, run_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        return self.call("list_transfers", {"run_id": run_id, "limit": limit})

    def list_activities(self, limit: int = 100, category: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.call("list_activities", {"limit": limit, "category": category})

    def get_active_runs(self) -> List[Dict[str, Any]]:
        return self.call("get_active_runs")

    def test_r2_connection(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        default_bucket: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.call("test_r2_connection", {
            "account_id": account_id,
            "access_key_id": access_key_id,
            "secret_access_key": secret_access_key,
            "default_bucket": default_bucket,
        })

    def list_buckets(self) -> List[Dict[str, Any]]:
        return self.call("list_buckets")

    def get_bucket_details(self, bucket_name: str) -> Dict[str, Any]:
        return self.call("get_bucket_details", {"bucket_name": bucket_name})

    def create_bucket(self, bucket_name: str) -> bool:
        return self.call("create_bucket", {"bucket_name": bucket_name})

    def save_credentials(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        default_bucket: Optional[str] = None,
    ) -> bool:
        return self.call("save_credentials", {
            "account_id": account_id,
            "access_key_id": access_key_id,
            "secret_access_key": secret_access_key,
            "default_bucket": default_bucket,
        })

    def has_credentials(self) -> bool:
        return self.call("has_credentials")

    def get_settings(self) -> Dict[str, str]:
        return self.call("get_settings")

    def set_setting(self, key: str, value: str) -> bool:
        return self.call("set_setting", {"key": key, "value": value})

    def download_rclone(self) -> Dict[str, Any]:
        return self.call("download_rclone", timeout=60.0)

    def get_rclone_status(self) -> Dict[str, Any]:
        return self.call("get_rclone_status")

    # ---------------------------------------------------------
    # Multi-PC Sync IPC Methods
    # ---------------------------------------------------------

    def list_sync_datasets(self) -> List[Dict[str, Any]]:
        return self.call("list_sync_datasets") or []

    def get_sync_dataset(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        return self.call("get_sync_dataset", {"id": dataset_id})

    def create_sync_dataset(
        self,
        name: str,
        local_path: str,
        bucket_name: str,
        schedule_mode: str = "realtime",
        schedule_interval_minutes: int = 15,
        max_delete_threshold: int = 50,
        bandwidth_limit: Optional[str] = None,
        exclude_patterns: Optional[List[str]] = None,
        initial_action: str = "merge",
    ) -> Dict[str, Any]:
        return self.call("create_sync_dataset", {
            "name": name,
            "local_path": local_path,
            "bucket_name": bucket_name,
            "schedule_mode": schedule_mode,
            "schedule_interval_minutes": schedule_interval_minutes,
            "max_delete_threshold": max_delete_threshold,
            "bandwidth_limit": bandwidth_limit,
            "exclude_patterns": exclude_patterns or [],
            "initial_action": initial_action,
        })

    def update_sync_dataset(self, dataset_dict: Dict[str, Any]) -> bool:
        return self.call("update_sync_dataset", {"dataset": dataset_dict})

    def delete_sync_dataset(self, dataset_id: str, delete_remote_files: bool = False) -> bool:
        return self.call("delete_sync_dataset", {"id": dataset_id, "delete_remote_files": delete_remote_files})

    def pause_sync_dataset(self, dataset_id: str) -> bool:
        return self.call("pause_sync_dataset", {"id": dataset_id})

    def resume_sync_dataset(self, dataset_id: str) -> bool:
        return self.call("resume_sync_dataset", {"id": dataset_id})

    def sync_dataset_now(self, dataset_id: str, force_resync: bool = False) -> bool:
        return self.call("sync_dataset_now", {"id": dataset_id, "force_resync": force_resync})

    def cancel_sync_dataset(self, dataset_id: str) -> bool:
        return self.call("cancel_sync_dataset", {"id": dataset_id})

    def discover_remote_datasets(self, bucket_name: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.call("discover_remote_datasets", {"bucket_name": bucket_name}) or []

    def join_remote_dataset(
        self,
        remote_info: Dict[str, Any],
        local_path: str,
        schedule_mode: str = "realtime",
        schedule_interval_minutes: int = 15,
        max_delete_threshold: int = 50,
        bandwidth_limit: Optional[str] = None,
        exclude_patterns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return self.call("join_remote_dataset", {
            "remote_info": remote_info,
            "local_path": local_path,
            "schedule_mode": schedule_mode,
            "schedule_interval_minutes": schedule_interval_minutes,
            "max_delete_threshold": max_delete_threshold,
            "bandwidth_limit": bandwidth_limit,
            "exclude_patterns": exclude_patterns or [],
        })

    def list_sync_devices(self, dataset_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.call("list_sync_devices", {"dataset_id": dataset_id}) or []

    def refresh_sync_devices(self, dataset_id: str) -> List[Dict[str, Any]]:
        return self.call("refresh_sync_devices", {"dataset_id": dataset_id}) or []

    def remove_sync_device(self, dataset_id: str, device_id: str) -> bool:
        return self.call("remove_sync_device", {"dataset_id": dataset_id, "device_id": device_id})

    def list_conflicts(self, dataset_id: Optional[str] = None, include_resolved: bool = False) -> List[Dict[str, Any]]:
        return self.call("list_conflicts", {"dataset_id": dataset_id, "include_resolved": include_resolved}) or []

    def resolve_conflict(self, conflict_id: int, resolution: str) -> bool:
        return self.call("resolve_conflict", {"conflict_id": conflict_id, "resolution": resolution})

    def check_folder_overlap(self, path: str, exclude_dataset_id: Optional[str] = None) -> List[str]:
        return self.call("check_folder_overlap", {"path": path, "exclude_dataset_id": exclude_dataset_id}) or []

    def get_device_identity(self) -> Dict[str, str]:
        return self.call("get_device_identity") or {}

    def set_device_name(self, name: str) -> bool:
        return self.call("set_device_name", {"name": name})

