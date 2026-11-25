"""Tema visual (escuro azul) e folha de estilo Qt."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget


class Theme:
    """Paleta ativa. Os widgets leem T.<cor> na hora de desenhar, então trocar o
    tema em tempo de execução só exige reaplicar a folha de estilo e repintar."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def apply(self, other):
        self.__dict__.update(other.__dict__)


# Tema único: azul-escuro, destaque azul-claro,
# botão principal verde e cantos retos.
T = Theme(
    name="HWScope", bg="#1b2838", panel="#16202d", panel2="#213345", alt="#1a2533", border="#2c4258",
    toolbar="#171a21", text="#c7d5e0", muted="#8f98a0", accent="#66c0f4", highlight="#2a475e",
    cpu="#66c0f4", gpu="#a4d007", ram="#e8a33d", disk="#b48ef5", swap="#57cbde", write="#f5c542",
    primary_bg="#75b022", primary_fg="#d2efa9", primary_bg2="#588a1b",
    btn_bg="#2a3f5a", btn_fg="#66c0f4", btn_hover_bg="#66c0f4", btn_hover_bg2="#417a9b", btn_hover_fg="#ffffff",
    radius="2px")


_THEMED = []   # (weakref do widget, função que reaplica as cores)


def themed(widget, fn):
    """Registra um widget cujas cores dependem do tema e aplica agora."""
    import weakref
    fn(widget)
    _THEMED.append((weakref.ref(widget), fn))
    return widget


def retheme_widgets():
    alive = []
    for ref, fn in _THEMED:
        w = ref()
        if w is None:
            continue
        try:
            fn(w)
            alive.append((ref, fn))
        except RuntimeError:  # widget C++ já destruído
            pass
    _THEMED[:] = alive


def tcolor(c):
    """Aceita uma chave do tema ("cpu") ou uma cor ("#ff0000")."""
    if isinstance(c, QColor):
        return c
    if isinstance(c, str) and not c.startswith("#") and hasattr(T, c):
        return QColor(getattr(T, c))
    return QColor(c)


FONT = '"Motiva Sans", "Noto Sans", "Segoe UI", "Cantarell", "Arial"'
MONO = '"JetBrains Mono", "DejaVu Sans Mono", monospace'


def build_style():
    from ui.kit import arrow_png
    ARROW = arrow_png(T.accent)
    G = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {}, stop:1 {})".format
    return f"""
* {{ font-family: {FONT}; font-size: 10pt; }}
QMainWindow, QWidget {{ background: {T.bg}; color: {T.text}; }}
QDialog, QWidget#dlgBody {{ background: {T.bg}; }}

/* cabeçalho, barra de ferramentas e faixa de aviso */
QWidget#Header {{ background: #171a21; }}
QWidget#Header QLabel {{ background: transparent; }}
QLabel#appName {{ background: transparent; color: #ffffff; }}
QLabel#appVer {{ background: transparent; color: {T.muted}; font-size: 9pt; }}
QWidget#Toolbar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1f2c3b, stop:1 #1b2838); border-bottom: 1px solid #0e141b; }}
QWidget#Toolbar QLabel {{ background: transparent; color: {T.muted}; }}
QFrame#vsep {{ background: #2a3f5a; border: none; }}
QFrame#Banner {{ background: #3a2f1c; border-bottom: 1px solid #0e141b; }}
QFrame#Banner QLabel {{ background: transparent; color: #ffcf6b; }}

/* botões */
QPushButton {{ background: #2a3f5a; color: #66c0f4; border: none; border-radius: 3px; padding: 0 16px; min-height: 32px; font-weight: 600; }}
QPushButton:hover {{ background: #66c0f4; color: #ffffff; }}
QPushButton:pressed {{ background: #4aa3d8; color: #ffffff; }}
QPushButton:disabled {{ background: #232d39; color: #4f5a66; }}
QPushButton[kind="green"] {{ background: {G("#75b022", "#588a1b")}; color: #ffffff; font-weight: 700; }}
QPushButton[kind="green"]:hover {{ background: {G("#8ed629", "#6aa621")}; }}
QPushButton[kind="green"]:disabled {{ background: #2f4220; color: #5d7044; }}
QPushButton[kind="blue"] {{ background: {G("#47bfff", "#1a44c2")}; color: #ffffff; }}
QPushButton[kind="blue"]:hover {{ background: {G("#66ccff", "#2a5ae0")}; }}
QPushButton[kind="blue"]:disabled {{ background: #1f3350; color: #50647e; }}
QPushButton[kind="danger"] {{ background: {G("#c43d3d", "#8f2424")}; color: #ffffff; font-weight: 700; }}
QPushButton[kind="danger"]:hover {{ background: {G("#d85050", "#a52e2e")}; }}
QPushButton[kind="danger"]:disabled {{ background: #3d2424; color: #7a5252; }}
QPushButton[kind="cancel"] {{ background: #3d4450; color: #dcdedf; }}
QPushButton[kind="cancel"]:hover {{ background: #4e5664; color: #ffffff; }}
QPushButton[kind="tool"] {{ background: transparent; color: {T.text}; min-height: 30px; padding: 0 12px; font-weight: 600; }}
QPushButton[kind="tool"]:hover {{ background: #2a3f5a; color: #ffffff; }}
QPushButton[kind="tool"]:disabled {{ background: transparent; color: #4f5a66; }}
QPushButton[kind="tool"][state="on"], QPushButton[kind="tool"][state="on"]:disabled {{ color: #a4d007; }}
QPushButton[kind="tool"][state="warn"] {{ color: #ffcf6b; }}
QPushButton[kind="tool"][state="bad"] {{ color: #ff6b6b; }}
QPushButton[kind="nav"] {{ background: transparent; color: #dcdedf; font-size: 11pt; font-weight: 700; min-height: 54px; max-height: 54px;
    padding: 0 11px; border-radius: 0px; border-bottom: 3px solid transparent; }}
QPushButton[kind="nav"]:hover {{ background: transparent; color: #ffffff; }}
QPushButton[kind="nav"]:checked {{ color: #66c0f4; border-bottom: 3px solid #1a9fff; }}
QPushButton[kind="pill"] {{ border-radius: 13px; min-height: 26px; max-height: 26px; padding: 0 14px; font-size: 9pt; font-weight: 700; }}
QPushButton[kind="pill"][state="ok"] {{ background: #1f3a20; color: #a4d007; }}
QPushButton[kind="pill"][state="warn"] {{ background: #3a2f1c; color: #ffcf6b; }}
QPushButton[kind="pill"][state="bad"] {{ background: #3a1c1c; color: #ff6b6b; }}
QPushButton[kind="pill"]:hover {{ color: #ffffff; }}

/* abas internas (Discos, Dispositivos, GPU) */
QTabWidget::pane {{ border: none; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: #dcdedf; padding: 9px 16px; border: none; border-bottom: 3px solid transparent; font-weight: 700; }}
QTabBar::tab:selected {{ color: #66c0f4; border-bottom: 3px solid #1a9fff; }}
QTabBar::tab:hover {{ color: #ffffff; }}

/* cartões e grupos */
QFrame#card {{ background: {T.panel}; border: 1px solid #2a3f5a; border-radius: 3px; }}
QFrame#card QLabel {{ background: transparent; }}
QLabel#cardTitle {{ background: transparent; color: #66c0f4; font-size: 9pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#cardName {{ background: transparent; color: #ffffff; font-weight: 600; }}
QLabel#cardSide {{ background: transparent; color: {T.muted}; }}
QLabel#badge {{ background: #2a3f5a; color: {T.text}; border-radius: 3px; padding: 2px 8px; font-size: 9pt; }}
QLabel#big {{ background: transparent; font-size: 26pt; font-weight: 300; color: #ffffff; }}
QLabel#muted {{ color: {T.muted}; font-size: 9pt; background: transparent; }}
QLabel#section {{ background: transparent; color: #66c0f4; font-size: 9pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#hero {{ background: transparent; font-size: 17pt; font-weight: 300; color: #ffffff; padding: 2px 0 4px 2px; }}
QGroupBox {{ background: {T.panel}; border: 1px solid #2a3f5a; border-radius: 3px; margin-top: 12px; padding-top: 8px; font-weight: 700; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #66c0f4; font-size: 9pt; }}
QGroupBox QLabel, QGroupBox QWidget {{ background: transparent; }}
QLabel#fieldLabel {{ background: transparent; color: {T.muted}; font-weight: 400; }}
QLabel#field {{ background: #0f1620; border: 1px solid #2a3f5a; border-radius: 3px; padding: 4px 8px; color: {T.text}; }}
QLabel#fieldSmall {{ background: #0f1620; border: 1px solid #2a3f5a; border-radius: 3px; padding: 2px 8px; font-size: 9pt; }}
QLabel#barText {{ background: transparent; color: {T.muted}; font-size: 9pt; }}

/* console / log */
QPlainTextEdit {{ background: #0b0f14; color: #a7b6c2; border: 1px solid #2a3f5a; border-radius: 3px; font-family: {MONO}; font-size: 9pt; }}

/* listas e tabelas */
QTreeWidget, QTableWidget, QListWidget {{ background: {T.panel}; alternate-background-color: #1a2533; border: 1px solid #2a3f5a;
    border-radius: 3px; gridline-color: #223246; selection-background-color: #2a475e; selection-color: #ffffff; outline: 0; }}
QTableWidget QWidget {{ background: transparent; }}
QHeaderView {{ background: #1f2c3b; }}
QHeaderView::section {{ background: #1f2c3b; color: #8f98a0; border: none; border-bottom: 1px solid #0e141b; padding: 6px 8px; font-size: 8pt; font-weight: 700; }}
QTableCornerButton::section {{ background: #1f2c3b; border: none; }}
QTreeWidget::item, QTableWidget::item, QListWidget::item {{ padding: 3px; }}
QTreeWidget::item:hover, QTableWidget::item:hover, QListWidget::item:hover {{ background: #223246; }}
QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {{ background: {G("#3d6c8d", "#2a475e")}; color: #ffffff; }}
QListWidget#diskList::item {{ padding: 10px; border-bottom: 1px solid #223246; }}
QListWidget#diskList::item:selected {{ background: {G("#3d6c8d", "#2a475e")}; color: #ffffff; }}

/* campos */
QComboBox {{ background: #2a3f5a; color: {T.text}; border: 1px solid transparent; border-radius: 3px; padding: 0 10px; min-height: 30px; }}
QComboBox:hover {{ border-color: #66c0f4; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({ARROW}); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{ background: #3d4450; color: #dcdedf; border: none; outline: 0; selection-background-color: #dcdedf; selection-color: #171a21; }}
QLineEdit, QSpinBox, QDoubleSpinBox {{ background: #0f1620; color: {T.text}; border: 1px solid #2a3f5a; border-radius: 3px; padding: 4px 8px; min-height: 22px; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: #66c0f4; }}
QCheckBox, QRadioButton {{ background: transparent; spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; background: #0f1620; border: 1px solid #2a3f5a; }}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: #66c0f4; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: #66c0f4; border-color: #66c0f4; }}

/* rolagem, menus, dicas, barra de status */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #3d4b5c; border-radius: 5px; min-height: 30px; margin: 1px; }}
QScrollBar::handle:horizontal {{ background: #3d4b5c; border-radius: 5px; min-width: 30px; margin: 1px; }}
QScrollBar::handle:hover {{ background: #4d5d70; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QMenu {{ background: #3d4450; color: #dcdedf; border: 1px solid #2a3f5a; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; background: transparent; }}
QMenu::item:selected {{ background: #dcdedf; color: #171a21; }}
QToolTip {{ background: #3d4450; color: #dcdedf; border: none; padding: 5px 8px; }}
QStatusBar {{ background: #171a21; color: {T.muted}; border-top: 1px solid #0e141b; }}
QStatusBar QLabel {{ background: transparent; color: {T.muted}; font-size: 9pt; }}

/* diálogos */
QFrame#DlgHead {{ background: {G("#2a475e", "#1b2838")}; }}
QFrame#DlgHead QLabel {{ background: transparent; }}
QLabel#dlgTitle {{ color: #ffffff; background: transparent; }}
QLabel#dlgSub {{ color: {T.muted}; background: transparent; }}
QLabel#msgText {{ color: {T.text}; background: transparent; }}
QLabel#dangerText {{ color: #ff8a8a; background: transparent; }}
QLabel#aboutItem {{ background: transparent; }}
QLabel#aboutCredit {{ color: {T.muted}; background: transparent; }}
"""


def apply_theme(app):
    pal = app.palette()
    for role, col in ((QPalette.Window, T.bg), (QPalette.Base, T.panel), (QPalette.Text, T.text),
                      (QPalette.WindowText, T.text), (QPalette.Button, T.panel2), (QPalette.ButtonText, T.text),
                      (QPalette.Highlight, T.highlight), (QPalette.HighlightedText, T.text),
                      (QPalette.AlternateBase, T.alt), (QPalette.ToolTipBase, T.panel2),
                      (QPalette.ToolTipText, T.text)):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    from ui.kit import install_hand_cursor
    install_hand_cursor(app)
    app.setStyleSheet(build_style())
    retheme_widgets()
    for w in app.allWidgets():
        QWidget.update(w)
