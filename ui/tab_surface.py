"""Discos → Verificar superfície (somente leitura)."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QThread, Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QListWidget, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from core import hwinfo as hw
from core import surface
from core.hwinfo import human_bytes
from ui.kit import ask, message, set_kind
from ui.common import InfoGroup, bar, scroll
from ui.theme import T


class SurfaceWorker(QThread):
    line = Signal(list)
    failed = Signal(str)
    finished_ok = Signal(int)

    def __init__(self, dev, ncell, mode, admin=None):
        super().__init__()
        self.dev, self.ncell, self.mode = dev, ncell, mode
        self.cancel = False
        self.proc = None
        self.admin = admin

    def run(self):
        if self.admin is not None:
            return self._run_admin()
        try:
            self.proc = surface.start(self.dev, self.ncell, self.mode, env=hw.clean_env(),
                                      fake_bad=os.environ.get("HWSCOPE_FAKE_BAD", ""))
        except Exception as e:
            self.failed.emit(str(e))
            return
        got = False
        for ln in self.proc.stdout:
            if self.cancel:
                break
            parts = ln.split()
            if parts:
                got = True
                self.line.emit(parts)
        if self.cancel:
            try:
                self.proc.terminate()
            except Exception:
                pass
            try:
                self.proc.stdout.close()  # helper como root encerra ao escrever no pipe fechado
            except Exception:
                pass
        rc = self.proc.wait()
        if not got and not self.cancel:
            err = (self.proc.stderr.read() or "").strip()
            last = err.splitlines()[-1] if err else ""
            self.failed.emit("Autorização negada." if rc in (126, 127) else (last[-300:] or f"falhou (código {rc})"))
            return
        self.finished_ok.emit(rc)

    def _run_admin(self):
        import queue as _q
        c = self.admin.client
        rid, q = c.stream_queue("surface", dev=self.dev, ncell=self.ncell, mode=self.mode)
        if rid is None:
            self.failed.emit("modo administrador não está ativo")
            return
        got, cancelled = False, False
        while True:
            try:
                item = q.get(timeout=0.5)
            except _q.Empty:
                if self.cancel and not cancelled:
                    c.cancel(rid)
                    cancelled = True
                continue
            if item[0] == "end":
                rc, err = item[1], (item[2] if len(item) > 2 else "")
                if not got and not self.cancel:
                    lines = (err or "").strip().splitlines()
                    self.failed.emit((lines[-1][-300:] if lines else "") or f"falhou (código {rc})")
                else:
                    self.finished_ok.emit(rc or 0)
                return
            parts = (item[1] or "").split()
            if parts:
                got = True
                self.line.emit(parts)
            if self.cancel and not cancelled:
                c.cancel(rid)
                cancelled = True


class BlockGrid(QWidget):
    def __init__(self, n=1000, cols=50):
        super().__init__()
        self.n, self.cols = n, cols
        self.state = [None] * n
        self.current = -1
        self.setMinimumSize(420, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def reset(self, n):
        self.n = n
        self.state = [None] * n
        self.current = -1
        self.update()

    def set(self, i, v):
        if 0 <= i < self.n:
            self.state[i] = v
            self.current = i + 1
            self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor(T.panel))
        rows = -(-self.n // self.cols)
        gap = 2
        cw = (r.width() - gap) / self.cols
        ch = (r.height() - gap) / rows
        for i in range(self.n):
            x = gap + (i % self.cols) * cw
            y = gap + (i // self.cols) * ch
            v = self.state[i]
            if v is None:
                col = QColor("#262c36") if i != self.current else QColor("#4a5568")
            elif v == "err":
                col = QColor(surface.ERR_COLOR)
            else:
                col = QColor(surface.CLASSES[v][1])
            p.fillRect(QRectF(x, y, cw - gap, ch - gap), col)
            if v == "err":
                p.setPen(QPen(QColor("#ffffff"), 1.2))
                p.drawLine(QPointF(x + 2, y + 2), QPointF(x + cw - gap - 2, y + ch - gap - 2))
                p.drawLine(QPointF(x + cw - gap - 2, y + 2), QPointF(x + 2, y + ch - gap - 2))
        p.end()


class SpeedGraph(QWidget):
    """Velocidade de leitura ao longo do disco (estilo benchmark do HD Tune)."""

    def __init__(self):
        super().__init__()
        self.n = 1000
        self.vals = {}
        self.setMinimumHeight(150)

    def reset(self, n):
        self.n, self.vals = n, {}
        self.update()

    def add(self, i, v):
        self.vals[i] = v
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor(T.panel2))
        left, bottom, top = 52, 18, 8
        w, h = r.width() - left - 8, r.height() - bottom - top
        mx = max(self.vals.values(), default=0)
        mx = max(10, mx * 1.15)
        p.setPen(QPen(QColor(T.border), 1))
        f = p.font()
        f.setPointSize(8)
        p.setFont(f)
        for k in range(5):
            y = top + h - h * k / 4
            p.setPen(QPen(QColor(T.border), 1))
            p.drawLine(QPointF(left, y), QPointF(left + w, y))
            p.setPen(QColor(T.muted))
            p.drawText(QRectF(0, y - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{mx * k / 4:.0f}")
        p.setPen(QColor(T.muted))
        p.drawText(QRectF(left, top + h + 2, w, 16), Qt.AlignLeft, "0%")
        p.drawText(QRectF(left, top + h + 2, w, 16), Qt.AlignCenter, "posição no disco")
        p.drawText(QRectF(left, top + h + 2, w, 16), Qt.AlignRight, "100%")
        p.save()
        p.translate(10, top + h / 2)
        p.rotate(-90)
        p.drawText(QRectF(-40, -6, 80, 14), Qt.AlignCenter, "MB/s")
        p.restore()
        if not self.vals:
            p.end()
            return
        path = QPainterPath()
        first = True
        for i in sorted(self.vals):
            x = left + w * (i + 0.5) / self.n
            y = top + h - h * self.vals[i] / mx
            if first:
                path.moveTo(x, y)
                first = False
            else:
                path.lineTo(x, y)
        p.setPen(QPen(QColor(T.disk), 1.6))
        p.drawPath(path)
        p.end()


class SurfaceTab(QWidget):
    """Verificação de superfície (somente leitura), como o Error Scan do HD Tune."""
    NCELL = 1000

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(QLabel("Disco:"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(330)
        top.addWidget(self.combo)
        top.addWidget(QLabel("  Modo:"))
        self.mode = QComboBox()
        self.mode.addItems(["Rápida (amostra de 4 MiB por bloco)", "Completa (lê o disco inteiro)"])
        top.addWidget(self.mode)
        top.addStretch()
        self.btn = QPushButton("▶ Iniciar verificação")
        self.btn.setProperty("kind", "green")
        top.addWidget(self.btn)
        self.save_btn = QPushButton("Salvar relatório")
        self.save_btn.setEnabled(False)
        top.addWidget(self.save_btn)
        outer.addLayout(top)
        info = QLabel("Somente leitura: nenhum dado é gravado no disco. Usa o “Modo administrador” para ler o "
                      "dispositivo. A verificação completa de um HD de 1 TB leva cerca de 2 horas.")
        info.setObjectName("muted")
        info.setWordWrap(True)
        outer.addWidget(info)
        self.banner = QLabel("")
        self.banner.setObjectName("banner")
        self.banner.hide()
        outer.addWidget(self.banner)

        body = QHBoxLayout()
        body.setSpacing(12)
        left = QVBoxLayout()
        gbox = QGroupBox("Mapa de blocos (cada quadrado = 0,1% do disco)")
        gl = QVBoxLayout(gbox)
        gl.setContentsMargins(8, 18, 8, 8)
        self.grid = BlockGrid(self.NCELL)
        gl.addWidget(self.grid)
        left.addWidget(gbox, 3)
        sbox = QGroupBox("Velocidade de leitura")
        sl = QVBoxLayout(sbox)
        sl.setContentsMargins(8, 18, 8, 8)
        self.graph = SpeedGraph()
        sl.addWidget(self.graph)
        left.addWidget(sbox, 2)
        body.addLayout(left, 3)

        rw = QWidget()
        right = QVBoxLayout(rw)
        right.setContentsMargins(0, 0, 4, 0)
        right.setSpacing(10)
        self.stats = InfoGroup("Progresso")
        for k in ("Progresso", "Posição", "Velocidade atual", "Velocidade mínima", "Velocidade média",
                  "Velocidade máxima", "Tempo de acesso", "Decorrido", "Restante", "Leitura direta"):
            self.stats.add(k)
        self.bar = bar()
        right.addWidget(self.bar)
        right.addWidget(self.stats)
        leg = QGroupBox("Tempo de leitura por bloco de 1 MiB")
        ll = QGridLayout(leg)
        ll.setContentsMargins(12, 18, 12, 10)
        self.counts = []
        items = list(surface.CLASSES) + [("Erro de leitura", surface.ERR_COLOR)]
        for r, (lab, col) in enumerate(items):
            sw = QLabel("■")
            sw.setStyleSheet(f"color:{col}; font-size:16px;")
            ll.addWidget(sw, r, 0)
            ll.addWidget(QLabel(lab), r, 1)
            c = QLabel("0")
            c.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            ll.addWidget(c, r, 2)
            self.counts.append(c)
        ll.setColumnStretch(1, 1)
        right.addWidget(leg)
        bad = QGroupBox("Setores ilegíveis (LBA)")
        bl = QVBoxLayout(bad)
        bl.setContentsMargins(8, 18, 8, 8)
        self.badlist = QListWidget()
        self.badlist.setMaximumHeight(140)
        bl.addWidget(self.badlist)
        right.addWidget(bad)
        right.addStretch()
        rs = scroll(rw)
        rs.setMinimumWidth(380)
        body.addWidget(rs, 2)
        outer.addLayout(body, 1)

        self.disks = []
        self.worker = None
        self.btn.clicked.connect(self.toggle)
        self.save_btn.clicked.connect(self.save)
        self._reset_stats()

    def set_disks(self, disks):
        self.disks = disks
        self.combo.clear()
        for d in disks:
            self.combo.addItem(f"{d['model']} — {human_bytes(d['size'], binary=False)} ({d['dev']})")

    def _reset_stats(self):
        self.size = 0
        self.hist = [0] * 6
        self.speeds = {}
        self.bad = []
        self.done_cells = 0
        self.t0 = None
        self.access = None
        self.direct = None
        self.result = None
        for c in self.counts:
            c.setText("0")
        self.badlist.clear()
        self.bar.setValue(0)
        self.bar.setFormat("0 %")

    def toggle(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel = True
            self.btn.setEnabled(False)
            self.btn.setText("Parando…")
            return
        i = self.combo.currentIndex()
        if not (0 <= i < len(self.disks)):
            return
        d = self.disks[i]
        use_admin = not os.access(d["dev"], os.R_OK)
        if use_admin and not (self.admin and self.admin.active):
            r = ask(self, "Modo administrador",
                    "Ler o disco diretamente exige permissão de administrador.\n\n"
                    "Ativar o Modo administrador agora? (a senha é pedida uma única vez)",
                    confirm="ATIVAR", kind="info", confirm_kind="green")
            if r and self.admin:
                self._pending = True
                self.admin.start()
            return
        mode = "quick" if self.mode.currentIndex() == 0 else "full"
        self._reset_stats()
        self.grid.reset(self.NCELL)
        self.graph.reset(self.NCELL)
        self.banner.hide()
        self.cur_disk = d
        self.cur_mode = mode
        self.stats.set("Progresso", "iniciando…")
        self.worker = SurfaceWorker(d["dev"], self.NCELL, mode, self.admin if use_admin else None)
        self.worker.line.connect(self._line)
        self.worker.failed.connect(self._failed)
        self.worker.finished_ok.connect(self._finished)
        self.worker.start()
        self.btn.setText("■ Parar")
        set_kind(self.btn, "cancel")
        self.combo.setEnabled(False)
        self.mode.setEnabled(False)
        self.save_btn.setEnabled(False)

    def _line(self, parts):
        tag = parts[0]
        if tag == "S":
            self.size = int(parts[1])
            self.direct = parts[2] == "1"
            self.t0 = time.monotonic()
            self.stats.set("Leitura direta", "Sim (O_DIRECT, sem cache)" if self.direct else "Não (com cache do sistema)")
        elif tag == "A":
            self.access = float(parts[1])
            self.stats.set("Tempo de acesso", f"{parts[1]} ms (mediana {parts[2]} ms)")
        elif tag == "E":
            lba, n = int(parts[1]), int(parts[2])
            self.bad.append((lba, n))
            self.badlist.addItem(f"LBA {lba:,}".replace(",", ".") + f"  ({n} setores de 512 B)")
        elif tag == "B":
            i, errs, nbytes, el = int(parts[1]), int(parts[3]), int(parts[4]), float(parts[5])
            hist = [int(x) for x in parts[6:11]]
            for k in range(5):
                self.hist[k] += hist[k]
            self.hist[5] += errs
            for k, c in enumerate(self.counts):
                c.setText(f"{self.hist[k]:,}".replace(",", "."))
            if errs:
                st = "err"
            else:
                st = next((k for k in range(4, -1, -1) if hist[k]), 0)
            self.grid.set(i, st)
            if el > 0 and nbytes:
                sp = nbytes / el / 1e6
                self.speeds[i] = sp
                self.graph.add(i, sp)
                self.stats.set("Velocidade atual", f"{sp:.1f} MB/s")
                v = list(self.speeds.values())
                self.stats.set("Velocidade mínima", f"{min(v):.1f} MB/s")
                self.stats.set("Velocidade média", f"{sum(v) / len(v):.1f} MB/s")
                self.stats.set("Velocidade máxima", f"{max(v):.1f} MB/s")
            self.done_cells = i + 1
            frac = self.done_cells / self.NCELL
            self.bar.setValue(int(frac * 1000))
            self.bar.setFormat(f"{frac * 100:.1f} %")
            self.stats.set("Progresso", f"{self.done_cells} / {self.NCELL} blocos")
            if self.size:
                self.stats.set("Posição", f"{human_bytes(self.size * frac, binary=False)} de {human_bytes(self.size, binary=False)}")
            if self.t0:
                el_all = time.monotonic() - self.t0
                self.stats.set("Decorrido", hw.fmt_uptime(el_all) if el_all >= 60 else f"{el_all:.0f} s")
                rem = el_all / frac * (1 - frac) if frac else None
                self.stats.set("Restante", (hw.fmt_uptime(rem) if rem >= 60 else f"{rem:.0f} s") if rem is not None else None)

    def _end_ui(self):
        self.btn.setEnabled(True)
        self.btn.setText("▶ Iniciar verificação")
        set_kind(self.btn, "green")
        self.combo.setEnabled(True)
        self.mode.setEnabled(True)

    def _failed(self, msg):
        self._end_ui()
        self.stats.set("Progresso", "não iniciado", "#ff5d5d")
        self._banner(f"Não foi possível ler o disco: {msg}", "#ff5d5d")

    def _finished(self, rc):
        self._end_ui()
        self.save_btn.setEnabled(True)
        cancelled = self.done_cells < self.NCELL
        nbad = sum(n for _, n in self.bad)
        slow = self.hist[4]
        if self.hist[5]:
            self.result = f"✖ {self.hist[5]} bloco(s) de 1 MiB com erro de leitura · {nbad} setor(es) de 512 B ilegíveis"
            self._banner(self.result + ". Faça backup e confira o SMART (aba Discos → Informações e saúde).", "#ff5d5d")
        elif slow:
            self.result = f"⚠ Nenhum erro, mas {slow} bloco(s) muito lentos (≥ 500 ms) — possíveis setores fracos"
            self._banner(self.result + ".", "#f5c542")
        else:
            self.result = "✔ Nenhum setor defeituoso encontrado" + (" (verificação interrompida)" if cancelled else "")
            self._banner(self.result + ".", "#4fd18b")
        if cancelled:
            self.stats.set("Progresso", f"interrompido em {self.done_cells / self.NCELL * 100:.1f} %")

    def _banner(self, text, color):
        self.banner.setText(text)
        c = QColor(color)
        self.banner.setStyleSheet(f"background:rgba({c.red()},{c.green()},{c.blue()},40); border:1px solid {color}; color:{color};"
                                  f"border-radius:2px; padding:8px 12px; font-weight:600;")
        self.banner.show()

    def save(self):
        d = getattr(self, "cur_disk", None)
        if not d:
            return
        default = os.path.expanduser(f"~/hwscope-superficie-{d['name']}-{time.strftime('%Y%m%d-%H%M')}.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Salvar relatório", default, "Texto (*.txt)")
        if not path:
            return
        v = list(self.speeds.values())
        L = [f"HWScope — verificação de superfície ({'rápida' if self.cur_mode == 'quick' else 'completa'})",
             f"Data: {time.strftime('%d/%m/%Y %H:%M')}",
             f"Disco: {d['model']} ({d['dev']}) — {human_bytes(d['size'], binary=False)}",
             f"Resultado: {self.result}",
             f"Blocos verificados: {self.done_cells}/{self.NCELL}",
             f"Tempo de acesso: {self.access} ms" if self.access else "",
             f"Velocidade mín/méd/máx: {min(v):.1f} / {sum(v) / len(v):.1f} / {max(v):.1f} MB/s" if v else "",
             "", "Blocos de 1 MiB por tempo de leitura:"]
        for (lab, _), n in zip(surface.CLASSES, self.hist):
            L.append(f"  {lab:<10} {n}")
        L.append(f"  Erro       {self.hist[5]}")
        if self.bad:
            L.append("")
            L.append("Setores ilegíveis (LBA inicial, quantidade de setores de 512 B):")
            L += [f"  {a}  {n}" for a, n in self.bad]
        try:
            with open(path, "w") as f:
                f.write("\n".join(x for x in L if x is not None) + "\n")
        except OSError as e:
            message(self, "Erro ao salvar", str(e), "error")

    admin = None
    _pending = False

    def admin_changed(self):
        if self._pending and self.admin and self.admin.active:
            self._pending = False
            self.toggle()
        elif self._pending and self.admin and not self.admin.starting and not self.admin.active:
            self._pending = False

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel = True
            self.worker.wait(3000)
