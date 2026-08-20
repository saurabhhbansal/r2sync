"""Filesystem change detection engine with native Windows/Linux watching and debouncing."""

import ctypes
import fnmatch
import logging
import os
import struct
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from r2sync.config import DEFAULT_EXCLUDE_PATTERNS, SYNC_DEFAULT_DEBOUNCE_SECONDS

logger = logging.getLogger(__name__)

# Interval at which the manager verifies that every registered watcher is still
# alive, and restarts (or downgrades to polling) the ones that died.
WATCHER_SUPERVISION_INTERVAL_SECONDS = 20.0

# ReadDirectoryChangesW action codes (winnt.h)
FILE_ACTION_ADDED = 0x00000001
FILE_ACTION_REMOVED = 0x00000002
FILE_ACTION_MODIFIED = 0x00000003
FILE_ACTION_RENAMED_OLD_NAME = 0x00000004
FILE_ACTION_RENAMED_NEW_NAME = 0x00000005

ACTION_NAMES = {
    FILE_ACTION_ADDED: "created",
    FILE_ACTION_REMOVED: "deleted",
    FILE_ACTION_MODIFIED: "modified",
    FILE_ACTION_RENAMED_OLD_NAME: "renamed_from",
    FILE_ACTION_RENAMED_NEW_NAME: "renamed_to",
}


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


def parse_file_notify_information(buffer: bytes, bytes_returned: int) -> List[Tuple[int, str]]:
    """Decode a ReadDirectoryChangesW output buffer into (action, relative_path) pairs.

    The buffer holds a chain of FILE_NOTIFY_INFORMATION records:
        DWORD NextEntryOffset; DWORD Action; DWORD FileNameLength; WCHAR FileName[]
    ``NextEntryOffset`` is 0 on the final record. FileNameLength counts *bytes*,
    not characters, and the name is UTF-16LE without a NUL terminator.

    Kept free of ``ctypes.wintypes`` so it stays importable (and testable) on
    non-Windows hosts.
    """
    results: List[Tuple[int, str]] = []
    if bytes_returned <= 0:
        return results

    data = buffer[:bytes_returned]
    offset = 0
    while offset + 12 <= len(data):
        next_offset, action, name_len = struct.unpack_from("<III", data, offset)
        name_start = offset + 12
        name_end = name_start + name_len
        if name_len < 0 or name_end > len(data):
            break
        try:
            name = data[name_start:name_end].decode("utf-16-le")
        except UnicodeDecodeError:
            name = ""
        if name:
            results.append((action, name.replace("\\", "/")))
        if next_offset == 0:
            break
        offset += next_offset

    return results


class WindowsDirectoryWatcher:
    """Native Windows filesystem watcher using overlapped ReadDirectoryChangesW.

    Overlapped (asynchronous) I/O is used rather than a blocking call so that
    ``stop()`` returns promptly instead of leaving a thread parked inside the
    kernel until the next unrelated filesystem event arrives.
    """

    def __init__(
        self,
        dataset_id: str,
        folder_path: str,
        callback: Callable[[str], None],
        exclude_patterns: Optional[List[str]] = None,
        on_failure: Optional[Callable[[str, str], None]] = None,
    ):
        self.dataset_id = dataset_id
        self.folder_path = folder_path
        self.callback = callback
        self.exclude_patterns = exclude_patterns or []
        self.on_failure = on_failure
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stop_handle: Optional[int] = None
        self._started_ok = threading.Event()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        self._stop_event.clear()
        self._started_ok.clear()
        self._thread = threading.Thread(
            target=self._watch_loop,
            name=f"win-watch-{self.dataset_id[:8]}",
            daemon=True,
        )
        self._thread.start()
        # Wait briefly for the directory handle to open so a bad path is reported
        # as a start failure instead of silently pretending to watch.
        self._started_ok.wait(timeout=2.0)
        return self._started_ok.is_set()

    def stop(self):
        self._stop_event.set()
        # Wake the overlapped wait immediately.
        if self._stop_handle:
            try:
                ctypes.windll.kernel32.SetEvent(self._stop_handle)
            except Exception:
                pass
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        self._thread = None

    def _emit(self, paths: List[str]) -> None:
        """Forward a change notification unless every changed path is excluded."""
        if paths and all(is_path_excluded(p, self.exclude_patterns) for p in paths):
            logger.debug(
                f"Watcher ignoring {len(paths)} excluded change(s) in dataset {self.dataset_id}"
            )
            return
        self.callback(self.dataset_id)

    def _watch_loop(self):
        import ctypes.wintypes as wintypes

        FILE_LIST_DIRECTORY = 0x0001
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        FILE_SHARE_DELETE = 0x00000004
        OPEN_EXISTING = 3
        FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
        FILE_FLAG_OVERLAPPED = 0x40000000
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        WAIT_OBJECT_0 = 0x00000000
        ERROR_NOTIFY_ENUM_DIR = 1022
        ERROR_OPERATION_ABORTED = 995
        ERROR_IO_PENDING = 997

        FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
        FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
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

        class OVERLAPPED(ctypes.Structure):
            _fields_ = [
                ("Internal", ctypes.POINTER(ctypes.c_ulong)),
                ("InternalHigh", ctypes.POINTER(ctypes.c_ulong)),
                ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE),
            ]

        kernel32 = ctypes.windll.kernel32

        # Explicit prototypes: without these ctypes assumes a 32-bit int return
        # value and silently truncates 64-bit HANDLEs.
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.CreateEventW.argtypes = [
            wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR,
        ]
        kernel32.ReadDirectoryChangesW.restype = wintypes.BOOL
        kernel32.ReadDirectoryChangesW.argtypes = [
            wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.BOOL,
            wintypes.DWORD, wintypes.LPDWORD, ctypes.POINTER(OVERLAPPED), wintypes.LPVOID,
        ]
        kernel32.WaitForMultipleObjects.restype = wintypes.DWORD
        kernel32.WaitForMultipleObjects.argtypes = [
            wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD,
        ]
        kernel32.GetOverlappedResult.restype = wintypes.BOOL
        kernel32.GetOverlappedResult.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(OVERLAPPED), wintypes.LPDWORD, wintypes.BOOL,
        ]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CancelIo.argtypes = [wintypes.HANDLE]
        kernel32.SetEvent.argtypes = [wintypes.HANDLE]
        kernel32.ResetEvent.argtypes = [wintypes.HANDLE]

        handle = None
        change_event = None
        stop_handle = None
        failure_reason: Optional[str] = None

        try:
            handle = kernel32.CreateFileW(
                self.folder_path,
                FILE_LIST_DIRECTORY,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                None,
                OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OVERLAPPED,
                None,
            )

            if not handle or handle == INVALID_HANDLE_VALUE:
                err = ctypes.GetLastError()
                failure_reason = f"CreateFileW failed for {self.folder_path} (error {err})"
                logger.warning(failure_reason)
                return

            change_event = kernel32.CreateEventW(None, True, False, None)
            stop_handle = kernel32.CreateEventW(None, True, False, None)
            if not change_event or not stop_handle:
                failure_reason = "Could not create Windows synchronization events"
                logger.warning(failure_reason)
                return
            self._stop_handle = stop_handle

            buffer = ctypes.create_string_buffer(64 * 1024)
            overlapped = OVERLAPPED()
            overlapped.hEvent = change_event

            wait_handles = (wintypes.HANDLE * 2)(change_event, stop_handle)
            self._started_ok.set()
            logger.debug(f"ReadDirectoryChangesW watching {self.folder_path}")

            while not self._stop_event.is_set():
                kernel32.ResetEvent(change_event)
                ok = kernel32.ReadDirectoryChangesW(
                    handle,
                    buffer,
                    ctypes.sizeof(buffer),
                    True,  # watch subtree
                    filter_flags,
                    None,  # lpBytesReturned is undefined for overlapped I/O
                    ctypes.byref(overlapped),
                    None,
                )
                if not ok:
                    err = ctypes.GetLastError()
                    if err == ERROR_IO_PENDING:
                        pass  # normal for overlapped I/O
                    elif err == ERROR_OPERATION_ABORTED or self._stop_event.is_set():
                        break
                    else:
                        failure_reason = f"ReadDirectoryChangesW failed (error {err})"
                        logger.warning(f"{failure_reason} for {self.folder_path}")
                        return

                rc = kernel32.WaitForMultipleObjects(2, wait_handles, False, 0xFFFFFFFF)
                if rc != WAIT_OBJECT_0 or self._stop_event.is_set():
                    kernel32.CancelIo(handle)
                    break

                got = wintypes.DWORD(0)
                if not kernel32.GetOverlappedResult(
                    handle, ctypes.byref(overlapped), ctypes.byref(got), False
                ):
                    err = ctypes.GetLastError()
                    if err == ERROR_NOTIFY_ENUM_DIR:
                        # Kernel buffer overflowed: too many changes to enumerate.
                        # Everything must be considered dirty.
                        logger.info(
                            f"Change buffer overflow for {self.folder_path}; forcing full reconcile"
                        )
                        self.callback(self.dataset_id)
                        continue
                    if err == ERROR_OPERATION_ABORTED or self._stop_event.is_set():
                        break
                    failure_reason = f"GetOverlappedResult failed (error {err})"
                    logger.warning(f"{failure_reason} for {self.folder_path}")
                    return

                if got.value == 0:
                    # Zero bytes also signals an overflow -> assume everything changed.
                    self.callback(self.dataset_id)
                    continue

                events = parse_file_notify_information(buffer.raw, got.value)
                if not events:
                    self.callback(self.dataset_id)
                    continue

                paths = [p for _, p in events]
                if logger.isEnabledFor(logging.DEBUG):
                    summary = ", ".join(
                        f"{ACTION_NAMES.get(a, a)}:{p}" for a, p in events[:5]
                    )
                    logger.debug(f"Watcher events for {self.dataset_id}: {summary}")
                self._emit(paths)

        except Exception as e:
            failure_reason = f"Windows watcher loop error: {e}"
            logger.warning(f"{failure_reason} for {self.folder_path}")
        finally:
            self._stop_handle = None
            for h in (change_event, stop_handle):
                if h:
                    try:
                        kernel32.CloseHandle(h)
                    except Exception:
                        pass
            if handle and handle != INVALID_HANDLE_VALUE:
                try:
                    kernel32.CloseHandle(handle)
                except Exception:
                    pass
            self._started_ok.set()
            if failure_reason and not self._stop_event.is_set() and self.on_failure:
                try:
                    self.on_failure(self.dataset_id, failure_reason)
                except Exception as cb_err:
                    logger.debug(f"Watcher failure callback error: {cb_err}")


class PollingDirectoryWatcher:
    """Lightweight cross-platform watcher scanning file mtimes and sizes with interval."""

    def __init__(
        self,
        dataset_id: str,
        folder_path: str,
        callback: Callable[[str], None],
        exclude_patterns: Optional[List[str]] = None,
        poll_interval: float = 4.0,
        on_failure: Optional[Callable[[str, str], None]] = None,
    ):
        self.dataset_id = dataset_id
        self.folder_path = folder_path
        self.callback = callback
        self.exclude_patterns = exclude_patterns or []
        self.poll_interval = poll_interval
        self.on_failure = on_failure
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._known_state: Dict[str, Tuple[float, int]] = {}

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        self._stop_event.clear()
        self._known_state = self._snapshot()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name=f"poll-watch-{self.dataset_id[:8]}",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self):
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=self.poll_interval + 2.0)
        self._thread = None

    def _snapshot(self) -> Dict[str, Tuple[float, int]]:
        """Map every non-excluded file to (mtime, size).

        Size is part of the key because a rewrite that preserves mtime (common
        with tools that restore timestamps) would otherwise go unnoticed.
        """
        state: Dict[str, Tuple[float, int]] = {}
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
                        state[rel_f] = (st.st_mtime, st.st_size)
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
        supervise: bool = True,
    ):
        self.on_change_triggered = on_change_triggered
        self.debounce_seconds = debounce_seconds
        self._watchers: Dict[str, Any] = {}
        self._registrations: Dict[str, Dict[str, Any]] = {}
        self._debounce_timers: Dict[str, threading.Timer] = {}
        self._lock = threading.RLock()
        self._supervise = supervise
        self._supervisor_stop = threading.Event()
        self._supervisor: Optional[threading.Thread] = None

    # ---------------------------------------------------------
    # Change plumbing
    # ---------------------------------------------------------

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
            timer.daemon = True
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

    def has_pending_change(self, dataset_id: str) -> bool:
        with self._lock:
            return dataset_id in self._debounce_timers

    # ---------------------------------------------------------
    # Watcher lifecycle
    # ---------------------------------------------------------

    def _build_watcher(
        self, dataset_id: str, folder_path: str, exclude_patterns: Optional[List[str]], force_polling: bool
    ):
        if sys.platform == "win32" and not force_polling:
            return WindowsDirectoryWatcher(
                dataset_id=dataset_id,
                folder_path=folder_path,
                callback=self._on_raw_change,
                exclude_patterns=exclude_patterns,
                on_failure=self._on_watcher_failed,
            )
        return PollingDirectoryWatcher(
            dataset_id=dataset_id,
            folder_path=folder_path,
            callback=self._on_raw_change,
            exclude_patterns=exclude_patterns,
            on_failure=self._on_watcher_failed,
        )

    def _on_watcher_failed(self, dataset_id: str, reason: str) -> None:
        """Native watcher died: fall back to polling so real-time sync survives."""
        with self._lock:
            reg = self._registrations.get(dataset_id)
            if not reg or reg.get("force_polling"):
                return
            reg["force_polling"] = True
        logger.warning(
            f"Native watcher for dataset {dataset_id} failed ({reason}); "
            "falling back to the polling watcher."
        )
        self.start_watching(
            dataset_id,
            reg["folder_path"],
            reg.get("exclude_patterns"),
            restart=True,
        )

    def is_watching(self, dataset_id: str) -> bool:
        """True when a watcher for this dataset exists and its thread is alive."""
        with self._lock:
            watcher = self._watchers.get(dataset_id)
        if watcher is None:
            return False
        try:
            return bool(watcher.is_alive())
        except Exception:
            return False

    def ensure_watching(
        self,
        dataset_id: str,
        folder_path: str,
        exclude_patterns: Optional[List[str]] = None,
    ) -> bool:
        """Start a watcher only if one is not already running for this dataset.

        Callers that run after every sync must use this instead of
        ``start_watching``: restarting a healthy watcher cancels the debounce
        timer holding a change the user made *during* the sync, which would
        silently drop that change.
        """
        with self._lock:
            reg = self._registrations.get(dataset_id)
            same_target = bool(
                reg
                and os.path.normpath(reg["folder_path"]) == os.path.normpath(folder_path)
                and (reg.get("exclude_patterns") or []) == (exclude_patterns or [])
            )
            if same_target and self.is_watching(dataset_id):
                return True
        return self.start_watching(dataset_id, folder_path, exclude_patterns, restart=True)

    def start_watching(
        self,
        dataset_id: str,
        folder_path: str,
        exclude_patterns: Optional[List[str]] = None,
        restart: bool = True,
    ) -> bool:
        if not os.path.exists(folder_path):
            logger.warning(f"Cannot watch non-existent path: {folder_path}")
            with self._lock:
                # Remember the intent so the supervisor can pick the folder up
                # once it appears (mapped/network drive mounted after boot).
                self._registrations[dataset_id] = {
                    "folder_path": folder_path,
                    "exclude_patterns": exclude_patterns,
                    "force_polling": False,
                }
            self._ensure_supervisor()
            return False

        with self._lock:
            force_polling = bool(
                self._registrations.get(dataset_id, {}).get("force_polling")
            )
            self._registrations[dataset_id] = {
                "folder_path": folder_path,
                "exclude_patterns": exclude_patterns,
                "force_polling": force_polling,
            }
            old = self._watchers.pop(dataset_id, None)

        # Stop the previous watcher outside the lock: stop() joins a thread that
        # may itself be waiting on this very lock inside _on_raw_change.
        if old is not None:
            try:
                old.stop()
            except Exception as e:
                logger.debug(f"Error stopping watcher: {e}")

        watcher = self._build_watcher(dataset_id, folder_path, exclude_patterns, force_polling)
        started = False
        try:
            started = watcher.start() is not False
        except Exception as e:
            logger.warning(f"Failed to start watcher for {folder_path}: {e}")
            started = False

        if not started and sys.platform == "win32" and not force_polling:
            logger.warning(
                f"Native watcher could not start for {folder_path}; using polling watcher instead."
            )
            with self._lock:
                self._registrations[dataset_id]["force_polling"] = True
            watcher = self._build_watcher(dataset_id, folder_path, exclude_patterns, True)
            try:
                started = watcher.start() is not False
            except Exception as e:
                logger.error(f"Polling watcher also failed for {folder_path}: {e}")
                started = False

        if not started:
            return False

        with self._lock:
            self._watchers[dataset_id] = watcher
        self._ensure_supervisor()
        logger.info(f"Started real-time watcher for dataset {dataset_id} at {folder_path}")
        return True

    def stop_watching(self, dataset_id: str):
        with self._lock:
            timer = self._debounce_timers.pop(dataset_id, None)
            watcher = self._watchers.pop(dataset_id, None)
            self._registrations.pop(dataset_id, None)
        if timer:
            timer.cancel()
        if watcher:
            try:
                watcher.stop()
            except Exception as e:
                logger.debug(f"Error stopping watcher: {e}")

    def stop_all(self):
        self._supervisor_stop.set()
        supervisor = self._supervisor
        self._supervisor = None

        with self._lock:
            timers = list(self._debounce_timers.values())
            self._debounce_timers.clear()
            watchers = list(self._watchers.values())
            self._watchers.clear()
            self._registrations.clear()

        for timer in timers:
            timer.cancel()
        for watcher in watchers:
            try:
                watcher.stop()
            except Exception:
                pass
        if supervisor and supervisor.is_alive() and supervisor is not threading.current_thread():
            supervisor.join(timeout=3.0)
        logger.info("All filesystem watchers stopped.")

    # ---------------------------------------------------------
    # Supervision
    # ---------------------------------------------------------

    def _ensure_supervisor(self) -> None:
        if not self._supervise:
            return
        with self._lock:
            if self._supervisor and self._supervisor.is_alive():
                return
            self._supervisor_stop.clear()
            self._supervisor = threading.Thread(
                target=self._supervise_loop, name="r2sync-watch-supervisor", daemon=True
            )
            self._supervisor.start()

    def _supervise_loop(self) -> None:
        while not self._supervisor_stop.is_set():
            self._supervisor_stop.wait(WATCHER_SUPERVISION_INTERVAL_SECONDS)
            if self._supervisor_stop.is_set():
                break
            try:
                self.check_health()
            except Exception as e:
                logger.debug(f"Watcher supervision error: {e}")

    def check_health(self) -> List[str]:
        """Restart any registered watcher whose thread has died. Returns revived ids."""
        with self._lock:
            registrations = dict(self._registrations)

        revived: List[str] = []
        for dataset_id, reg in registrations.items():
            if self.is_watching(dataset_id):
                continue
            folder = reg["folder_path"]
            if not os.path.exists(folder):
                continue
            logger.warning(
                f"Watcher for dataset {dataset_id} is not running; restarting it on {folder}"
            )
            if self.start_watching(dataset_id, folder, reg.get("exclude_patterns"), restart=True):
                revived.append(dataset_id)
                # A dead watcher means changes were missed while it was down.
                self._on_raw_change(dataset_id)
        return revived
