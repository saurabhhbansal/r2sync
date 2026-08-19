from PySide6.QtCore import Qt, Signal, QTimer, QThread
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
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from r2sync.config import (
    APP_DISPLAY_NAME,
    APP_VERSION,
    SETTING_SPEED_PROFILE,
)
from r2sync.core.credentials import (
    get_r2_credentials,
    mask_secret,
    save_r2_credentials,
)
from r2sync.core.r2_client import CloudflareR2Client
from r2sync.core.speed_profiles import SPEED_PROFILES, get_speed_profile, list_speed_profiles
from r2sync.core.updater import AutoUpdater, UpdateInfo
from r2sync.utils.system import get_windows_autostart, set_windows_autostart


class UpdateCheckWorker(QThread):
    check_finished = Signal(object)

    def run(self):
        try:
            info = AutoUpdater.check_for_updates()
            self.check_finished.emit(info)
        except Exception:
            from r2sync.core.updater import UpdateInfo
            from r2sync.config import APP_VERSION, GITHUB_REPO
            self.check_finished.emit(UpdateInfo(
                available=False,
                current_version=APP_VERSION,
                latest_version=APP_VERSION,
                release_name="",
                release_notes="",
                html_url=f"https://github.com/{GITHUB_REPO}/releases",
            ))


class UpdateDownloadWorker(QThread):
    progress = Signal(int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, update_info, parent=None):
        super().__init__(parent)
        self.update_info = update_info

    def run(self):
        try:
            def cb(done, total):
                if total > 0:
                    pct = int(done / total * 100)
                    self.progress.emit(pct)

            path = AutoUpdater.download_update(self.update_info, progress_cb=cb)
            self.finished.emit(path)
        except Exception as e:
            self.failed.emit(str(e))


class SettingsView(QWidget):
    """Application Settings View matching Stitch Design."""

    theme_changed = Signal(str)
    credentials_saved = Signal()
    device_name_saved = Signal(str)
    speed_profile_saved = Signal(str)
    restart_service_requested = Signal()
    start_service_requested = Signal()
    download_rclone_requested = Signal()
    test_connection_requested = Signal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pending_update: Optional[UpdateInfo] = None
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
        subtitle = QLabel("Configure Cloudflare credentials, transfer performance, auto-updates, and preferences")
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
        self.show_secret_btn = QPushButton("Show")
        self.show_secret_btn.setObjectName("secondaryBtn")
        self.show_secret_btn.setFixedWidth(54)
        self.show_secret_btn.clicked.connect(self._toggle_secret_visibility)
        secret_row.addWidget(self.secret_key_input)
        secret_row.addWidget(self.show_secret_btn)
        creds_layout.addRow("Secret Access Key:", secret_row)

        creds_btn_row = QHBoxLayout()
        self.test_creds_btn = QPushButton("Test Connection")
        self.test_creds_btn.setObjectName("secondaryBtn")
        self.test_creds_btn.clicked.connect(self._test_connection)
        self.save_creds_btn = QPushButton("Save Credentials")
        self.save_creds_btn.clicked.connect(self._save_credentials)

        creds_btn_row.addWidget(self.test_creds_btn)
        creds_btn_row.addWidget(self.save_creds_btn)
        creds_btn_row.addStretch()
        creds_layout.addRow("", creds_btn_row)

        layout.addWidget(creds_group)

        # 2. Transfer Speed & Concurrency Profile
        speed_group = QGroupBox("Transfer Speed & Concurrency Profile")
        speed_layout = QVBoxLayout(speed_group)
        speed_layout.setSpacing(12)

        speed_intro = QLabel("Choose a throughput profile matching your connection speed:")
        speed_intro.setStyleSheet("color: #A58C7D; font-size: 12px;")
        speed_layout.addWidget(speed_intro)

        # Slider (0: Eco, 1: Balanced, 2: Fast, 3: Turbo, 4: Extreme)
        self.speed_profiles_list = list_speed_profiles()
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(0, len(self.speed_profiles_list) - 1)
        self.speed_slider.setValue(3)  # default: Turbo
        self.speed_slider.setTickPosition(QSlider.TicksBelow)
        self.speed_slider.setTickInterval(1)
        self.speed_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #272A2E;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #F6821F;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #FFB786;
                width: 18px;
                margin-top: -6px;
                margin-bottom: -6px;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: #FFFFFF;
            }
        """)
        self.speed_slider.valueChanged.connect(self._on_speed_slider_changed)
        speed_layout.addWidget(self.speed_slider)

        # Profile Labels Row
        label_row = QHBoxLayout()
        for i, p in enumerate(self.speed_profiles_list):
            lbl = QLabel(p.label.split()[0])
            lbl.setStyleSheet("color: #A58C7D; font-size: 11px;")
            if i == 0:
                lbl.setAlignment(Qt.AlignLeft)
            elif i == len(self.speed_profiles_list) - 1:
                lbl.setAlignment(Qt.AlignRight)
            else:
                lbl.setAlignment(Qt.AlignCenter)
            label_row.addWidget(lbl)
        speed_layout.addLayout(label_row)

        # Profile Info Banner Card
        self.speed_card = QFrame()
        self.speed_card.setStyleSheet("background-color: #111418; border: 1px solid #272A2E; border-radius: 8px; padding: 10px;")
        card_layout = QVBoxLayout(self.speed_card)
        card_layout.setSpacing(4)
        card_layout.setContentsMargins(10, 8, 10, 8)

        self.speed_title_lbl = QLabel("<b>X-High (Turbo)</b> — 32 Parallel Streams")
        self.speed_title_lbl.setStyleSheet("color: #FFB786; font-size: 13px;")
        self.speed_desc_lbl = QLabel("Ultra-fast parallel transfers. Ideal for 500+ Mbps or gigabit fiber.")
        self.speed_desc_lbl.setStyleSheet("color: #A58C7D; font-size: 12px;")
        self.speed_metrics_lbl = QLabel("Streams: 32 | Checkers: 32 | Buffer: 32MB | Chunk: 16MB")
        self.speed_metrics_lbl.setStyleSheet("color: #4AE176; font-size: 11px; font-weight: 500;")

        card_layout.addWidget(self.speed_title_lbl)
        card_layout.addWidget(self.speed_desc_lbl)
        card_layout.addWidget(self.speed_metrics_lbl)
        speed_layout.addWidget(self.speed_card)

        layout.addWidget(speed_group)

        # 3. Auto-Updates Group
        update_group = QGroupBox("Software Updates")
        update_layout = QVBoxLayout(update_group)
        update_layout.setSpacing(10)

        update_header = QHBoxLayout()
        self.update_ver_lbl = QLabel(f"Current version: <b>v{APP_VERSION}</b>")
        self.update_ver_lbl.setStyleSheet("color: #E1E2E8; font-size: 13px;")
        self.check_update_btn = QPushButton("Check for Updates")
        self.check_update_btn.setObjectName("secondaryBtn")
        self.check_update_btn.clicked.connect(self._check_for_updates)
        update_header.addWidget(self.update_ver_lbl)
        update_header.addStretch()
        update_header.addWidget(self.check_update_btn)
        update_layout.addLayout(update_header)

        self.update_status_banner = QFrame()
        self.update_status_banner.setStyleSheet("background-color: #111418; border: 1px solid #272A2E; border-radius: 8px; padding: 10px;")
        banner_layout = QVBoxLayout(self.update_status_banner)
        banner_layout.setSpacing(6)
        banner_layout.setContentsMargins(10, 8, 10, 8)

        self.update_status_msg = QLabel("You are running the latest version of r2sync.")
        self.update_status_msg.setStyleSheet("color: #4AE176; font-size: 12px;")
        banner_layout.addWidget(self.update_status_msg)

        self.update_progress = QProgressBar()
        self.update_progress.setVisible(False)
        self.update_progress.setFixedHeight(8)
        self.update_progress.setStyleSheet("""
            QProgressBar {
                background-color: #191C20;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #F6821F;
                border-radius: 4px;
            }
        """)
        banner_layout.addWidget(self.update_progress)

        self.install_update_btn = QPushButton("Download and Install Update")
        self.install_update_btn.setStyleSheet("padding: 8px 16px; font-weight: 600;")
        self.install_update_btn.setVisible(False)
        self.install_update_btn.clicked.connect(self._start_update_download)
        banner_layout.addWidget(self.install_update_btn)

        update_layout.addWidget(self.update_status_banner)
        layout.addWidget(update_group)

        # 4. Background Service & Engine Group
        svc_group = QGroupBox("Background Engine & Service")
        svc_layout = QFormLayout(svc_group)
        svc_layout.setSpacing(12)

        svc_row = QHBoxLayout()
        self.svc_status_label = QLabel("<font color='#4AE176'>● Integrated Desktop Engine Active</font>")
        self.start_service_btn = QPushButton("Start 24/7 Background Daemon")
        self.start_service_btn.setObjectName("secondaryBtn")
        self.start_service_btn.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        self.start_service_btn.clicked.connect(self.start_service_requested.emit)
        self.start_service_btn.setVisible(False)
        svc_row.addWidget(self.svc_status_label)
        svc_row.addWidget(self.start_service_btn)
        svc_row.addStretch()
        svc_layout.addRow("Engine Status:", svc_row)

        self.rclone_status_label = QLabel("Detecting...")
        rclone_row = QHBoxLayout()
        rclone_row.addWidget(self.rclone_status_label)
        self.redetect_rclone_btn = QPushButton("Re-detect")
        self.redetect_rclone_btn.setObjectName("secondaryBtn")
        self.redetect_rclone_btn.clicked.connect(self._check_rclone)
        self.download_rclone_btn = QPushButton("Download Engine")
        self.download_rclone_btn.setObjectName("secondaryBtn")
        self.download_rclone_btn.clicked.connect(self.download_rclone_requested.emit)
        rclone_row.addWidget(self.redetect_rclone_btn)
        rclone_row.addWidget(self.download_rclone_btn)
        rclone_row.addStretch()
        svc_layout.addRow("Rclone Engine:", rclone_row)

        layout.addWidget(svc_group)

        # 5. Device Identity (Multi-PC Synchronization) Group
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

        # 6. Preferences Group
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

        # 7. About & Open Source Group
        about_group = QGroupBox("About r2sync")
        about_layout = QVBoxLayout(about_group)
        about_layout.setSpacing(8)

        ver_lbl = QLabel(f"<b>r2sync v{APP_VERSION}</b> — Private, native Cloudflare R2 backup & sync")
        ver_lbl.setStyleSheet("color: #E1E2E8;")
        about_layout.addWidget(ver_lbl)

        license_lbl = QLabel("Licensed under the MIT License. Zero telemetry, zero proprietary server dependencies.")
        license_lbl.setStyleSheet("color: #A58C7D; font-size: 12px;")
        about_layout.addWidget(license_lbl)

        layout.addWidget(about_group)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def _on_speed_slider_changed(self, index: int):
        if 0 <= index < len(self.speed_profiles_list):
            p = self.speed_profiles_list[index]
            self.speed_title_lbl.setText(f"<b>{p.label}</b> — {p.transfers} Parallel Streams")
            self.speed_desc_lbl.setText(p.description)
            concurrency = max(p.transfers // 2, 4)
            self.speed_metrics_lbl.setText(
                f"Streams: {p.transfers} | Checkers: {p.checkers} | Buffer: {p.buffer_size} | Chunk: {p.chunk_size} | Upload Concurrency: {concurrency}"
            )
            self.speed_profile_saved.emit(p.id)

    def set_speed_profile(self, profile_id: str):
        for i, p in enumerate(self.speed_profiles_list):
            if p.id == profile_id:
                self.speed_slider.setValue(i)
                self._on_speed_slider_changed(i)
                break

    def _check_for_updates(self):
        self.check_update_btn.setEnabled(False)
        self.update_status_msg.setText("Checking for latest release on GitHub...")
        self.update_status_msg.setStyleSheet("color: #FFB786; font-size: 12px;")

        self._check_worker = UpdateCheckWorker(self)
        self._check_worker.check_finished.connect(self._on_update_check_result)
        self._check_worker.start()

    def _on_update_check_result(self, info: UpdateInfo):
        self.check_update_btn.setEnabled(True)
        self.pending_update = info
        if info.available:
            self.update_status_msg.setText(
                f"<b>New Version Available: v{info.latest_version}</b> ({info.release_name})"
            )
            self.update_status_msg.setStyleSheet("color: #FFB786; font-size: 13px;")
            self.install_update_btn.setVisible(True)
            self.install_update_btn.setEnabled(True)
            self.install_update_btn.setText(f"Update Now to v{info.latest_version}")
        else:
            self.update_status_msg.setText(f"You are running the latest version of r2sync (v{APP_VERSION}).")
            self.update_status_msg.setStyleSheet("color: #4AE176; font-size: 12px;")
            self.install_update_btn.setVisible(False)

    def _start_update_download(self):
        if not self.pending_update or not self.pending_update.download_url:
            QMessageBox.information(
                self,
                "Manual Download",
                f"Please download the latest release from:\n{self.pending_update.html_url if self.pending_update else 'https://github.com/' + GITHUB_REPO + '/releases'}",
            )
            return

        self.install_update_btn.setEnabled(False)
        self.install_update_btn.setText("Downloading Update...")
        self.update_progress.setVisible(True)
        self.update_progress.setValue(0)

        self._download_worker = UpdateDownloadWorker(self.pending_update, self)
        self._download_worker.progress.connect(self.update_progress.setValue)
        self._download_worker.finished.connect(self._on_update_downloaded)
        self._download_worker.failed.connect(self._on_update_download_failed)
        self._download_worker.start()

    def _on_update_downloaded(self, installer_path):
        self.install_update_btn.setEnabled(True)
        self.install_update_btn.setText("Restarting to Apply Update...")
        self.update_status_msg.setText("Download complete. Launching update installer...")
        self.update_status_msg.setStyleSheet("color: #4AE176; font-size: 12px;")

        if sys.platform == "win32":
            AutoUpdater.apply_update_windows(installer_path, silent=False)
            from PySide6.QtWidgets import QApplication
            QApplication.quit()
        else:
            QMessageBox.information(
                self,
                "Update Ready",
                f"Update downloaded successfully to:\n{installer_path}",
            )

    def _on_update_download_failed(self, error_msg: str):
        self.install_update_btn.setEnabled(True)
        self.install_update_btn.setText("Retry Update Download")
        self.update_progress.setVisible(False)
        self.update_status_msg.setText(f"Update download failed: {error_msg}")
        self.update_status_msg.setStyleSheet("color: #FFB4AB; font-size: 12px;")
        QMessageBox.warning(self, "Update Failed", f"Could not download update:\n{error_msg}")

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
            self.show_secret_btn.setText("Hide")
        else:
            self.secret_key_input.setEchoMode(QLineEdit.Password)
            self.show_secret_btn.setText("Show")

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
            self.rclone_status_label.setText(f"<font color='#4AE176'>● Installed ({version})</font>")
        else:
            self.rclone_status_label.setText("<font color='#FFB4AB'>● Missing binary</font>")

    def set_service_status(self, active: bool):
        if active:
            self.svc_status_label.setText("<font color='#4AE176'>● Dedicated Background Service Active (24/7)</font>")
            self.start_service_btn.setVisible(False)
        else:
            self.svc_status_label.setText("<font color='#4AE176'>● Integrated Desktop Engine Active</font> <font color='#A58C7D'>(Syncing & schedules running)</font>")
            self.start_service_btn.setVisible(True)

