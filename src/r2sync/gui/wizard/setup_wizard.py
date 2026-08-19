"""Guided One-Time Cloudflare R2 Setup Wizard."""

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from r2sync.config import APP_DISPLAY_NAME
from r2sync.core.credentials import save_r2_credentials
from r2sync.core.models import BackupJob, BackupMode, JobScheduleType, R2Credentials
from r2sync.core.r2_client import CloudflareR2Client
from r2sync.core.rclone_engine import RcloneEngine


class ConnectionTestThread(QThread):
    result_ready = Signal(dict)

    def __init__(self, account_id: str, access_key: str, secret_key: str):
        super().__init__()
        self.account_id = account_id
        self.access_key = access_key
        self.secret_key = secret_key

    def run(self):
        creds = R2Credentials(
            account_id=self.account_id,
            access_key_id=self.access_key,
            secret_access_key=self.secret_key,
        )
        engine = RcloneEngine(creds)
        client = CloudflareR2Client(engine)
        res = client.test_connection(creds)
        self.result_ready.emit(res)


class WelcomePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle(f"Welcome to {APP_DISPLAY_NAME}")
        self.setSubTitle("Fast, private, open-source backup directly to Cloudflare R2.")

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        banner = QFrame()
        banner.setObjectName("cardWidget")
        banner_layout = QVBoxLayout(banner)

        icon_label = QLabel("🛡️ Direct-to-Storage Cloudflare R2 Backup")
        icon_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        banner_layout.addWidget(icon_label)

        desc_text = (
            "r2sync backs up your critical files and folders directly to your personal "
            "Cloudflare R2 storage without developer intermediaries, cloud proxies, or fees.\n\n"
            "• Direct encrypted sync using Rclone\n"
            "• Credentials secured with Windows Credential Vault / DPAPI\n"
            "• Background service keeps schedules running even when GUI is closed"
        )
        desc = QLabel(desc_text)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #94A3B8; line-height: 1.5;")
        banner_layout.addWidget(desc)

        layout.addWidget(banner)
        layout.addStretch()


class R2AuthPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Connect Cloudflare R2")
        self.setSubTitle("Enter your Cloudflare R2 credentials to connect securely.")
        self._test_thread: Optional[ConnectionTestThread] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        instr_card = QFrame()
        instr_card.setObjectName("cardWidget")
        instr_layout = QVBoxLayout(instr_card)
        instr_title = QLabel("1-Minute Setup Guide:")
        instr_title.setStyleSheet("font-weight: bold; color: #38BDF8;")
        instr_layout.addWidget(instr_title)

        steps = QLabel(
            "1. Open the Cloudflare Dashboard\n"
            "2. Navigate to R2 > Manage R2 API Tokens > Create API Token\n"
            "3. Select 'Object Read & Write' permission and copy your keys"
        )
        steps.setStyleSheet("color: #CBD5E1; font-size: 12px;")
        instr_layout.addWidget(steps)

        btn_row = QHBoxLayout()
        open_cf_btn = QPushButton("🌐 Open Cloudflare R2 Tokens Page")
        open_cf_btn.setObjectName("secondaryBtn")
        open_cf_btn.clicked.connect(lambda: CloudflareR2Client.open_in_browser("https://dash.cloudflare.com/?to=/:account/r2/api-tokens"))
        btn_row.addWidget(open_cf_btn)
        btn_row.addStretch()
        instr_layout.addLayout(btn_row)

        layout.addWidget(instr_card)

        form_frame = QFrame()
        form_frame.setObjectName("cardWidget")
        form = QFormLayout(form_frame)
        form.setSpacing(10)

        self.account_id_input = QLineEdit()
        self.account_id_input.setPlaceholderText("e.g. 9b8c7d6e5f4a3b2c1d0e...")
        form.addRow("Cloudflare Account ID:", self.account_id_input)

        self.access_key_input = QLineEdit()
        self.access_key_input.setPlaceholderText("Access Key ID (e.g. 7f8a9b...)")
        form.addRow("Access Key ID:", self.access_key_input)

        self.secret_key_input = QLineEdit()
        self.secret_key_input.setEchoMode(QLineEdit.Password)
        self.secret_key_input.setPlaceholderText("Secret Access Key (e.g. 4d5e6f...)")
        form.addRow("Secret Access Key:", self.secret_key_input)

        self.test_btn = QPushButton("⚡ Test Connection")
        self.test_btn.setObjectName("secondaryBtn")
        self.test_btn.clicked.connect(self._run_connection_test)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        test_row = QHBoxLayout()
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.status_label)
        test_row.addStretch()
        form.addRow("", test_row)

        layout.addWidget(form_frame)

        self.registerField("account_id*", self.account_id_input)
        self.registerField("access_key*", self.access_key_input)
        self.registerField("secret_key*", self.secret_key_input)

    def _run_connection_test(self):
        acc = self.account_id_input.text().strip()
        ak = self.access_key_input.text().strip()
        sk = self.secret_key_input.text().strip()

        if not acc or not ak or not sk:
            self.status_label.setText("<font color='#EF4444'>Please fill in all 3 fields first.</font>")
            return

        self.test_btn.setEnabled(False)
        self.status_label.setText("<font color='#38BDF8'>Testing connection to Cloudflare R2...</font>")

        self._test_thread = ConnectionTestThread(acc, ak, sk)
        self._test_thread.result_ready.connect(self._on_test_result)
        self._test_thread.start()

    def _on_test_result(self, res: dict):
        self.test_btn.setEnabled(True)
        if res.get("success"):
            lat = res.get("latency_ms", 0)
            self.status_label.setText(f"<font color='#10B981'>✓ Connected successfully ({lat}ms)!</font>")
            self.wizard().discovered_buckets = res.get("buckets", [])
        else:
            err = res.get("error") or res.get("message") or "Unknown error"
            self.status_label.setText(f"<font color='#EF4444'>✗ Connection failed: {err[:80]}</font>")


class BucketSelectionPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Select or Create R2 Bucket")
        self.setSubTitle("Choose the Cloudflare R2 bucket where your backups will be stored.")

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("cardWidget")
        card_layout = QVBoxLayout(card)

        card_layout.addWidget(QLabel("Select an existing bucket or create a new one:"))

        self.bucket_combo = QComboBox()
        self.bucket_combo.setEditable(True)
        self.bucket_combo.setPlaceholderText("e.g. my-backup-bucket")
        card_layout.addWidget(self.bucket_combo)

        create_note = QLabel("Tip: If the bucket name does not exist yet, r2sync will create it automatically.")
        create_note.setStyleSheet("color: #94A3B8; font-size: 12px;")
        card_layout.addWidget(create_note)

        layout.addWidget(card)
        layout.addStretch()

        self.registerField("bucket_name*", self.bucket_combo, "currentText")

    def initializePage(self):
        buckets = getattr(self.wizard(), "discovered_buckets", [])
        self.bucket_combo.clear()
        if buckets:
            for b in buckets:
                self.bucket_combo.addItem(b)
        else:
            self.bucket_combo.addItem("r2sync-backups")


class FirstJobPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Create Your First Backup Job")
        self.setSubTitle("Choose a folder to start protecting right away.")

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("cardWidget")
        card_layout = QVBoxLayout(card)

        card_layout.addWidget(QLabel("Source Folder to Back Up:"))
        folder_row = QHBoxLayout()
        self.path_input = QLineEdit()
        default_docs = str(Path.home() / "Documents")
        self.path_input.setText(default_docs)
        folder_row.addWidget(self.path_input)

        browse_btn = QPushButton("📁 Browse...")
        browse_btn.setObjectName("secondaryBtn")
        browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(browse_btn)
        card_layout.addLayout(folder_row)

        presets_row = QHBoxLayout()
        presets_label = QLabel("Quick Presets:")
        presets_label.setStyleSheet("color: #94A3B8; font-size: 12px;")
        presets_row.addWidget(presets_label)

        for name, folder in [("Documents", "Documents"), ("Pictures", "Pictures"), ("Desktop", "Desktop")]:
            p = str(Path.home() / folder)
            btn = QPushButton(name)
            btn.setObjectName("secondaryBtn")
            btn.clicked.connect(lambda checked=False, path=p: self.path_input.setText(path))
            presets_row.addWidget(btn)
        presets_row.addStretch()
        card_layout.addLayout(presets_row)

        card_layout.addSpacing(10)
        card_layout.addWidget(QLabel("Backup Schedule:"))
        self.schedule_combo = QComboBox()
        self.schedule_combo.addItems([
            "Daily at 02:00 (Recommended)",
            "Every 1 Hour",
            "Every 4 Hours",
            "Manual only (On demand)",
        ])
        card_layout.addWidget(self.schedule_combo)

        layout.addWidget(card)
        layout.addStretch()

        self.registerField("source_path*", self.path_input)

    def _browse_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select Folder to Back Up", str(Path.home()))
        if chosen:
            self.path_input.setText(chosen)


class SetupWizard(QWizard):
    """Main Guided Setup Wizard."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.discovered_buckets = []

        self.setWindowTitle(f"{APP_DISPLAY_NAME} Setup Wizard")
        self.setWizardStyle(QWizard.ModernStyle)
        self.resize(650, 480)

        self.addPage(WelcomePage())
        self.addPage(R2AuthPage())
        self.addPage(BucketSelectionPage())
        self.addPage(FirstJobPage())

    def accept(self):
        account_id = self.field("account_id").strip()
        access_key = self.field("access_key").strip()
        secret_key = self.field("secret_key").strip()
        bucket_name = self.field("bucket_name").strip()
        source_path = self.field("source_path").strip()

        save_r2_credentials(
            account_id=account_id,
            access_key_id=access_key,
            secret_access_key=secret_key,
            default_bucket=bucket_name,
        )

        if source_path and os.path.exists(source_path):
            folder_name = Path(source_path).name or "Backup"
            first_job = BackupJob(
                name=f"{folder_name} Backup",
                source_path=source_path,
                bucket_name=bucket_name,
                remote_prefix=folder_name,
                schedule_type=JobScheduleType.DAILY.value,
                schedule_time_of_day="02:00",
                backup_mode=BackupMode.SYNC.value,
                enabled=True,
            )
            self.db.create_job(first_job)

        super().accept()
