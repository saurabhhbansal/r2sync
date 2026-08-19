"""Backups view displaying configured backup jobs and actions matching Stitch Design."""

from datetime import datetime
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
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
    """Card widget representing an individual backup job matching Stitch Backups design."""

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
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # -------------------------------------------------------------
        # Top Row: Checkbox/Folder Icon + Title + Status Badge + Actions
        # -------------------------------------------------------------
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # Enable/Disable toggle checkbox
        self.enable_cb = QCheckBox()
        self.enable_cb.setChecked(bool(self.job_data.get("enabled", True)))
        self.enable_cb.toggled.connect(lambda chk: self.toggle_clicked.emit(self.job_id, chk))
        top_row.addWidget(self.enable_cb)

        # Folder Icon in Brand Orange
        folder_icon = QLabel("📁")
        folder_icon.setStyleSheet("font-size: 18px;")
        top_row.addWidget(folder_icon)

        # Job Title
        title_lbl = QLabel(self.job_data.get("name", "Unnamed Job"))
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 600; color: #E1E2E8;")
        top_row.addWidget(title_lbl)

        # Status Badge Pill
        enabled = self.job_data.get("enabled", True)
        last_status = (self.job_data.get("last_status") or "Active").upper()

        status_lbl = QLabel()
        if not enabled:
            status_lbl.setText("● PAUSED")
            status_lbl.setStyleSheet("background-color: #272A2E; color: #A58C7D; border-radius: 10px; padding: 2px 8px; font-size: 11px; font-weight: 500;")
        elif last_status == "FAILED":
            status_lbl.setText("● FAILED")
            status_lbl.setStyleSheet("background-color: rgba(220, 38, 38, 0.15); color: #FFB4AB; border: 1px solid rgba(220, 38, 38, 0.4); border-radius: 10px; padding: 2px 8px; font-size: 11px; font-weight: 600;")
        else:
            status_lbl.setText("● ACTIVE")
            status_lbl.setStyleSheet("background-color: rgba(74, 225, 118, 0.12); color: #4AE176; border: 1px solid rgba(74, 225, 118, 0.3); border-radius: 10px; padding: 2px 8px; font-size: 11px; font-weight: 600;")
        top_row.addWidget(status_lbl)

        top_row.addStretch()

        # Action Buttons
        run_btn = QPushButton("▶ Run Now")
        run_btn.setObjectName("secondaryBtn")
        run_btn.setStyleSheet("padding: 5px 12px; font-size: 12px; font-weight: 500;")
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

        # -------------------------------------------------------------
        # Middle 2-Column Grid: Local Path & Remote Target
        # -------------------------------------------------------------
        paths_grid = QGridLayout()
        paths_grid.setSpacing(12)

        # Local Path Box
        src = self.job_data.get("source_path", "")
        loc_box = QFrame()
        loc_box.setObjectName("codeBoxWidget")
        loc_layout = QVBoxLayout(loc_box)
        loc_layout.setContentsMargins(8, 6, 8, 6)
        loc_layout.setSpacing(2)
        loc_title = QLabel("LOCAL PATH")
        loc_title.setStyleSheet("color: #A58C7D; font-size: 10px; font-weight: 600; letter-spacing: 0.04em;")
        loc_path = QLabel(src)
        loc_path.setStyleSheet("color: #E1E2E8; font-family: monospace; font-size: 12px;")
        loc_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        loc_layout.addWidget(loc_title)
        loc_layout.addWidget(loc_path)
        paths_grid.addWidget(loc_box, 0, 0)

        # Remote Target Box
        bkt = self.job_data.get("bucket_name", "")
        pfx = self.job_data.get("remote_prefix", "")
        dest = f"r2:{bkt}/{pfx}" if pfx else f"r2:{bkt}"

        rem_box = QFrame()
        rem_box.setObjectName("codeBoxWidget")
        rem_layout = QVBoxLayout(rem_box)
        rem_layout.setContentsMargins(8, 6, 8, 6)
        rem_layout.setSpacing(2)
        rem_title = QLabel("REMOTE DESTINATION")
        rem_title.setStyleSheet("color: #A58C7D; font-size: 10px; font-weight: 600; letter-spacing: 0.04em;")
        rem_path = QLabel(dest)
        rem_path.setStyleSheet("color: #FFB786; font-family: monospace; font-size: 12px;")
        rem_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rem_layout.addWidget(rem_title)
        rem_layout.addWidget(rem_path)
        paths_grid.addWidget(rem_box, 0, 1)

        layout.addLayout(paths_grid)

        # -------------------------------------------------------------
        # Footer Row: Schedule + Last Run + Transferred Meta
        # -------------------------------------------------------------
        meta_frame = QFrame()
        meta_frame.setStyleSheet("border-top: 1px solid #272A2E; padding-top: 8px;")
        meta_row = QHBoxLayout(meta_frame)
        meta_row.setContentsMargins(0, 4, 0, 0)
        meta_row.setSpacing(16)

        # Schedule
        sched_type = self.job_data.get("schedule_type", "daily").title()
        if self.job_data.get("schedule_type") == "daily":
            sched_type += f" at {self.job_data.get('schedule_time_of_day')}"
        elif self.job_data.get("schedule_type") == "interval":
            sched_type += f" (every {self.job_data.get('schedule_interval_minutes')}m)"

        sched_lbl = QLabel(f"⏰  {sched_type}")
        sched_lbl.setStyleSheet("color: #A58C7D; font-size: 12px;")
        meta_row.addWidget(sched_lbl)

        # Last Run
        last_run = self.job_data.get("last_run_at")
        if last_run:
            try:
                last_str = datetime.fromisoformat(last_run).strftime("%b %d, %H:%M")
            except Exception:
                last_str = last_run[:16]
            last_lbl = QLabel(f"📜  Last: {last_str} <font color='#4AE176'>✓ Completed</font>")
        else:
            last_lbl = QLabel("📜  Last: Never")
        last_lbl.setStyleSheet("color: #A58C7D; font-size: 12px;")
        meta_row.addWidget(last_lbl)

        meta_row.addStretch()

        # Mode Badge
        mode_badge = QLabel(f"Mode: {self.job_data.get('backup_mode', 'sync').upper()}")
        mode_badge.setStyleSheet("color: #FFB786; font-size: 11px; font-weight: 600;")
        meta_row.addWidget(mode_badge)

        layout.addWidget(meta_frame)


class JobsView(QWidget):
    """View managing all backup jobs matching Stitch Backups design."""

    create_job_requested = Signal()
    run_job_requested = Signal(int)
    edit_job_requested = Signal(int)
    delete_job_requested = Signal(int)
    toggle_job_requested = Signal(int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.jobs_list = []
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # -------------------------------------------------------------
        # Header with Stitch action buttons
        # -------------------------------------------------------------
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        title = QLabel("Backups")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Automatically protect folders to Cloudflare R2.")
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        run_all_btn = QPushButton("Run All")
        run_all_btn.setObjectName("secondaryBtn")
        run_all_btn.setStyleSheet("padding: 8px 16px; font-size: 13px;")
        run_all_btn.clicked.connect(self._run_all_jobs)
        header.addWidget(run_all_btn)

        add_btn = QPushButton("➕ Create Backup")
        add_btn.setStyleSheet("padding: 8px 16px; font-size: 13px; font-weight: 600;")
        add_btn.clicked.connect(self.create_job_requested.emit)
        header.addWidget(add_btn)

        main_layout.addLayout(header)

        # -------------------------------------------------------------
        # Scroll Area for Job Cards
        # -------------------------------------------------------------
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

    def _run_all_jobs(self):
        for j in self.jobs_list:
            if j.get("enabled", True) and j.get("id"):
                self.run_job_requested.emit(j.get("id"))

    def set_jobs(self, jobs: list):
        self.jobs_list = jobs or []

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
            el.setSpacing(10)

            lbl1 = QLabel("📁 No Backup Jobs Configured")
            lbl1.setStyleSheet("font-size: 16px; font-weight: 600; color: #E1E2E8;")
            lbl2 = QLabel("Create your first backup job to begin protecting your files to Cloudflare R2.")
            lbl2.setStyleSheet("color: #A58C7D; font-size: 13px;")
            btn = QPushButton("➕ Create First Backup")
            btn.setStyleSheet("padding: 8px 20px; font-size: 13px; font-weight: 600;")
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
