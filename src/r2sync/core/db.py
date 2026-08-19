import json
import os
import platform
import socket
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from r2sync.core.models import (
    ActivityLog,
    BackupJob,
    BackupRun,
    Device,
    FileTransfer,
    SyncConflict,
    SyncDataset,
)
from r2sync.utils.paths import get_database_path, get_device_id_path


class Database:
    """Thread-safe SQLite database manager for r2sync."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_database_path()
        self._local = threading.local()
        self._lock = threading.Lock()
        self.init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a thread-local SQLite connection."""
        if not hasattr(self._local, "connection") or self._local.connection is None:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=30.0,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            self._local.connection = conn
        return self._local.connection

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """Context manager for thread-safe database transactions."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                yield cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def close(self) -> None:
        """Close thread-local SQLite connection if open."""
        with self._lock:
            if hasattr(self._local, "connection") and self._local.connection is not None:
                try:
                    self._local.connection.close()
                except Exception:
                    pass
                self._local.connection = None

    def init_schema(self) -> None:
        """Initialize tables and indexes if they do not exist."""
        with self.transaction() as cur:
            # Settings table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # Backup Jobs table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS backup_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    bucket_name TEXT NOT NULL,
                    remote_prefix TEXT NOT NULL DEFAULT '',
                    schedule_type TEXT NOT NULL DEFAULT 'daily',
                    schedule_interval_minutes INTEGER NOT NULL DEFAULT 60,
                    schedule_time_of_day TEXT NOT NULL DEFAULT '02:00',
                    schedule_days_of_week TEXT NOT NULL DEFAULT '[0,1,2,3,4,5,6]',
                    backup_mode TEXT NOT NULL DEFAULT 'sync',
                    delete_excluded INTEGER NOT NULL DEFAULT 0,
                    exclude_patterns TEXT NOT NULL DEFAULT '[]',
                    include_patterns TEXT NOT NULL DEFAULT '[]',
                    bandwidth_limit TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_run_at TEXT,
                    last_status TEXT,
                    next_run_at TEXT
                );
            """)

            # Backup Runs table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS backup_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    job_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    duration_seconds REAL NOT NULL DEFAULT 0.0,
                    bytes_transferred INTEGER NOT NULL DEFAULT 0,
                    total_bytes INTEGER NOT NULL DEFAULT 0,
                    files_transferred INTEGER NOT NULL DEFAULT 0,
                    total_files INTEGER NOT NULL DEFAULT 0,
                    files_deleted INTEGER NOT NULL DEFAULT 0,
                    errors_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    exit_code INTEGER,
                    log_file_path TEXT,
                    FOREIGN KEY (job_id) REFERENCES backup_jobs(id) ON DELETE CASCADE
                );
            """)

            # File Transfers table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS file_transfers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    job_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    transferred_bytes INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'transferred',
                    error_message TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES backup_runs(id) ON DELETE CASCADE
                );
            """)

            # Activity Logs table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT,
                    job_id INTEGER,
                    run_id INTEGER
                );
            """)

            # ---------------------------------------------------------
            # Schema v2: Multi-PC Sync Tables
            # ---------------------------------------------------------

            # Sync Datasets table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sync_datasets (
                    dataset_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    bucket_name TEXT NOT NULL,
                    remote_prefix TEXT NOT NULL DEFAULT '',
                    local_path TEXT NOT NULL,
                    schedule_mode TEXT NOT NULL DEFAULT 'realtime',
                    schedule_interval_minutes INTEGER NOT NULL DEFAULT 15,
                    status TEXT NOT NULL DEFAULT 'waiting',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    paused INTEGER NOT NULL DEFAULT 0,
                    initial_sync_done INTEGER NOT NULL DEFAULT 0,
                    max_delete_threshold INTEGER NOT NULL DEFAULT 50,
                    bandwidth_limit TEXT,
                    exclude_patterns TEXT NOT NULL DEFAULT '[]',
                    total_files INTEGER NOT NULL DEFAULT 0,
                    total_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_sync_at TEXT,
                    last_error TEXT
                );
            """)

            # Sync Devices table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sync_devices (
                    device_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL DEFAULT '',
                    device_name TEXT NOT NULL,
                    is_current_device INTEGER NOT NULL DEFAULT 0,
                    last_seen_at TEXT,
                    last_sync_at TEXT,
                    status TEXT NOT NULL DEFAULT 'offline',
                    client_version TEXT NOT NULL DEFAULT '1.0.0',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (device_id, dataset_id)
                );
            """)

            # Sync Conflicts table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sync_conflicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    local_modified_at TEXT NOT NULL,
                    local_size_bytes INTEGER NOT NULL DEFAULT 0,
                    remote_device_id TEXT,
                    remote_device_name TEXT,
                    remote_modified_at TEXT,
                    remote_size_bytes INTEGER NOT NULL DEFAULT 0,
                    conflict_file_path TEXT,
                    detected_at TEXT NOT NULL,
                    resolved INTEGER NOT NULL DEFAULT 0,
                    resolution TEXT,
                    resolved_at TEXT,
                    FOREIGN KEY (dataset_id) REFERENCES sync_datasets(dataset_id) ON DELETE CASCADE
                );
            """)

            # Sync File State table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sync_file_state (
                    dataset_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    modified_time REAL NOT NULL DEFAULT 0.0,
                    content_hash TEXT,
                    last_sync_state TEXT NOT NULL DEFAULT 'synced',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (dataset_id, relative_path)
                );
            """)

            # Indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_runs_job_id ON backup_runs(job_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON backup_runs(status);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_transfers_run ON file_transfers(run_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON activity_logs(timestamp);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_conflicts_dataset ON sync_conflicts(dataset_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_conflicts_resolved ON sync_conflicts(resolved);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sync_devices_dataset ON sync_devices(dataset_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sync_files_dataset ON sync_file_state(dataset_id);")

            # Set Schema Version in settings if not present
            cur.execute("INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES ('schema_version', '2', ?)", (datetime.now().isoformat(),))


    # ---------------------------------------------------------
    # Settings CRUD
    # ---------------------------------------------------------

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.transaction() as cur:
            cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        now = datetime.now().isoformat()
        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """, (key, value, now))

    def get_all_settings(self) -> Dict[str, str]:
        with self.transaction() as cur:
            cur.execute("SELECT key, value FROM settings")
            return {row["key"]: row["value"] for row in cur.fetchall()}

    # ---------------------------------------------------------
    # Backup Jobs CRUD
    # ---------------------------------------------------------

    def create_job(self, job: BackupJob) -> int:
        now = datetime.now().isoformat()
        job.created_at = job.created_at or now
        job.updated_at = now
        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO backup_jobs (
                    name, source_path, bucket_name, remote_prefix, schedule_type,
                    schedule_interval_minutes, schedule_time_of_day, schedule_days_of_week,
                    backup_mode, delete_excluded, exclude_patterns, include_patterns,
                    bandwidth_limit, enabled, created_at, updated_at, last_run_at,
                    last_status, next_run_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.name,
                job.source_path,
                job.bucket_name,
                job.remote_prefix,
                job.schedule_type,
                job.schedule_interval_minutes,
                job.schedule_time_of_day,
                json.dumps(job.schedule_days_of_week),
                job.backup_mode,
                1 if job.delete_excluded else 0,
                json.dumps(job.exclude_patterns),
                json.dumps(job.include_patterns),
                job.bandwidth_limit,
                1 if job.enabled else 0,
                job.created_at,
                job.updated_at,
                job.last_run_at,
                job.last_status,
                job.next_run_at,
            ))
            job.id = cur.lastrowid
            return cur.lastrowid

    def get_job(self, job_id: int) -> Optional[BackupJob]:
        with self.transaction() as cur:
            cur.execute("SELECT * FROM backup_jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            return BackupJob.from_dict(dict(row)) if row else None

    def list_jobs(self) -> List[BackupJob]:
        with self.transaction() as cur:
            cur.execute("SELECT * FROM backup_jobs ORDER BY id ASC")
            return [BackupJob.from_dict(dict(row)) for row in cur.fetchall()]

    def update_job(self, job: BackupJob) -> bool:
        if not job.id:
            return False
        job.updated_at = datetime.now().isoformat()
        with self.transaction() as cur:
            cur.execute("""
                UPDATE backup_jobs SET
                    name = ?, source_path = ?, bucket_name = ?, remote_prefix = ?,
                    schedule_type = ?, schedule_interval_minutes = ?, schedule_time_of_day = ?,
                    schedule_days_of_week = ?, backup_mode = ?, delete_excluded = ?,
                    exclude_patterns = ?, include_patterns = ?, bandwidth_limit = ?,
                    enabled = ?, updated_at = ?, last_run_at = ?, last_status = ?,
                    next_run_at = ?
                WHERE id = ?
            """, (
                job.name,
                job.source_path,
                job.bucket_name,
                job.remote_prefix,
                job.schedule_type,
                job.schedule_interval_minutes,
                job.schedule_time_of_day,
                json.dumps(job.schedule_days_of_week),
                job.backup_mode,
                1 if job.delete_excluded else 0,
                json.dumps(job.exclude_patterns),
                json.dumps(job.include_patterns),
                job.bandwidth_limit,
                1 if job.enabled else 0,
                job.updated_at,
                job.last_run_at,
                job.last_status,
                job.next_run_at,
                job.id,
            ))
            return cur.rowcount > 0

    def delete_job(self, job_id: int) -> bool:
        with self.transaction() as cur:
            cur.execute("DELETE FROM backup_jobs WHERE id = ?", (job_id,))
            return cur.rowcount > 0

    def update_job_status(
        self,
        job_id: int,
        last_run_at: Optional[str] = None,
        last_status: Optional[str] = None,
        next_run_at: Optional[str] = None,
    ) -> None:
        with self.transaction() as cur:
            updates = []
            params = []
            if last_run_at is not None:
                updates.append("last_run_at = ?")
                params.append(last_run_at)
            if last_status is not None:
                updates.append("last_status = ?")
                params.append(last_status)
            if next_run_at is not None:
                updates.append("next_run_at = ?")
                params.append(next_run_at)
            if updates:
                query = f"UPDATE backup_jobs SET {', '.join(updates)} WHERE id = ?"
                params.append(job_id)
                cur.execute(query, tuple(params))

    # ---------------------------------------------------------
    # Backup Runs CRUD
    # ---------------------------------------------------------

    def create_run(self, run: BackupRun) -> int:
        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO backup_runs (
                    job_id, job_name, status, started_at, completed_at, duration_seconds,
                    bytes_transferred, total_bytes, files_transferred, total_files,
                    files_deleted, errors_count, error_message, exit_code, log_file_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run.job_id,
                run.job_name,
                run.status,
                run.started_at,
                run.completed_at,
                run.duration_seconds,
                run.bytes_transferred,
                run.total_bytes,
                run.files_transferred,
                run.total_files,
                run.files_deleted,
                run.errors_count,
                run.error_message,
                run.exit_code,
                run.log_file_path,
            ))
            run.id = cur.lastrowid
            return cur.lastrowid

    def get_run(self, run_id: int) -> Optional[BackupRun]:
        with self.transaction() as cur:
            cur.execute("SELECT * FROM backup_runs WHERE id = ?", (run_id,))
            row = cur.fetchone()
            return BackupRun.from_dict(dict(row)) if row else None

    def update_run(self, run: BackupRun) -> bool:
        if not run.id:
            return False
        with self.transaction() as cur:
            cur.execute("""
                UPDATE backup_runs SET
                    status = ?, completed_at = ?, duration_seconds = ?,
                    bytes_transferred = ?, total_bytes = ?, files_transferred = ?,
                    total_files = ?, files_deleted = ?, errors_count = ?,
                    error_message = ?, exit_code = ?, log_file_path = ?
                WHERE id = ?
            """, (
                run.status,
                run.completed_at,
                run.duration_seconds,
                run.bytes_transferred,
                run.total_bytes,
                run.files_transferred,
                run.total_files,
                run.files_deleted,
                run.errors_count,
                run.error_message,
                run.exit_code,
                run.log_file_path,
                run.id,
            ))
            return cur.rowcount > 0

    def list_runs(
        self,
        limit: int = 50,
        offset: int = 0,
        job_id: Optional[int] = None,
    ) -> List[BackupRun]:
        with self.transaction() as cur:
            if job_id is not None:
                cur.execute("""
                    SELECT * FROM backup_runs
                    WHERE job_id = ?
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                """, (job_id, limit, offset))
            else:
                cur.execute("""
                    SELECT * FROM backup_runs
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
            return [BackupRun.from_dict(dict(row)) for row in cur.fetchall()]

    def get_active_runs(self) -> List[BackupRun]:
        with self.transaction() as cur:
            cur.execute("SELECT * FROM backup_runs WHERE status = 'running' ORDER BY id DESC")
            return [BackupRun.from_dict(dict(row)) for row in cur.fetchall()]

    # ---------------------------------------------------------
    # File Transfers CRUD
    # ---------------------------------------------------------

    def add_transfer(self, transfer: FileTransfer) -> int:
        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO file_transfers (
                    run_id, job_id, file_path, size_bytes, transferred_bytes,
                    status, error_message, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                transfer.run_id,
                transfer.job_id,
                transfer.file_path,
                transfer.size_bytes,
                transfer.transferred_bytes,
                transfer.status,
                transfer.error_message,
                transfer.timestamp,
            ))
            transfer.id = cur.lastrowid
            return cur.lastrowid

    def list_transfers_for_run(self, run_id: int, limit: int = 200) -> List[FileTransfer]:
        with self.transaction() as cur:
            cur.execute("""
                SELECT * FROM file_transfers
                WHERE run_id = ?
                ORDER BY id ASC
                LIMIT ?
            """, (run_id, limit))
            return [FileTransfer.from_dict(dict(row)) for row in cur.fetchall()]

    # ---------------------------------------------------------
    # Activity Logs CRUD
    # ---------------------------------------------------------

    def add_activity(
        self,
        level: str,
        category: str,
        message: str,
        details: Optional[str] = None,
        job_id: Optional[int] = None,
        run_id: Optional[int] = None,
    ) -> int:
        now = datetime.now().isoformat()
        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO activity_logs (
                    timestamp, level, category, message, details, job_id, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (now, level, category, message, details, job_id, run_id))
            return cur.lastrowid

    def list_activities(
        self,
        limit: int = 100,
        category: Optional[str] = None,
    ) -> List[ActivityLog]:
        with self.transaction() as cur:
            if category:
                cur.execute("""
                    SELECT * FROM activity_logs
                    WHERE category = ?
                    ORDER BY id DESC
                    LIMIT ?
                """, (category, limit))
            else:
                cur.execute("""
                    SELECT * FROM activity_logs
                    ORDER BY id DESC
                    LIMIT ?
                """, (limit,))
            return [ActivityLog.from_dict(dict(row)) for row in cur.fetchall()]

    # ---------------------------------------------------------
    # Aggregated Summary Stats
    # ---------------------------------------------------------

    def get_summary_stats(self) -> Dict[str, Any]:
        with self.transaction() as cur:
            cur.execute("SELECT COUNT(*) as total_jobs, SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) as active_jobs FROM backup_jobs")
            job_row = cur.fetchone()

            cur.execute("""
                SELECT
                    COUNT(*) as total_runs,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_runs,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_runs,
                    SUM(bytes_transferred) as total_bytes_transferred,
                    SUM(files_transferred) as total_files_transferred
                FROM backup_runs
            """)
            run_row = cur.fetchone()

            cur.execute("SELECT MAX(completed_at) as last_backup_at FROM backup_runs WHERE status = 'completed'")
            last_backup_row = cur.fetchone()


            # Sync stats
            cur.execute("""
                SELECT
                    COUNT(*) as total_sync_datasets,
                    SUM(CASE WHEN enabled = 1 AND paused = 0 THEN 1 ELSE 0 END) as active_sync_datasets,
                    SUM(total_bytes) as total_sync_bytes,
                    SUM(total_files) as total_sync_files
                FROM sync_datasets
            """)
            sync_row = cur.fetchone()

            cur.execute("SELECT COUNT(*) as unresolved_conflicts FROM sync_conflicts WHERE resolved = 0")
            conflict_row = cur.fetchone()


            return {
                "total_jobs": job_row["total_jobs"] if job_row else 0,
                "active_jobs": job_row["active_jobs"] if job_row else 0,
                "total_runs": run_row["total_runs"] if run_row else 0,
                "completed_runs": run_row["completed_runs"] if run_row else 0,
                "failed_runs": run_row["failed_runs"] if run_row else 0,
                "total_bytes_transferred": run_row["total_bytes_transferred"] or 0 if run_row else 0,
                "total_files_transferred": run_row["total_files_transferred"] or 0 if run_row else 0,
                "last_backup_at": last_backup_row["last_backup_at"] if last_backup_row else None,
                "total_sync_datasets": sync_row["total_sync_datasets"] if sync_row else 0,
                "active_sync_datasets": sync_row["active_sync_datasets"] if sync_row else 0,
                "total_sync_bytes": sync_row["total_sync_bytes"] or 0 if sync_row else 0,
                "total_sync_files": sync_row["total_sync_files"] or 0 if sync_row else 0,
                "unresolved_conflicts": conflict_row["unresolved_conflicts"] if conflict_row else 0,
            }

    # ---------------------------------------------------------
    # Device Identity Management
    # ---------------------------------------------------------

    def get_or_create_device_id(self) -> str:
        """Retrieve persistent device ID or generate a secure random UUID."""
        # 1. Try settings
        dev_id = self.get_setting("device_id")
        if dev_id and len(dev_id) >= 8:
            return dev_id

        # 2. Try file in state directory
        id_path = get_device_id_path()
        if id_path.exists():
            try:
                with open(id_path, "r", encoding="utf-8") as f:
                    file_id = f.read().strip()
                if file_id and len(file_id) >= 8:
                    self.set_setting("device_id", file_id)
                    return file_id
            except Exception:
                pass

        # 3. Generate new persistent UUID
        new_id = uuid.uuid4().hex[:16]
        self.set_setting("device_id", new_id)
        try:
            with open(id_path, "w", encoding="utf-8") as f:
                f.write(new_id)
        except Exception:
            pass

        return new_id

    def get_device_name(self) -> str:
        """Get human-readable device name (e.g. 'Desktop-PC')."""
        dev_name = self.get_setting("device_name")
        if dev_name:
            return dev_name
        try:
            node_name = platform.node() or socket.gethostname() or "Windows-PC"
            # Clean up domain part if present
            node_name = node_name.split(".")[0]
        except Exception:
            node_name = "Windows-PC"
        self.set_setting("device_name", node_name)
        return node_name

    def set_device_name(self, name: str) -> None:
        self.set_setting("device_name", name.strip())

    # ---------------------------------------------------------
    # Sync Datasets CRUD
    # ---------------------------------------------------------

    def create_sync_dataset(self, dataset: SyncDataset) -> str:
        now = datetime.now().isoformat()
        dataset.created_at = dataset.created_at or now
        dataset.updated_at = now
        if not dataset.dataset_id:
            dataset.dataset_id = uuid.uuid4().hex

        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO sync_datasets (
                    dataset_id, name, bucket_name, remote_prefix, local_path,
                    schedule_mode, schedule_interval_minutes, status, enabled,
                    paused, initial_sync_done, max_delete_threshold, bandwidth_limit,
                    exclude_patterns, total_files, total_bytes, created_at,
                    updated_at, last_sync_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                dataset.dataset_id,
                dataset.name,
                dataset.bucket_name,
                dataset.remote_prefix,
                dataset.local_path,
                dataset.schedule_mode,
                dataset.schedule_interval_minutes,
                dataset.status,
                1 if dataset.enabled else 0,
                1 if dataset.paused else 0,
                1 if dataset.initial_sync_done else 0,
                dataset.max_delete_threshold,
                dataset.bandwidth_limit,
                json.dumps(dataset.exclude_patterns),
                dataset.total_files,
                dataset.total_bytes,
                dataset.created_at,
                dataset.updated_at,
                dataset.last_sync_at,
                dataset.last_error,
            ))
            return dataset.dataset_id

    def get_sync_dataset(self, dataset_id: str) -> Optional[SyncDataset]:
        with self.transaction() as cur:
            cur.execute("SELECT * FROM sync_datasets WHERE dataset_id = ?", (dataset_id,))
            row = cur.fetchone()
            return SyncDataset.from_dict(dict(row)) if row else None

    def list_sync_datasets(self) -> List[SyncDataset]:
        with self.transaction() as cur:
            cur.execute("SELECT * FROM sync_datasets ORDER BY created_at ASC")
            return [SyncDataset.from_dict(dict(row)) for row in cur.fetchall()]

    def update_sync_dataset(self, dataset: SyncDataset) -> bool:
        dataset.updated_at = datetime.now().isoformat()
        with self.transaction() as cur:
            cur.execute("""
                UPDATE sync_datasets SET
                    name = ?, bucket_name = ?, remote_prefix = ?, local_path = ?,
                    schedule_mode = ?, schedule_interval_minutes = ?, status = ?,
                    enabled = ?, paused = ?, initial_sync_done = ?,
                    max_delete_threshold = ?, bandwidth_limit = ?, exclude_patterns = ?,
                    total_files = ?, total_bytes = ?, updated_at = ?,
                    last_sync_at = ?, last_error = ?
                WHERE dataset_id = ?
            """, (
                dataset.name,
                dataset.bucket_name,
                dataset.remote_prefix,
                dataset.local_path,
                dataset.schedule_mode,
                dataset.schedule_interval_minutes,
                dataset.status,
                1 if dataset.enabled else 0,
                1 if dataset.paused else 0,
                1 if dataset.initial_sync_done else 0,
                dataset.max_delete_threshold,
                dataset.bandwidth_limit,
                json.dumps(dataset.exclude_patterns),
                dataset.total_files,
                dataset.total_bytes,
                dataset.updated_at,
                dataset.last_sync_at,
                dataset.last_error,
                dataset.dataset_id,
            ))
            return cur.rowcount > 0

    def delete_sync_dataset(self, dataset_id: str) -> bool:
        with self.transaction() as cur:
            cur.execute("DELETE FROM sync_datasets WHERE dataset_id = ?", (dataset_id,))
            deleted = cur.rowcount > 0
            cur.execute("DELETE FROM sync_devices WHERE dataset_id = ?", (dataset_id,))
            cur.execute("DELETE FROM sync_conflicts WHERE dataset_id = ?", (dataset_id,))
            cur.execute("DELETE FROM sync_file_state WHERE dataset_id = ?", (dataset_id,))
            return deleted


    def update_sync_status(
        self,
        dataset_id: str,
        status: str,
        last_sync_at: Optional[str] = None,
        last_error: Optional[str] = None,
        total_files: Optional[int] = None,
        total_bytes: Optional[int] = None,
    ) -> None:
        with self.transaction() as cur:
            updates = ["status = ?", "updated_at = ?"]
            params = [status, datetime.now().isoformat()]
            if last_sync_at is not None:
                updates.append("last_sync_at = ?")
                params.append(last_sync_at)
            if last_error is not None:
                updates.append("last_error = ?")
                params.append(last_error)
            if total_files is not None:
                updates.append("total_files = ?")
                params.append(total_files)
            if total_bytes is not None:
                updates.append("total_bytes = ?")
                params.append(total_bytes)

            query = f"UPDATE sync_datasets SET {', '.join(updates)} WHERE dataset_id = ?"
            params.append(dataset_id)
            cur.execute(query, tuple(params))

    # ---------------------------------------------------------
    # Sync Devices CRUD
    # ---------------------------------------------------------

    def upsert_sync_device(self, device: Device) -> bool:
        now = datetime.now().isoformat()
        dataset_id = device.dataset_id or ""
        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO sync_devices (
                    device_id, dataset_id, device_name, is_current_device,
                    last_seen_at, last_sync_at, status, client_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id, dataset_id) DO UPDATE SET
                    device_name = excluded.device_name,
                    is_current_device = excluded.is_current_device,
                    last_seen_at = COALESCE(excluded.last_seen_at, sync_devices.last_seen_at),
                    last_sync_at = COALESCE(excluded.last_sync_at, sync_devices.last_sync_at),
                    status = excluded.status,
                    client_version = excluded.client_version,
                    updated_at = excluded.updated_at
            """, (
                device.device_id,
                dataset_id,
                device.device_name,
                1 if device.is_current_device else 0,
                device.last_seen_at or now,
                device.last_sync_at,
                device.status,
                device.client_version,
                now,
            ))
            return True

    def list_sync_devices(self, dataset_id: Optional[str] = None) -> List[Device]:
        with self.transaction() as cur:
            if dataset_id:
                cur.execute("SELECT * FROM sync_devices WHERE dataset_id = ? ORDER BY is_current_device DESC, device_name ASC", (dataset_id,))
            else:
                cur.execute("SELECT * FROM sync_devices ORDER BY is_current_device DESC, device_name ASC")
            return [Device.from_dict(dict(row)) for row in cur.fetchall()]

    def get_sync_device(self, device_id: str, dataset_id: Optional[str] = None) -> Optional[Device]:
        with self.transaction() as cur:
            if dataset_id:
                cur.execute("SELECT * FROM sync_devices WHERE device_id = ? AND dataset_id = ?", (device_id, dataset_id))
            else:
                cur.execute("SELECT * FROM sync_devices WHERE device_id = ? LIMIT 1", (device_id,))
            row = cur.fetchone()
            return Device.from_dict(dict(row)) if row else None

    def delete_sync_device(self, device_id: str, dataset_id: Optional[str] = None) -> bool:
        with self.transaction() as cur:
            if dataset_id:
                cur.execute("DELETE FROM sync_devices WHERE device_id = ? AND dataset_id = ?", (device_id, dataset_id))
            else:
                cur.execute("DELETE FROM sync_devices WHERE device_id = ?", (device_id,))
            return cur.rowcount > 0

    def update_device_heartbeat(self, device_id: str, dataset_id: Optional[str] = None, status: str = "online") -> bool:
        now = datetime.now().isoformat()
        with self.transaction() as cur:
            if dataset_id:
                cur.execute("""
                    UPDATE sync_devices SET last_seen_at = ?, status = ?, updated_at = ?
                    WHERE device_id = ? AND dataset_id = ?
                """, (now, status, now, device_id, dataset_id))
            else:
                cur.execute("""
                    UPDATE sync_devices SET last_seen_at = ?, status = ?, updated_at = ?
                    WHERE device_id = ?
                """, (now, status, now, device_id))
            return cur.rowcount > 0

    # ---------------------------------------------------------
    # Sync Conflicts CRUD
    # ---------------------------------------------------------

    def create_conflict(self, conflict: SyncConflict) -> int:
        now = datetime.now().isoformat()
        conflict.detected_at = conflict.detected_at or now
        with self.transaction() as cur:
            cur.execute("""
                INSERT INTO sync_conflicts (
                    dataset_id, relative_path, local_path, local_modified_at,
                    local_size_bytes, remote_device_id, remote_device_name,
                    remote_modified_at, remote_size_bytes, conflict_file_path,
                    detected_at, resolved, resolution, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                conflict.dataset_id,
                conflict.relative_path,
                conflict.local_path,
                conflict.local_modified_at,
                conflict.local_size_bytes,
                conflict.remote_device_id,
                conflict.remote_device_name,
                conflict.remote_modified_at,
                conflict.remote_size_bytes,
                conflict.conflict_file_path,
                conflict.detected_at,
                1 if conflict.resolved else 0,
                conflict.resolution,
                conflict.resolved_at,
            ))
            conflict.id = cur.lastrowid
            return cur.lastrowid

    def list_conflicts(self, dataset_id: Optional[str] = None, include_resolved: bool = False) -> List[SyncConflict]:
        with self.transaction() as cur:
            query = "SELECT * FROM sync_conflicts WHERE 1=1"
            params = []
            if dataset_id:
                query += " AND dataset_id = ?"
                params.append(dataset_id)
            if not include_resolved:
                query += " AND resolved = 0"
            query += " ORDER BY id DESC"
            cur.execute(query, tuple(params))
            return [SyncConflict.from_dict(dict(row)) for row in cur.fetchall()]

    def get_conflict(self, conflict_id: int) -> Optional[SyncConflict]:
        with self.transaction() as cur:
            cur.execute("SELECT * FROM sync_conflicts WHERE id = ?", (conflict_id,))
            row = cur.fetchone()
            return SyncConflict.from_dict(dict(row)) if row else None

    def resolve_conflict_db(self, conflict_id: int, resolution: str) -> bool:
        now = datetime.now().isoformat()
        with self.transaction() as cur:
            cur.execute("""
                UPDATE sync_conflicts SET
                    resolved = 1,
                    resolution = ?,
                    resolved_at = ?
                WHERE id = ?
            """, (resolution, now, conflict_id))
            return cur.rowcount > 0

    def count_unresolved_conflicts(self, dataset_id: Optional[str] = None) -> int:
        with self.transaction() as cur:
            if dataset_id:
                cur.execute("SELECT COUNT(*) as cnt FROM sync_conflicts WHERE dataset_id = ? AND resolved = 0", (dataset_id,))
            else:
                cur.execute("SELECT COUNT(*) as cnt FROM sync_conflicts WHERE resolved = 0")
            row = cur.fetchone()
            return row["cnt"] if row else 0

