import os
from r2sync.service.daemon import ServiceDaemon


def test_daemon_pid_and_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("R2SYNC_DATA_DIR", str(tmp_path))
    daemon = ServiceDaemon()

    daemon.start()
    pid_file = tmp_path / "state" / "service.pid"
    assert pid_file.exists()

    with open(pid_file, "r") as f:
        pid = int(f.read().strip())
    assert pid == os.getpid()

    daemon.stop()
    assert not pid_file.exists()
