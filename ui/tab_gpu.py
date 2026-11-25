"""Aba GPU (equivalente ao GPU-Z) com sensores mín/máx/média."""
from __future__ import annotations

import platform
import re
import time
from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from core.hwinfo import human_bytes
from ui.common import InfoGroup, Sparkline, fmt, scroll, temp_color
from ui.theme import T, themed


class StatTable(QWidget):
    """Tabela de sensores com Atual / Mínimo / Máximo / Média (como o GPU-Z)."""

    def __init__(self, keys):
        super().__init__()
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(6)
        head = QHBoxLayout()
        self.since = QLabel("")
        self.since.setObjectName("muted")
        head.addWidget(self.since)
        head.addStretch()
        self.reset_btn = QPushButton("Zerar mín/máx/média")
        head.addWidget(self.reset_btn)
        L.addLayout(head)
        self.tbl = QTableWidget(len(keys), 5)
        self.tbl.setHorizontalHeaderLabels(["Sensor", "Atual", "Mínimo", "Máximo", "Média"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl.setAlternatingRowColors(True)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.keys = list(keys)
        for r, k in enumerate(self.keys):
            self.tbl.setItem(r, 0, QTableWidgetItem(k))
            for c in range(1, 5):
                it = QTableWidgetItem("—")
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl.setItem(r, c, it)
            self.tbl.setRowHeight(r, 26)
        L.addWidget(self.tbl)
        self.stats = {}   # (grupo, chave) -> [min, max, soma, n, casas, unidade]
        self.group = None
        self.count = False
        self.t0 = {}
        self.reset_btn.clicked.connect(self.reset)

    def set_group(self, g):
        if g != self.group:
            for r in range(len(self.keys)):
                for c in (2, 3, 4):
                    self.tbl.item(r, c).setText("—")
        self.group = g
        self.t0.setdefault(g, time.time())
        self._since()

    def reset(self):
        for k in [k for k in self.stats if k[0] == self.group]:
            del self.stats[k]
        self.t0[self.group] = time.time()
        for r in range(len(self.keys)):
            for c in (2, 3, 4):
                self.tbl.item(r, c).setText("—")
        self._since()

    def _since(self):
        t = self.t0.get(self.group)
        if t:
            self.since.setText("Estatísticas desde " + time.strftime("%H:%M:%S", time.localtime(t)))

    @staticmethod
    def _parse(txt):
        m = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*([^\s/(·]*)", txt or "")
        if not m:
            return None, None, 0
        num = m.group(1)
        return float(num), m.group(2), (len(num.split(".")[1]) if "." in num else 0)

    def set(self, key, value, color=None, num=None, unit=None, nd=None):
        if key not in self.keys:
            return
        r = self.keys.index(key)
        txt = "—" if value in (None, "") else str(value)
        cur = self.tbl.item(r, 1)
        if cur.text() != txt:
            cur.setText(txt)
        cur.setForeground(QBrush(QColor(color or T.text)))
        v, u, d = self._parse(txt) if num is None else (num, unit or "", nd or 0)
        if v is None:
            return
        k = (self.group, key)
        st = self.stats.get(k)
        if self.count:
            if st is None or st[5] != u:
                st = [v, v, 0.0, 0, d, u]
            st[0], st[1] = min(st[0], v), max(st[1], v)
            st[2] += v
            st[3] += 1
            st[4] = max(st[4], d)
            self.stats[k] = st
        if st and st[3]:
            f = lambda x: f"{x:.{st[4]}f} {st[5]}".strip()
            for c, val in ((2, st[0]), (3, st[1]), (4, st[2] / st[3])):
                self.tbl.item(r, c).setText(f(val))
            if key.startswith("Temperatura") or key == "Hot spot":
                self.tbl.item(r, 3).setForeground(QBrush(QColor(temp_color(st[1]))))


class GpuTab(QWidget):
    """GPU-Z: Placa de vídeo / Sensores / Avançado."""

    def __init__(self):
        super().__init__()
        L = QVBoxLayout(self)
        L.setContentsMargins(14, 14, 14, 14)
        L.setSpacing(10)
        top = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setMinimumWidth(360)
        top.addWidget(QLabel("GPU:"))
        top.addWidget(self.combo)
        top.addStretch()
        L.addLayout(top)
        self.header = QLabel("—")
        self.header.setObjectName("hero")
        L.addWidget(self.header)
        self.sub = QTabWidget()
        self.sub.setObjectName("subtabs")
        L.addWidget(self.sub, 1)

        # --- Placa de vídeo (GPU-Z principal)
        card = QWidget()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 8, 0, 0)
        cl.setSpacing(10)
        self.card = InfoGroup("Placa de vídeo", cols=2)
        for k in ("Nome", "GPU (codinome)", "Revisão", "Tecnologia", "Área do die", "Lançamento", "Transistores",
                  "Arquitetura", "Versão da BIOS", "Subfornecedor", "ID do dispositivo", "ROPs / TMUs",
                  "Interface de barramento", "Shaders", "Unidades de computação", "DirectX",
                  "Pixel fillrate", "Texture fillrate", "Desempenho FP32", "Tipo de memória",
                  "Largura do barramento", "Tamanho da memória", "Largura de banda", "Taxa de memória",
                  "Driver", "Versão do driver", "Clock GPU (atual)", "Clock memória (atual)", "Boost / máx.",
                  "Memória máx.", "Clock padrão", "Memória padrão", "Multi-GPU", "Resizable BAR",
                  "Tipo", "Saída primária"):
            self.card.add(k)
        cl.addWidget(self.card)
        self.comp = InfoGroup("Computação e tecnologias", cols=2)
        for k in ("OpenCL", "CUDA", "ROCm/HIP", "Vulkan", "Ray tracing", "OpenGL", "Driver Vulkan",
                  "Decodificação de vídeo", "Codificação de vídeo", "Driver VA-API"):
            self.comp.add(k)
        cl.addWidget(self.comp)
        self.dbnote = QLabel("")
        self.dbnote.setObjectName("muted")
        self.dbnote.setWordWrap(True)
        cl.addWidget(self.dbnote)
        cl.addStretch()
        self.sub.addTab(scroll(card), "Placa de vídeo")

        # --- Sensores
        sens = QWidget()
        sl = QHBoxLayout(sens)
        sl.setContentsMargins(0, 8, 0, 0)
        sl.setSpacing(12)
        self.sens = StatTable(("Clock GPU", "Clock memória", "Temperatura GPU", "Hot spot", "Temperatura memória",
                               "Ventoinha (%)", "Ventoinha (RPM)", "Carga GPU", "Carga controlador mem.",
                               "Carga vídeo (enc/dec)", "Memória usada (dedicada)", "Memória usada (dinâmica)",
                               "Consumo da placa", "Tensão GPU (VDDC)", "Limitação (PerfCap)", "P-state",
                               "Temperatura CPU", "Memória do sistema usada"))
        sl.addWidget(self.sens, 3)
        gb = QGroupBox("Histórico")
        gl = QVBoxLayout(gb)
        gl.setContentsMargins(10, 18, 10, 10)
        self.spark = Sparkline("gpu", fixed_max=100)
        self.spark.color2 = "#ff5d5d"
        gl.addWidget(self.spark, 1)
        lg = themed(QLabel(), lambda w: w.setText(f"<span style='color:{T.gpu}'>━ uso %</span> &nbsp; <span style='color:#ff5d5d'>╌ temperatura °C</span>"))
        lg.setObjectName("muted")
        gl.addWidget(lg)
        self.spark_p = Sparkline("#f5c542")
        gl.addWidget(self.spark_p, 1)
        lp = QLabel("<span style='color:#f5c542'>━ consumo W</span>")
        lp.setObjectName("muted")
        gl.addWidget(lp)
        sl.addWidget(gb, 2)
        self.sub.addTab(sens, "Sensores")

        # --- Avançado
        adv = QWidget()
        al = QVBoxLayout(adv)
        al.setContentsMargins(0, 8, 0, 0)
        al.setSpacing(10)
        self.limits = InfoGroup("Limites", cols=2)
        for k in ("Limite de energia atual", "Limite padrão", "Limite mínimo", "Limite máximo",
                  "Limites de temperatura", "Overdrive", "Nível de desempenho", "Data da VBIOS",
                  "Compute capability", "Memória GTT"):
            self.limits.add(k)
        al.addWidget(self.limits)
        mg = QGroupBox("Monitores conectados")
        ml = QVBoxLayout(mg)
        ml.setContentsMargins(8, 18, 8, 8)
        self.mons = QTableWidget(0, 5)
        self.mons.setHorizontalHeaderLabels(["Conector", "Monitor", "Fabricante", "Modo nativo", "Tamanho"])
        self.mons.verticalHeader().setVisible(False)
        self.mons.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.mons.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.mons.setFixedHeight(150)
        ml.addWidget(self.mons)
        al.addWidget(mg)
        self.api = InfoGroup("Renderizador")
        for k in ("Renderizador OpenGL", "Fornecedor OpenGL", "Versão Mesa"):
            self.api.add(k)
        al.addWidget(self.api)
        al.addStretch()
        self.sub.addTab(scroll(adv), "Avançado")

        self.empty = QLabel("Nenhuma GPU encontrada em /sys/class/drm.")
        self.empty.setObjectName("muted")
        self.empty.hide()
        L.addWidget(self.empty)
        self.gpus = []
        self.gl = {}
        self.extra = {}
        self.hist = {}
        self.cpu_temp = None
        self.mem = {}
        self.combo.currentIndexChanged.connect(self._changed)

    def _changed(self, _):
        self.spark.clear()
        self.spark_p.clear()
        g = self._cur()
        if g:
            for u, t, p in self.hist.get(g["pci"], []):
                self.spark.add(u, t)
                self.spark_p.add(p)
            self.sens.set_group(g["pci"])
            self.sens.count = False
            self._render(g)

    def _cur(self):
        i = self.combo.currentIndex()
        return self.gpus[i] if 0 <= i < len(self.gpus) else None

    def set_gl(self, gl, extra):
        self.gl = gl or {}
        self.extra = extra or {}
        g = self._cur()
        if g:
            self._render(g)

    def set_dynamic(self, gpus, cpu_temp=None, mem=None):
        self.gpus = gpus
        self.cpu_temp, self.mem = cpu_temp, mem or {}
        self.empty.setVisible(not gpus)
        labels = [f"{g['name']}  [{g['pci']}]" for g in gpus]
        if [self.combo.itemText(i) for i in range(self.combo.count())] != labels:
            self.combo.blockSignals(True)
            cur = self.combo.currentIndex()
            self.combo.clear()
            self.combo.addItems(labels)
            self.combo.setCurrentIndex(max(0, min(cur, len(labels) - 1)))
            self.combo.blockSignals(False)
        for g in gpus:
            h = self.hist.setdefault(g["pci"], deque(maxlen=120))
            h.append((g["busy"], g["temp"], g["power"]))
        g = self._cur()
        if g:
            self.spark.add(g["busy"], g["temp"])
            self.spark_p.add(g["power"])
            self.sens.set_group(g["pci"])
            self.sens.count = True
            self._render(g)

    def _render(self, g):
        x = self.extra.get(g["pci"], {})
        spec = g.get("spec") or {}
        self.header.setText(x.get("marketing") or g["name"])
        vt = g.get("vram_total")
        vram_txt = human_bytes(vt) if vt else "—"
        rops = x.get("rops")
        tm = x.get("tmus")
        sh = x.get("shaders")
        drv = g["driver"]
        if x.get("mesa"):
            drv_ver = f"Mesa {x['mesa']} · kernel {platform.release()}"
        else:
            drv_ver = g["driver_version"] or f"kernel {platform.release()}"
        self.card.set_many({
            "Nome": x.get("marketing") or g["name"], "GPU (codinome)": g.get("codename"), "Revisão": g["revision"],
            "Tecnologia": spec.get("tech"), "Área do die": f"{spec['die']} mm²" if spec.get("die") else None,
            "Lançamento": spec.get("release"),
            "Transistores": f"{spec['transistors'] / 1000:.1f} bilhões".replace(".", ",") if spec.get("transistors") else None,
            "Arquitetura": spec.get("arch"), "Versão da BIOS": g["vbios"],
            "Subfornecedor": g["board_vendor"], "ID do dispositivo": g["ids"],
            "ROPs / TMUs": f"{rops or '?'} / {tm or '?'}" + (f"  {x['rops_note']}" if x.get("rops_note") else "") if (rops or tm) else None,
            "Interface de barramento": f"{g['link_max'].split(' (')[0]} x{g['width_max']} @ "
                                       f"x{g['width_cur']} {g['link_cur'].split(' (')[0]}" if g.get("link_max") and g.get("link_cur") else None,
            "Shaders": (f"{sh} unificados" + ("" if x.get("shaders_exact") else "  (chip completo)")) if sh else None,
            "Unidades de computação": x.get("cu"),
            "DirectX": "N/A no Linux (DXVK/VKD3D usam Vulkan)",
            "Pixel fillrate": f"{x['pixel_fill']:.1f} GPixel/s" if x.get("pixel_fill") else None,
            "Texture fillrate": f"{x['texture_fill']:.1f} GTexel/s" if x.get("texture_fill") else None,
            "Desempenho FP32": f"{x['tflops']:.2f} TFLOPS" if x.get("tflops") else None,
            "Tipo de memória": x.get("mem_type") or spec.get("mem_type") or (g["vram_vendor"] or None),
            "Largura do barramento": f"{spec['bus']} bits" + (" (chip)" if spec.get("bus") else "") if spec.get("bus") else None,
            "Tamanho da memória": vram_txt, "Largura de banda": f"≈ {x['bandwidth']:.1f} GB/s" if x.get("bandwidth") else None,
            "Taxa de memória": f"{x['mem_rate'] / 1000:.1f} Gbps" if x.get("mem_rate") else None,
            "Driver": drv, "Versão do driver": drv_ver,
            "Clock GPU (atual)": fmt(g["sclk"], "MHz"), "Clock memória (atual)": fmt(g["mclk"], "MHz"),
            "Boost / máx.": fmt(g["sclk_max"], "MHz"), "Memória máx.": fmt(g["mclk_max"], "MHz"),
            "Clock padrão": fmt(g.get("default_clock"), "MHz") if g.get("default_clock") else fmt(g["sclk_max"], "MHz"),
            "Memória padrão": fmt(g.get("default_mem"), "MHz") if g.get("default_mem") else fmt(g["mclk_max"], "MHz"),
            "Multi-GPU": f"{len(self.gpus)} GPU(s) no sistema" if len(self.gpus) > 1 else "Desativado",
            "Resizable BAR": g.get("rebar"),
            "Tipo": "Integrada" if g["integrated"] else "Dedicada",
            "Saída primária": "Sim" if g["boot_vga"] else "Não",
        })
        yn = lambda b: "✔ Sim" if b else "✖ Não"
        va = x.get("vaapi") or {}
        self.comp.set_many({
            "OpenCL": x.get("opencl") or "✖ (instale clinfo / runtime OpenCL)",
            "CUDA": f"✔ Sim (compute {g.get('compute_cap')})" if g.get("cuda") else "✖ Não",
            "ROCm/HIP": yn(x.get("rocm")) if g["vendor"] == "AMD" else "N/A",
            "Vulkan": x.get("vulkan") or "✖ (instale vulkan-tools)",
            "Ray tracing": yn(x.get("raytracing")) if x.get("vulkan") else None,
            "OpenGL": x.get("opengl") or "✖ (instale mesa-utils)",
            "Driver Vulkan": x.get("vk_driver"),
            "Decodificação de vídeo": ", ".join(va.get("decode") or []) or ("✖ (instale vainfo)" if not va else "—"),
            "Codificação de vídeo": ", ".join(va.get("encode") or []) or ("—" if va else None),
            "Driver VA-API": va.get("driver"),
        })
        self.dbnote.setText("Tecnologia, die, transistores, ROPs e largura do barramento vêm da base interna de "
                            "chips (valores do chip completo). Shaders/TMUs são exatos quando o OpenCL informa as "
                            "unidades de computação." if spec else
                            "Chip fora da base interna: campos de especificação não disponíveis.")
        # sensores
        temps = dict((l.lower(), t) for l, t in g["temps"])
        tg = g["temp"]
        hot = temps.get("junction") or temps.get("hotspot")
        tmem = temps.get("mem") or temps.get("memória")
        self.sens.set("Clock GPU", fmt(g["sclk"], "MHz"))
        self.sens.set("Clock memória", fmt(g["mclk"], "MHz"))
        self.sens.set("Temperatura GPU", fmt(tg, "°C", 1), temp_color(tg))
        self.sens.set("Hot spot", fmt(hot, "°C", 1), temp_color(hot))
        self.sens.set("Temperatura memória", fmt(tmem, "°C", 1), temp_color(tmem))
        self.sens.set("Ventoinha (%)", fmt(g["fan_pct"], "%"))
        self.sens.set("Ventoinha (RPM)", fmt(g["fan_rpm"], "RPM"))
        self.sens.set("Carga GPU", fmt(g["busy"], "%"))
        self.sens.set("Carga controlador mem.", fmt(g["mem_busy"], "%"))
        if g.get("enc_load") is not None:
            self.sens.set("Carga vídeo (enc/dec)", f"{g['enc_load']:.0f} % / {g.get('dec_load') or 0:.0f} %")
        vu = g.get("vram_used")
        self.sens.set("Memória usada (dedicada)", f"{vu / 2**20:,.0f} MiB / {vram_txt}".replace(",", ".") if vu is not None else None,
                      num=vu / 2**20 if vu is not None else None, unit="MiB")
        gu = g.get("gtt_used")
        self.sens.set("Memória usada (dinâmica)", f"{gu / 2**20:,.0f} MiB / {human_bytes(g['gtt_total'])}".replace(",", ".") if gu is not None and g.get("gtt_total") else None,
                      num=gu / 2**20 if gu is not None else None, unit="MiB")
        self.sens.set("Consumo da placa", fmt(g["power"], "W", 1))
        self.sens.set("Tensão GPU (VDDC)", fmt(g["voltage"], "V", 3))
        self.sens.set("Limitação (PerfCap)", g.get("perfcap"))
        self.sens.set("P-state", g["pstate"])
        self.sens.set("Temperatura CPU", fmt(self.cpu_temp, "°C", 1), temp_color(self.cpu_temp))
        m = self.mem
        self.sens.set("Memória do sistema usada", f"{m['used'] / 2**20:,.0f} MiB ({m.get('percent', 0):.0f} %)".replace(",", ".") if m else None,
                      num=m["used"] / 2**20 if m else None, unit="MiB")
        self.sens.count = False
        # avançado
        self.limits.set_many({
            "Limite de energia atual": fmt(g["power_cap"], "W"), "Limite padrão": fmt(g.get("power_cap_default"), "W"),
            "Limite mínimo": fmt(g.get("power_cap_min"), "W"), "Limite máximo": fmt(g.get("power_cap_max"), "W"),
            "Limites de temperatura": g.get("temp_limits"), "Overdrive": g.get("overdrive") or "—",
            "Nível de desempenho": g["perf_level"], "Data da VBIOS": g.get("vbios_date"),
            "Compute capability": g.get("compute_cap"),
            "Memória GTT": human_bytes(g["gtt_total"]) if g["gtt_total"] else None,
        })
        mons = g.get("monitors") or []
        if self.mons.rowCount() != len(mons):
            self.mons.setRowCount(len(mons))
        for r, mo in enumerate(mons):
            for c, v in enumerate([mo.get("connector"), mo.get("name"), mo.get("mfg"), mo.get("res"), mo.get("size")]):
                it = self.mons.item(r, c)
                if it is None:
                    it = QTableWidgetItem()
                    self.mons.setItem(r, c, it)
                it.setText(v or "—")
        gl = self.gl
        self.api.set("Renderizador OpenGL", gl.get("renderer") or "instale mesa-utils (glxinfo)")
        self.api.set("Fornecedor OpenGL", gl.get("gl_vendor"))
        self.api.set("Versão Mesa", x.get("mesa"))
