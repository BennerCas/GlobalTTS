"""Estilos visuales Premium para la UI en PyQt6 según DISENO.md.

Glassmorphism en modo oscuro, acentos cian/azul moderno,
tipografía limpia y transiciones elegantes.
"""

DARK_THEME_QSS = """
QWidget {
    background-color: #0d1117;
    color: #e6edf3;
    font-family: 'Segoe UI', 'Inter', -apple-system, sans-serif;
    font-size: 13px;
}

QDialog {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 12px;
}

QLabel {
    color: #c9d1d9;
}

QLabel#titleLabel {
    font-size: 19px;
    font-weight: 700;
    color: #58a6ff;
}

QLabel#subtitleLabel {
    font-size: 12px;
    color: #8b949e;
}

QLabel#footerLabel {
    font-size: 11px;
    font-weight: 600;
    color: #484f58;
    letter-spacing: 0.5px;
}

QLabel#metricTitle {
    font-size: 11px;
    font-weight: 600;
    color: #8b949e;
    text-transform: uppercase;
}

QLabel#metricValue {
    font-size: 15px;
    font-weight: 700;
    color: #58a6ff;
    font-family: 'Consolas', 'Segoe UI', monospace;
}

QLabel#metricValueActive {
    font-size: 15px;
    font-weight: 700;
    color: #3fb950;
    font-family: 'Consolas', 'Segoe UI', monospace;
}

QLineEdit {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 8px 12px;
    color: #ffffff;
    selection-background-color: #1f6feb;
}

QLineEdit:focus {
    border: 1px solid #58a6ff;
    background-color: #121820;
}

QComboBox {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 12px;
    color: #ffffff;
}

QComboBox:hover {
    border: 1px solid #58a6ff;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 25px;
    border-left-width: 0px;
}

QComboBox QAbstractItemView {
    background-color: #161b22;
    border: 1px solid #30363d;
    selection-background-color: #1f6feb;
    color: #ffffff;
}

QPushButton {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #30363d;
    border-color: #8b949e;
    color: #ffffff;
}

QPushButton#primaryButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1f6feb, stop:1 #238636);
    color: #ffffff;
    border: none;
    padding: 11px 20px;
    font-size: 14px;
    border-radius: 8px;
}

QPushButton#primaryButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #388bfd, stop:1 #2ea043);
}

QPushButton#primaryButton:disabled {
    background-color: #21262d;
    color: #484f58;
}

QPushButton#actionButton {
    background-color: #1f6feb;
    color: #ffffff;
    border: none;
    padding: 8px 14px;
    font-weight: 600;
    border-radius: 6px;
}

QPushButton#actionButton:hover {
    background-color: #388bfd;
}

QPushButton#secondaryActionButton {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    padding: 8px 14px;
    font-weight: 600;
    border-radius: 6px;
}

QPushButton#secondaryActionButton:hover {
    background-color: #30363d;
    border-color: #58a6ff;
    color: #ffffff;
}

QFrame#cardFrame {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px;
}

QFrame#metricCard {
    background-color: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 8px 12px;
}

QFrame#resultCard {
    background-color: #0d1117;
    border: 1px solid #238636;
    border-radius: 8px;
    padding: 12px;
}

QCheckBox {
    spacing: 8px;
    color: #c9d1d9;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #30363d;
    background-color: #0d1117;
}

QCheckBox::indicator:checked {
    background-color: #1f6feb;
    border: 1px solid #58a6ff;
}

QProgressBar {
    border: 1px solid #30363d;
    border-radius: 6px;
    text-align: center;
    background-color: #0d1117;
    color: #ffffff;
    font-weight: 700;
    font-family: 'Consolas', monospace;
    height: 22px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1f6feb, stop:1 #2ea043);
    border-radius: 5px;
}

QMenu {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 6px;
}

QMenu::item {
    padding: 8px 24px;
    border-radius: 4px;
    color: #e6edf3;
}

QMenu::item:selected {
    background-color: #1f6feb;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #30363d;
    margin: 4px 8px;
}
"""
