"""Integration tests for Multi-PC Sync IPC communication."""

import os
import socket
import tempfile
import time
import pytest

from r2sync.client.ipc_client import IPCClient
from r2sync.core.backup_engine import BackupEngine
from r2sync.core.db import Database
from r2sync.core.rclone_engine import RcloneEngine
from r2sync.core.scheduler import JobScheduler
from r2sync.core.sync_engine import SyncEngine
from r2sync.service.ipc_server import IPCServer


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def ipc_sync_setup(tmp_path):
    db_path = tmp_path / "test_ipc_sync.db"
    db = Database(db_path=db_path)
    rclone = RcloneEngine()
    be = BackupEngine(db=db, rclone_engine=rclone)
    se = SyncEngine(db=db, rclone_engine=rclone)
    sched = JobScheduler(db=db, job_runner_cb=lambda j: None)

    port = get_free_port()
    server = IPCServer(db=db, backup_engine=be, scheduler=sched, sync_engine=se, port=port)
    server.start()
    time.sleep(0.1)

    client = IPCClient(port=port)
    yield client, db, server

    server.stop()
    client.stop_event_stream()
    db.close()


def test_ipc_sync_crud_and_device_identity(ipc_sync_setup):
    client, db, server = ipc_sync_setup

    # Test device identity RPC
    dev_ident = client.get_device_identity()
    assert "device_id" in dev_ident
    assert len(dev_ident["device_id"]) > 0

    assert client.set_device_name("Office-PC") is True
    assert client.get_device_identity()["device_name"] == "Office-PC"

    # Test create sync dataset RPC
    with tempfile.TemporaryDirectory() as tmp_dir:
        created = client.create_sync_dataset(
            name="Test Sync IPC",
            local_path=tmp_dir,
            bucket_name="my-bucket",
            schedule_mode="interval",
            schedule_interval_minutes=30,
        )
        assert created is not None
        ds_id = created.get("dataset_id")
        assert ds_id is not None

        # Test list sync datasets RPC
        datasets = client.list_sync_datasets()
        assert len(datasets) == 1
        assert datasets[0]["name"] == "Test Sync IPC"
        assert datasets[0]["schedule_interval_minutes"] == 30

        # Test pause / resume RPC
        assert client.pause_sync_dataset(ds_id) is True
        fetched = client.get_sync_dataset(ds_id)
        assert fetched["paused"] is True

        assert client.resume_sync_dataset(ds_id) is True
        fetched = client.get_sync_dataset(ds_id)
        assert fetched["paused"] is False

        # Test delete sync dataset RPC
        assert client.delete_sync_dataset(ds_id) is True
        datasets = client.list_sync_datasets()
        assert len(datasets) == 0
