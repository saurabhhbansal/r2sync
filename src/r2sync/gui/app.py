"""Main Window and Application Controller for r2sync GUI."""

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
from r2sync.gui.views.dashboard_view import DashboardView
from r2sync.gui.views.history_view import HistoryView
from r2sync.gui.views.job_edit_dialog import JobEditDialog
from r2sync.gui.views.jobs_view import JobsView
from r2sync.gui.views.manage_devices_dialog import ManageDevicesDialog
from r2sync.gui.views.settings_view import SettingsView
from r2sync.gui.views.setup_pc_dialog import SetupPCDialog
from r2sync.gui.views.storage_view import StorageView
from r2sync.gui.views.sync_view import SyncView
from r2sync.gui.wizard.setup_wizard import SetupWizard


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(self, ipc_client: IPCClient, db: Database):
        super().__init__()
        self.ipc = ipc_client
        self.db = db

        self.setWindowTitle(f"{APP_DISPLAY_NAME} - Cloudflare R2 Backup")
        self.resize(1000, 680)
        self.setMinimumSize(850, 550)

        icon_path = get_asset_path("icon.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._init_ui()
        self._setup_tray()
        self._setup_timers()
        self._connect_signals()

        # Check first run / credentials
        if not has_r2_credentials():
            QTimer.singleShot(200, self._launch_setup_wizard)
        else:
            self.refresh_all_data()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # -------------------------------------------------------------
        # Left Navigation Sidebar
        # -------------------------------------------------------------
        sidebar = QFrame()
        sidebar.setObjectName("sidebarWidget")
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 20, 16, 16)
        sidebar_layout.setSpacing(8)

        # App Brand
        brand_row = QHBoxLayout()
        brand_logo = QLabel()
        icon_path = get_asset_path("icon.png")
        if icon_path.exists():
            pix = QPixmap(str(icon_path)).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            brand_logo.setPixmap(pix)
        else:
            brand_logo.setText("🛡️")
            brand_logo.setStyleSheet("font-size: 22px;")
        brand_title = QLabel(APP_DISPLAY_NAME)
        brand_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #FFFFFF;")
        brand_ver = QLabel(f"v{APP_VERSION}")
        brand_ver.setStyleSheet("color: #64748B; font-size: 11px; margin-top: 4px;")

        brand_row.addWidget(brand_logo)
        brand_row.addWidget(brand_title)
        brand_row.addWidget(brand_ver)
        brand_row.addStretch()
        sidebar_layout.addLayout(brand_row)

        sidebar_layout.addSpacing(16)

        # Nav Buttons (Section 5: Dashboard, Backups, Sync, Activity, Storage, Settings)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.btn_nav_dashboard = self._create_nav_button("📊  Dashboard", 0)
        self.btn_nav_jobs = self._create_nav_button("📁  Backups", 1)
        self.btn_nav_sync = self._create_nav_button("🔄  Sync", 2)
        self.btn_nav_history = self._create_nav_button("📜  Activity", 3)
        self.btn_nav_storage = self._create_nav_button("☁️  Storage", 4)
        self.btn_nav_settings = self._create_nav_button("⚙️  Settings", 5)

        sidebar_layout.addWidget(self.btn_nav_dashboard)
        sidebar_layout.addWidget(self.btn_nav_jobs)
        sidebar_layout.addWidget(self.btn_nav_sync)
        sidebar_layout.addWidget(self.btn_nav_history)
        sidebar_layout.addWidget(self.btn_nav_storage)
        sidebar_layout.addWidget(self.btn_nav_settings)
        sidebar_layout.addStretch()

        # Service Status Indicator at bottom of sidebar
        self.svc_badge = QLabel("● Service Online")
        self.svc_badge.setStyleSheet("color: #10B981; font-size: 12px; font-weight: 500;")
        sidebar_layout.addWidget(self.svc_badge)

        root_layout.addWidget(sidebar)

        # -------------------------------------------------------------
        # Right Stacked Content Views
        # -------------------------------------------------------------
        self.stack = QStackedWidget()

        self.view_dashboard = DashboardView()
        self.view_jobs = JobsView()
        self.view_sync = SyncView()
        self.view_history = HistoryView()
        self.view_storage = StorageView()
        self.view_settings = SettingsView()

        self.stack.addWidget(self.view_dashboard)
        self.stack.addWidget(self.view_jobs)
        self.stack.addWidget(self.view_sync)
        self.stack.addWidget(self.view_history)
        self.stack.addWidget(self.view_storage)
        self.stack.addWidget(self.view_settings)

        root_layout.addWidget(self.stack, stretch=1)

        self.btn_nav_dashboard.setChecked(True)


    def _create_nav_button(self, text: str, view_index: int) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setObjectName("secondaryBtn")
        btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 10px 14px;
                font-size: 13px;
                border-radius: 6px;
            }
            QPushButton:checked {
                background-color: #2563EB;
                color: #FFFFFF;
                font-weight: bold;
                border: none;
            }
        """)
        def on_nav_clicked():
            self.stack.setCurrentIndex(view_index)
            if view_index == 4:
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
        # Dashboard signals
        self.view_dashboard.new_job_requested.connect(self._open_new_job_dialog)
        self.view_dashboard.backup_all_requested.connect(self._on_backup_all)
        self.view_dashboard.view_history_requested.connect(lambda: self.btn_nav_history.click())
        self.view_dashboard.cancel_job_requested.connect(self._on_cancel_job)

        # Jobs signals
        self.view_jobs.create_job_requested.connect(self._open_new_job_dialog)
        self.view_jobs.run_job_requested.connect(self._on_run_job)
        self.view_jobs.edit_job_requested.connect(self._open_edit_job_dialog)
        self.view_jobs.delete_job_requested.connect(self._on_delete_job)
        self.view_jobs.toggle_job_requested.connect(self._on_toggle_job)

        # Sync signals
        self.view_sync.add_sync_requested.connect(self._open_add_sync_dialog)
        self.view_sync.setup_pc_requested.connect(self._open_setup_pc_dialog)
        self.view_sync.manage_computers_requested.connect(self._open_manage_computers_dialog)
        self.view_sync.open_conflicts_requested.connect(self._open_conflicts_dialog)
        self.view_sync.refresh_requested.connect(self.refresh_all_data)
        self.view_sync.sync_now_requested.connect(self._on_sync_dataset_now)
        self.view_sync.pause_toggle_requested.connect(self._on_pause_toggle_sync)
        self.view_sync.delete_dataset_requested.connect(self._on_delete_sync_dataset)

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
        self.view_settings.download_rclone_requested.connect(self._on_download_rclone)
        self.view_settings.test_connection_requested.connect(self._on_test_connection)

    # -------------------------------------------------------------
    # Event Handlers & Data Loading
    # -------------------------------------------------------------

    def _launch_setup_wizard(self):
        wizard = SetupWizard(self.db, self)
        if wizard.exec() == QDialog.Accepted:
            self._on_credentials_saved()
            self.btn_nav_dashboard.click()

    def _on_credentials_saved(self):
        self.refresh_all_data()
        self._refresh_storage()

    def refresh_all_data(self):
        try:
            # Stats & jobs (direct from DB or via IPC)
            stats = self.db.get_summary_stats()
            jobs = self.db.list_jobs()
            sync_datasets = self.db.list_sync_datasets()
            sync_devices = self.db.list_sync_devices()
            conflicts_count = self.db.count_unresolved_conflicts()
            logs = self.db.list_activities(limit=15)

            self.view_dashboard.update_stats(stats)
            self.view_dashboard.update_jobs([j.to_dict() for j in jobs])
            self.view_dashboard.update_activities([l.to_dict() for l in logs])
            self.view_jobs.set_jobs([j.to_dict() for j in jobs])
            self.view_sync.set_data(
                [d.to_dict() for d in sync_datasets],
                [dev.to_dict() for dev in sync_devices],
                conflicts_count,
            )

            # Device identity in settings
            dev_id = self.db.get_or_create_device_id()
            dev_name = self.db.get_device_name()
            self.view_settings.set_device_identity(dev_id, dev_name)

            creds = get_r2_credentials()
            if creds and creds.account_id:
                self.view_storage.set_account_id(creds.account_id)
            else:
                self.view_storage.set_account_id("")

            # Background service & rclone engine check
            is_svc_running = self.ipc.is_service_running()
            if is_svc_running:
                self.svc_badge.setText("● Service Online")
                self.svc_badge.setStyleSheet("color: #10B981; font-size: 12px;")
                self.view_settings.set_service_status(True)
                try:
                    r_status = self.ipc.get_rclone_status()
                    self.view_settings.set_rclone_status(
                        r_status.get("installed", False),
                        r_status.get("version", "Unknown")
                    )
                except Exception:
                    pass
            else:
                self.svc_badge.setText("● Standalone Mode")
                self.svc_badge.setStyleSheet("color: #F59E0B; font-size: 12px;")
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
        self.view_dashboard.live_progress.update_progress(event_data)
        self.tray.set_syncing(True, f"Syncing ({int(event_data.get('percentage', 0))}%)")

    def _on_ipc_completed(self, run_data: dict):
        self.view_dashboard.live_progress.on_job_completed(run_data)
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
        else:
            job = self.db.get_job(job_id)
            if job:
                from r2sync.core.backup_engine import BackupEngine
                be = BackupEngine(self.db)
                be.trigger_job_async(job)
        self.refresh_all_data()

    def _on_cancel_job(self, job_id: int):
        if self.ipc.is_service_running():
            self.ipc.cancel_job(job_id)
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
        self.view_dashboard.live_progress.update_progress(event_data)
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
            else:
                from r2sync.core.sync_engine import SyncEngine
                se = SyncEngine(self.db)
                se.create_and_init_dataset(
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
            self.btn_nav_sync.click()

    def _open_setup_pc_dialog(self):
        discovered = []
        try:
            if self.ipc.is_service_running():
                discovered = self.ipc.discover_remote_datasets()
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
                "To start sharing a folder, use '+ Add Sync Folder' to create the first dataset on this PC."
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
                from r2sync.core.sync_engine import SyncEngine
                se = SyncEngine(self.db)
                info = RemoteDatasetInfo.from_dict(sel)
                se.join_remote_dataset(remote_info=info, local_path=loc)

            self.refresh_all_data()
            self.btn_nav_sync.click()

    def _open_manage_computers_dialog(self, dataset_id: str):
        dataset = self.db.get_sync_dataset(dataset_id)
        if not dataset:
            return

        devices = [d.to_dict() for d in self.db.list_sync_devices(dataset_id)]

        def remove_dev_cb(ds_id: str, dev_id: str) -> bool:
            if self.ipc.is_service_running():
                return self.ipc.remove_sync_device(ds_id, dev_id)
            from r2sync.core.sync_engine import SyncEngine
            se = SyncEngine(self.db)
            return se.remove_device(ds_id, dev_id)

        def refresh_devs_cb(ds_id: str):
            if self.ipc.is_service_running():
                return self.ipc.refresh_sync_devices(ds_id)
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
        else:
            from r2sync.core.sync_engine import SyncEngine
            se = SyncEngine(self.db)
            se.trigger_sync_async(dataset_id)
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
            else:
                from r2sync.core.sync_engine import SyncEngine
                se = SyncEngine(self.db)
                se.delete_dataset(dataset_id, delete_remote_files=False)
            self.refresh_all_data()

    def _on_device_name_saved(self, name: str):
        if self.ipc.is_service_running():
            self.ipc.set_device_name(name)
        else:
            self.db.set_device_name(name)
        self.refresh_all_data()

    def _show_and_raise(self):
        self.show()
        self.raise_()
        self.activateWindow()


    def _on_force_quit(self):
        self.tray.hide()
        self.ipc.stop_event_stream()
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
