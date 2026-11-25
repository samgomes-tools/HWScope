"""Janela "Sobre": ícone, versão, recursos, dados do sistema e crédito."""
from __future__ import annotations

import os
import platform

from PySide6.QtCore import Qt, qVersion
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout

from ui.common import InfoGroup
from ui.meta import APP_NAME, APP_VERSION, HERE
from ui.kit import ScopeDialog

FEATURES = [
    "Temperaturas e uso de CPU, GPU, memória e discos",
    "Detalhes no estilo CPU-Z e GPU-Z, com SPD da memória",
    "Saúde dos discos (SMART), superfície e velocidade",
    "Teste de estresse, dispositivos e relatório",
]


def _distro():
    try:
        return platform.freedesktop_os_release().get("PRETTY_NAME") or "—"
    except OSError:
        return "—"


def _running_from():
    return os.environ.get("APPIMAGE") or os.path.join(HERE, "main.py")


class AboutDialog(ScopeDialog):
    def __init__(self, parent=None, admin_active=False):
        pm = QPixmap(os.path.join(HERE, "hwscope.png"))
        super().__init__(parent, f"Sobre o {APP_NAME}", f"Versão {APP_VERSION} · Monitor de hardware para Linux",
                         icon=pm if not pm.isNull() else None, width=500)
        lay = self.body

        # Recursos
        feats = QGroupBox("RECURSOS")
        fl = QVBoxLayout(feats)
        fl.setContentsMargins(12, 16, 12, 8)
        fl.setSpacing(3)
        for f in FEATURES:
            lb = QLabel(f"•&nbsp;&nbsp;{f}")
            lb.setTextFormat(Qt.RichText)
            lb.setObjectName("aboutItem")
            lb.setWordWrap(True)
            fl.addWidget(lb)
        lay.addWidget(feats)

        # Sistema
        self.sysbox = InfoGroup("SISTEMA")
        self.sysbox.grid.setContentsMargins(12, 16, 12, 8)
        self.sysbox.grid.setVerticalSpacing(4)
        for key in ("Distribuição", "Kernel", "Python / Qt", "Modo admin", "Executando"):
            self.sysbox.add(key).setObjectName("fieldSmall")
        f = self.sysbox.fields
        f["Distribuição"].setText(_distro())
        f["Kernel"].setText(platform.release())
        f["Python / Qt"].setText(f"{platform.python_version()} / Qt {qVersion()}")
        f["Modo admin"].setText("ativo" if admin_active else "desativado")
        path = _running_from()
        f["Executando"].setText(path)
        f["Executando"].setToolTip(path)
        lay.addWidget(self.sysbox)

        credit = QLabel("Desenvolvido por <b style='color:#ffffff'>Samuel Gomes</b>")
        credit.setAlignment(Qt.AlignCenter)
        credit.setObjectName("aboutCredit")
        lay.addWidget(credit)

        self.close_btn = self.add_button("FECHAR", "blue", self.accept)
        self.close_btn.setDefault(True)
        self.setFixedHeight(self.sizeHint().height())
