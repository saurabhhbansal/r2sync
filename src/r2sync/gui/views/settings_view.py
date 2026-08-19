"""Settings view for configuring credentials, background service, and preferences matching Stitch Design."""

import sys
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from r2sync.config import APP_DISPLAY_NAME, APP_VERSION
from r2sync.core.credentials import (
    get_r2_credentials,
    mask_secret,
    save_r2_credentials,
)
from r2sync.core.r2_client import CloudflareR2Client
from r2sync.utils.system import get_windows_autostart, set_windows_autostart


class SettingsView(QWidget):
    """Application Settings View matching Stitch Design."""

    theme_changed = Signal(str)
    credentials_saved = Signal()
    device_name_saved = Signal(str)
    restart_service_requested = Signal()
    download_rclone_requested = Signal()
    test_connection_requested = Signal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._load_current_values()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Settings")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Configure Cloudflare credentials, background service, and app preferences")
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        main_layout.addLayout(header)

        # Scroll area for settings sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(18)
        layout.setContentsMargins(0, 0, 0, 0)

        # 1. Cloudflare Credentials Group
        creds_group = QGroupBox("Cloudflare R2 Credentials")
        creds_layout = QFormLayout(creds_group)
        creds_layout.setSpacing(12)

        self.account_id_input = QLineEdit()
        self.account_id_input.setPlaceholderText("Cloudflare Account ID")
        creds_layout.addRow("Account ID:", self.account_id_input)

        self.access_key_input = QLineEdit()
        self.access_key_input.setPlaceholderText("Access Key ID")
        creds_layout.addRow("Access Key ID:", self.access_key_input)

        self.account_status_label = QLabel("<font color='#A58C7D'>● Not Configured</font>")
        creds_layout.addRow("Connection Status:", self.account_status_label)

        secret_row = QHBoxLayout()
        self.secret_key_input = QLineEdit()
        self.secret_key_input.setEchoMode(QLineEdit.Password)
        self.secret_key_input.setPlaceholderText("Secret Access Key")
        self.show_secret_btn = QPushButton("👁")
        self.show_secret_btn.setObjectName("secondaryBtn")
        self.show_secret_btn.setFixedWidth(36)
        self.show_secret_btn.clicked.connect(self._toggle_secret_visibility)
        secret_row.addWidget(self.secret_key_input)
        secret_row.addWidget(self.show_secret_btn)
        creds_layout.addRow("Secret Access Key:", secret_row)

        creds_btn_row = QHBoxLayout()
        self.test_creds_btn = QPushButton("⚡ Test Connection")
        self.test_creds_btn.setObjectName("secondaryBtn")
        self.test_creds_btn.clicked.connect(self._test_connection)
        self.save_creds_btn = QPushButton("💾 Save Credentials")
        self.save_creds_btn.clicked.connect(self._save_credentials)

        creds_btn_row.addWidget(self.test_creds_btn)
        creds_btn_row.addWidget(self.save_creds_btn)
        creds_btn_row.addStretch()
        creds_layout.addRow("", creds_btn_row)

        layout.addWidget(creds_group)

        # 2. Background Service & Engine Group
        svc_group = QGroupBox("Background Engine & Service")
        svc_layout = QFormLayout(svc_group)
        svc_layout.setSpacing(12)

        self.svc_status_label = QLabel("<font color='#4AE176'>● Background Service Active</font>")
        svc_layout.addRow("Service Status:", self.svc_status_label)

        self.rclone_status_label = QLabel("Detecting...")
        rclone_row = QHBoxLayout()
        rclone_row.addWidget(self.rclone_status_label)
        self.redetect_rclone_btn = QPushButton("🔄 Re-detect")
        self.redetect_rclone_btn.setObjectName("secondaryBtn")
        self.redetect_rclone_btn.clicked.connect(self._check_rclone)
        self.download_rclone_btn = QPushButton("⬇ Download Engine")
        self.download_rclone_btn.setObjectName("secondaryBtn")
        self.download_rclone_btn.clicked.connect(self.download_rclone_requested.emit)
        rclone_row.addWidget(self.redetect_rclone_btn)
        rclone_row.addWidget(self.download_rclone_btn)
        rclone_row.addStretch()
        svc_layout.addRow("Rclone Engine:", rclone_row)

        layout.addWidget(svc_group)

        # 3. Device Identity (Multi-PC Synchronization) Group
        dev_group = QGroupBox("Computer & Device Identity")
        dev_layout = QFormLayout(dev_group)
        dev_layout.setSpacing(12)

        dev_row = QHBoxLayout()
        self.device_name_input = QLineEdit()
        self.device_name_input.setPlaceholderText("e.g. Desktop-PC, Work-Laptop")
        self.save_dev_name_btn = QPushButton("Save Name")
        self.save_dev_name_btn.setObjectName("secondaryBtn")
        self.save_dev_name_btn.clicked.connect(self._save_device_name)
        dev_row.addWidget(self.device_name_input)
        dev_row.addWidget(self.save_dev_name_btn)
        dev_layout.addRow("Computer Name:", dev_row)

        dev_note = QLabel("This name identifies this PC across your shared Multi-PC sync folders.")
        dev_note.setStyleSheet("color: #A58C7D; font-size: 11px;")
        dev_layout.addRow("", dev_note)

        layout.addWidget(dev_group)

        # 4. Preferences Group
        pref_group = QGroupBox("Application Preferences")
        pref_layout = QFormLayout(pref_group)
        pref_layout.setSpacing(12)

        self.autostart_cb = QCheckBox("Start r2sync automatically with Windows (minimized to tray)")
        self.autostart_cb.setChecked(get_windows_autostart(APP_DISPLAY_NAME))
        self.autostart_cb.toggled.connect(self._on_autostart_toggled)
        pref_layout.addRow("Autostart:", self.autostart_cb)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark Theme (R2Sync Pro Dark)", "Light Theme"])
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        pref_layout.addRow("Color Theme:", self.theme_combo)

        layout.addWidget(pref_group)

        # 5. About & Open Source Group
        about_group = QGroupBox("About r2sync")
        about_layout = QVBoxLayout(about_group)
        about_layout.setSpacing(8)

        ver_lbl = QLabel(f"<b>{APP_DISPLAY_NAME} v{APP_VERSION}</b> — Cloudflare R2 Backup & Multi-PC Sync")
        ver_lbl.setStyleSheet("color: #E1E2E8;")
        about_layout.addWidget(ver_lbl)

        license_lbl = QLabel("Licensed under the MIT License. Zero telemetry, zero proprietary server dependencies.")
        license_lbl.setStyleSheet("color: #A58C7D; font-size: 12px;")
        about_layout.addWidget(license_lbl)

        layout.addWidget(about_group)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def _load_current_values(self):
        creds = get_r2_credentials()
        if creds and creds.account_id:
            self.account_id_input.setText(creds.account_id)
            self.access_key_input.setText(creds.access_key_id)
            self.secret_key_input.setText(creds.secret_access_key)
            masked = f"{creds.account_id[:6]}••••••••{creds.account_id[-4:]}" if len(creds.account_id) > 10 else creds.account_id
            self.account_status_label.setText(f"<font color='#4AE176'>● Connected ({masked})</font>")
        else:
            self.account_status_label.setText("<font color='#A58C7D'>● Not Configured</font>")
        self._check_rclone()

    def _check_rclone(self):
        try:
            from r2sync.core.rclone_engine import RcloneBinaryManager

            installed = RcloneBinaryManager.is_installed()
            ver = RcloneBinaryManager.get_version() if installed else "Not installed"
            self.set_rclone_status(installed, ver)
        except Exception as e:
            self.set_rclone_status(False, f"Error: {e}")

    def _toggle_secret_visibility(self):
        if self.secret_key_input.echoMode() == QLineEdit.Password:
            self.secret_key_input.setEchoMode(QLineEdit.Normal)
            self.show_secret_btn.setText("🔒")
        else:
            self.secret_key_input.setEchoMode(QLineEdit.Password)
            self.show_secret_btn.setText("👁")

    def _save_credentials(self):
        acc = self.account_id_input.text().strip()
        ak = self.access_key_input.text().strip()
        sk = self.secret_key_input.text().strip()

        if not acc or not ak or not sk:
            QMessageBox.warning(self, "Validation Error", "Please fill in all Cloudflare credentials.")
            return

        # Sanitize account_id
        acc = acc.replace("https://", "").replace("http://", "").rstrip("/")
        if ".r2.cloudflarestorage.com" in acc:
            acc = acc.replace(".r2.cloudflarestorage.com", "")

        save_r2_credentials(acc, ak, sk)
        self._load_current_values()
        QMessageBox.information(self, "Credentials Saved", "Cloudflare R2 credentials have been securely stored.")
        self.credentials_saved.emit()

    def _test_connection(self):
        acc = self.account_id_input.text().strip()
        ak = self.access_key_input.text().strip()
        sk = self.secret_key_input.text().strip()
        self.test_connection_requested.emit(acc, ak, sk)

    def _on_autostart_toggled(self, checked: bool):
        if sys.platform == "win32":
            set_windows_autostart(APP_DISPLAY_NAME, sys.argv[0], checked)

    def _on_theme_changed(self, index: int):
        theme_name = "light" if index == 1 else "dark"
        self.theme_changed.emit(theme_name)

    def set_device_identity(self, device_id: str, device_name: str):
        self.device_id = device_id
        self.device_name_input.setText(device_name or "")

    def _save_device_name(self):
        name = self.device_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Please provide a valid computer name.")
            return
        self.device_name_saved.emit(name)
        QMessageBox.information(self, "Saved", f"Computer name updated to '{name}'.")

    def set_rclone_status(self, installed: bool, version: str):
        if installed:
            self.rclone_status_label.setText(f"<font color='#4AE176'>✓ Installed ({version})</font>")
        else:
            self.rclone_status_label.setText("<font color='#FFB4AB'>✗ Missing binary</font>")

    def set_service_status(self, active: bool):
        if active:
            self.svc_status_label.setText("<font color='#4AE176'>● Background Service Active</font>")
        else:
            self.svc_status_label.setText("<font color='#FFB4AB'>● Background Service Offline</font>")
