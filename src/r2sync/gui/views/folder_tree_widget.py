"""Interactive folder structure tree widget with checkboxes for selective file and folder exclusion."""

import fnmatch
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyle,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from r2sync.config import DEFAULT_EXCLUDE_PATTERNS


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable string."""
    if size_bytes <= 0:
        return ""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{round(size_bytes / 1024, 1)} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{round(size_bytes / (1024 * 1024), 1)} MB"
    else:
        return f"{round(size_bytes / (1024 * 1024 * 1024), 2)} GB"


class FolderTreeFilterWidget(QWidget):
    """
    Interactive Folder Structure Tree Widget.
    Allows users to inspect directory trees and uncheck specific folders or files to exclude them.
    """

    exclusionsChanged = Signal()

    def __init__(self, root_path: str = "", initial_excludes: Optional[List[str]] = None, parent=None):
        super().__init__(parent)
        self.root_path = root_path
        self._custom_excludes: List[str] = initial_excludes or list(DEFAULT_EXCLUDE_PATTERNS[:6])
        self._item_state_block = False

        self._init_ui()
        if root_path and os.path.exists(root_path):
            self.set_root_path(root_path, self._custom_excludes)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 1. Quick Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setObjectName("secondaryBtn")
        self.select_all_btn.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        self.select_all_btn.clicked.connect(self._select_all)
        toolbar.addWidget(self.select_all_btn)

        self.uncheck_temp_btn = QPushButton("🧹 Exclude Build & Temp")
        self.uncheck_temp_btn.setObjectName("secondaryBtn")
        self.uncheck_temp_btn.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        self.uncheck_temp_btn.clicked.connect(self._uncheck_temp_artifacts)
        toolbar.addWidget(self.uncheck_temp_btn)

        toolbar.addStretch()

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter files/folders...")
        self.filter_input.setStyleSheet("padding: 4px 8px; font-size: 11px; max-width: 170px;")
        self.filter_input.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.filter_input)

        layout.addLayout(toolbar)

        # 2. Main Tree Widget
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Folder / File", "Size"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setStyleSheet("""
            QTreeWidget {
                background-color: #191C20;
                border: 1px solid #272A2E;
                border-radius: 8px;
                color: #E1E2E8;
                padding: 4px;
            }
            QTreeWidget::item {
                padding: 3px 0px;
                border-radius: 4px;
            }
            QTreeWidget::item:hover {
                background-color: #272A2E;
            }
            QTreeWidget::item:selected {
                background-color: #2D3035;
                color: #FFB786;
            }
            QHeaderView::section {
                background-color: #1D2024;
                color: #A58C7D;
                font-size: 11px;
                font-weight: 600;
                border: none;
                border-bottom: 1px solid #272A2E;
                padding: 4px 8px;
            }
        """)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, stretch=1)

        # 3. Status Bar / Summary Badge
        summary_row = QHBoxLayout()
        summary_row.setSpacing(8)

        self.summary_label = QLabel("No directory selected")
        self.summary_label.setStyleSheet("color: #A58C7D; font-size: 11px;")
        summary_row.addWidget(self.summary_label, stretch=1)

        self.adv_toggle_btn = QPushButton("Advanced Rules ▼")
        self.adv_toggle_btn.setObjectName("secondaryBtn")
        self.adv_toggle_btn.setStyleSheet("padding: 2px 8px; font-size: 10px; border: none; color: #FFB786;")
        self.adv_toggle_btn.clicked.connect(self._toggle_advanced)
        summary_row.addWidget(self.adv_toggle_btn)

        layout.addLayout(summary_row)

        # 4. Collapsible Advanced Glob Editor
        self.adv_frame = QFrame()
        self.adv_frame.setVisible(False)
        self.adv_frame.setStyleSheet("""
            QFrame {
                background-color: #1D2024;
                border: 1px solid #272A2E;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        adv_layout = QVBoxLayout(self.adv_frame)
        adv_layout.setContentsMargins(4, 4, 4, 4)
        adv_layout.setSpacing(4)

        adv_title = QLabel("Additional Glob Exclusion Rules (one per line):")
        adv_title.setStyleSheet("color: #A58C7D; font-size: 10px;")
        adv_layout.addWidget(adv_title)

        self.adv_patterns_edit = QTextEdit()
        self.adv_patterns_edit.setMaximumHeight(50)
        self.adv_patterns_edit.setStyleSheet("font-family: monospace; font-size: 11px;")
        self.adv_patterns_edit.setPlaceholderText("*.iso\nbackup_*.tar.gz")
        self.adv_patterns_edit.textChanged.connect(self._on_adv_patterns_changed)
        adv_layout.addWidget(self.adv_patterns_edit)

        layout.addWidget(self.adv_frame)

    def set_root_path(self, root_path: str, initial_excludes: Optional[List[str]] = None):
        """Set the root folder and populate directory tree."""
        self.root_path = os.path.abspath(root_path) if root_path else ""
        if initial_excludes is not None:
            self._custom_excludes = [p.strip() for p in initial_excludes if p.strip()]

        self.tree.clear()
        if not self.root_path or not os.path.exists(self.root_path):
            self.summary_label.setText("Directory not found or inaccessible")
            return

        self._item_state_block = True
        try:
            root_name = Path(self.root_path).name or self.root_path
            root_item = QTreeWidgetItem(self.tree)
            root_item.setText(0, f"📁 {root_name} (Root)")
            root_item.setData(0, Qt.UserRole, "")  # Empty relative path
            root_item.setData(0, Qt.UserRole + 1, True)  # Is Directory
            root_item.setFlags(root_item.flags() | Qt.ItemIsUserCheckable)

            # Check if root itself matches any exclusion
            root_item.setCheckState(0, Qt.Checked)

            # Populate first level of children
            self._populate_item_children(root_item, self.root_path, "")
            root_item.setExpanded(True)

            self._apply_initial_excludes_to_tree()

        finally:
            self._item_state_block = False

        self._update_summary()

    def _populate_item_children(self, parent_item: QTreeWidgetItem, parent_abs_path: str, parent_rel_path: str):
        """Populate child directories and files for a tree item."""
        try:
            entries = sorted(os.scandir(parent_abs_path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except (PermissionError, OSError):
            return

        for entry in entries:
            # Skip internal r2sync recovery trash
            if entry.name == ".r2sync_trash":
                continue

            rel_path = f"{parent_rel_path}/{entry.name}".lstrip("/") if parent_rel_path else entry.name
            child_item = QTreeWidgetItem(parent_item)
            child_item.setData(0, Qt.UserRole, rel_path)

            if entry.is_dir(follow_symlinks=False):
                child_item.setText(0, f"📁 {entry.name}")
                child_item.setData(0, Qt.UserRole + 1, True)
                child_item.setFlags(child_item.flags() | Qt.ItemIsUserCheckable)
                child_item.setCheckState(0, Qt.Checked)

                # Add dummy child so expansion arrow appears
                try:
                    has_sub = any(True for _ in os.scandir(entry.path))
                    if has_sub:
                        dummy = QTreeWidgetItem(child_item)
                        dummy.setText(0, "Loading...")
                        dummy.setData(0, Qt.UserRole, "__dummy__")
                except (PermissionError, OSError):
                    pass

            else:
                child_item.setText(0, f"📄 {entry.name}")
                child_item.setData(0, Qt.UserRole + 1, False)
                child_item.setFlags(child_item.flags() | Qt.ItemIsUserCheckable)
                child_item.setCheckState(0, Qt.Checked)
                try:
                    sz = entry.stat().st_size
                    child_item.setText(1, format_size(sz))
                    child_item.setData(1, Qt.UserRole, sz)
                except OSError:
                    child_item.setText(1, "")

    def _on_item_expanded(self, item: QTreeWidgetItem):
        """Lazy load children when a folder node is expanded."""
        if item.childCount() == 1 and item.child(0).data(0, Qt.UserRole) == "__dummy__":
            self._item_state_block = True
            try:
                item.removeChild(item.child(0))
                rel_path = item.data(0, Qt.UserRole)
                abs_path = os.path.join(self.root_path, rel_path) if rel_path else self.root_path
                self._populate_item_children(item, abs_path, rel_path)

                # Propagate parent's check state or exclusion matching to new children
                parent_checked = (item.checkState(0) == Qt.Checked)
                for i in range(item.childCount()):
                    child = item.child(i)
                    child_rel = child.data(0, Qt.UserRole)
                    is_dir = child.data(0, Qt.UserRole + 1)
                    test_path = f"{child_rel}/" if is_dir else child_rel

                    if not parent_checked or self._matches_excludes(test_path):
                        child.setCheckState(0, Qt.Unchecked)
                    else:
                        child.setCheckState(0, Qt.Checked)

            finally:
                self._item_state_block = False

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """Handle user checking or unchecking a folder/file."""
        if self._item_state_block or column != 0:
            return

        self._item_state_block = True
        try:
            state = item.checkState(0)
            # Propagate downward to all currently loaded children
            self._set_children_check_state(item, state)
        finally:
            self._item_state_block = False

        self._update_summary()
        self.exclusionsChanged.emit()

    def _set_children_check_state(self, parent_item: QTreeWidgetItem, state: Qt.CheckState):
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            if child.data(0, Qt.UserRole) != "__dummy__":
                child.setCheckState(0, state)
                self._set_children_check_state(child, state)

    def _matches_excludes(self, rel_path: str) -> bool:
        """Test if a relative path matches any active exclusion rule."""
        p_clean = rel_path.strip("/")
        for pat in self._custom_excludes:
            pat_clean = pat.strip()
            if not pat_clean:
                continue

            # Exact folder match e.g. node_modules/ or build/
            if pat_clean.endswith("/"):
                pat_dir = pat_clean.rstrip("/")
                if p_clean == pat_dir or p_clean.startswith(f"{pat_dir}/"):
                    return True
            elif fnmatch.fnmatch(p_clean, pat_clean) or fnmatch.fnmatch(os.path.basename(p_clean), pat_clean):
                return True
        return False

    def _apply_initial_excludes_to_tree(self):
        """Walk loaded items and set Unchecked state for items matching initial excludes."""
        def walk_and_mark(item: QTreeWidgetItem):
            rel_path = item.data(0, Qt.UserRole)
            if rel_path:
                is_dir = item.data(0, Qt.UserRole + 1)
                test_path = f"{rel_path}/" if is_dir else rel_path
                if self._matches_excludes(test_path):
                    item.setCheckState(0, Qt.Unchecked)
                    self._set_children_check_state(item, Qt.Unchecked)
                    return  # Exclude covers all children
            for i in range(item.childCount()):
                walk_and_mark(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk_and_mark(self.tree.topLevelItem(i))

    def _select_all(self):
        """Check all loaded nodes."""
        self._item_state_block = True
        try:
            for i in range(self.tree.topLevelItemCount()):
                root = self.tree.topLevelItem(i)
                root.setCheckState(0, Qt.Checked)
                self._set_children_check_state(root, Qt.Checked)
        finally:
            self._item_state_block = False
        self._update_summary()
        self.exclusionsChanged.emit()

    def _uncheck_temp_artifacts(self):
        """Uncheck common temporary, build, and lock files."""
        temp_names = {
            "node_modules", ".git", ".svn", ".hg", "__pycache__", "dist", "build",
            "target", ".cache", ".idea", ".vscode", "bin", "obj", "temp", "tmp",
            ".DS_Store", "Thumbs.db", "desktop.ini"
        }

        self._item_state_block = True
        try:
            def walk_and_filter(item: QTreeWidgetItem):
                rel = item.data(0, Qt.UserRole)
                if rel and rel != "__dummy__":
                    base = os.path.basename(rel)
                    is_dir = item.data(0, Qt.UserRole + 1)
                    if base in temp_names or base.startswith("~$") or base.endswith((".tmp", ".temp", ".pyc")):
                        item.setCheckState(0, Qt.Unchecked)
                        self._set_children_check_state(item, Qt.Unchecked)
                        return

                for i in range(item.childCount()):
                    walk_and_filter(item.child(i))

            for i in range(self.tree.topLevelItemCount()):
                walk_and_filter(self.tree.topLevelItem(i))
        finally:
            self._item_state_block = False

        self._update_summary()
        self.exclusionsChanged.emit()

    def _apply_filter(self, text: str):
        """Filter visible items in tree based on search text."""
        query = text.strip().lower()

        def filter_item(item: QTreeWidgetItem) -> bool:
            if item.data(0, Qt.UserRole) == "__dummy__":
                return False
            name = item.text(0).lower()
            matches = query in name if query else True
            child_matches = False
            for i in range(item.childCount()):
                if filter_item(item.child(i)):
                    child_matches = True
            visible = matches or child_matches
            item.setHidden(not visible)
            if query and child_matches:
                item.setExpanded(True)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            filter_item(self.tree.topLevelItem(i))

    def _toggle_advanced(self):
        is_vis = self.adv_frame.isVisible()
        self.adv_frame.setVisible(not is_vis)
        self.adv_toggle_btn.setText("Advanced Rules ▲" if not is_vis else "Advanced Rules ▼")

    def _on_adv_patterns_changed(self):
        self.exclusionsChanged.emit()

    def _update_summary(self):
        """Compute count of unchecked folders and files."""
        excluded_count = 0
        total_items = 0

        def count_stats(item: QTreeWidgetItem):
            nonlocal excluded_count, total_items
            if item.data(0, Qt.UserRole) == "__dummy__":
                return
            rel = item.data(0, Qt.UserRole)
            if rel:
                total_items += 1
                if item.checkState(0) == Qt.Unchecked:
                    excluded_count += 1
                    return  # If parent is excluded, don't double count children
            for i in range(item.childCount()):
                count_stats(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            count_stats(self.tree.topLevelItem(i))

        if not self.root_path:
            self.summary_label.setText("No folder selected")
        elif excluded_count == 0:
            self.summary_label.setText("✓ All items selected for sync & backup")
        else:
            self.summary_label.setText(f"✓ Items included | <font color='#FFB786'><b>{excluded_count}</b> folder(s)/file(s) unchecked & excluded</font>")

    def get_exclude_patterns(self) -> List[str]:
        """
        Collect all concise exclusion rules:
        Unchecked root folders/files + any custom patterns from the advanced editor.
        """
        excludes: Set[str] = set()

        def collect_unchecked(item: QTreeWidgetItem):
            if item.data(0, Qt.UserRole) == "__dummy__":
                return
            rel = item.data(0, Qt.UserRole)
            if rel:
                if item.checkState(0) == Qt.Unchecked:
                    is_dir = item.data(0, Qt.UserRole + 1)
                    if is_dir:
                        excludes.add(f"{rel}/")
                        excludes.add(f"{rel}/**")
                    else:
                        excludes.add(rel)
                    return  # Top-level unchecked node covers its sub-tree

            for i in range(item.childCount()):
                collect_unchecked(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            collect_unchecked(self.tree.topLevelItem(i))

        # Include advanced custom patterns
        adv_text = self.adv_patterns_edit.toPlainText().strip()
        if adv_text:
            for line in adv_text.splitlines():
                if line.strip():
                    excludes.add(line.strip())

        return sorted(list(excludes))

    def set_exclude_patterns(self, patterns: List[str]):
        """Set exclusion rules and reflect on tree & advanced editor."""
        self._custom_excludes = [p.strip() for p in patterns if p.strip()]
        self.adv_patterns_edit.setPlainText("\n".join(
            p for p in self._custom_excludes if not any(p.startswith(x) for x in ["/", "\\"])
        ))
        if self.root_path and os.path.exists(self.root_path):
            self._apply_initial_excludes_to_tree()
            self._update_summary()
