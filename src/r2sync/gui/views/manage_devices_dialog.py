"""Manage Connected Computers dialog matching Stitch Design."""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ManageDevicesDialog(QDialog):
    """Dialog for inspecting and managing computers connected to a shared dataset matching Stitch Design."""

    device_removed = Signal()

    def __init__(
        self,
        dataset_name: str,
        dataset_id: str,
        devices: List[Dict[str, Any]],
        remove_device_cb: Callable[[str, str], bool],
        refresh_cb: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.dataset_name = dataset_name
        self.dataset_id = dataset_id
        self.devices = devices or []
        self.remove_device_cb = remove_device_cb
        self.refresh_cb = refresh_cb

        self.setWindowTitle(f"Manage Computers — {dataset_name}")
        self.resize(680, 440)
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Header Info
        header_card = QFrame()
        header_card.setObjectName("heroCardWidget")
        header_card.setStyleSheet("""
            QFrame#heroCardWidget {
                background-color: #1D2024;
                border: 1px solid #272A2E;
                border-radius: 12px;
                padding: 16px;
            }
        """)
        hl = QVBoxLayout(header_card)

        title = QLabel(f"🖥️ Connected Computers — {self.dataset_name}")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #E1E2E8;")
        hl.addWidget(title)

        desc = QLabel(
            "These computers participate in synchronizing this dataset through your Cloudflare R2 storage. "
            "You can remove disconnected or retired devices at any time without deleting shared files."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #A58C7D; font-size: 12px;")
        hl.addWidget(desc)
        main_layout.addWidget(header_card)

        # Table Frame
        table_frame = QFrame()
        table_frame.setObjectName("cardWidget")
        tl = QVBoxLayout(table_frame)
        tl.setSpacing(10)

        btn_row_top = QHBoxLayout()
        t_lbl = QLabel("Registered Devices:")
        t_lbl.setStyleSheet("font-weight: 600; color: #E1E2E8;")
        btn_row_top.addWidget(t_lbl)
        btn_row_top.addStretch()

        if self.refresh_cb:
            refresh_btn = QPushButton("🔄 Refresh Devices")
            refresh_btn.setObjectName("secondaryBtn")
            refresh_btn.setStyleSheet("padding: 4px 10px; font-size: 11px;")
            refresh_btn.clicked.connect(self._on_refresh)
            btn_row_top.addWidget(refresh_btn)

        tl.addLayout(btn_row_top)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Computer Name", "Status", "Last Seen", "Device ID"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        self._populate_table()
        tl.addWidget(self.table)
        main_layout.addWidget(table_frame)

        # Bottom Buttons
        btn_layout = QHBoxLayout()

        self.remove_btn = QPushButton("🗑 Remove Selected Computer")
        self.remove_btn.setObjectName("dangerBtn")
        self.remove_btn.setEnabled(False)
        self.remove_btn.setStyleSheet("padding: 8px 16px;")
        self.remove_btn.clicked.connect(self._on_remove_clicked)
        btn_layout.addWidget(self.remove_btn)

        btn_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setObjectName("secondaryBtn")
        close_btn.setStyleSheet("padding: 8px 16px;")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        main_layout.addLayout(btn_layout)

    def _populate_table(self):
        self.table.setRowCount(len(self.devices))
        for row, dev in enumerate(self.devices):
            is_curr = dev.get("is_current_device", False)
            dev_name = dev.get("device_name", "Unknown PC")
            if is_curr:
                dev_name += " (This PC)"

            name_item = QTableWidgetItem(dev_name)
            if is_curr:
                name_item.setForeground(Qt.cyan)

            st = dev.get("status", "offline").title()
            st_item = QTableWidgetItem(f"● {st}")
            if st.lower() == "online" or st.lower() == "syncing":
                st_item.setForeground(Qt.green)
            else:
                st_item.setForeground(Qt.gray)

            last_seen = dev.get("last_seen_at") or dev.get("last_sync_at")
            if last_seen:
                try:
                    last_seen_str = datetime.fromisoformat(last_seen).strftime("%b %d, %H:%M")
                except Exception:
                    last_seen_str = last_seen[:16]
            else:
                last_seen_str = "Never"
            seen_item = QTableWidgetItem(last_seen_str)

            dev_id = dev.get("device_id", "")
            id_item = QTableWidgetItem(dev_id[:12] + "..." if len(dev_id) > 12 else dev_id)

            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, st_item)
            self.table.setItem(row, 2, seen_item)
            self.table.setItem(row, 3, id_item)

    def _on_selection_changed(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.devices):
            dev = self.devices[row]
            is_curr = dev.get("is_current_device", False)
            self.remove_btn.setEnabled(not is_curr)
        else:
            self.remove_btn.setEnabled(False)

    def _on_remove_clicked(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.devices):
            dev = self.devices[row]
            dev_name = dev.get("device_name", "Computer")
            dev_id = dev.get("device_id", "")

            ans = QMessageBox.question(
                self,
                "Remove Computer",
                f"Are you sure you want to remove '{dev_name}' from this dataset?\n\n"
                "Note: Removing a computer only disconnects its synchronization participation. "
                "It will NOT delete any shared files on Cloudflare R2 or other computers.",
                QMessageBox.Yes | QMessageBox.No,
            )

            if ans == QMessageBox.Yes:
                success = self.remove_device_cb(self.dataset_id, dev_id)
                if success:
                    self.devices = [d for d in self.devices if d.get("device_id") != dev_id]
                    self._populate_table()
                    self.device_removed.emit()
                    QMessageBox.information(self, "Success", f"'{dev_name}' was removed from the dataset.")
                else:
                    QMessageBox.warning(self, "Error", "Failed to remove computer.")

    def _on_refresh(self):
        if self.refresh_cb:
            updated = self.refresh_cb(self.dataset_id)
            if updated:
                self.devices = updated
                self._populate_table()
