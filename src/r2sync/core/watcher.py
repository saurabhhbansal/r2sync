"""Filesystem change detection engine with native Windows/Linux watching and debouncing."""

import ctypes
import fnmatch
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from r2sync.config import DEFAULT_EXCLUDE_PATTERNS, SYNC_DEFAULT_DEBOUNCE_SECONDS

logger = logging.getLogger(__name__)


def is_path_excluded(rel_path: str, exclude_patterns: List[str]) -> bool:
    """Check if a relative path matches any exclusion patterns or internal temp file rules."""
    norm = rel_path.replace("\\", "/")
    filename = os.path.basename(norm)

    # Ignore internal/temporary files
    if filename.startswith("~$") or filename.endswith(".tmp") or filename.endswith(".partial"):
        return True
    if filename in ("Thumbs.db", "desktop.ini", ".DS_Store"):
        return True
    if "/.r2sync_trash/" in f"/{norm}/" or "/.git/" in f"/{norm}/":
        return True

    all_patterns = list(DEFAULT_EXCLUDE_PATTERNS) + (exclude_patterns or [])
    for pat in all_patterns:
        pat = pat.strip()
        if not pat:
            continue
        pat_clean = pat.rstrip("/")
        if pat.endswith("/"):
            if fnmatch.fnmatch(norm, f"*{pat_clean}*") or fnmatch.fnmatch(norm, f"{pat_clean}/*"):
                return True
        elif fnmatch.fnmatch(filename, pat) or fnmatch.fnmatch(norm, pat):
            return True

    return False


class WindowsDirectoryWatcher:
    """Native Windows filesystem watcher using ReadDirectoryChangesW via ctypes."""

    def __init__(
        self,
        dataset_id: str,
        folder_path: str,
        callback: Callable[[str], None],
        exclude_patterns: Optional[List[str]] = None,
    ):
        self.dataset_id = dataset_id
        self.folder_path = folder_path
        self.callback = callback
        self.exclude_patterns = exclude_patterns or []
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if not sys.platform == "win32":
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watch_loop,
            name=f"win-watch-{self.dataset_id[:8]}",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None

    def _watch_loop(self):
        import ctypes.wintypes as wintypes

        FILE_LIST_DIRECTORY = 0x0001
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        FILE_SHARE_DELETE = 0x00000004
        OPEN_EXISTING = 3
        FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

        FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
        FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
        FILE_NOTIFY_CHANGE_ATTRIBUTES = 0x00000004
        FILE_NOTIFY_CHANGE_SIZE = 0x00000008
        FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
        FILE_NOTIFY_CHANGE_CREATION = 0x00000040

        filter_flags = (
            FILE_NOTIFY_CHANGE_FILE_NAME
            | FILE_NOTIFY_CHANGE_DIR_NAME
            | FILE_NOTIFY_CHANGE_SIZE
            | FILE_NOTIFY_CHANGE_LAST_WRITE
            | FILE_NOTIFY_CHANGE_CREATION
        )

        kernel32 = ctypes.windll.kernel32

        handle = kernel32.CreateFileW(
            self.folder_path,
            FILE_LIST_DIRECTORY,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )

        if handle == -1 or handle == 0xFFFFFFFF:
            logger.warning(f"Could not open directory handle for {self.folder_path}")
            return

        buffer = ctypes.create_string_buffer(64 * 1024)
        bytes_returned = wintypes.DWORD()

        try:
            while not self._stop_event.is_set():
                success = kernel32.ReadDirectoryChangesW(
                    handle,
                    buffer,
                    len(buffer),
                    True,  # watch subtree
                    filter_flags,
                    ctypes.byref(bytes_returned),
                    None,
                    None,
                )

                if self._stop_event.is_set():
                    break

                if success and bytes_returned.value > 0:
                    self.callback(self.dataset_id)
                else:
                    time.sleep(0.5)

        except Exception as e:
            logger.debug(f"Windows watcher loop error for {self.folder_path}: {e}")
        finally:
            kernel32.CloseHandle(handle)


class PollingDirectoryWatcher:
    """Lightweight cross-platform watcher scanning file mtimes and sizes with interval."""

    def __init__(
        self,
        dataset_id: str,
        folder_path: str,
        callback: Callable[[str], None],
        exclude_patterns: Optional[List[str]] = None,
        poll_interval: float = 4.0,
    ):
        self.dataset_id = dataset_id
        self.folder_path = folder_path
        self.callback = callback
        self.exclude_patterns = exclude_patterns or []
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._known_state: Dict[str, float] = {}

    def start(self):
        self._stop_event.clear()
        self._known_state = self._snapshot()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name=f"poll-watch-{self.dataset_id[:8]}",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None

    def _snapshot(self) -> Dict[str, float]:
        state = {}
        base = Path(self.folder_path)
        if not base.exists():
            return state

        try:
            for root, dirs, files in os.walk(str(base)):
                rel_root = os.path.relpath(root, str(base))
                if rel_root != "." and is_path_excluded(rel_root, self.exclude_patterns):
                    dirs[:] = []
                    continue

                for f in files:
                    rel_f = os.path.normpath(os.path.join(rel_root, f))
                    if is_path_excluded(rel_f, self.exclude_patterns):
                        continue
                    full_p = os.path.join(root, f)
                    try:
                        st = os.stat(full_p)
                        state[rel_f] = st.st_mtime
                    except OSError:
                        pass
        except Exception as e:
            logger.debug(f"Polling snapshot error: {e}")

        return state

    def _poll_loop(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(self.poll_interval)
            if self._stop_event.is_set():
                break

            current_state = self._snapshot()
            if current_state != self._known_state:
                self._known_state = current_state
                self.callback(self.dataset_id)


class DebouncedWatcherManager:
    """Manages active filesystem watchers and coalesces change bursts with debouncing."""

    def __init__(
        self,
        on_change_triggered: Callable[[str], None],
        debounce_seconds: float = SYNC_DEFAULT_DEBOUNCE_SECONDS,
    ):
        self.on_change_triggered = on_change_triggered
        self.debounce_seconds = debounce_seconds
        self._watchers: Dict[str, Any] = {}
        self._debounce_timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _on_raw_change(self, dataset_id: str):
        with self._lock:
            # Cancel existing debounce timer for this dataset
            if dataset_id in self._debounce_timers:
                self._debounce_timers[dataset_id].cancel()

            # Schedule new fire after debounce interval
            timer = threading.Timer(
                self.debounce_seconds,
                self._fire_change,
                args=(dataset_id,),
            )
            self._debounce_timers[dataset_id] = timer
            timer.start()

    def _fire_change(self, dataset_id: str):
        with self._lock:
            self._debounce_timers.pop(dataset_id, None)
        logger.info(f"Filesystem watcher detected debounced change for dataset {dataset_id}")
        try:
            self.on_change_triggered(dataset_id)
        except Exception as e:
            logger.error(f"Error in on_change_triggered callback for {dataset_id}: {e}")

    def start_watching(
        self,
        dataset_id: str,
        folder_path: str,
        exclude_patterns: Optional[List[str]] = None,
    ) -> bool:
        if not os.path.exists(folder_path):
            logger.warning(f"Cannot watch non-existent path: {folder_path}")
            return False

        with self._lock:
            self.stop_watching_unlocked(dataset_id)

            if sys.platform == "win32":
                watcher = WindowsDirectoryWatcher(
                    dataset_id=dataset_id,
                    folder_path=folder_path,
                    callback=self._on_raw_change,
                    exclude_patterns=exclude_patterns,
                )
            else:
                watcher = PollingDirectoryWatcher(
                    dataset_id=dataset_id,
                    folder_path=folder_path,
                    callback=self._on_raw_change,
                    exclude_patterns=exclude_patterns,
                )

            watcher.start()
            self._watchers[dataset_id] = watcher
            logger.info(f"Started real-time watcher for dataset {dataset_id} at {folder_path}")
            return True

    def stop_watching_unlocked(self, dataset_id: str):
        if dataset_id in self._debounce_timers:
            self._debounce_timers[dataset_id].cancel()
            self._debounce_timers.pop(dataset_id, None)

        if dataset_id in self._watchers:
            watcher = self._watchers.pop(dataset_id)
            try:
                watcher.stop()
            except Exception as e:
                logger.debug(f"Error stopping watcher: {e}")

    def stop_watching(self, dataset_id: str):
        with self._lock:
            self.stop_watching_unlocked(dataset_id)

    def stop_all(self):
        with self._lock:
            for timer in self._debounce_timers.values():
                timer.cancel()
            self._debounce_timers.clear()

            for watcher in self._watchers.values():
                try:
                    watcher.stop()
                except Exception:
                    pass
            self._watchers.clear()
            logger.info("All filesystem watchers stopped.")
