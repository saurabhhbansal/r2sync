"""Dashboard view showing overview stats, quick actions, and recent activities."""

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


class StatCard(QFrame):
    def __init__(self, title: str, initial_value: str = "0", subtitle: str = ""):
        super().__init__()
        self.setObjectName("cardWidget")
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("statTitleLabel")
        layout.addWidget(self.title_lbl)

        self.value_lbl = QLabel(initial_value)
        self.value_lbl.setObjectName("statValueLabel")
        layout.addWidget(self.value_lbl)

        self.sub_lbl = QLabel(subtitle)
        self.sub_lbl.setStyleSheet("color: #64748B; font-size: 11px;")
        layout.addWidget(self.sub_lbl)

    def set_value(self, val: str, sub: str = ""):
        self.value_lbl.setText(val)
        if sub:
            self.sub_lbl.setText(sub)


class DashboardView(QWidget):
    """Main overview dashboard widget."""

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
        main_layout.setSpacing(20)

        # Title & Status Header
        header_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Dashboard")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Overview of your Cloudflare R2 backups and schedules")
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box)
        header_row.addStretch()

        # Action Buttons
        self.backup_all_btn = QPushButton("⚡ Backup All Now")
        self.backup_all_btn.clicked.connect(self.backup_all_requested.emit)
        self.new_job_btn = QPushButton("➕ Add Job")
        self.new_job_btn.setObjectName("secondaryBtn")
        self.new_job_btn.clicked.connect(self.new_job_requested.emit)

        header_row.addWidget(self.backup_all_btn)
        header_row.addWidget(self.new_job_btn)
        main_layout.addLayout(header_row)

        # Live Progress Widget
        self.live_progress = LiveProgressWidget()
        self.live_progress.cancel_requested.connect(self.cancel_job_requested.emit)
        main_layout.addWidget(self.live_progress)

        # 4 Stats Cards Grid
        stats_grid = QGridLayout()
        stats_grid.setSpacing(14)

        self.card_jobs = StatCard("BACKUPS & SYNC", "0", "0 active")
        self.card_storage = StatCard("DATA STORED / TRANSFERRED", "0 MB", "To Cloudflare R2")
        self.card_files = StatCard("TOTAL FILES", "0", "Synchronized & Backed up")
        self.card_last_run = StatCard("LAST ACTIVITY", "Never", "Status: Idle")

        stats_grid.addWidget(self.card_jobs, 0, 0)
        stats_grid.addWidget(self.card_storage, 0, 1)
        stats_grid.addWidget(self.card_files, 0, 2)
        stats_grid.addWidget(self.card_last_run, 0, 3)
        main_layout.addLayout(stats_grid)


        # Upcoming Jobs & Recent Activity 2-column split
        lower_row = QHBoxLayout()
        lower_row.setSpacing(16)

        # Left: Upcoming Schedules
        upcoming_frame = QFrame()
        upcoming_frame.setObjectName("cardWidget")
        upcoming_layout = QVBoxLayout(upcoming_frame)
        upcoming_layout.setSpacing(10)

        up_title = QLabel("Upcoming Schedules")
        up_title.setStyleSheet("font-weight: bold; font-size: 14px; color: #FFFFFF;")
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

        # Right: Recent Activity Log
        activity_frame = QFrame()
        activity_frame.setObjectName("cardWidget")
        act_layout = QVBoxLayout(activity_frame)
        act_layout.setSpacing(10)

        act_header = QHBoxLayout()
        act_title = QLabel("Recent Activity")
        act_title.setStyleSheet("font-weight: bold; font-size: 14px; color: #FFFFFF;")
        act_header.addWidget(act_title)
        act_header.addStretch()

        view_hist_btn = QPushButton("View All History →")
        view_hist_btn.setObjectName("secondaryBtn")
        view_hist_btn.setStyleSheet("padding: 4px 8px; font-size: 11px;")
        view_hist_btn.clicked.connect(self.view_history_requested.emit)
        act_header.addWidget(view_hist_btn)
        act_layout.addLayout(act_header)

        self.activity_table = QTableWidget(0, 3)
        self.activity_table.setHorizontalHeaderLabels(["Time", "Level", "Event"])
        self.activity_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.activity_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.activity_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.activity_table.verticalHeader().setVisible(False)
        act_layout.addWidget(self.activity_table)

        lower_row.addWidget(activity_frame, stretch=1)
        main_layout.addLayout(lower_row)

    def update_stats(self, stats: dict):
        total_jobs = stats.get("total_jobs", 0)
        active_jobs = stats.get("active_jobs", 0)
        total_sync = stats.get("total_sync_datasets", 0)
        active_sync = stats.get("active_sync_datasets", 0)

        tot_all = total_jobs + total_sync
        act_all = active_jobs + active_sync
        self.card_jobs.set_value(f"{tot_all}", f"{act_all} active ({total_sync} sync, {total_jobs} backup)")

        bytes_done = (stats.get("total_bytes_transferred", 0) or 0) + (stats.get("total_sync_bytes", 0) or 0)
        if bytes_done > 1024 * 1024 * 1024:
            size_str = f"{round(bytes_done / (1024**3), 2)} GB"
        else:
            size_str = f"{round(bytes_done / (1024**2), 1)} MB"
        self.card_storage.set_value(size_str, "Cloudflare R2 Storage")

        total_files = (stats.get("total_files_transferred", 0) or 0) + (stats.get("total_sync_files", 0) or 0)
        conflicts = stats.get("unresolved_conflicts", 0)
        sub_str = f"⚠️ {conflicts} conflict(s)" if conflicts > 0 else "All synced & safe"
        self.card_files.set_value(f"{total_files:,}", sub_str)

        last_b = stats.get("last_backup_at")
        if last_b:
            try:
                dt = datetime.fromisoformat(last_b)
                time_str = dt.strftime("%b %d, %H:%M")
            except Exception:
                time_str = last_b[:16]
            self.card_last_run.set_value(time_str, "Protected")
        else:
            self.card_last_run.set_value("Ready", "Active & Protected")


    def update_jobs(self, jobs: list):
        self.jobs_table.setRowCount(len(jobs))
        for row, j in enumerate(jobs):
            name_item = QTableWidgetItem(j.get("name", ""))
            sched_str = j.get("schedule_type", "daily").title()
            if j.get("schedule_type") == "daily":
                sched_str += f" ({j.get('schedule_time_of_day')})"
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
