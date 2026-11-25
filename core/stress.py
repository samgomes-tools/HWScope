"""
Teste de estresse de CPU e RAM.

Roda num processo separado (a interface continua fluida) com uma thread por
núcleo lógico. A carga usa SHA-512 e compressão zlib em C, que liberam o GIL e
mantêm todos os núcleos a 100%. O modo RAM aloca uma parte da memória livre,
grava padrões aleatórios e confere cada bloco por hash, contando erros.

O processo envia uma linha por segundo:  T <operações> <passadas RAM> <erros RAM> <MB testados>
"""
from __future__ import annotations

import glob
import subprocess
import sys

WORKER = r'''
import sys, threading, time, hashlib, zlib, os
n = int(sys.argv[1]); mem_mb = int(sys.argv[2])
seed = os.urandom(1 << 20)
text = (b"HWScope stress " * 70000)[:1 << 20]
ops = [0] * n
stop = False

def cpu(i):
    h = hashlib.sha512
    c = zlib.compress
    a = seed[i * 997:] + seed[:i * 997]
    while not stop:
        h(a).digest()
        c(text, 6)
        ops[i] += 1

mem = {"passes": 0, "errors": 0, "mb": 0}
def ram():
    CH = 1 << 20
    blocks = []
    inv = bytes(255 - x for x in range(256))
    try:
        for _ in range(mem_mb):
            blocks.append(bytearray(seed))
    except MemoryError:
        pass
    mem["mb"] = len(blocks)
    expect = hashlib.sha256(seed).digest()
    expect_inv = hashlib.sha256(seed.translate(inv)).digest()
    flip = False
    while not stop:
        for b in blocks:
            if stop:
                return
            if hashlib.sha256(b).digest() != (expect_inv if flip else expect):
                mem["errors"] += 1
            b[:] = b.translate(inv)
        flip = not flip
        mem["passes"] += 1

ts = [threading.Thread(target=cpu, args=(i,), daemon=True) for i in range(n)]
if mem_mb > 0:
    ts.append(threading.Thread(target=ram, daemon=True))
for t in ts:
    t.start()
try:
    while True:
        time.sleep(1)
        sys.stdout.write("T %d %d %d %d\n" % (sum(ops), mem["passes"], mem["errors"], mem["mb"]))
        sys.stdout.flush()
except (BrokenPipeError, KeyboardInterrupt):
    stop = True
'''


def start(threads, mem_mb=0):
    return subprocess.Popen([sys.executable, "-I", "-c", WORKER, str(threads), str(mem_mb)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)


def throttle_count(root=""):
    """Eventos de limitação térmica (Intel: thermal_throttle). None se não houver."""
    tot, found = 0, False
    for f in glob.glob(root + "/sys/devices/system/cpu/cpu*/thermal_throttle/*_throttle_count"):
        try:
            with open(f) as fh:
                tot += int(fh.read().strip())
                found = True
        except (OSError, ValueError):
            pass
    return tot if found else None
