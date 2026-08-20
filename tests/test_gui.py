"""Tests for GUI views, theme styling, and window controller."""

import os
import sys
import pytest

from conftest import require_or_skip

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
        require_or_skip(False, f"PySide6 runtime ({PYSIDE6_IMPORT_ERROR})", "Install a PySide6 runtime (on Linux: libegl1, libgl1, libxkbcommon-x11-0, libdbus-1-3, libxcb-cursor0).")
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_main_window_and_views(qapp, tmp_path):
    if not PYSIDE6_AVAILABLE:
        require_or_skip(False, f"PySide6 runtime ({PYSIDE6_IMPORT_ERROR})", "Install a PySide6 runtime (on Linux: libegl1, libgl1, libxkbcommon-x11-0, libdbus-1-3, libxcb-cursor0).")

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

    # Verify all 4 consolidated views are instantiated in stack
    assert window.stack.count() == 4

    # Test tab switching
    for i in range(4):
        window.stack.setCurrentIndex(i)
        assert window.stack.currentIndex() == i

    # Test light theme switch
    apply_theme(qapp, "light")
    apply_theme(qapp, "dark")


def test_folder_tree_filter_widget(qapp, tmp_path):
    if not PYSIDE6_AVAILABLE:
        require_or_skip(False, f"PySide6 runtime ({PYSIDE6_IMPORT_ERROR})", "Install a PySide6 runtime (on Linux: libegl1, libgl1, libxkbcommon-x11-0, libdbus-1-3, libxcb-cursor0).")

    from PySide6.QtCore import Qt
    from r2sync.gui.views.folder_tree_widget import FolderTreeFilterWidget
    from r2sync.gui.views.job_edit_dialog import JobEditDialog
    from r2sync.gui.views.add_sync_dialog import AddSyncDialog

    # Create dummy folder structure
    src = tmp_path / "my_project"
    src.mkdir()
    (src / "src").mkdir()
    (src / "src" / "app.py").write_text("print('hello')")
    (src / "node_modules").mkdir()
    (src / "node_modules" / "pkg.json").write_text("{}")
    (src / "notes.txt").write_text("notes")

    widget = FolderTreeFilterWidget(str(src))
    assert widget.tree.topLevelItemCount() == 1

    root_item = widget.tree.topLevelItem(0)
    assert root_item.childCount() >= 3

    # Test exclude temp artifacts
    widget._uncheck_temp_artifacts()
    patterns = widget.get_exclude_patterns()
    assert any("node_modules" in p for p in patterns)

    # Test JobEditDialog with FolderTreeFilterWidget
    dlg = JobEditDialog(buckets=["my-bucket"])
    dlg.source_input.setText(str(src))
    dlg.name_input.setText("Project Backup")
    assert dlg.tree_filter.root_path == str(src.resolve())

    # Test AddSyncDialog with FolderTreeFilterWidget
    sync_dlg = AddSyncDialog(buckets=["my-bucket"])
    sync_dlg.source_input.setText(str(src))
    sync_dlg.name_input.setText("Project Sync")
    assert sync_dlg.tree_filter.root_path == str(src.resolve())

