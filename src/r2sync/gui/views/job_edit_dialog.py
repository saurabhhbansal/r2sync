"""Dialog for creating and modifying backup jobs matching Stitch Design."""

import json
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
)

from r2sync.config import DEFAULT_EXCLUDE_PATTERNS
from r2sync.core.models import BackupJob, BackupMode, JobScheduleType


class JobEditDialog(QDialog):
    """Dialog for creating or editing a backup job matching Stitch Design."""

    def __init__(self, job: Optional[BackupJob] = None, buckets: Optional[List[str]] = None, parent=None):
        super().__init__(parent)
        self.job = job
        self.buckets = buckets or ["r2sync-backups"]

        self.setWindowTitle("Edit Backup Job" if job else "Create Backup Job")
        self.resize(560, 620)
        self._init_ui()
        if job:
            self._load_job_data(job)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(20, 20, 20, 20)

        form_frame = QFrame()
        form_frame.setObjectName("cardWidget")
        form = QFormLayout(form_frame)
        form.setSpacing(12)

        # 1. Job Name
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. My Documents Backup")
        form.addRow("Job Name:", self.name_input)

        # 2. Source Folder
        folder_row = QHBoxLayout()
        self.source_input = QLineEdit()
        self.source_input.setPlaceholderText("Full path to local directory")
        browse_btn = QPushButton("📁 Browse...")
        browse_btn.setObjectName("secondaryBtn")
        browse_btn.setStyleSheet("padding: 6px 12px;")
        browse_btn.clicked.connect(self._browse_source)
        folder_row.addWidget(self.source_input)
        folder_row.addWidget(browse_btn)
        form.addRow("Source Folder:", folder_row)

        # 3. Target Bucket & Prefix
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
        form.addRow("Target R2 Bucket:", bucket_row)

        self.prefix_input = QLineEdit()
        self.prefix_input.setPlaceholderText("Optional subfolder path in bucket (e.g. Documents)")
        form.addRow("Bucket Subfolder:", self.prefix_input)

        main_layout.addWidget(form_frame)

        # 4. Schedule Group
        sched_group = QGroupBox("Backup Schedule")
        sched_layout = QVBoxLayout(sched_group)
        sched_layout.setSpacing(8)

        self.schedule_combo = QComboBox()
        self.schedule_combo.addItems([
            "Daily (at specific time)",
            "Interval (every X minutes)",
            "Weekly (specific days)",
            "Manual only (on-demand)",
        ])
        self.schedule_combo.currentIndexChanged.connect(self._on_schedule_changed)
        sched_layout.addWidget(self.schedule_combo)

        self.time_row = QHBoxLayout()
        self.time_row.addWidget(QLabel("Time of day (24h):"))
        self.hour_spin = QSpinBox()
        self.hour_spin.setRange(0, 23)
        self.hour_spin.setValue(2)
        self.min_spin = QSpinBox()
        self.min_spin.setRange(0, 59)
        self.min_spin.setValue(0)
        self.time_row.addWidget(self.hour_spin)
        self.time_row.addWidget(QLabel(":"))
        self.time_row.addWidget(self.min_spin)
        self.time_row.addStretch()
        sched_layout.addLayout(self.time_row)

        self.interval_row = QHBoxLayout()
        self.interval_row.addWidget(QLabel("Run every:"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 1440)
        self.interval_spin.setValue(60)
        self.interval_spin.setSuffix(" minutes")
        self.interval_row.addWidget(self.interval_spin)
        self.interval_row.addStretch()
        sched_layout.addLayout(self.interval_row)

        main_layout.addWidget(sched_group)

        # 5. Backup Mode & Exclusions
        opt_group = QGroupBox("Sync Options & Exclusions")
        opt_layout = QVBoxLayout(opt_group)
        opt_layout.setSpacing(8)

        mode_row = QHBoxLayout()
        self.sync_radio = QRadioButton("Mirror (Sync) - Deletes files in R2 if deleted locally")
        self.copy_radio = QRadioButton("Additive (Copy) - Never deletes files in R2")
        self.sync_radio.setChecked(True)
        mode_row.addWidget(self.sync_radio)
        mode_row.addWidget(self.copy_radio)
        opt_layout.addLayout(mode_row)

        self.delete_excluded_cb = QCheckBox("Delete files matching exclusion rules from destination")
        opt_layout.addWidget(self.delete_excluded_cb)

        opt_layout.addWidget(QLabel("Exclusion Patterns (one per line):"))
        self.exclude_edit = QTextEdit()
        self.exclude_edit.setPlaceholderText("*.tmp\n.git/\nnode_modules/")
        self.exclude_edit.setMaximumHeight(70)
        self.exclude_edit.setPlainText("\n".join(DEFAULT_EXCLUDE_PATTERNS[:7]))
        opt_layout.addWidget(self.exclude_edit)

        main_layout.addWidget(opt_group)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.setStyleSheet("padding: 8px 16px;")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save Backup Job")
        save_btn.setStyleSheet("padding: 8px 18px; font-weight: 600;")
        save_btn.clicked.connect(self._validate_and_save)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        main_layout.addLayout(btn_layout)

        self._on_schedule_changed(0)

    def _browse_source(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Source Directory", str(Path.home()))
        if folder:
            self.source_input.setText(folder)
            if not self.name_input.text():
                self.name_input.setText(f"{Path(folder).name} Backup")
            if not self.prefix_input.text():
                self.prefix_input.setText(Path(folder).name)

    def _on_schedule_changed(self, index: int):
        self.time_row.setEnabled(index in (0, 2))
        self.interval_row.setEnabled(index == 1)

    def _create_new_bucket(self):
        from r2sync.gui.views.storage_view import CreateBucketDialog
        dlg = CreateBucketDialog(self)
        if dlg.exec() == QDialog.Accepted and hasattr(dlg, "bucket_name"):
            name = dlg.bucket_name
            idx = self.bucket_combo.findText(name)
            if idx == -1:
                self.bucket_combo.addItem(name)
            self.bucket_combo.setCurrentText(name)

    def _load_job_data(self, job: BackupJob):
        self.name_input.setText(job.name)
        self.source_input.setText(job.source_path)
        if job.bucket_name:
            if self.bucket_combo.findText(job.bucket_name) == -1:
                self.bucket_combo.addItem(job.bucket_name)
            self.bucket_combo.setCurrentText(job.bucket_name)
        self.prefix_input.setText(job.remote_prefix)

        if job.schedule_type == JobScheduleType.INTERVAL.value:
            self.schedule_combo.setCurrentIndex(1)
            self.interval_spin.setValue(job.schedule_interval_minutes)
        elif job.schedule_type == JobScheduleType.WEEKLY.value:
            self.schedule_combo.setCurrentIndex(2)
        elif job.schedule_type == JobScheduleType.MANUAL.value:
            self.schedule_combo.setCurrentIndex(3)
        else:
            self.schedule_combo.setCurrentIndex(0)

        try:
            h, m = map(int, job.schedule_time_of_day.split(":"))
            self.hour_spin.setValue(h)
            self.min_spin.setValue(m)
        except Exception:
            pass

        if job.backup_mode == BackupMode.COPY.value:
            self.copy_radio.setChecked(True)
        else:
            self.sync_radio.setChecked(True)

        self.delete_excluded_cb.setChecked(job.delete_excluded)
        if job.exclude_patterns:
            self.exclude_edit.setPlainText("\n".join(job.exclude_patterns))

    def _validate_and_save(self):
        name = self.name_input.text().strip()
        source = self.source_input.text().strip()
        bucket = self.bucket_combo.currentText().strip()

        if not name:
            QMessageBox.warning(self, "Validation Error", "Please provide a name for this backup job.")
            return
        if not source:
            QMessageBox.warning(self, "Validation Error", "Please specify the source folder to back up.")
            return
        if not os.path.exists(source):
            QMessageBox.warning(self, "Validation Error", f"Source path does not exist:\n{source}")
            return
        if not bucket:
            QMessageBox.warning(self, "Validation Error", "Please select or enter a target R2 bucket.")
            return

        sched_idx = self.schedule_combo.currentIndex()
        if sched_idx == 1:
            sched_type = JobScheduleType.INTERVAL.value
        elif sched_idx == 2:
            sched_type = JobScheduleType.WEEKLY.value
        elif sched_idx == 3:
            sched_type = JobScheduleType.MANUAL.value
        else:
            sched_type = JobScheduleType.DAILY.value

        time_str = f"{self.hour_spin.value():02d}:{self.min_spin.value():02d}"
        excludes = [line.strip() for line in self.exclude_edit.toPlainText().splitlines() if line.strip()]

        if self.job:
            self.job.name = name
            self.job.source_path = source
            self.job.bucket_name = bucket
            self.job.remote_prefix = self.prefix_input.text().strip()
            self.job.schedule_type = sched_type
            self.job.schedule_interval_minutes = self.interval_spin.value()
            self.job.schedule_time_of_day = time_str
            self.job.backup_mode = BackupMode.COPY.value if self.copy_radio.isChecked() else BackupMode.SYNC.value
            self.job.delete_excluded = self.delete_excluded_cb.isChecked()
            self.job.exclude_patterns = excludes
        else:
            self.job = BackupJob(
                name=name,
                source_path=source,
                bucket_name=bucket,
                remote_prefix=self.prefix_input.text().strip(),
                schedule_type=sched_type,
                schedule_interval_minutes=self.interval_spin.value(),
                schedule_time_of_day=time_str,
                backup_mode=BackupMode.COPY.value if self.copy_radio.isChecked() else BackupMode.SYNC.value,
                delete_excluded=self.delete_excluded_cb.isChecked(),
                exclude_patterns=excludes,
                enabled=True,
            )

        self.accept()
