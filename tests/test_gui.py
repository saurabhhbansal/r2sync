"""Tests for GUI views, theme styling, and window controller."""

import os
import sys
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    from PySide6.QtWidgets import QApplication
    from r2sync.client.ipc_client import IPCClient
    from r2sync.core.db import Database
    from r2sync.core.models import BackupJob, SyncDataset
    from r2sync.gui.app import MainWindow
    from r2sync.gui.styles.theme import apply_theme
    PYSIDE6_AVAILABLE = True
except (ImportError, OSError) as e:
    PYSIDE6_AVAILABLE = False
    PYSIDE6_IMPORT_ERROR = str(e)


@pytest.fixture(scope="session")
def qapp():
    if not PYSIDE6_AVAILABLE:
        pytest.skip(f"PySide6 runtime libraries unavailable in environment: {PYSIDE6_IMPORT_ERROR}")
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_main_window_and_views(qapp, tmp_path):
    if not PYSIDE6_AVAILABLE:
        pytest.skip(f"PySide6 runtime libraries unavailable: {PYSIDE6_IMPORT_ERROR}")

    db_path = tmp_path / "gui_test.sqlite"
    db = Database(db_path)

    # Insert sample job and dataset
    job = BackupJob(name="Test Documents", source_path=str(tmp_path / "docs"), bucket_name="r2sync-test")
    db.create_job(job)

    ds = SyncDataset(dataset_id="test-ds-1", name="Test Sync Folder", local_path=str(tmp_path / "sync"), bucket_name="r2sync-test")
    db.create_sync_dataset(ds)

    ipc = IPCClient()
    apply_theme(qapp, "dark")

    window = MainWindow(ipc, db)
    window.refresh_all_data()

    # Verify all 6 views are instantiated in stack
    assert window.stack.count() == 6

    # Test tab switching
    for i in range(6):
        window.stack.setCurrentIndex(i)
        assert window.stack.currentIndex() == i

    # Test light theme switch
    apply_theme(qapp, "light")
    apply_theme(qapp, "dark")
