"""Cheap dataset size estimation used to give sync progress a real denominator.

rclone's ``totalBytes`` statistic is *"bytes discovered so far"* -- it grows
while rclone is still walking the tree, so showing it as the denominator of a
progress readout is misleading. This module produces an independent estimate of
how much data the dataset holds so the UI can distinguish

    Transferred / Total      (denominator is known and final)
    Scanned / Discovered     (rclone is still enumerating)

The scan is deliberately cheap: a local ``os.scandir`` walk plus a single
``rclone size --json --fast-list`` call against the remote prefix. It always
runs *alongside* the transfer, never in front of it, so it cannot delay the
first byte.
"""

import json
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, List, Optional

from r2sync.core.models import R2Credentials
from r2sync.core.watcher import is_path_excluded

logger = logging.getLogger(__name__)

# A remote listing that takes longer than this is not worth waiting for; the UI
# falls back to the "Scanned / Discovered" presentation instead.
REMOTE_SCAN_TIMEOUT_SECONDS = 25


@dataclass
class DatasetEstimate:
    """Best-effort totals for a dataset, from both sides of the sync."""

    local_files: int = 0
    local_bytes: int = 0
    remote_files: int = 0
    remote_bytes: int = 0
    local_complete: bool = False
    remote_complete: bool = False

    @property
    def complete(self) -> bool:
        return self.local_complete and self.remote_complete

    @property
    def union_files(self) -> int:
        """Upper bound on the number of distinct files across both sides."""
        return max(self.local_files, self.remote_files)

    @property
    def union_bytes(self) -> int:
        return max(self.local_bytes, self.remote_bytes)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["union_files"] = self.union_files
        data["union_bytes"] = self.union_bytes
        data["complete"] = self.complete
        return data


def scan_local_tree(
    local_path: str,
    exclude_patterns: Optional[List[str]] = None,
    cancel: Optional[threading.Event] = None,
) -> tuple[int, int, bool]:
    """Walk a local tree with os.scandir and return (files, bytes, completed)."""
    exclude_patterns = exclude_patterns or []
    total_files = 0
    total_bytes = 0

    if not os.path.isdir(local_path):
        return 0, 0, False

    stack = [local_path]
    while stack:
        if cancel is not None and cancel.is_set():
            return total_files, total_bytes, False
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        rel = os.path.relpath(entry.path, local_path)
                        if is_path_excluded(rel, exclude_patterns):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total_files += 1
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError as e:
            logger.debug(f"Pre-scan could not read {current}: {e}")
            continue

    return total_files, total_bytes, True


def scan_remote_prefix(
    rclone_engine,
    bucket_name: str,
    remote_prefix: str,
    creds: Optional[R2Credentials] = None,
    timeout: int = REMOTE_SCAN_TIMEOUT_SECONDS,
) -> tuple[int, int, bool]:
    """Return (files, bytes, completed) for a remote prefix via ``rclone size``."""
    from r2sync.core.rclone_engine import RcloneBinaryManager

    try:
        exe_path = RcloneBinaryManager.get_executable_path()
    except Exception as e:
        logger.debug(f"Pre-scan skipped, rclone unavailable: {e}")
        return 0, 0, False

    env = rclone_engine._build_env(creds)
    flags = 0x08000000 if sys.platform == "win32" else 0
    remote = f"r2:{bucket_name}/{remote_prefix.strip('/')}"

    try:
        res = subprocess.run(
            [
                str(exe_path), "size", remote, "--json",
                "--fast-list",
                "--retries", "1",
                "--low-level-retries", "2",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
        )
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            return int(data.get("count", 0)), int(data.get("bytes", 0)), True
    except subprocess.TimeoutExpired:
        logger.info(f"Remote pre-scan of {remote} timed out after {timeout}s")
    except Exception as e:
        logger.debug(f"Remote pre-scan failed for {remote}: {e}")

    return 0, 0, False


def estimate_dataset(
    rclone_engine,
    dataset,
    creds: Optional[R2Credentials] = None,
    cancel: Optional[threading.Event] = None,
) -> DatasetEstimate:
    """Estimate both sides of a dataset. Safe to call on a background thread."""
    est = DatasetEstimate()

    lf, lb, ok = scan_local_tree(dataset.local_path, dataset.exclude_patterns, cancel)
    est.local_files, est.local_bytes, est.local_complete = lf, lb, ok

    if cancel is not None and cancel.is_set():
        return est

    rf, rb, rok = scan_remote_prefix(
        rclone_engine,
        dataset.bucket_name,
        f"{dataset.remote_prefix.strip('/')}/data",
        creds,
    )
    est.remote_files, est.remote_bytes, est.remote_complete = rf, rb, rok
    return est


class BackgroundEstimator:
    """Runs :func:`estimate_dataset` off the critical path and publishes the result."""

    def __init__(self, rclone_engine, dataset, creds=None,
                 on_ready: Optional[Callable[[DatasetEstimate], None]] = None):
        self.rclone_engine = rclone_engine
        self.dataset = dataset
        self.creds = creds
        self.on_ready = on_ready
        self.estimate: Optional[DatasetEstimate] = None
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "BackgroundEstimator":
        self._thread = threading.Thread(
            target=self._run, name=f"prescan-{self.dataset.dataset_id[:8]}", daemon=True
        )
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            est = estimate_dataset(self.rclone_engine, self.dataset, self.creds, self._cancel)
        except Exception as e:
            logger.debug(f"Pre-scan failed for {self.dataset.dataset_id}: {e}")
            return
        if self._cancel.is_set():
            return
        self.estimate = est
        if self.on_ready:
            try:
                self.on_ready(est)
            except Exception as e:
                logger.debug(f"Pre-scan callback error: {e}")

    def stop(self) -> None:
        self._cancel.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
