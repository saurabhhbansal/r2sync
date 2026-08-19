"""Live progress widget displaying real-time backup metrics."""

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

from r2sync.core.models import TransferProgressEvent


class LiveProgressWidget(QFrame):
    """Card widget showing ongoing backup transfers."""

    cancel_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cardWidget")
        self.setStyleSheet("""
            QFrame#cardWidget {
                border: 1px solid #3B82F6;
                background-color: #1E293B;
            }
        """)
        self.current_job_id: Optional[int] = None
        self._init_ui()
        self.hide()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header row
        header_row = QHBoxLayout()
        self.title_label = QLabel("⚡ Syncing in Progress...")
        self.title_label.setStyleSheet("font-weight: bold; color: #38BDF8; font-size: 14px;")
        header_row.addWidget(self.title_label)
        header_row.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("dangerBtn")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        header_row.addWidget(self.cancel_btn)
        layout.addLayout(header_row)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        layout.addWidget(self.progress_bar)

        # Details row
        details_row = QHBoxLayout()
        self.file_label = QLabel("Preparing files...")
        self.file_label.setStyleSheet("color: #E2E8F0; font-size: 12px;")
        details_row.addWidget(self.file_label, stretch=2)

        self.stats_label = QLabel("0 MB / 0 MB (0 KB/s)")
        self.stats_label.setAlignment(Qt.AlignRight)
        self.stats_label.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: 500;")
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
        if len(curr_file) > 50:
            curr_file = "..." + curr_file[-47:]
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
