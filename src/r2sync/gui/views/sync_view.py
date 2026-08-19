"""Sync View displaying synchronized folders, connected computers, conflicts, and controls."""

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
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from r2sync.core.models import SyncStatus


class DatasetCardWidget(QFrame):
    """Card widget representing a synchronized dataset folder."""

    sync_now_clicked = Signal(str)
    pause_toggle_clicked = Signal(str, bool)  # dataset_id, is_paused
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
        layout.setSpacing(10)

        # Top Row: Title, Status Badge, Action Buttons
        top_row = QHBoxLayout()

        icon_lbl = QLabel("🔄")
        icon_lbl.setStyleSheet("font-size: 16px;")
        top_row.addWidget(icon_lbl)

        title_lbl = QLabel(self.dataset.get("name", "Unnamed Sync Dataset"))
        title_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFFFF;")
        top_row.addWidget(title_lbl)

        # Status badge
        status = self.dataset.get("status", "waiting").lower()
        paused = self.dataset.get("paused", False)
        
        status_lbl = QLabel()
        if paused:
            status_lbl.setText(" PAUSED ")
            status_lbl.setStyleSheet("background-color: #334155; color: #94A3B8; border-radius: 4px; font-size: 11px; font-weight: bold;")
        elif status == "synced":
            status_lbl.setText(" ✓ SYNCED ")
            status_lbl.setStyleSheet("background-color: #065F46; color: #34D399; border-radius: 4px; font-size: 11px; font-weight: bold;")
        elif status == "syncing":
            status_lbl.setText(" ⟳ SYNCING ")
            status_lbl.setStyleSheet("background-color: #1E3A8A; color: #60A5FA; border-radius: 4px; font-size: 11px; font-weight: bold;")
        elif status == "conflict":
            status_lbl.setText(" ⚠️ CONFLICT ")
            status_lbl.setStyleSheet("background-color: #78350F; color: #FBBF24; border-radius: 4px; font-size: 11px; font-weight: bold;")
        elif status == "needs_attention":
            status_lbl.setText(" ⛔ ATTENTION ")
            status_lbl.setStyleSheet("background-color: #7F1D1D; color: #F87171; border-radius: 4px; font-size: 11px; font-weight: bold;")
        else:
            status_lbl.setText(f" {status.upper()} ")
            status_lbl.setStyleSheet("background-color: #1E293B; color: #94A3B8; border-radius: 4px; font-size: 11px;")
        top_row.addWidget(status_lbl)

        top_row.addStretch()

        # Action Buttons
        sync_btn = QPushButton("▶ Sync Now")
        sync_btn.setStyleSheet("padding: 4px 10px; font-size: 12px;")
        sync_btn.clicked.connect(lambda: self.sync_now_clicked.emit(self.dataset_id))
        top_row.addWidget(sync_btn)

        pause_btn = QPushButton("▶ Resume" if paused else "⏸ Pause")
        pause_btn.setObjectName("secondaryBtn")
        pause_btn.setStyleSheet("padding: 4px 10px; font-size: 12px;")
        pause_btn.clicked.connect(lambda: self.pause_toggle_clicked.emit(self.dataset_id, not paused))
        top_row.addWidget(pause_btn)

        comp_btn = QPushButton("🖥️ Computers")
        comp_btn.setObjectName("secondaryBtn")
        comp_btn.setStyleSheet("padding: 4px 10px; font-size: 12px;")
        comp_btn.clicked.connect(lambda: self.manage_computers_clicked.emit(self.dataset_id))
        top_row.addWidget(comp_btn)

        del_btn = QPushButton("🗑")
        del_btn.setObjectName("dangerBtn")
        del_btn.setStyleSheet("padding: 4px 8px; font-size: 12px;")
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.dataset_id))
        top_row.addWidget(del_btn)

        layout.addLayout(top_row)

        # Middle Row: Path Mapping & Open Folder button
        paths_row = QHBoxLayout()
        local_p = self.dataset.get("local_path", "")
        bkt = self.dataset.get("bucket_name", "")
        pfx = self.dataset.get("remote_prefix", "")

        path_lbl = QLabel(f"📁 <b>Local:</b> {local_p}  →  ☁️ <b>R2:</b> {bkt}/{pfx}/data")
        path_lbl.setStyleSheet("color: #CBD5E1; font-size: 12px;")
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        paths_row.addWidget(path_lbl)
        paths_row.addStretch()

        open_btn = QPushButton("Open Folder ↗")
        open_btn.setObjectName("secondaryBtn")
        open_btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        open_btn.clicked.connect(self._open_local_folder)
        paths_row.addWidget(open_btn)

        layout.addLayout(paths_row)

        # Bottom Row: Stats & Metadata
        meta_row = QHBoxLayout()

        cnt = self.dataset.get("total_files", 0)
        sz = self.dataset.get("total_bytes", 0)
        if sz > 1024**3:
            sz_str = f"{round(sz / (1024**3), 2)} GB"
        elif sz > 1024**2:
            sz_str = f"{round(sz / (1024**2), 1)} MB"
        else:
            sz_str = f"{round(sz / 1024, 1)} KB"

        sched = self.dataset.get("schedule_mode", "realtime").title()
        if sched.lower() == "realtime":
            sched_str = "Real-Time Watcher"
        elif sched.lower() == "interval":
            sched_str = f"Every {self.dataset.get('schedule_interval_minutes', 15)}m"
        else:
            sched_str = sched

        last_sync = self.dataset.get("last_sync_at")
        if last_sync:
            try:
                last_str = datetime.fromisoformat(last_sync).strftime("%b %d, %H:%M:%S")
            except Exception:
                last_str = last_sync[:19]
        else:
            last_str = "Pending initial sync"

        meta_lbl = QLabel(f"📊 <b>{cnt:,} files ({sz_str})</b> | Schedule: <b>{sched_str}</b> | Last Synced: <b>{last_str}</b>")
        meta_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        meta_row.addWidget(meta_lbl)
        meta_row.addStretch()

        # Last error banner if present
        last_err = self.dataset.get("last_error")
        if last_err:
            err_badge = QLabel(f"⚠️ {last_err[:45]}...")
            err_badge.setStyleSheet("color: #F87171; font-size: 11px; font-weight: bold;")
            meta_row.addWidget(err_badge)

        layout.addLayout(meta_row)

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
    """Main view for managing multi-PC synchronization."""

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

        # Header
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Sync")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Your computers stay up to date through Cloudflare R2")
        subtitle.setObjectName("subtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        add_btn = QPushButton("➕ Add Sync Folder")
        add_btn.clicked.connect(self.add_sync_requested.emit)
        header.addWidget(add_btn)

        setup_btn = QPushButton("💻 Set Up This PC")
        setup_btn.setObjectName("secondaryBtn")
        setup_btn.clicked.connect(self.setup_pc_requested.emit)
        header.addWidget(setup_btn)

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setObjectName("secondaryBtn")
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        header.addWidget(refresh_btn)

        main_layout.addLayout(header)

        # Connected Computers Strip Card
        self.devices_frame = QFrame()
        self.devices_frame.setObjectName("cardWidget")
        self.devices_layout = QHBoxLayout(self.devices_frame)
        self.devices_layout.setSpacing(16)

        self.devices_summary_lbl = QLabel("🖥️ <b>Connected Computers:</b> Detecting...")
        self.devices_summary_lbl.setStyleSheet("color: #CBD5E1; font-size: 12px;")
        self.devices_layout.addWidget(self.devices_summary_lbl)
        self.devices_layout.addStretch()

        self.conflicts_badge_btn = QPushButton("⚠️ Conflicts Center (0)")
        self.conflicts_badge_btn.setObjectName("secondaryBtn")
        self.conflicts_badge_btn.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        self.conflicts_badge_btn.clicked.connect(lambda: self.open_conflicts_requested.emit(""))
        self.devices_layout.addWidget(self.conflicts_badge_btn)

        main_layout.addWidget(self.devices_frame)

        # Scroll Area for Datasets Cards
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
                color = "#10B981" if st in ("online", "syncing") else "#64748B"
                dev_names.append(f"<font color='{color}'>●</font> {name}")

            self.devices_summary_lbl.setText("🖥️ <b>Connected Computers:</b>  " + "   •   ".join(dev_names))
        else:
            self.devices_summary_lbl.setText("🖥️ <b>Connected Computers:</b> This PC (Online)")

        # Update Conflicts Badge
        if conflicts_count > 0:
            self.conflicts_badge_btn.setText(f"⚠️ Conflict Center ({conflicts_count} Active)")
            self.conflicts_badge_btn.setStyleSheet("background-color: #78350F; color: #FBBF24; font-weight: bold; border-radius: 4px; padding: 4px 10px;")
            self.conflicts_badge_btn.setVisible(True)
        else:
            self.conflicts_badge_btn.setText("✓ 0 Conflicts")
            self.conflicts_badge_btn.setStyleSheet("background-color: #065F46; color: #34D399; font-weight: 500; border-radius: 4px; padding: 4px 10px;")

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
            el.setSpacing(10)

            lbl1 = QLabel("🔄 Multi-PC Cloud Synchronization")
            lbl1.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF;")
            lbl2 = QLabel(
                "Keep folders continuously synchronized between your desktop, laptop, and work computers.\n"
                "All files sync directly through your personal Cloudflare R2 storage without developer intermediaries."
            )
            lbl2.setAlignment(Qt.AlignCenter)
            lbl2.setStyleSheet("color: #94A3B8; font-size: 13px; max-width: 500px;")

            btn_row = QHBoxLayout()
            btn1 = QPushButton("➕ Add Sync Folder")
            btn1.clicked.connect(self.add_sync_requested.emit)
            btn2 = QPushButton("💻 Connect to Existing Shared Dataset")
            btn2.setObjectName("secondaryBtn")
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
