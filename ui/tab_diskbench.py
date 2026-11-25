"""Discos → Teste de velocidade (estilo CrystalDiskMark)."""
from __future__ import annotations


from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from core import diskbench
from core.hwinfo import human_bytes
from ui.kit import message, set_kind
from ui.common import bar
from ui.theme import T


class DiskBenchWorker(QThread):
    progress = Signal(list)
    done = Signal(object, str)

    def __init__(self, folder, size_mb, seconds, which):
        super().__init__()
        self.b = diskbench.Bench(folder, size_mb, seconds, progress=lambda *a: self.progress.emit(list(a)))
        self.which = which

    def run(self):
        try:
            res = self.b.run(self.which)
            self.done.emit(res, "")
        except Exception as e:
            self.done.emit({}, str(e))


class DiskBenchTab(QWidget):
    """Teste de velocidade estilo CrystalDiskMark."""
    ROWS = [t[0] for t in diskbench.TESTS]

    def __init__(self):
        super().__init__()
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 8, 0, 0)
        L.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(QLabel("Local do teste:"))
        self.target = QComboBox()
        self.target.setMinimumWidth(300)
        top.addWidget(self.target)
        top.addWidget(QLabel("  Tamanho:"))
        self.size = QComboBox()
        self.size.addItems(["256 MiB", "1 GiB", "4 GiB"])
        self.size.setCurrentIndex(1)
        top.addWidget(self.size)
        top.addWidget(QLabel("  Duração:"))
        self.dur = QComboBox()
        self.dur.addItems(["3 s", "5 s", "10 s"])
        self.dur.setCurrentIndex(1)
        top.addWidget(self.dur)
        top.addWidget(QLabel("  Testar:"))
        self.which = QComboBox()
        self.which.addItems(["Leitura e escrita", "Só leitura", "Só escrita"])
        top.addWidget(self.which)
        top.addStretch()
        self.btn = QPushButton("▶ Iniciar")
        self.btn.setProperty("kind", "green")
        top.addWidget(self.btn)
        L.addLayout(top)
        note = QLabel("Cria um arquivo temporário com dados aleatórios na pasta escolhida (apagado ao final) e mede "
                      "leitura/escrita sem cache (O_DIRECT). Em SSDs, testes de escrita repetidos consomem um pouco "
                      "da vida útil. Q = requisições simultâneas, simuladas com threads.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        L.addWidget(note)
        self.tbl = QTableWidget(len(self.ROWS), 4)
        self.tbl.setHorizontalHeaderLabels(["Teste", "Leitura (MB/s)", "Escrita (MB/s)", "Detalhes"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl.setStyleSheet("QTableWidget{font-size:15px;}")
        for r, name in enumerate(self.ROWS):
            it = QTableWidgetItem(name)
            f = it.font()
            f.setBold(True)
            it.setFont(f)
            it.setForeground(QBrush(QColor(T.disk)))
            self.tbl.setItem(r, 0, it)
            for c in (1, 2, 3):
                x = QTableWidgetItem("—")
                x.setTextAlignment(Qt.AlignCenter)
                self.tbl.setItem(r, c, x)
            self.tbl.setRowHeight(r, 54)
        self.tbl.setFixedHeight(40 + 54 * len(self.ROWS))
        L.addWidget(self.tbl)
        self.bar = bar()
        self.bar.setFormat("pronto")
        L.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        L.addWidget(self.status)
        L.addStretch()
        self.targets = []
        self.worker = None
        self.results = {}
        self.btn.clicked.connect(self.toggle)

    def set_parts(self, parts):
        if self.targets or not parts:
            return
        self.targets = diskbench.writable_targets(parts)
        self.target.clear()
        for t in self.targets:
            free = f" · {human_bytes(t['free'], binary=False)} livres" if t["free"] else ""
            self.target.addItem(f"{t['label']}{free}")

    def toggle(self):
        if self.worker and self.worker.isRunning():
            self.worker.b.cancel = True
            self.btn.setEnabled(False)
            self.btn.setText("Parando…")
            return
        i = self.target.currentIndex()
        if not (0 <= i < len(self.targets)):
            return
        t = self.targets[i]
        size_mb = [256, 1024, 4096][self.size.currentIndex()]
        if t["free"] and t["free"] < size_mb * 1.1 * (1 << 20):
            message(self, "Espaço insuficiente", "Não há espaço livre suficiente para o arquivo de teste.", "warn")
            return
        which = [("read", "write"), ("read",), ("write",)][self.which.currentIndex()]
        for r in range(len(self.ROWS)):
            for c in (1, 2, 3):
                self.tbl.item(r, c).setText("—")
        self.results = {}
        self.worker = DiskBenchWorker(t["folder"], size_mb, [3.0, 5.0, 10.0][self.dur.currentIndex()], which)
        self.worker.progress.connect(self._prog)
        self.worker.done.connect(self._done)
        self.worker.start()
        self.btn.setText("■ Parar")
        set_kind(self.btn, "cancel")
        self.status.setText(f"Testando em {t['folder']} ({t['fstype']}).")

    def _prog(self, a):
        kind, frac = a[0], a[1]
        if kind == "prep":
            self.bar.setValue(int(frac * 1000))
            self.bar.setFormat(f"Criando arquivo de teste… {frac * 100:.0f} %")
        elif kind == "test":
            name, mode = a[2], a[3]
            self.bar.setValue(int(frac * 1000))
            self.bar.setFormat(f"{name} — {'leitura' if mode == 'read' else 'escrita'}…")
            r = self.ROWS.index(name)
            self.tbl.item(r, 1 if mode == "read" else 2).setText("…")
        elif kind == "result":
            name, mode, res = a[2], a[3], a[4]
            self.results[(name, mode)] = res
            r = self.ROWS.index(name)
            it = self.tbl.item(r, 1 if mode == "read" else 2)
            it.setText(f"{res['mbs']:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."))
            f = it.font()
            f.setPointSize(16)
            f.setBold(True)
            it.setFont(f)
            det = []
            for m in ("read", "write"):
                x = self.results.get((name, m))
                if x:
                    det.append(f"{'L' if m == 'read' else 'E'}: {x['iops']:,.0f} IOPS · {x['lat_us']:,.0f} µs".replace(",", "."))
            self.tbl.item(r, 3).setText("\n".join(det))
            self.bar.setValue(int(frac * 1000))

    def _done(self, res, err):
        self.btn.setEnabled(True)
        self.btn.setText("▶ Iniciar")
        set_kind(self.btn, "green")
        if err:
            self.bar.setFormat("erro")
            self.status.setText(f"Erro: {err}")
        else:
            self.bar.setValue(1000)
            self.bar.setFormat("concluído" if not self.worker.b.cancel else "interrompido")
            if not self.worker.b.direct:
                self.status.setText(self.status.text() + "  Aviso: o sistema de arquivos não aceita O_DIRECT; "
                                    "os resultados podem incluir cache.")

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.b.cancel = True
            self.worker.wait(15000)
