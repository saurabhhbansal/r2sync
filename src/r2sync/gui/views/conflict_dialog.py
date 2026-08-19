"""Conflict Center view and modal for reviewing and resolving file synchronization conflicts."""

import os
import subprocess
import sys
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from r2sync.core.models import ConflictResolution


class ConflictCardWidget(QFrame):
    """Card widget representing an individual file conflict with comparison details."""

    resolve_requested = Signal(int, str)  # conflict_id, resolution

    def __init__(self, conflict_data: Dict[str, Any], current_device_name: str = "This PC", parent=None):
        super().__init__(parent)
        self.conflict = conflict_data
        self.conflict_id = conflict_data.get("id", 0)
        self.current_device_name = current_device_name
        self.setObjectName("cardWidget")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header Row: File Name & Badge
        header_row = QHBoxLayout()
        icon_lbl = QLabel("⚠️")
        icon_lbl.setStyleSheet("font-size: 18px;")
        header_row.addWidget(icon_lbl)

        rel_path = self.conflict.get("relative_path", "Unknown file")
        file_name = os.path.basename(rel_path)
        title_lbl = QLabel(f"<b>{file_name}</b> <font color='#94A3B8'>({rel_path})</font>")
        title_lbl.setStyleSheet("font-size: 14px; color: #FFFFFF;")
        header_row.addWidget(title_lbl)
        header_row.addStretch()

        open_folder_btn = QPushButton("📁 Open Folder")
        open_folder_btn.setObjectName("secondaryBtn")
        open_folder_btn.setStyleSheet("padding: 4px 8px; font-size: 11px;")
        open_folder_btn.clicked.connect(self._open_folder)
        header_row.addWidget(open_folder_btn)

        layout.addLayout(header_row)

        # Comparison 2-Column Split Box
        comp_frame = QFrame()
        comp_frame.setStyleSheet("background-color: #0F172A; border-radius: 6px; padding: 8px;")
        comp_layout = QHBoxLayout(comp_frame)
        comp_layout.setSpacing(16)

        # Left Column: Local Version
        local_col = QVBoxLayout()
        local_col.setSpacing(4)
        local_title = QLabel(f"<b>🖥️ {self.current_device_name} (Local Version)</b>")
        local_title.setStyleSheet("color: #38BDF8; font-size: 12px;")
        local_col.addWidget(local_title)

        loc_time = self.conflict.get("local_modified_at", "")
        try:
            loc_time_str = datetime.fromisoformat(loc_time).strftime("%b %d, %H:%M:%S")
        except Exception:
            loc_time_str = loc_time[:19]
        loc_time_lbl = QLabel(f"Modified: {loc_time_str}")
        loc_time_lbl.setStyleSheet("color: #CBD5E1; font-size: 11px;")
        local_col.addWidget(loc_time_lbl)

        loc_sz = self.conflict.get("local_size_bytes", 0)
        loc_sz_str = f"{round(loc_sz / 1024, 1)} KB" if loc_sz < 1024**2 else f"{round(loc_sz / (1024**2), 2)} MB"
        loc_sz_lbl = QLabel(f"Size: {loc_sz_str}")
        loc_sz_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        local_col.addWidget(loc_sz_lbl)

        comp_layout.addLayout(local_col, stretch=1)

        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setStyleSheet("color: #334155;")
        comp_layout.addWidget(divider)

        # Right Column: Remote Version
        remote_col = QVBoxLayout()
        remote_col.setSpacing(4)
        remote_dev = self.conflict.get("remote_device_name") or "Connected Computer"
        remote_title = QLabel(f"<b>☁️ {remote_dev} (Remote Version)</b>")
        remote_title.setStyleSheet("color: #F59E0B; font-size: 12px;")
        remote_col.addWidget(remote_title)

        rem_time = self.conflict.get("remote_modified_at", "")
        try:
            rem_time_str = datetime.fromisoformat(rem_time).strftime("%b %d, %H:%M:%S")
        except Exception:
            rem_time_str = rem_time[:19]
        rem_time_lbl = QLabel(f"Modified: {rem_time_str}")
        rem_time_lbl.setStyleSheet("color: #CBD5E1; font-size: 11px;")
        remote_col.addWidget(rem_time_lbl)

        rem_sz = self.conflict.get("remote_size_bytes", 0)
        rem_sz_str = f"{round(rem_sz / 1024, 1)} KB" if rem_sz < 1024**2 else f"{round(rem_sz / (1024**2), 2)} MB"
        rem_sz_lbl = QLabel(f"Size: {rem_sz_str}")
        rem_sz_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        remote_col.addWidget(rem_sz_lbl)

        comp_layout.addLayout(remote_col, stretch=1)
        layout.addWidget(comp_frame)

        # Resolution Buttons Row
        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("<b>Resolution:</b>"))
        action_row.addStretch()

        btn_keep_local = QPushButton(f"Keep {self.current_device_name}")
        btn_keep_local.setObjectName("secondaryBtn")
        btn_keep_local.clicked.connect(lambda: self.resolve_requested.emit(self.conflict_id, ConflictResolution.KEEP_LOCAL.value))
        action_row.addWidget(btn_keep_local)

        btn_keep_remote = QPushButton(f"Keep {remote_dev}")
        btn_keep_remote.setObjectName("secondaryBtn")
        btn_keep_remote.clicked.connect(lambda: self.resolve_requested.emit(self.conflict_id, ConflictResolution.KEEP_REMOTE.value))
        action_row.addWidget(btn_keep_remote)

        btn_keep_both = QPushButton("Keep Both (Recommended)")
        btn_keep_both.clicked.connect(lambda: self.resolve_requested.emit(self.conflict_id, ConflictResolution.KEEP_BOTH.value))
        action_row.addWidget(btn_keep_both)

        layout.addLayout(action_row)

    def _open_folder(self):
        local_path = self.conflict.get("local_path", "")
        if local_path and os.path.exists(local_path):
            folder = os.path.dirname(local_path)
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        elif local_path:
            folder = os.path.dirname(local_path)
            if os.path.exists(folder):
                if sys.platform == "win32":
                    os.startfile(folder)
                else:
                    subprocess.Popen(["xdg-open", folder])


class ConflictCenterDialog(QDialog):
    """Modal Conflict Center for reviewing and resolving conflicts across datasets."""

    conflict_resolved = Signal()

    def __init__(
        self,
        conflicts: List[Dict[str, Any]],
        resolver_cb: Callable[[int, str], bool],
        current_device_name: str = "This PC",
        parent=None,
    ):
        super().__init__(parent)
        self.conflicts = conflicts or []
        self.resolver_cb = resolver_cb
        self.current_device_name = current_device_name

        self.setWindowTitle("Conflict Center")
        self.resize(700, 550)
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)

        # Header
        header_card = QFrame()
        header_card.setObjectName("cardWidget")
        hl = QVBoxLayout(header_card)

        count = len(self.conflicts)
        title = QLabel(f"⚠️ Conflict Center — {count} Unresolved Conflict{'s' if count != 1 else ''}")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFFFF;")
        hl.addWidget(title)

        desc = QLabel(
            "Simultaneous modifications were detected across different computers. "
            "Choose which version to keep, or keep both to ensure no data is lost."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #94A3B8; font-size: 12px;")
        hl.addWidget(desc)
        main_layout.addWidget(header_card)

        # Scroll Area for Conflict Cards
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

        self._populate_conflicts()

        # Bottom Close Button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        main_layout.addLayout(btn_row)

    def _populate_conflicts(self):
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.conflicts:
            empty_lbl = QLabel("✓ No unresolved conflicts! All files are synchronized.")
            empty_lbl.setAlignment(Qt.AlignCenter)
            empty_lbl.setStyleSheet("color: #10B981; font-size: 14px; padding: 40px;")
            self.cards_layout.insertWidget(0, empty_lbl)
            return

        for idx, c in enumerate(self.conflicts):
            card = ConflictCardWidget(c, self.current_device_name)
            card.resolve_requested.connect(self._on_resolve)
            self.cards_layout.insertWidget(idx, card)

    def _on_resolve(self, conflict_id: int, resolution: str):
        try:
            success = self.resolver_cb(conflict_id, resolution)
            if success:
                self.conflicts = [c for c in self.conflicts if c.get("id") != conflict_id]
                self._populate_conflicts()
                self.conflict_resolved.emit()
            else:
                QMessageBox.warning(self, "Error", "Failed to resolve conflict.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Conflict resolution error: {e}")
