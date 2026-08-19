"""Main Window and Application Controller for r2sync GUI matching Stitch Design."""

import logging
import sys
from typing import Optional

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from r2sync.client.ipc_client import IPCClient
from r2sync.config import APP_DISPLAY_NAME, APP_VERSION
from r2sync.core.credentials import get_r2_credentials, has_r2_credentials
from r2sync.core.db import Database
from r2sync.core.models import BackupJob, SyncDataset
from r2sync.gui.styles.theme import apply_theme
from r2sync.gui.tray import SystemTrayManager
from r2sync.utils.paths import get_asset_path
from r2sync.gui.views.add_sync_dialog import AddSyncDialog
from r2sync.gui.views.conflict_dialog import ConflictCenterDialog
from r2sync.gui.views.history_view import HistoryView
from r2sync.gui.views.job_edit_dialog import JobEditDialog
from r2sync.gui.views.manage_devices_dialog import ManageDevicesDialog
from r2sync.gui.views.overview_sync_view import OverviewSyncView
from r2sync.gui.views.settings_view import SettingsView
from r2sync.gui.views.setup_pc_dialog import SetupPCDialog
from r2sync.gui.views.storage_view import StorageView
from r2sync.gui.wizard.setup_wizard import SetupWizard


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Primary application window matching Stitch Design."""

    def __init__(self, ipc_client: IPCClient, db: Database):
        super().__init__()
        self.ipc = ipc_client
        self.db = db

        self.internal_backup_engine = None
        self.internal_sync_engine = None
        self.internal_scheduler = None

        self.setWindowTitle("r2sync")
        self.resize(1050, 700)
        self.setMinimumSize(900, 580)

        icon_path = get_asset_path("icon.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._init_ui()
        self._setup_tray()
        self._setup_engine()
        self._setup_timers()
        self._connect_signals()

        # Check first run / credentials
        if not has_r2_credentials():
            QTimer.singleShot(200, self._launch_setup_wizard)
        else:
            self.refresh_all_data()

    def _setup_engine(self):
        """Setup internal execution engines and scheduler when running in desktop mode."""
        if not self.ipc.is_service_running():
            logger.info("Initializing integrated desktop scheduler and sync watchers...")
            from r2sync.notifications.notifier import NotificationManager
            from r2sync.core.backup_engine import BackupEngine
            from r2sync.core.sync_engine import SyncEngine
            from r2sync.core.scheduler import JobScheduler
            from r2sync.core.rclone_engine import RcloneEngine

            rclone_eng = RcloneEngine()
            notifier = NotificationManager()

            self.internal_backup_engine = BackupEngine(
                db=self.db,
                rclone_engine=rclone_eng,
                notifier=notifier,
            )
            self.internal_sync_engine = SyncEngine(
                db=self.db,
                rclone_engine=rclone_eng,
                notifier=notifier,
            )

            # Connect internal engine callbacks to GUI progress methods
            self.internal_backup_engine.add_progress_listener(
                lambda p: self._on_ipc_progress(p.to_dict() if hasattr(p, "to_dict") else p.__dict__)
            )
            self.internal_backup_engine.add_completion_listener(
                lambda r: self._on_ipc_completed(r.to_dict() if hasattr(r, "to_dict") else r.__dict__)
            )
            self.internal_sync_engine.add_progress_listener(
                lambda p: self._on_sync_progress(p.to_dict() if hasattr(p, "to_dict") else p.__dict__)
            )
            self.internal_sync_engine.add_completion_listener(
                lambda ds, res: self._on_sync_completed(res)
            )

            self.internal_scheduler = JobScheduler(
                db=self.db,
                job_runner_cb=lambda j: self.internal_backup_engine.trigger_job_async(j),
                sync_runner_cb=lambda ds_id: self.internal_sync_engine.trigger_sync_async(ds_id),
                heartbeat_cb=self._on_heartbeat_tick,
            )
            self.internal_scheduler.start()

            # Start realtime file watchers
            self.internal_sync_engine.start_all_watchers()

    def _on_heartbeat_tick(self):
        datasets = self.db.list_sync_datasets()
        dev_id = self.db.get_or_create_device_id()
        for d in datasets:
            if d.enabled:
                self.db.update_device_heartbeat(dev_id, d.dataset_id, "online")

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # -------------------------------------------------------------
        # Left Navigation Sidebar (Stitch Sidebar)
        # -------------------------------------------------------------
        sidebar = QFrame()
        sidebar.setObjectName("sidebarWidget")
        sidebar.setFixedWidth(240)
        sidebar.setStyleSheet("""
            QFrame#sidebarWidget {
                background-color: #191C20;
                border-right: 1px solid #272A2E;
            }
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 20, 16, 16)
        sidebar_layout.setSpacing(6)

        # App Brand Header
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)

        brand_logo = QLabel()
        icon_path = get_asset_path("icon.png")
        if icon_path.exists():
            pix = QPixmap(str(icon_path)).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            brand_logo.setPixmap(pix)
        else:
            brand_logo.setText("[R2]")
            brand_logo.setStyleSheet("font-size: 14px; font-weight: bold; color: #F6821F;")

        brand_title_box = QVBoxLayout()
        brand_title_box.setSpacing(0)
        brand_title = QLabel("r2sync")
        brand_title.setStyleSheet("font-size: 19px; font-weight: 700; color: #F6821F; letter-spacing: -0.02em;")
        brand_ver = QLabel(f"v{APP_VERSION}")
        brand_ver.setStyleSheet("color: #A58C7D; font-size: 11px;")
        brand_title_box.addWidget(brand_title)
        brand_title_box.addWidget(brand_ver)

        brand_row.addWidget(brand_logo)
        brand_row.addLayout(brand_title_box)
        brand_row.addStretch()
        sidebar_layout.addLayout(brand_row)

        sidebar_layout.addSpacing(16)

        # Consolidated 4 Nav Workspaces (Overview & Sync, Activity, Storage, Settings)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.btn_nav_overview = self._create_nav_button("Overview & Sync", 0)
        self.btn_nav_history = self._create_nav_button("Activity", 1)
        self.btn_nav_storage = self._create_nav_button("Storage", 2)
        self.btn_nav_settings = self._create_nav_button("Settings", 3)

        sidebar_layout.addWidget(self.btn_nav_overview)
        sidebar_layout.addWidget(self.btn_nav_history)
        sidebar_layout.addWidget(self.btn_nav_storage)
        sidebar_layout.addWidget(self.btn_nav_settings)
        sidebar_layout.addStretch()

        # System Status Indicator at bottom of sidebar
        status_frame = QFrame()
        status_frame.setStyleSheet("border-top: 1px solid #272A2E; padding-top: 12px;")
        sf_layout = QHBoxLayout(status_frame)
        sf_layout.setContentsMargins(0, 0, 0, 0)
        sf_layout.setSpacing(6)

        self.svc_badge = QLabel("● All systems operational")
        self.svc_badge.setStyleSheet("color: #4AE176; font-size: 12px; font-weight: 500;")
        sf_layout.addWidget(self.svc_badge)
        sidebar_layout.addWidget(status_frame)

        root_layout.addWidget(sidebar)

        # -------------------------------------------------------------
        # Right Stacked Content Views (4 Consolidated Workspaces)
        # -------------------------------------------------------------
        self.stack = QStackedWidget()

        self.view_overview = OverviewSyncView()
        self.view_history = HistoryView()
        self.view_storage = StorageView()
        self.view_settings = SettingsView()

        self.stack.addWidget(self.view_overview)
        self.stack.addWidget(self.view_history)
        self.stack.addWidget(self.view_storage)
        self.stack.addWidget(self.view_settings)

        root_layout.addWidget(self.stack, stretch=1)

        self.btn_nav_overview.setChecked(True)

    def _create_nav_button(self, text: str, view_index: int) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setObjectName("secondaryBtn")
        btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 10px 14px;
                font-size: 13px;
                border-radius: 8px;
                background-color: transparent;
                border: 1px solid transparent;
                color: #A58C7D;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #272A2E;
                color: #E1E2E8;
            }
            QPushButton:checked {
                background-color: #272A2E;
                color: #FFB786;
                font-weight: 600;
                border-right: 3px solid #F6821F;
            }
        """)

        def on_nav_clicked():
            self.stack.setCurrentIndex(view_index)
            if view_index == 2:
                self._refresh_storage()

        btn.clicked.connect(on_nav_clicked)
        self.nav_group.addButton(btn, view_index)
        return btn

    def _setup_tray(self):
        self.tray = SystemTrayManager(self)
        self.tray.open_window_requested.connect(self._show_and_raise)
        self.tray.backup_all_requested.connect(self._on_backup_all)
        self.tray.quit_requested.connect(self._on_force_quit)
        self.tray.show()

    def _setup_timers(self):
        # Periodic data refresher (every 5 seconds)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_all_data)
        self.refresh_timer.start(5000)

        # Connect IPC event streaming
        self.ipc.add_event_listener("job_progress", self._on_ipc_progress)
        self.ipc.add_event_listener("job_completed", self._on_ipc_completed)
        self.ipc.add_event_listener("sync_progress", self._on_sync_progress)
        self.ipc.add_event_listener("sync_completed", self._on_sync_completed)

    def _connect_signals(self):
        # Overview & Sync signals
        self.view_overview.new_job_requested.connect(self._open_new_job_dialog)
        self.view_overview.backup_all_requested.connect(self._on_backup_all)
        self.view_overview.run_job_requested.connect(self._on_run_job)
        self.view_overview.edit_job_requested.connect(self._open_edit_job_dialog)
        self.view_overview.delete_job_requested.connect(self._on_delete_job)
        self.view_overview.toggle_job_requested.connect(self._on_toggle_job)
        self.view_overview.cancel_job_requested.connect(self._on_cancel_job)

        self.view_overview.add_sync_requested.connect(self._open_add_sync_dialog)
        self.view_overview.setup_pc_requested.connect(self._open_setup_pc_dialog)
        self.view_overview.manage_computers_requested.connect(self._open_manage_computers_dialog)
        self.view_overview.open_conflicts_requested.connect(self._open_conflicts_dialog)
        self.view_overview.sync_now_requested.connect(self._on_sync_dataset_now)
        self.view_overview.pause_toggle_requested.connect(self._on_pause_toggle_sync)
        self.view_overview.delete_dataset_requested.connect(self._on_delete_sync_dataset)
        self.view_overview.refresh_requested.connect(self.refresh_all_data)

        # History signals
        self.view_history.refresh_requested.connect(self._refresh_history)
        self.view_history.load_transfers_requested.connect(self._load_transfers)

        # Storage signals
        self.view_storage.refresh_requested.connect(self._refresh_storage)
        self.view_storage.create_bucket_requested.connect(self._on_create_bucket)

        # Settings signals
        self.view_settings.theme_changed.connect(lambda t: apply_theme(self, t))
        self.view_settings.credentials_saved.connect(self._on_credentials_saved)
        self.view_settings.device_name_saved.connect(self._on_device_name_saved)
        self.view_settings.speed_profile_saved.connect(self._on_speed_profile_saved)
        self.view_settings.start_service_requested.connect(self._on_start_background_service)
        self.view_settings.download_rclone_requested.connect(self._on_download_rclone)
        self.view_settings.test_connection_requested.connect(self._on_test_connection)

    def _on_start_background_service(self):
        try:
            import subprocess
            from pathlib import Path

            exe_dir = Path(sys.executable).parent
            service_exe = exe_dir / ("r2sync-service.exe" if sys.platform == "win32" else "r2sync-service")

            if service_exe.exists():
                cmd = [str(service_exe), "--standalone"]
            else:
                cmd = [sys.executable, "-m", "r2sync.service.main", "--standalone"]

            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW

            subprocess.Popen(
                cmd,
                creationflags=creation_flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            QTimer.singleShot(1500, self.refresh_all_data)
        except Exception as e:
            logger.error(f"Failed to start background service: {e}")

    # -------------------------------------------------------------
    # Event Handlers & Data Loading
    # -------------------------------------------------------------

    def _launch_setup_wizard(self):
        wizard = SetupWizard(self.db, self)
        if wizard.exec() == QDialog.Accepted:
            self._on_credentials_saved()
            self.btn_nav_overview.click()

    def _on_credentials_saved(self):
        self.refresh_all_data()
        self._refresh_storage()

    def _on_speed_profile_saved(self, profile_id: str):
        self.db.set_setting("speed_profile", profile_id)
        logger.info(f"Speed profile updated to: {profile_id}")

    def refresh_all_data(self):
        try:
            # Stats & jobs (direct from DB or via IPC)
            stats = self.db.get_summary_stats()
            jobs = self.db.list_jobs()
            sync_datasets = self.db.list_sync_datasets()
            sync_devices = self.db.list_sync_devices()
            conflicts_count = self.db.count_unresolved_conflicts()
            logs = self.db.list_activities(limit=15)

            self.view_overview.update_stats(stats)
            self.view_overview.update_jobs([j.to_dict() for j in jobs])
            self.view_overview.update_sync_data(
                [d.to_dict() for d in sync_datasets],
                [dev.to_dict() for dev in sync_devices],
                conflicts_count,
            )

            # Device identity & speed profile in settings
            dev_id = self.db.get_or_create_device_id()
            dev_name = self.db.get_device_name()
            self.view_settings.set_device_identity(dev_id, dev_name)

            saved_speed = self.db.get_setting("speed_profile") or "turbo"
            self.view_settings.set_speed_profile(saved_speed)

            creds = get_r2_credentials()
            if creds and creds.account_id:
                self.view_storage.set_account_id(creds.account_id)
            else:
                self.view_storage.set_account_id("")

            # Background service & rclone engine check
            is_svc_running = self.ipc.is_service_running()
            if conflicts_count > 0:
                self.svc_badge.setText(f"● {conflicts_count} Conflict(s)")
                self.svc_badge.setStyleSheet("color: #F6821F; font-size: 12px; font-weight: 600;")
            else:
                self.svc_badge.setText("● All systems operational")
                self.svc_badge.setStyleSheet("color: #4AE176; font-size: 12px; font-weight: 500;")

            if is_svc_running:
                self.view_settings.set_service_status(True)
                try:
                    r_status = self.ipc.get_rclone_status()
                    self.view_settings.set_rclone_status(
                        r_status.get("installed", False),
                        r_status.get("version", "Unknown"),
                    )
                except Exception:
                    pass
            else:
                self.view_settings.set_service_status(False)
                try:
                    from r2sync.core.rclone_engine import RcloneBinaryManager

                    installed = RcloneBinaryManager.is_installed()
                    ver = RcloneBinaryManager.get_version() if installed else "Not installed"
                    self.view_settings.set_rclone_status(installed, ver)
                except Exception:
                    pass

            self._refresh_history()

        except Exception as e:
            logger.debug(f"Refresh data error: {e}")

    def _refresh_history(self):
        try:
            runs = self.db.list_runs(limit=50)
            self.view_history.set_runs([r.to_dict() for r in runs])
        except Exception as e:
            logger.debug(f"Refresh history error: {e}")

    def _load_transfers(self, run_id: int):
        try:
            transfers = self.db.list_transfers_for_run(run_id)
            self.view_history.set_transfers([t.to_dict() for t in transfers])
        except Exception as e:
            logger.debug(f"Load transfers error: {e}")

    def _refresh_storage(self):
        try:
            creds = get_r2_credentials()
            if not creds or not creds.account_id:
                self.view_storage.set_account_id("")
                self.view_storage.set_buckets([])
                return

            self.view_storage.set_account_id(creds.account_id)

            if self.ipc.is_service_running():
                buckets = self.ipc.list_buckets() or []
            else:
                from r2sync.core.r2_client import CloudflareR2Client

                cf = CloudflareR2Client()
                bucket_objs = cf.list_buckets(creds)
                buckets = [b.to_dict() for b in bucket_objs]

            self.view_storage.set_buckets(buckets)
        except Exception as e:
            logger.debug(f"Refresh storage error: {e}")

    def _on_ipc_progress(self, event_data: dict):
        self.view_overview.live_progress.update_progress(event_data)
        self.tray.set_syncing(True, f"Syncing ({int(event_data.get('percentage', 0))}%)")

    def _on_ipc_completed(self, run_data: dict):
        self.view_overview.live_progress.on_job_completed(run_data)
        self.tray.set_syncing(False)
        self.refresh_all_data()

    def _get_available_buckets(self) -> list:
        try:
            if self.ipc.is_service_running():
                buckets_data = self.ipc.list_buckets() or []
                names = [b.get("name") for b in buckets_data if b.get("name")]
                if names:
                    return names
            else:
                from r2sync.core.credentials import get_r2_credentials
                from r2sync.core.r2_client import CloudflareR2Client

                creds = get_r2_credentials()
                if creds and creds.account_id:
                    cf = CloudflareR2Client()
                    bucket_objs = cf.list_buckets(creds)
                    names = [b.name for b in bucket_objs if b.name]
                    if names:
                        return names
        except Exception as e:
            logger.debug(f"Error fetching buckets for dialog: {e}")
        return ["r2sync-backups"]

    def _open_new_job_dialog(self):
        buckets = self._get_available_buckets()
        dlg = JobEditDialog(buckets=buckets, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.job:
            self.db.create_job(dlg.job)
            self.refresh_all_data()

    def _open_edit_job_dialog(self, job_id: int):
        job = self.db.get_job(job_id)
        if not job:
            return
        buckets = self._get_available_buckets()
        dlg = JobEditDialog(job=job, buckets=buckets, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.job:
            self.db.update_job(dlg.job)
            self.refresh_all_data()

    def _on_delete_job(self, job_id: int):
        job = self.db.get_job(job_id)
        if not job:
            return
        ans = QMessageBox.question(
            self,
            "Delete Backup Job",
            f"Are you sure you want to delete the backup job '{job.name}'?\n\n"
            "Note: This removes the job configuration locally. It does NOT delete your remote backups on Cloudflare R2.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            self.db.delete_job(job_id)
            self.refresh_all_data()

    def _on_toggle_job(self, job_id: int, enabled: bool):
        job = self.db.get_job(job_id)
        if job:
            job.enabled = enabled
            self.db.update_job(job)
            self.refresh_all_data()

    def _on_run_job(self, job_id: int):
        if self.ipc.is_service_running():
            self.ipc.run_job_now(job_id)
        elif self.internal_backup_engine:
            job = self.db.get_job(job_id)
            if job:
                self.internal_backup_engine.trigger_job_async(job)
        self.refresh_all_data()

    def _on_cancel_job(self, job_id: int):
        if self.ipc.is_service_running():
            self.ipc.cancel_job(job_id)
        elif self.internal_backup_engine:
            self.internal_backup_engine.cancel_job(job_id)
        self.refresh_all_data()

    def _on_backup_all(self):
        jobs = self.db.list_jobs()
        for j in jobs:
            if j.enabled and j.id:
                self._on_run_job(j.id)

    def _on_create_bucket(self, bucket_name: str):
        try:
            if self.ipc.is_service_running():
                self.ipc.create_bucket(bucket_name)
            else:
                from r2sync.core.r2_client import CloudflareR2Client

                cf = CloudflareR2Client()
                cf.create_bucket(bucket_name)
            QMessageBox.information(self, "Success", f"Bucket '{bucket_name}' created successfully.")
            self._refresh_storage()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to create bucket: {e}")

    def _on_download_rclone(self):
        try:
            if self.ipc.is_service_running():
                res = self.ipc.download_rclone()
                QMessageBox.information(self, "Success", f"Rclone successfully downloaded: {res.get('version')}")
            else:
                from r2sync.core.rclone_engine import RcloneBinaryManager

                RcloneBinaryManager.download_and_install()
                QMessageBox.information(self, "Success", "Rclone downloaded and installed.")
            self.refresh_all_data()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to download Rclone: {e}")

    def _on_test_connection(self, acc: str, ak: str, sk: str):
        try:
            if self.ipc.is_service_running():
                res = self.ipc.test_r2_connection(acc, ak, sk)
            else:
                from r2sync.core.models import R2Credentials
                from r2sync.core.r2_client import CloudflareR2Client

                creds = R2Credentials(account_id=acc, access_key_id=ak, secret_access_key=sk)
                cf = CloudflareR2Client()
                res = cf.test_connection(creds)

            if res.get("success"):
                lat = res.get("latency_ms", 0)
                buckets = res.get("buckets", [])
                b_info = f" Discovered {len(buckets)} bucket(s)." if buckets else ""
                ans = QMessageBox.question(
                    self,
                    "Connection Successful",
                    f"Successfully connected to Cloudflare R2 ({lat}ms)!{b_info}\n\n"
                    "Would you like to save these credentials now?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if ans == QMessageBox.Yes:
                    from r2sync.core.credentials import save_r2_credentials

                    save_r2_credentials(acc, ak, sk)
                    self.view_settings._load_current_values()
                    self._on_credentials_saved()
            else:
                err = res.get("error") or res.get("message") or "Unknown error"
                QMessageBox.warning(self, "Connection Failed", f"Failed to connect to Cloudflare R2:\n\n{err}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Connection test failed: {e}")

    def _on_sync_progress(self, event_data: dict):
        self.view_overview.live_progress.update_progress(event_data)
        pct = int(event_data.get("percentage", 0))
        self.tray.set_syncing(True, f"Syncing ({pct}%)")

    def _on_sync_completed(self, data: dict):
        self.tray.set_syncing(False)
        self.refresh_all_data()

    def _open_add_sync_dialog(self):
        buckets = self._get_available_buckets()

        def overlap_checker(path: str):
            if self.ipc.is_service_running():
                return self.ipc.check_folder_overlap(path)
            if self.internal_sync_engine:
                return self.internal_sync_engine.check_folder_overlap(path)
            from r2sync.core.sync_engine import SyncEngine

            se = SyncEngine(self.db)
            return se.check_folder_overlap(path)

        dlg = AddSyncDialog(buckets=buckets, overlap_checker=overlap_checker, parent=self)
        if dlg.exec() == QDialog.Accepted and hasattr(dlg, "result_data"):
            res = dlg.result_data
            if self.ipc.is_service_running():
                self.ipc.create_sync_dataset(
                    name=res["name"],
                    local_path=res["local_path"],
                    bucket_name=res["bucket_name"],
                    schedule_mode=res["schedule_mode"],
                    schedule_interval_minutes=res["schedule_interval_minutes"],
                    max_delete_threshold=res["max_delete_threshold"],
                    exclude_patterns=res["exclude_patterns"],
                    initial_action=res["initial_action"],
                )
            elif self.internal_sync_engine:
                self.internal_sync_engine.create_and_init_dataset(
                    name=res["name"],
                    local_path=res["local_path"],
                    bucket_name=res["bucket_name"],
                    schedule_mode=res["schedule_mode"],
                    schedule_interval_minutes=res["schedule_interval_minutes"],
                    max_delete_threshold=res["max_delete_threshold"],
                    exclude_patterns=res["exclude_patterns"],
                    initial_action=res["initial_action"],
                )
            self.refresh_all_data()
            self.btn_nav_overview.click()
            self.view_overview.tab_sync_btn.click()

    def _open_setup_pc_dialog(self):
        discovered = []
        try:
            if self.ipc.is_service_running():
                discovered = self.ipc.discover_remote_datasets()
            elif self.internal_sync_engine:
                discovered = [d.to_dict() for d in self.internal_sync_engine.discover_remote_datasets()]
            else:
                from r2sync.core.sync_engine import SyncEngine

                se = SyncEngine(self.db)
                discovered = [d.to_dict() for d in se.discover_remote_datasets()]
        except Exception as e:
            logger.debug(f"Error discovering datasets: {e}")

        if not discovered:
            QMessageBox.information(
                self,
                "No Datasets Found",
                "No existing shared datasets were found in your Cloudflare R2 bucket.\n\n"
                "To start sharing a folder, use '+ Add Sync Folder' to create the first dataset on this PC.",
            )
            return

        dlg = SetupPCDialog(discovered_datasets=discovered, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.selected_dataset and dlg.chosen_local_path:
            sel = dlg.selected_dataset
            loc = dlg.chosen_local_path

            if self.ipc.is_service_running():
                self.ipc.join_remote_dataset(
                    remote_info=sel,
                    local_path=loc,
                )
            else:
                from r2sync.core.models import RemoteDatasetInfo
                engine = self.internal_sync_engine
                if not engine:
                    from r2sync.core.sync_engine import SyncEngine
                    engine = SyncEngine(self.db)
                info = RemoteDatasetInfo.from_dict(sel)
                engine.join_remote_dataset(remote_info=info, local_path=loc)

            self.refresh_all_data()
            self.btn_nav_overview.click()
            self.view_overview.tab_sync_btn.click()

    def _open_manage_computers_dialog(self, dataset_id: str):
        dataset = self.db.get_sync_dataset(dataset_id)
        if not dataset:
            return

        devices = [d.to_dict() for d in self.db.list_sync_devices(dataset_id)]

        def remove_dev_cb(ds_id: str, dev_id: str) -> bool:
            if self.ipc.is_service_running():
                return self.ipc.remove_sync_device(ds_id, dev_id)
            if self.internal_sync_engine:
                return self.internal_sync_engine.remove_device(ds_id, dev_id)
            from r2sync.core.sync_engine import SyncEngine

            se = SyncEngine(self.db)
            return se.remove_device(ds_id, dev_id)

        def refresh_devs_cb(ds_id: str):
            if self.ipc.is_service_running():
                return self.ipc.refresh_sync_devices(ds_id)
            if self.internal_sync_engine:
                return [d.to_dict() for d in self.internal_sync_engine.refresh_connected_devices(ds_id)]
            from r2sync.core.sync_engine import SyncEngine

            se = SyncEngine(self.db)
            return [d.to_dict() for d in se.refresh_connected_devices(ds_id)]

        dlg = ManageDevicesDialog(
            dataset_name=dataset.name,
            dataset_id=dataset_id,
            devices=devices,
            remove_device_cb=remove_dev_cb,
            refresh_cb=refresh_devs_cb,
            parent=self,
        )
        dlg.device_removed.connect(self.refresh_all_data)
        dlg.exec()

    def _open_conflicts_dialog(self, dataset_id: str = ""):
        conflicts = [c.to_dict() for c in self.db.list_conflicts(dataset_id or None, include_resolved=False)]

        def resolver_cb(c_id: int, res: str) -> bool:
            if self.ipc.is_service_running():
                return self.ipc.resolve_conflict(c_id, res)
            if self.internal_sync_engine:
                return self.internal_sync_engine.resolve_conflict(c_id, res)
            from r2sync.core.sync_engine import SyncEngine

            se = SyncEngine(self.db)
            return se.resolve_conflict(c_id, res)

        current_pc_name = self.db.get_device_name()
        dlg = ConflictCenterDialog(
            conflicts=conflicts,
            resolver_cb=resolver_cb,
            current_device_name=current_pc_name,
            parent=self,
        )
        dlg.conflict_resolved.connect(self.refresh_all_data)
        dlg.exec()

    def _on_sync_dataset_now(self, dataset_id: str):
        if self.ipc.is_service_running():
            self.ipc.sync_dataset_now(dataset_id)
        elif self.internal_sync_engine:
            self.internal_sync_engine.trigger_sync_async(dataset_id)
        self.refresh_all_data()

    def _on_pause_toggle_sync(self, dataset_id: str, pause: bool):
        if self.ipc.is_service_running():
            if pause:
                self.ipc.pause_sync_dataset(dataset_id)
            else:
                self.ipc.resume_sync_dataset(dataset_id)
        else:
            ds = self.db.get_sync_dataset(dataset_id)
            if ds:
                ds.paused = pause
                ds.status = "paused" if pause else "waiting"
                self.db.update_sync_dataset(ds)
                if self.internal_sync_engine:
                    if pause:
                        self.internal_sync_engine.watcher_manager.stop_watching(dataset_id)
                    elif ds.enabled and ds.schedule_mode == "realtime" and os.path.exists(ds.local_path):
                        self.internal_sync_engine.watcher_manager.start_watching(dataset_id, ds.local_path, ds.exclude_patterns)
        self.refresh_all_data()

    def _on_delete_sync_dataset(self, dataset_id: str):
        ds = self.db.get_sync_dataset(dataset_id)
        if not ds:
            return
        ans = QMessageBox.question(
            self,
            "Disconnect Sync Folder",
            f"Are you sure you want to stop synchronizing '{ds.name}' on this PC?\n\n"
            "• Your local files will remain intact.\n"
            "• Cloudflare R2 dataset files will remain intact for your other computers.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            if self.ipc.is_service_running():
                self.ipc.delete_sync_dataset(dataset_id, delete_remote_files=False)
            elif self.internal_sync_engine:
                self.internal_sync_engine.delete_dataset(dataset_id, delete_remote_files=False)
            self.refresh_all_data()

    def _on_device_name_saved(self, name: str):
        if self.ipc.is_service_running():
            self.ipc.set_device_name(name)
        else:
            self.db.set_device_name(name)
        self.refresh_all_data()

    def _show_and_raise(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_force_quit(self):
        self.tray.hide()
        self.ipc.stop_event_stream()
        if self.internal_scheduler:
            self.internal_scheduler.stop()
        if self.internal_sync_engine:
            self.internal_sync_engine.stop_all_watchers()
        from PySide6.QtWidgets import QApplication

        QApplication.quit()

    def closeEvent(self, event: QCloseEvent):
        # Minimize to system tray on close instead of exiting
        if self.tray.isVisible():
            self.hide()
            self.tray.showMessage(
                APP_DISPLAY_NAME,
                "r2sync is still running in the background to maintain your backup schedules.",
                QIcon(),
                2000,
            )
            event.ignore()
        else:
            event.accept()
