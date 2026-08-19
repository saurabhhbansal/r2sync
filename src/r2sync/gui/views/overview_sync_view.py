"""Unified Overview & Synchronization view combining Dashboard, Backups, and Multi-PC Sync."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from r2sync.gui.views.dashboard_view import BentoStatCard
from r2sync.gui.views.jobs_view import JobsView
from r2sync.gui.views.live_progress import LiveProgressWidget
from r2sync.gui.views.sync_view import SyncView


class OverviewSyncView(QWidget):
    """Consolidated main workspace uniting high-level metrics, Backup Jobs, and Multi-PC Sync datasets."""

    new_job_requested = Signal()
    backup_all_requested = Signal()
    run_job_requested = Signal(int)
    edit_job_requested = Signal(int)
    delete_job_requested = Signal(int)
    toggle_job_requested = Signal(int, bool)
    cancel_job_requested = Signal(int)

    add_sync_requested = Signal()
    setup_pc_requested = Signal()
    manage_computers_requested = Signal(str)
    open_conflicts_requested = Signal(str)
    sync_now_requested = Signal(str)
    pause_toggle_requested = Signal(str, bool)
    delete_dataset_requested = Signal(str)
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._connect_internal_signals()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # -------------------------------------------------------------
        # 1. Header Toolbar
        # -------------------------------------------------------------
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Overview & Sync")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Manage your automated cloud backups and shared Multi-PC folders")
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)

        # Quick Action Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)

        self.setup_pc_btn = QPushButton("🔗 Set Up This PC")
        self.setup_pc_btn.setObjectName("secondaryBtn")
        self.setup_pc_btn.clicked.connect(self.setup_pc_requested.emit)

        self.backup_all_btn = QPushButton("⚡ Backup All")
        self.backup_all_btn.setObjectName("secondaryBtn")
        self.backup_all_btn.clicked.connect(self.backup_all_requested.emit)

        self.add_sync_btn = QPushButton("+ Add Sync Folder")
        self.add_sync_btn.clicked.connect(self.add_sync_requested.emit)

        self.add_backup_btn = QPushButton("+ Add Backup")
        self.add_backup_btn.setStyleSheet("background-color: #272A2E; color: #E1E2E8; border: 1px solid #323539;")
        self.add_backup_btn.clicked.connect(self.new_job_requested.emit)

        btn_box.addWidget(self.setup_pc_btn)
        btn_box.addWidget(self.backup_all_btn)
        btn_box.addWidget(self.add_backup_btn)
        btn_box.addWidget(self.add_sync_btn)

        header.addLayout(btn_box)
        main_layout.addLayout(header)

        # -------------------------------------------------------------
        # 2. Bento Stat Cards Grid
        # -------------------------------------------------------------
        stats_grid = QGridLayout()
        stats_grid.setSpacing(12)

        self.card_storage = BentoStatCard("Cloud Storage", "0.0", "GB", "Cloudflare R2")
        self.card_backups = BentoStatCard("Backup Jobs", "0", "active", "Automated")
        self.card_sync = BentoStatCard("Sync Folders", "0", "shared", "Multi-PC")
        self.card_conflicts = BentoStatCard("File Conflicts", "0", "unresolved", "Auto-safe")

        stats_grid.addWidget(self.card_storage, 0, 0)
        stats_grid.addWidget(self.card_backups, 0, 1)
        stats_grid.addWidget(self.card_sync, 0, 2)
        stats_grid.addWidget(self.card_conflicts, 0, 3)
        main_layout.addLayout(stats_grid)

        # -------------------------------------------------------------
        # 3. Live Progress Banner
        # -------------------------------------------------------------
        self.live_progress = LiveProgressWidget()
        self.live_progress.cancel_requested.connect(self.cancel_job_requested.emit)
        main_layout.addWidget(self.live_progress)

        # -------------------------------------------------------------
        # 4. Segmented Tab Switcher (Backups | Multi-PC Sync)
        # -------------------------------------------------------------
        segment_bar = QFrame()
        segment_bar.setStyleSheet("""
            QFrame {
                background-color: #111418;
                border: 1px solid #272A2E;
                border-radius: 8px;
                padding: 4px;
            }
        """)
        seg_layout = QHBoxLayout(segment_bar)
        seg_layout.setContentsMargins(4, 4, 4, 4)
        seg_layout.setSpacing(6)

        self.seg_group = QButtonGroup(self)
        self.seg_group.setExclusive(True)

        self.tab_backups_btn = QPushButton("📁  Backup Jobs (0)")
        self.tab_backups_btn.setCheckable(True)
        self.tab_backups_btn.setChecked(True)
        self.tab_backups_btn.setStyleSheet(self._segment_button_style())

        self.tab_sync_btn = QPushButton("🔄  Multi-PC Sync (0)")
        self.tab_sync_btn.setCheckable(True)
        self.tab_sync_btn.setStyleSheet(self._segment_button_style())

        self.seg_group.addButton(self.tab_backups_btn, 0)
        self.seg_group.addButton(self.tab_sync_btn, 1)

        seg_layout.addWidget(self.tab_backups_btn)
        seg_layout.addWidget(self.tab_sync_btn)
        seg_layout.addStretch()

        main_layout.addWidget(segment_bar)

        # -------------------------------------------------------------
        # 5. Stacked Section (Jobs View & Sync View)
        # -------------------------------------------------------------
        self.inner_stack = QStackedWidget()

        self.view_jobs = JobsView()
        self.view_sync = SyncView()

        self.inner_stack.addWidget(self.view_jobs)
        self.inner_stack.addWidget(self.view_sync)

        self.tab_backups_btn.clicked.connect(lambda: self.inner_stack.setCurrentIndex(0))
        self.tab_sync_btn.clicked.connect(lambda: self.inner_stack.setCurrentIndex(1))

        main_layout.addWidget(self.inner_stack, stretch=1)

    def _segment_button_style(self) -> str:
        return """
            QPushButton {
                padding: 8px 18px;
                font-size: 13px;
                font-weight: 500;
                border-radius: 6px;
                background-color: transparent;
                border: 1px solid transparent;
                color: #A58C7D;
            }
            QPushButton:hover {
                background-color: #272A2E;
                color: #E1E2E8;
            }
            QPushButton:checked {
                background-color: #F6821F;
                color: #FFFFFF;
                font-weight: 600;
            }
        """

    def _connect_internal_signals(self):
        # JobsView signals
        self.view_jobs.create_job_requested.connect(self.new_job_requested.emit)
        self.view_jobs.run_job_requested.connect(self.run_job_requested.emit)
        self.view_jobs.edit_job_requested.connect(self.edit_job_requested.emit)
        self.view_jobs.delete_job_requested.connect(self.delete_job_requested.emit)
        self.view_jobs.toggle_job_requested.connect(self.toggle_job_requested.emit)

        # SyncView signals
        self.view_sync.add_sync_requested.connect(self.add_sync_requested.emit)
        self.view_sync.setup_pc_requested.connect(self.setup_pc_requested.emit)
        self.view_sync.manage_computers_requested.connect(self.manage_computers_requested.emit)
        self.view_sync.open_conflicts_requested.connect(self.open_conflicts_requested.emit)
        self.view_sync.sync_now_requested.connect(self.sync_now_requested.emit)
        self.view_sync.pause_toggle_requested.connect(self.pause_toggle_requested.emit)
        self.view_sync.delete_dataset_requested.connect(self.delete_dataset_requested.emit)
        self.view_sync.refresh_requested.connect(self.refresh_requested.emit)

    def update_stats(self, stats: dict):
        size_gb = stats.get("total_bytes_stored", 0) / (1024 ** 3)
        self.card_storage.set_value(f"{size_gb:.2f}")
        self.card_backups.set_value(str(stats.get("total_jobs", 0)))

    def update_jobs(self, jobs: list):
        self.tab_backups_btn.setText(f"📁  Backup Jobs ({len(jobs)})")
        self.view_jobs.set_jobs(jobs)

    def update_sync_data(self, datasets: list, devices: list, conflicts_count: int):
        self.tab_sync_btn.setText(f"🔄  Multi-PC Sync ({len(datasets)})")
        self.card_sync.set_value(str(len(datasets)))
        self.card_conflicts.set_value(str(conflicts_count))
        if conflicts_count > 0:
            self.card_conflicts.value_lbl.setStyleSheet("font-size: 26px; font-weight: 600; color: #FFB786;")
        else:
            self.card_conflicts.value_lbl.setStyleSheet("font-size: 26px; font-weight: 600; color: #E1E2E8;")
        self.view_sync.set_data(datasets, devices, conflicts_count)
