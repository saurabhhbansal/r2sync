"""Jobs view displaying configured backup jobs and control actions."""

from datetime import datetime
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from r2sync.core.models import BackupJob


class JobCardWidget(QFrame):
    """Card widget representing an individual backup job."""

    run_clicked = Signal(int)
    edit_clicked = Signal(int)
    delete_clicked = Signal(int)
    toggle_clicked = Signal(int, bool)

    def __init__(self, job_data: dict, parent=None):
        super().__init__(parent)
        self.job_data = job_data
        self.job_id = job_data.get("id", 0)
        self.setObjectName("cardWidget")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Top row: Checkbox/Title & Action Buttons
        top_row = QHBoxLayout()

        self.enable_cb = QCheckBox()
        self.enable_cb.setChecked(bool(self.job_data.get("enabled", True)))
        self.enable_cb.toggled.connect(lambda chk: self.toggle_clicked.emit(self.job_id, chk))
        top_row.addWidget(self.enable_cb)

        title_lbl = QLabel(self.job_data.get("name", "Unnamed Job"))
        title_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFFFF;")
        top_row.addWidget(title_lbl)

        # Status badge
        last_status = self.job_data.get("last_status") or "New"
        status_lbl = QLabel(f" {last_status.upper()} ")
        if last_status.lower() == "completed":
            status_lbl.setStyleSheet("background-color: #065F46; color: #34D399; border-radius: 4px; font-size: 11px; font-weight: bold;")
        elif last_status.lower() == "failed":
            status_lbl.setStyleSheet("background-color: #7F1D1D; color: #F87171; border-radius: 4px; font-size: 11px; font-weight: bold;")
        else:
            status_lbl.setStyleSheet("background-color: #1E293B; color: #94A3B8; border-radius: 4px; font-size: 11px;")
        top_row.addWidget(status_lbl)

        top_row.addStretch()

        # Actions
        run_btn = QPushButton("▶ Run Now")
        run_btn.setStyleSheet("padding: 5px 10px; font-size: 12px;")
        run_btn.clicked.connect(lambda: self.run_clicked.emit(self.job_id))
        top_row.addWidget(run_btn)

        edit_btn = QPushButton("✏ Edit")
        edit_btn.setObjectName("secondaryBtn")
        edit_btn.setStyleSheet("padding: 5px 10px; font-size: 12px;")
        edit_btn.clicked.connect(lambda: self.edit_clicked.emit(self.job_id))
        top_row.addWidget(edit_btn)

        del_btn = QPushButton("🗑")
        del_btn.setObjectName("dangerBtn")
        del_btn.setStyleSheet("padding: 5px 10px; font-size: 12px;")
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.job_id))
        top_row.addWidget(del_btn)

        layout.addLayout(top_row)

        # Middle row: Paths
        paths_row = QHBoxLayout()
        src = self.job_data.get("source_path", "")
        bkt = self.job_data.get("bucket_name", "")
        pfx = self.job_data.get("remote_prefix", "")
        dest = f"r2:{bkt}/{pfx}" if pfx else f"r2:{bkt}"

        path_text = QLabel(f"📁 <b>Source:</b> {src}  →  ☁️ <b>Target:</b> {dest}")
        path_text.setStyleSheet("color: #CBD5E1; font-size: 12px;")
        path_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        paths_row.addWidget(path_text)
        layout.addLayout(paths_row)

        # Bottom row: Schedule & Last Run
        meta_row = QHBoxLayout()
        sched_type = self.job_data.get("schedule_type", "daily").title()
        if self.job_data.get("schedule_type") == "daily":
            sched_type += f" at {self.job_data.get('schedule_time_of_day')}"
        elif self.job_data.get("schedule_type") == "interval":
            sched_type += f" (every {self.job_data.get('schedule_interval_minutes')}m)"

        last_run = self.job_data.get("last_run_at")
        if last_run:
            try:
                last_str = datetime.fromisoformat(last_run).strftime("%b %d, %H:%M")
            except Exception:
                last_str = last_run[:16]
        else:
            last_str = "Never"

        next_run = self.job_data.get("next_run_at")
        if next_run:
            try:
                next_str = datetime.fromisoformat(next_run).strftime("%b %d, %H:%M")
            except Exception:
                next_str = next_run[:16]
        else:
            next_str = "None"

        meta_text = QLabel(f"⏰ Schedule: <b>{sched_type}</b> | Last Run: <b>{last_str}</b> | Next Run: <b>{next_str}</b>")
        meta_text.setStyleSheet("color: #94A3B8; font-size: 11px;")
        meta_row.addWidget(meta_text)
        meta_row.addStretch()

        mode_badge = QLabel(f"Mode: {self.job_data.get('backup_mode', 'sync').upper()}")
        mode_badge.setStyleSheet("color: #38BDF8; font-size: 11px; font-weight: 500;")
        meta_row.addWidget(mode_badge)

        layout.addLayout(meta_row)


class JobsView(QWidget):
    """View managing all backup jobs."""

    create_job_requested = Signal()
    run_job_requested = Signal(int)
    edit_job_requested = Signal(int)
    delete_job_requested = Signal(int)
    toggle_job_requested = Signal(int, bool)

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
        title = QLabel("Backup Jobs")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Configure folders, sync schedules, and Cloudflare R2 destinations")
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        add_btn = QPushButton("➕ Add Backup Job")
        add_btn.clicked.connect(self.create_job_requested.emit)
        header.addWidget(add_btn)
        main_layout.addLayout(header)

        # Scroll Area for Job Cards
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setSpacing(12)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.addStretch()

        self.scroll.setWidget(self.cards_container)
        main_layout.addWidget(self.scroll)

    def set_jobs(self, jobs: list):
        # Clear existing cards
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not jobs:
            empty_frame = QFrame()
            empty_frame.setObjectName("cardWidget")
            el = QVBoxLayout(empty_frame)
            el.setAlignment(Qt.AlignCenter)
            el.setSpacing(8)

            lbl1 = QLabel("📁 No Backup Jobs Configured")
            lbl1.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF;")
            lbl2 = QLabel("Create your first backup job to begin protecting your files to Cloudflare R2.")
            lbl2.setStyleSheet("color: #94A3B8;")
            btn = QPushButton("➕ Create First Backup Job")
            btn.clicked.connect(self.create_job_requested.emit)

            el.addWidget(lbl1)
            el.addWidget(lbl2)
            el.addWidget(btn)
            self.cards_layout.insertWidget(0, empty_frame)
            return

        for idx, job in enumerate(jobs):
            card = JobCardWidget(job)
            card.run_clicked.connect(self.run_job_requested.emit)
            card.edit_clicked.connect(self.edit_job_requested.emit)
            card.delete_clicked.connect(self.delete_job_requested.emit)
            card.toggle_clicked.connect(self.toggle_job_requested.emit)
            self.cards_layout.insertWidget(idx, card)
