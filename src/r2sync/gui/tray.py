"""System Tray integration for r2sync."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from r2sync.config import APP_DISPLAY_NAME
from r2sync.utils.paths import get_asset_path


def create_tray_icon(is_syncing: bool = False, badge_color: str = "#F59E0B") -> QIcon:
    """Generate tray icon from official asset, adding a badge if syncing."""
    icon_path = get_asset_path("icon.png")
    if icon_path.exists():
        base = QPixmap(str(icon_path)).scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if not is_syncing:
            return QIcon(base)
        # Overlay a badge indicator in bottom-right corner
        pixmap = QPixmap(base)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(badge_color))
        painter.setPen(QColor("#12161F"))
        painter.drawEllipse(18, 18, 12, 12)
        painter.end()
        return QIcon(pixmap)

    # Fallback vector icon
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#2563EB" if not is_syncing else badge_color))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(2, 2, 28, 28, 6, 6)
    painter.setPen(QColor("#FFFFFF"))
    painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "R2")
    painter.end()
    return QIcon(pixmap)


class SystemTrayManager(QSystemTrayIcon):
    """System tray icon and context menu manager."""

    open_window_requested = Signal()
    backup_all_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIcon(create_tray_icon(is_syncing=False))
        self.setToolTip(f"{APP_DISPLAY_NAME} - Cloudflare R2 Backup")
        self._init_menu()
        self.activated.connect(self._on_activated)

    def _init_menu(self):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #18202F;
                color: #E2E8F0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #2563EB;
                color: #FFFFFF;
                border-radius: 4px;
            }
        """)

        self.status_action = QAction(f"{APP_DISPLAY_NAME}: Ready", menu)
        self.status_action.setEnabled(False)
        menu.addAction(self.status_action)
        menu.addSeparator()

        open_action = QAction("Open r2sync", menu)
        open_action.triggered.connect(self.open_window_requested.emit)
        menu.addAction(open_action)

        backup_all_action = QAction("Backup All Now", menu)
        backup_all_action.triggered.connect(self.backup_all_requested.emit)
        menu.addAction(backup_all_action)

        menu.addSeparator()

        quit_action = QAction("Exit r2sync", menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_window_requested.emit()

    def set_syncing(self, is_syncing: bool, message: str = ""):
        if is_syncing:
            self.setIcon(create_tray_icon(is_syncing=True))
            self.status_action.setText(f"r2sync: {message or 'Syncing...'}")
            self.setToolTip(f"r2sync - {message or 'Syncing files'}")
        else:
            self.setIcon(create_tray_icon(is_syncing=False))
            self.status_action.setText("r2sync: Up to date")
            self.setToolTip(f"{APP_DISPLAY_NAME} - Ready")
