"""Tests for the progress readout: Transferred/Total vs Scanned/Discovered."""

import os

import pytest

from conftest import skip_module_unless

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from r2sync.core.models import SyncProgressEvent
from r2sync.core.prescan import DatasetEstimate, scan_local_tree

try:
    from PySide6.QtWidgets import QApplication
    from r2sync.gui.views.live_progress import (
        LiveProgressWidget,
        format_bytes,
        format_duration,
        format_speed,
    )
    PYSIDE6_AVAILABLE = True
except (ImportError, OSError) as e:
    PYSIDE6_AVAILABLE = False
    PYSIDE6_IMPORT_ERROR = str(e)

pytestmark = skip_module_unless(
    PYSIDE6_AVAILABLE, "PySide6 runtime", "Install a PySide6 runtime (on Linux: libegl1, libgl1, libxkbcommon-x11-0, libdbus-1-3, libxcb-cursor0)."
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def test_byte_formatting_picks_a_sensible_unit():
    assert format_bytes(0) == "0 B"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(5 * 1024 ** 3) == "5.0 GB"
    assert format_speed(2 * 1024 ** 2) == "2.0 MB/s"


def test_duration_formatting():
    assert format_duration(None) == "--"
    assert format_duration(45) == "45s"
    assert format_duration(125) == "2m 05s"
    assert format_duration(3725) == "1h 02m"


# ---------------------------------------------------------------------------
# The two presentation modes
# ---------------------------------------------------------------------------

def test_scanning_phase_says_discovered_not_total(qapp):
    """While rclone is still enumerating, the denominator is not a real total."""
    w = LiveProgressWidget()
    w.update_progress(SyncProgressEvent(
        dataset_id="ds1",
        phase="scanning",
        totals_final=False,
        checks_done=812,
        total_bytes=1_200_000,
        estimated_total_bytes=9_000_000,
    ).to_dict())

    text = w.stats_label.text()
    assert "Scanned" in text and "discovered" in text
    assert "/" not in text, "a Transferred/Total ratio must not be implied yet"
    # An indeterminate bar rather than a misleading percentage.
    assert (w.progress_bar.minimum(), w.progress_bar.maximum()) == (0, 0)


def test_transfer_phase_shows_a_real_total(qapp):
    w = LiveProgressWidget()
    w.update_progress(SyncProgressEvent(
        dataset_id="ds1",
        phase="transferring",
        totals_final=True,
        percentage=25.0,
        bytes_transferred=1024 ** 2,
        total_bytes=4 * 1024 ** 2,
        files_transferred=3,
        total_files=12,
        speed_bytes_per_sec=2 * 1024 ** 2,
        eta_seconds=90,
        current_file="reports/q3 summary.xlsx",
    ).to_dict())

    text = w.stats_label.text()
    assert "1.0 MB / 4.0 MB" in text
    assert "3/12 files" in text
    assert "2.0 MB/s" in text
    assert "ETA 1m 30s" in text
    assert w.progress_bar.value() == 25
    assert (w.progress_bar.minimum(), w.progress_bar.maximum()) == (0, 100)


def test_download_and_upload_are_labelled_distinctly(qapp):
    w = LiveProgressWidget()
    base = dict(dataset_id="ds1", phase="transferring", totals_final=True,
                bytes_transferred=10, total_bytes=100)

    w.update_progress(SyncProgressEvent(direction="download", **base).to_dict())
    assert "Downloading" in w.title_label.text()

    w.update_progress(SyncProgressEvent(direction="upload", **base).to_dict())
    assert "Uploading" in w.title_label.text()

    w.update_progress(SyncProgressEvent(direction="sync", **base).to_dict())
    assert "Sync in Progress" in w.title_label.text()


def test_reset_restores_a_determinate_idle_bar(qapp):
    w = LiveProgressWidget()
    w.update_progress(SyncProgressEvent(
        dataset_id="ds1", phase="scanning", totals_final=False
    ).to_dict())
    assert w.progress_bar.maximum() == 0

    w.reset()
    assert (w.progress_bar.minimum(), w.progress_bar.maximum()) == (0, 100)
    assert w.isHidden()


def test_long_file_names_are_elided(qapp):
    w = LiveProgressWidget()
    long_name = "some/very/deeply/nested/directory/structure/" + "x" * 80 + ".bin"
    w.update_progress(SyncProgressEvent(
        dataset_id="ds1", phase="transferring", totals_final=True,
        total_bytes=10, bytes_transferred=1, current_file=long_name,
    ).to_dict())
    assert len(w.file_label.text()) <= 55


# ---------------------------------------------------------------------------
# Pre-scan
# ---------------------------------------------------------------------------

def test_local_prescan_counts_files_and_bytes(tmp_path):
    (tmp_path / "sub dir").mkdir()
    (tmp_path / "a.txt").write_bytes(b"x" * 100)
    (tmp_path / "sub dir" / "résumé.pdf").write_bytes(b"y" * 250)

    files, size, complete = scan_local_tree(str(tmp_path), [])
    assert (files, size, complete) == (2, 350, True)


def test_local_prescan_honours_exclusions(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "big.js").write_bytes(b"z" * 5000)
    (tmp_path / "keep.txt").write_bytes(b"k" * 10)
    (tmp_path / "scratch.tmp").write_bytes(b"t" * 999)

    files, size, complete = scan_local_tree(str(tmp_path), [])
    assert (files, size) == (1, 10)


def test_local_prescan_on_missing_folder_is_not_complete(tmp_path):
    assert scan_local_tree(str(tmp_path / "nope"), []) == (0, 0, False)


def test_estimate_union_is_an_upper_bound():
    est = DatasetEstimate(local_files=10, local_bytes=1000,
                          remote_files=4, remote_bytes=4000,
                          local_complete=True, remote_complete=True)
    assert est.union_files == 10
    assert est.union_bytes == 4000
    assert est.complete is True
    assert est.to_dict()["union_bytes"] == 4000


def test_estimate_is_incomplete_when_the_remote_scan_failed():
    est = DatasetEstimate(local_complete=True, remote_complete=False)
    assert est.complete is False
