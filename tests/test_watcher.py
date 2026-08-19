"""Unit tests for filesystem change detection and debounced watcher manager."""

import time
from r2sync.core.watcher import DebouncedWatcherManager, is_path_excluded


def test_path_exclusion_rules():
    # Temporary and internal system files must be excluded
    assert is_path_excluded("~$document.docx", []) is True
    assert is_path_excluded("temp_file.tmp", []) is True
    assert is_path_excluded("file.partial", []) is True
    assert is_path_excluded("Thumbs.db", []) is True
    assert is_path_excluded(".DS_Store", []) is True
    assert is_path_excluded(".r2sync_trash/deleted_file.txt", []) is True
    assert is_path_excluded(".git/HEAD", []) is True

    # User patterns
    custom_patterns = ["*.log", "build/", "node_modules/"]
    assert is_path_excluded("server.log", custom_patterns) is True
    assert is_path_excluded("build/output.bin", custom_patterns) is True
    assert is_path_excluded("node_modules/package/index.js", custom_patterns) is True

    # Valid non-excluded files
    assert is_path_excluded("my_notes.txt", custom_patterns) is False
    assert is_path_excluded("photos/vacation.jpg", custom_patterns) is False


def test_debounced_event_firing():
    events_received = []

    def on_change(dataset_id: str):
        events_received.append(dataset_id)

    manager = DebouncedWatcherManager(on_change_triggered=on_change, debounce_seconds=0.1)

    # Fire multiple rapid raw change events for dataset-1
    manager._on_raw_change("dataset-1")
    manager._on_raw_change("dataset-1")
    manager._on_raw_change("dataset-1")

    # Before debounce timer expires, no callback should have fired
    assert len(events_received) == 0

    # Wait for debounce duration
    time.sleep(0.2)

    # Should have coalesced into exactly 1 event
    assert len(events_received) == 1
    assert events_received[0] == "dataset-1"
