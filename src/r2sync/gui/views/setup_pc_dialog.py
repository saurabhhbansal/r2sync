"""Dialog for discovering and joining existing remote datasets ('Set Up This PC')."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class SetupPCDialog(QDialog):
    """Wizard/Dialog for connecting this PC to an existing remote Sync dataset."""

    def __init__(self, discovered_datasets: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.discovered = discovered_datasets or []
        self.selected_dataset: Optional[Dict[str, Any]] = None
        self.chosen_local_path: str = ""

        self.setWindowTitle("Set Up This Computer")
        self.resize(640, 520)
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)

        # Header Info Banner
        info_card = QFrame()
        info_card.setObjectName("cardWidget")
        info_layout = QVBoxLayout(info_card)

        title = QLabel("💻 Set Up Synchronized Folders on This PC")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #38BDF8;")
        info_layout.addWidget(title)

        desc = QLabel(
            "We found shared sync datasets on your Cloudflare R2 storage from other computers. "
            "Select a dataset below to synchronize its files to this computer."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #CBD5E1; font-size: 12px;")
        info_layout.addWidget(desc)
        main_layout.addWidget(info_card)

        # Datasets Table Frame
        table_frame = QFrame()
        table_frame.setObjectName("cardWidget")
        table_layout = QVBoxLayout(table_frame)
        table_layout.addWidget(QLabel("<b>Available Remote Datasets:</b>"))

        self.datasets_table = QTableWidget(0, 4)
        self.datasets_table.setHorizontalHeaderLabels([
            "Dataset Name", "Created By", "Files", "Size"
        ])
        self.datasets_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.datasets_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.datasets_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.datasets_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.datasets_table.verticalHeader().setVisible(False)
        self.datasets_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.datasets_table.setSelectionMode(QTableWidget.SingleSelection)
        self.datasets_table.itemSelectionChanged.connect(self._on_dataset_selected)

        self._populate_datasets()
        table_layout.addWidget(self.datasets_table)
        main_layout.addWidget(table_frame)

        # Local Path Selection Frame
        path_frame = QFrame()
        path_frame.setObjectName("cardWidget")
        path_layout = QFormLayout(path_frame)

        folder_row = QHBoxLayout()
        self.local_input = QLineEdit()
        self.local_input.setPlaceholderText("Select destination folder on this computer")
        browse_btn = QPushButton("📁 Browse...")
        browse_btn.setObjectName("secondaryBtn")
        browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.local_input)
        folder_row.addWidget(browse_btn)
        path_layout.addRow("Local Location:", folder_row)

        main_layout.addWidget(path_frame)

        # Bottom Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.clicked.connect(self.reject)

        self.start_btn = QPushButton("Start Initial Sync")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._validate_and_accept)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.start_btn)
        main_layout.addLayout(btn_layout)

    def _populate_datasets(self):
        self.datasets_table.setRowCount(len(self.discovered))
        for row, d in enumerate(self.discovered):
            name_item = QTableWidgetItem(d.get("name", "Unknown"))
            creator_item = QTableWidgetItem(d.get("created_by_device", "Other PC"))

            cnt = d.get("total_files", 0)
            cnt_item = QTableWidgetItem(f"{cnt:,} files" if cnt > 0 else "—")

            sz = d.get("total_bytes", 0)
            if sz > 1024**3:
                sz_str = f"{round(sz / (1024**3), 2)} GB"
            elif sz > 1024**2:
                sz_str = f"{round(sz / (1024**2), 1)} MB"
            else:
                sz_str = "—"
            sz_item = QTableWidgetItem(sz_str)

            self.datasets_table.setItem(row, 0, name_item)
            self.datasets_table.setItem(row, 1, creator_item)
            self.datasets_table.setItem(row, 2, cnt_item)
            self.datasets_table.setItem(row, 3, sz_item)

        if self.discovered:
            self.datasets_table.selectRow(0)

    def _on_dataset_selected(self):
        row = self.datasets_table.currentRow()
        if 0 <= row < len(self.discovered):
            self.selected_dataset = self.discovered[row]
            ds_name = self.selected_dataset.get("name", "SyncFolder")
            # Suggest default local path
            default_path = str(Path.home() / ds_name)
            self.local_input.setText(default_path)
            self.start_btn.setEnabled(True)
        else:
            self.start_btn.setEnabled(False)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Local Folder Location", str(Path.home()))
        if folder:
            self.local_input.setText(folder)

    def _validate_and_accept(self):
        if not self.selected_dataset:
            QMessageBox.warning(self, "Selection Required", "Please select a remote dataset to connect.")
            return

        loc = self.local_input.text().strip()
        if not loc:
            QMessageBox.warning(self, "Path Required", "Please specify a local folder location.")
            return

        self.chosen_local_path = os.path.abspath(loc)
        self.accept()
