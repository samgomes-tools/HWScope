"""Janela principal."""
from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import QMetaObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QHeaderView, QLabel, QMainWindow, QSizePolicy, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from core import hwinfo as hw
from core import health
from core.hwinfo import human_bytes
from ui.about import AboutDialog
from ui.admin import AdminService, AdminTaskWorker, RaplService
from ui.collector import Collector
from ui.kit import ScopeDialog, btn, message, vsep
from ui.common import ADMIN, fmt, need_admin, temp_color
from ui.meta import APP_NAME, APP_VERSION, HERE
from ui.tab_board import BoardTab, SystemTab
from ui.tab_cpu import CachesTab, CpuTab
from ui.tab_devices import DevicesTab
from ui.tab_diskbench import DiskBenchTab
from ui.tab_disks import DiskTab, DisksTab
from ui.tab_gpu import GpuTab
from ui.tab_memory import MemoryTab, SpdTab
from ui.tab_overview import OverviewTab
from ui.tab_stress import StressTab
from ui.tab_surface import SurfaceTab
from ui.theme import T


class MainWindow(QMainWindow):
    set_interval = Signal(int)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — Monitor de Hardware")
        self.resize(1360, 820)
        self.setMinimumSize(1260, 640)
        icon = os.path.join(HERE, "hwscope.png")
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))
        self.static = {}
        self.last = {}

        # ---- cabeçalho: logo, nome, abas, status e atualizar
        header = QWidget()
        header.setObjectName("Header")
        header.setFixedHeight(58)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 14, 0)
        hl.setSpacing(0)
        logo = QLabel()
        icon_pm = QPixmap(os.path.join(HERE, "hwscope.png"))
        if not icon_pm.isNull():
            logo.setPixmap(icon_pm.scaled(34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        hl.addWidget(logo)
        hl.addSpacing(10)
        name = QLabel(APP_NAME.upper())
        name.setObjectName("appName")
        nf = name.font()
        nf.setPointSizeF(15)
        nf.setBold(True)
        nf.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        name.setFont(nf)
        hl.addWidget(name)
        hl.addSpacing(22)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_box = QHBoxLayout()
        self.nav_box.setSpacing(0)
        hl.addLayout(self.nav_box)
        hl.addStretch(1)
        self.status_pill = btn("…", "pill", self.show_diag)
        self.status_pill.setProperty("state", "ok")
        hl.addWidget(self.status_pill)
        hl.addSpacing(10)
        self.refresh_btn = btn("⟳ ATUALIZAR", None, self.refresh_now)
        self.refresh_btn.setToolTip("Lê agora os sensores, as dependências e, no Modo administrador, o SMART dos discos")
        hl.addWidget(self.refresh_btn)

        # ---- barra de ferramentas
        toolbar = QWidget()
        toolbar.setObjectName("Toolbar")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(12, 5, 12, 5)
        tl.setSpacing(4)
        tl.addWidget(QLabel("Atualizar a cada "))
        self.interval = QComboBox()
        self.interval.addItems(["0,5 s", "1 s", "2 s", "5 s"])
        self.interval.setCurrentIndex(1)
        self.interval.currentIndexChanged.connect(
            lambda i: self.set_interval.emit([500, 1000, 2000, 5000][i]))
        tl.addWidget(self.interval)
        tl.addSpacing(6)
        tl.addWidget(vsep())
        self.admin_btn = btn("🔒  Modo administrador", "tool", self.activate_admin)
        self.admin_btn.setToolTip("Pede a senha uma única vez e libera tudo que precisa de root: sensores de "
                                  "disco/RAM, SPD, dmidecode, SMART completo, potência RAPL e verificação de superfície")
        tl.addWidget(self.admin_btn)
        self.diag_btn = btn("🩺  Diagnóstico", "tool", self.show_diag)
        tl.addWidget(self.diag_btn)
        tl.addWidget(vsep())
        self.export_btn = btn("⤓  Exportar relatório", "tool", self.export)
        tl.addWidget(self.export_btn)
        self.about_btn = btn("ⓘ  Sobre", "tool", self.about)
        tl.addWidget(self.about_btn)
        tl.addStretch(1)
        ver = QLabel(f"{APP_NAME} v{APP_VERSION}")
        ver.setObjectName("appVer")
        tl.addWidget(ver)
        QTimer.singleShot(1500, self.check_deps)

        # ---- faixa de aviso (Modo administrador desligado)
        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(16, 8, 12, 8)
        bl.setSpacing(10)
        bt = QLabel("⚠  Temperatura de discos e RAM, SPD, SMART completo e potência da CPU precisam do Modo administrador.")
        bt.setWordWrap(True)
        bl.addWidget(bt, 1)
        bl.addWidget(btn("Agora não", "cancel", self.banner.hide))
        bl.addWidget(btn("ATIVAR MODO ADMINISTRADOR", "green", self.activate_admin))

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().hide()
        self.overview = OverviewTab()
        self.cpu = CpuTab()
        self.caches = CachesTab()
        self.board = BoardTab()
        self.sysinfo = SystemTab()
        self.mem = MemoryTab()
        self.spdtab = SpdTab()
        self.gpu = GpuTab()
        self.disk = DiskTab()
        self.surface = SurfaceTab()
        self.diskbench = DiskBenchTab()
        self.disks_tab = DisksTab(self.disk, self.surface, self.diskbench)
        self.devices = DevicesTab()
        self.stress = StressTab()
        self.rapl = RaplService()
        self.rapl.changed.connect(lambda: (self.cpu.set_rapl(self.rapl), self.stress.set_rapl(self.rapl)))
        self.admin = AdminService()
        self.admin.state.connect(self._admin_state)
        self.surface.admin = self.admin
        self._admin_tasks = None
        self._smart_timer = QTimer(self)
        self._smart_timer.timeout.connect(lambda: self._run_admin_tasks(("smart",)))
        self.cpu.set_rapl(self.rapl)
        self.stress.set_rapl(self.rapl)
        for w_, name in ((self.overview, "Visão geral"), (self.cpu, "CPU"), (self.caches, "Caches"),
                         (self.board, "Placa-mãe"), (self.mem, "Memória"), (self.spdtab, "SPD"),
                         (self.gpu, "GPU"), (self.disks_tab, "Discos"), (self.devices, "Dispositivos"),
                         (self.stress, "Estresse"),
                         (self.sysinfo, "Sistema")):
            self.tabs.addTab(w_, name)
            nb = btn(name, "nav")
            nb.setCheckable(True)
            nb.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.nav.addButton(nb, self.tabs.count() - 1)
            self.nav_box.addWidget(nb)
        self.nav.button(0).setChecked(True)
        self.nav.idClicked.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(lambda i: self.nav.button(i).setChecked(True))
        self.spdtab.spd_loaded.connect(lambda mods: self.mem.set_spd(mods))
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(header)
        cl.addWidget(toolbar)
        cl.addWidget(self.banner)
        cl.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.status = QLabel("Coletando informações…")
        self.statusBar().addWidget(self.status, 1)

        self.thread = QThread(self)
        self.collector = Collector()
        self.collector.moveToThread(self.thread)
        self.thread.started.connect(self.collector.start)
        self.collector.static_ready.connect(self.on_static)
        self.collector.dynamic_ready.connect(self.on_dynamic)
        self.set_interval.connect(self.collector.set_interval)
        self.thread.start()

    def shutdown(self):
        self.surface.stop()
        self.diskbench.stop()
        self.stress.stop()
        self.rapl.stop()
        self.admin.stop()
        if self.thread.isRunning():
            QMetaObject.invokeMethod(self.collector, "stop", Qt.BlockingQueuedConnection)
            self.thread.quit()
            self.thread.wait(1500)

    def closeEvent(self, ev):
        self.shutdown()
        super().closeEvent(ev)

    @Slot(object)
    def on_static(self, s):
        self.static = s
        self.cpu.set_static(s["cpu"])
        self.caches.set_static(s["cpu"])
        self.board.set_static(s["system"], s.get("chipset"), s["cpu"])
        self.sysinfo.set_static(s["system"])
        self.mem.set_static(s.get("dimms"), s.get("mem_array"), s.get("memgen"), s.get("spd"))
        self.spdtab.mem_type = ((s.get("memgen") or {}).get("type") or "").upper()
        self.spdtab.set_static(s.get("spd"), s.get("spd_msg", ""))
        self.disk.set_static(s.get("disks", []))
        self.surface.set_disks(s.get("disks", []))
        c = s["cpu"]
        self.overview.cpu.name.setText(c.get("name", "—"))
        self.overview.cpu.badge.setText(f"{c.get('cores')}C / {c.get('threads')}T")
        dimms = [d for d in (s.get("dimms") or []) if d["present"]]
        if dimms:
            t = dimms[0].get("type") or ""
            sp = dimms[0].get("configured") or dimms[0].get("speed")
            self.overview.ram.badge.setText(f"{t} {sp + ' MT/s' if sp else ''}".strip())
        disks = s.get("disks", [])
        self.overview.disk.badge.setText(f"{len(disks)} disco(s)")
        self.overview.disk.name.setText(
            human_bytes(sum(d["size"] for d in disks), binary=False) + " no total" if disks else "—")

    @Slot(object)
    def on_dynamic(self, d):
        if "gl" in d:
            self.gpu.set_gl(d["gl"], d.get("gpu_extra"))
            return
        if self.rapl.active and self.rapl.package is not None:
            d["cpu_power"] = self.rapl.package
        self.last = d
        ov = self.overview
        ov.update_sensors(d["chips"])
        cpu = d.get("cpu", {})
        t = d.get("cpu_temp")
        tot = cpu.get("total")
        if t is not None:
            ov.cpu.set_big(f"{t:.0f}°C", temp_color(t))
            ov.cpu.spark.add(t)
            ov.cpu.side.setText(f"uso <b>{tot:.0f}%</b>" if tot is not None else "")
        else:
            ov.cpu.set_big(f"{tot:.0f}%" if tot is not None else "—")
            ov.cpu.spark.fixed_max = 100
            ov.cpu.spark.add(tot)
            ov.cpu.side.setText("sem sensor de\ntemperatura")
        fr = cpu.get("freqs") or []
        ov.cpu.foot.setText(f"Clock médio {sum(fr) / len(fr):.0f} MHz · máx {max(fr):.0f} MHz" if fr else "")
        gpus = d.get("gpus") or []
        if gpus:
            g = gpus[0]
            ov.gpu.name.setText(g["name"])
            ov.gpu.badge.setText(g["driver"] or "")
            if g["temp"] is not None:
                ov.gpu.set_big(f"{g['temp']:.0f}°C", temp_color(g["temp"]))
                ov.gpu.spark.add(g["temp"])
            else:
                ov.gpu.set_big(fmt(g["busy"], "%") if g["busy"] is not None else "—")
                ov.gpu.spark.fixed_max = 100
                ov.gpu.spark.add(g["busy"])
            side = []
            if g["busy"] is not None and g["temp"] is not None:
                side.append(f"uso <b>{g['busy']:.0f}%</b>")
            if g["power"] is not None:
                side.append(f"{g['power']:.0f} W")
            ov.gpu.side.setText("<br>".join(side))
            foot = []
            if g["sclk"] is not None:
                foot.append(f"GPU {g['sclk']:.0f} MHz")
            if g["vram_used"] is not None and g["vram_total"]:
                foot.append(f"VRAM {human_bytes(g['vram_used'])} / {human_bytes(g['vram_total'])}")
            ov.gpu.foot.setText(" · ".join(foot))
        else:
            ov.gpu.name.setText("Nenhuma GPU detectada")
        m = d.get("mem") or {}
        if m:
            ov.ram.set_big(f"{m['percent']:.0f}%")
            ov.ram.name.setText(f"{human_bytes(m['total'])} instalados")
            rt = d.get("ram_temps") or []
            if rt:
                hot = max(t for _, t in rt)
                ov.ram.side.setText(f"<span style='font-size:22px;font-weight:700;color:{temp_color(hot)}'>{hot:.0f}°C</span>"
                                    f"<br>{human_bytes(m['used'])} em uso")
            else:
                ov.ram.side.setText(f"{human_bytes(m['used'])}<br>em uso")
            ov.ram.spark.add(m["percent"])
            ov.ram.foot.setText(f"Disponível {human_bytes(m['available'])} · Swap {m['swap_percent']:.0f}%")
        # disco: maior temperatura e IO total
        dtemps = [s["value"] for c in d["chips"] if c["kind"] == "disk" for s in c["sensors"] if s["type"] == "temp"]
        disks = {x["name"] for x in self.static.get("disks", [])}
        io = d.get("io", {})
        rd_ = sum(v[0] for k, v in io.items() if k in disks)
        wr_ = sum(v[1] for k, v in io.items() if k in disks)
        if dtemps:
            ov.disk.set_big(f"{max(dtemps):.0f}°C", temp_color(max(dtemps)))
            ov.disk.spark.add(max(dtemps))
        else:
            ov.disk.set_big(f"{(rd_ + wr_) / 1e6:.1f}", None)
            ov.disk.big.setText(f"{(rd_ + wr_) / 1e6:.1f} <span style='font-size:14px;color:{T.muted}'>MB/s</span>")
            ov.disk.spark.add((rd_ + wr_) / 1e6)
        ov.disk.side.setText(f"↓ {rd_ / 1e6:.1f} MB/s<br>↑ {wr_ / 1e6:.1f} MB/s")
        root = next((p for ps in d.get("parts", {}).values() for p in ps if p["mount"] == "/"), None)
        foot = f"Raiz (/): {root['percent']:.0f}% usado de {human_bytes(root['total'], binary=False)}" if root and root["total"] else ""
        if not dtemps:
            foot = need_admin("Sem temperatura — use o “Modo administrador”", "Os discos não informam temperatura")
        ov.disk.foot.setText(foot)

        self.cpu.set_dynamic(cpu, t, d.get("core_temps"), d.get("vcore"), d.get("cpu_power"))
        if self.rapl.active:
            self.cpu.set_rapl(self.rapl)
        self.board.set_superio(d.get("superio"))
        if gpus:
            prim = next((g for g in gpus if g["boot_vga"]), gpus[0])
            self.board.set_gpu(prim)
        self.mem.set_dynamic(m)
        self.mem.set_temps(d.get("ram_temps"))
        self.gpu.set_dynamic(gpus, t, m)
        self.disk.set_dynamic(d["chips"], d.get("parts", {}), io, d.get("disk_health"))
        self.diskbench.set_parts(d.get("parts", {}))
        ws = self.disk.worst_status()
        if ws:
            ov.disk.badge.setText(f"{len(self.static.get('disks', []))} disco(s) · {ws}")
            ov.disk.badge.setStyleSheet(f"color:{health.COLORS.get(ws, T.muted)};")
        self.sysinfo.set_uptime(d.get("uptime"))
        self.sysinfo.set_swap(d.get("swap"))
        dv = self.devices
        if "nets" in d:
            dv.set_net(d["nets"], d.get("net_glob"))
            dv.set_usb(d.get("usb") or [])
            dv.set_audio(d.get("audio"))
        dv.set_net_counters(d.get("net_ctr") or {})
        dv.set_batteries(d.get("bats") or [], d.get("ac"))
        dv.set_fans(d.get("fans") or [])
        ov.fan_names = dv.tree_names(d.get("fans") or [])
        self.stress.feed(d)
        nsens = sum(len(c["sensors"]) for c in d["chips"])
        self.status.setText(f"{nsens} sensores · ligado há {hw.fmt_uptime(d.get('uptime'))} · "
                            f"atualizado às {time.strftime('%H:%M:%S')}")

    def activate_admin(self):
        if self.admin.active or self.admin.starting:
            return
        self.status.setText("Aguardando a senha de administrador…")
        self.admin.start()

    def _admin_state(self):
        a = self.admin
        ADMIN["on"] = a.active
        ADMIN["rapl"] = self.rapl.available
        if a.active:
            self.admin_btn.setText("🔓  Administrador ativo")
            self.admin_btn.setProperty("state", "on")
            self.admin_btn.setEnabled(False)
            self.banner.hide()
            self.admin_btn.setToolTip("Funções de root liberadas até fechar o HWScope")
            if self._admin_tasks is None:
                self._run_admin_tasks()
                self._smart_timer.start(10 * 60 * 1000)
                if not self.rapl.readable:
                    self.rapl.start(self.admin)
        elif a.starting:
            self.admin_btn.setText("⏳  Aguardando senha…")
            self.admin_btn.setEnabled(False)
        else:
            self.admin_btn.setText("🔒  Modo administrador")
            self.admin_btn.setProperty("state", "")
            self.admin_btn.setEnabled(True)
            self._admin_tasks = None
            self._smart_timer.stop()
            if a.error:
                self.status.setText(f"Modo administrador: {a.error}")
        self.admin_btn.style().unpolish(self.admin_btn)
        self.admin_btn.style().polish(self.admin_btn)
        self.cpu.set_rapl(self.rapl)
        self.surface.admin_changed()

    def _run_admin_tasks(self, tasks=("modules", "dmidecode", "spd", "serials", "smart")):
        if not self.admin.active:
            return
        mem_type = ((self.static.get("memgen") or {}).get("type") or "").upper()
        w_ = AdminTaskWorker(self.admin, self.static.get("disks", []), mem_type, tasks)
        w_.result.connect(self._admin_result)
        self._admin_tasks = w_
        w_.start()
        if "modules" in tasks:
            self.status.setText("Modo administrador ativo: carregando sensores, lendo SPD, dmidecode e SMART…")

    def _admin_result(self, kind, data):
        if kind == "modules":
            out = data.get("out", "")
            ok = [l.split()[1] for l in out.splitlines() if l.startswith("OK ")]
            board = [l.split(None, 1)[1] for l in out.splitlines() if l.startswith("BOARD ")]
            self.admin_mods = {}
            for l in out.splitlines():
                p = l.split(None, 2)
                if len(p) >= 2 and p[0] in ("OK", "FAIL"):
                    self.admin_mods[p[1]] = (p[0], p[2] if len(p) > 2 else "")
            self.admin_acpi = "ACPICONFLICT" in out
            self.status.setText("Drivers carregados: " + (", ".join(ok) or "nenhum") +
                                (f" · sensores da placa-mãe: {board[0]}" if board else ""))
            self.check_deps()
        elif kind == "dimms":
            if not data.get("dimms") and not self.static.get("dimms"):
                self.mem.note.setText("O dmidecode não retornou dados dos pentes: " + (data.get("err") or
                                      "o firmware desta placa não informa os módulos.").strip()[:200])
            if data.get("dimms"):
                self.mem.apply_dimms(data["dimms"])
                self.static["dimms"] = data["dimms"]
                self.static["memgen"] = hw.memory_general(data["dimms"])
        elif kind == "spd":
            mods, msg = data
            self.static["spd"] = mods
            self.spdtab.mem_type = ((self.static.get("memgen") or {}).get("type") or "").upper()
            self.spdtab.apply_admin(mods, msg)
        elif kind == "serials":
            if data.get("board_serial"):
                self.board.board.set("Nº de série", data["board_serial"])
            if data.get("product_serial"):
                self.sysinfo.system.set("Nº de série", data["product_serial"])
            if data.get("product_uuid"):
                self.sysinfo.system.set("UUID", data["product_uuid"])
        elif kind == "smart":
            dev, info = data
            self.disk.set_smart(dev, info)

    def check_deps(self):
        try:
            self.deps = hw.dependencies(self.last.get("gpus") if self.last else None)
        except Exception as e:
            print("deps:", e, file=sys.stderr)
            return
        miss = [d for d in self.deps["deps"] if not d["ok"] and d["level"] in ("essencial", "recomendado")]
        ess = [d for d in miss if d["level"] == "essencial"]
        if miss:
            self.diag_btn.setText(f"⚠  Diagnóstico ({len(miss)})")
            self.diag_btn.setProperty("state", "bad" if ess else "warn")
            self.status_pill.setText(f"⚠ {len(miss)} PENDÊNCIA{'S' if len(miss) > 1 else ''}")
            self.status_pill.setProperty("state", "bad" if ess else "warn")
            self.status_pill.setToolTip("Clique para ver o que instalar")
            self.diag_btn.setToolTip("Faltam programas: " + ", ".join(d["exe"] for d in miss) +
                                     "\nClique para ver o que instalar.")
        else:
            self.diag_btn.setText("🩺  Diagnóstico")
            self.diag_btn.setProperty("state", "")
            self.status_pill.setText("✓ SISTEMA OK")
            self.status_pill.setProperty("state", "ok")
            self.status_pill.setToolTip("Todas as dependências essenciais e recomendadas estão instaladas")
            self.diag_btn.setToolTip("Todas as dependências essenciais e recomendadas estão instaladas")
        for b in (self.diag_btn, self.status_pill):
            b.style().unpolish(b)
            b.style().polish(b)

    def show_diag(self):
        from PySide6.QtWidgets import QPlainTextEdit, QLineEdit
        self.check_deps()
        deps = getattr(self, "deps", None) or {"deps": [], "kmods": [], "install": "", "family": "apt"}
        miss = sum(1 for d in deps["deps"] if not d["ok"] and d["level"] in ("essencial", "recomendado"))
        dlg = ScopeDialog(self, "Diagnóstico",
                          f"Faltam {miss} programa(s) recomendado(s)" if miss else "Todos os programas necessários estão instalados")
        dlg.resize(920, 760)
        dlg.setMinimumSize(760, 560)
        # conteúdo numa área com rolagem: as tabelas mantêm a altura e nada se sobrepõe
        from PySide6.QtWidgets import QLayout, QScrollArea
        inner = QWidget()
        inner.setObjectName("dlgBody")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(8)
        lay.setSizeConstraint(QLayout.SetMinimumSize)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setWidget(inner)
        dlg.body.addWidget(sa, 1)
        t = QLabel("Dependências")
        t.setObjectName("section")
        lay.addWidget(t)
        tbl = QTableWidget(len(deps["deps"]), 5)
        tbl.setHorizontalHeaderLabels(["", "Programa", "Para que serve", "Nível", "Pacote"])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tbl.setSelectionMode(QAbstractItemView.NoSelection)
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        for r, d in enumerate(deps["deps"]):
            col = "#a4d007" if d["ok"] else ("#ff6b6b" if d["level"] == "essencial" else
                                             "#ffcf6b" if d["level"] == "recomendado" else T.muted)
            vals = ["✔" if d["ok"] else "✖", d["exe"], d["why"], d["level"], d["pkg"] if not d["ok"] else "instalado"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c in (0, 4) or (c == 3 and not d["ok"]):
                    it.setForeground(QBrush(QColor(col)))
                if c == 0:
                    it.setTextAlignment(Qt.AlignCenter)
                tbl.setItem(r, c, it)
            tbl.setRowHeight(r, 26)
        tbl.setFixedHeight(36 + 26 * max(len(deps["deps"]), 1))
        lay.addWidget(tbl)
        row = QHBoxLayout()
        if deps["install"]:
            lab = QLabel("Para instalar o que falta:")
            row.addWidget(lab)
            cmd = QLineEdit(deps["install"])
            cmd.setReadOnly(True)
            cmd.setFont(QFont("monospace", 10))
            row.addWidget(cmd, 1)
            cbtn = btn("Copiar comando", "blue")
            cbtn.clicked.connect(lambda: QApplication.clipboard().setText(deps["install"]))
            row.addWidget(cbtn)
        else:
            ok = QLabel("✔ Todos os programas necessários estão instalados.")
            ok.setStyleSheet("color:#a4d007; font-weight:600;")
            row.addWidget(ok)
        lay.addLayout(row)
        if any(d["exe"] == "nvidia-smi" and not d["ok"] for d in deps["deps"]):
            nv = QLabel("GPU NVIDIA sem o driver proprietário: instale-o pela ferramenta de drivers da sua distro "
                        "(ex.: “Drivers adicionais” no Ubuntu/Mint).")
            nv.setWordWrap(True)
            nv.setStyleSheet("color:#ffcf6b;")
            lay.addWidget(nv)
        t2 = QLabel("Drivers de sensores do kernel")
        t2.setObjectName("section")
        lay.addWidget(t2)
        km = QTableWidget(len(deps["kmods"]), 3)
        km.setHorizontalHeaderLabels(["Driver", "Para que serve", "Estado"])
        km.verticalHeader().setVisible(False)
        km.setEditTriggers(QAbstractItemView.NoEditTriggers)
        km.setSelectionMode(QAbstractItemView.NoSelection)
        kh = km.horizontalHeader()
        kh.setSectionResizeMode(QHeaderView.ResizeToContents)
        kh.setSectionResizeMode(1, QHeaderView.Stretch)
        for r, m in enumerate(deps["kmods"]):
            tried = getattr(self, "admin_mods", {}).get(m["name"])
            if m["loaded"]:
                st, col = "carregado", "#4fd18b"
            elif tried and tried[0] == "FAIL":
                why = tried[1].lower()
                if m["name"] in ("nct6775", "it87") and getattr(self, "admin_acpi", False):
                    st = "bloqueado pelo ACPI da placa (precisa do parâmetro de kernel acpi_enforce_resources=lax)"
                elif "no such device" in why or "no such" in why:
                    st = "testado: este chip não existe nesta placa"
                elif "not found" in why:
                    st = "não existe neste kernel"
                else:
                    st = f"falhou: {tried[1][:80]}" if tried[1] else "testado: não carregou"
                col = T.muted
            elif tried and tried[0] == "OK":
                st, col = "carregado e descarregado (sem hardware compatível)", T.muted
            elif m["available"]:
                st, col = ("disponível — será usado pelo Modo administrador" if not self.admin.active
                           else "disponível"), "#f5c542"
            else:
                st, col = "não existe neste kernel", T.muted
            for c, v in enumerate([m["name"], m["why"], st]):
                it = QTableWidgetItem(v)
                if c == 2:
                    it.setForeground(QBrush(QColor(col)))
                km.setItem(r, c, it)
            km.setRowHeight(r, 26)
        km.setFixedHeight(36 + 26 * max(len(deps["kmods"]), 1))
        lay.addWidget(km)
        t3 = QLabel("Sensores e discos")
        t3.setObjectName("section")
        lay.addWidget(t3)
        txt = hw.diagnostics(self.static, self.last)
        dep_txt = "Dependências:\n" + "\n".join(
            f"  {'OK ' if d['ok'] else 'FALTA'}  {d['exe']:<15} {d['level']:<12} {d['pkg']}" for d in deps["deps"])
        if deps["install"]:
            dep_txt += f"\n  Instalar: {deps['install']}"
        dep_txt += "\n\nDrivers do kernel:\n" + "\n".join(
            f"  {m['name']:<10} {'carregado' if m['loaded'] else 'disponível' if m['available'] else 'ausente'}"
            for m in deps["kmods"])
        full = dep_txt + "\n\n" + txt
        ed = QPlainTextEdit(txt)
        ed.setReadOnly(True)
        ed.setMinimumHeight(220)
        lay.addWidget(ed, 1)
        dlg.add_button("FECHAR", "cancel", dlg.reject)
        dlg.add_button("COPIAR TUDO", "blue", lambda: QApplication.clipboard().setText(full))
        dlg.exec()

    def export(self):
        if not self.static or not self.last:
            return
        default = os.path.expanduser(f"~/hwscope-{time.strftime('%Y%m%d-%H%M')}.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Exportar relatório", default, "Texto (*.txt)")
        if not path:
            return
        try:
            with open(path, "w") as f:
                f.write(hw.build_report(self.static, self.last))
            self.status.setText(f"Relatório salvo em {path}")
        except OSError as e:
            message(self, "Erro ao salvar", str(e), "error")

    def refresh_now(self):
        QMetaObject.invokeMethod(self.collector, "tick", Qt.QueuedConnection)
        self.check_deps()
        if self.admin.active:
            self._run_admin_tasks(("smart",))
        self.status.setText("Atualizando…")

    def about(self):
        AboutDialog(self, admin_active=self.admin.active).exec()
