"""Path resolution and directory management for r2sync."""

import os
import sys
from pathlib import Path
from typing import Optional

from r2sync.config import APP_NAME


def get_data_dir() -> Path:
    """Return the base persistent application data directory.
    
    On Windows: %LOCALAPPDATA%\r2sync
    On Linux/macOS: ~/.local/share/r2sync (or $XDG_DATA_HOME/r2sync)
    Can be overridden with environment variable R2SYNC_DATA_DIR.
    """
    env_override = os.environ.get("R2SYNC_DATA_DIR")
    if env_override:
        path = Path(env_override)
    elif sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            path = Path(local_app_data) / APP_NAME
        else:
            path = Path.home() / "AppData" / "Local" / APP_NAME
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            path = Path(xdg_data) / APP_NAME
        else:
            path = Path.home() / ".local" / "share" / APP_NAME

    path.mkdir(parents=True, exist_ok=True)
    return path


def get_database_path() -> Path:
    """Return path to SQLite database file (%LOCALAPPDATA%/r2sync/database.sqlite)."""
    return get_data_dir() / "database.sqlite"


def get_logs_dir() -> Path:
    """Return path to logs directory (%LOCALAPPDATA%/r2sync/logs)."""
    path = get_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_rclone_dir() -> Path:
    """Return path to rclone binary directory (%LOCALAPPDATA%/r2sync/rclone)."""
    path = get_data_dir() / "rclone"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_rclone_executable_path() -> Path:
    """Return expected path to rclone executable."""
    ext = ".exe" if sys.platform == "win32" else ""
    return get_rclone_dir() / f"rclone{ext}"


def get_state_dir() -> Path:
    """Return path to runtime state directory (%LOCALAPPDATA%/r2sync/state)."""
    path = get_data_dir() / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cache_dir() -> Path:
    """Return path to cache directory (%LOCALAPPDATA%/r2sync/cache)."""
    path = get_data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_ipc_token_path() -> Path:
    """Return path to IPC authentication token file."""
    return get_state_dir() / "ipc_auth.token"


def get_service_pid_path() -> Path:
    """Return path to background service PID file."""
    return get_state_dir() / "service.pid"


def get_device_id_path() -> Path:
    """Return path to persistent device ID file."""
    return get_state_dir() / "device.id"


def get_bisync_dir() -> Path:
    """Return path to rclone bisync working directory."""
    path = get_data_dir() / "bisync"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_dataset_bisync_dir(dataset_id: str) -> Path:
    """Return path to rclone bisync workdir for a specific dataset."""
    path = get_bisync_dir() / dataset_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_recovery_dir() -> Path:
    """Return path to local file recovery/backup directory."""
    path = get_data_dir() / "recovery"
    path.mkdir(parents=True, exist_ok=True)
    return path

