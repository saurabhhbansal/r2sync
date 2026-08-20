"""Domain data models for r2sync."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import json


class JobScheduleType(str, Enum):
    MANUAL = "manual"
    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"
    REALTIME_WATCH = "realtime_watch"


class BackupMode(str, Enum):
    SYNC = "sync"  # Exact mirror (deletes destination files absent locally)
    COPY = "copy"  # Additive only (preserves remote files)


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    PAUSED = "paused"


@dataclass
class BackupJob:
    name: str
    source_path: str
    bucket_name: str
    id: Optional[int] = None
    remote_prefix: str = ""
    schedule_type: str = JobScheduleType.DAILY.value
    schedule_interval_minutes: int = 60
    schedule_time_of_day: str = "02:00"  # 24h format HH:MM
    schedule_days_of_week: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])  # 0=Monday, 6=Sunday
    backup_mode: str = BackupMode.SYNC.value
    delete_excluded: bool = False
    exclude_patterns: List[str] = field(default_factory=list)
    include_patterns: List[str] = field(default_factory=list)
    bandwidth_limit: Optional[str] = None  # e.g., '10M', '500k', or None for unlimited
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_run_at: Optional[str] = None
    last_status: Optional[str] = None
    next_run_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackupJob":
        data = dict(data)
        if isinstance(data.get("schedule_days_of_week"), str):
            try:
                data["schedule_days_of_week"] = json.loads(data["schedule_days_of_week"])
            except Exception:
                data["schedule_days_of_week"] = [0, 1, 2, 3, 4, 5, 6]
        if isinstance(data.get("exclude_patterns"), str):
            try:
                data["exclude_patterns"] = json.loads(data["exclude_patterns"])
            except Exception:
                data["exclude_patterns"] = []
        if isinstance(data.get("include_patterns"), str):
            try:
                data["include_patterns"] = json.loads(data["include_patterns"])
            except Exception:
                data["include_patterns"] = []
        if "enabled" in data:
            data["enabled"] = bool(data["enabled"])
        if "delete_excluded" in data:
            data["delete_excluded"] = bool(data["delete_excluded"])
        return cls(**data)


@dataclass
class BackupRun:
    job_id: int
    job_name: str
    id: Optional[int] = None
    status: str = RunStatus.PENDING.value
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    duration_seconds: float = 0.0
    bytes_transferred: int = 0
    total_bytes: int = 0
    files_transferred: int = 0
    total_files: int = 0
    files_deleted: int = 0
    errors_count: int = 0
    error_message: Optional[str] = None
    exit_code: Optional[int] = None
    log_file_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackupRun":
        return cls(**data)


@dataclass
class FileTransfer:
    run_id: int
    job_id: int
    file_path: str
    size_bytes: int
    id: Optional[int] = None
    transferred_bytes: int = 0
    status: str = "transferred"  # transferred, deleted, checked, error
    error_message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileTransfer":
        return cls(**data)


@dataclass
class ActivityLog:
    timestamp: str
    level: str
    category: str
    message: str
    id: Optional[int] = None
    details: Optional[str] = None
    job_id: Optional[int] = None
    run_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActivityLog":
        return cls(**data)


@dataclass
class R2Credentials:
    account_id: str
    access_key_id: str
    secret_access_key: str
    default_bucket: Optional[str] = None
    endpoint_url: Optional[str] = None

    def __post_init__(self):
        if self.account_id:
            clean_acc = self.account_id.strip()
            clean_acc = clean_acc.replace("https://", "").replace("http://", "").rstrip("/")
            if ".r2.cloudflarestorage.com" in clean_acc:
                clean_acc = clean_acc.replace(".r2.cloudflarestorage.com", "")
            self.account_id = clean_acc
        if self.access_key_id:
            self.access_key_id = self.access_key_id.strip()
        if self.secret_access_key:
            self.secret_access_key = self.secret_access_key.strip()
        if self.default_bucket:
            self.default_bucket = self.default_bucket.strip()

    def get_endpoint(self) -> str:
        if self.endpoint_url:
            return self.endpoint_url
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


@dataclass
class R2BucketInfo:
    name: str
    created_at: Optional[str] = None
    location: Optional[str] = "auto"
    object_count: Optional[int] = None
    size_bytes: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TransferProgressEvent:
    job_id: int
    run_id: Optional[int] = None
    percentage: float = 0.0
    bytes_transferred: int = 0
    total_bytes: int = 0
    speed_bytes_per_sec: float = 0.0
    eta_seconds: Optional[int] = None
    current_file: Optional[str] = None
    files_transferred: int = 0
    total_files: int = 0
    errors_count: int = 0

    # --- Progress phase reporting -------------------------------------
    # ``phase`` is one of "scanning" (rclone is still enumerating, so the
    # totals below are only what has been *discovered* so far), "transferring"
    # (the transfer queue is complete, so totals are final) or "finalizing".
    # ``totals_final`` says whether ``total_bytes``/``total_files`` may still
    # grow, which is what lets the UI choose between showing
    # "Transferred / Total" and "Scanned / Discovered".
    phase: str = "scanning"
    totals_final: bool = False
    checks_done: int = 0
    total_checks: int = 0
    estimated_total_bytes: int = 0
    estimated_total_files: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------------------
# Multi-PC Sync Data Models
# ----------------------------------------------------------------------

class SyncStatus(str, Enum):
    SYNCED = "synced"
    SYNCING = "syncing"
    WAITING = "waiting"
    OFFLINE = "offline"
    CONFLICT = "conflict"
    PAUSED = "paused"
    ERROR = "error"
    NEEDS_ATTENTION = "needs_attention"


class SyncScheduleMode(str, Enum):
    REALTIME = "realtime"
    INTERVAL = "interval"
    DAILY = "daily"
    MANUAL = "manual"


class ConflictResolution(str, Enum):
    KEEP_LOCAL = "keep_local"
    KEEP_REMOTE = "keep_remote"
    KEEP_BOTH = "keep_both"


@dataclass
class Device:
    device_id: str
    device_name: str
    dataset_id: Optional[str] = None
    is_current_device: bool = False
    last_seen_at: Optional[str] = None
    last_sync_at: Optional[str] = None
    status: str = "online"  # online, offline, syncing
    client_version: str = "1.0.0"
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Device":
        data = dict(data)
        if "is_current_device" in data:
            data["is_current_device"] = bool(data["is_current_device"])
        return cls(**data)


@dataclass
class SyncDataset:
    dataset_id: str
    name: str
    bucket_name: str
    local_path: str
    remote_prefix: str = ""
    schedule_mode: str = SyncScheduleMode.REALTIME.value
    schedule_interval_minutes: int = 15
    status: str = SyncStatus.WAITING.value
    enabled: bool = True
    paused: bool = False
    initial_sync_done: bool = False
    max_delete_threshold: int = 50
    bandwidth_limit: Optional[str] = None
    exclude_patterns: List[str] = field(default_factory=list)
    total_files: int = 0
    total_bytes: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_sync_at: Optional[str] = None
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SyncDataset":
        data = dict(data)
        if isinstance(data.get("exclude_patterns"), str):
            try:
                data["exclude_patterns"] = json.loads(data["exclude_patterns"])
            except Exception:
                data["exclude_patterns"] = []
        if "enabled" in data:
            data["enabled"] = bool(data["enabled"])
        if "paused" in data:
            data["paused"] = bool(data["paused"])
        if "initial_sync_done" in data:
            data["initial_sync_done"] = bool(data["initial_sync_done"])
        return cls(**data)


@dataclass
class SyncConflict:
    dataset_id: str
    relative_path: str
    local_path: str
    id: Optional[int] = None
    local_modified_at: str = field(default_factory=lambda: datetime.now().isoformat())
    local_size_bytes: int = 0
    remote_device_id: Optional[str] = None
    remote_device_name: Optional[str] = None
    remote_modified_at: Optional[str] = None
    remote_size_bytes: int = 0
    conflict_file_path: Optional[str] = None
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved: bool = False
    resolution: Optional[str] = None
    resolved_at: Optional[str] = None


    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SyncConflict":
        data = dict(data)
        if "resolved" in data:
            data["resolved"] = bool(data["resolved"])
        return cls(**data)


@dataclass
class RemoteDatasetInfo:
    dataset_id: str
    name: str
    bucket_name: str
    created_by_device: str = "Unknown"
    # Which computer and which folder this dataset was created from. Together
    # they let a re-added folder be matched back to the data it already has in
    # R2 instead of starting a second copy. Datasets written before these were
    # published carry empty strings, so treat absence as "unknown", not "no".
    created_by_device_id: str = ""
    local_path: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    total_files: int = 0
    total_bytes: int = 0
    protocol_version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RemoteDatasetInfo":
        return cls(**data)


@dataclass
class SyncProgressEvent:
    dataset_id: str
    status: str = SyncStatus.SYNCING.value
    percentage: float = 0.0
    bytes_transferred: int = 0
    total_bytes: int = 0
    speed_bytes_per_sec: float = 0.0
    eta_seconds: Optional[int] = None
    current_file: Optional[str] = None
    files_transferred: int = 0
    total_files: int = 0
    errors_count: int = 0
    conflicts_count: int = 0
    message: Optional[str] = None

    # --- Progress phase reporting -------------------------------------
    # ``phase`` is one of "scanning" (rclone is still enumerating, so the
    # totals below are only what has been *discovered* so far), "transferring"
    # (the transfer queue is complete, so totals are final) or "finalizing".
    # ``totals_final`` says whether ``total_bytes``/``total_files`` may still
    # grow, which is what lets the UI choose between showing
    # "Transferred / Total" and "Scanned / Discovered".
    phase: str = "scanning"
    totals_final: bool = False
    checks_done: int = 0
    total_checks: int = 0
    estimated_total_bytes: int = 0
    estimated_total_files: int = 0
    direction: str = "sync"  # "upload", "download" or "sync"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

