"""Cloudflare R2 Storage management and dashboard links view."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from r2sync.core.credentials import get_r2_credentials
from r2sync.core.r2_client import CloudflareR2Client


class CreateBucketDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Cloudflare R2 Bucket")
        self.resize(400, 160)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Enter bucket name (lowercase letters, numbers, hyphens):"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. my-app-backups")
        layout.addWidget(self.name_input)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        create_btn = QPushButton("Create Bucket")
        create_btn.clicked.connect(self._validate)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(create_btn)
        layout.addLayout(btn_row)

    def _validate(self):
        name = self.name_input.text().strip().lower()
        if not name or len(name) < 3:
            QMessageBox.warning(self, "Invalid Name", "Bucket name must be at least 3 characters.")
            return
        self.bucket_name = name
        self.accept()


class StorageView(QWidget):
    """View displaying Cloudflare R2 buckets, usage stats, and dashboard shortcuts."""

    refresh_requested = Signal()
    create_bucket_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Cloudflare R2 Storage")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Manage buckets, check storage usage, and access Cloudflare dashboard")
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        create_btn = QPushButton("➕ Create Bucket")
        create_btn.clicked.connect(self._open_create_bucket)
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setObjectName("secondaryBtn")
        refresh_btn.clicked.connect(self.refresh_requested.emit)

        header.addWidget(create_btn)
        header.addWidget(refresh_btn)
        main_layout.addLayout(header)

        # Account Info Card
        acc_frame = QFrame()
        acc_frame.setObjectName("cardWidget")
        acc_layout = QHBoxLayout(acc_frame)

        self.acc_label = QLabel("<b>Cloudflare Account:</b> Not configured")
        self.acc_label.setStyleSheet("color: #CBD5E1;")
        acc_layout.addWidget(self.acc_label)
        acc_layout.addStretch()

        # Cloudflare official link buttons
        dash_btn = QPushButton("🌐 Open Cloudflare R2")
        dash_btn.setObjectName("secondaryBtn")
        dash_btn.clicked.connect(self._open_cf_dashboard)
        acc_layout.addWidget(dash_btn)

        tokens_btn = QPushButton("🔑 API Tokens")
        tokens_btn.setObjectName("secondaryBtn")
        tokens_btn.clicked.connect(self._open_cf_tokens)
        acc_layout.addWidget(tokens_btn)

        billing_btn = QPushButton("💳 Billing & Usage")
        billing_btn.setObjectName("secondaryBtn")
        billing_btn.clicked.connect(self._open_cf_billing)
        acc_layout.addWidget(billing_btn)

        main_layout.addWidget(acc_frame)

        # Buckets Table Frame
        table_frame = QFrame()
        table_frame.setObjectName("cardWidget")
        t_layout = QVBoxLayout(table_frame)
        t_layout.addWidget(QLabel("<b>Your R2 Buckets:</b>"))

        self.buckets_table = QTableWidget(0, 4)
        self.buckets_table.setHorizontalHeaderLabels(["Bucket Name", "Region", "Objects", "Storage Used"])
        self.buckets_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.buckets_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.buckets_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.buckets_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.buckets_table.verticalHeader().setVisible(False)
        self.buckets_table.setSelectionBehavior(QTableWidget.SelectRows)
        t_layout.addWidget(self.buckets_table)

        main_layout.addWidget(table_frame)

        # Storage Cost & Cloudflare Pricing Visibility Card
        cost_frame = QFrame()
        cost_frame.setObjectName("cardWidget")
        cost_layout = QVBoxLayout(cost_frame)
        cost_layout.setSpacing(8)

        cost_title = QLabel("💰 Cloudflare R2 Storage & Cost Estimation")
        cost_title.setStyleSheet("font-weight: bold; color: #FFFFFF; font-size: 14px;")
        cost_layout.addWidget(cost_title)

        self.cost_calc_lbl = QLabel("Estimated Storage: <b>0 GB</b> | Estimated Monthly Cost: <b>$0.00 / month</b> (Within Free Tier)")
        self.cost_calc_lbl.setStyleSheet("color: #38BDF8; font-size: 13px;")
        cost_layout.addWidget(self.cost_calc_lbl)

        pricing_notes = QLabel(
            "• <b>Free Tier:</b> First 10 GB-months of storage are 100% free every month.<br>"
            "• <b>Standard Rate:</b> $0.015 per GB-month for storage beyond the free tier.<br>"
            "• <b>Egress Fees:</b> $0 (Zero egress / bandwidth fees on Cloudflare R2).<br>"
            "• <i>Note: Estimates are approximations. Class A/B API operations and taxes may apply according to Cloudflare's billing policy.</i>"
        )
        pricing_notes.setStyleSheet("color: #94A3B8; font-size: 11px; line-height: 1.4;")
        cost_layout.addWidget(pricing_notes)

        cost_link_btn = QPushButton("🌐 View Official Cloudflare R2 Pricing Details ↗")
        cost_link_btn.setObjectName("secondaryBtn")
        cost_link_btn.setStyleSheet("padding: 4px 8px; font-size: 11px;")
        cost_link_btn.clicked.connect(lambda: CloudflareR2Client.open_in_browser("https://developers.cloudflare.com/r2/pricing/"))
        cost_layout.addWidget(cost_link_btn)

        main_layout.addWidget(cost_frame)


    def set_account_id(self, account_id: str):
        if account_id:
            masked_acc = f"{account_id[:6]}••••••••{account_id[-4:]}" if len(account_id) > 10 else account_id
            self.acc_label.setText(f"<font color='#10B981'>● Connected</font> | <b>Account ID:</b> {masked_acc}  |  <b>Endpoint:</b> {account_id}.r2.cloudflarestorage.com")
        else:
            self.acc_label.setText("<font color='#94A3B8'>● Not Connected</font> | <b>Cloudflare Account:</b> Not configured in Settings")

    def set_buckets(self, buckets: list):
        self.buckets_table.setRowCount(len(buckets))
        total_storage_bytes = 0

        for row, b in enumerate(buckets):
            name_item = QTableWidgetItem(b.get("name", ""))
            loc_item = QTableWidgetItem(b.get("location", "auto"))

            cnt = b.get("object_count")
            cnt_str = f"{cnt:,}" if cnt is not None else "—"
            cnt_item = QTableWidgetItem(cnt_str)

            sz = b.get("size_bytes") or 0
            total_storage_bytes += sz
            if sz > 0:
                if sz > 1024**3:
                    sz_str = f"{round(sz / (1024**3), 2)} GB"
                else:
                    sz_str = f"{round(sz / (1024**2), 1)} MB"
            else:
                sz_str = "—"
            sz_item = QTableWidgetItem(sz_str)

            self.buckets_table.setItem(row, 0, name_item)
            self.buckets_table.setItem(row, 1, loc_item)
            self.buckets_table.setItem(row, 2, cnt_item)
            self.buckets_table.setItem(row, 3, sz_item)

        total_gb = total_storage_bytes / (1024**3)
        billable_gb = max(0.0, total_gb - 10.0)
        est_cost = billable_gb * 0.015
        if billable_gb <= 0:
            self.cost_calc_lbl.setText(
                f"Estimated Storage: <b>{round(total_gb, 2)} GB</b> | Estimated Monthly Cost: <b>$0.00 / month</b> (Within Free Tier)"
            )
        else:
            self.cost_calc_lbl.setText(
                f"Estimated Storage: <b>{round(total_gb, 2)} GB</b> | Estimated Monthly Cost: <b>${est_cost:.2f} / month</b>"
            )


    def _open_create_bucket(self):
        dlg = CreateBucketDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.create_bucket_requested.emit(dlg.bucket_name)

    def _open_cf_dashboard(self):
        creds = get_r2_credentials()
        acc = creds.account_id if creds else None
        CloudflareR2Client.open_in_browser(CloudflareR2Client.get_dashboard_url(acc))

    def _open_cf_tokens(self):
        creds = get_r2_credentials()
        acc = creds.account_id if creds else None
        CloudflareR2Client.open_in_browser(CloudflareR2Client.get_api_tokens_url(acc))

    def _open_cf_billing(self):
        creds = get_r2_credentials()
        acc = creds.account_id if creds else None
        CloudflareR2Client.open_in_browser(CloudflareR2Client.get_billing_url(acc))
