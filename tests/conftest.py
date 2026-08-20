"""Shared pytest configuration for the r2sync suite."""

import os

import pytest

# Constructing the GUI window normally launches the detached background service
# (that is what keeps sync alive after the window closes). Tests must never
# spawn a real daemon, which would bind the IPC port and outlive the run.
os.environ.setdefault("R2SYNC_NO_AUTO_SERVICE", "1")


@pytest.fixture(autouse=True)
def isolated_app_data(tmp_path_factory, monkeypatch):
    """Point every test at a throwaway application data directory."""
    if os.environ.get("R2SYNC_DATA_DIR"):
        yield
        return
    data_dir = tmp_path_factory.mktemp("r2sync-data")
    monkeypatch.setenv("R2SYNC_DATA_DIR", str(data_dir))
    yield
