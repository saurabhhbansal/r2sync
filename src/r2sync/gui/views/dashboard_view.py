"""Dashboard Overview view matching Stitch R2Sync Pro Dark Design."""

from datetime import datetime
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from r2sync.gui.views.live_progress import LiveProgressWidget


class BentoStatCard(QFrame):
    """Clean bento stat card matching the Stitch Overview design."""

    def __init__(self, title: str, initial_value: str = "0", suffix: str = "", badge_text: str = ""):
        super().__init__()
        self.setObjectName("bentoCardWidget")
        self.setStyleSheet("""
            QFrame#bentoCardWidget {
                background-color: #111418;
                border: 1px solid #272A2E;
                border-radius: 8px;
                padding: 14px;
            }
            QFrame#bentoCardWidget:hover {
                background-color: #1D2024;
                border-color: #323539;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet("color: #A58C7D; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;")
        layout.addWidget(self.title_lbl)

        val_row = QHBoxLayout()
        val_row.setSpacing(6)

        self.value_lbl = QLabel(initial_value)
        self.value_lbl.setStyleSheet("font-size: 26px; font-weight: 600; color: #E1E2E8; letter-spacing: -0.02em;")
        val_row.addWidget(self.value_lbl)

        if suffix:
            self.suffix_lbl = QLabel(suffix)
            self.suffix_lbl.setStyleSheet("color: #A58C7D; font-size: 14px; font-weight: 400; margin-top: 6px;")
            val_row.addWidget(self.suffix_lbl)

        if badge_text:
            self.badge_lbl = QLabel(f"● {badge_text}")
            self.badge_lbl.setStyleSheet("color: #4AE176; font-size: 11px; font-weight: 500; margin-top: 6px;")
            val_row.addWidget(self.badge_lbl)
        else:
            self.badge_lbl = None

        val_row.addStretch()
        layout.addLayout(val_row)

    def set_value(self, val: str, suffix: str = "", badge_text: str = "", badge_color: str = "#4AE176"):
        self.value_lbl.setText(val)
        if hasattr(self, "suffix_lbl") and suffix:
            self.suffix_lbl.setText(suffix)
        if self.badge_lbl and badge_text:
            self.badge_lbl.setText(f"● {badge_text}")
            self.badge_lbl.setStyleSheet(f"color: {badge_color}; font-size: 11px; font-weight: 500; margin-top: 6px;")


class DashboardView(QWidget):
    """Main overview dashboard widget matching Stitch Design."""

    new_job_requested = Signal()
    backup_all_requested = Signal()
    view_history_requested = Signal()
    cancel_job_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # Scroll Area for clean overflow
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        # -------------------------------------------------------------
        # Page Title & Actions
        # -------------------------------------------------------------
        header_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        title = QLabel("Overview")
        title.setObjectName("titleLabel")
        title_box.addWidget(title)

        header_row.addLayout(title_box)
        header_row.addStretch()

        layout.addLayout(header_row)

        # -------------------------------------------------------------
        # Live Progress Widget (Appears during active sync/backup)
        # -------------------------------------------------------------
        self.live_progress = LiveProgressWidget()
        self.live_progress.cancel_requested.connect(self.cancel_job_requested.emit)
        layout.addWidget(self.live_progress)

        # -------------------------------------------------------------
        # Health Hero Card (Stitch Component)
        # -------------------------------------------------------------
        self.hero_card = QFrame()
        self.hero_card.setObjectName("heroCardWidget")
        self.hero_card.setStyleSheet("""
            QFrame#heroCardWidget {
                background-color: #1D2024;
                border: 1px solid #272A2E;
                border-radius: 12px;
                padding: 18px 20px;
            }
        """)
        hero_layout = QHBoxLayout(self.hero_card)
        hero_layout.setSpacing(16)

        # Status Icon Badge
        self.hero_icon = QLabel("●")
        self.hero_icon.setAlignment(Qt.AlignCenter)
        self.hero_icon.setFixedSize(42, 42)
        self.hero_icon.setStyleSheet("""
            background-color: rgba(74, 225, 118, 0.12);
            color: #4AE176;
            border: 1px solid rgba(74, 225, 118, 0.3);
            border-radius: 21px;
            font-size: 20px;
            font-weight: bold;
        """)
        hero_layout.addWidget(self.hero_icon)

        # Text Info
        hero_text_box = QVBoxLayout()
        hero_text_box.setSpacing(4)
        self.hero_title = QLabel("Everything is up to date")
        self.hero_title.setStyleSheet("font-size: 18px; font-weight: 600; color: #E1E2E8;")
        self.hero_subtitle = QLabel("0 backup jobs, 0 sync datasets. All files secured to Cloudflare R2.")
        self.hero_subtitle.setStyleSheet("color: #A58C7D; font-size: 13px;")
        hero_text_box.addWidget(self.hero_title)
        hero_text_box.addWidget(self.hero_subtitle)
        hero_layout.addLayout(hero_text_box)
        hero_layout.addStretch()

        # Action Buttons in Hero
        self.hero_sync_btn = QPushButton("Sync Now")
        self.hero_sync_btn.setObjectName("secondaryBtn")
        self.hero_sync_btn.setStyleSheet("padding: 8px 16px; font-size: 13px;")
        self.hero_sync_btn.clicked.connect(self.backup_all_requested.emit)
        hero_layout.addWidget(self.hero_sync_btn)

        self.hero_add_btn = QPushButton("+ Add Backup")
        self.hero_add_btn.setStyleSheet("padding: 8px 16px; font-size: 13px;")
        self.hero_add_btn.clicked.connect(self.new_job_requested.emit)
        hero_layout.addWidget(self.hero_add_btn)

        layout.addWidget(self.hero_card)

        # -------------------------------------------------------------
        # 5-Metric Bento Grid (Stitch Layout)
        # -------------------------------------------------------------
        stats_grid = QGridLayout()
        stats_grid.setSpacing(12)

        self.bento_protected = BentoStatCard("Protected", "0", "MB")
        self.bento_backups = BentoStatCard("Backups", "0", "", "0 active")
        self.bento_sync = BentoStatCard("Sync Datasets", "0")
        self.bento_devices = BentoStatCard("Devices", "1", "", "Online")
        self.bento_r2 = BentoStatCard("R2 Storage", "0", "MB")

        stats_grid.addWidget(self.bento_protected, 0, 0)
        stats_grid.addWidget(self.bento_backups, 0, 1)
        stats_grid.addWidget(self.bento_sync, 0, 2)
        stats_grid.addWidget(self.bento_devices, 0, 3)
        stats_grid.addWidget(self.bento_r2, 0, 4)

        layout.addLayout(stats_grid)

        # -------------------------------------------------------------
        # Split Section: Recent Activity Timeline & Upcoming Schedules
        # -------------------------------------------------------------
        lower_row = QHBoxLayout()
        lower_row.setSpacing(16)

        # Left: Recent Activity Timeline
        activity_frame = QFrame()
        activity_frame.setObjectName("cardWidget")
        act_layout = QVBoxLayout(activity_frame)
        act_layout.setSpacing(12)

        act_header = QHBoxLayout()
        act_title = QLabel("Recent Activity")
        act_title.setObjectName("sectionTitleLabel")
        act_header.addWidget(act_title)
        act_header.addStretch()

        view_hist_btn = QPushButton("View All Activity →")
        view_hist_btn.setObjectName("secondaryBtn")
        view_hist_btn.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        view_hist_btn.clicked.connect(self.view_history_requested.emit)
        act_header.addWidget(view_hist_btn)
        act_layout.addLayout(act_header)

        self.activity_table = QTableWidget(0, 3)
        self.activity_table.setHorizontalHeaderLabels(["Time", "Level", "Event"])
        self.activity_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.activity_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.activity_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.activity_table.verticalHeader().setVisible(False)
        self.activity_table.setSelectionBehavior(QTableWidget.SelectRows)
        act_layout.addWidget(self.activity_table)

        lower_row.addWidget(activity_frame, stretch=1)

        # Right: Upcoming Schedules
        upcoming_frame = QFrame()
        upcoming_frame.setObjectName("cardWidget")
        upcoming_layout = QVBoxLayout(upcoming_frame)
        upcoming_layout.setSpacing(12)

        up_title = QLabel("Upcoming Schedules")
        up_title.setObjectName("sectionTitleLabel")
        upcoming_layout.addWidget(up_title)

        self.jobs_table = QTableWidget(0, 3)
        self.jobs_table.setHorizontalHeaderLabels(["Job Name", "Schedule", "Next Run"])
        self.jobs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.jobs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.jobs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.jobs_table.verticalHeader().setVisible(False)
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectRows)
        upcoming_layout.addWidget(self.jobs_table)

        lower_row.addWidget(upcoming_frame, stretch=1)

        layout.addLayout(lower_row)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def update_stats(self, stats: dict):
        total_jobs = stats.get("total_jobs", 0)
        active_jobs = stats.get("active_jobs", 0)
        total_sync = stats.get("total_sync_datasets", 0)
        active_sync = stats.get("active_sync_datasets", 0)
        unresolved_conflicts = stats.get("unresolved_conflicts", 0)

        # Format Data Sizes
        bytes_done = (stats.get("total_bytes_transferred", 0) or 0) + (stats.get("total_sync_bytes", 0) or 0)
        if bytes_done > 1024 * 1024 * 1024:
            prot_val = f"{round(bytes_done / (1024**3), 1)}"
            prot_suf = "GB"
        elif bytes_done > 1024 * 1024:
            prot_val = f"{round(bytes_done / (1024**2), 1)}"
            prot_suf = "MB"
        else:
            prot_val = f"{round(bytes_done / 1024, 0)}"
            prot_suf = "KB"

        self.bento_protected.set_value(prot_val, prot_suf)
        self.bento_backups.set_value(str(total_jobs), badge_text=f"{active_jobs} active")
        self.bento_sync.set_value(str(total_sync))

        # Hero subtitle
        last_b = stats.get("last_backup_at")
        if last_b:
            try:
                dt = datetime.fromisoformat(last_b)
                time_str = dt.strftime("%b %d, %H:%M")
            except Exception:
                time_str = last_b[:16]
            activity_text = f"Last activity: {time_str}."
        else:
            activity_text = "Ready to back up."

        if unresolved_conflicts > 0:
            self.hero_icon.setText("●")
            self.hero_icon.setStyleSheet("""
                background-color: rgba(246, 130, 31, 0.15);
                color: #F6821F;
                border: 1px solid rgba(246, 130, 31, 0.4);
                border-radius: 21px;
                font-size: 20px;
            """)
            self.hero_title.setText("Conflicts Detected")
            self.hero_subtitle.setText(f"{unresolved_conflicts} unresolved conflict(s) require review. {total_jobs} jobs, {total_sync} sync folders.")
        else:
            self.hero_icon.setText("●")
            self.hero_icon.setStyleSheet("""
                background-color: rgba(74, 225, 118, 0.12);
                color: #4AE176;
                border: 1px solid rgba(74, 225, 118, 0.3);
                border-radius: 21px;
                font-size: 20px;
                font-weight: bold;
            """)
            self.hero_title.setText("Everything is up to date")
            self.hero_subtitle.setText(f"{total_jobs} backup job(s), {total_sync} sync folder(s). {activity_text}")

        # Update R2 storage metric
        self.bento_r2.set_value(prot_val, prot_suf)

    def update_jobs(self, jobs: list):
        self.jobs_table.setRowCount(len(jobs))
        for row, j in enumerate(jobs):
            name_item = QTableWidgetItem(j.get("name", ""))
            sched_str = j.get("schedule_type", "daily").title()
            if j.get("schedule_type") == "daily":
                sched_str += f" ({j.get('schedule_time_of_day')})"
            elif j.get("schedule_type") == "interval":
                sched_str += f" ({j.get('schedule_interval_minutes')}m)"
            sched_item = QTableWidgetItem(sched_str)

            next_run = j.get("next_run_at")
            if next_run:
                try:
                    next_str = datetime.fromisoformat(next_run).strftime("%b %d, %H:%M")
                except Exception:
                    next_str = next_run[:16]
            else:
                next_str = "Manual / Paused"
            next_item = QTableWidgetItem(next_str)

            self.jobs_table.setItem(row, 0, name_item)
            self.jobs_table.setItem(row, 1, sched_item)
            self.jobs_table.setItem(row, 2, next_item)

    def update_activities(self, logs: list):
        self.activity_table.setRowCount(len(logs))
        for row, l in enumerate(logs):
            time_str = l.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(time_str)
                time_str = dt.strftime("%H:%M:%S")
            except Exception:
                time_str = time_str[11:19]

            lvl = l.get("level", "INFO")
            msg = l.get("message", "")

            t_item = QTableWidgetItem(time_str)
            l_item = QTableWidgetItem(lvl)
            if lvl == "ERROR":
                l_item.setForeground(Qt.red)
            elif lvl == "WARNING":
                l_item.setForeground(Qt.yellow)
            else:
                l_item.setForeground(Qt.cyan)

            m_item = QTableWidgetItem(msg)

            self.activity_table.setItem(row, 0, t_item)
            self.activity_table.setItem(row, 1, l_item)
            self.activity_table.setItem(row, 2, m_item)
