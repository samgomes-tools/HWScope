"""Modo administrador (processo root único) e leitura de potência RAPL."""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QThread, Signal

from core import hwinfo as hw
from core import spd, rootbroker


class AdminService(QObject):
    """Modo administrador: um processo root para todas as funções privilegiadas."""
    state = Signal()

    def __init__(self):
        super().__init__()
        self.client = rootbroker.Client(env=hw.clean_env(), on_state=self.state.emit)

    @property
    def active(self):
        return self.client.active

    @property
    def starting(self):
        return self.client.starting

    @property
    def error(self):
        return self.client.error

    def start(self):
        self.client.start()

    def stop(self):
        self.client.stop()


class AdminTaskWorker(QThread):
    """Executa, já como root, as leituras privilegiadas em sequência."""
    result = Signal(str, object)

    def __init__(self, admin, disks, mem_type, tasks=("modules", "dmidecode", "spd", "serials", "smart")):
        super().__init__()
        self.admin, self.disks, self.mem_type, self.tasks = admin, disks, mem_type, tasks

    def run(self):
        c = self.admin.client
        if "modules" in self.tasks:
            r = c.call("modules")
            self.result.emit("modules", r)
        if "dmidecode" in self.tasks:
            r = c.call("dmidecode")
            dimms = hw.parse_dmidecode_memory(r.get("out", "")) if r.get("rc") == 0 else None
            self.result.emit("dimms", {"dimms": dimms, "err": r.get("err")})
        if "spd" in self.tasks:
            r = c.call("spd", type=self.mem_type)
            mods, msg = spd.parse_priv_output(r.get("out", ""))
            if r.get("rc") not in (0, None) and not mods and r.get("err"):
                msg = r["err"]
            self.result.emit("spd", (mods, msg))
        if "serials" in self.tasks:
            r = c.call("serials")
            self.result.emit("serials", r.get("data") or {})
        if "smart" in self.tasks:
            for d in self.disks:
                r = c.call("smart", dev=d["dev"])
                if r.get("rc") == -1 and r.get("err"):
                    info = {"error": r["err"]}
                else:
                    info = hw.smart_from_output(r.get("out", ""), r.get("err", ""))
                self.result.emit("smart", (d["dev"], info))


class RaplService(QObject):
    """Lê a potência RAPL como root (pkexec) num processo auxiliar."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.zones = {z["path"]: z for z in hw.rapl_zones()}
        self.available = bool(self.zones)
        self.readable = hw.rapl_readable() if self.available else False
        self.active = False
        self.error = None
        self.latest = {}       # label -> watts
        self.package = None
        self._prev = {}
        self._proc = None
        self._reader = None

    _lineSig = Signal(str)
    _endSig = Signal(int)

    def start(self, admin):
        """Começa a ler via processo do modo administrador."""
        if self.active or not self.available or not admin.active:
            return
        try:
            self._lineSig.disconnect()
            self._endSig.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._lineSig.connect(self._line)
        self._endSig.connect(self._ended)
        self.error = None
        self._admin = admin
        self._rid = admin.client.stream("rapl", lambda t, m: self._lineSig.emit(m.get("data", "")) if t == "line"
                                        else self._endSig.emit(int(m.get("rc") or 0)))

    def _line(self, ln):
        if ln == "END":
            return
        try:
            path, val = ln.split(" ", 1)
            e = int(val)
        except ValueError:
            return
        now = time.monotonic()
        z = self.zones.get(path) or {"label": path, "name": path, "max_range": 0}
        prev = self._prev.get(path)
        self._prev[path] = (e, now)
        if not self.active:
            self.active = True
            self.changed.emit()
        if prev:
            e0, t0 = prev
            de = e - e0
            if de < 0 and z["max_range"]:
                de += z["max_range"]
            if de >= 0 and now > t0:
                w = de / 1e6 / (now - t0)
                self.latest[z["label"]] = w
                if z["name"].startswith("package"):
                    self.package = sum(v for k, v in self.latest.items() if k.startswith("Pacote"))

    def _ended(self, rc):
        was = self.active
        self.active = False
        if not was:
            self.error = "não foi possível ler o RAPL"
        self.changed.emit()

    def stop(self):
        if getattr(self, "_admin", None) and getattr(self, "_rid", None):
            self._admin.client.cancel(self._rid)

    def status_text(self):
        if not self.available:
            return "RAPL não disponível neste processador/kernel"
        if self.active:
            return "Lendo como administrador"
        if self.readable:
            return "Legível sem senha"
        if self.error:
            return f"Falhou: {self.error}"
        return "Requer “Modo administrador” (botão no topo)"


class _LineReader(QThread):
    line = Signal(str)
    ended = Signal(int)

    def __init__(self, proc):
        super().__init__()
        self.proc = proc

    def run(self):
        try:
            for ln in self.proc.stdout:
                self.line.emit(ln.strip())
        except Exception:
            pass
        self.ended.emit(self.proc.wait())
