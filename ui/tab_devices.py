"""Aba Dispositivos: rede, bateria, ventoinhas, USB e áudio."""
from __future__ import annotations

import time
from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QListWidget,
                               QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from core import hwinfo as hw
from core import devices
from core.hwinfo import human_bytes
from ui.common import rate_text
from ui.common import InfoGroup, Sparkline, bar, fmt, scroll
from ui.theme import T, themed


class DevicesTab(QWidget):
    """Rede, bateria, ventoinhas, USB e áudio."""

    def __init__(self):
        super().__init__()
        L = QVBoxLayout(self)
        L.setContentsMargins(14, 10, 14, 14)
        self.sub = QTabWidget()
        self.sub.setObjectName("subtabs")
        L.addWidget(self.sub)
        self._build_net()
        self._build_bat()
        self._build_fans()
        self._build_usb()
        self._build_audio()
        self.fan_names = devices.load_fan_names()
        self.fan_stats = {}
        self._last_net = None
        self.net_hist = {}
        self.nets = []

    # ---------------- Rede ----------------
    def _build_net(self):
        w = QWidget()
        L = QHBoxLayout(w)
        L.setContentsMargins(0, 8, 0, 0)
        L.setSpacing(12)
        self.net_list = QListWidget()
        self.net_list.setFixedWidth(250)
        self.net_list.setObjectName("diskList")
        L.addWidget(self.net_list)
        right = QWidget()
        R = QVBoxLayout(right)
        R.setContentsMargins(0, 0, 0, 0)
        R.setSpacing(10)
        self.net_info = InfoGroup("Interface", cols=2)
        for k in ("Nome", "Tipo", "Estado", "Velocidade do link", "Adaptador", "Barramento", "Driver",
                  "Versão do driver", "MAC", "MTU", "IPv4", "Gateway", "IPv6", "DNS", "Hostname"):
            self.net_info.add(k)
        R.addWidget(self.net_info)
        self.wifi = InfoGroup("Wi-Fi", cols=2)
        for k in ("Rede (SSID)", "Sinal", "Padrão", "Frequência", "Taxa recepção", "Taxa envio"):
            self.wifi.add(k)
        R.addWidget(self.wifi)
        tg = QGroupBox("Tráfego")
        tl = QVBoxLayout(tg)
        tl.setContentsMargins(10, 18, 10, 10)
        self.net_lbl = QLabel("—")
        tl.addWidget(self.net_lbl)
        self.net_spark = Sparkline("ram")
        self.net_spark.color2 = "write"
        self.net_spark.setMinimumHeight(110)
        tl.addWidget(self.net_spark)
        lg = themed(QLabel(), lambda w: w.setText(f"<span style='color:{T.ram}'>━ recebendo</span> &nbsp; <span style='color:{T.write}'>╌ enviando</span> (KB/s)"))
        lg.setObjectName("muted")
        tl.addWidget(lg)
        self.net_tot = QLabel("")
        self.net_tot.setObjectName("muted")
        tl.addWidget(self.net_tot)
        R.addWidget(tg)
        R.addStretch()
        L.addWidget(scroll(right), 1)
        self.net_list.currentRowChanged.connect(lambda _: self._render_net(reset=True))
        self.sub.addTab(w, "Rede")

    def set_net(self, nets, glob_):
        self.nets = nets
        self.net_glob = glob_ or {}
        labels = [f"{n['name']}  ·  {n['type']}\n{'●' if n['state'] == 'Conectado' else '○'} {n['state']}"
                  + (f" · {n['ipv4'][0].split('/')[0]}" if n["ipv4"] else "") for n in nets]
        if [self.net_list.item(i).text() for i in range(self.net_list.count())] != labels:
            cur = max(self.net_list.currentRow(), 0)
            self.net_list.blockSignals(True)
            self.net_list.clear()
            for t in labels:
                self.net_list.addItem(t)
            self.net_list.setCurrentRow(min(cur, len(labels) - 1))
            self.net_list.blockSignals(False)
        self._render_net()

    def set_net_counters(self, ctr):
        now = time.monotonic()
        rates = {}
        if self._last_net:
            t0, c0 = self._last_net
            dt = max(now - t0, 1e-3)
            for k, v in ctr.items():
                if k in c0:
                    rates[k] = (max(v[0] - c0[k][0], 0) / dt, max(v[1] - c0[k][1], 0) / dt)
        self._last_net = (now, ctr)
        for k, r in rates.items():
            self.net_hist.setdefault(k, deque(maxlen=120)).append(r)
        self.ctr = ctr
        i = self.net_list.currentRow()
        if 0 <= i < len(self.nets):
            n = self.nets[i]["name"]
            r = rates.get(n)
            if r:
                self.net_spark.add(r[0] / 1e3, r[1] / 1e3)
                self.net_lbl.setText(f"↓ <b>{rate_text(r[0])}</b> &nbsp;&nbsp; ↑ <b>{rate_text(r[1])}</b>")
            c = ctr.get(n)
            if c:
                self.net_tot.setText(f"Desde o boot: recebido {human_bytes(c[0])} · enviado {human_bytes(c[1])}"
                                     f" · erros {c[2]} · descartados {c[3]}")

    def _render_net(self, reset=False):
        i = self.net_list.currentRow()
        if not (0 <= i < len(self.nets)):
            return
        n = self.nets[i]
        sp = n["speed"]
        self.net_info.set_many({
            "Nome": n["name"], "Tipo": n["type"], "Estado": n["state"],
            "Velocidade do link": (f"{sp / 1000:g} Gb/s" if sp and sp >= 1000 else f"{sp} Mb/s") + (f" · {n['duplex']}" if n["duplex"] else "") if sp else None,
            "Adaptador": n["hw"], "Barramento": n["bus"], "Driver": n["driver"], "Versão do driver": n["driver_version"],
            "MAC": n["mac"], "MTU": n["mtu"], "IPv4": ", ".join(n["ipv4"]) or None, "Gateway": n["gateway"],
            "IPv6": ", ".join(n["ipv6"][:2]) or None, "DNS": self.net_glob.get("dns"),
            "Hostname": self.net_glob.get("hostname"),
        })
        self.net_info.set("Estado", n["state"], "#4fd18b" if n["state"] == "Conectado" else T.muted)
        wf = n.get("wifi")
        self.wifi.setVisible(bool(wf is not None))
        if wf is not None:
            sig = wf.get("signal")
            q = None
            if sig is not None:
                q = max(0, min(100, 2 * (sig + 100)))
                txt = f"{sig:.0f} dBm ({q:.0f} %)"
            else:
                txt = wf.get("nm_signal")
            col = None if q is None else ("#4fd18b" if q >= 60 else "#f5c542" if q >= 35 else "#ff5d5d")
            self.wifi.set("Sinal", txt, col)
            self.wifi.set_many({"Rede (SSID)": wf.get("ssid") or "(instale 'iw' para ver)", "Padrão": wf.get("standard"),
                                "Frequência": wf.get("freq"), "Taxa recepção": wf.get("rx_rate"),
                                "Taxa envio": wf.get("tx_rate")})
        if reset:
            self.net_spark.clear()
            for r in self.net_hist.get(n["name"], []):
                self.net_spark.add(r[0] / 1e3, r[1] / 1e3)

    # ---------------- Bateria ----------------
    def _build_bat(self):
        w = QWidget()
        self.bat_lay = QVBoxLayout(w)
        self.bat_lay.setContentsMargins(0, 8, 0, 0)
        self.bat_lay.setSpacing(10)
        self.ac = QLabel("")
        self.ac.setObjectName("section")
        self.bat_lay.addWidget(self.ac)
        self.bat_groups = []
        self.bat_none = QLabel("Nenhuma bateria encontrada (computador de mesa ou bateria não exposta pelo firmware).")
        self.bat_none.setObjectName("muted")
        self.bat_lay.addWidget(self.bat_none)
        self.bat_lay.addStretch()
        self.sub.addTab(scroll(w), "Bateria")

    def set_batteries(self, bats, ac):
        self.ac.setText("🔌 Na tomada" if ac else ("🔋 Na bateria" if ac is False else ""))
        self.bat_none.setVisible(not bats)
        while len(self.bat_groups) < len(bats):
            g = InfoGroup("Bateria", cols=2)
            for k in ("Fabricante", "Modelo", "Tecnologia", "Nº de série", "Estado", "Carga", "Energia atual",
                      "Capacidade atual (cheia)", "Capacidade de projeto", "Saúde", "Ciclos", "Desgaste",
                      "Potência", "Tensão", "Tempo restante", "Limite de carga"):
                g.add(k)
            b = bar()
            g.grid.addWidget(b, 100, 0, 1, 4)
            g.bar = b
            self.bat_lay.insertWidget(1 + len(self.bat_groups), g)
            self.bat_groups.append(g)
        for g, b in zip(self.bat_groups, bats):
            g.setTitle(f"Bateria {b['name']}")
            u = b["unit"]
            hp = b["health"]
            hcol = "#4fd18b" if hp and hp >= 80 else "#f5c542" if hp and hp >= 60 else "#ff5d5d"
            g.set_many({
                "Fabricante": b["manufacturer"], "Modelo": b["model"], "Tecnologia": b["technology"],
                "Nº de série": b["serial"], "Estado": b["status"], "Carga": fmt(b["capacity"], "%"),
                "Energia atual": f"{b['now']:.2f} {u}" if b["now"] is not None else None,
                "Capacidade atual (cheia)": f"{b['full']:.2f} {u}" if b["full"] else None,
                "Capacidade de projeto": f"{b['design']:.2f} {u}" if b["design"] else None,
                "Ciclos": b["cycles"] if b["cycles"] else "— (não informado)",
                "Desgaste": f"{100 - hp:.1f} %" if hp else None,
                "Potência": (f"{b['watts']:.1f} W" + (" (carregando)" if b["raw_status"] == "Charging" else "")) if b["watts"] else None,
                "Tensão": fmt(b["voltage"], "V", 2),
                "Tempo restante": hw.fmt_uptime(b["time_left"]) + (" até carregar" if b["raw_status"] == "Charging" else " de uso") if b["time_left"] else None,
                "Limite de carga": f"{b['threshold_end']} %" if b["threshold_end"] else None,
            })
            g.set("Saúde", f"{hp:.1f} % da capacidade original" if hp else None, hcol if hp else None)
            cap = b["capacity"] or 0
            g.bar.setValue(cap * 10)
            g.bar.setFormat(f"{cap} %")
            col = "#4fd18b" if cap > 40 else "#f5c542" if cap > 15 else "#ff5d5d"
            g.bar.set_colors(col)

    # ---------------- Ventoinhas ----------------
    def _build_fans(self):
        w = QWidget()
        L = QVBoxLayout(w)
        L.setContentsMargins(0, 8, 0, 0)
        L.setSpacing(8)
        tip = QLabel("Dê dois cliques na coluna “Nome” para renomear (ex.: “CPU”, “Gabinete frontal”). "
                     "Os nomes ficam salvos e também aparecem na Visão geral.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        L.addWidget(tip)
        self.fan_tbl = QTableWidget(0, 8)
        self.fan_tbl.setHorizontalHeaderLabels(["Nome", "Sensor", "Chip", "RPM", "Mín", "Máx", "PWM", "Modo"])
        self.fan_tbl.verticalHeader().setVisible(False)
        fh = self.fan_tbl.horizontalHeader()
        fh.setSectionResizeMode(QHeaderView.ResizeToContents)
        fh.setSectionResizeMode(0, QHeaderView.Stretch)
        fh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.fan_tbl.setAlternatingRowColors(True)
        L.addWidget(self.fan_tbl)
        self.fan_none = QLabel("Nenhuma ventoinha com sensor encontrada. Em desktops, o driver do Super I/O "
                               "(nct6775/it87) precisa estar carregado — veja “Diagnóstico”.")
        self.fan_none.setObjectName("muted")
        self.fan_none.setWordWrap(True)
        L.addWidget(self.fan_none)
        self.fan_tbl.itemChanged.connect(self._fan_renamed)
        self.fan_keys = []
        self.sub.addTab(w, "Ventoinhas")

    def _fan_renamed(self, it):
        if it.column() != 0 or self._filling:
            return
        r = it.row()
        if r < len(self.fan_keys):
            name = it.text().strip()
            if name:
                self.fan_names[self.fan_keys[r]] = name
            else:
                self.fan_names.pop(self.fan_keys[r], None)
            devices.save_fan_names(self.fan_names)

    _filling = False

    def set_fans(self, fans):
        self.fan_none.setVisible(not fans)
        self._filling = True
        if self.fan_tbl.rowCount() != len(fans):
            self.fan_tbl.setRowCount(len(fans))
        self.fan_keys = [f["key"] for f in fans]
        for r, f in enumerate(fans):
            mn, mx = self.fan_stats.get(f["key"], (f["rpm"], f["rpm"]))
            mn, mx = min(mn, f["rpm"]), max(mx, f["rpm"])
            self.fan_stats[f["key"]] = (mn, mx)
            default = "Placa de vídeo" if f["kind"] == "gpu" else ""
            vals = [self.fan_names.get(f["key"], default), f["label"], f"{f['chip']} ({f['chip_name']})",
                    f"{f['rpm']:.0f}" if f["rpm"] else "0 (parada/desconectada)", f"{mn:.0f}", f"{mx:.0f}",
                    f"{f['pwm']} %" if f["pwm"] is not None else "—", f["mode"] or "—"]
            for c, v in enumerate(vals):
                it = self.fan_tbl.item(r, c)
                if it is None:
                    it = QTableWidgetItem()
                    if c != 0:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    else:
                        it.setForeground(QBrush(QColor(T.cpu)))
                    self.fan_tbl.setItem(r, c, it)
                if c == 0 and self.fan_tbl.state() == QAbstractItemView.EditingState:
                    continue
                if it.text() != str(v):
                    it.setText(str(v))
        self._filling = False

    def tree_names(self, fans):
        return {f["skey"]: self.fan_names[f["key"]] for f in fans if f["key"] in self.fan_names}

    # ---------------- USB ----------------
    def _build_usb(self):
        w = QWidget()
        L = QVBoxLayout(w)
        L.setContentsMargins(0, 8, 0, 0)
        self.usb_tree = QTreeWidget()
        self.usb_tree.setHeaderLabels(["Dispositivo", "ID", "Classe", "Velocidade", "Driver", "Energia", "Porta"])
        self.usb_tree.setAlternatingRowColors(True)
        h = self.usb_tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 7):
            h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        L.addWidget(self.usb_tree)
        self.usb_none = QLabel("Nenhum dispositivo USB encontrado.")
        self.usb_none.setObjectName("muted")
        L.addWidget(self.usb_none)
        self._usb_sig = None
        self.sub.addTab(w, "USB")

    def set_usb(self, devs):
        sig = [(d["path"], d["name"]) for d in devs]
        self.usb_none.setVisible(not devs)
        if sig == self._usb_sig:
            return
        self._usb_sig = sig
        self.usb_tree.clear()
        roots = {}
        for d in devs:
            if d["root"]:
                it = QTreeWidgetItem([f"Barramento {d['bus']} — {d['speed']}", d["id"], "Hub raiz", "", d["driver"] or "", "", ""])
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
                it.setForeground(0, QBrush(QColor(T.ram)))
                self.usb_tree.addTopLevelItem(it)
                it.setExpanded(True)
                roots[d["bus"]] = it
        for d in devs:
            if d["root"]:
                continue
            parent = roots.get(d["bus"])
            it = QTreeWidgetItem([d["name"], d["id"], d["class"], d["speed"] or "", d["driver"] or "",
                                  d["power"] or "", d["port"]])
            if d["db_name"] and d["db_name"] != d["name"]:
                it.setToolTip(0, d["db_name"])
            (parent.addChild(it) if parent else self.usb_tree.addTopLevelItem(it))

    # ---------------- Áudio ----------------
    def _build_audio(self):
        w = QWidget()
        L = QVBoxLayout(w)
        L.setContentsMargins(0, 8, 0, 0)
        L.setSpacing(10)
        self.aud = InfoGroup("Sistema de áudio")
        for k in ("Servidor de som", "Saída padrão", "Entrada padrão"):
            self.aud.add(k)
        L.addWidget(self.aud)
        self.aud_tbl = QTableWidget(0, 5)
        self.aud_tbl.setHorizontalHeaderLabels(["#", "Placa", "Controlador", "Codec", "Driver"])
        self.aud_tbl.verticalHeader().setVisible(False)
        self.aud_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.aud_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.aud_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.aud_tbl.setFixedHeight(200)
        L.addWidget(self.aud_tbl)
        pg = QGroupBox("Entradas e saídas (PCM)")
        pl = QVBoxLayout(pg)
        pl.setContentsMargins(10, 18, 10, 10)
        self.aud_pcm = QLabel("—")
        self.aud_pcm.setWordWrap(True)
        self.aud_pcm.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pl.addWidget(self.aud_pcm)
        L.addWidget(pg)
        L.addStretch()
        self.sub.addTab(scroll(w), "Áudio")

    def set_audio(self, a):
        if not a:
            return
        self.aud.set_many({"Servidor de som": a.get("server") or "— (pactl não encontrado)",
                           "Saída padrão": a.get("default_sink"), "Entrada padrão": a.get("default_source")})
        cards = a.get("cards") or []
        self.aud_tbl.setRowCount(len(cards))
        lines = []
        for r, c in enumerate(cards):
            for col, v in enumerate([c["index"], c["name"], c["hw"] or "—", ", ".join(c["codecs"]) or "—", c["driver"]]):
                self.aud_tbl.setItem(r, col, QTableWidgetItem(str(v)))
            if c["pcms"]:
                lines.append(f"<b>{c['id']}</b>: " + " · ".join(c["pcms"]))
        self.aud_pcm.setText("<br>".join(lines) or "Nenhuma placa de som encontrada.")
