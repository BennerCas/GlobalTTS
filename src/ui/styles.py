"""Estilos visuales Ejecutivos Premium para GlobalTTS.

Diseño exclusivo Obsidian & Titanium Slate:
- Paleta seria, sobria, sin gradientes chillones ni elementos infantiles.
- Bordes micrométricos en titanio (#1e2633 / #334155).
- Acentos funcionales en azul real corporativo (#1d4ed8 / #2563eb).
- Tipografía nítida de alta jerarquía y legibilidad industrial.
- Firma institucional de rigor: HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®
"""

DARK_THEME_QSS = """
QWidget {
    background-color: #090d14;
    color: #e2e8f0;
    font-family: 'Segoe UI', 'Inter', -apple-system, sans-serif;
    font-size: 13px;
}

QDialog {
    background-color: #0c111a;
    border: 1px solid #1e2633;
    border-radius: 8px;
}

QLabel {
    color: #94a3b8;
}

QLabel#titleLabel {
    font-size: 18px;
    font-weight: 700;
    color: #f8fafc;
    letter-spacing: 0.4px;
}

QLabel#subtitleLabel {
    font-size: 12px;
    color: #64748b;
}

QLabel#footerLabel {
    font-size: 11px;
    font-weight: 700;
    color: #475569;
    letter-spacing: 1px;
    text-transform: uppercase;
}

QLabel#metricTitle {
    font-size: 11px;
    font-weight: 700;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.8px;
}

QLabel#metricValue {
    font-size: 15px;
    font-weight: 700;
    color: #38bdf8;
    font-family: 'Consolas', monospace;
}

QLabel#metricValueActive {
    font-size: 15px;
    font-weight: 700;
    color: #22c55e;
    font-family: 'Consolas', monospace;
}

QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #0b0f16;
    border: 1px solid #1e2633;
    border-radius: 5px;
    padding: 7px 11px;
    color: #f8fafc;
    selection-background-color: #1d4ed8;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #3b82f6;
    background-color: #0d131e;
}

QComboBox {
    background-color: #0b0f16;
    border: 1px solid #1e2633;
    border-radius: 5px;
    padding: 6px 12px;
    color: #f1f5f9;
}

QComboBox:hover {
    border: 1px solid #334155;
    background-color: #0f141f;
}

QComboBox:focus {
    border: 1px solid #3b82f6;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left-width: 0px;
}

QComboBox QAbstractItemView {
    background-color: #0f141f;
    border: 1px solid #1e2633;
    selection-background-color: #1e293b;
    selection-color: #f8fafc;
    color: #e2e8f0;
    padding: 4px;
}

QSpinBox, QDoubleSpinBox {
    background-color: #0b0f16;
    border: 1px solid #1e2633;
    border-radius: 5px;
    padding: 6px 10px;
    color: #f8fafc;
}

QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #3b82f6;
}

QPushButton {
    background-color: #131924;
    color: #cbd5e1;
    border: 1px solid #1e2633;
    border-radius: 5px;
    padding: 7px 15px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #1a2230;
    border-color: #334155;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #0f141d;
}

QPushButton:disabled {
    background-color: #0e1219;
    color: #475569;
    border-color: #18202c;
}

QPushButton#primaryButton {
    background-color: #1d4ed8;
    color: #ffffff;
    border: 1px solid #2563eb;
    padding: 10px 18px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.3px;
    border-radius: 6px;
}

QPushButton#primaryButton:hover {
    background-color: #2563eb;
    border-color: #3b82f6;
}

QPushButton#primaryButton:disabled {
    background-color: #131924;
    color: #475569;
    border-color: #1e2633;
}

QPushButton#actionButton {
    background-color: #1e293b;
    color: #93c5fd;
    border: 1px solid #334155;
    padding: 7px 13px;
    font-weight: 600;
    border-radius: 5px;
}

QPushButton#actionButton:hover {
    background-color: #2563eb;
    color: #ffffff;
    border-color: #3b82f6;
}

QPushButton#secondaryActionButton {
    background-color: #0f141d;
    color: #94a3b8;
    border: 1px solid #1e2633;
    padding: 7px 13px;
    font-weight: 600;
    border-radius: 5px;
}

QPushButton#secondaryActionButton:hover {
    background-color: #18202d;
    border-color: #334155;
    color: #f1f5f9;
}

QPushButton#brandButton {
    background-color: #0f141d;
    color: #cbd5e1;
    border: 1px solid #334155;
    padding: 7px 14px;
    font-weight: 600;
    border-radius: 5px;
}

QPushButton#brandButton:hover {
    background-color: #1e293b;
    border-color: #475569;
    color: #ffffff;
}

QFrame#cardFrame {
    background-color: #0c111a;
    border: 1px solid #1e2633;
    border-radius: 6px;
    padding: 12px;
}

QFrame#metricCard {
    background-color: #0b0f16;
    border: 1px solid #18202c;
    border-radius: 6px;
    padding: 8px 12px;
}

QFrame#resultCard {
    background-color: #0c131d;
    border: 1px solid #1e3a5f;
    border-radius: 6px;
    padding: 12px;
}

QGroupBox {
    border: 1px solid #1e2633;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 14px;
    font-weight: 700;
    font-size: 11px;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 5px;
    background-color: #090d14;
}

QCheckBox {
    spacing: 8px;
    color: #cbd5e1;
}

QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border-radius: 3px;
    border: 1px solid #232e3f;
    background-color: #0b0f16;
}

QCheckBox::indicator:hover {
    border-color: #3b82f6;
}

QCheckBox::indicator:checked {
    background-color: #1d4ed8;
    border: 1px solid #3b82f6;
}

QProgressBar {
    border: 1px solid #1e2633;
    border-radius: 4px;
    text-align: center;
    background-color: #0b0f16;
    color: #f8fafc;
    font-weight: 700;
    font-family: 'Consolas', monospace;
    font-size: 11px;
    height: 20px;
}

QProgressBar::chunk {
    background-color: #1d4ed8;
    border-radius: 3px;
}

QSlider::groove:horizontal {
    height: 4px;
    background: #1e2633;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: #2563eb;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: #38bdf8;
    border: 1px solid #7dd3fc;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}

QSlider::handle:horizontal:hover {
    background: #ffffff;
    border-color: #ffffff;
}

QTableWidget {
    background-color: #0b0f16;
    alternate-background-color: #0e131b;
    border: 1px solid #1e2633;
    border-radius: 6px;
    gridline-color: #151c27;
    selection-background-color: #1e293b;
    selection-color: #ffffff;
    color: #e2e8f0;
}

QHeaderView::section {
    background-color: #0f141d;
    color: #64748b;
    border: none;
    border-bottom: 1px solid #1e2633;
    border-right: 1px solid #151c27;
    padding: 7px 10px;
    font-weight: 700;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}

QTabBar::tab {
    background: #0c1017;
    color: #64748b;
    padding: 8px 14px;
    font-weight: 600;
    font-size: 12px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 3px;
    border: 1px solid #161e2b;
    border-bottom: none;
}

QPushButton#tabCornerButton {
    background: #0c1017;
    color: #38bdf8;
    padding: 6px 11px;
    font-weight: 700;
    font-size: 11px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
    border: 1px solid #1e293b;
    border-bottom: none;
}

QPushButton#tabCornerButton:hover {
    background: #131c2b;
    color: #ffffff;
    border-color: #38bdf8;
}

QTabBar::tab:selected {
    background: #090d14;
    color: #38bdf8;
    border-top: 2px solid #2563eb;
    border-left: 1px solid #1e2633;
    border-right: 1px solid #1e2633;
    border-bottom: 1px solid #090d14;
}

QTabBar::tab:hover:!selected {
    background: #111721;
    color: #94a3b8;
}

QMenu {
    background-color: #0c111a;
    border: 1px solid #1e2633;
    border-radius: 6px;
    padding: 5px;
}

QMenu::item {
    padding: 7px 22px;
    border-radius: 4px;
    color: #cbd5e1;
}

QMenu::item:selected {
    background-color: #1d4ed8;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #1e2633;
    margin: 4px 8px;
}

QScrollBar:vertical {
    background: #090d14;
    width: 6px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #1e2633;
    min-height: 20px;
    border-radius: 3px;
}

QScrollBar::handle:vertical:hover {
    background: #334155;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""
