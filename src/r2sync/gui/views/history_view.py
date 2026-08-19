"""History and activity logs view."""

import os
from datetime import datetime
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
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
        self.text_edit.setStyleSheet("font-family: monospace; font-size: 12px; background-color: #0F131D;")
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
        export_btn = QPushButton("💾 Export Log File...")
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
    """View displaying completed backup runs and detailed file records."""

    refresh_requested = Signal()
    load_transfers_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.runs_data = []
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Activity & Run History")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Inspect previous backup runs, file transfer records, and sync activity logs")
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setObjectName("secondaryBtn")
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        header.addWidget(refresh_btn)
        main_layout.addLayout(header)

        from PySide6.QtWidgets import QTabWidget
        self.tabs = QTabWidget()

        # TAB 1: Backup Runs & File Transfers
        tab1_widget = QWidget()
        tab1_layout = QVBoxLayout(tab1_widget)
        tab1_layout.setContentsMargins(0, 8, 0, 0)

        # Splitter: Top (Runs table), Bottom (File transfers in selected run)
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(8)

        # Runs Table Frame
        runs_frame = QFrame()
        runs_frame.setObjectName("cardWidget")
        runs_layout = QVBoxLayout(runs_frame)
        runs_layout.setSpacing(8)
        runs_layout.addWidget(QLabel("<b>Backup Execution Runs:</b>"))

        self.runs_table = QTableWidget(0, 7)
        self.runs_table.setHorizontalHeaderLabels([
            "ID", "Job Name", "Status", "Started", "Duration", "Transferred", "Errors"
        ])
        self.runs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (0, 2, 3, 4, 5, 6):
            self.runs_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.runs_table.verticalHeader().setVisible(False)
        self.runs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.runs_table.setSelectionMode(QTableWidget.SingleSelection)
        self.runs_table.itemSelectionChanged.connect(self._on_run_selected)
        runs_layout.addWidget(self.runs_table)

        splitter.addWidget(runs_frame)

        # File Transfers Frame
        transfers_frame = QFrame()
        transfers_frame.setObjectName("cardWidget")
        transfers_layout = QVBoxLayout(transfers_frame)
        transfers_layout.setSpacing(8)

        tf_header = QHBoxLayout()
        self.transfers_title = QLabel("<b>Files in Selected Run:</b>")
        tf_header.addWidget(self.transfers_title)
        tf_header.addStretch()

        self.view_log_btn = QPushButton("📄 View Raw Log")
        self.view_log_btn.setObjectName("secondaryBtn")
        self.view_log_btn.setEnabled(False)
        self.view_log_btn.clicked.connect(self._open_log_viewer)
        tf_header.addWidget(self.view_log_btn)
        transfers_layout.addLayout(tf_header)

        self.transfers_table = QTableWidget(0, 4)
        self.transfers_table.setHorizontalHeaderLabels(["File Path", "Status", "Size", "Error / Details"])
        self.transfers_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.transfers_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.transfers_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.transfers_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.transfers_table.verticalHeader().setVisible(False)
        self.transfers_table.setSelectionBehavior(QTableWidget.SelectRows)
        transfers_layout.addWidget(self.transfers_table)

        splitter.addWidget(transfers_frame)
        splitter.setSizes([260, 260])
        tab1_layout.addWidget(splitter)
        self.tabs.addTab(tab1_widget, "📦 Backup Runs")

        # TAB 2: Activity Events & System Log
        tab2_widget = QWidget()
        tab2_layout = QVBoxLayout(tab2_widget)
        tab2_layout.setContentsMargins(0, 8, 0, 0)
        tab2_frame = QFrame()
        tab2_frame.setObjectName("cardWidget")
        t2_l = QVBoxLayout(tab2_frame)

        self.activities_table = QTableWidget(0, 4)
        self.activities_table.setHorizontalHeaderLabels(["Timestamp", "Level", "Category", "Event Message"])
        self.activities_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.activities_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.activities_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.activities_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.activities_table.verticalHeader().setVisible(False)
        self.activities_table.setSelectionBehavior(QTableWidget.SelectRows)
        t2_l.addWidget(self.activities_table)
        tab2_layout.addWidget(tab2_frame)
        self.tabs.addTab(tab2_widget, "📋 Activity Log (Sync & Backups)")

        main_layout.addWidget(self.tabs)


    def set_runs(self, runs: list):
        self.runs_data = runs
        self.runs_table.setRowCount(len(runs))

        for row, r in enumerate(runs):
            r_id = QTableWidgetItem(f"#{r.get('id', 0)}")
            job_name = QTableWidgetItem(r.get("job_name", ""))
            
            st = r.get("status", "unknown").upper()
            status_item = QTableWidgetItem(st)
            if st == "COMPLETED":
                status_item.setForeground(Qt.green)
            elif st == "FAILED":
                status_item.setForeground(Qt.red)
            elif st == "RUNNING":
                status_item.setForeground(Qt.cyan)

            started = r.get("started_at", "")
            try:
                started_str = datetime.fromisoformat(started).strftime("%b %d, %H:%M:%S")
            except Exception:
                started_str = started[:19]
            started_item = QTableWidgetItem(started_str)

            dur = f"{r.get('duration_seconds', 0.0)}s"
            dur_item = QTableWidgetItem(dur)

            mb = round(r.get("bytes_transferred", 0) / (1024 * 1024), 2)
            trans_str = f"{r.get('files_transferred', 0)} files ({mb} MB)"
            trans_item = QTableWidgetItem(trans_str)

            err_count = r.get("errors_count", 0)
            err_item = QTableWidgetItem(str(err_count))
            if err_count > 0:
                err_item.setForeground(Qt.red)

            self.runs_table.setItem(row, 0, r_id)
            self.runs_table.setItem(row, 1, job_name)
            self.runs_table.setItem(row, 2, status_item)
            self.runs_table.setItem(row, 3, started_item)
            self.runs_table.setItem(row, 4, dur_item)
            self.runs_table.setItem(row, 5, trans_item)
            self.runs_table.setItem(row, 6, err_item)

        if runs and self.runs_table.currentRow() < 0:
            self.runs_table.selectRow(0)

    def _on_run_selected(self):
        row = self.runs_table.currentRow()
        if 0 <= row < len(self.runs_data):
            run = self.runs_data[row]
            run_id = run.get("id", 0)
            self.view_log_btn.setEnabled(bool(run.get("log_file_path")))
            self.load_transfers_requested.emit(run_id)

    def set_transfers(self, transfers: list):
        self.transfers_table.setRowCount(len(transfers))
        for row, t in enumerate(transfers):
            p_item = QTableWidgetItem(t.get("file_path", ""))
            
            st = t.get("status", "")
            st_item = QTableWidgetItem(st.upper())
            if st == "transferred":
                st_item.setForeground(Qt.green)
            elif st == "deleted":
                st_item.setForeground(Qt.yellow)
            elif st == "error":
                st_item.setForeground(Qt.red)

            sz = t.get("size_bytes", 0)
            if sz > 1024 * 1024:
                sz_str = f"{round(sz / (1024*1024), 2)} MB"
            elif sz > 1024:
                sz_str = f"{round(sz / 1024, 1)} KB"
            else:
                sz_str = f"{sz} B"
            sz_item = QTableWidgetItem(sz_str)

            err_item = QTableWidgetItem(t.get("error_message") or "")

            self.transfers_table.setItem(row, 0, p_item)
            self.transfers_table.setItem(row, 1, st_item)
            self.transfers_table.setItem(row, 2, sz_item)
            self.transfers_table.setItem(row, 3, err_item)

    def _open_log_viewer(self):
        row = self.runs_table.currentRow()
        if 0 <= row < len(self.runs_data):
            run = self.runs_data[row]
            dlg = LogViewerDialog(run.get("log_file_path", ""), run.get("id", 0), self)
            dlg.exec()

    def set_activities(self, activities: list):
        self.activities_table.setRowCount(len(activities))
        for row, a in enumerate(activities):
            created = a.get("created_at", "")
            try:
                created_str = datetime.fromisoformat(created).strftime("%b %d, %H:%M:%S")
            except Exception:
                created_str = created[:19]
            ts_item = QTableWidgetItem(created_str)

            lvl = a.get("level", "INFO").upper()
            lvl_item = QTableWidgetItem(lvl)
            if lvl == "ERROR":
                lvl_item.setForeground(Qt.red)
            elif lvl == "WARNING":
                lvl_item.setForeground(Qt.yellow)
            else:
                lvl_item.setForeground(Qt.cyan)

            cat = a.get("category", "system").upper()
            cat_item = QTableWidgetItem(cat)

            msg = a.get("message", "")
            msg_item = QTableWidgetItem(msg)

            self.activities_table.setItem(row, 0, ts_item)
            self.activities_table.setItem(row, 1, lvl_item)
            self.activities_table.setItem(row, 2, cat_item)
            self.activities_table.setItem(row, 3, msg_item)

