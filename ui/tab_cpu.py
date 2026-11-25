"""Abas CPU e Caches (equivalentes ao CPU-Z)."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ui.common import ADMIN, InfoGroup, Sparkline, bar, fmt, need_admin, scroll, temp_color
from ui.theme import T, themed


class CpuTab(QWidget):
    """Equivalente à aba CPU do CPU-Z (+ extras do Linux)."""

    def set_rapl(self, svc):
        self.rapl_status.setText(svc.status_text())
        if svc.active and svc.latest:
            for k, v in svc.latest.items():
                mx = max(self.rapl_max.get(k, 0), v)
                self.rapl_max[k] = mx
                self.rapl.set(k, f"{v:.1f} W   (máx {mx:.1f} W)")
            if svc.package is not None:
                self.rapl_spark.add(svc.package)

    def __init__(self):
        super().__init__()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(12)
        left = QWidget()
        L = QVBoxLayout(left)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(10)
        self.header = QLabel("—")
        self.header.setObjectName("hero")
        self.header.setWordWrap(True)
        L.addWidget(self.header)
        self.proc = InfoGroup("Processador", cols=2)
        for k in ("Nome", "Codinome", "TDP máx.", "Soquete", "Tecnologia", "Tensão do núcleo",
                  "Fabricante", "Microarquitetura", "Família", "Modelo", "Stepping", "Família est.",
                  "Modelo est.", "Revisão", "Microcódigo", "Arquitetura"):
            self.proc.add(k)
        self.proc.add("Especificação", span=2)
        L.addWidget(self.proc)
        ins = QGroupBox("Instruções")
        il = QVBoxLayout(ins)
        il.setContentsMargins(12, 18, 12, 10)
        self.instr = QLabel("—")
        self.instr.setWordWrap(True)
        self.instr.setObjectName("field")
        self.instr.setTextInteractionFlags(Qt.TextSelectableByMouse)
        il.addWidget(self.instr)
        self.vuln = QLabel("")
        self.vuln.setWordWrap(True)
        self.vuln.setObjectName("muted")
        il.addWidget(self.vuln)
        L.addWidget(ins)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.clk = InfoGroup("Clocks (núcleo #0)")
        for k in ("Velocidade do núcleo", "Multiplicador", "Velocidade do barramento", "Clock médio",
                  "Clock máximo atual", "Mínimo / máximo (hw)"):
            self.clk.add(k)
        row.addWidget(self.clk)
        self.cache = InfoGroup("Cache")
        for k in ("L1 Dados", "L1 Instruções", "L2", "L3"):
            self.cache.add(k)
        row.addWidget(self.cache)
        L.addLayout(row)
        self.sel = InfoGroup("Seleção / topologia", cols=3)
        for k in ("Soquetes", "Núcleos", "Threads", "Grupos L3 (CCX)", "Virtualização", "Hipervisor"):
            self.sel.add(k)
        L.addWidget(self.sel)
        self.pw = InfoGroup("Energia e gerenciamento", cols=2)
        for k in ("Temperatura", "Potência do pacote", "Driver", "Governor", "Boost/Turbo",
                  "Preferência energia", "Uso total", "Carga média", "Limite PL1", "Limite PL2", "BogoMIPS"):
            self.pw.add(k)
        L.addWidget(self.pw)
        rg = QGroupBox("Potência (RAPL)")
        rl = QVBoxLayout(rg)
        rl.setContentsMargins(12, 18, 12, 10)
        rrow = QHBoxLayout()
        self.rapl_status = QLabel("—")
        self.rapl_status.setObjectName("muted")
        self.rapl_status.setWordWrap(True)
        rrow.addWidget(self.rapl_status, 1)
        rl.addLayout(rrow)
        self.rapl = InfoGroup("", cols=2)
        self.rapl.setStyleSheet("QGroupBox{border:none; margin-top:0; background:transparent;}")
        rl.addWidget(self.rapl)
        self.rapl_spark = Sparkline("#f5c542")
        self.rapl_spark.setMinimumHeight(70)
        rl.addWidget(self.rapl_spark)
        self.rapl_max = {}
        L.addWidget(rg)
        L.addStretch()
        outer.addWidget(scroll(left), 3)

        right = QWidget()
        R = QVBoxLayout(right)
        R.setContentsMargins(0, 0, 0, 0)
        R.setSpacing(10)
        gb = QGroupBox("Uso e temperatura (últimos 2 min)")
        gl = QVBoxLayout(gb)
        gl.setContentsMargins(10, 18, 10, 10)
        self.spark = Sparkline("cpu", fixed_max=100)
        self.spark.color2 = "#ff5d5d"
        self.spark.setMinimumHeight(110)
        gl.addWidget(self.spark)
        lg = themed(QLabel(), lambda w: w.setText(f"<span style='color:{T.cpu}'>━ uso %</span> &nbsp; "
                    f"<span style='color:#ff5d5d'>╌ temperatura °C</span>"))
        lg.setObjectName("muted")
        gl.addWidget(lg)
        R.addWidget(gb)
        cg = QGroupBox("Por núcleo (thread lógica)")
        cl = QVBoxLayout(cg)
        cl.setContentsMargins(8, 18, 8, 8)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Thread", "Clock", "Uso"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 100)
        cl.addWidget(self.table)
        self.ctemps = QLabel("")
        self.ctemps.setWordWrap(True)
        self.ctemps.setObjectName("muted")
        cl.addWidget(self.ctemps)
        R.addWidget(cg, 1)
        outer.addWidget(right, 2)
        self.bars = []
        self.static = {}

    def set_static(self, c):
        self.static = c
        db = c.get("db") or {}
        self.header.setText(c.get("name", "—"))
        nm = re.sub(r"\(R\)|\(TM\)|CPU|Processor|\d+-Core|@.*", "", c.get("name") or "")
        nm = re.sub(r"^\d+th Gen ", "", nm)
        tdp = c.get("tdp") or {}
        self.proc.set_many({
            "Nome": re.sub(r"\s+", " ", nm).strip(), "Codinome": db.get("codename"),
            "TDP máx.": fmt(tdp.get("long_term"), "W") if tdp.get("long_term") else "— (não exposto)",
            "Soquete": db.get("package"), "Tecnologia": db.get("technology"),
            "Fabricante": c.get("vendor"), "Microarquitetura": c.get("microarch") or db.get("codename"),
            "Revisão": db.get("revision"), "Microcódigo": c.get("microcode"), "Arquitetura": c.get("arch"),
            "Especificação": c.get("name"),
        })
        self.proc.set_many(c.get("cpuid") or {})
        cc = c.get("caches", {})
        for k, lab in (("L1d", "L1 Dados"), ("L1i", "L1 Instruções"), ("L2", "L2"), ("L3", "L3")):
            self.cache.set(lab, cc.get(k))
        hy = c.get("hybrid")
        self.sel.set_many({
            "Soquetes": c.get("sockets"),
            "Núcleos": f"{c.get('cores')}  ({hy['P']}P + {hy['E']}E)" if hy else c.get("cores"),
            "Threads": c.get("threads"), "Grupos L3 (CCX)": c.get("l3_groups"),
            "Virtualização": c.get("virtualization"),
            "Hipervisor": "Sim (máquina virtual)" if c.get("hypervisor") else "Não",
        })
        self.clk.set("Mínimo / máximo (hw)", f"{fmt(c.get('min_mhz'))} / {fmt(c.get('max_mhz'), 'MHz')}")
        self.pw.set_many({
            "Driver": c.get("driver"), "Governor": c.get("governor"), "Boost/Turbo": c.get("boost"),
            "Preferência energia": c.get("epp"), "BogoMIPS": c.get("bogomips"),
            "Limite PL1": fmt(tdp.get("long_term"), "W"), "Limite PL2": fmt(tdp.get("short_term"), "W"),
        })
        self.instr.setText(", ".join(c.get("instructions") or []) or "—")
        self.instr.setToolTip("Todas as flags: " + " ".join(c.get("flags_all") or []))
        if c.get("vulnerable"):
            self.vuln.setText("⚠ Vulnerável (sem mitigação): " + ", ".join(c["vulnerable"]))

    def set_dynamic(self, d, temp, core_temps, vcore=None, power=None):
        freqs, usage = d.get("freqs") or [], d.get("usage") or []
        n = max(len(freqs), len(usage))
        if self.table.rowCount() != n:
            self.table.setRowCount(n)
            self.bars = []
            for i in range(n):
                it = QTableWidgetItem(f"#{i}")
                it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, 0, it)
                it2 = QTableWidgetItem("—")
                it2.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, 1, it2)
                b = bar(usage=True)
                w = QWidget()
                wl = QHBoxLayout(w)
                wl.setContentsMargins(6, 3, 6, 3)
                wl.addWidget(b)
                self.table.setCellWidget(i, 2, w)
                self.bars.append(b)
                self.table.setRowHeight(i, 24)
        for i in range(n):
            f = freqs[i] if i < len(freqs) else None
            self.table.item(i, 1).setText(fmt(f, "MHz"))
            u = usage[i] if i < len(usage) else 0
            self.bars[i].setValue(int(u * 10))
            self.bars[i].setFormat(f"{u:.0f} %")
        avg = sum(freqs) / len(freqs) if freqs else None
        c0 = freqs[0] if freqs else None
        bus = 100.0
        self.clk.set("Velocidade do núcleo", fmt(c0, "MHz", 1))
        mn, mx = self.static.get("min_mhz"), self.static.get("max_mhz")
        if c0:
            rng = f"  ({mn / bus:.0f} – {mx / bus:.0f})" if mn and mx else ""
            self.clk.set("Multiplicador", f"x {c0 / bus:.1f}{rng}")
            self.clk.set("Velocidade do barramento", f"{bus:.1f} MHz (referência)")
        self.clk.set("Clock médio", fmt(avg, "MHz"))
        self.clk.set("Clock máximo atual", fmt(max(freqs) if freqs else None, "MHz"))
        self.proc.set("Tensão do núcleo", fmt(vcore, "V", 3) if vcore else "— (sem sensor)")
        self.pw.set("Temperatura", fmt(temp, "°C", 1), temp_color(temp))
        self.pw.set("Potência do pacote", fmt(power, "W", 1) if power else need_admin(
            "— (requer “Modo administrador”)",
            "aguardando leitura…" if ADMIN["rapl"] else "— (RAPL não disponível neste sistema)"))
        self.pw.set("Uso total", fmt(d.get("total"), "%", 1))
        ld = d.get("load")
        self.pw.set("Carga média", " / ".join(f"{x:.2f}" for x in ld) if ld else None)
        self.spark.add(d.get("total"), temp)
        if core_temps:
            self.ctemps.setText("Temperaturas: " + "  ·  ".join(f"{l}: {t:.0f}°C" for l, t in core_temps))


class CachesTab(QWidget):
    def __init__(self):
        super().__init__()
        L = QVBoxLayout(self)
        L.setContentsMargins(14, 14, 14, 14)
        t = QLabel("Caches do processador")
        t.setObjectName("hero")
        L.addWidget(t)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["Cache", "Tipo", "Tamanho", "Instâncias", "Total",
                                              "Associatividade", "Linha", "Conjuntos", "Compartilhada por"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        L.addWidget(self.table)
        self.note = QLabel("Fonte: /sys/devices/system/cpu/cpu*/cache. Instâncias = quantos blocos "
                           "independentes desse cache existem no chip.")
        self.note.setObjectName("muted")
        L.addWidget(self.note)
        L.addStretch()

    def set_static(self, c):
        rows = c.get("cache_detail") or []
        self.table.setRowCount(len(rows))
        for r, x in enumerate(rows):
            vals = [f"L{x['level']}", x["type"], x["size"], f"{x['count']} ×", x["total"],
                    f"{x['ways']}-way" if x["ways"] else "—", f"{x['line']} bytes" if x["line"] else "—",
                    x["sets"] or "—", f"{x['shared']} thread(s)" if x["shared"] else "—"]
            for col, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, col, it)
        self.table.setFixedHeight(40 + 32 * max(len(rows), 1))
