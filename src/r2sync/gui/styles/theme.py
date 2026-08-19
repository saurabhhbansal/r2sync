"""Modern Dark and Light stylesheets for r2sync based on Stitch R2Sync Pro Dark Design System."""

DARK_THEME_QSS = """
/* Global Base */
QWidget {
    color: #E1E2E8;
    background-color: transparent;
    font-family: "Inter", "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
    selection-background-color: #F6821F;
    selection-color: #000000;
}

QMainWindow, QDialog, QStackedWidget {
    background-color: #111418;
}

QLabel {
    background-color: transparent;
    color: #E1E2E8;
}

QSplitter::handle {
    background-color: #272A2E;
}

QScrollArea {
    background-color: transparent;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

/* ScrollBars */
QScrollBar:vertical {
    border: none;
    background: #111418;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #272A2E;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #323539;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    border: none;
    background: #111418;
    height: 8px;
    margin: 0px;
}
QScrollBar::handle:horizontal {
    background: #272A2E;
    min-width: 24px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: #323539;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* Tabs */
QTabWidget::pane {
    border: 1px solid #272A2E;
    background-color: #1D2024;
    border-radius: 8px;
}

QTabBar::tab {
    background: #191C20;
    color: #A58C7D;
    padding: 9px 18px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 4px;
    font-weight: 500;
    border: 1px solid transparent;
}
QTabBar::tab:selected {
    background: #272A2E;
    color: #FFB786;
    font-weight: 600;
    border-bottom: 2px solid #F6821F;
}
QTabBar::tab:hover:!selected {
    background: #272A2E;
    color: #E1E2E8;
}

/* Buttons */
QPushButton {
    background-color: #F6821F;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 13px;
}
QPushButton:hover {
    background-color: #FF9A47;
}
QPushButton:pressed {
    background-color: #E57314;
}
QPushButton:disabled {
    background-color: #272A2E;
    color: #564336;
}

QPushButton#secondaryBtn {
    background-color: #1D2024;
    color: #E1E2E8;
    border: 1px solid #323539;
}
QPushButton#secondaryBtn:hover {
    background-color: #272A2E;
    border-color: #564336;
    color: #FFFFFF;
}
QPushButton#secondaryBtn:pressed {
    background-color: #111418;
}
QPushButton#secondaryBtn:checked {
    background-color: #323539;
    color: #FFB786;
    border-color: #F6821F;
}

QPushButton#chipBtn {
    background-color: #1D2024;
    color: #A58C7D;
    border: 1px solid #323539;
    border-radius: 14px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton#chipBtn:hover {
    background-color: #272A2E;
    color: #E1E2E8;
}
QPushButton#chipBtn:checked {
    background-color: #272A2E;
    color: #FFB786;
    border: 1px solid #F6821F;
    font-weight: 600;
}

QPushButton#dangerBtn {
    background-color: #7F1D1D;
    color: #FFB4AB;
    border: 1px solid #93000A;
}
QPushButton#dangerBtn:hover {
    background-color: #93000A;
    color: #FFFFFF;
}

QPushButton#successBtn {
    background-color: #004219;
    color: #4AE176;
    border: 1px solid #02BA55;
}
QPushButton#successBtn:hover {
    background-color: #02BA55;
    color: #002109;
}

/* Inputs & Form Controls */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background-color: #1D2024;
    color: #E1E2E8;
    border: 1px solid #323539;
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: #F6821F;
    selection-color: #000000;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #F6821F;
    background-color: #272A2E;
}
QLineEdit:disabled, QTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
    background-color: #111418;
    color: #564336;
    border-color: #272A2E;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 25px;
    border-left-width: 0px;
}
QComboBox QAbstractItemView {
    background-color: #1D2024;
    border: 1px solid #323539;
    border-radius: 6px;
    color: #E1E2E8;
    selection-background-color: #272A2E;
    selection-color: #FFB786;
    padding: 4px;
}

/* Tables & Lists */
QTableWidget, QTableView, QListWidget {
    background-color: #1D2024;
    border: 1px solid #272A2E;
    border-radius: 8px;
    gridline-color: #272A2E;
    color: #E1E2E8;
    selection-background-color: #272A2E;
    selection-color: #FFB786;
}
QHeaderView::section {
    background-color: #191C20;
    color: #A58C7D;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #272A2E;
    font-weight: 600;
    font-size: 11px;
    text-align: left;
}

/* Progress Bar */
QProgressBar {
    background-color: #272A2E;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: #E1E2E8;
    font-weight: bold;
    height: 8px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F6821F, stop:1 #FFB786);
    border-radius: 4px;
}

/* Checkbox & Radio */
QCheckBox, QRadioButton {
    background-color: transparent;
    color: #E1E2E8;
    spacing: 8px;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #564336;
    background-color: #1D2024;
}
QRadioButton::indicator {
    border-radius: 9px;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #F6821F;
    border-color: #FFB786;
}

/* GroupBox */
QGroupBox {
    background-color: transparent;
    border: 1px solid #272A2E;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 18px;
    font-weight: 600;
    color: #A58C7D;
}
QGroupBox::title {
    background-color: transparent;
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #FFB786;
}

/* Custom Card Classes */
QFrame#cardWidget {
    background-color: #1D2024;
    border: 1px solid #272A2E;
    border-radius: 10px;
    padding: 16px;
}
QFrame#cardWidget:hover {
    border-color: #323539;
}

QFrame#heroCardWidget {
    background-color: #1D2024;
    border: 1px solid #272A2E;
    border-radius: 12px;
    padding: 20px;
}

QFrame#bentoCardWidget {
    background-color: #111418;
    border: 1px solid #272A2E;
    border-radius: 8px;
    padding: 14px;
}
QFrame#bentoCardWidget:hover {
    background-color: #1D2024;
    border-color: #323539;
}

QFrame#sidebarWidget {
    background-color: #191C20;
    border-right: 1px solid #272A2E;
}

QFrame#drawerWidget {
    background-color: #191C20;
    border-left: 1px solid #272A2E;
}

QFrame#codeBoxWidget {
    background-color: #0B0E12;
    border: 1px solid #272A2E;
    border-radius: 6px;
    padding: 6px 10px;
}

/* Labels */
QLabel#titleLabel {
    background-color: transparent;
    font-size: 22px;
    font-weight: 600;
    color: #E1E2E8;
    letter-spacing: -0.01em;
}

QLabel#subtitleLabel {
    background-color: transparent;
    font-size: 13px;
    color: #A58C7D;
}

QLabel#statValueLabel {
    background-color: transparent;
    font-size: 28px;
    font-weight: 600;
    color: #E1E2E8;
    letter-spacing: -0.02em;
}

QLabel#statTitleLabel {
    background-color: transparent;
    font-size: 11px;
    font-weight: 600;
    color: #A58C7D;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

QLabel#sectionTitleLabel {
    background-color: transparent;
    font-size: 15px;
    font-weight: 600;
    color: #E1E2E8;
}
"""

LIGHT_THEME_QSS = """
QWidget {
    color: #1E293B;
    background-color: transparent;
    font-family: "Inter", "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
    selection-background-color: #F6821F;
    selection-color: #FFFFFF;
}

QMainWindow, QDialog, QStackedWidget {
    background-color: #F8FAFC;
}

QLabel {
    background-color: transparent;
    color: #1E293B;
}

QSplitter::handle {
    background-color: #E2E8F0;
}

QScrollArea {
    background-color: transparent;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

QScrollBar:vertical {
    border: none;
    background: #F8FAFC;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #CBD5E1;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #94A3B8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QTabWidget::pane {
    border: 1px solid #E2E8F0;
    background-color: #FFFFFF;
    border-radius: 8px;
}

QTabBar::tab {
    background: #F1F5F9;
    color: #64748B;
    padding: 9px 18px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 4px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    color: #F6821F;
    font-weight: 600;
    border-bottom: 2px solid #F6821F;
}

QPushButton {
    background-color: #F6821F;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 13px;
}
QPushButton:hover {
    background-color: #FF9A47;
}

QPushButton#secondaryBtn {
    background-color: #F1F5F9;
    color: #334155;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
}
QPushButton#secondaryBtn:hover {
    background-color: #E2E8F0;
    color: #0F172A;
}

QPushButton#chipBtn {
    background-color: #F1F5F9;
    color: #64748B;
    border: 1px solid #CBD5E1;
    border-radius: 14px;
    padding: 5px 14px;
    font-size: 12px;
}
QPushButton#chipBtn:checked {
    background-color: #EFF6FF;
    color: #F6821F;
    border: 1px solid #F6821F;
    font-weight: 600;
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background-color: #FFFFFF;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    padding: 8px 12px;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #F6821F;
}

QTableWidget, QTableView, QListWidget {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    gridline-color: #F1F5F9;
    color: #1E293B;
    selection-background-color: #FFF7ED;
    selection-color: #C2410C;
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
    border-radius: 4px;
    text-align: center;
    color: #0F172A;
    font-weight: bold;
    height: 8px;
}
QProgressBar::chunk {
    background: #F6821F;
    border-radius: 4px;
}

QGroupBox {
    background-color: transparent;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 18px;
    font-weight: 600;
    color: #64748B;
}
QGroupBox::title {
    background-color: transparent;
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #F6821F;
}

QFrame#cardWidget {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    padding: 16px;
}

QFrame#heroCardWidget {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 20px;
}

QFrame#bentoCardWidget {
    background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 14px;
}

QFrame#sidebarWidget {
    background-color: #F1F5F9;
    border-right: 1px solid #E2E8F0;
}

QFrame#drawerWidget {
    background-color: #F1F5F9;
    border-left: 1px solid #E2E8F0;
}

QFrame#codeBoxWidget {
    background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    padding: 6px 10px;
}

QLabel#titleLabel {
    background-color: transparent;
    font-size: 22px;
    font-weight: 600;
    color: #0F172A;
}

QLabel#subtitleLabel {
    background-color: transparent;
    font-size: 13px;
    color: #64748B;
}

QLabel#statValueLabel {
    background-color: transparent;
    font-size: 28px;
    font-weight: 600;
    color: #0F172A;
}

QLabel#statTitleLabel {
    background-color: transparent;
    font-size: 11px;
    font-weight: 600;
    color: #64748B;
    text-transform: uppercase;
}

QLabel#sectionTitleLabel {
    background-color: transparent;
    font-size: 15px;
    font-weight: 600;
    color: #0F172A;
}
"""


def apply_theme(app, theme_name: str = "dark") -> None:
    if theme_name.lower() == "light":
        app.setStyleSheet(LIGHT_THEME_QSS)
    else:
        app.setStyleSheet(DARK_THEME_QSS)
