"""
Teste de velocidade de disco no estilo do CrystalDiskMark.

Cria um arquivo de teste (dados aleatórios, incompressíveis) na pasta escolhida e
mede leitura/escrita com O_DIRECT (sem cache do sistema):
  SEQ1M Q8T1, SEQ1M Q1T1, RND4K Q32T1, RND4K Q1T1
A "profundidade de fila" (Q) é simulada com várias threads de E/S simultâneas
(as chamadas de E/S do Python liberam o GIL). O arquivo é apagado no final.
"""
from __future__ import annotations

import mmap
import os
import random
import threading
import time

TESTS = [("SEQ1M Q8T1", 1 << 20, 8, True), ("SEQ1M Q1T1", 1 << 20, 1, True),
         ("RND4K Q32T1", 4096, 32, False), ("RND4K Q1T1", 4096, 1, False)]


class Bench:
    def __init__(self, folder, size_mb=1024, seconds=5.0, progress=None):
        self.folder = folder
        self.size = size_mb << 20
        self.seconds = seconds
        self.progress = progress or (lambda *a: None)
        self.cancel = False
        self.path = os.path.join(folder, f".hwscope-bench-{os.getpid()}.tmp")
        self.direct = hasattr(os, "O_DIRECT")

    def _open(self, write):
        flags = (os.O_RDWR if write else os.O_RDONLY)
        if self.direct:
            try:
                return os.open(self.path, flags | os.O_DIRECT)
            except OSError:
                self.direct = False
        return os.open(self.path, flags)

    def prepare(self):
        """Cria o arquivo de teste com dados aleatórios."""
        chunk = 1 << 20
        buf = mmap.mmap(-1, chunk)
        buf.write(os.urandom(chunk))
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.close(fd)
            fd = self._open(True)
            done = 0
            while done < self.size and not self.cancel:
                os.pwrite(fd, buf, done)
                done += chunk
                self.progress("prep", done / self.size)
            os.fsync(fd)
        finally:
            os.close(fd)
            buf.close()

    def _run(self, bs, qd, seq, write):
        nblocks = self.size // bs
        stop = time.perf_counter() + self.seconds
        counts = [0] * qd
        lat = [0.0] * qd
        errs = []
        pos = [0]
        lock = threading.Lock()

        def worker(k):
            fd = self._open(write)
            buf = mmap.mmap(-1, bs)
            buf.write(os.urandom(bs))
            mv = memoryview(buf)
            rnd = random.Random(k * 7919 + bs)
            n = 0
            tl = 0.0
            try:
                while time.perf_counter() < stop and not self.cancel:
                    if seq:
                        with lock:
                            off = (pos[0] % nblocks) * bs
                            pos[0] += 1
                    else:
                        off = rnd.randrange(nblocks) * bs
                    t = time.perf_counter()
                    if write:
                        os.pwrite(fd, mv, off)
                    else:
                        os.preadv(fd, [mv], off)
                    tl += time.perf_counter() - t
                    n += 1
                if write:
                    os.fsync(fd)
            except OSError as e:
                errs.append(str(e))
            finally:
                os.close(fd)
                mv.release()
                buf.close()
            counts[k] = n
            lat[k] = tl

        if not self.direct:
            try:
                fd = os.open(self.path, os.O_RDONLY)
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
                os.close(fd)
            except (OSError, AttributeError):
                pass
        t0 = time.perf_counter()
        ts = [threading.Thread(target=worker, args=(k,), daemon=True) for k in range(qd)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        el = time.perf_counter() - t0
        if errs:
            raise OSError(errs[0])
        ops = sum(counts)
        return {"mbs": ops * bs / el / 1e6, "iops": ops / el,
                "lat_us": (sum(lat) / ops * 1e6) if ops else None}

    def run(self, which=("read", "write")):
        res = {}
        try:
            self.prepare()
            total = len(TESTS) * len(which)
            k = 0
            for mode in which:
                for name, bs, qd, seq in TESTS:
                    if self.cancel:
                        return res
                    self.progress("test", k / total, name, mode)
                    r = self._run(bs, qd, seq, mode == "write")
                    res[(name, mode)] = r
                    k += 1
                    self.progress("result", k / total, name, mode, r)
                    time.sleep(0.5)
        finally:
            try:
                os.remove(self.path)
            except OSError:
                pass
        return res


def writable_targets(parts, home=None):
    """Lista de (rótulo, pasta) onde o usuário pode criar o arquivo de teste."""
    home = home or os.path.expanduser("~")
    out = []
    seen = set()
    try:
        hdev = os.stat(home).st_dev
    except OSError:
        hdev = None
    for blk, mounts in sorted(parts.items()):
        for m in mounts:
            mp = m["mount"]
            if m["fstype"] in ("vfat", "tmpfs", "squashfs", "iso9660", "overlay") and mp.startswith("/boot"):
                continue
            try:
                dev = os.stat(mp).st_dev
            except OSError:
                continue
            folder = None
            if os.access(mp, os.W_OK):
                folder = mp
            elif dev == hdev:
                folder = home
            else:
                for sub in ("home", "tmp", "var/tmp"):
                    p = os.path.join(mp, sub)
                    if os.path.isdir(p) and os.access(p, os.W_OK) and os.stat(p).st_dev == dev:
                        folder = p
                        break
            if folder and (dev, folder) not in seen:
                seen.add((dev, folder))
                free = m["total"] - m["used"] if m.get("total") and m.get("used") is not None else None
                out.append({"label": f"{blk} — {mp}", "folder": folder, "blk": blk, "free": free,
                            "fstype": m["fstype"]})
    if not out:
        out.append({"label": f"Pasta pessoal ({home})", "folder": home, "blk": "?", "free": None, "fstype": "?"})
    return out
