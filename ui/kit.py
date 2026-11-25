"""Componentes visuais reutilizáveis: botões por tipo, barra de uso, diálogos e mensagens."""
from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import (QAbstractButton, QCheckBox, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

ACCENT = "#66c0f4"


# ---------------------------------------------------------------- botões
def set_kind(button, kind):
    """Muda o tipo visual de um botão (padrão, green, blue, danger, cancel, tool, nav, pill)."""
    button.setProperty("kind", kind or "")
    button.style().unpolish(button)
    button.style().polish(button)
    return button


def btn(text, kind=None, slot=None, parent=None):
    b = QPushButton(text, parent)
    if kind:
        b.setProperty("kind", kind)
    b.setCursor(Qt.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


def vsep():
    s = QFrame()
    s.setObjectName("vsep")
    s.setFixedWidth(1)
    s.setFixedHeight(22)
    return s


class _HandCursor(QObject):
    """Ajustes globais aplicados quando cada widget é preparado: cursor de mão em botões e
    títulos de colunas em MAIÚSCULAS (o QSS não tem text-transform)."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Polish:
            if isinstance(obj, QAbstractButton):
                obj.setCursor(Qt.PointingHandCursor)
            elif isinstance(obj, QHeaderView) and obj.orientation() == Qt.Horizontal and not obj.property("_upper"):
                obj.setProperty("_upper", True)
                m = obj.model()
                if m is not None:
                    m.headerDataChanged.connect(lambda o, a, b, m=m: _upper_headers(m, o, a, b))
                    m.columnsInserted.connect(lambda _p, a, b, m=m: _upper_headers(m, Qt.Horizontal, a, b))
                    _upper_headers(m, Qt.Horizontal, 0, m.columnCount() - 1)
        return False


def _upper_headers(model, orient, first, last):
    if orient != Qt.Horizontal:
        return
    for s in range(max(first, 0), last + 1):
        t = model.headerData(s, Qt.Horizontal, Qt.DisplayRole)
        if isinstance(t, str) and t != t.upper():
            model.setHeaderData(s, Qt.Horizontal, t.upper(), Qt.DisplayRole)


_hand = None


def install_hand_cursor(app):
    global _hand
    if _hand is None:
        _hand = _HandCursor(app)
        app.installEventFilter(_hand)


# ---------------------------------------------------------------- setas do combobox (PNG em tempo de execução)
def arrow_png(color=ACCENT):
    path = os.path.join(tempfile.gettempdir(), f"hwscope-arrow-{color.strip('#')}.png")
    if not os.path.exists(path):
        img = QImage(20, 12, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawPolygon(QPolygonF([QPointF(2, 2), QPointF(18, 2), QPointF(10, 10)]))
        p.end()
        img.save(path)
    return path.replace(os.sep, "/")


# ---------------------------------------------------------------- barra de uso / progresso (8 px)
class UsageBar(QWidget):
    """Barra fina de 8 px com o texto à direita. Mesma interface usada do QProgressBar
    (setRange/setValue/setFormat). Em barras de uso, acima de 90 % fica vermelha."""

    BLUE = ("#47bfff", "#1a44c2")
    RED = ("#ff6b6b", "#c43d3d")

    def __init__(self, usage=False, parent=None):
        super().__init__(parent)
        self.usage = usage
        self._min, self._max, self._val = 0, 1000, 0
        self._colors = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._track = _Track(self)
        lay.addWidget(self._track, 1)
        self._label = QLabel("")
        self._label.setObjectName("barText")
        self._label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        lay.addWidget(self._label)
        self.setMinimumHeight(16)

    # interface compatível com QProgressBar
    def setRange(self, a, b):
        self._min, self._max = a, max(b, a + 1)
        self._track.update()

    def setValue(self, v):
        self._val = max(self._min, min(self._max, int(v)))
        self._track.update()

    def value(self):
        return self._val

    def maximum(self):
        return self._max

    def setFormat(self, text):
        self._label.setText(text)

    def format(self):
        return self._label.text()

    def setTextVisible(self, on):
        self._label.setVisible(on)

    def set_colors(self, c1, c2=None):
        """Cores fixas para o preenchimento (ex.: bateria). None volta ao padrão."""
        self._colors = (c1, c2 or c1) if c1 else None
        self._track.update()

    def frac(self):
        return (self._val - self._min) / (self._max - self._min)


class _Track(QWidget):
    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0f1620"))
        p.drawRoundedRect(r, 4, 4)
        f = self.bar.frac()
        if f <= 0:
            return
        c = self.bar._colors or (self.bar.RED if self.bar.usage and f > 0.9 else self.bar.BLUE)
        fr = QRectF(r.x(), r.y(), max(r.width() * f, 8), r.height())
        g = QLinearGradient(fr.topLeft(), fr.topRight())
        g.setColorAt(0, QColor(c[0]))
        g.setColorAt(1, QColor(c[1]))
        p.setBrush(g)
        p.drawRoundedRect(fr, 4, 4)


# ---------------------------------------------------------------- diálogos
class ScopeDialog(QDialog):
    """Diálogo padrão do app: cabeçalho com título em maiúsculas, corpo com margens de 22 px
    e rodapé com os botões alinhados à direita."""

    def __init__(self, parent=None, title="", subtitle="", icon=None, width=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QFrame()
        head.setObjectName("DlgHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(22, 16, 22, 16)
        hl.setSpacing(14)
        if icon is not None:
            ic = QLabel()
            ic.setObjectName("dlgIcon")
            if isinstance(icon, QPixmap):
                ic.setPixmap(icon.scaled(42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                ic.setText(str(icon))
            hl.addWidget(ic, 0, Qt.AlignVCenter)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        self.title_lbl = QLabel(title.upper())
        self.title_lbl.setObjectName("dlgTitle")
        f = self.title_lbl.font()
        f.setPointSizeF(13)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        self.title_lbl.setFont(f)
        tl.addWidget(self.title_lbl)
        self.subtitle_lbl = QLabel(subtitle)
        self.subtitle_lbl.setObjectName("dlgSub")
        self.subtitle_lbl.setVisible(bool(subtitle))
        tl.addWidget(self.subtitle_lbl)
        hl.addLayout(tl, 1)
        outer.addWidget(head)

        self.body_w = QWidget()
        self.body_w.setObjectName("dlgBody")
        self.body = QVBoxLayout(self.body_w)
        self.body.setContentsMargins(22, 18, 22, 8)
        self.body.setSpacing(12)
        outer.addWidget(self.body_w, 1)

        foot = QWidget()
        foot.setObjectName("dlgBody")
        self.footer = QHBoxLayout(foot)
        self.footer.setContentsMargins(22, 10, 22, 18)
        self.footer.setSpacing(10)
        self.footer.addStretch()
        outer.addWidget(foot)
        if width:
            self.setFixedWidth(width)

    def add_button(self, text, kind=None, slot=None):
        b = btn(text, kind, slot)
        b.setMinimumWidth(120)
        self.footer.addWidget(b)
        return b


ICONS = {
    "info": ("i", "#66c0f4"),
    "warn": ("!", "#ffcf6b"),
    "error": ("✕", "#ff6b6b"),
    "ok": ("✓", "#a4d007"),
}


def _round_icon(kind):
    ch, col = ICONS.get(kind, ICONS["info"])
    lb = QLabel(ch)
    lb.setFixedSize(40, 40)
    lb.setAlignment(Qt.AlignCenter)
    lb.setStyleSheet(f"background:transparent; color:{col}; border:2px solid {col}; border-radius:20px;"
                     "font-size:19px; font-weight:700;")
    return lb


def _message_dialog(parent, title, text, kind, subtitle=""):
    d = ScopeDialog(parent, title, subtitle)
    d.setMinimumWidth(460)
    row = QHBoxLayout()
    row.setSpacing(16)
    row.addWidget(_round_icon(kind), 0, Qt.AlignTop)
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setObjectName("dangerText" if kind == "danger" else "msgText")
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    row.addWidget(lb, 1)
    d.body.addLayout(row)
    return d, lb


def message(parent, title, text, kind="info", button="OK"):
    """Substitui QMessageBox.information/warning/critical."""
    d, _ = _message_dialog(parent, title, text, kind)
    d.add_button(button, "blue" if kind != "error" else "cancel", d.accept).setDefault(True)
    d.exec()


def ask(parent, title, text, confirm="CONFIRMAR", kind="warn", confirm_kind="green",
        cancel="CANCELAR", danger_text=None, check_text=None):
    """Pergunta com CANCELAR à esquerda do botão de confirmação. Retorna True se confirmado.

    danger_text: aviso extra em vermelho claro. check_text: exige marcar a caixa para liberar."""
    d, _ = _message_dialog(parent, title, text, kind)
    if danger_text:
        dl = QLabel(danger_text)
        dl.setWordWrap(True)
        dl.setObjectName("dangerText")
        d.body.addWidget(dl)
    chk = None
    if check_text:
        chk = QCheckBox(check_text)
        d.body.addWidget(chk)
    d.add_button(cancel, "cancel", d.reject)
    ok = d.add_button(confirm, confirm_kind, d.accept)
    if chk is not None:
        ok.setEnabled(False)
        chk.toggled.connect(ok.setEnabled)
    else:
        ok.setDefault(True)
    return d.exec() == QDialog.Accepted
