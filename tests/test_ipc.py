import time
import pytest
from r2sync.client.ipc_client import IPCClient
from r2sync.core.backup_engine import BackupEngine
from r2sync.core.db import Database
from r2sync.core.models import BackupJob
from r2sync.core.rclone_engine import RcloneEngine
from r2sync.core.scheduler import JobScheduler
from r2sync.service.ipc_server import IPCServer


@pytest.fixture
def ipc_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("R2SYNC_DATA_DIR", str(tmp_path))
    db = Database(tmp_path / "test.db")
    engine = RcloneEngine()
    backup_engine = BackupEngine(db, engine)
    scheduler = JobScheduler(db, lambda j: None)

    # Use port 48999 for test isolation
    test_port = 48999
    server = IPCServer(db, backup_engine, scheduler, port=test_port)
    server.start()

    client = IPCClient(port=test_port)
    time.sleep(0.1)

    yield {"server": server, "client": client, "db": db, "backup_engine": backup_engine}

    server.stop()
    client.stop_event_stream()


def test_ipc_ping_and_job_crud(ipc_setup):
    client = ipc_setup["client"]
    db = ipc_setup["db"]

    assert client.is_service_running() is True
    ping = client.call("ping")
    assert ping["status"] == "ok"

    # Create job via IPC
    job_dict = {
        "name": "IPC Test Job",
        "source_path": "/test/src",
        "bucket_name": "ipc-bucket",
    }
    job_id = client.create_job(job_dict)
    assert job_id > 0

    # List jobs
    jobs = client.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["name"] == "IPC Test Job"

    # Get job
    j = client.get_job(job_id)
    assert j["id"] == job_id

    # Delete job
    assert client.delete_job(job_id) is True
    assert len(client.list_jobs()) == 0
