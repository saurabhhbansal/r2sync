"""Rclone integration engine: binary management, execution, and real-time streaming."""

import io
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from r2sync.config import (
    RCLONE_BUFFER_SIZE,
    RCLONE_CHUNK_SIZE,
    RCLONE_CONCURRENCY,
    RCLONE_DEFAULT_CHECKERS,
    RCLONE_DEFAULT_TRANSFERS,
    RCLONE_VERSION,
    SYNC_PROTOCOL_VERSION,
    SYNC_R2_ROOT,
)
from r2sync.core.models import (
    BackupJob,
    BackupMode,
    BackupRun,
    Device,
    FileTransfer,
    R2BucketInfo,
    R2Credentials,
    RemoteDatasetInfo,
    RunStatus,
    SyncConflict,
    SyncDataset,
    SyncProgressEvent,
    SyncStatus,
    TransferProgressEvent,
)
from r2sync.core.speed_profiles import get_speed_profile, SpeedProfile
from r2sync.utils.paths import (
    get_cache_dir,
    get_dataset_bisync_dir,
    get_logs_dir,
    get_rclone_dir,
    get_rclone_executable_path,
    get_recovery_dir,
)


logger = logging.getLogger(__name__)


class RcloneNotFoundError(Exception):
    """Raised when rclone executable is missing."""
    pass


class RcloneExecutionError(Exception):
    """Raised when rclone exits with non-zero status."""
    def __init__(self, message: str, exit_code: int, logs: List[str]):
        super().__init__(message)
        self.exit_code = exit_code
        self.logs = logs


class RcloneBinaryManager:
    """Manages downloading, updating, and verifying the internal Rclone binary."""

    @classmethod
    def get_os_arch_string(cls) -> str:
        sys_name = platform.system().lower()
        machine = platform.machine().lower()

        if sys_name == "windows":
            os_part = "windows"
        elif sys_name == "linux":
            os_part = "linux"
        elif sys_name == "darwin":
            os_part = "osx"
        else:
            os_part = sys_name

        if machine in ("x86_64", "amd64", "x64"):
            arch_part = "amd64"
        elif machine in ("aarch64", "arm64"):
            arch_part = "arm64"
        elif machine in ("i386", "i686", "x86"):
            arch_part = "386"
        elif "arm" in machine:
            arch_part = "arm-v7"
        else:
            arch_part = "amd64"

        return f"{os_part}-{arch_part}"

    @classmethod
    def get_download_url(cls, version: str = RCLONE_VERSION) -> str:
        os_arch = cls.get_os_arch_string()
        return f"https://downloads.rclone.org/{version}/rclone-{version}-{os_arch}.zip"

    @classmethod
    def is_installed(cls) -> bool:
        exe = get_rclone_executable_path()
        if exe.exists() and os.access(str(exe), os.X_OK):
            return True
        which_path = shutil.which("rclone")
        return which_path is not None

    @classmethod
    def get_executable_path(cls) -> Path:
        exe = get_rclone_executable_path()
        if exe.exists() and os.access(str(exe), os.X_OK):
            return exe
        which_path = shutil.which("rclone")
        if which_path:
            return Path(which_path)
        raise RcloneNotFoundError(f"Rclone binary not found at {exe} or in system PATH.")

    @classmethod
    def download_and_install(
        cls,
        version: str = RCLONE_VERSION,
        progress_cb: Optional[Callable[[float, str], None]] = None,
    ) -> Path:
        """Download official rclone zip archive, extract binary to rclone dir, and verify."""
        url = cls.get_download_url(version)
        logger.info(f"Downloading Rclone {version} from {url}...")
        if progress_cb:
            progress_cb(0.1, f"Downloading Rclone {version}...")

        cache_dir = get_cache_dir()
        zip_dest = cache_dir / f"rclone_{version}.zip"

        req = urllib.request.Request(url, headers={"User-Agent": "r2sync/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 64

            with open(zip_dest, "wb") as out_file:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0 and progress_cb:
                        pct = 0.1 + (0.7 * (downloaded / total_size))
                        progress_cb(pct, f"Downloading: {downloaded // 1024} KB / {total_size // 1024} KB")

        if progress_cb:
            progress_cb(0.85, "Extracting Rclone binary...")

        rclone_dir = get_rclone_dir()
        target_exe_name = "rclone.exe" if sys.platform == "win32" else "rclone"
        target_exe_path = rclone_dir / target_exe_name

        with zipfile.ZipFile(zip_dest, "r") as zip_ref:
            for member in zip_ref.namelist():
                if member.endswith(target_exe_name):
                    with zip_ref.open(member) as source_file, open(target_exe_path, "wb") as dest_file:
                        shutil.copyfileobj(source_file, dest_file)
                    break

        if sys.platform != "win32" and target_exe_path.exists():
            os.chmod(target_exe_path, 0o755)

        try:
            zip_dest.unlink(missing_ok=True)
        except Exception:
            pass

        if not target_exe_path.exists():
            raise RcloneNotFoundError(f"Failed to extract {target_exe_name} to {target_exe_path}")

        if progress_cb:
            progress_cb(0.95, "Verifying Rclone binary...")

        ver = cls.get_version(target_exe_path)
        logger.info(f"Rclone successfully installed: {ver}")

        if progress_cb:
            progress_cb(1.0, f"Installed {ver}")

        return target_exe_path

    _cached_version: Optional[str] = None

    @classmethod
    def get_version(cls, exe_path: Optional[Path] = None, force_refresh: bool = False) -> str:
        if cls._cached_version and not force_refresh and not exe_path:
            return cls._cached_version
        try:
            exe = exe_path or cls.get_executable_path()
            flags = 0x08000000 if sys.platform == "win32" else 0
            res = subprocess.run([str(exe), "version"], capture_output=True, text=True, timeout=5, creationflags=flags)
            lines = res.stdout.strip().splitlines()
            ver = lines[0] if lines else "Unknown"
            if not exe_path:
                cls._cached_version = ver
            return ver
        except Exception as e:
            return f"Error: {e}"


class RcloneEngine:
    """High-performance execution engine for Rclone operations with Cloudflare R2."""

    def __init__(self, credentials: Optional[R2Credentials] = None):
        self.credentials = credentials
        self._active_processes: Dict[int, subprocess.Popen] = {}
        self._active_sync_processes: Dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()


    def set_credentials(self, credentials: R2Credentials) -> None:
        self.credentials = credentials

    def _build_env(self, creds: Optional[R2Credentials] = None) -> Dict[str, str]:
        """Build environment variables passing credentials directly in memory."""
        c = creds or self.credentials
        env = os.environ.copy()
        if c:
            env["RCLONE_CONFIG_R2_TYPE"] = "s3"
            env["RCLONE_CONFIG_R2_PROVIDER"] = "Cloudflare"
            env["RCLONE_CONFIG_R2_ACCESS_KEY_ID"] = c.access_key_id
            env["RCLONE_CONFIG_R2_SECRET_ACCESS_KEY"] = c.secret_access_key
            env["RCLONE_CONFIG_R2_REGION"] = "auto"
            env["RCLONE_CONFIG_R2_ENDPOINT"] = c.get_endpoint()
            env["RCLONE_CONFIG_R2_NO_CHECK_BUCKET"] = "false"
        return env

    def cancel_run(self, job_id: int) -> bool:
        """Cancel any active rclone process for the specified job_id."""
        with self._lock:
            proc = self._active_processes.get(job_id)
            if not proc:
                return False
            try:
                proc.terminate()
                return True
            except Exception as e:
                logger.warning(f"Failed to terminate process for job {job_id}: {e}")
                try:
                    proc.kill()
                    return True
                except Exception:
                    return False

    def is_job_running(self, job_id: int) -> bool:
        with self._lock:
            proc = self._active_processes.get(job_id)
            if proc and proc.poll() is None:
                return True
            return False

    def run_backup(
        self,
        job: BackupJob,
        run_record: BackupRun,
        progress_cb: Optional[Callable[[TransferProgressEvent], None]] = None,
        file_transfer_cb: Optional[Callable[[FileTransfer], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        creds: Optional[R2Credentials] = None,
        speed_profile: Optional[str] = None,
    ) -> BackupRun:
        """Execute a backup job (sync or copy) and stream progress & stats."""
        exe_path = RcloneBinaryManager.get_executable_path()
        env = self._build_env(creds)
        prof = get_speed_profile(speed_profile)

        prefix = job.remote_prefix.strip("/")
        dest_remote = f"r2:{job.bucket_name}"
        if prefix:
            dest_remote = f"{dest_remote}/{prefix}"

        cmd_action = "sync" if job.backup_mode == BackupMode.SYNC.value else "copy"
        
        args = [
            str(exe_path),
            cmd_action,
            job.source_path,
            dest_remote,
            "--use-json-log",
            "--stats", "1s",
            "--stats-log-level", "NOTICE",
            "--fast-list",
            "--buffer-size", prof.buffer_size,
            "--s3-chunk-size", prof.chunk_size,
            "--s3-upload-cutoff", prof.chunk_size,
            "--s3-copy-cutoff", prof.chunk_size,
            "--s3-upload-concurrency", str(max(prof.transfers // 2, 4)),
            "--transfers", str(prof.transfers),
            "--checkers", str(prof.checkers),
            "--s3-no-check-bucket",
            "--s3-disable-checksum",
            "--retries", "3",
            "--low-level-retries", "10",
        ]

        if job.delete_excluded and cmd_action == "sync":
            args.append("--delete-excluded")

        if job.bandwidth_limit:
            args.extend(["--bwlimit", job.bandwidth_limit])

        for pattern in job.exclude_patterns:
            if pattern.strip():
                args.extend(["--exclude", pattern.strip()])

        for pattern in job.include_patterns:
            if pattern.strip():
                args.extend(["--include", pattern.strip()])

        today_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_path = get_logs_dir() / f"run_{job.id or 0}_{today_str}.log"
        run_record.log_file_path = str(log_file_path)
        run_record.status = RunStatus.RUNNING.value
        start_time = time.time()

        log_lines: List[str] = []

        try:
            kwargs: Dict[str, Any] = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "env": env,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "bufsize": 1,
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = 0x08000000

            proc = subprocess.Popen(args, **kwargs)

            if job.id:
                with self._lock:
                    self._active_processes[job.id] = proc

            with open(log_file_path, "w", encoding="utf-8") as log_f:
                log_f.write(f"=== r2sync Backup Started at {datetime.now().isoformat()} ===\n")
                log_f.write(f"Job: {job.name} (ID: {job.id})\n")
                log_f.write(f"Source: {job.source_path}\n")
                log_f.write(f"Destination: {dest_remote}\n")
                log_f.write(f"Mode: {cmd_action}\n\n")

                for line in iter(proc.stdout.readline, ""):
                    if not line:
                        break
                    line_clean = line.strip()
                    log_f.write(line)
                    log_f.flush()
                    log_lines.append(line_clean)

                    if log_cb:
                        log_cb(line_clean)

                    try:
                        data = json.loads(line_clean)
                        msg = data.get("msg", "")
                        stats_data = data.get("stats")

                        if stats_data or (isinstance(msg, dict) and "bytes" in msg):
                            st = stats_data or msg
                            bytes_done = st.get("bytes", 0)
                            total_bytes = st.get("totalBytes", 0)
                            speed = st.get("speed", 0.0)
                            eta = st.get("eta")
                            transfers = st.get("transfers", 0)
                            total_transfers = st.get("totalTransfers", 0)
                            errors = st.get("errors", 0)
                            deletes = st.get("deletes", 0)

                            pct = (bytes_done / total_bytes * 100.0) if total_bytes > 0 else 0.0
                            transferring_list = st.get("transferring", [])
                            curr_file = transferring_list[0].get("name") if transferring_list else None

                            progress_event = TransferProgressEvent(
                                job_id=job.id or 0,
                                run_id=run_record.id,
                                percentage=round(pct, 1),
                                bytes_transferred=bytes_done,
                                total_bytes=total_bytes,
                                speed_bytes_per_sec=speed,
                                eta_seconds=eta,
                                current_file=curr_file,
                                files_transferred=transfers,
                                total_files=total_transfers,
                                errors_count=errors,
                            )

                            run_record.bytes_transferred = bytes_done
                            run_record.total_bytes = total_bytes
                            run_record.files_transferred = transfers
                            run_record.total_files = total_transfers
                            run_record.files_deleted = deletes
                            run_record.errors_count = errors

                            if progress_cb:
                                progress_cb(progress_event)

                        obj_name = data.get("object")
                        if obj_name and file_transfer_cb:
                            transfer_size = data.get("size", 0)
                            status_str = "transferred"
                            if "Deleted" in msg:
                                status_str = "deleted"
                            elif "Checked" in msg or "Unchanged" in msg:
                                status_str = "checked"
                            elif data.get("level") == "error":
                                status_str = "error"

                            ft = FileTransfer(
                                run_id=run_record.id or 0,
                                job_id=job.id or 0,
                                file_path=obj_name,
                                size_bytes=transfer_size,
                                transferred_bytes=transfer_size if status_str == "transferred" else 0,
                                status=status_str,
                                error_message=msg if status_str == "error" else None,
                            )
                            file_transfer_cb(ft)

                    except json.JSONDecodeError:
                        pass

            exit_code = proc.wait()
            end_time = time.time()
            duration = end_time - start_time

            run_record.duration_seconds = round(duration, 2)
            run_record.completed_at = datetime.now().isoformat()
            run_record.exit_code = exit_code

            if exit_code == 0:
                run_record.status = RunStatus.COMPLETED.value
            elif exit_code == -15 or exit_code == 1:
                run_record.status = RunStatus.CANCELED.value
                run_record.error_message = "Backup job was canceled by user."
            else:
                run_record.status = RunStatus.FAILED.value
                run_record.error_message = f"Rclone exited with code {exit_code}"

        except Exception as e:
            run_record.status = RunStatus.FAILED.value
            run_record.completed_at = datetime.now().isoformat()
            run_record.duration_seconds = round(time.time() - start_time, 2)
            run_record.error_message = str(e)
            logger.error(f"Backup execution error: {e}", exc_info=True)

        finally:
            if job.id:
                with self._lock:
                    self._active_processes.pop(job.id, None)

        return run_record

    def test_connection(self, creds: Optional[R2Credentials] = None) -> Dict[str, Any]:
        """Test R2 connectivity by listing buckets."""
        exe_path = RcloneBinaryManager.get_executable_path()
        env = self._build_env(creds)

        start = time.time()
        try:
            flags = 0x08000000 if sys.platform == "win32" else 0
            res = subprocess.run(
                [
                    str(exe_path),
                    "lsd",
                    "r2:",
                    "--fast-list",
                    "--retries", "1",
                    "--low-level-retries", "1",
                    "--contimeout", "8s",
                    "--timeout", "8s",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=flags,
            )
            latency_ms = round((time.time() - start) * 1000, 1)

            if res.returncode == 0:
                buckets = []
                for line in res.stdout.strip().splitlines():
                    parts = line.strip().split()
                    if parts:
                        buckets.append(parts[-1])
                return {
                    "success": True,
                    "buckets": buckets,
                    "latency_ms": latency_ms,
                    "message": f"Successfully connected to Cloudflare R2 ({latency_ms}ms)",
                }
            else:
                err_msg = res.stderr.strip() or res.stdout.strip()
                if "403" in err_msg or "AccessDenied" in err_msg or "Forbidden" in err_msg:
                    err_msg += "\n\nHint: Cloudflare R2 API Token requires 'Admin Read & Write' permission and 'Apply to all buckets' to list buckets."
                elif "401" in err_msg or "InvalidAccessKeyId" in err_msg or "SignatureDoesNotMatch" in err_msg:
                    err_msg += "\n\nHint: Check Access Key ID and Secret Access Key. Note: Cloudflare User Bearer tokens or Global API keys cannot be used for S3 authentication."
                return {
                    "success": False,
                    "buckets": [],
                    "latency_ms": latency_ms,
                    "error": err_msg,
                    "message": f"Connection failed: {err_msg}",
                }
        except Exception as e:
            return {
                "success": False,
                "buckets": [],
                "latency_ms": 0,
                "error": str(e),
                "message": f"Connection failed: {e}",
            }

    def list_buckets(self, creds: Optional[R2Credentials] = None) -> List[str]:
        res = self.test_connection(creds)
        if res.get("success"):
            return res.get("buckets", [])
        raise RcloneExecutionError(res.get("error", "Failed to list buckets"), 1, [])

    def create_bucket(self, bucket_name: str, creds: Optional[R2Credentials] = None) -> bool:
        """Create a new R2 bucket via rclone mkdir."""
        exe_path = RcloneBinaryManager.get_executable_path()
        env = self._build_env(creds)
        flags = 0x08000000 if sys.platform == "win32" else 0

        res = subprocess.run(
            [str(exe_path), "mkdir", f"r2:{bucket_name}"],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=flags,
        )
        if res.returncode == 0:
            return True
        raise RcloneExecutionError(res.stderr.strip(), res.returncode, [res.stderr.strip()])

    def get_bucket_size(self, bucket_name: str, creds: Optional[R2Credentials] = None) -> Dict[str, Any]:
        """Get total size and object count of a bucket via rclone size --json."""
        exe_path = RcloneBinaryManager.get_executable_path()
        env = self._build_env(creds)
        flags = 0x08000000 if sys.platform == "win32" else 0

        try:
            res = subprocess.run(
                [str(exe_path), "size", f"r2:{bucket_name}", "--json"],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=flags,
            )
            if res.returncode == 0:
                data = json.loads(res.stdout)
                return {
                    "count": data.get("count", 0),
                    "bytes": data.get("bytes", 0),
                }
        except Exception as e:
            logger.debug(f"Failed to get size for {bucket_name}: {e}")

        return {"count": 0, "bytes": 0}

    # ---------------------------------------------------------
    # Bidirectional Cloud Sync (Bisync) Operations
    # ---------------------------------------------------------

    def cancel_bisync(self, dataset_id: str) -> bool:
        """Cancel an active bisync process for the specified dataset_id."""
        with self._lock:
            proc = self._active_sync_processes.get(dataset_id)
            if not proc:
                return False
            try:
                proc.terminate()
                return True
            except Exception as e:
                logger.warning(f"Failed to terminate bisync process for dataset {dataset_id}: {e}")
                try:
                    proc.kill()
                    return True
                except Exception:
                    return False

    def is_bisync_running(self, dataset_id: str) -> bool:
        with self._lock:
            proc = self._active_sync_processes.get(dataset_id)
            if proc and proc.poll() is None:
                return True
            return False

    def run_bisync(
        self,
        dataset: SyncDataset,
        resync_mode: Optional[str] = None,  # "path1" for initial upload, "path2" for initial download, None for normal
        force_resync: bool = False,
        progress_cb: Optional[Callable[[SyncProgressEvent], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        creds: Optional[R2Credentials] = None,
        speed_profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute bidirectional synchronization between local path and R2 dataset namespace."""
        exe_path = RcloneBinaryManager.get_executable_path()
        env = self._build_env(creds)
        prof = get_speed_profile(speed_profile)

        workdir = get_dataset_bisync_dir(dataset.dataset_id)
        local_path = dataset.local_path
        remote_prefix = dataset.remote_prefix.strip("/")
        remote_data_path = f"r2:{dataset.bucket_name}/{remote_prefix}/data"

        # Local recovery/trash directory for deleted or replaced files
        recovery_dir = dataset.local_path + "/.r2sync_trash"

        args = [
            str(exe_path),
            "bisync",
            local_path,
            remote_data_path,
            "--workdir", str(workdir),
            "--use-json-log",
            "--stats", "1s",
            "--stats-log-level", "NOTICE",
            "--fast-list",
            "--buffer-size", prof.buffer_size,
            "--s3-chunk-size", prof.chunk_size,
            "--s3-upload-cutoff", prof.chunk_size,
            "--s3-copy-cutoff", prof.chunk_size,
            "--s3-upload-concurrency", str(max(prof.transfers // 2, 4)),
            "--transfers", str(prof.transfers),
            "--checkers", str(prof.checkers),
            "--s3-no-check-bucket",
            "--s3-disable-checksum",
            "--retries", "3",
            "--low-level-retries", "10",
            "--backup-dir1", recovery_dir,
            "--no-cleanup",
        ]

        if force_resync or resync_mode or not dataset.initial_sync_done:
            mode = resync_mode or "path1"
            args.extend(["--resync", "--resync-mode", mode])
        else:
            args.extend(["--recover", "--resilient"])

        # Mass deletion threshold safety
        max_del = dataset.max_delete_threshold or 50
        args.extend(["--max-delete", str(max_del)])

        if dataset.bandwidth_limit:
            args.extend(["--bwlimit", dataset.bandwidth_limit])

        # Exclusions
        args.extend(["--exclude", ".r2sync_trash/**", "--exclude", ".r2sync_trash/"])
        for pat in dataset.exclude_patterns:
            if pat.strip():
                args.extend(["--exclude", pat.strip()])

        today_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_path = get_logs_dir() / f"sync_{dataset.dataset_id[:8]}_{today_str}.log"
        start_time = time.time()

        result_stats = {
            "success": False,
            "exit_code": None,
            "duration_seconds": 0.0,
            "bytes_transferred": 0,
            "total_bytes": 0,
            "files_transferred": 0,
            "total_files": 0,
            "files_deleted": 0,
            "errors_count": 0,
            "conflicts_detected": [],
            "mass_deletion_triggered": False,
            "error_message": None,
            "log_file_path": str(log_file_path),
        }

        log_lines: List[str] = []

        try:
            kwargs: Dict[str, Any] = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "env": env,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "bufsize": 1,
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = 0x08000000

            proc = subprocess.Popen(args, **kwargs)

            with self._lock:
                self._active_sync_processes[dataset.dataset_id] = proc

            with open(log_file_path, "w", encoding="utf-8") as log_f:
                log_f.write(f"=== r2sync Multi-PC Bisync Started at {datetime.now().isoformat()} ===\n")
                log_f.write(f"Dataset: {dataset.name} (ID: {dataset.dataset_id})\n")
                log_f.write(f"Local: {local_path}\n")
                log_f.write(f"Remote: {remote_data_path}\n")
                log_f.write(f"Mode: {'resync ' + str(resync_mode) if (force_resync or resync_mode or not dataset.initial_sync_done) else 'incremental'}\n\n")

                for line in iter(proc.stdout.readline, ""):
                    if not line:
                        break
                    line_clean = line.strip()
                    log_f.write(line)
                    log_f.flush()
                    log_lines.append(line_clean)

                    if log_cb:
                        log_cb(line_clean)

                    # Check for conflict lines in output
                    if "conflict" in line_clean.lower() or "Path1 and Path2 have both changed" in line_clean:
                        result_stats["conflicts_detected"].append(line_clean)

                    # Check for safety mass deletion abort
                    if "safety check" in line_clean.lower() or "--max-delete" in line_clean.lower() or "too many deletes" in line_clean.lower():
                        result_stats["mass_deletion_triggered"] = True

                    try:
                        data = json.loads(line_clean)
                        msg = data.get("msg", "")
                        stats_data = data.get("stats")

                        if stats_data or (isinstance(msg, dict) and "bytes" in msg):
                            st = stats_data or msg
                            bytes_done = st.get("bytes", 0)
                            total_bytes = st.get("totalBytes", 0)
                            speed = st.get("speed", 0.0)
                            eta = st.get("eta")
                            transfers = st.get("transfers", 0)
                            total_transfers = st.get("totalTransfers", 0)
                            errors = st.get("errors", 0)
                            deletes = st.get("deletes", 0)

                            pct = (bytes_done / total_bytes * 100.0) if total_bytes > 0 else 0.0
                            transferring_list = st.get("transferring", [])
                            curr_file = transferring_list[0].get("name") if transferring_list else None

                            progress_event = SyncProgressEvent(
                                dataset_id=dataset.dataset_id,
                                status=SyncStatus.SYNCING.value,
                                percentage=round(pct, 1),
                                bytes_transferred=bytes_done,
                                total_bytes=total_bytes,
                                speed_bytes_per_sec=speed,
                                eta_seconds=eta,
                                current_file=curr_file,
                                files_transferred=transfers,
                                total_files=total_transfers,
                                errors_count=errors,
                                conflicts_count=len(result_stats["conflicts_detected"]),
                            )

                            result_stats["bytes_transferred"] = bytes_done
                            result_stats["total_bytes"] = total_bytes
                            result_stats["files_transferred"] = transfers
                            result_stats["total_files"] = total_transfers
                            result_stats["files_deleted"] = deletes
                            result_stats["errors_count"] = errors

                            if progress_cb:
                                progress_cb(progress_event)

                    except json.JSONDecodeError:
                        pass

            exit_code = proc.wait()
            end_time = time.time()
            duration = end_time - start_time

            result_stats["duration_seconds"] = round(duration, 2)
            result_stats["exit_code"] = exit_code

            if exit_code == 0:
                result_stats["success"] = True
            elif result_stats["mass_deletion_triggered"]:
                result_stats["success"] = False
                result_stats["error_message"] = "Sync paused: Deletion safety threshold exceeded to protect your files."
            elif exit_code == -15 or exit_code == 1:
                if len(result_stats["conflicts_detected"]) > 0:
                    result_stats["error_message"] = "Conflicts detected during synchronization."
                else:
                    result_stats["error_message"] = "Sync was canceled or interrupted."
            else:
                result_stats["error_message"] = f"Rclone bisync exited with code {exit_code}"

        except Exception as e:
            result_stats["success"] = False
            result_stats["duration_seconds"] = round(time.time() - start_time, 2)
            result_stats["error_message"] = str(e)
            logger.error(f"Bisync execution error for dataset {dataset.dataset_id}: {e}", exc_info=True)

        finally:
            with self._lock:
                self._active_sync_processes.pop(dataset.dataset_id, None)

        return result_stats

    # ---------------------------------------------------------
    # Remote Metadata & Device Registry
    # ---------------------------------------------------------

    def cat_remote_file(self, remote_path: str, creds: Optional[R2Credentials] = None) -> Optional[str]:
        """Read content of a remote text file via rclone cat."""
        exe_path = RcloneBinaryManager.get_executable_path()
        env = self._build_env(creds)
        flags = 0x08000000 if sys.platform == "win32" else 0

        try:
            res = subprocess.run(
                [str(exe_path), "cat", f"r2:{remote_path}"],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=flags,
            )
            if res.returncode == 0:
                return res.stdout
        except Exception as e:
            logger.debug(f"cat_remote_file failed for {remote_path}: {e}")
        return None

    def rcat_remote_file(self, remote_path: str, content: str, creds: Optional[R2Credentials] = None) -> bool:
        """Write content directly to a remote file via rclone rcat."""
        exe_path = RcloneBinaryManager.get_executable_path()
        env = self._build_env(creds)
        flags = 0x08000000 if sys.platform == "win32" else 0

        try:
            res = subprocess.run(
                [str(exe_path), "rcat", f"r2:{remote_path}"],
                input=content,
                env=env,
                capture_output=True,
                text=True,
                timeout=25,
                creationflags=flags,
            )
            return res.returncode == 0
        except Exception as e:
            logger.debug(f"rcat_remote_file failed for {remote_path}: {e}")
            return False

    def delete_remote_file(self, remote_path: str, creds: Optional[R2Credentials] = None) -> bool:
        """Delete a remote file via rclone deletefile."""
        exe_path = RcloneBinaryManager.get_executable_path()
        env = self._build_env(creds)
        flags = 0x08000000 if sys.platform == "win32" else 0

        try:
            res = subprocess.run(
                [str(exe_path), "deletefile", f"r2:{remote_path}"],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=flags,
            )
            return res.returncode == 0
        except Exception as e:
            logger.debug(f"delete_remote_file failed for {remote_path}: {e}")
            return False

    def list_remote_files(self, remote_dir: str, creds: Optional[R2Credentials] = None) -> List[Dict[str, Any]]:
        """List objects in remote directory via rclone lsjson."""
        exe_path = RcloneBinaryManager.get_executable_path()
        env = self._build_env(creds)
        flags = 0x08000000 if sys.platform == "win32" else 0

        try:
            res = subprocess.run(
                [str(exe_path), "lsjson", f"r2:{remote_dir}"],
                env=env,
                capture_output=True,
                text=True,
                timeout=25,
                creationflags=flags,
            )
            if res.returncode == 0 and res.stdout.strip():
                return json.loads(res.stdout)
        except Exception as e:
            logger.debug(f"list_remote_files failed for {remote_dir}: {e}")
        return []

    def discover_remote_datasets(self, bucket_name: str, creds: Optional[R2Credentials] = None) -> List[RemoteDatasetInfo]:
        """Scan R2 bucket for available sync datasets under r2sync/v1/datasets/."""
        datasets_root = f"{bucket_name}/{SYNC_R2_ROOT}"
        entries = self.list_remote_files(datasets_root, creds)
        found: List[RemoteDatasetInfo] = []

        for entry in entries:
            if not entry.get("IsDir"):
                continue
            dataset_id = entry.get("Path", "").strip("/")
            if not dataset_id:
                continue

            meta_path = f"{bucket_name}/{SYNC_R2_ROOT}/{dataset_id}/metadata/dataset.json"
            meta_json = self.cat_remote_file(meta_path, creds)
            if meta_json:
                try:
                    data = json.loads(meta_json)
                    found.append(RemoteDatasetInfo(
                        dataset_id=data.get("dataset_id", dataset_id),
                        name=data.get("name", dataset_id),
                        bucket_name=bucket_name,
                        created_by_device=data.get("created_by_device", "Unknown"),
                        created_at=data.get("created_at", datetime.now().isoformat()),
                        total_files=data.get("total_files", 0),
                        total_bytes=data.get("total_bytes", 0),
                        protocol_version=data.get("protocol_version", SYNC_PROTOCOL_VERSION),
                    ))
                except Exception as e:
                    logger.debug(f"Error parsing metadata for dataset {dataset_id}: {e}")

        return found

    def upload_dataset_metadata(self, dataset: SyncDataset, device: Device, creds: Optional[R2Credentials] = None) -> bool:
        """Upload dataset metadata to R2 (metadata/dataset.json)."""
        remote_meta_path = f"{dataset.bucket_name}/{dataset.remote_prefix.strip('/')}/metadata/dataset.json"
        payload = {
            "dataset_id": dataset.dataset_id,
            "name": dataset.name,
            "bucket_name": dataset.bucket_name,
            "created_by_device": device.device_name,
            "created_by_device_id": device.device_id,
            "created_at": dataset.created_at,
            "protocol_version": SYNC_PROTOCOL_VERSION,
            "total_files": dataset.total_files,
            "total_bytes": dataset.total_bytes,
        }
        return self.rcat_remote_file(remote_meta_path, json.dumps(payload, indent=2), creds)

    def register_remote_device(self, dataset: SyncDataset, device: Device, creds: Optional[R2Credentials] = None) -> bool:
        """Register or update device heartbeat in R2 (devices/<device_id>.json)."""
        remote_dev_path = f"{dataset.bucket_name}/{dataset.remote_prefix.strip('/')}/devices/{device.device_id}.json"
        payload = {
            "device_id": device.device_id,
            "device_name": device.device_name,
            "dataset_id": dataset.dataset_id,
            "last_seen_at": datetime.now().isoformat(),
            "last_sync_at": device.last_sync_at,
            "status": device.status,
            "client_version": device.client_version,
            "protocol_version": SYNC_PROTOCOL_VERSION,
        }
        return self.rcat_remote_file(remote_dev_path, json.dumps(payload, indent=2), creds)

    def fetch_remote_devices(self, dataset: SyncDataset, creds: Optional[R2Credentials] = None) -> List[Device]:
        """Fetch all registered devices for a dataset from R2."""
        remote_dev_dir = f"{dataset.bucket_name}/{dataset.remote_prefix.strip('/')}/devices"
        entries = self.list_remote_files(remote_dev_dir, creds)
        devices: List[Device] = []

        for entry in entries:
            name = entry.get("Name", "")
            if not name.endswith(".json"):
                continue
            dev_path = f"{remote_dev_dir}/{name}"
            dev_json = self.cat_remote_file(dev_path, creds)
            if dev_json:
                try:
                    data = json.loads(dev_json)
                    devices.append(Device(
                        device_id=data.get("device_id", name[:-5]),
                        device_name=data.get("device_name", "Unknown PC"),
                        dataset_id=dataset.dataset_id,
                        last_seen_at=data.get("last_seen_at"),
                        last_sync_at=data.get("last_sync_at"),
                        status=data.get("status", "offline"),
                        client_version=data.get("client_version", "1.0.0"),
                    ))
                except Exception as e:
                    logger.debug(f"Error parsing device file {name}: {e}")

        return devices

    def remove_remote_device(self, dataset: SyncDataset, device_id: str, creds: Optional[R2Credentials] = None) -> bool:
        """Remove a device registration from R2 without deleting dataset files."""
        remote_dev_path = f"{dataset.bucket_name}/{dataset.remote_prefix.strip('/')}/devices/{device_id}.json"
        return self.delete_remote_file(remote_dev_path, creds)

