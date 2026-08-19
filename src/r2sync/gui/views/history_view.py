"""Activity and history view matching Stitch Activity design."""

import os
from datetime import datetime
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class LogViewerDialog(QDialog):
    """Modal displaying raw execution logs for a backup run."""

    def __init__(self, log_path: str, run_id: int, parent=None):
        super().__init__(parent)
        self.log_path = log_path
        self.setWindowTitle(f"Run #{run_id} Execution Log")
        self.resize(700, 500)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet("font-family: monospace; font-size: 12px; background-color: #0B0E12; border: 1px solid #272A2E; color: #E1E2E8;")
        layout.addWidget(self.text_edit)

        # Load file
        if log_path and os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    self.text_edit.setPlainText(f.read())
            except Exception as e:
                self.text_edit.setPlainText(f"Failed to read log file: {e}")
        else:
            self.text_edit.setPlainText("Log file is not available or has expired.")

        # Bottom buttons
        btn_row = QHBoxLayout()
        export_btn = QPushButton("Export Log File...")
        export_btn.setObjectName("secondaryBtn")
        export_btn.clicked.connect(self._export_log)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        btn_row.addWidget(export_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _export_log(self):
        dest, _ = QFileDialog.getSaveFileName(self, "Export Log", "r2sync_run.log", "Log Files (*.log);;All Files (*)")
        if dest:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(self.text_edit.toPlainText())


class HistoryView(QWidget):
    """View displaying completed backup runs and detailed records matching Stitch Activity design."""

    refresh_requested = Signal()
    load_transfers_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.runs_data = []
        self.transfers_data = []
        self.filter_mode = "all"
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(14)

        # -------------------------------------------------------------
        # Header & Actions
        # -------------------------------------------------------------
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        title = QLabel("Activity")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Review your recent sync and backup events.")
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("secondaryBtn")
        refresh_btn.setStyleSheet("padding: 8px 14px; font-size: 13px;")
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        header.addWidget(refresh_btn)

        main_layout.addLayout(header)

        # -------------------------------------------------------------
        # Filter Chips (Stitch Component: All, Backups, Sync, Errors)
        # -------------------------------------------------------------
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)

        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)

        for idx, (label, mode) in enumerate([
            ("All", "all"),
            ("Backups", "backup"),
            ("Sync", "sync"),
            ("Errors", "error"),
        ]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setObjectName("chipBtn")
            if idx == 0:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, m=mode: self._on_filter_changed(m))
            self.chip_group.addButton(btn, idx)
            chips_row.addWidget(btn)

        chips_row.addStretch()
        main_layout.addLayout(chips_row)

        # -------------------------------------------------------------
        # 2-Pane Splitter: Left (Runs / Events), Right (Drawer Details)
        # -------------------------------------------------------------
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(8)

        # Left Pane: Runs Table Card
        left_frame = QFrame()
        left_frame.setObjectName("cardWidget")
        left_layout = QVBoxLayout(left_frame)
        left_layout.setSpacing(10)

        self.runs_table = QTableWidget(0, 6)
        self.runs_table.setHorizontalHeaderLabels([
            "ID", "Job / Target", "Status", "Started", "Duration", "Transferred"
        ])
        self.runs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (0, 2, 3, 4, 5):
            self.runs_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.runs_table.verticalHeader().setVisible(False)
        self.runs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.runs_table.setSelectionMode(QTableWidget.SingleSelection)
        self.runs_table.itemSelectionChanged.connect(self._on_run_selected)
        left_layout.addWidget(self.runs_table)

        splitter.addWidget(left_frame)

        # Right Pane: Activity Details Drawer (Stitch Drawer Component)
        self.drawer_frame = QFrame()
        self.drawer_frame.setObjectName("cardWidget")
        self.drawer_frame.setMinimumWidth(320)
        self.drawer_frame.setMaximumWidth(400)
        drawer_layout = QVBoxLayout(self.drawer_frame)
        drawer_layout.setSpacing(14)
        drawer_layout.setContentsMargins(16, 16, 16, 16)

        # Drawer Header
        d_header = QHBoxLayout()
        d_title = QLabel("Activity Details")
        d_title.setStyleSheet("font-size: 15px; font-weight: 600; color: #E1E2E8;")
        d_header.addWidget(d_title)
        d_header.addStretch()
        drawer_layout.addLayout(d_header)

        # Event Highlight Box
        self.event_hl_box = QFrame()
        self.event_hl_box.setStyleSheet("background-color: #111418; border: 1px solid #272A2E; border-radius: 8px; padding: 10px;")
        hl_l = QHBoxLayout(self.event_hl_box)
        hl_l.setSpacing(10)

        self.hl_icon = QLabel("●")
        self.hl_icon.setAlignment(Qt.AlignCenter)
        self.hl_icon.setFixedSize(36, 36)
        self.hl_icon.setStyleSheet("background-color: rgba(74, 225, 118, 0.12); color: #4AE176; border-radius: 18px; font-size: 16px; font-weight: bold;")
        hl_l.addWidget(self.hl_icon)

        hl_text = QVBoxLayout()
        hl_text.setSpacing(2)
        self.hl_name = QLabel("Select an event")
        self.hl_name.setStyleSheet("font-size: 14px; font-weight: 600; color: #E1E2E8;")
        self.hl_sub = QLabel("No event selected")
        self.hl_sub.setStyleSheet("font-size: 11px; color: #A58C7D;")
        hl_text.addWidget(self.hl_name)
        hl_text.addWidget(self.hl_sub)
        hl_l.addLayout(hl_text)
        hl_l.addStretch()

        drawer_layout.addWidget(self.event_hl_box)

        # Metadata Grid
        meta_grid = QGridLayout()
        meta_grid.setSpacing(10)

        meta_grid.addWidget(QLabel("Started:"), 0, 0)
        self.d_started = QLabel("—")
        self.d_started.setStyleSheet("color: #E1E2E8; font-weight: 500;")
        meta_grid.addWidget(self.d_started, 0, 1)

        meta_grid.addWidget(QLabel("Duration:"), 1, 0)
        self.d_duration = QLabel("—")
        self.d_duration.setStyleSheet("color: #E1E2E8; font-weight: 500;")
        meta_grid.addWidget(self.d_duration, 1, 1)

        meta_grid.addWidget(QLabel("Transferred:"), 2, 0)
        self.d_transferred = QLabel("—")
        self.d_transferred.setStyleSheet("color: #FFB786; font-weight: 500;")
        meta_grid.addWidget(self.d_transferred, 2, 1)

        drawer_layout.addLayout(meta_grid)

        # Affected Files Preview Header
        files_hdr = QLabel("AFFECTED FILES")
        files_hdr.setStyleSheet("color: #A58C7D; font-size: 10px; font-weight: 600; letter-spacing: 0.04em;")
        drawer_layout.addWidget(files_hdr)

        self.transfers_table = QTableWidget(0, 2)
        self.transfers_table.setHorizontalHeaderLabels(["File Path", "Size"])
        self.transfers_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.transfers_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.transfers_table.verticalHeader().setVisible(False)
        self.transfers_table.setSelectionBehavior(QTableWidget.SelectRows)
        drawer_layout.addWidget(self.transfers_table)

        # View Log Action Button
        self.view_log_btn = QPushButton("View Technical Details")
        self.view_log_btn.setObjectName("secondaryBtn")
        self.view_log_btn.setEnabled(False)
        self.view_log_btn.setStyleSheet("padding: 8px 12px; font-size: 12px;")
        self.view_log_btn.clicked.connect(self._open_log_viewer)
        drawer_layout.addWidget(self.view_log_btn)

        splitter.addWidget(self.drawer_frame)
        splitter.setSizes([500, 320])

        main_layout.addWidget(splitter)

    def _on_filter_changed(self, mode: str):
        self.filter_mode = mode
        self._populate_runs()

    def set_runs(self, runs: list):
        import json
        runs_json = json.dumps(runs, sort_keys=True)
        if hasattr(self, "_last_runs_json") and self._last_runs_json == runs_json:
            return
        self._last_runs_json = runs_json

        self.runs_data = runs
        self._populate_runs()

    def _populate_runs(self):
        filtered = []
        for r in self.runs_data:
            st = (r.get("status") or "").lower()
            name = (r.get("job_name") or "").lower()
            if self.filter_mode == "error" and st != "failed":
                continue
            elif self.filter_mode == "backup" and "sync" in name:
                continue
            elif self.filter_mode == "sync" and "sync" not in name:
                continue
            filtered.append(r)

        self.runs_table.setRowCount(len(filtered))
        for row, r in enumerate(filtered):
            r_id = QTableWidgetItem(f"#{r.get('id', 0)}")
            job_name = QTableWidgetItem(r.get("job_name", ""))

            st = r.get("status", "unknown").upper()
            status_item = QTableWidgetItem(f"● {st}")
            if st == "COMPLETED":
                status_item.setForeground(Qt.green)
            elif st == "FAILED":
                status_item.setForeground(Qt.red)
            elif st == "RUNNING":
                status_item.setForeground(Qt.cyan)

            started = r.get("started_at", "")
            try:
                started_str = datetime.fromisoformat(started).strftime("%b %d, %H:%M")
            except Exception:
                started_str = started[:16]
            started_item = QTableWidgetItem(started_str)

            dur = f"{r.get('duration_seconds', 0.0)}s"
            dur_item = QTableWidgetItem(dur)

            mb = round(r.get("bytes_transferred", 0) / (1024 * 1024), 2)
            trans_str = f"{r.get('files_transferred', 0)} files ({mb} MB)"
            trans_item = QTableWidgetItem(trans_str)

            self.runs_table.setItem(row, 0, r_id)
            self.runs_table.setItem(row, 1, job_name)
            self.runs_table.setItem(row, 2, status_item)
            self.runs_table.setItem(row, 3, started_item)
            self.runs_table.setItem(row, 4, dur_item)
            self.runs_table.setItem(row, 5, trans_item)

        if filtered and self.runs_table.currentRow() < 0:
            self.runs_table.selectRow(0)

    def _on_run_selected(self):
        row = self.runs_table.currentRow()
        if 0 <= row < len(self.runs_data):
            run = self.runs_data[row]
            run_id = run.get("id", 0)
            self.view_log_btn.setEnabled(bool(run.get("log_file_path")))

            # Update drawer
            job_name = run.get("job_name", "Backup")
            st = (run.get("status") or "").upper()
            self.hl_name.setText(job_name)

            if st == "COMPLETED":
                self.hl_icon.setText("●")
                self.hl_icon.setStyleSheet("background-color: rgba(74, 225, 118, 0.12); color: #4AE176; border-radius: 18px; font-size: 16px; font-weight: bold;")
                self.hl_sub.setText("Completed successfully")
            elif st == "FAILED":
                self.hl_icon.setText("●")
                self.hl_icon.setStyleSheet("background-color: rgba(220, 38, 38, 0.15); color: #FFB4AB; border-radius: 18px; font-size: 16px; font-weight: bold;")
                self.hl_sub.setText("Failed / Execution error")
            else:
                self.hl_icon.setText("●")
                self.hl_icon.setStyleSheet("background-color: rgba(56, 189, 248, 0.15); color: #38BDF8; border-radius: 18px; font-size: 16px;")
                self.hl_sub.setText(f"Status: {st}")

            started = run.get("started_at", "")
            try:
                self.d_started.setText(datetime.fromisoformat(started).strftime("%b %d, %H:%M:%S"))
            except Exception:
                self.d_started.setText(started[:19])

            self.d_duration.setText(f"{run.get('duration_seconds', 0.0)} seconds")

            mb = round(run.get("bytes_transferred", 0) / (1024 * 1024), 2)
            self.d_transferred.setText(f"{run.get('files_transferred', 0)} files ({mb} MB)")

            self.load_transfers_requested.emit(run_id)

    def set_transfers(self, transfers: list):
        self.transfers_data = transfers
        self.transfers_table.setRowCount(len(transfers))
        for row, t in enumerate(transfers):
            p_item = QTableWidgetItem(os.path.basename(t.get("file_path", "")))
            p_item.setToolTip(t.get("file_path", ""))

            sz = t.get("size_bytes", 0)
            if sz > 1024 * 1024:
                sz_str = f"{round(sz / (1024*1024), 1)} MB"
            elif sz > 1024:
                sz_str = f"{round(sz / 1024, 0)} KB"
            else:
                sz_str = f"{sz} B"
            sz_item = QTableWidgetItem(sz_str)

            self.transfers_table.setItem(row, 0, p_item)
            self.transfers_table.setItem(row, 1, sz_item)

    def _open_log_viewer(self):
        row = self.runs_table.currentRow()
        if 0 <= row < len(self.runs_data):
            run = self.runs_data[row]
            dlg = LogViewerDialog(run.get("log_file_path", ""), run.get("id", 0), self)
            dlg.exec()
