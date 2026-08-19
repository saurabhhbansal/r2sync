"""Dialog for creating and adding a new Sync folder dataset matching Stitch Design."""

import os
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt
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
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from r2sync.config import DEFAULT_EXCLUDE_PATTERNS
from r2sync.core.models import SyncDataset, SyncScheduleMode, SyncStatus
from r2sync.gui.views.folder_tree_widget import FolderTreeFilterWidget


class AddSyncDialog(QDialog):
    """Dialog for creating a new Multi-PC Sync dataset matching Stitch Design."""

    def __init__(
        self,
        buckets: Optional[List[str]] = None,
        overlap_checker: Optional[callable] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.buckets = buckets or ["r2sync-backups"]
        self.overlap_checker = overlap_checker
        self.dataset: Optional[SyncDataset] = None
        self.initial_action = "merge"

        self.setWindowTitle("Add Sync Folder")
        self.resize(620, 720)
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Header Info Banner
        info_card = QFrame()
        info_card.setObjectName("heroCardWidget")
        info_card.setStyleSheet("""
            QFrame#heroCardWidget {
                background-color: #1D2024;
                border: 1px solid #272A2E;
                border-radius: 12px;
                padding: 16px;
            }
        """)
        info_layout = QVBoxLayout(info_card)
        info_layout.setSpacing(4)

        info_title = QLabel("🔄  Continuous Multi-PC Synchronization")
        info_title.setStyleSheet("font-weight: 600; color: #FFB786; font-size: 14px;")
        info_layout.addWidget(info_title)

        info_desc = QLabel(
            "Sync keeps your selected local folder continuously up to date across all your connected computers through your private Cloudflare R2 storage."
        )
        info_desc.setWordWrap(True)
        info_desc.setStyleSheet("color: #A58C7D; font-size: 12px;")
        info_layout.addWidget(info_desc)
        main_layout.addWidget(info_card)

        form_frame = QFrame()
        form_frame.setObjectName("cardWidget")
        form = QFormLayout(form_frame)
        form.setSpacing(12)

        # 1. Dataset Name
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Shared Documents, Projects, Photos")
        form.addRow("Sync Dataset Name:", self.name_input)

        # 2. Local Folder
        folder_row = QHBoxLayout()
        self.source_input = QLineEdit()
        self.source_input.setPlaceholderText("Select local folder to synchronize")
        self.source_input.textChanged.connect(self._on_path_changed)
        browse_btn = QPushButton("📁 Browse...")
        browse_btn.setObjectName("secondaryBtn")
        browse_btn.setStyleSheet("padding: 6px 12px;")
        browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.source_input)
        folder_row.addWidget(browse_btn)
        form.addRow("Local Folder:", folder_row)

        # Overlap Warning Label (Hidden by default)
        self.overlap_warn_lbl = QLabel("")
        self.overlap_warn_lbl.setStyleSheet("color: #F6821F; font-size: 11px; font-weight: 600;")
        self.overlap_warn_lbl.setVisible(False)
        form.addRow("", self.overlap_warn_lbl)

        # 3. Target Bucket
        bucket_row = QHBoxLayout()
        self.bucket_combo = QComboBox()
        self.bucket_combo.setEditable(False)
        for b in self.buckets:
            self.bucket_combo.addItem(b)

        new_bucket_btn = QPushButton("➕ New Bucket")
        new_bucket_btn.setObjectName("secondaryBtn")
        new_bucket_btn.setStyleSheet("padding: 6px 12px;")
        new_bucket_btn.clicked.connect(self._create_new_bucket)

        bucket_row.addWidget(self.bucket_combo, stretch=1)
        bucket_row.addWidget(new_bucket_btn)
        form.addRow("R2 Bucket:", bucket_row)

        main_layout.addWidget(form_frame)

        # 4. Initial Folder Content Handling (Data Protection)
        self.nonempty_group = QGroupBox("Initial Folder Setup")
        ne_layout = QVBoxLayout(self.nonempty_group)
        ne_layout.setSpacing(8)

        ne_label = QLabel("How should r2sync handle existing files in this folder?")
        ne_label.setStyleSheet("color: #E1E2E8; font-size: 12px;")
        ne_layout.addWidget(ne_label)

        self.radio_merge = QRadioButton("Merge with cloud dataset (Safest default)")
        self.radio_replace = QRadioButton("Replace local files with cloud version")
        self.radio_merge.setChecked(True)

        ne_layout.addWidget(self.radio_merge)
        ne_layout.addWidget(self.radio_replace)
        main_layout.addWidget(self.nonempty_group)

        # 5. Scheduling Mode
        sched_group = QGroupBox("Sync Schedule & Frequency")
        sched_layout = QVBoxLayout(sched_group)
        sched_layout.setSpacing(8)

        self.sched_combo = QComboBox()
        self.sched_combo.addItems([
            "Real-Time (Continuous Watcher - Recommended)",
            "Every 15 Minutes",
            "Every 30 Minutes",
            "Every 1 Hour",
            "Every 4 Hours",
            "Daily",
            "Manual Only (On demand)",
        ])
        sched_layout.addWidget(self.sched_combo)
        main_layout.addWidget(sched_group)

        # 6. Exclusions (Interactive Folder Structure Tree)
        opt_group = QGroupBox("Selective Sync & Exclusion Rules")
        opt_layout = QVBoxLayout(opt_group)
        opt_layout.setSpacing(6)

        tree_hint = QLabel("Uncheck any folders or files below to exclude them from synchronization:")
        tree_hint.setStyleSheet("color: #A58C7D; font-size: 12px;")
        opt_layout.addWidget(tree_hint)

        self.tree_filter = FolderTreeFilterWidget(parent=self)
        opt_layout.addWidget(self.tree_filter)

        main_layout.addWidget(opt_group)

        # Bottom Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.setStyleSheet("padding: 8px 16px;")
        cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("Start Synchronization")
        self.save_btn.setStyleSheet("padding: 8px 18px; font-weight: 600;")
        self.save_btn.clicked.connect(self._validate_and_save)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.save_btn)
        main_layout.addLayout(btn_layout)

    def _create_new_bucket(self):
        from r2sync.gui.views.storage_view import CreateBucketDialog
        dlg = CreateBucketDialog(self)
        if dlg.exec() == QDialog.Accepted and hasattr(dlg, "bucket_name"):
            name = dlg.bucket_name
            idx = self.bucket_combo.findText(name)
            if idx == -1:
                self.bucket_combo.addItem(name)
            self.bucket_combo.setCurrentText(name)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Sync Directory", str(Path.home()))
        if folder:
            self.source_input.setText(folder)
            if not self.name_input.text():
                self.name_input.setText(Path(folder).name)
            self.tree_filter.set_root_path(folder)

    def _on_path_changed(self, path: str):
        path = path.strip()
        if path and os.path.exists(path) and os.path.isdir(path):
            if self.tree_filter.root_path != os.path.abspath(path):
                self.tree_filter.set_root_path(path)

        if path and self.overlap_checker:
            overlaps = self.overlap_checker(path)
            if overlaps:
                msg = "⚠️ Warning: This folder overlaps with existing jobs:\n• " + "\n• ".join(overlaps)
                self.overlap_warn_lbl.setText(msg)
                self.overlap_warn_lbl.setVisible(True)
            else:
                self.overlap_warn_lbl.setVisible(False)
        else:
            self.overlap_warn_lbl.setVisible(False)

    def _validate_and_save(self):
        name = self.name_input.text().strip()
        source = self.source_input.text().strip()
        bucket = self.bucket_combo.currentText().strip()

        if not name:
            QMessageBox.warning(self, "Validation Error", "Please provide a name for this Sync dataset.")
            return
        if not source:
            QMessageBox.warning(self, "Validation Error", "Please select a local folder to synchronize.")
            return
        if not os.path.exists(source):
            try:
                os.makedirs(source, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "Validation Error", f"Could not create local directory:\n{e}")
                return
        if not bucket:
            QMessageBox.warning(self, "Validation Error", "Please specify a Cloudflare R2 bucket.")
            return

        # Check overlaps warning
        if self.overlap_checker:
            overlaps = self.overlap_checker(source)
            if overlaps:
                ans = QMessageBox.warning(
                    self,
                    "Overlapping Folder Warning",
                    f"The selected folder overlaps with:\n\n• " + "\n• ".join(overlaps) +
                    "\n\nRunning Backup and Sync on the same files may produce unexpected results.\n\nDo you want to proceed anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if ans != QMessageBox.Yes:
                    return

        # Determine schedule mode
        idx = self.sched_combo.currentIndex()
        if idx == 0:
            sched_mode = SyncScheduleMode.REALTIME.value
            interval_mins = 15
        elif idx == 1:
            sched_mode = SyncScheduleMode.INTERVAL.value
            interval_mins = 15
        elif idx == 2:
            sched_mode = SyncScheduleMode.INTERVAL.value
            interval_mins = 30
        elif idx == 3:
            sched_mode = SyncScheduleMode.INTERVAL.value
            interval_mins = 60
        elif idx == 4:
            sched_mode = SyncScheduleMode.INTERVAL.value
            interval_mins = 240
        elif idx == 5:
            sched_mode = SyncScheduleMode.DAILY.value
            interval_mins = 1440
        else:
            sched_mode = SyncScheduleMode.MANUAL.value
            interval_mins = 60

        excludes = self.tree_filter.get_exclude_patterns()
        self.initial_action = "replace" if self.radio_replace.isChecked() else "merge"

        self.result_data = {
            "name": name,
            "local_path": source,
            "bucket_name": bucket,
            "schedule_mode": sched_mode,
            "schedule_interval_minutes": interval_mins,
            "max_delete_threshold": 50,
            "exclude_patterns": excludes,
            "initial_action": self.initial_action,
        }

        self.accept()
