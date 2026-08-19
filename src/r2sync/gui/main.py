"""Main entry point for r2sync desktop GUI application."""

import sys
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from r2sync.client.ipc_client import IPCClient
from r2sync.config import APP_DISPLAY_NAME
from r2sync.core.db import Database
from r2sync.gui.app import MainWindow
from r2sync.gui.styles.theme import apply_theme
from r2sync.utils.logging import setup_logger
from r2sync.utils.paths import get_asset_path

logger = setup_logger(name="r2sync.gui", file_prefix="gui")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setQuitOnLastWindowClosed(False)

    icon_path = get_asset_path("icon.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    apply_theme(app, "dark")

    db = Database()
    ipc = IPCClient()

    window = MainWindow(ipc_client=ipc, db=db)

    # Check CLI arguments (e.g. launched with --minimized on startup)
    if "--minimized" not in sys.argv:
        window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
