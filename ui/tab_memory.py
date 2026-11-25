"""Abas Memória e SPD."""
from __future__ import annotations


from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from core import hwinfo as hw
from core.hwinfo import human_bytes
from ui.common import InfoGroup, Sparkline, bar, fmt, scroll, temp_color
from ui.theme import T


class MemoryTab(QWidget):
    """Aba Memory do CPU-Z: geral, timings e uso."""

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        w = QWidget()
        L = QVBoxLayout(w)
        L.setContentsMargins(14, 14, 14, 14)
        L.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(12)
        self.gen = InfoGroup("Geral", cols=2)
        for k in ("Tipo", "Tamanho", "Canais", "Pentes", "Frequência DRAM", "Taxa efetiva",
                  "Frequência Uncore/NB", "Slots", "Capacidade máx.", "ECC", "Temperatura"):
            self.gen.add(k)
        top.addWidget(self.gen, 3)
        self.tim = InfoGroup("Timings")
        for k in ("Frequência DRAM", "CAS# Latency (CL)", "RAS# to CAS# (tRCD)", "RAS# Precharge (tRP)",
                  "Cycle Time (tRAS)", "Bank Cycle Time (tRC)", "Refresh (tRFC)", "Command Rate (CR)", "Origem"):
            self.tim.add(k)
        top.addWidget(self.tim, 2)
        L.addLayout(top)
        mid = QHBoxLayout()
        mid.setSpacing(12)
        self.usage = InfoGroup("Uso", cols=2)
        for k in ("Total", "Em uso", "Disponível", "Cache/Buffers", "Compartilhada", "Swap total", "Swap em uso"):
            self.usage.add(k)
        mid.addWidget(self.usage, 3)
        right = QGroupBox("Ocupação")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 18, 12, 10)
        rl.addWidget(QLabel("RAM"))
        self.ram_bar = bar(usage=True)
        rl.addWidget(self.ram_bar)
        rl.addWidget(QLabel("Swap"))
        self.swap_bar = bar(usage=True)
        rl.addWidget(self.swap_bar)
        self.spark = Sparkline("ram", fixed_max=100)
        rl.addWidget(self.spark, 1)
        mid.addWidget(right, 2)
        L.addLayout(mid)

        head = QHBoxLayout()
        t = QLabel("Módulos (SMBIOS)")
        t.setObjectName("section")
        head.addWidget(t)
        head.addStretch()
        L.addLayout(head)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["Slot", "Tamanho", "Tipo", "Velocidade", "Configurada",
                                              "Fabricante", "Part number", "Rank", "Tensão", "Formato"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(170)
        L.addWidget(self.table)
        self.note = QLabel("")
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        L.addWidget(self.note)
        L.addStretch()
        outer.addWidget(scroll(w))
        self.spd = []
        self.memgen = {}

    def set_static(self, dimms, arr, memgen, spd_mods):
        arr = arr or {}
        self.memgen = memgen or {}
        self.gen.set("Slots", arr.get("slots"))
        mx = arr.get("max")
        self.gen.set("Capacidade máx.", human_bytes(int(mx)) if mx and mx.isdigit() else mx)
        self.gen.set("ECC", arr.get("ecc"))
        self.fill(dimms)
        self.set_spd(spd_mods)

    def set_spd(self, mods):
        self.spd = mods or []
        mg = self.memgen
        typ = mg.get("type") or (self.spd[0]["type"] if self.spd else None)
        self.gen.set_many({
            "Tipo": typ, "Tamanho": human_bytes(mg.get("total")) if mg.get("total") else None,
            "Canais": mg.get("channels"), "Pentes": mg.get("count"),
            "Frequência DRAM": fmt(mg.get("dram_mhz"), "MHz", 1),
            "Taxa efetiva": fmt(mg.get("mts"), "MT/s"),
            "Frequência Uncore/NB": fmt(mg.get("uncore"), "MHz") if mg.get("uncore") else "— (não exposto)",
        })
        # timings: perfil do SPD que corresponde à velocidade configurada
        mts = mg.get("mts")
        row, origin = None, None
        for m in self.spd:
            rows = m.get("timings") or []
            exact = [r for r in rows if mts and abs(r["mts"] - mts) <= 40]
            if exact:
                row = sorted(exact, key=lambda r: not r["label"].startswith(("XMP", "EXPO")))[0]
                origin = f"SPD {m.get('address')} · {row['label']}"
                break
            if rows and not row:
                below = [r for r in rows if not mts or r["mts"] <= mts] or rows
                row = below[-1]
                origin = f"SPD {m.get('address')} · {row['label']} (mais próximo)"
        if row:
            tck = 2000.0 / row["mts"]
            raw = (self.spd[0].get("raw_timings_ns") or {}) if self.spd else {}
            trfc = int(-(-raw["tRFC1"] // tck)) if raw.get("tRFC1") else None
            self.tim.set_many({
                "Frequência DRAM": f"{row['mts'] / 2:.1f} MHz", "CAS# Latency (CL)": f"{row['CL']}",
                "RAS# to CAS# (tRCD)": row["tRCD"], "RAS# Precharge (tRP)": row["tRP"],
                "Cycle Time (tRAS)": row["tRAS"], "Bank Cycle Time (tRC)": row["tRC"],
                "Refresh (tRFC)": trfc, "Command Rate (CR)": "— (lido só do controlador)", "Origem": origin,
            })
        else:
            self.tim.set("Origem", "SPD indisponível — veja a aba SPD", T.muted)

    def fill(self, dimms):
        if not dimms:
            self.table.setRowCount(0)
            self.note.setText("Detalhes dos módulos indisponíveis sem privilégios. Clique em "
                              "“Modo administrador” no topo (requer o pacote dmidecode).")
            return
        self.note.setText("")
        rows = sorted(dimms, key=lambda d: not d["present"])
        self.table.setRowCount(len(rows))
        for r, d in enumerate(rows):
            if d["present"]:
                v = d.get("voltage")
                vals = [d["slot"] + (f" ({d['bank']})" if d.get("bank") else ""), human_bytes(d["size"]),
                        d.get("type"), f"{d['speed']} MT/s" if d.get("speed") else "—",
                        f"{d['configured']} MT/s" if d.get("configured") else "—",
                        d.get("manufacturer"), d.get("part"), d.get("rank"),
                        f"{int(v) / 1000:.2f} V" if v and str(v).isdigit() and int(v) else "—", d.get("form")]
            else:
                vals = [d["slot"], "vazio", "", "", "", "", "", "", "", ""]
            for c, v in enumerate(vals):
                it = QTableWidgetItem("—" if v in (None, "") and d["present"] else str(v or ""))
                if not d["present"]:
                    it.setForeground(QBrush(QColor(T.muted)))
                self.table.setItem(r, c, it)

    def apply_dimms(self, dimms):
        if dimms:
            self.fill(dimms)
            self.memgen = hw.memory_general(dimms)
            self.set_spd(self.spd)

    def set_temps(self, temps):
        if temps:
            hot = max(t for _, t in temps)
            self.gen.set("Temperatura", "  ·  ".join(f"{l}: {t:.0f}°C" for l, t in temps), temp_color(hot))
        else:
            self.gen.set("Temperatura", "sem sensor — veja “Diagnóstico”", T.muted)

    def set_dynamic(self, m):
        if not m:
            return
        self.usage.set_many({
            "Total": human_bytes(m["total"]), "Em uso": f"{human_bytes(m['used'])}  ({m['percent']:.0f} %)",
            "Disponível": human_bytes(m["available"]), "Cache/Buffers": human_bytes(m["cached"]),
            "Compartilhada": human_bytes(m["shared"]), "Swap total": human_bytes(m["swap_total"]),
            "Swap em uso": f"{human_bytes(m['swap_used'])}  ({m['swap_percent']:.0f} %)",
        })
        if not self.memgen.get("total"):
            self.gen.set("Tamanho", human_bytes(m["total"]))
        self.ram_bar.setValue(int(m["percent"] * 10))
        self.ram_bar.setFormat(f"{human_bytes(m['used'])} / {human_bytes(m['total'])}  ({m['percent']:.0f} %)")
        self.swap_bar.setValue(int(m["swap_percent"] * 10))
        self.swap_bar.setFormat(f"{human_bytes(m['swap_used'])} / {human_bytes(m['swap_total'])}")
        self.spark.add(m["percent"])


class SpdTab(QWidget):
    """Aba SPD do CPU-Z."""
    spd_loaded = Signal(object)

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        w = QWidget()
        L = QVBoxLayout(w)
        L.setContentsMargins(14, 14, 14, 14)
        L.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(QLabel("Seleção do slot de memória:"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(260)
        top.addWidget(self.combo)
        top.addStretch()
        L.addLayout(top)
        self.note = QLabel("")
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        L.addWidget(self.note)
        self.info = InfoGroup("Módulo", cols=2)
        for k in ("Tipo", "Tamanho do módulo", "Largura de banda máx.", "Tipo de módulo", "Fabricante do módulo",
                  "Fabricante da DRAM", "Part number", "Nº de série", "Data de fabricação", "Ranks",
                  "Organização", "Largura do barramento", "Perfis estendidos", "Sensor térmico", "ECC",
                  "Revisão SPD", "Latências CAS suportadas"):
            self.info.add(k)
        L.addWidget(self.info)
        tg = QGroupBox("Tabela de timings")
        tl = QVBoxLayout(tg)
        tl.setContentsMargins(8, 18, 8, 8)
        self.table = QTableWidget(8, 0)
        self.table.setVerticalHeaderLabels(["Frequência", "Taxa (MT/s)", "CAS# Latency", "RAS# to CAS#",
                                            "RAS# Precharge", "tRAS", "tRC", "Tensão"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setFixedHeight(300)
        tl.addWidget(self.table)
        L.addWidget(tg)
        L.addStretch()
        outer.addWidget(scroll(w))
        self.mods = []
        self.mem_type = ""
        self.combo.currentIndexChanged.connect(self._render)

    def set_static(self, mods, msg):
        self.mods = mods or []
        self.combo.blockSignals(True)
        self.combo.clear()
        for m in self.mods:
            self.combo.addItem(f"SPD {m.get('address')} — {m.get('type')} {human_bytes(m.get('size')) if m.get('size') else ''}")
        self.combo.blockSignals(False)
        if self.mods:
            self.note.setText("Timings JEDEC calculados a partir do SPD; perfis XMP/EXPO quando presentes.")
            self._render(0)
        else:
            self.note.setText(
                f"SPD não lido: {msg}\n\n"
                "Clique em “Modo administrador” no topo: o app carrega os drivers e procura os pentes "
                "no barramento SMBus automaticamente.\n"
                "Em placas AMD com DDR4, o barramento SPD (i2c-piix4) só é suportado em kernels recentes; "
                "em alguns notebooks o acesso é bloqueado pelo fabricante.")

    def apply_admin(self, mods, msg):
        self.set_static(mods, msg)
        if not mods:
            self.note.setText(f"SPD não lido mesmo com o Modo administrador ativo: {msg}\n\n"
                              "Causas comuns: a placa-mãe/notebook bloqueia o barramento SMBus, ou o kernel não "
                              "suporta o controlador SMBus desta placa. Os dados básicos dos pentes continuam na "
                              "aba Memória (via dmidecode).")
        if mods:
            self.spd_loaded.emit(mods)

    def _render(self, i):
        if not (0 <= i < len(self.mods)):
            return
        m = self.mods[i]
        ext = " / ".join(x for x in (m.get("xmp"), m.get("expo")) if x) or "Nenhum"
        mts = m.get("max_mts")
        self.info.set_many({
            "Tipo": m.get("type"), "Tamanho do módulo": human_bytes(m.get("size")) if m.get("size") else None,
            "Largura de banda máx.": f"{m.get('pc')} ({mts // 2} MHz)" if m.get("pc") and mts else None,
            "Tipo de módulo": m.get("module"), "Fabricante do módulo": m.get("manufacturer"),
            "Fabricante da DRAM": m.get("dram_manufacturer"), "Part number": m.get("part"),
            "Nº de série": m.get("serial"), "Data de fabricação": m.get("date"), "Ranks": m.get("ranks"),
            "Organização": m.get("width"), "Largura do barramento": f"{m.get('bus')} bits" if m.get("bus") else None,
            "Perfis estendidos": ext, "Sensor térmico": m.get("thermal"), "ECC": m.get("ecc"),
            "Revisão SPD": m.get("spd_rev"),
            "Latências CAS suportadas": " ".join(str(c) for c in m.get("cas_supported") or []) or None,
        })
        rows = m.get("timings") or []
        self.table.setColumnCount(len(rows))
        self.table.setHorizontalHeaderLabels([r["label"] for r in rows])
        for c, r in enumerate(rows):
            vals = [f"{r['mts'] / 2:.0f} MHz", r["mts"], r["CL"], r["tRCD"], r["tRP"], r["tRAS"], r["tRC"], r["volt"]]
            for rr, v in enumerate(vals):
                it = QTableWidgetItem("—" if v is None else str(v))
                it.setTextAlignment(Qt.AlignCenter)
                if r["label"].startswith(("XMP", "EXPO")):
                    it.setForeground(QBrush(QColor(T.cpu)))
                self.table.setItem(rr, c, it)
