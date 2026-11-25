"""Abas Placa-mãe e Sistema (inclui swap)."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QGroupBox, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from core import hwinfo as hw
from core.hwinfo import human_bytes
from ui.common import InfoGroup, bar, scroll


class BoardTab(QWidget):
    """Aba Mainboard do CPU-Z."""

    def __init__(self):
        super().__init__()
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(14, 14, 14, 14)
        g.setSpacing(12)
        self.board = InfoGroup("Placa-mãe", cols=2)
        for k in ("Fabricante", "Modelo", "Versão", "Nº de série", "Chipset", "PCIe máximo"):
            self.board.add(k)
        self.board.add("Norte (host bridge)", span=2)
        self.board.add("Rev. host bridge")
        self.board.add("Rev. LPC")
        self.board.add("Sul (LPC/ISA)", span=2)
        self.board.add("LPCIO (Super I/O)", span=2)
        self.bios = InfoGroup("BIOS / UEFI", cols=2)
        for k in ("Fabricante", "Versão", "Data", "Revisão", "Modo de boot", "Secure Boot", "Microcódigo da CPU"):
            self.bios.add(k)
        self.gi = InfoGroup("Interface gráfica", cols=2)
        for k in ("Barramento", "Dispositivo", "Largura atual", "Largura máx.", "Velocidade atual", "Velocidade máx."):
            self.gi.add(k)
        g.addWidget(self.board, 0, 0)
        g.addWidget(self.bios, 1, 0)
        g.addWidget(self.gi, 2, 0)
        g.setRowStretch(3, 1)
        note = QLabel("Nº de série da placa-mãe só é legível como root na maioria das distros.")
        note.setObjectName("muted")
        g.addWidget(note, 3, 0, Qt.AlignTop)
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.addWidget(scroll(w))

    def set_static(self, s, chipset, cpu):
        self.board.set_many(s["board"])
        self.board.set_many(chipset or {})
        self.bios.set_many(s["bios"])
        self.bios.set("Microcódigo da CPU", cpu.get("microcode"))

    def set_superio(self, name):
        self.board.set("LPCIO (Super I/O)", name or "— (driver do Super I/O não carregado)")

    def set_gpu(self, g):
        if not g:
            return
        self.gi.set_many({
            "Barramento": "PCI-Express" + (f" {g['link_max'].split(' (')[0].replace('PCIe ', '')}" if g.get("link_max") else ""),
            "Dispositivo": g["name"],
            "Largura atual": f"x{g['width_cur']}" if g.get("width_cur") else None,
            "Largura máx.": f"x{g['width_max']}" if g.get("width_max") else None,
            "Velocidade atual": g.get("link_cur"), "Velocidade máx.": g.get("link_max"),
        })


class SystemTab(QWidget):
    def __init__(self):
        super().__init__()
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(14, 14, 14, 14)
        g.setSpacing(12)
        self.system = InfoGroup("Sistema")
        for k in ("Fabricante", "Produto", "Versão", "Família", "SKU", "Chassi"):
            self.system.add(k)
        self.os = InfoGroup("Sistema operacional")
        for k in ("Distribuição", "Kernel", "Arquitetura", "Hostname", "Ambiente gráfico", "Sessão", "Boot", "Ligado há"):
            self.os.add(k)
        g.addWidget(self.system, 0, 0)
        g.addWidget(self.os, 0, 1)
        self.swap = InfoGroup("Swap", cols=2)
        for k in ("Total", "Em uso", "Livre", "Swappiness", "Entrada (swap-in)", "Saída (swap-out)",
                  "Lido do swap desde o boot", "Gravado no swap desde o boot", "vfs_cache_pressure",
                  "page-cluster", "zswap", "Hibernação"):
            self.swap.add(k)
        self.swap_bar = bar(usage=True)
        self.swap.grid.addWidget(self.swap_bar, 100, 0, 1, 4)
        g.addWidget(self.swap, 1, 0, 1, 2)
        dv = QGroupBox("Dispositivos de swap")
        dl = QVBoxLayout(dv)
        dl.setContentsMargins(8, 18, 8, 8)
        self.swap_tbl = QTableWidget(0, 6)
        self.swap_tbl.setHorizontalHeaderLabels(["Dispositivo", "Tipo", "Tamanho", "Em uso", "Prioridade", "Detalhes"])
        self.swap_tbl.verticalHeader().setVisible(False)
        self.swap_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.swap_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.swap_tbl.horizontalHeader().setStretchLastSection(True)
        self.swap_tbl.setFixedHeight(130)
        dl.addWidget(self.swap_tbl)
        self.swap_note = QLabel("")
        self.swap_note.setObjectName("muted")
        self.swap_note.setWordWrap(True)
        dl.addWidget(self.swap_note)
        g.addWidget(dv, 2, 0, 1, 2)
        g.setRowStretch(3, 1)
        self._last_swap = None
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.addWidget(scroll(w))

    def set_static(self, s):
        self.system.set_many(s["system"])
        self.os.set_many(s["os"])

    def set_uptime(self, up):
        self.os.set("Ligado há", hw.fmt_uptime(up))

    def set_swap(self, sw):
        if not sw:
            return
        tot, used = sw["total"] or 0, sw["used"] or 0
        pct = used / tot * 100 if tot else 0
        self.swap.set("Total", human_bytes(tot) if tot else "0 (sem swap ativo)")
        self.swap.set("Em uso", f"{human_bytes(used)}  ({pct:.1f} %)", "#f5c542" if pct > 50 else None)
        self.swap.set("Livre", human_bytes(tot - used))
        self.swap_bar.setValue(int(pct * 10))
        self.swap_bar.setFormat(f"{human_bytes(used)} / {human_bytes(tot)}  ({pct:.0f} %)")
        sv = sw.get("swappiness")
        hint = {"60": " (padrão)", "10": " (baixo: evita usar swap)", "100": " (alto)", "0": " (só em último caso)"}
        if sv and sv.isdigit() and int(sv) > 100:
            hint[sv] = " (alto — típico com zram)"
        self.swap.set("Swappiness", f"{sv}{hint.get(sv, '')}" if sv else None)
        self.swap.set("vfs_cache_pressure", sw.get("cache_pressure"))
        self.swap.set("page-cluster", f"{sw['page_cluster']} ({2 ** int(sw['page_cluster'])} páginas por leitura)"
                      if (sw.get("page_cluster") or "").isdigit() else sw.get("page_cluster"))
        z = sw.get("zswap")
        if z:
            txt = f"Ativado · {z['compressor']}" + (f" · {z['zpool']}" if z.get("zpool") else "") + \
                  f" · até {z['pool']}% da RAM" if z["enabled"] else "Desativado"
            if z["enabled"] and sw.get("zswap_stored") is not None:
                txt += f" · {human_bytes(sw['zswap_stored'])} armazenados"
        else:
            txt = "Não disponível no kernel"
        self.swap.set("zswap", txt)
        self.swap.set("Hibernação", sw.get("hibernate"))
        now = time.monotonic()
        if sw.get("sin") is not None:
            self.swap.set("Lido do swap desde o boot", human_bytes(sw["sin"]))
            self.swap.set("Gravado no swap desde o boot", human_bytes(sw["sout"]))
            if self._last_swap:
                t0, i0, o0 = self._last_swap
                dt = max(now - t0, 1e-3)
                ri, ro = max(sw["sin"] - i0, 0) / dt, max(sw["sout"] - o0, 0) / dt
                self.swap.set("Entrada (swap-in)", f"{human_bytes(ri)}/s", "#ff8a3d" if ri > 1e6 else None)
                self.swap.set("Saída (swap-out)", f"{human_bytes(ro)}/s", "#ff8a3d" if ro > 1e6 else None)
            self._last_swap = (now, sw["sin"], sw["sout"])
        devs = sw.get("devices") or []
        if self.swap_tbl.rowCount() != len(devs):
            self.swap_tbl.setRowCount(len(devs))
            self.swap_tbl.setFixedHeight(40 + 30 * max(len(devs), 1))
        for r, d in enumerate(devs):
            det = []
            if d.get("algoritmo"):
                det.append(f"algoritmo {d['algoritmo']}")
            if d.get("dados") is not None:
                det.append(f"{human_bytes(d['dados'])} de dados em {human_bytes(d['ocupando'])} de RAM")
            if d.get("taxa"):
                det.append(f"compressão {d['taxa']:.1f}:1")
            if d.get("disco"):
                det.append(f"no disco {d['disco']}")
            if d.get("volume"):
                det.append(f"volume {d['volume']}")
            vals = [d["name"], d["kind"], human_bytes(d["size"]),
                    f"{human_bytes(d['used'])} ({d['used'] / d['size'] * 100:.0f} %)" if d["size"] else "—",
                    d["prio"], " · ".join(det) or "—"]
            for c, v in enumerate(vals):
                it = self.swap_tbl.item(r, c)
                if it is None:
                    it = QTableWidgetItem()
                    self.swap_tbl.setItem(r, c, it)
                it.setText(str(v))
        if not devs:
            self.swap_note.setText("Nenhum swap ativo. Sem swap, o sistema pode encerrar programas quando a RAM acabar.")
        elif any("zram" in d["kind"] for d in devs) and len(devs) > 1:
            self.swap_note.setText("zram é usado primeiro (prioridade maior); o swap em disco serve de reserva.")
        else:
            self.swap_note.setText("Prioridade maior é usada primeiro. Swappiness define o quanto o kernel prefere "
                                   "mover memória para o swap em vez de descartar cache.")
