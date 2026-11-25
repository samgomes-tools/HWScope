"""
Verificação de superfície (somente leitura), no estilo do "Error Scan" do HD Tune
e do Victoria.

O disco é dividido em N células. Cada célula é lida em blocos de 1 MiB com O_DIRECT
(sem cache), medindo o tempo de cada bloco. Erros de leitura são refinados setor a
setor (4 KiB) para listar os LBAs ilegíveis. NADA é escrito no disco.

A leitura do dispositivo exige root: o código abaixo (HELPER) roda com o Python
do sistema via pkexec, recebendo o script pela entrada padrão, e devolve o
progresso em linhas de texto pela saída padrão.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

HELPER = r'''
import os, sys, time, mmap, random
dev, ncell, mode = sys.argv[1], int(sys.argv[2]), sys.argv[3]
fake = [tuple(int(x) for x in r.split("-")) for r in (sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else [])]
CH = 1 << 20
SEC = 4096
out = sys.stdout

def emit(*a):
    try:
        out.write(" ".join(str(x) for x in a) + "\n")
        out.flush()
    except (BrokenPipeError, OSError):
        os._exit(0)

flags = os.O_RDONLY
direct = getattr(os, "O_DIRECT", 0)
try:
    fd = os.open(dev, flags | direct)
except OSError:
    direct = 0
    fd = os.open(dev, flags)
size = os.lseek(fd, 0, os.SEEK_END)
emit("S", size, 1 if direct else 0)
buf = mmap.mmap(-1, CH)
mv = memoryview(buf)

def rd(off, n):
    for a, b in fake:
        if off < b and off + n > a:
            time.sleep(0.05)
            raise OSError(5, "I/O error (simulado)")
    if not direct:
        try:
            os.posix_fadvise(fd, off, n, os.POSIX_FADV_DONTNEED)
        except Exception:
            pass
    r = os.preadv(fd, [mv[:n]], off)
    if r < n:
        raise OSError(5, "leitura curta")

# tempo de acesso: leituras aleatórias de 4 KiB
times = []
for _ in range(40):
    off = random.randrange(0, max(size - SEC, 1)) // SEC * SEC
    t = time.perf_counter()
    try:
        rd(off, SEC)
    except OSError:
        continue
    times.append((time.perf_counter() - t) * 1000)
if times:
    times.sort()
    emit("A", "%.2f" % (sum(times) / len(times)), "%.2f" % times[len(times) // 2])

cell = max((size // ncell) // SEC * SEC, SEC)
LIM = (20, 50, 150, 500)
for i in range(ncell):
    start = i * cell
    if start >= size:
        break
    end = size if i == ncell - 1 else min(size, start + cell)
    if mode == "quick":
        end = min(end, start + 4 * CH)
    hist = [0, 0, 0, 0, 0]
    errs = 0
    worst = 0.0
    nbytes = 0
    t0 = time.perf_counter()
    off = start
    while off < end:
        n = min(CH, end - off)
        if n % 512:
            n -= n % 512
            if n == 0:
                break
        t = time.perf_counter()
        try:
            rd(off, n)
            dt = (time.perf_counter() - t) * 1000
            worst = max(worst, dt)
            k = 0
            while k < 4 and dt >= LIM[k]:
                k += 1
            hist[k] += 1
            nbytes += n
        except OSError:
            errs += 1
            # refina setor a setor para achar os LBAs ilegíveis
            s = off
            bad = 0
            while s < off + n:
                m = min(SEC, off + n - s)
                try:
                    rd(s, m)
                except OSError:
                    bad += 1
                    if bad <= 64:
                        emit("E", s // 512, m // 512)
                s += m
        off += n
    el = time.perf_counter() - t0
    emit("B", i, "%.1f" % worst, errs, nbytes, "%.4f" % el, *hist)
emit("D")
'''


def system_python():
    for p in ("/usr/bin/python3", "/bin/python3", "/usr/local/bin/python3"):
        if os.path.exists(p):
            return p
    return shutil.which("python3")


def start(dev, ncell=1000, mode="full", env=None, fake_bad=""):
    """Inicia a leitura. Usa o próprio usuário se tiver acesso ao dispositivo,
    senão pkexec + python3 do sistema. Devolve o Popen (saída em texto)."""
    args = [dev, str(ncell), mode, fake_bad]
    if os.access(dev, os.R_OK):
        cmd = [sys.executable, "-I", "-"] + args
    else:
        py = system_python()
        if not py:
            raise RuntimeError("python3 do sistema não encontrado (necessário para ler o disco como root).")
        if not shutil.which("pkexec"):
            raise RuntimeError("pkexec não encontrado (instale o polkit).")
        cmd = ["pkexec", py, "-I", "-"] + args
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, bufsize=1, env=env)
    p.stdin.write(HELPER)
    p.stdin.close()
    return p


# Classes de tempo por bloco de 1 MiB (como o Victoria)
CLASSES = [("< 20 ms", "#3fae6a"), ("< 50 ms", "#8fd16a"), ("< 150 ms", "#f5c542"),
           ("< 500 ms", "#ff8a3d"), ("≥ 500 ms", "#ff4d4d")]
ERR_COLOR = "#b0003a"
