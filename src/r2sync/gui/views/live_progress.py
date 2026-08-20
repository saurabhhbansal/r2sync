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



def format_bytes(num: float) -> str:
    """Human-readable byte count with a unit that suits the magnitude."""
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(num)} B"
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def format_speed(bytes_per_sec: float) -> str:
    return f"{format_bytes(bytes_per_sec)}/s"


def format_duration(seconds: Optional[int]) -> str:
    """Render an ETA as a compact h/m/s string."""
    if not seconds or seconds < 0:
        return "--"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


def _elide(text: str, limit: int = 55) -> str:
    return text if len(text) <= limit else "..." + text[-(limit - 3):]


class LiveProgressWidget(QFrame):
    """Card widget showing ongoing backup and sync transfers."""

    cancel_requested = Signal(int)

    TITLES = {
        "upload": "Uploading to Cloudflare R2...",
        "download": "Downloading from Cloudflare R2...",
        "sync": "Sync in Progress...",
    }

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
        self.title_label = QLabel("Sync in Progress...")
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

        phase = event_data.get("phase", "transferring")
        totals_final = bool(event_data.get("totals_final", True))
        direction = event_data.get("direction", "sync")

        self.title_label.setText(self.TITLES.get(direction, "Sync in Progress..."))

        speed = event_data.get("speed_bytes_per_sec", 0.0) or 0.0
        eta = event_data.get("eta_seconds")
        done = event_data.get("bytes_transferred", 0) or 0
        total = event_data.get("total_bytes", 0) or 0

        if totals_final and total > 0:
            # The transfer queue is complete, so this denominator is real.
            pct = int(event_data.get("percentage", 0))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)

            files_done = event_data.get("files_transferred", 0) or 0
            files_total = event_data.get("total_files", 0) or 0
            detail = f"{format_bytes(done)} / {format_bytes(total)}"
            if files_total:
                detail += f"  ·  {files_done}/{files_total} files"
            detail += f"  ·  {format_speed(speed)}"
            if eta:
                detail += f"  ·  ETA {format_duration(eta)}"
            self.stats_label.setText(detail)

            curr_file = event_data.get("current_file") or "Transferring files..."
            self.file_label.setText(_elide(curr_file))
        else:
            # rclone is still enumerating: the total is only what has been
            # discovered so far, so it is labelled as such and the bar stays
            # indeterminate rather than implying a meaningful percentage.
            self.progress_bar.setRange(0, 0)

            checked = event_data.get("checks_done", 0) or 0
            discovered = event_data.get("estimated_total_bytes", 0) or total
            detail = f"Scanned {checked:,} · {format_bytes(discovered)} discovered"
            if speed:
                detail += f"  ·  {format_speed(speed)}"
            self.stats_label.setText(detail)

            label = "Checking for changes..." if phase == "scanning" else "Preparing transfer..."
            self.file_label.setText(label)

    def on_job_completed(self, run_data: dict):
        if run_data.get("job_id") == self.current_job_id:
            self.reset()

    def reset(self):
        """Hide the card and restore the bar to a determinate idle state."""
        self.hide()
        self.current_job_id = None
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.title_label.setText("Sync in Progress...")
        self.file_label.setText("Preparing files...")
        self.stats_label.setText("")
