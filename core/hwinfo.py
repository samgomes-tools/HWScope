"""
HWScope - coleta de informações de hardware no Linux.

Lê tudo a partir de /sys, /proc e de ferramentas opcionais (nvidia-smi,
udevadm, dmidecode, smartctl, glxinfo). Nada aqui depende de Qt, então o
módulo pode ser testado isoladamente.

A variável de ambiente HWSCOPE_ROOT permite apontar para uma árvore
/sys e /proc simulada (usada nos testes).
"""
from __future__ import annotations

import glob
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from . import cpudb
from . import gpudb

ROOT = os.environ.get("HWSCOPE_ROOT", "")


def P(path: str) -> str:
    """Prefixa caminhos absolutos com a raiz simulada (se houver)."""
    return ROOT + path if ROOT and path.startswith("/") else path


def rd(path: str, default=None):
    try:
        with open(path, "r", errors="replace") as f:
            return f.read().strip()
    except (OSError, ValueError):
        return default


def rd_int(path: str, default=None):
    v = rd(path)
    if v is None:
        return default
    try:
        return int(v.split()[0])
    except (ValueError, IndexError):
        return default


def clean_env():
    """Ambiente para programas externos, sem as variáveis internas do AppImage."""
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    if "HWSCOPE_ORIG_LD_LIBRARY_PATH" in env:
        orig = env.pop("HWSCOPE_ORIG_LD_LIBRARY_PATH")
        if orig:
            env["LD_LIBRARY_PATH"] = orig
        else:
            env.pop("LD_LIBRARY_PATH", None)
    for k in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "SSL_CERT_FILE", "TCL_LIBRARY",
              "TK_LIBRARY", "TKPATH"):
        if os.environ.get("APPDIR"):
            env.pop(k, None)
    return env


def run(cmd, timeout=4.0):
    """Executa um comando e devolve stdout, ou None se falhar."""
    exe = shutil.which(cmd[0])
    if not exe or ROOT:
        return None
    try:
        r = subprocess.run([exe] + list(cmd[1:]), capture_output=True, text=True,
                           timeout=timeout, env=clean_env())
        if r.returncode != 0:
            return None
        return r.stdout
    except (OSError, subprocess.SubprocessError):
        return None


def human_bytes(n, binary=True):
    if n is None:
        return "—"
    step = 1024.0 if binary else 1000.0
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"] if binary else \
            ["B", "KB", "MB", "GB", "TB", "PB"]
    n = float(n)
    for u in units:
        if abs(n) < step or u == units[-1]:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= step


# --------------------------------------------------------------------------
# pci.ids
# --------------------------------------------------------------------------
_PCI_DB = None


def _pci_db():
    global _PCI_DB
    if _PCI_DB is not None:
        return _PCI_DB
    vendors, devices, subs = {}, {}, {}
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cand in ("/usr/share/hwdata/pci.ids", "/usr/share/misc/pci.ids",
                 "/usr/share/pci.ids", os.path.join(here, "data", "pci.ids")):
        if os.path.exists(cand):
            try:
                cur_v = cur_d = None
                with open(cand, "r", errors="replace") as f:
                    for line in f:
                        if not line or line[0] == "#" or line.startswith("C "):
                            if line.startswith("C "):
                                break  # classes ficam no fim do arquivo
                            continue
                        if line[0] != "\t":
                            p = line.rstrip("\n").split("  ", 1)
                            if len(p) == 2:
                                cur_v = p[0].lower()
                                vendors[cur_v] = p[1].strip()
                        elif line[1] != "\t":
                            p = line.strip().split("  ", 1)
                            if len(p) == 2 and cur_v:
                                cur_d = p[0].lower()
                                devices[(cur_v, cur_d)] = p[1].strip()
                        else:
                            p = line.strip().split("  ", 1)
                            if len(p) == 2 and cur_v and cur_d:
                                sv_sd = p[0].lower().split()
                                if len(sv_sd) == 2:
                                    subs[(cur_v, cur_d, sv_sd[0], sv_sd[1])] = p[1].strip()
                break
            except OSError:
                continue
    _PCI_DB = (vendors, devices, subs)
    return _PCI_DB


def _hex(v):
    if not v:
        return None
    return v.lower().replace("0x", "")


def pci_names(vendor, device, svendor=None, sdevice=None):
    vendors, devices, subs = _pci_db()
    v, d, sv, sd = _hex(vendor), _hex(device), _hex(svendor), _hex(sdevice)
    return {
        "vendor": vendors.get(v),
        "device": devices.get((v, d)),
        "subvendor": vendors.get(sv) if sv else None,
        "subdevice": subs.get((v, d, sv, sd)) if sv and sd else None,
    }


VENDOR_SHORT = {"1002": "AMD", "1022": "AMD", "10de": "NVIDIA", "8086": "Intel", "1af4": "Virtio",
                "15ad": "VMware", "1234": "QEMU", "1b36": "Red Hat", "80ee": "VirtualBox",
                "1a03": "ASPEED", "102b": "Matrox", "5143": "Qualcomm", "14e4": "Broadcom"}


def pretty_device_name(name):
    """'Navi 21 [Radeon RX 6800/6800 XT / 6900 XT]' -> parte entre colchetes."""
    if not name:
        return name
    m = re.search(r"\[(.+)\]", name)
    return m.group(1) if m else name


# --------------------------------------------------------------------------
# Sistema / placa-mãe
# --------------------------------------------------------------------------
CHASSIS = {"1": "Outro", "2": "Desconhecido", "3": "Desktop", "4": "Desktop low-profile",
           "5": "Pizza box", "6": "Mini torre", "7": "Torre", "8": "Portátil",
           "9": "Laptop", "10": "Notebook", "11": "Handheld", "12": "Docking station",
           "13": "All-in-one", "14": "Sub-notebook", "15": "Compacto", "16": "Lunch box",
           "17": "Servidor", "23": "Servidor rack", "30": "Tablet", "31": "Conversível",
           "32": "Destacável", "35": "Mini PC", "36": "Stick PC"}


def system_info():
    dmi = P("/sys/class/dmi/id")

    def d(n):
        v = rd(os.path.join(dmi, n))
        if v and v.lower() in ("to be filled by o.e.m.", "default string", "not specified",
                                "system product name", "system manufacturer", "none", "0"):
            return v  # mantém, mas é genérico
        return v

    os_rel = {}
    txt = rd(P("/etc/os-release")) or rd(P("/usr/lib/os-release")) or ""
    for line in txt.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            os_rel[k] = v.strip().strip('"')

    boot = psutil.boot_time() if psutil else None
    up = time.time() - boot if boot else None

    return {
        "board": {
            "Fabricante": d("board_vendor"),
            "Modelo": d("board_name"),
            "Versão": d("board_version"),
            "Nº de série": d("board_serial"),
        },
        "bios": {
            "Fabricante": d("bios_vendor"),
            "Versão": d("bios_version"),
            "Data": d("bios_date"),
            "Revisão": d("bios_release"),
            "Modo de boot": "UEFI" if os.path.isdir(P("/sys/firmware/efi")) else "Legacy (BIOS)",
            "Secure Boot": _secure_boot(),
        },
        "system": {
            "Fabricante": d("sys_vendor"),
            "Produto": d("product_name"),
            "Versão": d("product_version"),
            "Família": d("product_family"),
            "SKU": d("product_sku"),
            "Chassi": CHASSIS.get(d("chassis_type") or "", d("chassis_type")),
        },
        "os": {
            "Distribuição": os_rel.get("PRETTY_NAME") or platform.platform(),
            "Kernel": platform.release(),
            "Arquitetura": platform.machine(),
            "Hostname": socket.gethostname(),
            "Ambiente gráfico": os.environ.get("XDG_CURRENT_DESKTOP") or
                                os.environ.get("DESKTOP_SESSION") or "—",
            "Sessão": os.environ.get("XDG_SESSION_TYPE", "—"),
            "Boot": time.strftime("%d/%m/%Y %H:%M", time.localtime(boot)) if boot else "—",
        },
        "uptime": up,
    }


def _secure_boot():
    for f in glob.glob(P("/sys/firmware/efi/efivars/SecureBoot-*")):
        try:
            with open(f, "rb") as fh:
                data = fh.read()
            return "Ativado" if data and data[-1] == 1 else "Desativado"
        except OSError:
            return "—"
    return "—"


def fmt_uptime(sec):
    if sec is None:
        return "—"
    sec = int(sec)
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m, _ = divmod(sec, 60)
    return (f"{d}d " if d else "") + f"{h:02d}h {m:02d}min"


# --------------------------------------------------------------------------
# CPU
# --------------------------------------------------------------------------
INSTR = [("mmx", "MMX"), ("sse", "SSE"), ("sse2", "SSE2"), ("pni", "SSE3"),
         ("ssse3", "SSSE3"), ("sse4_1", "SSE4.1"), ("sse4_2", "SSE4.2"), ("sse4a", "SSE4A"),
         ("lm", "x86-64"), ("aes", "AES"), ("avx", "AVX"), ("avx2", "AVX2"), ("fma", "FMA3"),
         ("avx512f", "AVX-512F"), ("avx512_bf16", "AVX-512 BF16"), ("avx_vnni", "AVX-VNNI"),
         ("amx_tile", "AMX"), ("sha_ni", "SHA"), ("bmi1", "BMI1"), ("bmi2", "BMI2"),
         ("adx", "ADX"), ("f16c", "F16C"), ("popcnt", "POPCNT"), ("rdrand", "RDRAND"),
         ("vmx", "VT-x"), ("svm", "AMD-V"), ("ht", "HT"), ("nx", "NX"),
         ("constant_tsc", "Invariant TSC")]

AMD_FAMILY = {0x15: "Bulldozer/Piledriver", 0x16: "Jaguar/Puma", 0x17: "Zen / Zen+ / Zen 2",
              0x18: "Hygon Dhyana", 0x19: "Zen 3 / Zen 4", 0x1A: "Zen 5"}


def _amd_uarch(fam, model):
    try:
        m = int(model)
    except (TypeError, ValueError):
        m = None
    if fam == 0x17 and m is not None:
        if m in (0x08, 0x18):
            return "Zen+"
        return "Zen 2" if m >= 0x30 else "Zen"
    if fam == 0x19 and m is not None:
        if m < 0x10 or 0x20 <= m < 0x60:
            return "Zen 3" if m not in (0x40, 0x44) else "Zen 3+"
        return "Zen 4"
    return AMD_FAMILY.get(fam)


def _parse_cpulist(s):
    out = set()
    for part in (s or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def cpu_static():
    txt = rd(P("/proc/cpuinfo")) or ""
    procs, cur = [], {}
    for line in txt.splitlines():
        if not line.strip():
            if cur:
                procs.append(cur)
                cur = {}
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            cur[k.strip()] = v.strip()
    if cur:
        procs.append(cur)
    p0 = procs[0] if procs else {}

    sockets = {p.get("physical id", "0") for p in procs} or {"0"}
    cores = {(p.get("physical id", "0"), p.get("core id", str(i))) for i, p in enumerate(procs)}
    if procs and "core id" in p0:
        threads, ncores = len(procs), len(cores)
    elif psutil:
        threads = psutil.cpu_count(logical=True) or len(procs)
        ncores = psutil.cpu_count(logical=False) or threads
    else:
        threads = ncores = len(procs)

    flags = set((p0.get("flags") or p0.get("Features") or "").split())
    instr = [name for f, name in INSTR if f in flags]

    vendor_raw = p0.get("vendor_id", "")
    vendor = {"AuthenticAMD": "AMD", "GenuineIntel": "Intel", "HygonGenuine": "Hygon"}.get(
        vendor_raw, vendor_raw or p0.get("CPU implementer", "—"))
    name = p0.get("model name") or p0.get("Model") or p0.get("Hardware") or platform.processor()
    name = re.sub(r"\s+", " ", name or "—")

    fam = p0.get("cpu family")
    fam_i = int(fam) if fam and fam.isdigit() else None
    arch_name = _amd_uarch(fam_i, p0.get("model")) if vendor == "AMD" and fam_i else None

    # cache (lida de cpu0 e multiplicada pelo nº de grupos que a compartilham)
    caches = {}
    seen = {}
    for idx in sorted(glob.glob(P("/sys/devices/system/cpu/cpu[0-9]*/cache/index[0-9]*"))):
        lvl = rd(os.path.join(idx, "level"))
        typ = rd(os.path.join(idx, "type"))
        size = rd(os.path.join(idx, "size"))
        shared = rd(os.path.join(idx, "shared_cpu_list"))
        ways = rd(os.path.join(idx, "ways_of_associativity"))
        if not lvl or not size:
            continue
        key = f"L{lvl}" + ({"Data": "d", "Instruction": "i"}.get(typ, ""))
        kb = _size_kb(size)
        seen.setdefault(key, {"groups": set(), "each": kb, "ways": ways, "level": lvl, "type": typ,
                              "line": rd(os.path.join(idx, "coherency_line_size")),
                              "sets": rd(os.path.join(idx, "number_of_sets")),
                              "per": len(_parse_cpulist(shared)) if shared else None})
        seen[key]["groups"].add(shared)
    for key, info in seen.items():
        n = len(info["groups"])
        total = info["each"] * n
        txt = f"{n} × {_fmt_kb(info['each'])}" if n > 1 else _fmt_kb(info["each"])
        if n > 1:
            txt += f"  ({_fmt_kb(total)})"
        if info["ways"]:
            txt += f"  · {info['ways']}-way"
        caches[key] = txt
    cache_detail = []
    for key in sorted(seen, key=lambda k: (int(seen[k]["level"]), k)):
        info = seen[key]
        cache_detail.append({"name": key, "level": info["level"],
                             "type": {"Data": "Dados", "Instruction": "Instruções", "Unified": "Unificado"}.get(info["type"], info["type"]),
                             "size": _fmt_kb(info["each"]), "count": len(info["groups"]),
                             "total": _fmt_kb(info["each"] * len(info["groups"])),
                             "ways": info["ways"], "line": info["line"], "sets": info["sets"],
                             "shared": info["per"]})
    if not caches and p0.get("cache size"):
        caches["L2/L3"] = p0["cache size"]

    cf = P("/sys/devices/system/cpu/cpu0/cpufreq")
    fmin = rd_int(os.path.join(cf, "cpuinfo_min_freq"))
    fmax = rd_int(os.path.join(cf, "cpuinfo_max_freq"))
    if fmax is None and psutil:
        try:
            fr = psutil.cpu_freq()
            if fr:
                fmin, fmax = int(fr.min * 1000) or None, int(fr.max * 1000) or None
        except Exception:
            pass
    boost = rd(P("/sys/devices/system/cpu/cpufreq/boost"))
    if boost is None:
        nt = rd(P("/sys/devices/system/cpu/intel_pstate/no_turbo"))
        boost = None if nt is None else ("0" if nt == "1" else "1")

    vuln = []
    for f in sorted(glob.glob(P("/sys/devices/system/cpu/vulnerabilities/*"))):
        st = rd(f, "")
        if st.startswith("Vulnerable"):
            vuln.append(os.path.basename(f))

    return {
        "name": name,
        "vendor": vendor,
        "vendor_raw": vendor_raw,
        "arch": platform.machine(),
        "microarch": arch_name,
        "family": fam,
        "model": p0.get("model"),
        "stepping": p0.get("stepping"),
        "microcode": p0.get("microcode"),
        "sockets": len(sockets),
        "cores": ncores,
        "threads": threads,
        "caches": caches,
        "instructions": instr,
        "min_mhz": fmin // 1000 if fmin else None,
        "max_mhz": fmax // 1000 if fmax else None,
        "driver": rd(os.path.join(cf, "scaling_driver")),
        "governor": rd(os.path.join(cf, "scaling_governor")),
        "epp": rd(os.path.join(cf, "energy_performance_preference")),
        "boost": {"1": "Ativado", "0": "Desativado"}.get(boost or "", "—"),
        "bogomips": p0.get("bogomips") or p0.get("BogoMIPS"),
        "vulnerable": vuln,
        "cache_detail": cache_detail,
        "l3_groups": len(seen.get("L3", {}).get("groups", ())) or None,
        "hybrid": _hybrid(),
        "tdp": _rapl_limits(),
        "db": cpudb.lookup(vendor, fam, p0.get("model"), p0.get("stepping"), name),
        "cpuid": cpudb.cpuid_fields(fam, p0.get("model"), p0.get("stepping")),
        "flags_all": sorted(flags),
        "virtualization": "VT-x" if "vmx" in flags else ("AMD-V" if "svm" in flags else "—"),
        "hypervisor": "hypervisor" in flags,
    }


def _size_kb(s):
    s = s.strip().upper()
    m = re.match(r"(\d+)\s*([KMG]?)", s)
    if not m:
        return 0
    n = int(m.group(1))
    return n * {"": 1, "K": 1, "M": 1024, "G": 1024 * 1024}[m.group(2)]


def _fmt_kb(kb):
    if kb >= 1024 and kb % 1024 == 0:
        return f"{kb // 1024} MB"
    if kb >= 1024:
        return f"{kb / 1024:.1f} MB"
    return f"{kb} KB"


def cpu_dynamic():
    freqs = []
    for c in sorted(glob.glob(P("/sys/devices/system/cpu/cpu[0-9]*")),
                    key=lambda x: int(re.sub(r"\D", "", os.path.basename(x)) or 0)):
        f = rd_int(os.path.join(c, "cpufreq/scaling_cur_freq"))
        if f is not None:
            freqs.append(f / 1000.0)
    if not freqs and psutil:
        try:
            fr = psutil.cpu_freq(percpu=True) or []
            freqs = [x.current for x in fr]
        except Exception:
            freqs = []
    if not freqs:
        # /proc/cpuinfo "cpu MHz"
        for line in (rd(P("/proc/cpuinfo")) or "").splitlines():
            if line.startswith("cpu MHz"):
                try:
                    freqs.append(float(line.split(":")[1]))
                except ValueError:
                    pass
    usage = psutil.cpu_percent(percpu=True) if psutil else []
    total = sum(usage) / len(usage) if usage else None
    load = os.getloadavg() if hasattr(os, "getloadavg") else None
    return {"freqs": freqs, "usage": usage, "total": total, "load": load}


# --------------------------------------------------------------------------
# Sensores (hwmon)
# --------------------------------------------------------------------------
CPU_CHIPS = {"k10temp", "coretemp", "zenpower", "k8temp", "cpu_thermal", "fam15h_power",
             "via_cputemp", "x86_pkg_temp", "soc_thermal", "cpu"}
GPU_CHIPS = {"amdgpu", "radeon", "nouveau", "i915", "xe", "nvidia"}
DISK_CHIPS = {"nvme", "drivetemp"}
BOARD_PREFIX = ("nct", "it8", "f71", "w83", "asus", "acpitz", "thinkpad", "dell", "hp",
                "pch_", "lm", "gigabyte", "asrock", "msi", "ec_", "applesmc")

KIND_LABEL = {"cpu": "Processador", "gpu": "Placa de vídeo", "disk": "Armazenamento",
              "board": "Placa-mãe / ACPI", "mem": "Memória", "other": "Outros"}

SENSOR_TYPES = {
    "temp": ("°C", 1000.0),
    "fan": ("RPM", 1.0),
    "in": ("V", 1000.0),
    "curr": ("A", 1000.0),
    "power": ("W", 1_000_000.0),
    "freq": ("MHz", 1_000_000.0),
    "energy": ("J", 1_000_000.0),
    "pwm": ("%", 2.55),
}


def _chip_kind(name):
    if name in CPU_CHIPS:
        return "cpu"
    if name in GPU_CHIPS:
        return "gpu"
    if name in DISK_CHIPS:
        return "disk"
    if name.startswith(("spd5118", "jc42", "ee1004")):
        return "mem"
    if name.startswith(BOARD_PREFIX):
        return "board"
    return "other"


def _resolve_device(hw):
    dev = os.path.join(hw, "device")
    try:
        return os.path.realpath(dev) if os.path.exists(dev) else None
    except OSError:
        return None


def _disk_model_for_hwmon(name, devpath):
    """Tenta achar o nome do bloco (nvme0n1/sda) e o modelo do disco."""
    if not devpath:
        return None, None
    if name == "nvme":
        # devpath: .../nvme/nvme0  (ou o PCI device em kernels antigos)
        ctrl = None
        if re.search(r"/nvme\d+$", devpath):
            ctrl = devpath
        else:
            cands = glob.glob(os.path.join(devpath, "nvme", "nvme*"))
            ctrl = cands[0] if cands else None
        if ctrl:
            model = rd(os.path.join(ctrl, "model"))
            base = os.path.basename(ctrl)
            blocks = sorted(glob.glob(os.path.join(ctrl, base + "n*")))
            blk = os.path.basename(blocks[0]) if blocks else base + "n1"
            return blk, model
    if name == "drivetemp":
        model = rd(os.path.join(devpath, "model"))
        b = glob.glob(os.path.join(devpath, "block", "*"))
        return (os.path.basename(b[0]) if b else None), model
    return None, None


def read_hwmon():
    chips = []
    for hw in sorted(glob.glob(P("/sys/class/hwmon/hwmon*")),
                     key=lambda x: int(re.sub(r"\D", "", os.path.basename(x)) or 0)):
        name = rd(os.path.join(hw, "name"), os.path.basename(hw))
        devpath = _resolve_device(hw)
        kind = _chip_kind(name)
        chip = {"id": os.path.basename(hw), "name": name, "kind": kind, "path": hw,
                "device": devpath, "sensors": [], "title": name, "block": None, "pci": None}
        if kind == "disk":
            blk, model = _disk_model_for_hwmon(name, devpath)
            chip["block"] = blk
            if model:
                chip["title"] = f"{model}" + (f" ({blk})" if blk else "")
        elif kind == "gpu" and devpath:
            chip["pci"] = os.path.basename(devpath)
            n = pci_names(rd(os.path.join(devpath, "vendor")), rd(os.path.join(devpath, "device")))
            if n["device"]:
                chip["title"] = pretty_device_name(n["device"])

        try:
            files = os.listdir(hw)
        except OSError:
            files = []
        idxs = {}
        for f in files:
            m = re.match(r"^(temp|fan|in|curr|power|freq|energy)(\d+)_(input|average)$", f)
            if m:
                idxs.setdefault((m.group(1), int(m.group(2))), f)
        for (typ, i), fname in sorted(idxs.items(), key=lambda x: (list(SENSOR_TYPES).index(x[0][0]), x[0][1])):
            unit, div = SENSOR_TYPES[typ]
            raw = rd_int(os.path.join(hw, fname))
            if raw is None:
                continue
            label = rd(os.path.join(hw, f"{typ}{i}_label")) or f"{typ}{i}"
            val = raw / div
            if typ == "temp" and (val <= -100 or val >= 250):
                continue  # leituras inválidas
            mx = rd_int(os.path.join(hw, f"{typ}{i}_max"))
            crit = rd_int(os.path.join(hw, f"{typ}{i}_crit"))
            chip["sensors"].append({
                "type": typ, "label": label, "value": val, "unit": unit,
                "max": mx / div if mx not in (None, 0) else None,
                "crit": crit / div if crit not in (None, 0) else None,
                "key": f"{chip['id']}/{typ}{i}",
            })
        if chip["sensors"]:
            if kind == "mem":
                n = sum(1 for c in chips if c["kind"] == "mem") + 1
                chip["title"] = f"Pente {n} ({name})"
                for s_ in chip["sensors"]:
                    if s_["label"] == "temp1":
                        s_["label"] = "Temperatura"
            chips.append(chip)

    # thermal zones que não aparecem no hwmon (ex.: x86_pkg_temp)
    have = {c["name"] for c in chips}
    tz_sensors = []
    for tz in sorted(glob.glob(P("/sys/class/thermal/thermal_zone*"))):
        typ = rd(os.path.join(tz, "type"))
        t = rd_int(os.path.join(tz, "temp"))
        if typ is None or t is None or typ in have or typ == "acpitz" and "acpitz" in have:
            continue
        if t <= 0 or t > 250000:
            continue
        tz_sensors.append({"type": "temp", "label": typ, "value": t / 1000.0, "unit": "°C",
                           "max": None, "crit": None, "key": f"tz/{os.path.basename(tz)}"})
    if tz_sensors:
        k = "cpu" if any(s["label"] in ("x86_pkg_temp", "cpu-thermal", "cpu_thermal") for s in tz_sensors) else "board"
        chips.append({"id": "thermal", "name": "thermal_zone", "kind": k,
                      "path": P("/sys/class/thermal"), "device": None, "title": "Zonas térmicas",
                      "sensors": tz_sensors, "block": None, "pci": None})
    return chips


def pick_cpu_temp(chips):
    pref = [("k10temp", ("Tctl", "Tdie")), ("zenpower", ("Tdie", "Tctl")),
            ("coretemp", ("Package id 0", "Physical id 0")), ("cpu_thermal", ()),
            ("x86_pkg_temp", ())]
    for chip_name, labels in pref:
        for c in chips:
            if c["name"] != chip_name:
                continue
            temps = [s for s in c["sensors"] if s["type"] == "temp"]
            for lab in labels:
                for s in temps:
                    if s["label"] == lab:
                        return s["value"]
            if temps:
                return max(s["value"] for s in temps)
    for c in chips:
        for s in c["sensors"]:
            if s["type"] == "temp" and s["label"] in ("x86_pkg_temp", "cpu-thermal", "cpu_thermal"):
                return s["value"]
    for c in chips:
        if c["name"] == "acpitz":
            t = [s["value"] for s in c["sensors"] if s["type"] == "temp"]
            if t:
                return t[0]
    return None


def core_temps(chips):
    """Temperaturas por núcleo (Intel coretemp: 'Core N'; AMD: Tccd)."""
    out = []
    for c in chips:
        if c["name"] in ("coretemp", "k10temp", "zenpower"):
            for s in c["sensors"]:
                if s["type"] == "temp" and (s["label"].startswith("Core") or s["label"].startswith("Tccd")):
                    out.append((s["label"], s["value"]))
    return out


# --------------------------------------------------------------------------
# Memória
# --------------------------------------------------------------------------
def mem_dynamic():
    if not psutil:
        return {}
    v = psutil.virtual_memory()
    s = psutil.swap_memory()
    return {"total": v.total, "used": v.total - v.available, "available": v.available,
            "percent": v.percent, "cached": getattr(v, "cached", 0) + getattr(v, "buffers", 0),
            "shared": getattr(v, "shared", 0),
            "swap_total": s.total, "swap_used": s.used, "swap_percent": s.percent}


def dimms_udev():
    """systemd >= 248 expõe os dados SMBIOS de memória via udev sem root."""
    out = run(["udevadm", "info", "--query=property", "--path=/sys/devices/virtual/dmi/id"])
    if not out:
        return None, {}
    props = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    dev = {}
    for k, v in props.items():
        m = re.match(r"MEMORY_DEVICE_(\d+)_(.+)", k)
        if m:
            dev.setdefault(int(m.group(1)), {})[m.group(2)] = v
    arr = {
        "slots": props.get("MEMORY_ARRAY_NUM_DEVICES"),
        "max": props.get("MEMORY_ARRAY_MAX_CAPACITY"),
        "ecc": props.get("MEMORY_ARRAY_EC_TYPE"),
    }
    if not dev:
        return None, arr
    result = []
    for i in sorted(dev):
        d = dev[i]
        size = d.get("SIZE")
        present = d.get("PRESENT", "1" if size and size != "0" else "0") != "0" and size not in (None, "0")
        result.append({
            "slot": d.get("LOCATOR") or f"Slot {i}",
            "bank": d.get("BANK_LOCATOR"),
            "present": present,
            "size": int(size) if size and size.isdigit() else None,
            "type": d.get("TYPE"),
            "form": d.get("FORM_FACTOR"),
            "speed": d.get("SPEED_MTS"),
            "configured": d.get("CONFIGURED_SPEED_MTS"),
            "manufacturer": d.get("MANUFACTURER"),
            "part": (d.get("PART_NUMBER") or "").strip(),
            "serial": d.get("SERIAL_NUMBER"),
            "rank": d.get("RANK"),
            "voltage": d.get("CONFIGURED_VOLTAGE"),
            "width": d.get("DATA_WIDTH"),
        })
    return result, arr


def parse_dmidecode_memory(txt):
    result = []
    for block in txt.split("\n\n"):
        if "Memory Device" not in block:
            continue
        d = {}
        for line in block.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                d[k.strip()] = v.strip()
        size = d.get("Size", "")
        present = not size.startswith("No Module") and size not in ("", "Unknown")
        nbytes = None
        m = re.match(r"(\d+)\s*(MB|GB|TB|kB)", size)
        if m:
            nbytes = int(m.group(1)) * {"kB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}[m.group(2)]

        def num(x):
            mm = re.match(r"(\d+)", x or "")
            return mm.group(1) if mm else None
        volt = d.get("Configured Voltage", "")
        vm = re.match(r"([\d.]+)", volt)
        result.append({
            "slot": d.get("Locator"), "bank": d.get("Bank Locator"), "present": present,
            "size": nbytes, "type": d.get("Type"), "form": d.get("Form Factor"),
            "speed": num(d.get("Speed")), "configured": num(d.get("Configured Memory Speed") or d.get("Configured Clock Speed")),
            "manufacturer": d.get("Manufacturer"), "part": d.get("Part Number"),
            "serial": d.get("Serial Number"), "rank": d.get("Rank"),
            "voltage": str(int(float(vm.group(1)) * 1000)) if vm else None,
            "width": num(d.get("Data Width")),
        })
    return result


def dimms_dmidecode(privileged=False):
    cmd = ["dmidecode", "-t", "17"]
    if privileged:
        if not shutil.which("pkexec"):
            return None
        exe = shutil.which("dmidecode") or "/usr/sbin/dmidecode"
        out = run(["pkexec", exe, "-t", "17"], timeout=60)
    else:
        out = run(cmd)
    if not out:
        return None
    return parse_dmidecode_memory(out)


# --------------------------------------------------------------------------
# GPU
# --------------------------------------------------------------------------
NV_FIELDS = ["index", "name", "driver_version", "pci.bus_id", "temperature.gpu",
             "utilization.gpu", "utilization.memory", "memory.total", "memory.used",
             "clocks.gr", "clocks.mem", "clocks.max.gr", "clocks.max.mem", "power.draw",
             "power.limit", "fan.speed", "pcie.link.gen.current", "pcie.link.gen.max",
             "pcie.link.width.current", "pcie.link.width.max", "vbios_version",
             "clocks.sm", "pstate"]


def nvidia_smi():
    out = run(["nvidia-smi", "--query-gpu=" + ",".join(NV_FIELDS),
               "--format=csv,noheader,nounits"], timeout=3)
    res = {}
    if not out:
        return res
    for line in out.strip().splitlines():
        vals = [v.strip() for v in line.split(",")]
        if len(vals) != len(NV_FIELDS):
            continue
        d = {}
        for k, v in zip(NV_FIELDS, vals):
            d[k] = None if v in ("[N/A]", "N/A", "[Not Supported]", "") else v
        bus = (d.get("pci.bus_id") or "").lower()
        # 00000000:01:00.0 -> 0000:01:00.0
        if bus.count(":") == 2 and len(bus.split(":")[0]) == 8:
            bus = bus[4:]
        res[bus] = d
    return res


def _fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dpm_current(path):
    txt = rd(path)
    if not txt:
        return None
    for line in txt.splitlines():
        if "*" in line:
            m = re.search(r"(\d+)\s*Mhz", line, re.I)
            if m:
                return int(m.group(1))
    return None


def _dpm_max(path):
    txt = rd(path)
    if not txt:
        return None
    vals = [int(m) for m in re.findall(r"(\d+)\s*Mhz", txt, re.I)]
    return max(vals) if vals else None


_GL_CACHE = {}


def opengl_info():
    if "v" in _GL_CACHE:
        return _GL_CACHE["v"]
    info = {}
    out = run(["glxinfo", "-B"], timeout=5)
    if out:
        for line in out.splitlines():
            line = line.strip()
            for key, name in (("OpenGL renderer string:", "renderer"),
                              ("OpenGL core profile version string:", "gl_core"),
                              ("OpenGL version string:", "gl"),
                              ("OpenGL vendor string:", "gl_vendor")):
                if line.startswith(key):
                    info[name] = line[len(key):].strip()
    vk = run(["vulkaninfo", "--summary"], timeout=6)
    if vk:
        m = re.search(r"Vulkan Instance Version:\s*(\S+)", vk)
        if m:
            info["vulkan"] = m.group(1)
        info["vk_devices"] = re.findall(r"deviceName\s*=\s*(.+)", vk)
        info["vk_api"] = re.findall(r"apiVersion\s*=\s*(\S+)", vk)
    _GL_CACHE["v"] = info
    return info


def _link(pci, attr):
    return rd(os.path.join(pci, attr))


def _pcie_gen(speed):
    if not speed:
        return None
    m = re.match(r"([\d.]+)\s*GT/s", speed)
    if not m:
        return speed
    gen = {"2.5": 1, "5.0": 2, "5": 2, "8.0": 3, "8": 3, "16.0": 4, "16": 4, "32.0": 5, "32": 5, "64.0": 6, "64": 6}.get(m.group(1))
    return f"PCIe {gen}.0 ({speed.split(' PCIe')[0]})" if gen else speed


def gpus(hwmon_chips=None):
    nv = nvidia_smi()
    nvx = nvidia_smi_extra() if nv else {}
    seen_pci = set()
    result = []
    cards = sorted(glob.glob(P("/sys/class/drm/card[0-9]*")))
    for card in cards:
        if "-" in os.path.basename(card):
            continue
        dev = os.path.join(card, "device")
        if not os.path.exists(os.path.join(dev, "vendor")):
            continue
        pci = os.path.realpath(dev)
        addr = os.path.basename(pci)
        if addr in seen_pci:
            continue
        seen_pci.add(addr)
        vid, did = rd(os.path.join(dev, "vendor")), rd(os.path.join(dev, "device"))
        svid, sdid = rd(os.path.join(dev, "subsystem_vendor")), rd(os.path.join(dev, "subsystem_device"))
        names = pci_names(vid, did, svid, sdid)
        drv_link = os.path.join(dev, "driver")
        driver = os.path.basename(os.path.realpath(drv_link)) if os.path.exists(drv_link) else None
        vshort = VENDOR_SHORT.get(_hex(vid) or "", names["vendor"] or vid)
        g = {
            "card": os.path.basename(card),
            "pci": addr,
            "vendor": vshort,
            "vendor_full": names["vendor"],
            "name": pretty_device_name(names["device"]) or f"{vshort} GPU [{_hex(vid)}:{_hex(did)}]",
            "chip": names["device"],
            "board_vendor": names["subvendor"],
            "board_name": names["subdevice"],
            "ids": f"{_hex(vid)}:{_hex(did)} — {(_hex(svid) or '?')}:{(_hex(sdid) or '?')}",
            "revision": rd(os.path.join(dev, "revision")),
            "driver": driver,
            "driver_version": rd(P(f"/sys/module/{driver}/version")) if driver else None,
            "link_cur": _pcie_gen(_link(pci, "current_link_speed")),
            "link_max": _pcie_gen(_link(pci, "max_link_speed")),
            "width_cur": _link(pci, "current_link_width"),
            "width_max": _link(pci, "max_link_width"),
            "vbios": rd(os.path.join(dev, "vbios_version")),
            "boot_vga": rd(os.path.join(dev, "boot_vga")) == "1",
            "vram_total": rd_int(os.path.join(dev, "mem_info_vram_total")),
            "vram_used": rd_int(os.path.join(dev, "mem_info_vram_used")),
            "gtt_total": rd_int(os.path.join(dev, "mem_info_gtt_total")),
            "gtt_used": rd_int(os.path.join(dev, "mem_info_gtt_used")),
            "vram_vendor": rd(os.path.join(dev, "mem_info_vram_vendor")),
            "busy": rd_int(os.path.join(dev, "gpu_busy_percent")),
            "mem_busy": rd_int(os.path.join(dev, "mem_busy_percent")),
            "sclk": _dpm_current(os.path.join(dev, "pp_dpm_sclk")),
            "mclk": _dpm_current(os.path.join(dev, "pp_dpm_mclk")),
            "sclk_max": _dpm_max(os.path.join(dev, "pp_dpm_sclk")),
            "mclk_max": _dpm_max(os.path.join(dev, "pp_dpm_mclk")),
            "perf_level": rd(os.path.join(dev, "power_dpm_force_performance_level")),
            "temps": [], "fan_rpm": None, "fan_pct": None, "power": None, "power_cap": None,
            "voltage": None, "pstate": None,
        }
        # Intel i915/xe
        if g["sclk"] is None:
            cur = rd_int(os.path.join(card, "gt_cur_freq_mhz")) or rd_int(os.path.join(card, "gt_act_freq_mhz"))
            if cur is not None:
                g["sclk"] = cur
                g["sclk_max"] = rd_int(os.path.join(card, "gt_max_freq_mhz")) or rd_int(os.path.join(card, "gt_RP0_freq_mhz"))

        # hwmon da GPU
        for hw in glob.glob(os.path.join(dev, "hwmon", "hwmon*")):
            for f in sorted(glob.glob(os.path.join(hw, "temp*_input"))):
                t = rd_int(f)
                if t is None:
                    continue
                lab = rd(f.replace("_input", "_label")) or os.path.basename(f).split("_")[0]
                g["temps"].append((lab, t / 1000.0))
            rpm = rd_int(os.path.join(hw, "fan1_input"))
            if rpm is not None:
                g["fan_rpm"] = rpm
            pwm = rd_int(os.path.join(hw, "pwm1"))
            if pwm is not None:
                g["fan_pct"] = round(pwm / 2.55)
            pw = rd_int(os.path.join(hw, "power1_average")) or rd_int(os.path.join(hw, "power1_input"))
            if pw is not None:
                g["power"] = pw / 1e6
            cap = rd_int(os.path.join(hw, "power1_cap"))
            if cap:
                g["power_cap"] = cap / 1e6
            v = rd_int(os.path.join(hw, "in0_input"))
            if v is not None:
                g["voltage"] = v / 1000.0
            if g["sclk"] is None:
                f1 = rd_int(os.path.join(hw, "freq1_input"))
                if f1:
                    g["sclk"] = f1 // 1_000_000
            if g["mclk"] is None:
                f2 = rd_int(os.path.join(hw, "freq2_input"))
                if f2:
                    g["mclk"] = f2 // 1_000_000

        # NVIDIA proprietário
        n = nv.get(addr.lower())
        if n:
            n = {**n, **nvx.get(addr.lower(), {})}
        if n:
            g["name"] = n.get("name") or g["name"]
            g["driver_version"] = n.get("driver_version")
            g["vbios"] = n.get("vbios_version") or g["vbios"]
            t = _fnum(n.get("temperature.gpu"))
            if t is not None:
                g["temps"] = [("GPU", t)]
            g["busy"] = _fnum(n.get("utilization.gpu"))
            g["mem_busy"] = _fnum(n.get("utilization.memory"))
            mt, mu = _fnum(n.get("memory.total")), _fnum(n.get("memory.used"))
            g["vram_total"] = int(mt * 1024 ** 2) if mt else g["vram_total"]
            g["vram_used"] = int(mu * 1024 ** 2) if mu is not None else g["vram_used"]
            g["sclk"] = _fnum(n.get("clocks.gr"))
            g["mclk"] = _fnum(n.get("clocks.mem"))
            g["sclk_max"] = _fnum(n.get("clocks.max.gr"))
            g["mclk_max"] = _fnum(n.get("clocks.max.mem"))
            g["power"] = _fnum(n.get("power.draw"))
            g["power_cap"] = _fnum(n.get("power.limit"))
            g["fan_pct"] = _fnum(n.get("fan.speed"))
            g["pstate"] = n.get("pstate")
            gc, gm = n.get("pcie.link.gen.current"), n.get("pcie.link.gen.max")
            if gc:
                g["link_cur"] = f"PCIe {gc}.0"
            if gm:
                g["link_max"] = f"PCIe {gm}.0"
            g["width_cur"] = n.get("pcie.link.width.current") or g["width_cur"]
            g["width_max"] = n.get("pcie.link.width.max") or g["width_max"]
        g["temp"] = max((t for _, t in g["temps"]), default=None) if g["temps"] else None
        # Prefere 'edge' como temperatura principal (AMD)
        for lab, t in g["temps"]:
            if lab.lower() in ("edge", "gpu"):
                g["temp"] = t
        g["integrated"] = _is_integrated(g)
        _gpu_enrich(g, pci, dev, card, n)
        result.append(g)
    # Discretas primeiro
    result.sort(key=lambda x: (x["integrated"], x["card"]))
    return result


def _is_integrated(g):
    if g["vendor"] == "Intel" and not (g["name"] or "").lower().startswith("arc") and "arc" not in (g["name"] or "").lower():
        return True
    if g["vendor"] == "AMD" and g["vram_total"] and g["vram_total"] <= 2 * 1024 ** 3 and \
            g["pci"].split(":")[1] not in ("01", "03"):
        n = (g["name"] or "").lower()
        if not re.search(r"\brx\b|radeon pro|instinct", n):
            return True
    return False


# --------------------------------------------------------------------------
# Discos
# --------------------------------------------------------------------------
SKIP_BLOCK = ("loop", "ram", "zram", "dm-", "md", "sr", "fd", "nbd", "mtdblock")


def _udev_props(dev):
    out = run(["udevadm", "info", "--query=property", "--name=" + dev], timeout=2)
    props = {}
    for line in (out or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    return props


def disks_static():
    out = []
    for blk in sorted(glob.glob(P("/sys/block/*"))):
        name = os.path.basename(blk)
        if name.startswith(SKIP_BLOCK):
            continue
        size = rd_int(os.path.join(blk, "size"), 0) * 512
        if size == 0:
            continue
        dev = os.path.join(blk, "device")
        rot = rd(os.path.join(blk, "queue/rotational")) == "1"
        removable = rd(os.path.join(blk, "removable")) == "1"
        props = _udev_props(name)
        bus = props.get("ID_BUS")
        if name.startswith("nvme"):
            iface = "NVMe"
            model = rd(os.path.join(dev, "model"))
            serial = rd(os.path.join(dev, "serial"))
            fw = rd(os.path.join(dev, "firmware_rev"))
            vendor = None
            # Link PCIe do controlador NVMe
            ctrl = os.path.realpath(dev)
            pci = os.path.dirname(ctrl) if os.path.basename(os.path.dirname(ctrl)) == "nvme" else ctrl
            pci = os.path.dirname(pci) if os.path.basename(pci) == "nvme" else pci
            link = _pcie_gen(rd(os.path.join(pci, "current_link_speed")))
            width = rd(os.path.join(pci, "current_link_width"))
            if link:
                iface = f"NVMe · {link.split(' (')[0]} x{width}" if width else f"NVMe · {link}"
            kind = "SSD NVMe"
        elif name.startswith("mmcblk"):
            iface = "eMMC/SD"
            model = rd(os.path.join(dev, "name"))
            serial = rd(os.path.join(dev, "serial"))
            fw = rd(os.path.join(dev, "fwrev"))
            vendor = None
            kind = "Cartão/eMMC"
        else:
            model = rd(os.path.join(dev, "model"))
            vendor = rd(os.path.join(dev, "vendor"))
            serial = props.get("ID_SERIAL_SHORT")
            fw = rd(os.path.join(dev, "rev")) or props.get("ID_REVISION")
            if not bus:
                real = os.path.realpath(dev)
                bus = "usb" if "/usb" in real else ("ata" if re.search(r"/ata\d+/", real) else None)
            iface = {"ata": "SATA", "usb": "USB", "scsi": "SCSI"}.get(bus or "", (bus or "SCSI").upper())
            if name.startswith("vd"):
                iface = "VirtIO"
            kind = "HDD" if rot else "SSD"
            if bus == "usb" or removable:
                kind = "Removível" if removable else kind
        if vendor and vendor.upper() in ("ATA", "") :
            vendor = None
        model = (model or props.get("ID_MODEL", "").replace("_", " ") or name).strip()
        rpm = None
        if rot and props.get("ID_ATA_ROTATION_RATE_RPM"):
            rpm = props["ID_ATA_ROTATION_RATE_RPM"]
        out.append({
            "name": name, "dev": "/dev/" + name, "model": model, "vendor": vendor,
            "serial": serial or props.get("ID_SERIAL_SHORT"), "firmware": fw, "size": size,
            "rotational": rot, "removable": removable, "interface": iface, "kind": kind,
            "rpm": rpm,
            "logical_block": rd_int(os.path.join(blk, "queue/logical_block_size")),
            "physical_block": rd_int(os.path.join(blk, "queue/physical_block_size")),
            "scheduler": _sched(rd(os.path.join(blk, "queue/scheduler"))),
            "wwn": props.get("ID_WWN"),
            "ptable": props.get("ID_PART_TABLE_TYPE"),
            "partitions": sorted(os.path.basename(p) for p in glob.glob(os.path.join(blk, name + "*"))),
        })
    return out


def _sched(s):
    if not s:
        return None
    m = re.search(r"\[(.+?)\]", s)
    return m.group(1) if m else s


def partitions_usage():
    """Mapeia /dev/xxx -> lista de (mountpoint, fstype, usage)."""
    res = {}
    if not psutil:
        return res
    try:
        parts = psutil.disk_partitions(all=False)
    except Exception:
        return res
    seen = set()
    for p in parts:
        dev = os.path.realpath(p.device) if p.device.startswith("/dev/") else p.device
        if (dev, p.mountpoint) in seen or p.mountpoint.startswith(("/snap/", "/var/snap")):
            continue
        seen.add((dev, p.mountpoint))
        try:
            u = psutil.disk_usage(p.mountpoint)
        except (OSError, PermissionError):
            u = None
        res.setdefault(os.path.basename(dev), []).append({
            "mount": p.mountpoint, "fstype": p.fstype,
            "total": u.total if u else None, "used": u.used if u else None,
            "percent": u.percent if u else None})
    return res


def disk_io():
    if not psutil:
        return {}
    try:
        c = psutil.disk_io_counters(perdisk=True) or {}
    except Exception:
        return {}
    return {k: (v.read_bytes, v.write_bytes) for k, v in c.items()}


def smart_info(dev, privileged=True):
    exe = shutil.which("smartctl") or ("/usr/sbin/smartctl" if os.path.exists("/usr/sbin/smartctl") else None)
    if not exe:
        return {"error": "smartctl não encontrado. Instale o pacote 'smartmontools'."}
    cmd = ["pkexec", exe, "-j", "-a", dev] if privileged and shutil.which("pkexec") else [exe, "-j", "-a", dev]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90, env=clean_env())
    except (OSError, subprocess.SubprocessError) as e:
        return {"error": str(e)}
    if r.returncode in (126, 127) and "pkexec" in cmd[0]:
        return {"error": "Autorização negada."}
    try:
        j = json.loads(r.stdout)
    except ValueError:
        return {"error": (r.stderr or r.stdout or "Falha ao ler SMART").strip()[:400]}
    return parse_smart(j)


def parse_smart(j):
    info = {}
    st = j.get("smart_status", {})
    if "passed" in st:
        info["Saúde (SMART)"] = "OK ✔" if st["passed"] else "FALHA ✖"
    if j.get("temperature", {}).get("current") is not None:
        info["Temperatura"] = f"{j['temperature']['current']} °C"
    if j.get("power_on_time", {}).get("hours") is not None:
        h = j["power_on_time"]["hours"]
        info["Horas ligado"] = f"{h} h ({h / 24:.0f} dias)"
    if j.get("power_cycle_count") is not None:
        info["Ciclos de energia"] = str(j["power_cycle_count"])
    nv = j.get("nvme_smart_health_information_log")
    if nv:
        units = nv.get("data_units_written")
        if units is not None:
            info["Dados escritos"] = human_bytes(units * 512000, binary=False)
        units = nv.get("data_units_read")
        if units is not None:
            info["Dados lidos"] = human_bytes(units * 512000, binary=False)
        if nv.get("percentage_used") is not None:
            info["Vida útil usada"] = f"{nv['percentage_used']} %"
        if nv.get("available_spare") is not None:
            info["Reserva disponível"] = f"{nv['available_spare']} %"
        if nv.get("media_errors") is not None:
            info["Erros de mídia"] = str(nv["media_errors"])
        if nv.get("unsafe_shutdowns") is not None:
            info["Desligamentos inseguros"] = str(nv["unsafe_shutdowns"])
    attrs = j.get("ata_smart_attributes", {}).get("table", [])
    want = {5: "Setores realocados", 9: None, 187: "Erros não corrigíveis", 194: None,
            197: "Setores pendentes", 198: "Setores irrecuperáveis", 231: "Vida útil restante",
            233: "Desgaste (media wearout)", 241: "Total LBAs escritos", 177: "Wear leveling"}
    for a in attrs:
        lab = want.get(a.get("id"))
        if lab:
            raw = a.get("raw", {}).get("value")
            if a.get("id") == 241 and raw is not None:
                info["Dados escritos"] = human_bytes(raw * 512, binary=False)
            elif a.get("id") in (231, 233, 177):
                info[lab] = f"{a.get('value')} %"
            else:
                info[lab] = str(raw)
    if j.get("model_name"):
        info.setdefault("Modelo", j["model_name"])
    return info


# --------------------------------------------------------------------------
# Relatório
# --------------------------------------------------------------------------
def build_report(static, dyn):
    L = []

    def sec(t):
        L.append("")
        L.append("=" * 64)
        L.append(t)
        L.append("=" * 64)

    def kv(k, v):
        L.append(f"  {k:<26}{v if v not in (None, '') else '—'}")

    L.append(f"HWScope — relatório gerado em {time.strftime('%d/%m/%Y %H:%M:%S')}")
    s = static["system"]
    for title, key in (("SISTEMA OPERACIONAL", "os"), ("SISTEMA", "system"),
                       ("PLACA-MÃE", "board"), ("BIOS / UEFI", "bios")):
        sec(title)
        for k, v in s[key].items():
            kv(k, v)
    c = static["cpu"]
    sec("PROCESSADOR")
    db = c.get("db") or {}
    kv("Nome", c["name"])
    kv("Codinome", db.get("codename"))
    kv("Soquete", db.get("package"))
    kv("Tecnologia", db.get("technology"))
    kv("Revisão", db.get("revision"))
    kv("Fabricante", c["vendor"])
    kv("Microarquitetura", c["microarch"])
    kv("Família/Modelo/Stepping", f"{c['family']} / {c['model']} / {c['stepping']}")
    kv("Microcódigo", c["microcode"])
    kv("Núcleos / Threads", f"{c['cores']} / {c['threads']}")
    kv("Clock mín/máx", f"{c['min_mhz']} / {c['max_mhz']} MHz")
    for k, v in c["caches"].items():
        kv(f"Cache {k}", v)
    kv("Instruções", ", ".join(c["instructions"]))
    sec("CHIPSET")
    for k, v in (static.get("chipset") or {}).items():
        kv(k, v)
    sec("MEMÓRIA")
    m = dyn.get("mem", {})
    kv("Total", human_bytes(m.get("total")))
    kv("Em uso", f"{human_bytes(m.get('used'))} ({m.get('percent')} %)")
    kv("Swap", f"{human_bytes(m.get('swap_used'))} / {human_bytes(m.get('swap_total'))}")
    for d in static.get("dimms") or []:
        if d["present"]:
            kv(d["slot"], f"{human_bytes(d['size'])} {d['type'] or ''} {d['speed'] or '?'} MT/s "
                          f"{d['manufacturer'] or ''} {d['part'] or ''}")
    for m in static.get("spd") or []:
        sec(f"SPD {m.get('address')} — {m.get('type')} {m.get('module') or ''}")
        kv("Tamanho", human_bytes(m.get("size")))
        kv("Fabricante", m.get("manufacturer"))
        kv("Part number", m.get("part"))
        kv("Nº de série", m.get("serial"))
        kv("Data", m.get("date"))
        for r in m.get("timings") or []:
            kv(r["label"], f"{r['mts']} MT/s  {r['CL']}-{r['tRCD']}-{r['tRP']}-{r['tRAS']}  {r['volt']}")
    for g in dyn.get("gpus", []):
        sec(f"PLACA DE VÍDEO — {g['name']}")
        kv("Fabricante da placa", g["board_vendor"])
        kv("Chip", g["chip"])
        sp = g.get("spec") or {}
        kv("Codinome", g.get("codename"))
        kv("Arquitetura / processo", f"{sp.get('arch')} / {sp.get('tech')}" if sp else None)
        kv("Resizable BAR", g.get("rebar"))
        kv("IDs PCI", g["ids"])
        kv("Driver", f"{g['driver']} {g['driver_version'] or ''}")
        kv("Barramento", f"{g['link_cur']} x{g['width_cur']} (máx {g['link_max']} x{g['width_max']})")
        kv("VRAM", human_bytes(g["vram_total"]))
        kv("VBIOS", g["vbios"])
        kv("Temperatura", f"{g['temp']:.0f} °C" if g["temp"] is not None else None)
    for d in static.get("disks", []):
        sec(f"DISCO — {d['model']} ({d['dev']})")
        kv("Tipo / Interface", f"{d['kind']} / {d['interface']}")
        kv("Capacidade", human_bytes(d["size"], binary=False))
        kv("Nº de série", d["serial"])
        kv("Firmware", d["firmware"])
    sec("SENSORES")
    for chip in dyn.get("chips", []):
        L.append(f"  [{chip['title']}]  ({chip['name']})")
        for snr in chip["sensors"]:
            L.append(f"      {snr['label']:<22}{snr['value']:.1f} {snr['unit']}")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------
# Temperatura de discos sem root (UDisks2) e da RAM (spd5118 / jc42)
# --------------------------------------------------------------------------
def parse_udisks_dump(txt):
    """Extrai {bloco: temperatura °C} da saída de 'udisksctl dump'."""
    drive_temp, block_drive = {}, {}
    cur, props = None, {}

    def flush():
        if cur is None:
            return
        if "/drives/" in cur:
            t = props.get("SmartTemperature")
            try:
                k = float(t) if t is not None else 0.0
            except ValueError:
                k = 0.0
            if k > 200:  # UDisks informa em Kelvin
                drive_temp[cur] = k - 273.15
        elif "/block_devices/" in cur and props.get("Drive"):
            drv = props["Drive"].strip("'\"")
            if drv and drv != "/":
                block_drive[os.path.basename(cur)] = drv

    for line in txt.splitlines():
        if line.startswith("/org/freedesktop/UDisks2/") and line.rstrip().endswith(":"):
            flush()
            cur, props = line.strip().rstrip(":"), {}
            continue
        s = line.strip()
        if s.startswith("org.freedesktop.UDisks2."):
            continue
        if ":" in s and cur:
            k, v = s.split(":", 1)
            k, v = k.strip(), v.strip()
            if k == "SmartTemperature" and k in props and props[k] not in ("0", "0.0"):
                continue
            if k in ("SmartTemperature", "Drive"):
                props[k] = v
    flush()
    out = {}
    for blk, drv in block_drive.items():
        if drv in drive_temp and re.match(r"^(sd[a-z]+|nvme\d+n\d+|hd[a-z]+|vd[a-z]+)$", blk):
            out[blk] = round(drive_temp[drv], 1)
    return out


def udisks_temps():
    out = run(["udisksctl", "dump"], timeout=6)
    return parse_udisks_dump(out) if out else {}


def udisks_all():
    """Uma leitura do UDisks2 -> (temperaturas, saúde SMART) por bloco."""
    from . import health
    out = run(["udisksctl", "dump"], timeout=6)
    if not out:
        return {}, {}
    try:
        hl = health.parse_udisks(out)
    except Exception:
        hl = {}
    return parse_udisks_dump(out), hl


def smart_from_output(out, err=""):
    """Avalia a saída JSON do smartctl (vinda do modo administrador)."""
    from . import health
    try:
        j = json.loads(out)
    except (ValueError, TypeError):
        return {"error": (err or out or "Falha ao ler SMART").strip()[:400]}
    res = health.assess_smartctl(j)
    if "error" not in res:
        res["history"] = health.compare_and_store(res.get("serial"), res.get("counters") or {})
    return res


def smart_full(dev):
    """SMART completo via smartctl (pkexec) avaliado como no CrystalDiskInfo."""
    from . import health
    exe = shutil.which("smartctl") or ("/usr/sbin/smartctl" if os.path.exists("/usr/sbin/smartctl") else None)
    if not exe:
        return {"error": "smartctl não encontrado. Instale o pacote 'smartmontools'."}
    cmd = [exe, "-j", "-a", dev]
    if not os.access(dev, os.R_OK) and shutil.which("pkexec"):
        cmd = ["pkexec"] + cmd
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90, env=clean_env())
    except (OSError, subprocess.SubprocessError) as e:
        return {"error": str(e)}
    if r.returncode in (126, 127) and cmd[0] == "pkexec":
        return {"error": "Autorização negada."}
    try:
        j = json.loads(r.stdout)
    except ValueError:
        return {"error": (r.stderr or r.stdout or "Falha ao ler SMART").strip()[:400]}
    res = health.assess_smartctl(j)
    if "error" not in res:
        res["history"] = health.compare_and_store(res.get("serial"), res.get("counters") or {})
    return res


def ram_temps(chips):
    """Lista [(rótulo, °C)] dos sensores térmicos dos pentes (DDR5 spd5118, DDR4 jc42)."""
    res = []
    for c in chips:
        if c["kind"] != "mem":
            continue
        for s in c["sensors"]:
            if s["type"] == "temp":
                res.append(s["value"])
    return [(f"Pente {i + 1}", t) for i, t in enumerate(res)]


SENSOR_MODULES = ["drivetemp", "spd5118", "jc42", "ee1004", "nct6775", "it87", "k10temp",
                  "coretemp", "zenpower", "i2c_i801", "i2c_piix4", "i2c_dev", "nvme"]


def loaded_modules():
    txt = rd(P("/proc/modules")) or ""
    return {l.split()[0] for l in txt.splitlines() if l.strip()}


def enable_sensors(persist=True):
    """Carrega drivetemp (HD/SSD SATA) e spd5118/jc42 (RAM) via pkexec."""
    if not shutil.which("pkexec"):
        return False, "pkexec não encontrado (instale o polkit)."
    mods = "drivetemp spd5118 jc42 ee1004"
    script = f"for m in {mods}; do modprobe $m 2>/dev/null; done; "
    if persist:
        script += ("printf '# Gerado pelo HWScope: sensores de temperatura\\ndrivetemp\\nspd5118\\nee1004\\n' "
                   "> /etc/modules-load.d/hwscope-sensors.conf; ")
    script += "lsmod | grep -E '^(drivetemp|spd5118|jc42|ee1004)' | cut -d' ' -f1"
    try:
        r = subprocess.run(["pkexec", "/bin/sh", "-c", script], capture_output=True, text=True,
                           timeout=120, env=clean_env())
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if r.returncode in (126, 127):
        return False, "Autorização negada."
    loaded = r.stdout.split()
    return True, "Módulos ativos: " + (", ".join(loaded) if loaded else "nenhum")


def diagnostics(static, dyn):
    L = []
    L.append(f"Kernel: {platform.release()}")
    mods = loaded_modules()
    L.append("Módulos de sensores carregados: " + (", ".join(m for m in SENSOR_MODULES if m in mods) or "nenhum"))
    L.append("")
    L.append("Chips hwmon encontrados:")
    for c in dyn.get("chips", []):
        temps = [f"{s['label']}={s['value']:.0f}°C" for s in c["sensors"] if s["type"] == "temp"]
        L.append(f"  • {c['name']} [{hw_kind(c['kind'])}] {c['title'] if c['title'] != c['name'] else ''} {' '.join(temps)}")
    if not dyn.get("chips"):
        L.append("  (nenhum)")
    L.append("")
    L.append("Discos:")
    ut = dyn.get("udisks_temps", {})
    hwt = {c["block"] for c in dyn.get("chips", []) if c["kind"] == "disk"}
    for d in static.get("disks", []):
        src = "hwmon" if d["name"] in hwt else ("UDisks2" if d["name"] in ut else "SEM TEMPERATURA")
        L.append(f"  • {d['name']} {d['model']} ({d['interface']}): {src}")
    L.append(f"  udisksctl: {'sim' if shutil.which('udisksctl') else 'não instalado'} · "
             f"smartctl: {'sim' if shutil.which('smartctl') or os.path.exists('/usr/sbin/smartctl') else 'não instalado'}")
    L.append("")
    dimms = [x for x in (static.get("dimms") or []) if x.get("present")]
    types = {x.get("type") for x in dimms if x.get("type")}
    L.append(f"Memória: {', '.join(types) or 'tipo desconhecido'} · sensores de RAM: "
             f"{len(ram_temps(dyn.get('chips', [])))}")
    L.append("")
    L.append("Sugestões:")
    sata = [d for d in static.get("disks", []) if not d["name"].startswith("nvme") and d["name"] not in hwt]
    if sata and "drivetemp" not in mods:
        L.append("  - HD/SSD SATA: o módulo 'drivetemp' não está carregado → use o 'Modo administrador'.")
    nv = [d for d in static.get("disks", []) if d["name"].startswith("nvme") and d["name"] not in hwt]
    if nv:
        L.append("  - NVMe sem hwmon: kernel sem CONFIG_NVME_HWMON; o HWScope usa UDisks2 como alternativa "
                 "(instale 'udisks2' se não houver).")
    if not ram_temps(dyn.get("chips", [])):
        if "DDR5" in types:
            L.append("  - RAM DDR5: precisa do módulo 'spd5118' (kernel 6.11+) → use o 'Modo administrador'. "
                     "Em placas AMD o barramento SPD só é suportado em kernels mais novos (6.13+).")
        else:
            L.append("  - RAM DDR4/DDR3: a maioria dos pentes NÃO tem sensor de temperatura. O Modo "
                     "administrador procura o sensor (chip TSOD/jc42) no barramento SMBus; se nada aparecer, "
                     "seus pentes não têm sensor.")
    return "\n".join(L)


def hw_kind(k):
    return KIND_LABEL.get(k, k)


# ==========================================================================
# Campos extras (CPU-Z / GPU-Z)
# ==========================================================================
def _hybrid():
    """Intel híbrido: núcleos P (cpu_core) e E (cpu_atom)."""
    p = rd(P("/sys/devices/cpu_core/cpus"))
    e = rd(P("/sys/devices/cpu_atom/cpus"))
    if not p or not e:
        return None
    return {"P": len(_parse_cpulist(p)), "E": len(_parse_cpulist(e))}


def _rapl_limits():
    base = P("/sys/class/powercap/intel-rapl:0")
    res = {}
    for i in range(3):
        name = rd(os.path.join(base, f"constraint_{i}_name"))
        lim = rd_int(os.path.join(base, f"constraint_{i}_power_limit_uw"))
        if name and lim:
            res[name] = lim / 1e6
    return res or None


class PowerMeter:
    """Potência do pacote da CPU via RAPL (energy_uj) quando legível sem root."""

    def __init__(self):
        self.last = None
        cands = glob.glob(P("/sys/class/powercap/intel-rapl:0/energy_uj")) + \
            glob.glob(P("/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj"))
        self.path = cands[0] if cands else None

    def read(self):
        if not self.path:
            return None
        e = rd_int(self.path)
        if e is None:
            self.path = None  # sem permissão
            return None
        now = time.monotonic()
        val = None
        if self.last:
            e0, t0 = self.last
            if e >= e0 and now > t0:
                val = (e - e0) / 1e6 / (now - t0)
        self.last = (e, now)
        return val


def cpu_voltage_power(chips):
    """Vcore e potência da CPU a partir do hwmon (zenpower, Super I/O)."""
    vcore = power = None
    src = None
    for c in chips:
        for s in c["sensors"]:
            lab = s["label"].lower()
            if s["type"] == "in" and (lab in ("vcore", "cpu core", "cpu vcore", "vddcr_cpu", "svi2_core") or "vcore" in lab):
                vcore, src = s["value"], c["name"]
            if s["type"] == "power" and c["kind"] == "cpu" and lab in ("svi2_p_core", "ppt", "package", "power1", "socket"):
                power = (power or 0) + s["value"]
    if vcore is None:
        for c in chips:
            if c["name"].startswith(("nct", "it8")):
                for s in c["sensors"]:
                    if s["type"] == "in" and s["key"].endswith("/in0"):
                        vcore, src = s["value"], c["name"] + " in0"
    return vcore, power, src


SUPERIO = {"nct": ("Nuvoton", "D"), "it8": ("ITE", "E"), "f71": ("Fintek", ""), "w83": ("Winbond", ""),
           "f81": ("Fintek", "")}


def superio_name(chips):
    for c in chips:
        n = c["name"]
        for pre, (vendor, suf) in SUPERIO.items():
            if n.startswith(pre):
                return f"{vendor} {n.upper()}{suf}"
    return None


def _pci_dev(addr):
    d = P(f"/sys/bus/pci/devices/{addr}")
    if not os.path.isdir(d):
        return None
    vid, did = rd(os.path.join(d, "vendor")), rd(os.path.join(d, "device"))
    n = pci_names(vid, did)
    return {"addr": addr, "vendor": VENDOR_SHORT.get(_hex(vid) or "", n["vendor"]),
            "name": n["device"] or f"[{_hex(vid)}:{_hex(did)}]",
            "rev": rd(os.path.join(d, "revision")), "class": rd(os.path.join(d, "class")) or ""}


def chipset_info():
    devs = []
    for d in sorted(glob.glob(P("/sys/bus/pci/devices/*"))):
        x = _pci_dev(os.path.basename(d))
        if x:
            devs.append(x)
    host = next((x for x in devs if x["class"].startswith("0x0600")), None)
    isa = next((x for x in devs if x["class"].startswith("0x0601")), None)
    chipset = None
    for x in devs:
        nm = x["name"] or ""
        m = re.search(r"\b([BHQXZAW]\d{3}[A-Z]?|[3-8]00 Series)\s+Chipset", nm)
        if m:
            chipset = f"{x['vendor']} {m.group(1)}"
            break
    if not chipset and isa and isa["name"]:
        m = re.search(r"\b([BHQXZ]\d{2,3}[A-Z]?)\b", isa["name"])
        if m:
            chipset = f"{isa['vendor']} {m.group(1)}"
    pcie = []
    for d in glob.glob(P("/sys/bus/pci/devices/*/max_link_speed")):
        g = _pcie_gen(rd(d))
        if g:
            pcie.append(g.split(" (")[0])
    return {
        "Norte (host bridge)": f"{host['vendor']} {host['name']}" if host and host["name"] else None,
        "Rev. host bridge": host["rev"] if host else None,
        "Sul (LPC/ISA)": f"{isa['vendor']} {isa['name']}" if isa and isa["name"] else None,
        "Rev. LPC": isa["rev"] if isa else None,
        "Chipset": chipset,
        "PCIe máximo": max(pcie, key=lambda g: float(re.sub(r"[^\d.]", "", g) or 0)) if pcie else None,
    }


def memory_general(dimms):
    pres = [d for d in (dimms or []) if d.get("present")]
    if not pres:
        return {}
    chans = set()
    for d in pres:
        txt = f"{d.get('bank') or ''} {d.get('slot') or ''}"
        m = re.search(r"CHANNEL\s*([A-H])|Channel([A-H])|DIMM_?([A-H])\d|Controller\d-Channel([A-H])|\bCH([A-H])", txt, re.I)
        if m:
            chans.add(next(g for g in m.groups() if g).upper())
    n = len(chans) if chans else None
    if not n:
        n = 2 if len(pres) in (2, 4) else (1 if len(pres) == 1 else None)
    ddr5 = any((d.get("type") or "").upper() == "DDR5" for d in pres)
    mode = {1: "Single", 2: "Dual", 3: "Triple", 4: "Quad", 8: "Octa"}.get(n, str(n) if n else None)
    if ddr5 and n:
        mode += f" (2 × 32-bit por pente, {n * 2} subcanais)"
    sp = pres[0].get("configured") or pres[0].get("speed")
    uncore = None
    for f in glob.glob(P("/sys/devices/system/cpu/intel_uncore_frequency/*/current_freq_khz")):
        v = rd_int(f)
        if v:
            uncore = v / 1000
            break
    return {"channels": mode, "dram_mhz": int(sp) / 2 if sp and str(sp).isdigit() else None,
            "mts": int(sp) if sp and str(sp).isdigit() else None, "uncore": uncore,
            "total": sum(d["size"] or 0 for d in pres), "type": pres[0].get("type"),
            "count": len(pres)}


# ---------------- GPU ----------------
NV_EXTRA = ["pci.bus_id", "utilization.encoder", "utilization.decoder", "clocks_throttle_reasons.active",
            "clocks.default_applications.graphics", "clocks.default_applications.memory",
            "power.default_limit", "power.max_limit", "power.min_limit", "temperature.memory",
            "clocks.video", "memory.reserved", "display_active", "compute_cap"]


def nvidia_smi_extra():
    res = {}
    for fields in (NV_EXTRA, NV_EXTRA[:-1], NV_EXTRA[:-4]):
        out = run(["nvidia-smi", "--query-gpu=" + ",".join(fields), "--format=csv,noheader,nounits"], timeout=3)
        if out:
            for line in out.strip().splitlines():
                vals = [v.strip() for v in line.split(",")]
                if len(vals) != len(fields):
                    continue
                d = {k: (None if v in ("[N/A]", "N/A", "[Not Supported]", "") else v) for k, v in zip(fields, vals)}
                bus = (d.get("pci.bus_id") or "").lower()
                if bus.count(":") == 2 and len(bus.split(":")[0]) == 8:
                    bus = bus[4:]
                res[bus] = d
            break
    return res


THROTTLE = {0x1: "Ociosa", 0x2: "Clock de aplicação", 0x4: "Limite de energia (SW)", 0x8: "Redução por HW",
            0x10: "Sincronismo", 0x20: "Térmico (SW)", 0x40: "Térmico (HW)", 0x80: "Freio de energia (HW)",
            0x100: "Clock de display"}


def nv_perfcap(v):
    try:
        x = int(v, 16)
    except (TypeError, ValueError):
        return None
    if x == 0:
        return "Nenhum (sem limitação)"
    return ", ".join(n for b, n in THROTTLE.items() if x & b) or hex(x)


def resizable_bar(pci, vram):
    """Compara o maior BAR prefetchable com a VRAM."""
    txt = rd(os.path.join(pci, "resource"))
    if not txt:
        return None
    biggest = 0
    for line in txt.splitlines()[:6]:
        try:
            a, b, fl = (int(x, 16) for x in line.split())
        except ValueError:
            continue
        if a and b > a and fl & 0x200:  # IORESOURCE_MEM
            biggest = max(biggest, b - a + 1)
    if not biggest:
        return None
    if vram and biggest >= vram * 0.9:
        return f"Ativado (BAR {human_bytes(biggest)})"
    if biggest > 256 * 1024 ** 2:
        return f"Ativado (BAR {human_bytes(biggest)})"
    return f"Desativado (BAR {human_bytes(biggest)})"


def _edid_info(path):
    try:
        with open(path, "rb") as f:
            e = f.read(256)
    except OSError:
        return {}
    if len(e) < 128 or e[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return {}
    mfg = "".join(chr(((((e[8] << 8) | e[9]) >> s) & 0x1F) + 64) for s in (10, 5, 0))
    info = {"mfg": mfg}
    for i in range(54, 126, 18):
        d = e[i:i + 18]
        if d[0] or d[1]:
            if "res" not in info:
                h = d[2] | ((d[4] & 0xF0) << 4)
                v = d[5] | ((d[7] & 0xF0) << 4)
                pclk = (d[0] | (d[1] << 8)) * 10000
                hb = d[3] | ((d[4] & 0xF) << 8)
                vb = d[6] | ((d[7] & 0xF) << 8)
                hz = pclk / ((h + hb) * (v + vb)) if (h + hb) and (v + vb) else 0
                info["res"] = f"{h}×{v} @ {hz:.0f} Hz"
                hs, vs = d[12] | ((d[14] & 0xF0) << 4), d[13] | ((d[14] & 0xF) << 8)
                if hs and vs:
                    info["size"] = f'{(hs ** 2 + vs ** 2) ** 0.5 / 25.4:.1f}"'
        elif d[3] == 0xFC:
            info["name"] = d[5:18].split(b"\n")[0].decode("ascii", "replace").strip()
    return info


def monitors(card):
    out = []
    for c in sorted(glob.glob(card + "-*")):
        st = rd(os.path.join(c, "status"))
        if st != "connected":
            continue
        conn = os.path.basename(c).split("-", 1)[1]
        e = _edid_info(os.path.join(c, "edid"))
        out.append({"connector": conn, **e})
    return out


_CL = {}


def opencl_devices():
    if "v" in _CL:
        return _CL["v"]
    out = run(["clinfo", "--raw"], timeout=10)
    devs = {}
    if out:
        for line in out.splitlines():
            m = re.match(r"\s*\[(\S+?)/(\d+)\]\s+(CL_\w+)\s+(.*)", line)
            if not m:
                continue
            key = (m.group(1), m.group(2))
            devs.setdefault(key, {})[m.group(3)] = m.group(4).strip()
    res = []
    for (plat, idx), d in devs.items():
        bus = None
        for k in ("CL_DEVICE_PCI_BUS_INFO_KHR", "CL_DEVICE_TOPOLOGY_AMD"):
            m = re.search(r"([0-9a-f]{2}:[0-9a-f]{2}\.\d)", d.get(k, ""), re.I)
            if m:
                bus = m.group(1).lower()
        res.append({"platform": plat, "name": d.get("CL_DEVICE_NAME"), "cu": d.get("CL_DEVICE_MAX_COMPUTE_UNITS"),
                    "version": d.get("CL_DEVICE_VERSION"), "driver": d.get("CL_DRIVER_VERSION"),
                    "vendor": d.get("CL_DEVICE_VENDOR"), "bus": bus, "type": d.get("CL_DEVICE_TYPE", "")})
    _CL["v"] = res
    return res


_VK = {}


def vulkan_devices():
    if "v" in _VK:
        return _VK["v"]
    res = []
    out = run(["vulkaninfo", "--summary"], timeout=8)
    if out:
        for blk in re.split(r"\nGPU\d+:\n", out)[1:]:
            d = dict(re.findall(r"^\s*(\w+)\s*=\s*(.+?)\s*$", blk, re.M))
            res.append(d)
    full = run(["vulkaninfo"], timeout=15) or ""
    rt = "VK_KHR_ray_tracing_pipeline" in full or "VK_KHR_ray_query" in full
    for d in res:
        d["raytracing"] = rt
    _VK["v"] = res
    return res


_VA = {}


def vaapi_info():
    if "v" in _VA:
        return _VA["v"]
    out = run(["vainfo"], timeout=6) or ""
    dec, enc = set(), set()
    for m in re.finditer(r"VAProfile(\w+?)\s*:\s*VAEntrypoint(\w+)", out):
        prof, ep = m.group(1), m.group(2)
        codec = next((c for c in ("H264", "HEVC", "AV1", "VP9", "VP8", "MPEG2", "VC1", "JPEG") if prof.upper().startswith(c)), None)
        if not codec:
            continue
        codec = {"H264": "H.264", "HEVC": "H.265/HEVC"}.get(codec, codec)
        if ep == "VLD":
            dec.add(codec)
        elif "Enc" in ep:
            enc.add(codec)
    drv = re.search(r"Driver version:\s*(.+)", out)
    _VA["v"] = {"decode": sorted(dec), "encode": sorted(enc), "driver": drv.group(1).strip() if drv else None} if out else None
    return _VA["v"]


def _gpu_enrich(g, pci, dev, card, n):
    key, spec = gpudb.find(g.get("chip"), g.get("name"))
    g["codename"] = key or ((g.get("chip") or "").split(" [")[0] or None)
    g["spec"] = spec
    g["rebar"] = resizable_bar(pci, g.get("vram_total"))
    g["monitors"] = monitors(card)
    if dev:
        for hw in glob.glob(os.path.join(dev, "hwmon", "hwmon*")):
            for k, f in (("power_cap_default", "power1_cap_default"), ("power_cap_max", "power1_cap_max"),
                         ("power_cap_min", "power1_cap_min")):
                v = rd_int(os.path.join(hw, f))
                if v:
                    g[k] = v / 1e6
            crit = []
            for f in sorted(glob.glob(os.path.join(hw, "temp*_crit"))):
                v = rd_int(f)
                if v and v < 200000:
                    lab = rd(f.replace("_crit", "_label")) or os.path.basename(f).split("_")[0]
                    crit.append(f"{lab} {v / 1000:.0f}°C")
            g["temp_limits"] = ", ".join(crit) or None
        g["vbios_date"] = rd(os.path.join(dev, "vbios_date"))
        od = rd(os.path.join(dev, "pp_od_clk_voltage"))
        g["overdrive"] = "Disponível" if od else None
    if n:
        g["enc_load"] = _fnum(n.get("utilization.encoder"))
        g["dec_load"] = _fnum(n.get("utilization.decoder"))
        g["perfcap"] = nv_perfcap(n.get("clocks_throttle_reasons.active"))
        g["default_clock"] = _fnum(n.get("clocks.default_applications.graphics"))
        g["default_mem"] = _fnum(n.get("clocks.default_applications.memory"))
        g["power_cap_default"] = _fnum(n.get("power.default_limit"))
        g["power_cap_max"] = _fnum(n.get("power.max_limit"))
        g["power_cap_min"] = _fnum(n.get("power.min_limit"))
        tm = _fnum(n.get("temperature.memory"))
        if tm:
            g["temps"].append(("Memória", tm))
        g["compute_cap"] = n.get("compute_cap")
        g["cuda"] = True
    else:
        g["cuda"] = False


def gpu_static_extra(g, gl):
    """Junta dados de OpenCL / Vulkan / VA-API e calcula shaders, fillrate e banda."""
    out = {}
    spec = g.get("spec") or {}
    cl = opencl_devices()
    bus = g["pci"].split(":", 1)[1] if ":" in g["pci"] else g["pci"]
    mine = [d for d in cl if d["bus"] and d["bus"] == bus.lower()]
    if not mine and len([d for d in cl if "GPU" in d["type"]]) == 1:
        mine = [d for d in cl if "GPU" in d["type"]]
    out["opencl"] = f"{mine[0]['version']} ({mine[0]['platform']})" if mine else None
    cu = int(mine[0]["cu"]) if mine and mine[0].get("cu", "").isdigit() else None
    arch = spec.get("arch", "")
    shaders = tmus = None
    exact = False
    if cu and arch:
        spc = gpudb.per_cu(arch, gpudb.SHADERS_PER_CU)
        tpc = gpudb.per_cu(arch, gpudb.TMUS_PER_CU)
        if spc:
            shaders, exact = cu * spc, True
        if tpc:
            tmus = int(cu * tpc)
    if shaders is None and spec:
        shaders, tmus = spec["shaders"], spec["tmus"]
    out["shaders"] = shaders
    out["shaders_exact"] = exact
    out["cu"] = cu
    out["tmus"] = tmus
    out["rops"] = spec.get("rops")
    if spec and shaders and exact and shaders < spec["shaders"]:
        # chip cortado: ROPs escalados como aproximação
        out["rops_note"] = "(chip completo)"
    boost = g.get("sclk_max")
    if boost and out["rops"]:
        out["pixel_fill"] = out["rops"] * boost / 1000.0
    if boost and tmus:
        out["texture_fill"] = tmus * boost / 1000.0
    if shaders and boost:
        out["tflops"] = shaders * 2 * boost / 1e6
    mt = spec.get("mem_type")
    bw = spec.get("bus")
    if g.get("vram_vendor") and mt and mt != "Sistema":
        out["mem_type"] = f"{mt} ({g['vram_vendor'].capitalize()})"
    else:
        out["mem_type"] = mt
    mclk = g.get("mclk_max")
    if mclk and bw and mt in gpudb.MEM_RATE and not g.get("integrated"):
        if g["vendor"] == "NVIDIA":
            rate = mclk * 2 * (2 if mt == "GDDR6X" else (2 if mt == "GDDR7" else 1))
        else:
            rate = mclk * gpudb.MEM_RATE[mt] * (2 if mt.startswith("GDDR6") else 1)
        out["bandwidth"] = rate * bw / 8 / 1000.0
        out["mem_rate"] = rate
    vk = vulkan_devices()
    vkd = None
    for d in vk:
        nm = d.get("deviceName", "")
        if g["name"] and (g["name"].split("/")[0].split(" (")[0] in nm or (g.get("codename") or "#") in nm):
            vkd = d
    if not vkd and vk:
        vkd = next((d for d in vk if d.get("deviceType", "").endswith("DISCRETE_GPU") != g.get("integrated")), vk[0])
    if vkd:
        out["vulkan"] = vkd.get("apiVersion")
        out["vk_driver"] = " ".join(x for x in (vkd.get("driverName"), vkd.get("driverInfo")) if x)
        out["raytracing"] = vkd.get("raytracing")
    out["opengl"] = gl.get("gl_core") or gl.get("gl")
    # nome comercial exato (ex.: "AMD Radeon RX 6700 XT") via Vulkan/OpenGL
    if vkd:
        ok = vkd.get("deviceType", "").endswith("DISCRETE_GPU") != bool(g.get("integrated"))
        cand = vkd.get("deviceName", "") if ok else ""
    else:
        cand = gl.get("renderer", "") if g.get("boot_vga") else ""
    cand = re.sub(r"\s*\(.*\)\s*$", "", cand).strip()
    if cand and re.search(r"radeon|geforce|rtx|gtx|arc|intel|quadro|nvidia", cand, re.I) and len(cand) < 60:
        out["marketing"] = cand
    m = re.search(r"Mesa ([\d.]+\S*)", (gl.get("gl") or "") + " " + (gl.get("gl_core") or ""))
    out["mesa"] = m.group(1) if m else None
    out["vaapi"] = vaapi_info()
    out["rocm"] = os.path.isdir("/opt/rocm") or bool(shutil.which("rocminfo"))
    return out


# --------------------------------------------------------------------------
# Swap
# --------------------------------------------------------------------------
def swap_info():
    devs = []
    txt = rd(P("/proc/swaps")) or ""
    for line in txt.splitlines()[1:]:
        p = line.split()
        if len(p) < 5:
            continue
        name, typ = p[0].replace("\\040", " "), p[1]
        size, used, prio = int(p[2]) * 1024, int(p[3]) * 1024, p[4]
        kind = {"partition": "Partição", "file": "Arquivo"}.get(typ, typ)
        extra = {}
        base = os.path.basename(name)
        if base.startswith("zram"):
            kind = "zram (RAM comprimida)"
            zb = P(f"/sys/block/{base}")
            alg = rd(os.path.join(zb, "comp_algorithm"))
            m = re.search(r"\[(\w+)\]", alg or "")
            extra["algoritmo"] = m.group(1) if m else alg
            mm = (rd(os.path.join(zb, "mm_stat")) or "").split()
            if len(mm) >= 3:
                orig, compr, total = int(mm[0]), int(mm[1]), int(mm[2])
                extra["dados"] = orig
                extra["ocupando"] = total
                extra["taxa"] = orig / compr if compr else None
        elif name.startswith("/dev/"):
            blk = os.path.basename(os.path.realpath(name))
            parent = None
            for d in glob.glob(P("/sys/block/*")):
                if os.path.exists(os.path.join(d, blk)) or os.path.basename(d) == blk:
                    parent = os.path.basename(d)
                    break
            if parent:
                rot = rd(P(f"/sys/block/{parent}/queue/rotational")) == "1"
                extra["disco"] = f"{parent} ({'HDD' if rot else 'SSD'})"
            if blk.startswith("dm-"):
                nm = rd(P(f"/sys/block/{blk}/dm/name"))
                if nm:
                    extra["volume"] = nm
                    if "crypt" in (rd(P(f"/sys/block/{blk}/dm/uuid")) or "").lower():
                        kind += " criptografada"
        devs.append({"name": name, "kind": kind, "size": size, "used": used, "prio": prio, **extra})

    def sysctl(n):
        return rd(P(f"/proc/sys/vm/{n}"))

    zs = P("/sys/module/zswap/parameters")
    zswap = None
    if os.path.isdir(zs):
        en = rd(os.path.join(zs, "enabled"))
        zswap = {"enabled": en in ("Y", "1"), "compressor": rd(os.path.join(zs, "compressor")),
                 "pool": rd(os.path.join(zs, "max_pool_percent")), "zpool": rd(os.path.join(zs, "zpool"))}
    zstored = None
    zdir = "/sys/kernel/debug/zswap"
    if os.path.isdir(zdir):
        sp = rd_int(os.path.join(zdir, "stored_pages"))
        if sp is not None:
            zstored = sp * 4096
    resume = rd(P("/sys/power/resume"))
    hib = None
    if resume and resume not in ("0:0", "0"):
        hib = f"configurada (dispositivo {resume})"
    s = psutil.swap_memory() if psutil else None
    return {
        "devices": devs,
        "total": sum(d["size"] for d in devs) if devs else (s.total if s else 0),
        "used": sum(d["used"] for d in devs) if devs else (s.used if s else 0),
        "sin": getattr(s, "sin", None), "sout": getattr(s, "sout", None),
        "swappiness": sysctl("swappiness"), "cache_pressure": sysctl("vfs_cache_pressure"),
        "page_cluster": sysctl("page-cluster"), "watermark": sysctl("watermark_scale_factor"),
        "zswap": zswap, "zswap_stored": zstored,
        "hibernate": hib or "não configurada",
    }


# --------------------------------------------------------------------------
# RAPL (potência) com root
# --------------------------------------------------------------------------
RAPL_NAMES = {"package-0": "Pacote (CPU inteira)", "package-1": "Pacote 2", "core": "Núcleos",
              "uncore": "Gráfico integrado / uncore", "dram": "Memória (DRAM)", "psys": "Plataforma (sistema)"}


def rapl_zones():
    """Zonas RAPL disponíveis: [{path, name, label, max_range}]."""
    out = []
    for d in sorted(glob.glob(P("/sys/class/powercap/intel-rapl:*"))):
        if not os.path.exists(os.path.join(d, "energy_uj")):
            continue
        name = rd(os.path.join(d, "name")) or os.path.basename(d)
        out.append({"path": os.path.join(d, "energy_uj"), "zone": os.path.basename(d), "name": name,
                    "label": RAPL_NAMES.get(name, name),
                    "max_range": rd_int(os.path.join(d, "max_energy_range_uj")) or 0})
    return out


def rapl_readable():
    z = rapl_zones()
    return bool(z) and rd_int(z[0]["path"]) is not None


# Lê os contadores como root e envia uma linha por segundo; termina sozinho quando
# o HWScope fecha (o pipe é fechado e o printf recebe SIGPIPE).
RAPL_SCRIPT = r"""
trap 'exit 0' PIPE TERM INT
while :; do
  for f in /sys/class/powercap/intel-rapl:*/energy_uj; do
    [ -r "$f" ] || continue
    printf '%s %s\n' "$f" "$(cat "$f" 2>/dev/null)" || exit 0
  done
  printf 'END\n' || exit 0
  sleep 1
done
"""


# --------------------------------------------------------------------------
# Dependências (programas externos opcionais)
# --------------------------------------------------------------------------
def distro_family():
    txt = rd(P("/etc/os-release")) or ""
    ids = " ".join(re.findall(r"^(?:ID|ID_LIKE)=\"?([^\"\n]+)", txt, re.M)).lower()
    for fam, keys in (("apt", ("debian", "ubuntu", "mint", "pop", "elementary", "zorin")),
                      ("dnf", ("fedora", "rhel", "centos", "rocky", "alma", "nobara")),
                      ("pacman", ("arch", "manjaro", "endeavouros", "cachyos", "garuda")),
                      ("zypper", ("suse", "opensuse"))):
        if any(k in ids for k in keys):
            return fam
    return "apt"


INSTALL_CMD = {"apt": "sudo apt install", "dnf": "sudo dnf install", "pacman": "sudo pacman -S --needed",
               "zypper": "sudo zypper install"}

#  (programa, para que serve, nível, {família: pacote}, condição)
DEPS = [
    ("python3", "Modo administrador (processo root)", "essencial",
     {"apt": "python3", "dnf": "python3", "pacman": "python", "zypper": "python3"}, None),
    ("pkexec", "Pedir a senha de administrador", "essencial",
     {"apt": "pkexec", "dnf": "polkit", "pacman": "polkit", "zypper": "polkit"}, None),
    ("modprobe", "Carregar drivers de sensores", "essencial",
     {"apt": "kmod", "dnf": "kmod", "pacman": "kmod", "zypper": "kmod"}, None),
    ("udisksctl", "Saúde e temperatura dos discos sem senha", "recomendado",
     {"apt": "udisks2", "dnf": "udisks2", "pacman": "udisks2", "zypper": "udisks2"}, None),
    ("smartctl", "SMART completo dos discos", "recomendado",
     {"apt": "smartmontools", "dnf": "smartmontools", "pacman": "smartmontools", "zypper": "smartmontools"}, None),
    ("dmidecode", "Detalhes dos pentes de RAM", "recomendado",
     {"apt": "dmidecode", "dnf": "dmidecode", "pacman": "dmidecode", "zypper": "dmidecode"}, None),
    ("glxinfo", "Renderizador e versão do OpenGL", "recomendado",
     {"apt": "mesa-utils", "dnf": "glx-utils", "pacman": "mesa-utils", "zypper": "Mesa-demo-x"}, "gpu"),
    ("vulkaninfo", "Versão do Vulkan e ray tracing", "recomendado",
     {"apt": "vulkan-tools", "dnf": "vulkan-tools", "pacman": "vulkan-tools", "zypper": "vulkan-tools"}, "gpu"),
    ("clinfo", "OpenCL e contagem exata de shaders da GPU", "opcional",
     {"apt": "clinfo", "dnf": "clinfo", "pacman": "clinfo", "zypper": "clinfo"}, "gpu"),
    ("vainfo", "Codecs de vídeo acelerados pela GPU", "opcional",
     {"apt": "vainfo", "dnf": "libva-utils", "pacman": "libva-utils", "zypper": "libva-utils"}, "gpu"),
    ("iw", "Nome da rede, padrão e frequência do Wi-Fi", "opcional",
     {"apt": "iw", "dnf": "iw", "pacman": "iw", "zypper": "iw"}, "wifi"),
    ("pactl", "Servidor de som e saída/entrada padrão", "opcional",
     {"apt": "pulseaudio-utils", "dnf": "pulseaudio-utils", "pacman": "libpulse", "zypper": "pulseaudio-utils"}, None),
    ("sensors-detect", "Detectar o chip de sensores da placa-mãe", "opcional",
     {"apt": "lm-sensors", "dnf": "lm_sensors", "pacman": "lm_sensors", "zypper": "sensors"}, None),
    ("nvidia-smi", "Sensores e dados da GPU NVIDIA", "essencial",
     {"apt": "(driver proprietário NVIDIA)", "dnf": "(driver proprietário NVIDIA)",
      "pacman": "nvidia-utils", "zypper": "(driver proprietário NVIDIA)"}, "nvidia"),
]

KMODS = [("drivetemp", "temperatura de HD/SSD SATA"), ("spd5118", "temperatura e SPD de RAM DDR5"),
         ("ee1004", "SPD de RAM DDR4"), ("at24", "SPD de RAM DDR3 (EEPROM)"),
         ("jc42", "temperatura de RAM DDR3/DDR4 com sensor"),
         ("nct6775", "sensores da placa-mãe (Nuvoton)"), ("it87", "sensores da placa-mãe (ITE)")]


def _find_exe(name):
    p = shutil.which(name)
    if p:
        return p
    for d in ("/usr/sbin", "/sbin", "/usr/bin", "/bin", "/usr/local/sbin", "/usr/local/bin"):
        if os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    return None


def dependencies(gpus=None, nets=None):
    fam = distro_family()
    has_gpu = bool(gpus) or bool(glob.glob(P("/sys/class/drm/card[0-9]")))
    vendors = {g.get("vendor") for g in (gpus or [])}
    if not vendors:
        for c in glob.glob(P("/sys/class/drm/card[0-9]*/device/vendor")):
            vendors.add({"0x10de": "NVIDIA"}.get(rd(c) or "", ""))
    has_wifi = bool(glob.glob(P("/sys/class/net/*/wireless"))) or bool(glob.glob(P("/sys/class/net/*/phy80211")))
    cond = {None: True, "gpu": has_gpu, "wifi": has_wifi, "nvidia": "NVIDIA" in vendors}
    out = []
    for exe, why, level, pkgs, c in DEPS:
        if not cond.get(c, True):
            continue
        path = _find_exe(exe)
        if exe == "python3":
            path = next((p for p in ("/usr/bin/python3", "/bin/python3", "/usr/local/bin/python3")
                         if os.path.exists(p)), None) or path
        out.append({"exe": exe, "why": why, "level": level, "ok": bool(path), "path": path,
                    "pkg": pkgs.get(fam) or pkgs.get("apt")})
    missing = [d["pkg"] for d in out if not d["ok"] and not d["pkg"].startswith("(")]
    cmd = f"{INSTALL_CMD[fam]} {' '.join(dict.fromkeys(missing))}" if missing else ""
    loaded = loaded_modules()
    kmods = []
    rel = platform.release()
    for m, why in KMODS:
        builtin = m in (rd(f"/lib/modules/{rel}/modules.builtin") or "")
        is_loaded = m in loaded or os.path.isdir(P(f"/sys/module/{m}"))
        avail = is_loaded or builtin or bool(glob.glob(f"/lib/modules/{rel}/**/{m}.ko*", recursive=True)) or \
            bool(glob.glob(f"/usr/lib/modules/{rel}/**/{m}.ko*", recursive=True))
        kmods.append({"name": m, "why": why, "loaded": is_loaded, "available": avail})
    return {"family": fam, "deps": out, "install": cmd, "kmods": kmods}
