import os
import sys

# Check for TUI mode or headless Linux environment
if "tui" in sys.argv or "--tui" in sys.argv or (
    sys.platform.startswith("linux")
    and not os.environ.get("DISPLAY")
    and not os.environ.get("WAYLAND_DISPLAY")
    and "--minimized" not in sys.argv
):
    from r2sync.client.tui import run_tui
    run_tui()
    sys.exit(0)

from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from r2sync.client.ipc_client import IPCClient
from r2sync.config import APP_DISPLAY_NAME
from r2sync.core.db import Database
from r2sync.gui.app import MainWindow
from r2sync.gui.styles.theme import apply_theme
from r2sync.utils.logging import setup_logger
from r2sync.utils.paths import get_asset_path

logger = setup_logger(name="r2sync.gui", file_prefix="gui")

SINGLE_INSTANCE_SERVER_NAME = "r2sync_single_instance_app_v1"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setQuitOnLastWindowClosed(False)

    # 1. Single Instance Check: Check if an instance is already running
    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_SERVER_NAME)
    if socket.waitForConnected(400):
        # Existing instance found! Send "show" command and exit
        logger.info("Another r2sync instance is already running. Activating existing window...")
        socket.write(b"show\n")
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()
        return 0

    icon_path = get_asset_path("icon.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    apply_theme(app, "dark")

    db = Database()
    ipc = IPCClient()

    window = MainWindow(ipc_client=ipc, db=db)

    # Setup local server to listen for new instance activation requests
    server = QLocalServer()
    server.removeServer(SINGLE_INSTANCE_SERVER_NAME)
    server.listen(SINGLE_INSTANCE_SERVER_NAME)

    def on_new_connection():
        client_sock = server.nextPendingConnection()
        if client_sock:
            window.showNormal()
            window.raise_()
            window.activateWindow()

    server.newConnection.connect(on_new_connection)

    # Check CLI arguments (e.g. launched with --minimized on startup)
    if "--minimized" not in sys.argv:
        window.show()

    exit_code = app.exec()
    server.close()
    server.removeServer(SINGLE_INSTANCE_SERVER_NAME)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
