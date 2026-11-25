"""Aba Estresse: carga de CPU/RAM com monitoramento."""
from __future__ import annotations

import os
import time
from collections import deque

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from core import hwinfo as hw
from core import stress
from ui.kit import ask, set_kind
from ui.common import fmt_duration
from ui.common import ADMIN, InfoGroup, Sparkline, bar, fmt, need_admin, scroll, temp_color
from ui.theme import T, themed


class StressTab(QWidget):
    """Teste de estresse de CPU/RAM com monitoramento e parada térmica."""
    LIMITS = (80, 85, 90, 95, 100, 105, 110, None)
    DUR = [("1 minuto", 60), ("5 minutos", 300), ("10 minutos", 600), ("15 minutos", 900),
           ("30 minutos", 1800), ("1 hora", 3600), ("Sem limite", 0)]

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(QLabel("Carga:"))
        self.mode = QComboBox()
        self.mode.addItems(["CPU — todas as threads", "CPU + RAM (com verificação de erros)",
                            "CPU — uma thread", "Só RAM"])
        top.addWidget(self.mode)
        top.addWidget(QLabel("  Duração:"))
        self.dur = QComboBox()
        self.dur.addItems([d[0] for d in self.DUR])
        self.dur.setCurrentIndex(2)
        top.addWidget(self.dur)
        top.addWidget(QLabel("  Parar se a CPU passar de:"))
        self.limit = QComboBox()
        self.limit.addItems([f"{t} °C" for t in self.LIMITS[:-1]] + ["Sem limite"])
        self.limit.setCurrentIndex(2)
        top.addWidget(self.limit)
        top.addStretch()
        self.btn = QPushButton("▶ Iniciar teste")
        self.btn.setProperty("kind", "green")
        top.addWidget(self.btn)
        outer.addLayout(top)
        info = QLabel("Coloca o processador em 100% de uso para verificar refrigeração e estabilidade. Feche jogos "
                      "e programas pesados antes. O teste para sozinho se a temperatura passar do limite escolhido (exceto em “Sem limite”). "
                      "No modo RAM, 70% da memória livre é preenchida e conferida continuamente.")
        info.setObjectName("muted")
        info.setWordWrap(True)
        outer.addWidget(info)
        self.banner = QLabel("")
        self.banner.setWordWrap(True)
        self.banner.hide()
        outer.addWidget(self.banner)

        body = QHBoxLayout()
        body.setSpacing(12)
        left = QVBoxLayout()
        tg = QGroupBox("Temperatura da CPU (°C)")
        tl = QVBoxLayout(tg)
        tl.setContentsMargins(10, 18, 10, 10)
        self.g_temp = Sparkline("#ff5d5d", maxlen=900, fixed_max=110)
        self.g_temp.setMinimumHeight(150)
        tl.addWidget(self.g_temp)
        left.addWidget(tg, 1)
        cg = QGroupBox("Clock médio (MHz) e uso (%)")
        cl = QVBoxLayout(cg)
        cl.setContentsMargins(10, 18, 10, 10)
        self.g_clk = Sparkline("cpu", maxlen=900)
        self.g_clk.setMinimumHeight(120)
        cl.addWidget(self.g_clk)
        lg = themed(QLabel(), lambda w: w.setText(f"<span style='color:{T.cpu}'>━ clock</span>"))
        lg.setObjectName("muted")
        cl.addWidget(lg)
        left.addWidget(cg, 1)
        pg = QGroupBox("Potência (W)")
        pl = QVBoxLayout(pg)
        pl.setContentsMargins(10, 18, 10, 10)
        self.g_pw = Sparkline("#f5c542", maxlen=900)
        self.g_pw.setMinimumHeight(80)
        pl.addWidget(self.g_pw)
        left.addWidget(pg)
        body.addLayout(left, 3)

        rw = QWidget()
        right = QVBoxLayout(rw)
        right.setContentsMargins(0, 0, 4, 0)
        right.setSpacing(10)
        self.bar = bar()
        self.bar.setFormat("parado")
        right.addWidget(self.bar)
        self.st = InfoGroup("Monitoramento")
        for k in ("Estado", "Decorrido", "Restante", "Temperatura atual", "Temperatura máxima",
                  "Temperatura média", "Uso da CPU", "Clock atual", "Clock no início", "Clock mínimo",
                  "Queda de clock", "Limitação térmica (eventos)", "Potência", "Potência máxima",
                  "Tensão do núcleo", "Ventoinha da CPU", "Operações/s", "RAM testada", "Erros de RAM"):
            self.st.add(k)
        right.addWidget(self.st)
        right.addStretch()
        rs = scroll(rw)
        rs.setMinimumWidth(380)
        body.addWidget(rs, 2)
        outer.addLayout(body, 1)

        self.proc = None
        self.reader = None
        self.running = False
        self.btn.clicked.connect(self.toggle)
        self.limit_c = 90
        self._reset()

    def _reset(self):
        self.t0 = None
        self.temps, self.clocks, self.powers = [], [], []
        self.clk_start = None
        self.ops_last = None
        self.ops_rate = None
        self.mem = (0, 0, 0)
        self.throttle0 = None
        self.stop_reason = None

    def toggle(self):
        if self.running:
            self.finish("Interrompido pelo usuário")
            return
        if self.last_temp is None:
            if not ask(self, "Sem sensor de temperatura",
                       "Não foi encontrado sensor de temperatura da CPU, então o teste NÃO terá parada "
                       "automática por temperatura.\n\nDeseja continuar mesmo assim?",
                       confirm="CONTINUAR", kind="warn", confirm_kind="danger"):
                return
        if self.LIMITS[self.limit.currentIndex()] is None and self.mode.currentIndex() != 3:
            if not ask(self, "Sem limite de temperatura",
                       "O teste NÃO vai parar por temperatura. A própria CPU ainda reduz o clock ou "
                       "desliga o PC se atingir o limite de segurança dela.",
                       confirm="INICIAR MESMO ASSIM", kind="warn", confirm_kind="danger",
                       danger_text="Temperaturas altas por muito tempo não são recomendadas. Acompanhe o teste.",
                       check_text="Entendo o risco e vou acompanhar o teste"):
                return
        m = self.mode.currentIndex()
        n = os.cpu_count() or 1
        threads = {0: n, 1: n, 2: 1, 3: 0}[m]
        mem_mb = 0
        if m in (1, 3) and hw.psutil:
            mem_mb = int(hw.psutil.virtual_memory().available * 0.7 / (1 << 20))
        self._reset()
        span = self.DUR[self.dur.currentIndex()][1] or 1800
        span = max(60, min(span, 3600))
        for g in (self.g_temp, self.g_clk, self.g_pw):
            g.data = deque(maxlen=span)
            g.data2 = deque(maxlen=span)
            g.clear()
        self.limit_c = self.LIMITS[self.limit.currentIndex()]
        self.duration = self.DUR[self.dur.currentIndex()][1]
        self.mem_mode = mem_mb > 0
        self.proc = stress.start(threads, mem_mb)
        self.reader = _StressReader(self.proc)
        self.reader.line.connect(self._line)
        self.reader.start()
        self.running = True
        self.t0 = time.monotonic()
        self.throttle0 = stress.throttle_count(hw.ROOT)
        self.banner.hide()
        self.btn.setText("■ Parar")
        set_kind(self.btn, "cancel")
        for w_ in (self.mode, self.dur, self.limit):
            w_.setEnabled(False)
        self.st.set("Estado", f"Em execução ({threads} threads" + (f", {mem_mb:,} MB de RAM)".replace(",", ".") if mem_mb else ")"), "#ff8a3d")
        self.st.set("RAM testada", "—" if not mem_mb else "alocando…")
        self.st.set("Erros de RAM", "—" if not mem_mb else "0")

    def _line(self, parts):
        if len(parts) >= 5 and parts[0] == "T":
            ops = int(parts[1])
            if self.ops_last is not None:
                self.ops_rate = ops - self.ops_last
            self.ops_last = ops
            self.mem = (int(parts[2]), int(parts[3]), int(parts[4]))

    def feed(self, d):
        """Chamado a cada atualização da janela principal."""
        cpu = d.get("cpu", {}) or {}
        t = d.get("cpu_temp")
        self.last_temp = t
        if not self.running:
            return
        el = time.monotonic() - self.t0
        fr = cpu.get("freqs") or []
        clk = sum(fr) / len(fr) if fr else None
        pw = d.get("cpu_power")
        if t is not None:
            self.temps.append(t)
            self.g_temp.add(t)
        if clk:
            self.clocks.append(clk)
            self.g_clk.add(clk)
            if self.clk_start is None and el >= 3:
                self.clk_start = sum(self.clocks[-3:]) / len(self.clocks[-3:])
        if pw:
            self.powers.append(pw)
            self.g_pw.add(pw)
        if self.duration:
            frac = min(el / self.duration, 1)
            self.bar.setValue(int(frac * 1000))
            self.bar.setFormat(f"{frac * 100:.0f} %")
        else:
            self.bar.setValue(1000)
            self.bar.setFormat("sem limite de tempo")
        self.st.set("Decorrido", fmt_duration(el))
        self.st.set("Restante", fmt_duration(self.duration - el) if self.duration else "—")
        self.st.set("Temperatura atual", fmt(t, "°C", 1), temp_color(t))
        if self.temps:
            mx = max(self.temps)
            self.st.set("Temperatura máxima", f"{mx:.1f} °C", temp_color(mx))
            self.st.set("Temperatura média", f"{sum(self.temps) / len(self.temps):.1f} °C")
        self.st.set("Uso da CPU", fmt(cpu.get("total"), "%", 0))
        self.st.set("Clock atual", fmt(clk, "MHz"))
        self.st.set("Clock no início", fmt(self.clk_start, "MHz"))
        if self.clocks:
            self.st.set("Clock mínimo", f"{min(self.clocks[3:] or self.clocks):.0f} MHz")
        drop = None
        if self.clk_start and len(self.clocks) >= 10:
            recent = sum(self.clocks[-10:]) / 10
            drop = max(0.0, (self.clk_start - recent) / self.clk_start * 100)
            self.st.set("Queda de clock", f"{drop:.1f} %", "#ff5d5d" if drop > 10 else "#f5c542" if drop > 4 else "#4fd18b")
        tc = stress.throttle_count(hw.ROOT)
        if tc is not None and self.throttle0 is not None:
            ev = tc - self.throttle0
            self.st.set("Limitação térmica (eventos)", ev, "#ff5d5d" if ev else "#4fd18b")
        else:
            self.st.set("Limitação térmica (eventos)", "— (contador não exposto; veja a queda de clock)")
        self.st.set("Potência", fmt(pw, "W", 1) if pw else need_admin(
            "— (requer “Modo administrador”)",
            "aguardando leitura…" if ADMIN["rapl"] else "— (RAPL não disponível neste sistema)"))
        if self.powers:
            self.st.set("Potência máxima", f"{max(self.powers):.1f} W")
        self.st.set("Tensão do núcleo", fmt(d.get("vcore"), "V", 3) if d.get("vcore") else "—")
        fans = [f for f in (d.get("fans") or []) if f["kind"] == "board" and f["rpm"]]
        self.st.set("Ventoinha da CPU", f"{fans[0]['rpm']:.0f} RPM ({fans[0]['label']})" if fans else "—")
        self.st.set("Operações/s", f"{self.ops_rate:,}".replace(",", ".") if self.ops_rate else "—")
        if self.mem_mode:
            passes, errs, mb = self.mem
            self.st.set("RAM testada", f"{mb:,} MB · {passes} passada(s)".replace(",", ".") if mb else "alocando…")
            self.st.set("Erros de RAM", errs, "#ff5d5d" if errs else "#4fd18b")
        # condições de parada
        if t is not None and self.limit_c is not None and t >= self.limit_c:
            self.finish(f"Parado: temperatura atingiu {t:.0f} °C (limite {self.limit_c} °C)")
        elif self.mem_mode and self.mem[1]:
            self.finish(f"Parado: {self.mem[1]} erro(s) de memória detectado(s)")
        elif self.proc and self.proc.poll() is not None:
            self.finish("O processo de carga terminou inesperadamente (falta de memória?)")
        elif self.duration and el >= self.duration:
            self.finish("Concluído")

    def finish(self, reason):
        if not self.running:
            return
        self.running = False
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.btn.setText("▶ Iniciar teste")
        set_kind(self.btn, "green")
        for w_ in (self.mode, self.dur, self.limit):
            w_.setEnabled(True)
        mx = max(self.temps) if self.temps else None
        drop = None
        if self.clk_start and len(self.clocks) >= 10:
            drop = max(0.0, (self.clk_start - sum(self.clocks[-10:]) / 10) / self.clk_start * 100)
        el = time.monotonic() - self.t0 if self.t0 else 0
        parts = [reason, f"duração {fmt_duration(el)}"]
        if mx is not None:
            parts.append(f"temperatura máxima {mx:.0f} °C")
        if drop is not None:
            parts.append(f"queda de clock {drop:.0f} %")
        if self.mem_mode:
            parts.append(f"{self.mem[1]} erro(s) de RAM em {self.mem[0]} passada(s)")
        if reason.startswith("Parado") and "erro" in reason:
            col, verdict = "#ff5d5d", "✖ Instável — erros de memória. Rode o MemTest86 e verifique XMP/EXPO."
        elif reason.startswith("Parado"):
            col, verdict = "#ff5d5d", "✖ Temperatura alta — verifique cooler, pasta térmica e fluxo de ar do gabinete."
        elif reason.startswith("O processo"):
            col, verdict = "#ff5d5d", "✖ O teste não pôde continuar."
        elif drop is not None and drop > 10:
            col, verdict = "#f5c542", "⚠ Estável, mas o clock caiu bastante sob carga (provável limitação térmica ou de energia)."
        elif mx is not None and mx >= 90:
            col, verdict = "#f5c542", "⚠ Estável, mas a temperatura ficou muito alta."
        elif reason == "Concluído":
            col, verdict = "#4fd18b", "✔ Estável — sem erros e temperatura dentro do normal."
        else:
            col, verdict = "#8a93a3", "Teste interrompido antes do fim."
        c = QColor(col)
        self.banner.setText(f"{verdict}\n" + " · ".join(parts))
        self.banner.setStyleSheet(f"background:rgba({c.red()},{c.green()},{c.blue()},40); border:1px solid {col};"
                                  f"color:{col}; border-radius:2px; padding:8px 12px; font-weight:600;")
        self.banner.show()
        self.st.set("Estado", reason, col)
        self.bar.setFormat("encerrado")

    def stop(self):
        if self.running:
            self.finish("Interrompido")

    def set_rapl(self, svc):
        pass

    last_temp = None


class _StressReader(QThread):
    line = Signal(list)

    def __init__(self, proc):
        super().__init__()
        self.proc = proc

    def run(self):
        try:
            for ln in self.proc.stdout:
                self.line.emit(ln.split())
        except Exception:
            pass
