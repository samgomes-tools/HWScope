"""Coleta periódica dos sensores numa thread separada."""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from core import hwinfo as hw
from core import spd, devices


class Collector(QObject):
    static_ready = Signal(object)
    dynamic_ready = Signal(object)

    def __init__(self):
        super().__init__()
        self.interval = 1000
        self._timer = None
        self._last_io = None
        self._last_t = None
        self._disks = []
        self._udisks = {}
        self._udisks_t = 0.0
        self._pm = None

    @Slot()
    def start(self):
        static = {}
        try:
            static["cpu"] = hw.cpu_static()
        except Exception as e:  # nunca derrubar a interface
            static["cpu"] = {"name": f"erro: {e}", "caches": {}, "instructions": []}
        static["system"] = hw.system_info()
        try:
            dimms, arr = hw.dimms_udev()
            if not dimms:
                dimms = hw.dimms_dmidecode(privileged=False)
        except Exception:
            dimms, arr = None, {}
        static["dimms"], static["mem_array"] = dimms, arr
        try:
            static["disks"] = hw.disks_static()
        except Exception:
            static["disks"] = []
        self._disks = static["disks"]
        try:
            static["chipset"] = hw.chipset_info()
        except Exception:
            static["chipset"] = {}
        try:
            static["spd"], static["spd_msg"] = spd.read_all(hw.ROOT, env=hw.clean_env())
        except Exception as e:
            static["spd"], static["spd_msg"] = [], str(e)
        static["memgen"] = hw.memory_general(dimms)
        self._pm = hw.PowerMeter()
        if hw.psutil:
            hw.psutil.cpu_percent(percpu=True)  # primeira chamada inicializa
        self.static_ready.emit(static)
        self._timer = QTimer()
        self._timer.timeout.connect(self.tick)
        self._timer.start(self.interval)
        QTimer.singleShot(150, self.tick)
        # Informações de OpenGL/Vulkan demoram — coletadas depois
        QTimer.singleShot(400, self._gl)

    def _gl(self):
        try:
            gl = hw.opengl_info()
        except Exception:
            gl = {}
        extra = {}
        try:
            for g in hw.gpus():
                extra[g["pci"]] = hw.gpu_static_extra(g, gl)
        except Exception as e:
            print("gpu extra:", e, file=sys.stderr)
        self.dynamic_ready.emit({"gl": gl, "gpu_extra": extra})

    @Slot()
    def stop(self):
        if self._timer:
            self._timer.stop()

    @Slot(int)
    def set_interval(self, ms):
        self.interval = ms
        if self._timer:
            self._timer.setInterval(ms)

    @Slot()
    def tick(self):
        d = {}
        try:
            d["chips"] = hw.read_hwmon()
        except Exception:
            d["chips"] = []
        try:
            d["cpu"] = hw.cpu_dynamic()
        except Exception:
            d["cpu"] = {}
        # Discos sem sensor hwmon: temperatura via UDisks2 (sem root), a cada 20 s
        now_w = time.time()
        if now_w - self._udisks_t > 20:
            self._udisks_t = now_w
            try:
                self._udisks, self._uhealth = hw.udisks_all()
            except Exception:
                self._udisks, self._uhealth = {}, {}
        d["udisks_temps"] = self._udisks
        d["disk_health"] = getattr(self, "_uhealth", {})
        have = {c["block"] for c in d["chips"] if c["kind"] == "disk" and c.get("block")}
        models = {x["name"]: x["model"] for x in self._disks}
        for blk, t in sorted(self._udisks.items()):
            if blk in have:
                continue
            d["chips"].append({"id": f"udisks-{blk}", "name": "udisks2", "kind": "disk",
                               "title": f"{models.get(blk, blk)} ({blk})", "block": blk, "pci": None,
                               "path": "UDisks2 (SMART)", "device": None,
                               "sensors": [{"type": "temp", "label": "Temperatura (via SMART/UDisks2)",
                                            "value": t, "unit": "°C", "max": None, "crit": None,
                                            "key": f"udisks/{blk}"}]})
        d["ram_temps"] = hw.ram_temps(d["chips"])
        d["vcore"], d["cpu_power"], d["vcore_src"] = hw.cpu_voltage_power(d["chips"])
        if self._pm:
            p = self._pm.read()
            if p is not None:
                d["cpu_power"] = p
        d["superio"] = hw.superio_name(d["chips"])
        now_d = time.time()
        if now_d - getattr(self, "_dev_t", 0) > 5:
            self._dev_t = now_d
            for key, fn in (("nets", devices.net_interfaces), ("net_glob", devices.net_globals),
                            ("usb", devices.usb_devices), ("audio", devices.audio)):
                try:
                    d[key] = fn()
                except Exception as e:
                    print(key, e, file=sys.stderr)
        try:
            d["net_ctr"] = devices.net_counters()
            d["bats"], d["ac"] = devices.batteries()
            d["fans"] = devices.fans(d["chips"])
        except Exception as e:
            print("devices", e, file=sys.stderr)
        try:
            d["swap"] = hw.swap_info()
        except Exception:
            d["swap"] = None
        d["cpu_temp"] = hw.pick_cpu_temp(d["chips"])
        d["core_temps"] = hw.core_temps(d["chips"])
        d["mem"] = hw.mem_dynamic()
        try:
            d["gpus"] = hw.gpus(d["chips"])
        except Exception:
            d["gpus"] = []
        d["parts"] = hw.partitions_usage()
        io = hw.disk_io()
        now = time.monotonic()
        rates = {}
        if self._last_io and self._last_t:
            dt = max(now - self._last_t, 1e-3)
            for k, (r, w) in io.items():
                if k in self._last_io:
                    r0, w0 = self._last_io[k]
                    rates[k] = (max(r - r0, 0) / dt, max(w - w0, 0) / dt)
        self._last_io, self._last_t = io, now
        d["io"] = rates
        d["uptime"] = time.time() - hw.psutil.boot_time() if hw.psutil else None
        self.dynamic_ready.emit(d)
