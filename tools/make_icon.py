#!/usr/bin/env python3
"""Gera hwscope.png (256 px) a partir de hwscope.svg.

Uso:  python3 tools/make_icon.py
"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app = QGuiApplication(sys.argv)
size = 256
img = QImage(size, size, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
QSvgRenderer(os.path.join(BASE, "hwscope.svg")).render(p)
p.end()
img.save(os.path.join(BASE, "hwscope.png"))
print("hwscope.png gerado")
