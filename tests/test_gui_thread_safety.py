"""Engine and IPC events must reach the GUI on the GUI thread.

Sync progress/completion callbacks run on a sync worker thread and IPC events
run on the client's socket-reader thread. Both used to call straight into
widget code, which Qt does not allow: it segfaulted the whole process partway
through an ordinary sync. It only showed up once the end-to-end tests had a
real rclone to drive, which is also why CI never caught it.

The fix routes every such callback through a Qt signal, so Qt queues the
payload and runs the handler on the GUI thread.
"""

import os
import threading

import pytest

from conftest import require_or_skip

os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    from PySide6.QtWidgets import QApplication
    from r2sync.client.ipc_client import IPCClient
    from r2sync.core.db import Database
    from r2sync.core.models import SyncDataset, SyncProgressEvent
    from r2sync.gui.app import MainWindow, _as_payload
    PYSIDE6_AVAILABLE = True
except (ImportError, OSError) as e:  # pragma: no cover - environment dependent
    PYSIDE6_AVAILABLE = False
    PYSIDE6_IMPORT_ERROR = str(e)

QT_HOW = (
    "Install a PySide6 runtime (on Linux: libegl1, libgl1, libxkbcommon-x11-0, "
    "libdbus-1-3, libxcb-cursor0)."
)


@pytest.fixture(scope="module")
def qapp():
    if not PYSIDE6_AVAILABLE:
        require_or_skip(False, f"PySide6 runtime ({PYSIDE6_IMPORT_ERROR})", QT_HOW)
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path):
    db = Database(tmp_path / "thread_safety.sqlite")
    db.create_sync_dataset(SyncDataset(
        dataset_id="ds-thread", name="Threaded", bucket_name="bkt",
        local_path=str(tmp_path / "sync"),
    ))
    win = MainWindow(IPCClient(), db)
    yield win
    win.close()
    db.close()


SIGNALS = [
    "job_progress_received",
    "job_completed_received",
    "sync_progress_received",
    "sync_completed_received",
]


@pytest.mark.parametrize("name", SIGNALS)
def test_the_window_exposes_a_signal_for_every_worker_event(window, name):
    assert hasattr(window, name), (
        f"{name} is the GUI-thread hop for worker callbacks; without it the "
        "handler runs on the worker thread and Qt crashes"
    )


def test_emitting_from_a_worker_thread_does_not_run_the_handler_there(window):
    """The point of the signal: the handler must not run inline on the worker.

    With a direct callback the handler executed on the emitting thread, which
    is precisely the illegal widget access. Queued delivery means nothing runs
    until the GUI thread pumps its event loop.
    """
    ran_on = []
    window.sync_completed_received.connect(
        lambda _payload: ran_on.append(threading.current_thread().name)
    )

    worker = threading.Thread(
        target=lambda: window.sync_completed_received.emit({"dataset_id": "ds-thread"}),
        name="pretend-sync-worker",
    )
    worker.start()
    worker.join(timeout=5)

    assert "pretend-sync-worker" not in ran_on, (
        "the handler ran on the worker thread -- the callback is still direct"
    )


def test_a_real_engine_broadcast_never_touches_widgets_on_the_worker(window):
    """Drives the actual engine callback path, not just the signal in isolation.

    ``_broadcast_progress`` is what a sync worker calls. The registered listener
    resolves ``self._on_sync_progress`` at call time, so swapping the attribute
    catches a direct call; a correctly wired window emits instead and the
    handler stays queued until the GUI thread runs it.
    """
    engine = window.internal_sync_engine
    if engine is None:
        pytest.skip("no internal engine in this configuration")

    offending_threads = []

    def recorder(payload):
        current = threading.current_thread()
        if current is not threading.main_thread():
            offending_threads.append(current.name)

    window._on_sync_progress = recorder
    window._on_sync_completed = recorder

    event = SyncProgressEvent(dataset_id="ds-thread", status="syncing", percentage=50.0)
    worker = threading.Thread(
        target=lambda: engine._broadcast_progress(event),
        name="pretend-sync-worker",
    )
    worker.start()
    worker.join(timeout=5)

    assert not offending_threads, (
        f"a GUI handler ran on {offending_threads} -- the engine listener calls "
        "into widget code directly instead of emitting a signal"
    )


def test_payload_normalisation_accepts_every_event_shape():
    event = SyncProgressEvent(dataset_id="ds", status="syncing", percentage=12.5)
    assert _as_payload(event)["dataset_id"] == "ds"

    already_a_dict = {"dataset_id": "ds", "percentage": 12.5}
    assert _as_payload(already_a_dict) is already_a_dict

    class Plain:
        def __init__(self):
            self.dataset_id = "ds"

    assert _as_payload(Plain())["dataset_id"] == "ds"
