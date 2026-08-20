"""End-to-end synchronization tests driving a real rclone binary.

The "R2" side is an rclone ``alias`` remote pointing at a local directory, so
the whole production path runs unchanged -- watcher, debounce, coalescing
queue, SyncEngine, bisync command line, progress parsing -- with only the
storage backend swapped.

Skipped automatically when no rclone binary is available (set
``R2SYNC_TEST_RCLONE`` to point at one, or put ``rclone`` on PATH).
"""

import hashlib
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from conftest import skip_module_unless

from r2sync.core.db import Database
from r2sync.core.models import R2Credentials, SyncDataset, SyncScheduleMode, SyncStatus
from r2sync.core.sync_engine import SyncEngine

RCLONE_BIN = os.environ.get("R2SYNC_TEST_RCLONE") or shutil.which("rclone")

pytestmark = skip_module_unless(
    bool(RCLONE_BIN), "an rclone binary", "Put rclone on PATH or set R2SYNC_TEST_RCLONE to a binary."
)

SYNC_TIMEOUT = 60


class Harness:
    """A dataset wired to a local stand-in for R2."""

    def __init__(self, root: Path, db: Database, engine: SyncEngine, dataset: SyncDataset,
                 local: Path, remote_data: Path):
        self.root = root
        self.db = db
        self.engine = engine
        self.dataset = dataset
        self.local = local
        self.remote_data = remote_data

    # -- helpers ---------------------------------------------------------
    def sync(self, **kw) -> None:
        self.engine.trigger_sync_async(self.dataset.dataset_id, **kw)
        self.wait_idle()

    def wait_idle(self, timeout: float = SYNC_TIMEOUT) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.engine.is_dataset_syncing(self.dataset.dataset_id) and \
               not self.engine.has_pending_sync(self.dataset.dataset_id):
                # Let a queued follow-up actually start before declaring idle.
                time.sleep(0.2)
                if not self.engine.is_dataset_syncing(self.dataset.dataset_id):
                    return
            time.sleep(0.1)
        raise AssertionError("sync did not settle in time")

    def wait_for_remote(self, rel: str, timeout: float = SYNC_TIMEOUT) -> Path:
        return self._wait_exists(self.remote_data / rel, timeout, "remote")

    def wait_for_local(self, rel: str, timeout: float = SYNC_TIMEOUT) -> Path:
        return self._wait_exists(self.local / rel, timeout, "local")

    def wait_for_remote_gone(self, rel: str, timeout: float = SYNC_TIMEOUT) -> None:
        self._wait_missing(self.remote_data / rel, timeout, "remote")

    @staticmethod
    def _wait_exists(path: Path, timeout: float, side: str) -> Path:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if path.exists():
                return path
            time.sleep(0.2)
        raise AssertionError(f"{side} file never appeared: {path}")

    @staticmethod
    def _wait_missing(path: Path, timeout: float, side: str) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not path.exists():
                return
            time.sleep(0.2)
        raise AssertionError(f"{side} file was never removed: {path}")

    @staticmethod
    def _rel(path: Path, root: Path) -> str:
        """Relative path with forward slashes on every platform.

        ``str(Path.relative_to(...))`` yields backslashes on Windows, so the
        expectations in these tests (written with "/") only ever matched on
        POSIX. The separator is an artifact of the test helper, not of anything
        r2sync produces.
        """
        return path.relative_to(root).as_posix()

    def remote_tree(self):
        return sorted(
            self._rel(p, self.remote_data)
            for p in self.remote_data.rglob("*") if p.is_file()
        )

    def local_tree(self):
        return sorted(
            self._rel(p, self.local)
            for p in self.local.rglob("*")
            if p.is_file() and ".r2sync_trash" not in p.parts
        )


@pytest.fixture
def harness(tmp_path, monkeypatch, request):
    # bisync names its state files after both synced paths flattened into a
    # single filename -- "<path1 with separators as _>..<path2 likewise>".
    # pytest's tmp_path spells out pytest-of-<user>/pytest-N/<test name>, and
    # because path2 here is an alias onto a second local tree under that same
    # root, the name came to 266 characters: past Windows' 255-character limit
    # on a filename, so every test in this module died at "syntax error
    # detected in your path(s)" before transferring a byte. Production stays
    # far short of it -- path2 there is the string "r2:bucket/..." rather than
    # a second absolute path -- so give just the two synced trees a short root
    # of their own and leave everything else under tmp_path.
    synced_root = Path(tempfile.mkdtemp(prefix="r2e2e"))
    request.addfinalizer(lambda: shutil.rmtree(synced_root, ignore_errors=True))

    data_dir = tmp_path / "appdata"
    (data_dir / "rclone").mkdir(parents=True)
    # Must match get_rclone_executable_path(), which appends ".exe" on Windows.
    # Without the extension the copy was simply ignored there and the tests
    # silently fell back to whatever rclone happened to be on PATH.
    rclone_name = "rclone.exe" if sys.platform == "win32" else "rclone"
    shutil.copy(RCLONE_BIN, data_dir / "rclone" / rclone_name)
    os.chmod(data_dir / "rclone" / rclone_name, 0o755)
    monkeypatch.setenv("R2SYNC_DATA_DIR", str(data_dir))

    fake_r2 = synced_root / "fakeR2"
    fake_r2.mkdir()

    # Swap the S3 backend for a local alias; everything else is production code.
    def build_env(self, creds=None):
        env = os.environ.copy()
        env["RCLONE_CONFIG_R2_TYPE"] = "alias"
        env["RCLONE_CONFIG_R2_REMOTE"] = str(fake_r2)
        return env

    monkeypatch.setattr("r2sync.core.rclone_engine.RcloneEngine._build_env", build_env)
    monkeypatch.setattr(
        "r2sync.core.sync_engine.get_r2_credentials",
        lambda: R2Credentials(account_id="a", access_key_id="k",
                              secret_access_key="s", default_bucket="bkt"),
    )
    monkeypatch.setattr("r2sync.core.sync_engine.check_internet_connection", lambda: True)

    local = synced_root / "Mes Documents Été"
    local.mkdir()

    db = Database(db_path=data_dir / "e2e.sqlite")
    dataset = SyncDataset(
        dataset_id="ds-e2e",
        name="E2E Folder",
        bucket_name="bkt",
        remote_prefix="r2sync/v1/datasets/ds-e2e",
        local_path=str(local),
        schedule_mode=SyncScheduleMode.REALTIME.value,
        status=SyncStatus.WAITING.value,
    )
    db.create_sync_dataset(dataset)

    # Unlike S3, the local backend has no implicit prefixes, so the remote
    # "directory" has to exist before bisync will list it.
    remote_data = fake_r2 / "bkt" / "r2sync/v1/datasets/ds-e2e" / "data"
    remote_data.mkdir(parents=True)

    engine = SyncEngine(db=db)
    engine.watcher_manager.debounce_seconds = 0.4

    h = Harness(synced_root, db, engine, dataset, local, remote_data)
    yield h

    engine.stop_all_watchers()
    db.close()

    # A failed assertion here reads "assert [] == [...]" and says nothing about
    # why rclone declined to transfer anything. The bisync log holds the exact
    # command line and rclone's own diagnostics, and is otherwise thrown away
    # with tmp_path -- which left a Windows-only failure undebuggable from a CI
    # log. Dump it on failure only, so passing runs stay quiet.
    if getattr(request.node, "rep_call", None) is not None and request.node.rep_call.failed:
        for log in sorted((data_dir / "logs").glob("*.log")):
            print(f"\n----- {log.name} -----")
            print(log.read_text(encoding="utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# Local -> R2
# ---------------------------------------------------------------------------

def test_initial_sync_uploads_existing_files(harness):
    (harness.local / "seed.txt").write_text("hello", encoding="utf-8")
    (harness.local / "sub folder").mkdir()
    (harness.local / "sub folder" / "résumé.txt").write_text("bonjour", encoding="utf-8")

    harness.sync(resync_mode="path1", force_resync=True)

    assert harness.remote_tree() == ["seed.txt", "sub folder/résumé.txt"]


def test_creating_a_file_triggers_a_sync_through_the_watcher(harness):
    """The headline bug: a newly created file must actually reach R2."""
    (harness.local / "seed.txt").write_text("hello", encoding="utf-8")
    harness.sync(resync_mode="path1", force_resync=True)

    assert harness.engine.watcher_manager.is_watching("ds-e2e"), \
        "the watcher must be live after the first sync"

    (harness.local / "brand new file.txt").write_text("created by the user", encoding="utf-8")

    harness.wait_for_remote("brand new file.txt")
    assert (harness.remote_data / "brand new file.txt").read_text(encoding="utf-8") == "created by the user"


def test_modify_delete_and_rename_all_propagate(harness):
    # Several files, so removing one is an ordinary deletion rather than
    # "the whole folder is now empty".
    for i in range(4):
        (harness.local / f"keep_{i}.txt").write_text(f"keep {i}", encoding="utf-8")
    target = harness.local / "notes.txt"
    target.write_text("v1", encoding="utf-8")
    harness.sync(resync_mode="path1", force_resync=True)
    assert "notes.txt" in harness.remote_tree()

    # modify
    target.write_text("v2 with more content", encoding="utf-8")
    deadline = time.time() + SYNC_TIMEOUT
    while time.time() < deadline:
        if (harness.remote_data / "notes.txt").read_text(encoding="utf-8") == "v2 with more content":
            break
        time.sleep(0.2)
    assert (harness.remote_data / "notes.txt").read_text(encoding="utf-8") == "v2 with more content"

    # rename
    target.rename(harness.local / "renamed notes.txt")
    harness.wait_for_remote("renamed notes.txt")
    harness.wait_for_remote_gone("notes.txt")

    # delete
    (harness.local / "renamed notes.txt").unlink()
    harness.wait_for_remote_gone("renamed notes.txt")
    assert sorted(harness.remote_tree()) == [f"keep_{i}.txt" for i in range(4)]


def test_renaming_the_only_file_still_propagates(harness):
    """A one-file folder trips bisync's percentage delete guard.

    r2sync's threshold is a file count, so it has to be converted before it is
    handed to bisync; passing the raw count meant "abort above 50%" and a rename
    in a small folder never reached R2.
    """
    (harness.local / "solo.txt").write_text("only file", encoding="utf-8")
    harness.sync(resync_mode="path1", force_resync=True)

    (harness.local / "solo.txt").rename(harness.local / "solo renamed.txt")
    harness.wait_for_remote("solo renamed.txt")
    harness.wait_for_remote_gone("solo.txt")


def test_emptying_the_whole_folder_is_held_for_confirmation(harness):
    """An empty local folder is indistinguishable from an unmounted drive.

    rclone refuses to sync from an empty source; r2sync surfaces that as
    "needs attention" instead of silently re-baselining, which would either
    resurrect the deletions or propagate a bogus wipe to the other computers.
    """
    for i in range(3):
        (harness.local / f"f{i}.txt").write_text(f"content {i}", encoding="utf-8")
    harness.sync(resync_mode="path1", force_resync=True)
    assert len(harness.remote_tree()) == 3

    for i in range(3):
        (harness.local / f"f{i}.txt").unlink()
    harness.sync()

    stored = harness.db.get_sync_dataset("ds-e2e")
    assert stored.status == SyncStatus.NEEDS_ATTENTION.value
    assert "empty" in (stored.last_error or "").lower()
    # Crucially, the remote copies are still intact and recoverable.
    assert len(harness.remote_tree()) == 3


def test_rapid_successive_changes_all_end_up_synced(harness):
    (harness.local / "seed.txt").write_text("seed", encoding="utf-8")
    harness.sync(resync_mode="path1", force_resync=True)

    for i in range(12):
        (harness.local / f"burst_{i:02d}.txt").write_text(f"content {i}", encoding="utf-8")
        time.sleep(0.05)

    deadline = time.time() + SYNC_TIMEOUT
    expected = {f"burst_{i:02d}.txt" for i in range(12)}
    while time.time() < deadline:
        if expected.issubset(set(harness.remote_tree())):
            break
        time.sleep(0.3)

    missing = expected - set(harness.remote_tree())
    assert not missing, f"changes lost during a burst: {sorted(missing)}"


def test_a_change_made_during_a_sync_is_not_lost(harness):
    """Reproduces the exact drop: edit while a sync is already in flight."""
    for i in range(40):
        (harness.local / f"bulk_{i:03d}.bin").write_bytes(os.urandom(64 * 1024))
    harness.sync(resync_mode="path1", force_resync=True)

    # Start a sync and drop a new file in while it is still running.
    started = threading.Event()
    original = harness.engine.rclone_engine.run_bisync

    def slow_bisync(*a, **kw):
        started.set()
        time.sleep(1.5)
        return original(*a, **kw)

    harness.engine.rclone_engine.run_bisync = slow_bisync
    harness.engine.trigger_sync_async("ds-e2e")
    assert started.wait(timeout=10)

    (harness.local / "written during sync.txt").write_text("must not be lost", encoding="utf-8")
    time.sleep(0.5)
    harness.engine.rclone_engine.run_bisync = original

    harness.wait_for_remote("written during sync.txt")


def test_unicode_and_spaced_paths_round_trip(harness):
    names = [
        "café ☕ notes.txt",
        "Ünïcödé/深い/ディレクトリ.txt",
        "with spaces and (parens).md",
        "emoji 🚀 file.txt",
    ]
    for name in names:
        path = harness.local / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"content of {name}", encoding="utf-8")

    harness.sync(resync_mode="path1", force_resync=True)

    assert sorted(harness.remote_tree()) == sorted(names)
    for name in names:
        assert (harness.remote_data / name).read_text(encoding="utf-8") == f"content of {name}"


def test_second_sync_is_incremental_not_a_resync(harness):
    """initial_sync_done must be persisted so bisync stops re-baselining."""
    (harness.local / "a.txt").write_text("a", encoding="utf-8")
    harness.sync(resync_mode="path1", force_resync=True)

    stored = harness.db.get_sync_dataset("ds-e2e")
    assert stored.initial_sync_done is True, "initial_sync_done was not persisted"

    seen = {}
    original = harness.engine.rclone_engine.run_bisync

    def capture(dataset, **kw):
        seen["force_resync"] = kw.get("force_resync")
        seen["initial_sync_done"] = dataset.initial_sync_done
        return original(dataset, **kw)

    harness.engine.rclone_engine.run_bisync = capture
    (harness.local / "b.txt").write_text("b", encoding="utf-8")
    harness.sync()

    assert seen["initial_sync_done"] is True
    assert not seen["force_resync"]


# ---------------------------------------------------------------------------
# R2 -> local (the download path)
# ---------------------------------------------------------------------------

def test_remote_changes_download_to_the_local_folder(harness):
    (harness.local / "local.txt").write_text("from this pc", encoding="utf-8")
    harness.sync(resync_mode="path1", force_resync=True)

    # Another computer adds files to the shared dataset.
    (harness.remote_data / "from other pc.txt").write_text("hello from the laptop", encoding="utf-8")
    (harness.remote_data / "shared dir").mkdir()
    (harness.remote_data / "shared dir" / "spreadsheet.csv").write_text("a,b,c\n1,2,3\n", encoding="utf-8")

    harness.sync()

    assert (harness.local / "from other pc.txt").read_text(encoding="utf-8") == "hello from the laptop"
    assert (harness.local / "shared dir" / "spreadsheet.csv").exists()


def test_large_multi_file_download_is_byte_exact(harness):
    harness.sync(resync_mode="path1", force_resync=True)

    expected = {}
    for i in range(6):
        name = f"large_{i}.bin"
        payload = os.urandom(3 * 1024 * 1024)
        (harness.remote_data / name).write_bytes(payload)
        expected[name] = hashlib.sha256(payload).hexdigest()

    harness.sync()

    for name, digest in expected.items():
        local_file = harness.local / name
        assert local_file.exists(), f"{name} was not downloaded"
        assert hashlib.sha256(local_file.read_bytes()).hexdigest() == digest


def test_download_progress_reports_direction_and_totals(harness):
    # Throttled so transfers stay in flight across several 1s stats ticks;
    # otherwise rclone's "transferring" list is empty every time it is sampled.
    harness.dataset.bandwidth_limit = "2M"
    harness.db.update_sync_dataset(harness.dataset)
    harness.sync(resync_mode="path1", force_resync=True)

    for i in range(4):
        (harness.remote_data / f"payload_{i}.bin").write_bytes(os.urandom(2 * 1024 * 1024))

    events = []
    harness.engine.add_progress_listener(events.append)
    harness.sync()

    assert events, "no progress events were emitted for a download"
    transferring = [e for e in events if e.bytes_transferred > 0]
    assert transferring, "progress never reported transferred bytes"
    assert any(e.direction == "download" for e in transferring), \
        "downloads were not identified as downloads"
    assert all(e.totals_final for e in transferring), \
        "--check-first should make totals final before any byte moves"
    assert events[-1].phase == "finalizing"


def test_interrupted_download_resumes_without_corrupting_files(harness):
    """A killed transfer must not leave a half-written file in place."""
    harness.sync(resync_mode="path1", force_resync=True)

    payloads = {}
    for i in range(8):
        name = f"big_{i}.bin"
        data = os.urandom(4 * 1024 * 1024)
        (harness.remote_data / name).write_bytes(data)
        payloads[name] = hashlib.sha256(data).hexdigest()

    # Interrupt mid-flight.
    harness.engine.trigger_sync_async("ds-e2e")
    time.sleep(0.6)
    harness.engine.cancel_sync("ds-e2e")
    harness.wait_idle()

    # Whatever landed must be either complete-and-correct or absent; no
    # truncated file may masquerade as a finished download.
    for name, digest in payloads.items():
        p = harness.local / name
        if p.exists():
            assert hashlib.sha256(p.read_bytes()).hexdigest() == digest, \
                f"{name} was left corrupted by the interruption"

    # And a follow-up run completes the job.
    harness.sync()
    for name, digest in payloads.items():
        p = harness.local / name
        assert p.exists(), f"{name} never completed after resume"
        assert hashlib.sha256(p.read_bytes()).hexdigest() == digest

    leftovers = [p.name for p in harness.local.rglob("*.partial")]
    assert not leftovers, f"partial files left behind: {leftovers}"


def test_bidirectional_changes_in_one_pass(harness):
    (harness.local / "from_local.txt").write_text("local side", encoding="utf-8")
    harness.sync(resync_mode="path1", force_resync=True)

    (harness.local / "another_local.txt").write_text("local 2", encoding="utf-8")
    (harness.remote_data / "from_remote.txt").write_text("remote side", encoding="utf-8")

    harness.sync()

    assert (harness.remote_data / "another_local.txt").exists()
    assert (harness.local / "from_remote.txt").exists()


# ---------------------------------------------------------------------------
# Download strategy (verified against the real rclone binary)
# ---------------------------------------------------------------------------

def _run_rclone(args, cwd=None):
    import subprocess

    return subprocess.run(
        [RCLONE_BIN, *args], capture_output=True, text=True, timeout=180, cwd=cwd
    )


@pytest.mark.parametrize("size_mb", [48])
def test_tuning_switches_downloads_from_one_stream_to_many(tmp_path, size_mb):
    """The core download fix, checked against rclone's own behaviour.

    rclone only splits a download across streams above ``--multi-thread-cutoff``
    (256 MiB by default), so before this change an ordinary large file came down
    over a single connection no matter which speed profile was selected.
    """
    from r2sync.core.speed_profiles import build_transfer_flags, get_speed_profile

    src = tmp_path / "src"
    src.mkdir()
    (src / "big.bin").write_bytes(os.urandom(size_mb * 1024 * 1024))

    default_dst = tmp_path / "dst_default"
    tuned_dst = tmp_path / "dst_tuned"

    default_run = _run_rclone(["copy", str(src), str(default_dst), "-vv"])
    assert default_run.returncode == 0
    assert "Starting multi-thread copy" not in default_run.stderr, (
        "rclone's defaults unexpectedly used multi-thread; the baseline for this "
        "test no longer holds"
    )

    flags = build_transfer_flags(get_speed_profile("turbo"), include_s3=False)
    tuned_run = _run_rclone(["copy", str(src), str(tuned_dst), "-vv", *flags])
    assert tuned_run.returncode == 0
    assert "Starting multi-thread copy" in tuned_run.stderr, (
        "the tuned profile did not engage parallel download streams"
    )

    # And the file is still byte-exact.
    assert (tuned_dst / "big.bin").read_bytes() == (src / "big.bin").read_bytes()


def test_profile_flags_are_all_accepted_by_rclone(tmp_path):
    """Guards against a typo'd or removed flag silently breaking every transfer."""
    from r2sync.core.speed_profiles import build_transfer_flags, list_speed_profiles

    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text("hi", encoding="utf-8")

    for prof in list_speed_profiles():
        dst = tmp_path / f"dst_{prof.id}"
        res = _run_rclone([
            "copy", str(src), str(dst), "--check-first",
            *build_transfer_flags(prof, include_s3=True),
        ])
        assert res.returncode == 0, f"profile {prof.id} produced an invalid command: {res.stderr[-500:]}"
        assert (dst / "f.txt").read_text(encoding="utf-8") == "hi"
