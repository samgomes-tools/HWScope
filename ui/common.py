"""Widgets e funções compartilhados entre as abas."""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ui.theme import T, tcolor, themed


ADMIN = {"on": False, "rapl": False}


def need_admin(off_text, on_text):
    """Texto de dica conforme o Modo administrador esteja ou não ativo."""
    return on_text if ADMIN["on"] else off_text


def temp_color(t):
    if t is None:
        return T.muted
    if t < 60:
        return "#4fd18b"
    if t < 80:
        return "#f5c542"
    return "#ff5d5d"


def fmt(v, unit="", nd=0, none="—"):
    if v is None:
        return none
    try:
        return f"{v:.{nd}f}{(' ' + unit) if unit else ''}"
    except (TypeError, ValueError):
        return f"{v}{(' ' + unit) if unit else ''}"


class Sparkline(QWidget):
    def __init__(self, color, maxlen=120, fixed_max=None, parent=None):
        super().__init__(parent)
        self.color = color
        self.data = deque(maxlen=maxlen)
        self.data2 = deque(maxlen=maxlen)
        self.color2 = "#ffffff"
        self.fixed_max = fixed_max
        self.setMinimumHeight(54)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def add(self, v, v2=None):
        self.data.append(v if v is not None else float("nan"))
        if v2 is not None or self.data2:
            self.data2.append(v2 if v2 is not None else float("nan"))
        self.update()

    def clear(self):
        self.data.clear()
        self.data2.clear()
        self.update()

    def _path(self, data, w, h, top, mx, mn):
        n = self.data.maxlen
        path = QPainterPath()
        started = False
        start_x = 0
        pts = list(data)
        for i, v in enumerate(pts):
            if v != v:  # NaN
                continue
            x = w - (len(pts) - 1 - i) * (w / (n - 1))
            y = top + h - (v - mn) / (mx - mn or 1) * h
            y = max(top, min(top + h, y))
            if not started:
                path.moveTo(x, y)
                start_x = x
                started = True
            else:
                path.lineTo(x, y)
        return path, started, start_x

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor(T.panel2))
        p.setPen(QPen(QColor(T.border), 1))
        for i in range(1, 4):
            y = r.height() * i / 4
            p.drawLine(QPointF(0, y), QPointF(r.width(), y))
        vals = [v for v in list(self.data) + list(self.data2) if v == v]
        if not vals:
            p.end()
            return
        mx = self.fixed_max or max(max(vals) * 1.15, 1)
        mn = 0
        top, h, w = 4, r.height() - 6, r.width()
        if self.data2:
            path2, ok2, _ = self._path(self.data2, w, h, top, mx, mn)
            if ok2:
                p.setPen(QPen(tcolor(self.color2), 1.3, Qt.DashLine))
                p.drawPath(path2)
        path, ok, sx = self._path(self.data, w, h, top, mx, mn)
        if ok:
            fill = QPainterPath(path)
            fill.lineTo(w, top + h)
            fill.lineTo(sx, top + h)
            fill.closeSubpath()
            g = QLinearGradient(0, top, 0, top + h)
            c1 = tcolor(self.color)
            c1.setAlpha(110)
            c2 = tcolor(self.color)
            c2.setAlpha(8)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.fillPath(fill, QBrush(g))
            p.setPen(QPen(tcolor(self.color), 2))
            p.drawPath(path)
        p.end()


class StatCard(QFrame):
    def __init__(self, title, color, fixed_max=None):
        super().__init__()
        self.setObjectName("card")
        self.color = color
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        top = QHBoxLayout()
        dot = QLabel("●")
        themed(dot, lambda w: w.setStyleSheet(f"color:{tcolor(color).name()}; font-size:13px;"))
        t = QLabel(title.upper())
        t.setObjectName("cardTitle")
        top.addWidget(dot)
        top.addWidget(t)
        top.addStretch()
        self.badge = QLabel("")
        self.badge.setObjectName("badge")
        top.addWidget(self.badge)
        lay.addLayout(top)
        self.name = QLabel("—")
        self.name.setObjectName("cardName")
        self.name.setWordWrap(False)
        self.name.setMinimumWidth(10)
        self.name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(self.name)
        row = QHBoxLayout()
        self.big = QLabel("—")
        self.big.setObjectName("big")
        row.addWidget(self.big)
        row.addStretch()
        self.side = QLabel("")
        self.side.setObjectName("cardSide")
        self.side.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.side)
        lay.addLayout(row)
        self.spark = Sparkline(color, fixed_max=fixed_max)
        lay.addWidget(self.spark, 1)
        self.foot = QLabel("")
        self.foot.setObjectName("muted")
        lay.addWidget(self.foot)

    def set_big(self, text, color=None):
        self.big.setText(text)
        self.big.setStyleSheet(f"color:{color or T.text};")


class InfoGroup(QGroupBox):
    """Caixa estilo CPU-Z: rótulo à esquerda, campo à direita."""

    def __init__(self, title, cols=1):
        super().__init__(title)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(12, 18, 12, 10)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(6)
        self.cols = cols
        self.fields = {}
        self._n = 0

    def add(self, key, label=None, span=1):
        r, c = divmod(self._n, self.cols)
        lab = QLabel(label or key)
        lab.setObjectName("fieldLabel")
        val = QLabel("—")
        val.setObjectName("field")
        val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        val.setMinimumWidth(40)
        val.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.grid.addWidget(lab, r, c * 2)
        self.grid.addWidget(val, r, c * 2 + 1, 1, span * 2 - 1)
        for i in range(self.cols):
            self.grid.setColumnStretch(i * 2 + 1, 1)
        self._n += span if span > 1 else 1
        if span > 1:
            self._n = (r + 1) * self.cols
        self.fields[key] = val
        return val

    def set(self, key, value, color=None):
        if key not in self.fields:
            self.add(key)
        w = self.fields[key]
        txt = "—" if value in (None, "") else str(value)
        if w.text() != txt:
            w.setText(txt)
            w.setToolTip(txt)
        if color:
            w.setStyleSheet(f"color:{color};")

    def set_many(self, d):
        for k, v in d.items():
            self.set(k, v)


def bar(color=None, h=None, usage=False):
    """Barra fina de 8 px (gradiente azul) com o texto ao lado.
    usage=True: barras de uso, que ficam vermelhas acima de 90 %. color/h mantidos por compatibilidade."""
    from ui.kit import UsageBar
    b = UsageBar(usage=usage)
    b.setRange(0, 1000)
    return b


def scroll(widget):
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.NoFrame)
    s.setWidget(widget)
    return s


def hexdec(v):
    try:
        i = int(v)
        return f"{i} (0x{i:X})"
    except (TypeError, ValueError):
        return v


def rate_text(bps):
    if bps >= 1e6:
        return f"{bps / 1e6:.2f} MB/s"
    return f"{bps / 1e3:.1f} KB/s"


def fmt_duration(s):
    s = max(0, int(s))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}h {m:02d}min {s:02d}s" if h else f"{m:02d}min {s:02d}s"
