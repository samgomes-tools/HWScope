"""
Modo administrador: um único processo auxiliar roda como root (uma senha, via
pkexec) e atende, pela sessão inteira, só as operações privilegiadas abaixo.
Ele não executa comandos arbitrários: cada operação é fixa e os argumentos são
validados. O processo termina sozinho quando o HWScope fecha (fim do stdin).

Protocolo: linhas JSON.
  app -> root : {"id": n, "op": "...", ...args}   |  {"op": "cancel", "target": n}
  root -> app : {"type": "ready"} | {"id": n, "type": "result", "data": {...}}
                | {"id": n, "type": "line", "data": "..."} | {"id": n, "type": "end", "rc": x}
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading

from . import spd as _spd
from . import surface as _surface

MODULES_SCRIPT = r"""
for m in drivetemp spd5118 jc42 ee1004 at24 i2c_dev coretemp k10temp nct6775 it87; do
  if err=$(modprobe "$m" 2>&1); then echo "OK $m"; else echo "FAIL $m $(echo "$err" | tail -1)"; fi
done
if dmesg 2>/dev/null | grep -iE "(nct6775|it87|0x2e|0x4e|0x290).*conflicts with|ACPI.*resource.*(nct|it87)" | grep -q .; then
  echo "ACPICONFLICT"
fi
sleep 0.5
PERSIST="drivetemp spd5118 ee1004"
for m in nct6775 it87; do
  # só mantém o driver da placa-mãe se ele realmente encontrou o chip de sensores
  if grep -qsE "^(nct|it8)" /sys/class/hwmon/*/name && lsmod | grep -q "^$m "; then
    n=$(cat /sys/class/hwmon/*/name 2>/dev/null | grep -E "^(nct|it8)" | head -1)
    case "$m:$n" in nct6775:nct*|it87:it8*) PERSIST="$PERSIST $m"; echo "BOARD $n" ;; esac
  fi
done
mkdir -p /etc/modules-load.d
{ echo "# Gerado pelo HWScope: sensores de temperatura e SPD"; for m in $PERSIST; do echo "$m"; done; } \
  > /etc/modules-load.d/hwscope-sensors.conf
"""

BROKER = r'''
import sys, os, json, threading, subprocess, re, time, glob, shutil
SURFACE = %(surface)r
SPD = %(spd)r
MODULES = %(modules)r
lock = threading.Lock()
jobs = {}

def send(o):
    with lock:
        try:
            sys.stdout.write(json.dumps(o) + "\n")
            sys.stdout.flush()
        except Exception:
            os._exit(0)

DEV_RE = re.compile(r"^/dev/(sd[a-z]{1,2}|nvme\d+n\d+|hd[a-z]|vd[a-z]{1,2}|xvd[a-z]{1,2}|mmcblk\d+)$")

def which(x):
    p = shutil.which(x)
    if p:
        return p
    for d in ("/usr/sbin", "/sbin", "/usr/bin", "/bin", "/usr/local/sbin"):
        if os.path.exists(os.path.join(d, x)):
            return os.path.join(d, x)
    return None

def run(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"rc": r.returncode, "out": r.stdout, "err": r.stderr[-2000:]}
    except Exception as e:
        return {"rc": -1, "out": "", "err": str(e)}

def op_modules(a):
    return run(["/bin/sh", "-c", MODULES], 120)

def op_dmidecode(a):
    exe = which("dmidecode")
    if not exe:
        return {"rc": -1, "out": "", "err": "dmidecode não instalado"}
    return run([exe, "-t", "17"], 60)

def op_smart(a):
    dev = a.get("dev", "")
    if not DEV_RE.match(dev):
        return {"rc": -1, "out": "", "err": "dispositivo inválido"}
    exe = which("smartctl")
    if not exe:
        return {"rc": -1, "out": "", "err": "smartctl não encontrado. Instale o pacote 'smartmontools'."}
    return run([exe, "-j", "-a", dev], 90)

def op_spd(a):
    t = a.get("type", "")
    if t not in ("DDR3", "DDR3L", "LPDDR3", "DDR4", "DDR5"):
        t = ""
    return run(["/bin/sh", "-c", SPD, "hwscope-spd", t], 180)

def op_serials(a):
    out = {}
    for n in ("board_serial", "product_serial", "chassis_serial", "product_uuid"):
        try:
            with open("/sys/class/dmi/id/" + n) as f:
                out[n] = f.read().strip()
        except OSError:
            pass
    return {"rc": 0, "data": out}

def stream_rapl(rid, a):
    files = sorted(glob.glob("/sys/class/powercap/intel-rapl:*/energy_uj"))
    while rid in jobs:
        for f in files:
            try:
                with open(f) as fh:
                    send({"id": rid, "type": "line", "data": f + " " + fh.read().strip()})
            except OSError:
                pass
        time.sleep(1)

def stream_surface(rid, a):
    dev = a.get("dev", "")
    try:
        n = int(a.get("ncell", 1000))
    except ValueError:
        n = 1000
    mode = a.get("mode", "quick")
    if not DEV_RE.match(dev) or not (1 <= n <= 20000) or mode not in ("quick", "full"):
        send({"id": rid, "type": "end", "rc": -1, "err": "parâmetros inválidos"})
        return
    p = subprocess.Popen([sys.executable, "-I", "-c", SURFACE, dev, str(n), mode, ""],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    jobs[rid] = p
    for ln in p.stdout:
        if rid not in jobs:
            break
        send({"id": rid, "type": "line", "data": ln.rstrip("\n")})
    try:
        p.terminate()
    except Exception:
        pass
    rc = p.wait()
    send({"id": rid, "type": "end", "rc": rc, "err": (p.stderr.read() or "")[-500:]})

CALLS = {"modules": op_modules, "dmidecode": op_dmidecode, "smart": op_smart, "spd": op_spd,
         "serials": op_serials}
STREAMS = {"rapl": stream_rapl, "surface": stream_surface}

def handle(msg):
    rid, op = msg.get("id"), msg.get("op")
    if op in CALLS:
        send({"id": rid, "type": "result", "data": CALLS[op](msg)})
    elif op in STREAMS:
        jobs.setdefault(rid, True)
        try:
            STREAMS[op](rid, msg)
        finally:
            jobs.pop(rid, None)
            send({"id": rid, "type": "end", "rc": 0})
    else:
        send({"id": rid, "type": "result", "data": {"rc": -1, "err": "operação desconhecida"}})

send({"type": "ready", "uid": os.getuid()})
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if msg.get("op") == "cancel":
        j = jobs.pop(msg.get("target"), None)
        if isinstance(j, subprocess.Popen):
            try:
                j.terminate()
            except Exception:
                pass
        continue
    threading.Thread(target=handle, args=(msg,), daemon=True).start()
for j in list(jobs.values()):
    if isinstance(j, subprocess.Popen):
        try:
            j.kill()
        except Exception:
            pass
os._exit(0)
'''


def broker_code():
    return BROKER % {"surface": _surface.HELPER, "spd": _spd.PRIV_SCRIPT, "modules": MODULES_SCRIPT}


class Client:
    """Cliente (sem Qt) do processo root. Callbacks rodam na thread leitora."""

    def __init__(self, env=None, on_state=None):
        self.env = env
        self.on_state = on_state or (lambda *a: None)
        self.proc = None
        self.active = False
        self.starting = False
        self.error = None
        self._id = 0
        self._lock = threading.Lock()
        self._waiters = {}
        self._streams = {}

    @staticmethod
    def system_python():
        for p in ("/usr/bin/python3", "/bin/python3", "/usr/local/bin/python3"):
            if os.path.exists(p):
                return p
        return shutil.which("python3")

    def start(self, cmd_prefix=("pkexec",)):
        if self.active or self.starting:
            return
        py = self.system_python()
        if not py:
            self.error = "python3 do sistema não encontrado"
            self.on_state()
            return
        if cmd_prefix and not shutil.which(cmd_prefix[0]):
            self.error = "pkexec não encontrado (instale o polkit)"
            self.on_state()
            return
        d = tempfile.mkdtemp(prefix="hwscope-")
        path = os.path.join(d, "broker.py")
        with open(path, "w") as f:
            f.write(broker_code())
        os.chmod(path, 0o600)
        self.starting = True
        self.error = None
        self.on_state()
        try:
            self.proc = subprocess.Popen(list(cmd_prefix) + [py, "-I", path], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                         bufsize=1, env=self.env)
        except OSError as e:
            self.starting = False
            self.error = str(e)
            self.on_state()
            return
        threading.Thread(target=self._reader, args=(path, d), daemon=True).start()

    def _reader(self, path, d):
        for ln in self.proc.stdout:
            try:
                m = json.loads(ln)
            except ValueError:
                continue
            t = m.get("type")
            if t == "ready":
                for x in (path,):
                    try:
                        os.remove(x)
                        os.rmdir(d)
                    except OSError:
                        pass
                self.active, self.starting = True, False
                self.on_state()
                continue
            rid = m.get("id")
            if t == "result":
                w = self._waiters.pop(rid, None)
                if w:
                    w[1].append(m.get("data"))
                    w[0].set()
            elif t in ("line", "end"):
                cb = self._streams.get(rid)
                if cb:
                    cb(t, m)
                if t == "end":
                    self._streams.pop(rid, None)
        rc = self.proc.wait()
        try:
            os.remove(path)
            os.rmdir(d)
        except OSError:
            pass
        was = self.active
        self.active = self.starting = False
        if not was:
            self.error = "autorização negada" if rc in (126, 127) else f"o processo terminou (código {rc})"
        for ev, box in list(self._waiters.values()):
            box.append({"rc": -1, "err": "modo administrador encerrado"})
            ev.set()
        self._waiters.clear()
        for cb in list(self._streams.values()):
            cb("end", {"rc": -1})
        self._streams.clear()
        self.on_state()

    def _send(self, msg):
        with self._lock:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()

    def _next(self):
        with self._lock:
            self._id += 1
            return self._id

    def call(self, op, timeout=200, **args):
        """Chamada síncrona (use fora da thread da interface)."""
        if not self.active:
            return {"rc": -1, "err": "modo administrador não está ativo"}
        rid = self._next()
        ev, box = threading.Event(), []
        self._waiters[rid] = (ev, box)
        try:
            self._send({"id": rid, "op": op, **args})
        except (OSError, ValueError):
            self._waiters.pop(rid, None)
            return {"rc": -1, "err": "falha de comunicação"}
        if not ev.wait(timeout):
            self._waiters.pop(rid, None)
            return {"rc": -1, "err": "tempo esgotado"}
        return box[0] if box else {"rc": -1, "err": "sem resposta"}

    def stream(self, op, callback, **args):
        if not self.active:
            return None
        rid = self._next()
        self._streams[rid] = callback
        try:
            self._send({"id": rid, "op": op, **args})
        except (OSError, ValueError):
            self._streams.pop(rid, None)
            return None
        return rid

    def stream_queue(self, op, **args):
        """Stream como fila (para threads de trabalho): itens ('line', texto) / ('end', rc)."""
        q = queue.Queue()

        def cb(t, m):
            q.put(("line", m.get("data")) if t == "line" else ("end", m.get("rc"), m.get("err")))
        rid = self.stream(op, cb, **args)
        return rid, q

    def cancel(self, rid):
        if self.active and rid:
            try:
                self._send({"op": "cancel", "target": rid})
            except (OSError, ValueError):
                pass

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
