"""Multi-PC Sync View matching Stitch Design."""

import os
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class DatasetCardWidget(QFrame):
    """Card widget representing a synchronized dataset folder matching Stitch Multi-PC Sync."""

    sync_now_clicked = Signal(str)
    pause_toggle_clicked = Signal(str, bool)
    conflicts_clicked = Signal(str)
    manage_computers_clicked = Signal(str)
    delete_clicked = Signal(str)

    def __init__(self, dataset_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.dataset = dataset_data
        self.dataset_id = dataset_data.get("dataset_id", "")
        self.setObjectName("cardWidget")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # -------------------------------------------------------------
        # Top Bar: Shared Folder Icon + Title + Status + Action Buttons
        # -------------------------------------------------------------
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # Title & Status Subtitle
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_lbl = QLabel(self.dataset.get("name", "Unnamed Sync Dataset"))
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 600; color: #E1E2E8;")
        title_box.addWidget(title_lbl)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)

        status = self.dataset.get("status", "waiting").lower()
        paused = self.dataset.get("paused", False)

        status_lbl = QLabel()
        if paused:
            status_lbl.setText("● PAUSED")
            status_lbl.setStyleSheet("color: #A58C7D; font-size: 11px; font-weight: 600;")
        elif status == "synced":
            status_lbl.setText("● Synced")
            status_lbl.setStyleSheet("color: #4AE176; font-size: 11px; font-weight: 600;")
        elif status == "syncing":
            status_lbl.setText("● Syncing")
            status_lbl.setStyleSheet("color: #38BDF8; font-size: 11px; font-weight: 600;")
        elif status == "conflict":
            status_lbl.setText("● Conflict Detected")
            status_lbl.setStyleSheet("color: #F6821F; font-size: 11px; font-weight: 600;")
        else:
            status_lbl.setText(f"● {status.title()}")
            status_lbl.setStyleSheet("color: #A58C7D; font-size: 11px; font-weight: 500;")
        status_row.addWidget(status_lbl)

        last_sync = self.dataset.get("last_sync_at")
        if last_sync:
            try:
                last_str = datetime.fromisoformat(last_sync).strftime("%b %d, %H:%M")
            except Exception:
                last_str = last_sync[:16]
            time_lbl = QLabel(f"• {last_str}")
        else:
            time_lbl = QLabel("• Just now")
        time_lbl.setStyleSheet("color: #A58C7D; font-size: 11px;")
        status_row.addWidget(time_lbl)
        status_row.addStretch()

        title_box.addLayout(status_row)
        top_row.addLayout(title_box)
        top_row.addStretch()

        # Action Buttons
        sync_btn = QPushButton("Sync")
        sync_btn.setObjectName("secondaryBtn")
        sync_btn.setStyleSheet("padding: 5px 12px; font-size: 12px; font-weight: 500;")
        sync_btn.clicked.connect(lambda: self.sync_now_clicked.emit(self.dataset_id))
        top_row.addWidget(sync_btn)

        pause_btn = QPushButton("Resume" if paused else "Pause")
        pause_btn.setObjectName("secondaryBtn")
        pause_btn.setStyleSheet("padding: 5px 10px; font-size: 12px;")
        pause_btn.clicked.connect(lambda: self.pause_toggle_clicked.emit(self.dataset_id, not paused))
        top_row.addWidget(pause_btn)

        comp_btn = QPushButton("Devices")
        comp_btn.setObjectName("secondaryBtn")
        comp_btn.setStyleSheet("padding: 5px 10px; font-size: 12px;")
        comp_btn.clicked.connect(lambda: self.manage_computers_clicked.emit(self.dataset_id))
        top_row.addWidget(comp_btn)

        del_btn = QPushButton("Delete")
        del_btn.setObjectName("dangerBtn")
        del_btn.setStyleSheet("padding: 5px 10px; font-size: 12px;")
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.dataset_id))
        top_row.addWidget(del_btn)

        layout.addLayout(top_row)

        # -------------------------------------------------------------
        # Middle 2-Column Grid: Paths & Details
        # -------------------------------------------------------------
        paths_grid = QGridLayout()
        paths_grid.setSpacing(12)

        # Local Path Container
        local_p = self.dataset.get("local_path", "")
        loc_box = QFrame()
        loc_box.setObjectName("codeBoxWidget")
        loc_layout = QVBoxLayout(loc_box)
        loc_layout.setContentsMargins(8, 6, 8, 6)
        loc_layout.setSpacing(2)
        loc_title = QLabel("LOCAL PATH")
        loc_title.setStyleSheet("color: #A58C7D; font-size: 10px; font-weight: 600; letter-spacing: 0.04em;")

        loc_row = QHBoxLayout()
        loc_path = QLabel(local_p)
        loc_path.setStyleSheet("color: #E1E2E8; font-family: monospace; font-size: 12px;")
        loc_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        loc_row.addWidget(loc_path)
        loc_row.addStretch()

        open_btn = QPushButton("Open ↗")
        open_btn.setObjectName("secondaryBtn")
        open_btn.setStyleSheet("padding: 2px 6px; font-size: 10px;")
        open_btn.clicked.connect(self._open_local_folder)
        loc_row.addWidget(open_btn)

        loc_layout.addWidget(loc_title)
        loc_layout.addLayout(loc_row)
        paths_grid.addWidget(loc_box, 0, 0)

        # Remote Target Container
        bkt = self.dataset.get("bucket_name", "")
        pfx = self.dataset.get("remote_prefix", "")
        rem_box = QFrame()
        rem_box.setObjectName("codeBoxWidget")
        rem_layout = QVBoxLayout(rem_box)
        rem_layout.setContentsMargins(8, 6, 8, 6)
        rem_layout.setSpacing(2)
        rem_title = QLabel("REMOTE TARGET")
        rem_title.setStyleSheet("color: #A58C7D; font-size: 10px; font-weight: 600; letter-spacing: 0.04em;")
        rem_path = QLabel(f"Cloudflare R2 ({bkt}/{pfx}/data)")
        rem_path.setStyleSheet("color: #FFB786; font-family: monospace; font-size: 12px;")
        rem_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rem_layout.addWidget(rem_title)
        rem_layout.addWidget(rem_path)
        paths_grid.addWidget(rem_box, 0, 1)

        layout.addLayout(paths_grid)

        # -------------------------------------------------------------
        # Footer Row: Files Count + Size + Schedule
        # -------------------------------------------------------------
        meta_frame = QFrame()
        meta_frame.setStyleSheet("border-top: 1px solid #272A2E; padding-top: 8px;")
        meta_row = QHBoxLayout(meta_frame)
        meta_row.setContentsMargins(0, 4, 0, 0)
        meta_row.setSpacing(16)

        cnt = self.dataset.get("total_files", 0)
        sz = self.dataset.get("total_bytes", 0)
        if sz > 1024**3:
            sz_str = f"{round(sz / (1024**3), 2)} GB"
        elif sz > 1024**2:
            sz_str = f"{round(sz / (1024**2), 1)} MB"
        else:
            sz_str = f"{round(sz / 1024, 1)} KB"

        files_lbl = QLabel(f"{cnt:,} files ({sz_str})")
        files_lbl.setStyleSheet("color: #A58C7D; font-size: 12px;")
        meta_row.addWidget(files_lbl)

        sched = self.dataset.get("schedule_mode", "realtime").title()
        if sched.lower() == "realtime":
            sched_str = "Real-Time Watcher"
        elif sched.lower() == "interval":
            sched_str = f"Every {self.dataset.get('schedule_interval_minutes', 15)}m"
        else:
            sched_str = sched

        sched_lbl = QLabel(sched_str)
        sched_lbl.setStyleSheet("color: #A58C7D; font-size: 12px;")
        meta_row.addWidget(sched_lbl)
        meta_row.addStretch()

        # Subtle bottom progress bar line
        progress_bar = QProgressBar()
        progress_bar.setFixedHeight(2)
        progress_bar.setTextVisible(False)
        progress_bar.setRange(0, 100)
        progress_bar.setValue(100)
        progress_bar.setStyleSheet("""
            QProgressBar { background-color: transparent; border: none; }
            QProgressBar::chunk { background-color: #4AE176; }
        """)

        layout.addWidget(meta_frame)
        layout.addWidget(progress_bar)

    def _open_local_folder(self):
        local_path = self.dataset.get("local_path", "")
        if local_path and os.path.exists(local_path):
            if sys.platform == "win32":
                os.startfile(local_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", local_path])
            else:
                subprocess.Popen(["xdg-open", local_path])


class SyncView(QWidget):
    """Main view for managing Multi-PC Synchronization matching Stitch Design."""

    add_sync_requested = Signal()
    setup_pc_requested = Signal()
    manage_computers_requested = Signal(str)
    open_conflicts_requested = Signal(str)
    refresh_requested = Signal()
    sync_now_requested = Signal(str)
    pause_toggle_requested = Signal(str, bool)
    delete_dataset_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.datasets: List[Dict[str, Any]] = []
        self.devices: List[Dict[str, Any]] = []
        self.conflicts_count: int = 0
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # -------------------------------------------------------------
        # Header & Actions
        # -------------------------------------------------------------
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        title = QLabel("Multi-PC Sync")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Keep the same files up to date across your computers.")
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        self.conflicts_btn = QPushButton("Conflicts (0)")
        self.conflicts_btn.setObjectName("secondaryBtn")
        self.conflicts_btn.setStyleSheet("padding: 8px 14px; font-size: 13px;")
        self.conflicts_btn.clicked.connect(lambda: self.open_conflicts_requested.emit(""))
        header.addWidget(self.conflicts_btn)

        setup_btn = QPushButton("Set Up This PC")
        setup_btn.setObjectName("secondaryBtn")
        setup_btn.setStyleSheet("padding: 8px 14px; font-size: 13px;")
        setup_btn.clicked.connect(self.setup_pc_requested.emit)
        header.addWidget(setup_btn)

        add_btn = QPushButton("+ Add Sync Folder")
        add_btn.setStyleSheet("padding: 8px 16px; font-size: 13px; font-weight: 600;")
        add_btn.clicked.connect(self.add_sync_requested.emit)
        header.addWidget(add_btn)

        main_layout.addLayout(header)

        # -------------------------------------------------------------
        # Topology / Connected Devices Card
        # -------------------------------------------------------------
        self.devices_frame = QFrame()
        self.devices_frame.setObjectName("heroCardWidget")
        self.devices_frame.setStyleSheet("""
            QFrame#heroCardWidget {
                background-color: #1D2024;
                border: 1px solid #272A2E;
                border-radius: 12px;
                padding: 14px 18px;
            }
        """)
        dev_layout = QHBoxLayout(self.devices_frame)
        dev_layout.setSpacing(12)

        hub_lbl = QLabel("Cloudflare R2")
        hub_lbl.setStyleSheet("color: #FFB786; font-weight: 600; font-size: 12px; background-color: #111418; padding: 4px 10px; border-radius: 6px; border: 1px solid #323539;")
        dev_layout.addWidget(hub_lbl)

        arrow_lbl = QLabel("⇄")
        arrow_lbl.setStyleSheet("color: #4AE176; font-weight: bold; font-size: 14px;")
        dev_layout.addWidget(arrow_lbl)

        self.devices_summary_lbl = QLabel("Detecting connected computers...")
        self.devices_summary_lbl.setStyleSheet("color: #E1E2E8; font-size: 12px;")
        dev_layout.addWidget(self.devices_summary_lbl)
        dev_layout.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("secondaryBtn")
        refresh_btn.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        dev_layout.addWidget(refresh_btn)

        main_layout.addWidget(self.devices_frame)

        # -------------------------------------------------------------
        # Scroll Area for Datasets Cards
        # -------------------------------------------------------------
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setSpacing(12)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.addStretch()

        self.scroll.setWidget(self.cards_container)
        main_layout.addWidget(self.scroll)

    def set_data(
        self,
        datasets: List[Dict[str, Any]],
        devices: List[Dict[str, Any]],
        conflicts_count: int = 0,
    ):
        self.datasets = datasets or []
        self.devices = devices or []
        self.conflicts_count = conflicts_count

        # Update Connected Computers Strip
        if devices:
            dev_names = []
            for d in devices:
                name = d.get("device_name", "PC")
                if d.get("is_current_device"):
                    name += " (This PC)"
                st = d.get("status", "offline")
                color = "#4AE176" if st in ("online", "syncing") else "#A58C7D"
                dev_names.append(f"<font color='{color}'>●</font> {name}")

            self.devices_summary_lbl.setText("<b>Connected Computers:</b>  " + "   •   ".join(dev_names))
        else:
            self.devices_summary_lbl.setText("<b>Connected Computers:</b> <font color='#4AE176'>●</font> This PC (Online)")

        # Update Conflicts Button
        if conflicts_count > 0:
            self.conflicts_btn.setText(f"Conflicts ({conflicts_count})")
            self.conflicts_btn.setStyleSheet("""
                background-color: rgba(246, 130, 31, 0.15);
                color: #FFB786;
                border: 1px solid #F6821F;
                padding: 8px 14px;
                font-size: 13px;
                font-weight: 600;
            """)
        else:
            self.conflicts_btn.setText("0 Conflicts")
            self.conflicts_btn.setStyleSheet("padding: 8px 14px; font-size: 13px;")

        # Populate Cards
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.datasets:
            empty_frame = QFrame()
            empty_frame.setObjectName("cardWidget")
            el = QVBoxLayout(empty_frame)
            el.setAlignment(Qt.AlignCenter)
            el.setSpacing(12)

            lbl1 = QLabel("Multi-PC Cloud Synchronization")
            lbl1.setStyleSheet("font-size: 16px; font-weight: 600; color: #E1E2E8;")
            lbl2 = QLabel(
                "Keep folders continuously synchronized between your desktop, laptop, and work computers.\n"
                "All files sync directly through your personal Cloudflare R2 storage without developer intermediaries."
            )
            lbl2.setAlignment(Qt.AlignCenter)
            lbl2.setStyleSheet("color: #A58C7D; font-size: 13px; max-width: 500px;")

            btn_row = QHBoxLayout()
            btn1 = QPushButton("+ Add Sync Folder")
            btn1.setStyleSheet("padding: 8px 16px; font-weight: 600;")
            btn1.clicked.connect(self.add_sync_requested.emit)
            btn2 = QPushButton("Connect to Existing Dataset")
            btn2.setObjectName("secondaryBtn")
            btn2.setStyleSheet("padding: 8px 16px;")
            btn2.clicked.connect(self.setup_pc_requested.emit)

            btn_row.addWidget(btn1)
            btn_row.addWidget(btn2)

            el.addWidget(lbl1)
            el.addWidget(lbl2)
            el.addLayout(btn_row)

            self.cards_layout.insertWidget(0, empty_frame)
            return

        for idx, ds in enumerate(self.datasets):
            card = DatasetCardWidget(ds)
            card.sync_now_clicked.connect(self.sync_now_requested.emit)
            card.pause_toggle_clicked.connect(self.pause_toggle_requested.emit)
            card.manage_computers_clicked.connect(self.manage_computers_requested.emit)
            card.delete_clicked.connect(self.delete_dataset_requested.emit)
            self.cards_layout.insertWidget(idx, card)
