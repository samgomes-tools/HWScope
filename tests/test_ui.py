"""Teste de fumaça da interface: abre a janela no modo offscreen, percorre as abas,
e garante que nenhum erro aconteceu."""
import sys

import pytest

pytest.importorskip("PySide6")


def test_main_window_runs():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from ui import theme
    from ui.window import MainWindow

    errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda *a: errors.append(a)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    theme.apply_theme(app)
    w = MainWindow()
    w.resize(1240, 800)
    w.show()

    steps = []
    for i in range(w.tabs.count()):
        steps.append(lambda i=i: w.tabs.setCurrentIndex(i))

    def run(k=0):
        if k < len(steps):
            steps[k]()
            QTimer.singleShot(250, lambda: run(k + 1))
        else:
            app.quit()
    QTimer.singleShot(3000, run)
    app.exec()
    assert w.last, "o coletor não enviou dados"
    assert not hasattr(w, "theme_box"), "não deve haver seletor de tema"
    assert theme.T.name == "HWScope"
    assert "Vermeer" in w.cpu.proc.fields["Codinome"].text()
    w.shutdown()
    sys.excepthook = old_hook
    assert not errors, errors


def test_about_dialog(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from ui import theme
    from ui.about import AboutDialog

    monkeypatch.setenv("APPIMAGE", "/home/teste/HWScope-x86_64.AppImage")
    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app)
    d = AboutDialog(None, admin_active=True)
    f = d.sysbox.fields
    assert f["Executando"].text() == "/home/teste/HWScope-x86_64.AppImage"
    assert f["Modo admin"].text() == "ativo"
    assert f["Kernel"].text() not in ("", "—")
    d.close()
