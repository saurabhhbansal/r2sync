"""Modern Dark and Light stylesheets for r2sync."""

DARK_THEME_QSS = """
QMainWindow, QDialog, QWidget {
    background-color: #12161F;
    color: #E2E8F0;
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
}

QSplitter::handle {
    background-color: #1E293B;
}

QScrollBar:vertical {
    border: none;
    background: #12161F;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #334155;
    min-height: 20px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #475569;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QTabWidget::pane {
    border: 1px solid #1E293B;
    background-color: #12161F;
    border-radius: 8px;
}

QTabBar::tab {
    background: #18202F;
    color: #94A3B8;
    padding: 10px 20px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 4px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background: #2563EB;
    color: #FFFFFF;
    font-weight: 600;
}
QTabBar::tab:hover:!selected {
    background: #1E293B;
    color: #F8FAFC;
}

QPushButton {
    background-color: #2563EB;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #1D4ED8;
}
QPushButton:pressed {
    background-color: #1E40AF;
}
QPushButton:disabled {
    background-color: #334155;
    color: #64748B;
}

QPushButton#secondaryBtn {
    background-color: #1E293B;
    color: #E2E8F0;
    border: 1px solid #334155;
}
QPushButton#secondaryBtn:hover {
    background-color: #334155;
    border-color: #475569;
}
QPushButton#secondaryBtn:pressed {
    background-color: #0F172A;
}

QPushButton#dangerBtn {
    background-color: #DC2626;
    color: #FFFFFF;
}
QPushButton#dangerBtn:hover {
    background-color: #B91C1C;
}

QPushButton#successBtn {
    background-color: #059669;
    color: #FFFFFF;
}
QPushButton#successBtn:hover {
    background-color: #047857;
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background-color: #1E293B;
    color: #F8FAFC;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 8px 12px;
    selection-background-color: #2563EB;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #3B82F6;
    background-color: #1A2333;
}
QLineEdit:disabled, QTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
    background-color: #0F172A;
    color: #64748B;
    border-color: #1E293B;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 25px;
    border-left-width: 0px;
}

QTableWidget, QTableView, QListWidget {
    background-color: #18202F;
    border: 1px solid #1E293B;
    border-radius: 8px;
    gridline-color: #1E293B;
    color: #E2E8F0;
    selection-background-color: #1E3A8A;
    selection-color: #FFFFFF;
}
QHeaderView::section {
    background-color: #12161F;
    color: #94A3B8;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #1E293B;
    font-weight: 600;
    text-align: left;
}

QProgressBar {
    background-color: #1E293B;
    border: none;
    border-radius: 5px;
    text-align: center;
    color: #FFFFFF;
    font-weight: bold;
    height: 10px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:1 #38BDF8);
    border-radius: 5px;
}

QCheckBox {
    color: #E2E8F0;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #475569;
    background-color: #1E293B;
}
QCheckBox::indicator:checked {
    background-color: #2563EB;
    border-color: #3B82F6;
}

QGroupBox {
    border: 1px solid #1E293B;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 18px;
    font-weight: bold;
    color: #94A3B8;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #38BDF8;
}

/* Custom Card Classes */
QFrame#cardWidget {
    background-color: #18202F;
    border: 1px solid #1E293B;
    border-radius: 10px;
    padding: 16px;
}

QFrame#sidebarWidget {
    background-color: #0F131D;
    border-right: 1px solid #1E293B;
}

QLabel#titleLabel {
    font-size: 20px;
    font-weight: bold;
    color: #FFFFFF;
}

QLabel#subtitleLabel {
    font-size: 13px;
    color: #94A3B8;
}

QLabel#statValueLabel {
    font-size: 24px;
    font-weight: bold;
    color: #38BDF8;
}

QLabel#statTitleLabel {
    font-size: 12px;
    font-weight: 600;
    color: #94A3B8;
    text-transform: uppercase;
}
"""

LIGHT_THEME_QSS = """
QMainWindow, QDialog, QWidget {
    background-color: #F8FAFC;
    color: #1E293B;
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
}

QSplitter::handle {
    background-color: #E2E8F0;
}

QScrollBar:vertical {
    border: none;
    background: #F8FAFC;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #CBD5E1;
    min-height: 20px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #94A3B8;
}

QTabWidget::pane {
    border: 1px solid #E2E8F0;
    background-color: #FFFFFF;
    border-radius: 8px;
}

QTabBar::tab {
    background: #F1F5F9;
    color: #64748B;
    padding: 10px 20px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 4px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background: #2563EB;
    color: #FFFFFF;
    font-weight: 600;
}

QPushButton {
    background-color: #2563EB;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #1D4ED8;
}

QPushButton#secondaryBtn {
    background-color: #F1F5F9;
    color: #334155;
    border: 1px solid #CBD5E1;
}
QPushButton#secondaryBtn:hover {
    background-color: #E2E8F0;
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background-color: #FFFFFF;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 8px 12px;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #2563EB;
}

QTableWidget, QTableView, QListWidget {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    gridline-color: #F1F5F9;
    color: #1E293B;
    selection-background-color: #EFF6FF;
    selection-color: #1E40AF;
}
QHeaderView::section {
    background-color: #F8FAFC;
    color: #64748B;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #E2E8F0;
    font-weight: 600;
}

QProgressBar {
    background-color: #E2E8F0;
    border: none;
    border-radius: 5px;
    text-align: center;
    color: #0F172A;
    font-weight: bold;
    height: 10px;
}
QProgressBar::chunk {
    background: #2563EB;
    border-radius: 5px;
}

QFrame#cardWidget {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    padding: 16px;
}

QFrame#sidebarWidget {
    background-color: #F1F5F9;
    border-right: 1px solid #E2E8F0;
}

QLabel#titleLabel {
    font-size: 20px;
    font-weight: bold;
    color: #0F172A;
}

QLabel#subtitleLabel {
    font-size: 13px;
    color: #64748B;
}

QLabel#statValueLabel {
    font-size: 24px;
    font-weight: bold;
    color: #2563EB;
}

QLabel#statTitleLabel {
    font-size: 12px;
    font-weight: 600;
    color: #64748B;
    text-transform: uppercase;
}
"""


def apply_theme(app, theme_name: str = "dark") -> None:
    if theme_name.lower() == "light":
        app.setStyleSheet(LIGHT_THEME_QSS)
    else:
        app.setStyleSheet(DARK_THEME_QSS)
