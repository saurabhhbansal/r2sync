"""Regression tests for how r2sync reads rclone bisync's output.

Every string asserted here was taken from a real rclone v1.68.2 bisync run, not
from the docs. The distinction that matters throughout is between rclone's
*generic* recovery footer, which it prints after every single critical error:

    Bisync critical error: <the actual reason>
    Bisync aborted. Must run --resync to recover.

and its *specific* diagnostics ("empty prior Path1 listing", "cannot find prior
Path1 or Path2 listings", ...) which genuinely mean the saved baseline is
unusable. Matching the footer treated a permission error, a cancelled run and a
dropped connection alike as "the baseline is stale", hid the real cause behind
a fixed message, and kicked off a full re-baseline of the dataset each time.
"""

import io
from unittest.mock import patch

import pytest

from r2sync.core.models import SyncDataset
from r2sync.core.rclone_engine import (
    _EMPTY_SOURCE_MARKERS,
    _STALE_BASELINE_MARKERS,
    RcloneEngine,
)


def _run_bisync(dataset, stdout_lines, exit_code=1, **kwargs):
    """Drive run_bisync against a scripted rclone stdout and return its result."""

    class FakeProc:
        def __init__(self):
            self.stdout = io.StringIO("".join(line + "\n" for line in stdout_lines))

        def wait(self):
            return exit_code

        def poll(self):
            return exit_code

    with patch("subprocess.Popen", return_value=FakeProc()), \
         patch("r2sync.core.rclone_engine.RcloneBinaryManager.get_executable_path",
               return_value="/usr/bin/rclone"):
        return RcloneEngine().run_bisync(dataset=dataset, **kwargs)


@pytest.fixture
def dataset(tmp_path):
    return SyncDataset(
        dataset_id="ds-diag", name="Diag", bucket_name="bkt",
        remote_prefix="r2sync/v1/datasets/ds-diag", local_path=str(tmp_path),
        initial_sync_done=True,
    )


# ---------------------------------------------------------------------------
# The generic footer must not be read as a diagnosis
# ---------------------------------------------------------------------------

GENERIC_FOOTERS = [
    "Bisync aborted. Must run --resync to recover.",
    "Bisync interrupted. Must run --resync to recover.",
    "Bisync aborted. Please try again.",
]


@pytest.mark.parametrize("footer", GENERIC_FOOTERS)
def test_no_marker_matches_a_generic_footer(footer):
    """Guards the marker tables directly, independent of how they are consumed."""
    low = footer.lower()
    for marker in _STALE_BASELINE_MARKERS + _EMPTY_SOURCE_MARKERS:
        assert marker not in low, f"{marker!r} matches rclone's generic footer"


@pytest.mark.parametrize("footer", GENERIC_FOOTERS)
def test_generic_recovery_footer_is_not_a_stale_baseline(dataset, footer):
    result = _run_bisync(dataset, [
        'Bisync critical error: failed to create file: permission denied',
        footer,
    ])

    assert not result["needs_resync"], (
        "rclone prints this footer after every critical error, so treating it "
        "as a diagnosis re-baselines the dataset for unrelated failures"
    )


def test_the_real_reason_reaches_the_user(dataset):
    result = _run_bisync(dataset, [
        'Bisync critical error: failed to create file: permission denied',
        "Bisync aborted. Must run --resync to recover.",
    ])

    assert result["critical_error"] == "failed to create file: permission denied"
    assert "permission denied" in result["error_message"]
    assert "stale" not in result["error_message"].lower()


def test_colour_escapes_are_stripped_from_the_reason(dataset):
    # rclone colourises error lines even under --use-json-log.
    result = _run_bisync(dataset, [
        '\x1b[31mBisync critical error: disk quota exceeded\x1b[0m',
    ])

    assert result["critical_error"] == "disk quota exceeded"


# ---------------------------------------------------------------------------
# The specific diagnostics must still be recognised
# ---------------------------------------------------------------------------

STALE_BASELINE_LINES = [
    "Bisync critical error: cannot find prior Path1 or Path2 listings, "
    "likely due to critical error on prior run",
    "Bisync critical error: empty prior Path1 listing: /wd/ds.path1.lst",
    "Bisync critical error: empty prior Path2 listing: /wd/ds.path2.lst",
    "Bisync critical error: filters file has changed (must run --resync): /wd/ds.md5",
]


@pytest.mark.parametrize("line", STALE_BASELINE_LINES)
def test_real_stale_baseline_diagnostics_are_recognised(dataset, line):
    result = _run_bisync(dataset, [line, "Bisync aborted. Must run --resync to recover."])

    assert result["needs_resync"] is True


def test_empty_prior_listing_is_not_mistaken_for_an_empty_folder(dataset):
    """The two cases share one rclone format string but need opposite handling.

    ``Empty %s listing. Cannot sync to an empty directory: %s`` renders with
    either "prior Path1" or "current Path1". A *prior* listing that is empty is
    a stale baseline and self-heals with a re-baseline; a *current* one means
    the live folder is empty and needs a human to confirm. Keying off the shared
    tail parked recoverable datasets in needs_attention forever.
    """
    result = _run_bisync(dataset, [
        "Empty prior Path1 listing. Cannot sync to an empty directory: /wd/ds.path1.lst",
    ])

    assert result["needs_resync"] is True
    assert result["empty_source_abort"] is False


def test_empty_current_listing_still_stops_for_confirmation(dataset):
    result = _run_bisync(dataset, [
        "Empty current Path1 listing. Cannot sync to an empty directory: /wd/ds.path1.lst-new",
    ])

    assert result["empty_source_abort"] is True
    assert result["needs_resync"] is False
    assert "empty" in result["error_message"].lower()


# ---------------------------------------------------------------------------
# A run that already carried --resync cannot have a stale baseline
# ---------------------------------------------------------------------------

def test_a_resync_run_is_never_diagnosed_as_needing_a_resync(dataset):
    result = _run_bisync(
        dataset,
        ["Bisync critical error: empty prior Path1 listing: /wd/ds.path1.lst"],
        force_resync=True,
    )

    assert result["did_resync"] is True
    assert not result["needs_resync"], (
        "the run just rebuilt the listings, so blaming them would loop forever"
    )


def test_first_ever_sync_counts_as_a_resync(tmp_path):
    never_synced = SyncDataset(
        dataset_id="ds-new", name="New", bucket_name="bkt",
        remote_prefix="r2sync/v1/datasets/ds-new", local_path=str(tmp_path),
        initial_sync_done=False,
    )
    result = _run_bisync(never_synced, ["Bisync critical error: some other failure"])

    assert result["did_resync"] is True


# ---------------------------------------------------------------------------
# Lock files
# ---------------------------------------------------------------------------

def test_a_held_lock_is_reported_as_transient_not_as_a_failure(dataset):
    result = _run_bisync(dataset, [
        "Bisync critical error: prior lock file found: /wd/ds/_data.lck",
    ])

    assert result["lock_conflict"] is True
    assert not result["needs_resync"]
    assert "still running" in result["error_message"]


def test_bisync_expires_abandoned_lock_files(dataset):
    """A run killed by a crash or a reboot leaves its lock behind.

    Without --max-lock rclone treats that lock as valid forever and every later
    sync of the dataset dies in a fraction of a second with "prior lock file
    found", with no way to clear it from the UI.
    """
    captured = {}

    class FakeProc:
        stdout = io.StringIO("")

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
        RcloneEngine().run_bisync(dataset=dataset)

    args = captured["args"]
    assert "--max-lock" in args
    assert args[args.index("--max-lock") + 1].endswith("m")


# ---------------------------------------------------------------------------
# Log contents
# ---------------------------------------------------------------------------

def test_the_sync_log_records_the_exact_command_line(dataset):
    """Without this the logs cannot be used to reproduce a run by hand.

    Credentials travel through the environment, never argv, so writing the
    command line to disk leaks nothing.
    """
    result = _run_bisync(dataset, ["all good"], exit_code=0)

    log = open(result["log_file_path"], encoding="utf-8").read()
    assert "Command:" in log
    assert "bisync" in log
    assert "--max-lock" in log
    for secret_ish in ("secret", "access_key", "RCLONE_CONFIG_R2_SECRET"):
        assert secret_ish not in log
