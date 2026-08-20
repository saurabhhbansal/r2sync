"""Regression tests for upload/download tuning of the rclone command lines.

The download path used to inherit rclone's defaults entirely: any file under
256 MiB came down over a single HTTP stream while uploads got up to 32 parallel
S3 parts.
"""

import os
from unittest.mock import patch

import pytest

from r2sync.core.models import BackupJob, BackupMode, BackupRun, SyncDataset
from r2sync.core.rclone_engine import (
    RcloneEngine,
    TransferPhaseTracker,
    _transfer_direction,
    compute_max_delete_percent,
)
from r2sync.core.speed_profiles import (
    SPEED_PROFILES,
    build_transfer_flags,
    get_speed_profile,
    list_speed_profiles,
)


def _flag_value(args, flag):
    return args[args.index(flag) + 1]


def _capture_args(run_callable):
    """Run a callable with Popen stubbed out and return the argv rclone got."""
    captured = {}

    class FakeProc:
        stdout = iter(())

        def wait(self):
            return 0

        def poll(self):
            return 0

    def fake_popen(args, **kwargs):
        captured["args"] = args
        return FakeProc()

    with patch("subprocess.Popen", side_effect=fake_popen), \
         patch("r2sync.core.rclone_engine.RcloneBinaryManager.get_executable_path",
               return_value="/usr/bin/rclone"):
        run_callable()
    return captured["args"]


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def test_every_profile_tunes_both_directions():
    for prof in list_speed_profiles():
        assert prof.multi_thread_streams >= 2, prof.id
        assert prof.multi_thread_cutoff, prof.id
        assert prof.multi_thread_chunk_size, prof.id
        assert prof.upload_concurrency >= 1, prof.id


def test_download_cutoff_is_below_rclones_256m_default():
    """rclone's default cutoff means typical files never go multi-stream."""
    for prof in list_speed_profiles():
        cutoff_mb = int(prof.multi_thread_cutoff.rstrip("M"))
        assert cutoff_mb <= 128, f"{prof.id} would leave most files single-stream"


def test_faster_profiles_do_not_download_slower_than_eco():
    order = ["eco", "balanced", "fast", "turbo", "extreme"]
    streams = [SPEED_PROFILES[p].multi_thread_streams for p in order]
    assert streams == sorted(streams)


def test_download_streams_are_capped_to_available_cpus():
    """transfers x streams must not explode into hundreds of range requests."""
    prof = SPEED_PROFILES["extreme"]
    effective = prof.effective_multi_thread_streams
    assert 2 <= effective <= prof.multi_thread_streams
    assert effective <= (os.cpu_count() or 4) * 2


def test_build_transfer_flags_covers_both_directions():
    flags = build_transfer_flags(get_speed_profile("turbo"))
    for flag in (
        "--multi-thread-streams",
        "--multi-thread-cutoff",
        "--multi-thread-chunk-size",
        "--s3-upload-concurrency",
        "--s3-chunk-size",
        "--transfers",
        "--checkers",
        "--buffer-size",
    ):
        assert flag in flags, flag


# ---------------------------------------------------------------------------
# Command lines
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    return RcloneEngine()


def test_bisync_command_tunes_downloads(engine, tmp_path):
    dataset = SyncDataset(
        dataset_id="ds1", name="D", bucket_name="bkt",
        remote_prefix="r2sync/v1/datasets/ds1", local_path=str(tmp_path),
        initial_sync_done=True,
    )
    args = _capture_args(lambda: engine.run_bisync(dataset=dataset, speed_profile="turbo"))

    assert "--multi-thread-streams" in args
    assert "--multi-thread-cutoff" in args
    assert "--multi-thread-chunk-size" in args
    assert int(_flag_value(args, "--multi-thread-streams")) >= 2


def test_backup_command_tunes_downloads_too(engine, tmp_path):
    job = BackupJob(name="J", source_path=str(tmp_path), bucket_name="bkt",
                    backup_mode=BackupMode.SYNC.value, id=1)
    run = BackupRun(job_id=1, job_name="J")
    args = _capture_args(
        lambda: engine.run_backup(job=job, run_record=run, speed_profile="turbo")
    )

    # Backup is upload-only today, but a restore reuses the same engine, so the
    # two paths must not drift apart again.
    assert "--multi-thread-streams" in args
    assert "--s3-upload-concurrency" in args


def test_both_commands_check_first_so_totals_are_final(engine, tmp_path):
    dataset = SyncDataset(dataset_id="ds1", name="D", bucket_name="bkt",
                          local_path=str(tmp_path), initial_sync_done=True)
    job = BackupJob(name="J", source_path=str(tmp_path), bucket_name="bkt", id=1)

    bisync_args = _capture_args(lambda: engine.run_bisync(dataset=dataset))
    backup_args = _capture_args(
        lambda: engine.run_backup(job=job, run_record=BackupRun(job_id=1, job_name="J"))
    )

    assert "--check-first" in bisync_args
    assert "--check-first" in backup_args


def test_downloads_stay_atomic_for_safe_resume(engine, tmp_path):
    """--inplace would let an interrupted download corrupt the local file.

    Without it rclone writes to a .partial file and renames on success, so an
    interrupted transfer leaves the previous version intact and only the
    unfinished file is redone.
    """
    dataset = SyncDataset(dataset_id="ds1", name="D", bucket_name="bkt",
                          local_path=str(tmp_path), initial_sync_done=True)
    args = _capture_args(lambda: engine.run_bisync(dataset=dataset))

    assert "--inplace" not in args
    assert int(_flag_value(args, "--low-level-retries")) >= 10
    assert int(_flag_value(args, "--retries")) >= 3


def test_completed_sync_uses_incremental_bisync_not_resync(engine, tmp_path):
    """A dataset that finished its first sync must stop re-running --resync."""
    dataset = SyncDataset(dataset_id="ds1", name="D", bucket_name="bkt",
                          local_path=str(tmp_path), initial_sync_done=True)
    args = _capture_args(lambda: engine.run_bisync(dataset=dataset))

    assert "--resync" not in args
    assert "--recover" in args and "--resilient" in args


def test_first_sync_still_resyncs(engine, tmp_path):
    dataset = SyncDataset(dataset_id="ds1", name="D", bucket_name="bkt",
                          local_path=str(tmp_path), initial_sync_done=False)
    args = _capture_args(lambda: engine.run_bisync(dataset=dataset))
    assert "--resync" in args


# ---------------------------------------------------------------------------
# Progress phases
# ---------------------------------------------------------------------------

def test_totals_are_not_final_while_rclone_is_still_scanning():
    tracker = TransferPhaseTracker()
    phase, final, total_bytes, total_files = tracker.observe(
        {"bytes": 0, "transfers": 0, "totalBytes": 1_000, "totalTransfers": 3, "transferring": []}
    )
    assert phase == TransferPhaseTracker.PHASE_SCANNING
    assert final is False


def test_totals_become_final_once_transfers_start():
    tracker = TransferPhaseTracker()
    tracker.observe({"bytes": 0, "transfers": 0, "totalBytes": 100, "totalTransfers": 1})
    phase, final, _, _ = tracker.observe(
        {"bytes": 512, "transfers": 1, "totalBytes": 4_000, "totalTransfers": 9}
    )
    assert phase == TransferPhaseTracker.PHASE_TRANSFERRING
    assert final is True


def test_totals_never_appear_to_shrink():
    """rclone's totals dip as in-flight items settle; the UI must not go backwards."""
    tracker = TransferPhaseTracker()
    tracker.observe({"bytes": 10, "transfers": 1, "totalBytes": 5_000, "totalTransfers": 10})
    _, _, total_bytes, total_files = tracker.observe(
        {"bytes": 20, "transfers": 1, "totalBytes": 4_800, "totalTransfers": 9}
    )
    assert total_bytes == 5_000
    assert total_files == 10


def test_transfer_direction_is_derived_from_the_local_side():
    """rclone labels a remote Fs by backend description, not by remote name."""
    local = "/home/u/Docs"
    remote = "S3 bucket my-bucket path r2sync/v1/datasets/ds/data"

    assert _transfer_direction([{"srcFs": remote, "dstFs": local}], local) == "download"
    assert _transfer_direction([{"srcFs": local, "dstFs": remote}], local) == "upload"
    assert _transfer_direction(
        [{"srcFs": remote, "dstFs": local}, {"srcFs": local, "dstFs": remote}], local
    ) == "sync"
    assert _transfer_direction([], local) == "sync"


def test_transfer_direction_tolerates_path_spelling_differences():
    from r2sync.core.rclone_engine import _is_same_fs

    assert _is_same_fs("/home/u/Docs/", "/home/u/Docs")
    assert _is_same_fs("/home/u/./Docs", "/home/u/Docs")
    assert not _is_same_fs("", "/home/u/Docs")
    assert not _is_same_fs("/home/u/Other", "/home/u/Docs")


def test_transfer_direction_survives_rclones_windows_path_spelling():
    """The Windows leg reported every download as "sync" until this held.

    rclone's local backend renders an absolute Windows path with the
    extended-length prefix and forward slashes, while the dataset holds the
    path the folder picker produced. Comparing them literally matched neither
    side of a transfer. Asserted on every platform, not just Windows, because
    the spelling is rclone's and arrives the same way wherever it is parsed.
    """
    from r2sync.core.rclone_engine import _is_same_fs

    local = r"C:\Users\me\Docs"
    assert _is_same_fs("//?/C:/Users/me/Docs", local)
    assert _is_same_fs(r"\\?\C:\Users\me\Docs", local)
    assert not _is_same_fs("//?/C:/Users/me/Other", local)

    unc = r"\\server\share\Docs"
    assert _is_same_fs("//?/UNC/server/share/Docs", unc)

    remote = "S3 bucket my-bucket path r2sync/v1/datasets/ds/data"
    assert _transfer_direction([{"srcFs": remote, "dstFs": "//?/C:/Users/me/Docs"}],
                               local) == "download"
    assert _transfer_direction([{"srcFs": "//?/C:/Users/me/Docs", "dstFs": remote}],
                               local) == "upload"


# ---------------------------------------------------------------------------
# Mass deletion protection
# ---------------------------------------------------------------------------

def test_max_delete_is_translated_from_a_file_count_to_a_percentage():
    """bisync's --max-delete is a percentage, unlike rclone sync's count."""
    # 50 deletions out of 1000 tracked files is 5%.
    assert compute_max_delete_percent(50, 1000) == 5
    assert compute_max_delete_percent(100, 1000) == 10


def test_small_datasets_are_not_paralysed_by_the_delete_guard():
    """Renaming the only file in a folder is 1-of-1 deletions, i.e. 100%.

    Passing the raw count through meant "abort above 50%", so that rename
    aborted the run and the dataset stalled in 'needs attention'.
    """
    assert compute_max_delete_percent(50, 1) == 100
    assert compute_max_delete_percent(50, 3) == 100


def test_delete_guard_still_protects_large_datasets():
    # Wiping a big folder must still be well over the ceiling.
    pct = compute_max_delete_percent(50, 10_000)
    assert pct == 1
    assert pct < 100


def test_delete_guard_falls_back_to_a_percentage_without_a_baseline():
    from r2sync.config import SYNC_DEFAULT_MAX_DELETE_PERCENT

    assert compute_max_delete_percent(50, 0) == SYNC_DEFAULT_MAX_DELETE_PERCENT


def test_delete_guard_percentage_stays_in_range():
    for total in (1, 2, 7, 999, 1_000_000):
        for threshold in (0, 1, 50, 5000):
            pct = compute_max_delete_percent(threshold, total)
            assert 1 <= pct <= 100


def test_bisync_passes_the_percentage_form_of_the_threshold(engine, tmp_path):
    dataset = SyncDataset(
        dataset_id="ds1", name="D", bucket_name="bkt", local_path=str(tmp_path),
        initial_sync_done=True, max_delete_threshold=50, total_files=1000,
    )
    args = _capture_args(lambda: engine.run_bisync(dataset=dataset))
    assert _flag_value(args, "--max-delete") == "5"


def test_force_retry_keeps_the_deletion_ceiling(engine, tmp_path):
    """--force may waive the 'all changed' guard but never --max-delete."""
    dataset = SyncDataset(
        dataset_id="ds1", name="D", bucket_name="bkt", local_path=str(tmp_path),
        initial_sync_done=True, max_delete_threshold=50, total_files=1000,
    )
    args = _capture_args(lambda: engine.run_bisync(dataset=dataset, force=True))
    assert "--force" in args
    assert _flag_value(args, "--max-delete") == "5"
