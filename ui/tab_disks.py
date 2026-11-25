"""Discos → Informações e saúde, e o contêiner das sub-abas."""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QListWidget,
                               QListWidgetItem, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from core import health
from core.hwinfo import human_bytes
from ui.common import InfoGroup, Sparkline, bar, need_admin, scroll, temp_color
from ui.theme import T, themed


class DiskTab(QWidget):
    """Informações + saúde (estilo CrystalDiskInfo)."""

    def __init__(self):
        super().__init__()
        L = QHBoxLayout(self)
        L.setContentsMargins(0, 8, 0, 0)
        L.setSpacing(12)
        self.list = QListWidget()
        self.list.setFixedWidth(280)
        self.list.setObjectName("diskList")
        L.addWidget(self.list)
        right = QWidget()
        R = QVBoxLayout(right)
        R.setContentsMargins(0, 0, 0, 0)
        R.setSpacing(10)
        self.header = QLabel("—")
        self.header.setObjectName("hero")
        R.addWidget(self.header)
        self.alert = QLabel("")
        self.alert.setWordWrap(True)
        self.alert.hide()
        R.addWidget(self.alert)

        top = QHBoxLayout()
        top.setSpacing(12)
        hb = QGroupBox("Estado de saúde")
        hl = QVBoxLayout(hb)
        hl.setContentsMargins(12, 18, 12, 10)
        self.badge = QLabel("—")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setMinimumHeight(70)
        hl.addWidget(self.badge)
        self.temp_badge = QLabel("—")
        self.temp_badge.setAlignment(Qt.AlignCenter)
        self.temp_badge.setMinimumHeight(44)
        hl.addWidget(self.temp_badge)
        self.reasons = QLabel("")
        self.reasons.setWordWrap(True)
        self.reasons.setObjectName("muted")
        hl.addWidget(self.reasons)
        hl.addStretch()

        hb.setFixedWidth(240)
        top.addWidget(hb)
        self.info = InfoGroup("Dispositivo", cols=2)
        for k in ("Dispositivo", "Tipo", "Interface", "Capacidade", "Nº de série", "Firmware", "Fabricante",
                  "Rotação", "Horas ligado", "Ciclos de energia", "Total escrito", "Autoteste",
                  "Bloco lógico/físico", "Escalonador", "Tabela de partição", "WWN", "Removível", "Fonte"):
            self.info.add(k)
        top.addWidget(self.info, 1)
        R.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(12)
        pg = QGroupBox("Partições montadas")
        pgl = QVBoxLayout(pg)
        pgl.setContentsMargins(8, 18, 8, 8)
        self.parts = QTableWidget(0, 5)
        self.parts.setHorizontalHeaderLabels(["Partição", "Montagem", "Sistema", "Tamanho", "Uso"])
        self.parts.verticalHeader().setVisible(False)
        self.parts.setEditTriggers(QAbstractItemView.NoEditTriggers)
        ph_ = self.parts.horizontalHeader()
        ph_.setSectionResizeMode(QHeaderView.ResizeToContents)
        ph_.setSectionResizeMode(1, QHeaderView.Stretch)
        ph_.setSectionResizeMode(4, QHeaderView.Fixed)
        self.parts.setColumnWidth(4, 150)
        self.parts.setFixedHeight(150)
        pgl.addWidget(self.parts)
        row.addWidget(pg, 3)
        io = QGroupBox("Atividade")
        il = QVBoxLayout(io)
        il.setContentsMargins(10, 18, 10, 10)
        self.io_lbl = QLabel("Leitura —   Escrita —")
        il.addWidget(self.io_lbl)
        self.spark = Sparkline("disk")
        self.spark.color2 = "write"
        il.addWidget(self.spark, 1)
        lg = themed(QLabel(), lambda w: w.setText(f"<span style='color:{T.disk}'>━ leitura</span> &nbsp; <span style='color:{T.write}'>╌ escrita</span>"))
        lg.setObjectName("muted")
        il.addWidget(lg)
        row.addWidget(io, 2)
        R.addLayout(row)

        sg = QGroupBox("Atributos SMART")
        sgl = QVBoxLayout(sg)
        sgl.setContentsMargins(8, 18, 8, 8)
        self.smart_note = QLabel("Ative o “Modo administrador” no topo para ver todos os atributos (requer smartmontools).")
        self.smart_note.setObjectName("muted")
        self.smart_note.setWordWrap(True)
        sgl.addWidget(self.smart_note)
        self.smart_tbl = QTableWidget(0, 7)
        self.smart_tbl.setHorizontalHeaderLabels(["ID", "Atributo", "Atual", "Pior", "Limite", "Valor bruto", "Estado"])
        self.smart_tbl.verticalHeader().setVisible(False)
        self.smart_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.smart_tbl.setAlternatingRowColors(True)
        self.smart_tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.smart_tbl.hide()
        sgl.addWidget(self.smart_tbl)
        R.addWidget(sg)
        R.addStretch()
        L.addWidget(scroll(right), 1)
        self.disks = []
        self.temps = {}
        self.health = {}
        self.hist = {}
        self.dyn_parts = {}
        self.smart_cache = {}
        self.list.currentRowChanged.connect(self._render)
        self._w = None

    # ---------- dados ----------
    def set_static(self, disks):
        self.disks = disks
        self.list.clear()
        for d in disks:
            self.list.addItem(QListWidgetItem(self._item_text(d)))
        if disks:
            self.list.setCurrentRow(0)

    def _status(self, d):
        full = self.smart_cache.get(d["dev"])
        if full and "error" not in full:
            return full["status"], full.get("life"), full
        h = self.health.get(d["name"])
        if h:
            return h["status"], None, h
        return health.UNKNOWN, None, {}

    def _item_text(self, d):
        st, life, _ = self._status(d)
        t = self.temps.get(d["name"])
        extra = f" · {t:.0f}°C" if t is not None else ""
        lf = f" {life}%" if life is not None else ""
        return f"{d['model']}\n● {st}{lf}{extra}  ·  {human_bytes(d['size'], binary=False)} · {d['name']}"

    def _cur(self):
        i = self.list.currentRow()
        return self.disks[i] if 0 <= i < len(self.disks) else None

    def worst_status(self):
        order = [health.BAD, health.CAUTION, health.GOOD, health.UNKNOWN]
        sts = [self._status(d)[0] for d in self.disks]
        for o in order:
            if o in sts:
                return o
        return None

    def set_dynamic(self, chips, parts, io, disk_health=None):
        self.temps = {}
        for c in chips:
            if c["kind"] == "disk" and c.get("block"):
                ts = [s["value"] for s in c["sensors"] if s["type"] == "temp"]
                if ts and c["block"] not in self.temps:
                    self.temps[c["block"]] = ts[0]
        if disk_health is not None:
            self.health = disk_health
        self.dyn_parts = parts
        for i, d in enumerate(self.disks):
            r, w = io.get(d["name"], (0, 0))
            self.hist.setdefault(d["name"], deque(maxlen=120)).append((r, w))
            it = self.list.item(i)
            if it:
                txt = self._item_text(d)
                if it.text() != txt:
                    it.setText(txt)
                    it.setForeground(QBrush(QColor(health.COLORS.get(self._status(d)[0], T.text))))
        d = self._cur()
        if d:
            r, w = io.get(d["name"], (0, 0))
            self.spark.add(r / 1e6, w / 1e6)
            self.io_lbl.setText(f"Leitura <b>{r / 1e6:.1f} MB/s</b> &nbsp;&nbsp; Escrita <b>{w / 1e6:.1f} MB/s</b>")
            self._health_card(d)
            self._parts(d)

    def _health_card(self, d):
        st, life, src = self._status(d)
        col = health.COLORS.get(st, T.muted)
        c = QColor(col)
        life_txt = f"<br><span style='font-size:15px'>{life} %</span>" if life is not None else ""
        self.badge.setText(f"<span style='font-size:22px;font-weight:800'>{st}</span>{life_txt}")
        self.badge.setStyleSheet(f"background:rgba({c.red()},{c.green()},{c.blue()},45); border:2px solid {col};"
                                 f"border-radius:2px; color:{col};")
        t = self.temps.get(d["name"])
        if t is None:
            t = src.get("temp") if isinstance(src, dict) else None
        tc = QColor(temp_color(t))
        self.temp_badge.setText(f"<span style='font-size:18px;font-weight:700'>{t:.0f} °C</span>" if t is not None else
                                "<span style='font-size:13px'>sem temperatura</span>")
        self.temp_badge.setStyleSheet(f"background:rgba({tc.red()},{tc.green()},{tc.blue()},35); border:1px solid {tc.name()};"
                                      f"border-radius:2px; color:{tc.name()};")
        rs = src.get("reasons") if isinstance(src, dict) else None
        if rs:
            self.reasons.setText("• " + "\n• ".join(rs))
        elif st == health.GOOD:
            self.reasons.setText("Nenhum problema detectado.")
        elif st == health.UNKNOWN:
            self.reasons.setText(need_admin("Sem dados SMART automáticos (instale udisks2 ou ative o “Modo administrador” no topo).",
                                            "Lendo SMART…"))
        else:
            self.reasons.setText("")
        hrs = src.get("hours") if isinstance(src, dict) else None
        self.info.set("Horas ligado", f"{hrs:,} h  ({hrs / 24:.0f} dias)".replace(",", ".") if hrs else None)
        if isinstance(src, dict):
            self.info.set("Autoteste", src.get("selftest"))
            self.info.set("Fonte", "smartctl (completo)" if src.get("source") == "smartctl" else
                          ("UDisks2 (automático)" if src else None))
            if src.get("source") == "smartctl":
                self.info.set("Ciclos de energia", src.get("cycles"))
                self.info.set("Total escrito", src.get("written"))
                if src.get("rotation"):
                    self.info.set("Rotação", src["rotation"])
                if src.get("iface"):
                    self.info.set("Interface", f"{d['interface']} · {src['iface']}")

    def _parts(self, d):
        rows = []
        for p in [d["name"]] + d["partitions"]:
            for m in self.dyn_parts.get(p, []):
                rows.append((p, m))
        if self.parts.rowCount() != len(rows):
            self.parts.setRowCount(len(rows))
        for r, (p, m) in enumerate(rows):
            vals = [p, m["mount"], m["fstype"], human_bytes(m["total"], binary=False) if m["total"] else "—"]
            for c, v in enumerate(vals):
                it = self.parts.item(r, c)
                if it is None:
                    it = QTableWidgetItem()
                    self.parts.setItem(r, c, it)
                it.setText(str(v))
            w = self.parts.cellWidget(r, 4)
            if w is None:
                w = bar(usage=True)
                self.parts.setCellWidget(r, 4, w)
            if m["percent"] is not None:
                w.setValue(int(m["percent"] * 10))
                w.setFormat(f"{human_bytes(m['used'], binary=False)} ({m['percent']:.0f} %)")

    def _render(self, _=None):
        d = self._cur()
        if not d:
            return
        self.header.setText(d["model"])
        self.info.set_many({
            "Dispositivo": d["dev"], "Tipo": d["kind"], "Interface": d["interface"],
            "Capacidade": f"{human_bytes(d['size'], binary=False)}  ({human_bytes(d['size'])})",
            "Nº de série": d["serial"], "Firmware": d["firmware"], "Fabricante": d["vendor"],
            "Rotação": f"{d['rpm']} RPM" if d.get("rpm") else ("—" if d["rotational"] else "N/A (SSD)"),
            "Bloco lógico/físico": f"{d['logical_block']} / {d['physical_block']} bytes",
            "Escalonador": d["scheduler"], "Tabela de partição": (d["ptable"] or "").upper() or None,
            "WWN": d["wwn"], "Removível": "Sim" if d["removable"] else "Não",
            "Ciclos de energia": None, "Total escrito": None,
        })
        self.spark.clear()
        for r, w in self.hist.get(d["name"], []):
            self.spark.add(r / 1e6, w / 1e6)
        self.parts.setRowCount(0)
        self._parts(d)
        self._health_card(d)
        self._show_smart(self.smart_cache.get(d["dev"]))

    def set_smart(self, dev, info):
        self.smart_cache[dev] = info
        d = self._cur()
        if d and d["dev"] == dev:
            self._render()

    def _show_smart(self, info):
        self.alert.hide()
        if not info:
            self.smart_tbl.hide()
            self.smart_note.show()
            self.smart_note.setText(need_admin("Ative o “Modo administrador” no topo para ver todos os atributos (requer smartmontools).",
                                               "Lendo SMART completo…"))
            return
        if "error" in info:
            self.smart_tbl.hide()
            self.smart_note.show()
            self.smart_note.setText(f"Erro: {info['error']}")
            return
        if info.get("history"):
            self.alert.setText("⚠ Piora desde a última leitura: " + "; ".join(info["history"]) +
                               ". Faça backup dos dados importantes.")
            self.alert.setStyleSheet("background:rgba(255,93,93,40); border:1px solid #ff5d5d; color:#ff5d5d;"
                                     "border-radius:2px; padding:8px 12px; font-weight:600;")
            self.alert.show()
        self.smart_note.hide()
        rows = info.get("attrs") or []
        nvme = info.get("kind") == "nvme"
        self.smart_tbl.setColumnCount(2 if nvme else 7)
        self.smart_tbl.setHorizontalHeaderLabels(["Atributo", "Valor"] if nvme else
                                                 ["ID", "Atributo", "Atual", "Pior", "Limite", "Valor bruto", "Estado"])
        self.smart_tbl.horizontalHeader().setSectionResizeMode(0 if nvme else 1, QHeaderView.Stretch)
        self.smart_tbl.setRowCount(len(rows))
        for r, a in enumerate(rows):
            vals = [a["name"], a["value"]] if nvme else [a["id"], a["name"], a["value"], a["worst"], a["thresh"], a["raw"], a["flag"] or "OK"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem("" if v is None else str(v))
                if not nvme and c != 1:
                    it.setTextAlignment(Qt.AlignCenter)
                if a.get("flag") and a["flag"] != "":
                    it.setForeground(QBrush(QColor("#ff5d5d" if a["flag"] in ("falhando",) else "#f5c542")))
                self.smart_tbl.setItem(r, c, it)
        self.smart_tbl.setFixedHeight(40 + 28 * max(len(rows), 1))
        self.smart_tbl.show()


class DisksTab(QWidget):
    """Contêiner: Informações e saúde / Verificar superfície / Teste de velocidade."""

    def __init__(self, info, surface_tab, bench_tab):
        super().__init__()
        L = QVBoxLayout(self)
        L.setContentsMargins(14, 10, 14, 14)
        self.sub = QTabWidget()
        self.sub.setObjectName("subtabs")
        self.sub.addTab(info, "Informações e saúde")
        self.sub.addTab(surface_tab, "Verificar superfície")
        self.sub.addTab(bench_tab, "Teste de velocidade")
        L.addWidget(self.sub)
