"""Aba Visão geral: cartões e árvore de todos os sensores."""
from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from core import hwinfo as hw
from ui.common import StatCard, fmt, temp_color
from ui.theme import T


class OverviewTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)
        cards = QGridLayout()
        cards.setSpacing(12)
        self.cpu = StatCard("Processador", "cpu")
        self.gpu = StatCard("Placa de vídeo", "gpu")
        self.ram = StatCard("Memória RAM", "ram", fixed_max=100)
        self.disk = StatCard("Armazenamento", "disk")
        for i, c in enumerate((self.cpu, self.gpu, self.ram, self.disk)):
            c.setMinimumHeight(190)
            cards.addWidget(c, 0, i)
            cards.setColumnStretch(i, 1)
        lay.addLayout(cards)

        head = QHBoxLayout()
        t = QLabel("Todos os sensores")
        t.setObjectName("section")
        head.addWidget(t)
        head.addStretch()
        self.reset_btn = QPushButton("Zerar mín/máx")
        head.addWidget(self.reset_btn)
        lay.addLayout(head)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Sensor", "Atual", "Mínimo", "Máximo", "Limite"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setDefaultAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.tree.headerItem().setTextAlignment(0, Qt.AlignLeft | Qt.AlignVCenter)
        for i in range(1, 5):
            h.setSectionResizeMode(i, QHeaderView.Fixed)
            h.resizeSection(i, 110)
        lay.addWidget(self.tree, 1)
        self.items = {}
        self.groups = {}
        self.minmax = {}
        self.reset_btn.clicked.connect(self.reset)
        self.empty = QLabel("Nenhum sensor hwmon encontrado. Em máquinas virtuais isso é normal; "
                            "em PCs reais, rode 'sudo sensors-detect' (pacote lm-sensors) e carregue os módulos sugeridos.")
        self.empty.setWordWrap(True)
        self.empty.setObjectName("muted")
        self.empty.hide()
        lay.addWidget(self.empty)

    def reset(self):
        self.minmax.clear()

    fan_names = {}

    def update_sensors(self, chips):
        self.empty.setVisible(not chips)
        kinds_order = ["cpu", "gpu", "mem", "disk", "board", "other"]
        alive = set()
        for chip in sorted(chips, key=lambda c: kinds_order.index(c["kind"])):
            gkey = chip["id"]
            alive.add(gkey)
            grp = self.groups.get(gkey)
            if grp is None:
                grp = QTreeWidgetItem([f"{hw.KIND_LABEL[chip['kind']]} — {chip['title']}"])
                f = grp.font(0)
                f.setBold(True)
                grp.setFont(0, f)
                grp.setToolTip(0, f"{chip['name']}  ({chip['path']})")
                self.tree.addTopLevelItem(grp)
                grp.setExpanded(True)
                grp.setFirstColumnSpanned(False)
                self.groups[gkey] = grp
            grp.setForeground(0, QBrush(QColor({"cpu": T.cpu, "gpu": T.gpu, "disk": T.disk,
                                                 "mem": T.ram}.get(chip["kind"], T.text))))
            for s in chip["sensors"]:
                k = s["key"]
                alive.add(k)
                mn, mx = self.minmax.get(k, (s["value"], s["value"]))
                mn, mx = min(mn, s["value"]), max(mx, s["value"])
                self.minmax[k] = (mn, mx)
                nd = 0 if s["unit"] in ("RPM", "MHz") else (3 if s["unit"] in ("V", "A") else 1)
                lim = s["crit"] or s["max"]
                lab = s["label"]
                if k in self.fan_names:
                    lab = f"{self.fan_names[k]}  ({s['label']})"
                vals = [lab, fmt(s["value"], s["unit"], nd), fmt(mn, s["unit"], nd),
                        fmt(mx, s["unit"], nd), fmt(lim, s["unit"], nd) if lim else ""]
                it = self.items.get(k)
                if it is None:
                    it = QTreeWidgetItem(vals)
                    for i in range(1, 5):
                        it.setTextAlignment(i, Qt.AlignRight | Qt.AlignVCenter)
                    grp.addChild(it)
                    self.items[k] = it
                else:
                    for i, v in enumerate(vals):
                        if it.text(i) != v:
                            it.setText(i, v)
                if s["type"] == "temp":
                    it.setForeground(1, QBrush(QColor(temp_color(s["value"]))))
                    it.setForeground(3, QBrush(QColor(temp_color(mx))))
        # remove sensores que sumiram
        for k in list(self.items):
            if k not in alive:
                it = self.items.pop(k)
                (it.parent() or self.tree.invisibleRootItem()).removeChild(it)
        for k in list(self.groups):
            if k not in alive:
                self.tree.invisibleRootItem().removeChild(self.groups.pop(k))
