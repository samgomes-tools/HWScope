"""Ponto de entrada da interface."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ui.meta import APP_NAME
from ui.theme import apply_theme
from ui.window import MainWindow


def main():
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("hwscope")
    app.setStyle("Fusion")
    apply_theme(app)
    w = MainWindow()
    app.aboutToQuit.connect(w.shutdown)
    w.show()
    if os.environ.get("HWSCOPE_SCREENSHOT"):
        # usado nos testes: salva capturas das abas e sai
        out = os.environ["HWSCOPE_SCREENSHOT"]

        def shoot(i=0):
            if i >= w.tabs.count():
                subs = [(w.gpu, w.gpu.sub, k, f"gpu{k}") for k in (1, 2)] + \
                       [(w.disks_tab, w.disks_tab.sub, k, f"disk{k}") for k in (1, 2)] + \
                       [(w.devices, w.devices.sub, k, f"dev{k}") for k in range(5)]
                j = i - w.tabs.count()
                if j < len(subs):
                    top_, sub_, k, nm = subs[j]
                    w.tabs.setCurrentWidget(top_)
                    sub_.setCurrentIndex(k)
                    QTimer.singleShot(400, lambda: (w.grab().save(f"{out}/{nm}.png"), shoot(i + 1)))
                    return
                app.quit()
                return
            w.tabs.setCurrentIndex(i)
            if os.environ.get("HWSCOPE_SHOT_DISK"):
                w.disk.list.setCurrentRow(int(os.environ["HWSCOPE_SHOT_DISK"]))
            QTimer.singleShot(400, lambda: (w.grab().save(f"{out}/tab{i}.png"), shoot(i + 1)))
        QTimer.singleShot(int(os.environ.get("HWSCOPE_SHOT_DELAY", "4000")), shoot)
    sys.exit(app.exec())
