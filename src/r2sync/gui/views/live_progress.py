"""Live progress widget displaying real-time backup metrics matching Stitch Design."""

from typing import Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class LiveProgressWidget(QFrame):
    """Card widget showing ongoing backup and sync transfers."""

    cancel_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cardWidget")
        self.setStyleSheet("""
            QFrame#cardWidget {
                border: 1px solid #F6821F;
                background-color: #1D2024;
                border-radius: 10px;
                padding: 14px;
            }
        """)
        self.current_job_id: Optional[int] = None
        self._init_ui()
        self.hide()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(4, 4, 4, 4)

        # Header row
        header_row = QHBoxLayout()
        self.title_label = QLabel("⚡ Syncing in Progress...")
        self.title_label.setStyleSheet("font-weight: 600; color: #FFB786; font-size: 14px;")
        header_row.addWidget(self.title_label)
        header_row.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("dangerBtn")
        self.cancel_btn.setStyleSheet("padding: 4px 12px; font-size: 11px; font-weight: 600;")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        header_row.addWidget(self.cancel_btn)
        layout.addLayout(header_row)

        # Progress bar (sleek 6px)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #272A2E;
                border-radius: 3px;
                height: 6px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F6821F, stop:1 #FFB786);
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Details row
        details_row = QHBoxLayout()
        self.file_label = QLabel("Preparing files...")
        self.file_label.setStyleSheet("color: #E1E2E8; font-size: 12px; font-family: monospace;")
        details_row.addWidget(self.file_label, stretch=2)

        self.stats_label = QLabel("0 MB / 0 MB (0 KB/s)")
        self.stats_label.setAlignment(Qt.AlignRight)
        self.stats_label.setStyleSheet("color: #A58C7D; font-size: 12px; font-weight: 500;")
        details_row.addWidget(self.stats_label, stretch=1)
        layout.addLayout(details_row)

    def _on_cancel_clicked(self):
        if self.current_job_id is not None:
            self.cancel_requested.emit(self.current_job_id)

    def update_progress(self, event_data: dict):
        self.show()
        job_id = event_data.get("job_id", 0)
        self.current_job_id = job_id

        pct = int(event_data.get("percentage", 0))
        self.progress_bar.setValue(pct)

        curr_file = event_data.get("current_file") or "Transferring files..."
        if len(curr_file) > 55:
            curr_file = "..." + curr_file[-52:]
        self.file_label.setText(curr_file)

        done_mb = round(event_data.get("bytes_transferred", 0) / (1024 * 1024), 1)
        total_mb = round(event_data.get("total_bytes", 0) / (1024 * 1024), 1)
        speed = event_data.get("speed_bytes_per_sec", 0.0)

        if speed > 1024 * 1024:
            speed_str = f"{round(speed / (1024 * 1024), 1)} MB/s"
        else:
            speed_str = f"{round(speed / 1024, 0)} KB/s"

        eta = event_data.get("eta_seconds")
        eta_str = f" • ETA: {eta}s" if eta else ""

        self.stats_label.setText(f"{done_mb} MB / {total_mb} MB ({speed_str}){eta_str}")

    def on_job_completed(self, run_data: dict):
        if run_data.get("job_id") == self.current_job_id:
            self.hide()
            self.current_job_id = None
