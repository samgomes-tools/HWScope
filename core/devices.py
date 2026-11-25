"""
Rede, bateria, ventoinhas, USB e áudio (somente leitura, sem root).
"""
from __future__ import annotations

import glob
import json
import os
import re
import socket

from . import hwinfo as hw
from .hwinfo import P, rd, rd_int, run

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------
# Rede
# --------------------------------------------------------------------------
def _default_routes():
    gw = {}
    for line in (rd(P("/proc/net/route")) or "").splitlines()[1:]:
        p = line.split()
        if len(p) >= 3 and p[1] == "00000000":
            g = int(p[2], 16)
            gw[p[0]] = socket.inet_ntoa(g.to_bytes(4, "little"))
    return gw


def _dns():
    out = []
    for line in (rd(P("/etc/resolv.conf")) or "").splitlines():
        if line.startswith("nameserver"):
            out.append(line.split()[1])
    if out == ["127.0.0.53"]:
        txt = run(["resolvectl", "dns"], timeout=2) or ""
        real = re.findall(r"(\d+\.\d+\.\d+\.\d+|[0-9a-f:]{6,})", txt)
        if real:
            return ", ".join(dict.fromkeys(real)) + " (via systemd-resolved)"
    return ", ".join(out) or None


def _wifi(name):
    info = {}
    for line in (rd(P("/proc/net/wireless")) or "").splitlines()[2:]:
        if line.strip().startswith(name + ":"):
            p = line.split()
            try:
                info["quality"] = float(p[2].rstrip("."))
                info["signal"] = float(p[3].rstrip("."))
            except (ValueError, IndexError):
                pass
    out = run(["iw", "dev", name, "link"], timeout=2)
    if out:
        m = re.search(r"SSID: (.+)", out)
        info["ssid"] = m.group(1).strip() if m else None
        m = re.search(r"freq: ([\d.]+)", out)
        if m:
            f = float(m.group(1))
            info["freq"] = f"{f / 1000:.3g} GHz" + (" (6 GHz)" if f > 5925 else "")
        m = re.search(r"rx bitrate: ([\d.]+ \S+)(.*)", out)
        if m:
            info["rx_rate"] = m.group(1)
            std = re.search(r"\b(EHT|HE|VHT|HT)", m.group(2))
            info["standard"] = {"EHT": "Wi-Fi 7 (802.11be)", "HE": "Wi-Fi 6/6E (802.11ax)",
                                "VHT": "Wi-Fi 5 (802.11ac)", "HT": "Wi-Fi 4 (802.11n)"}.get(std.group(1)) if std else None
        m = re.search(r"tx bitrate: ([\d.]+ \S+)", out)
        if m:
            info["tx_rate"] = m.group(1)
        m = re.search(r"signal: (-?\d+) dBm", out)
        if m:
            info["signal"] = float(m.group(1))
    elif not info.get("ssid"):
        nm = run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,RATE,FREQ", "dev", "wifi"], timeout=3)
        for line in (nm or "").splitlines():
            if line.startswith("yes:") or line.startswith("sim:"):
                p = line.split(":")
                info["ssid"] = p[1]
                info["nm_signal"] = p[2] + " %"
                info["rx_rate"] = p[3]
                info["freq"] = p[4] if len(p) > 4 else None
    return info


def net_interfaces():
    gws = _default_routes()
    addrs = psutil.net_if_addrs() if psutil else {}
    stats = psutil.net_if_stats() if psutil else {}
    res = []
    for d in sorted(glob.glob(P("/sys/class/net/*"))):
        name = os.path.basename(d)
        if name == "lo":
            continue
        dev = os.path.join(d, "device")
        virtual = not os.path.exists(dev)
        wireless = os.path.isdir(os.path.join(d, "wireless")) or os.path.isdir(os.path.join(d, "phy80211"))
        typ = "Wi-Fi" if wireless else ("Ethernet" if rd(os.path.join(d, "type")) == "1" else "Outro")
        if virtual:
            if name.startswith(("docker", "br-", "virbr", "veth", "vnet", "ifb", "tun", "tap", "wg", "tailscale", "zt")):
                typ = "Virtual"
            else:
                typ = "Virtual" if not wireless else typ
        drv = os.path.basename(os.path.realpath(os.path.join(dev, "driver"))) if os.path.exists(os.path.join(dev, "driver")) else None
        hwname = None
        bus = None
        if not virtual:
            real = os.path.realpath(dev)
            if os.path.exists(os.path.join(real, "vendor")) and os.path.exists(os.path.join(real, "device")) and "/usb" not in real:
                n = hw.pci_names(rd(os.path.join(real, "vendor")), rd(os.path.join(real, "device")))
                hwname = " ".join(x for x in (hw.VENDOR_SHORT.get(hw._hex(rd(os.path.join(real, "vendor"))) or "", n["vendor"]), n["device"]) if x)
                bus = "PCIe"
            elif "/usb" in real:
                bus = "USB"
                up = real
                for _ in range(4):
                    up = os.path.dirname(up)
                    if os.path.exists(os.path.join(up, "idVendor")):
                        hwname = " ".join(x for x in (rd(os.path.join(up, "manufacturer")), rd(os.path.join(up, "product"))) if x) or \
                            usb_name(rd(os.path.join(up, "idVendor")), rd(os.path.join(up, "idProduct")))
                        break
        speed = rd_int(os.path.join(d, "speed"))
        st = stats.get(name)
        ipv4, ipv6 = [], []
        for a in addrs.get(name, []):
            if a.family == socket.AF_INET:
                ipv4.append(f"{a.address}/{_prefix(a.netmask)}" if a.netmask else a.address)
            elif a.family == socket.AF_INET6 and not a.address.startswith("fe80"):
                ipv6.append(a.address.split("%")[0])
        item = {
            "name": name, "type": typ, "virtual": virtual, "hw": hwname, "bus": bus, "driver": drv,
            "driver_version": rd(P(f"/sys/module/{drv}/version")) if drv else None,
            "mac": rd(os.path.join(d, "address")), "mtu": rd(os.path.join(d, "mtu")),
            "state": {"up": "Conectado", "down": "Desconectado", "dormant": "Inativo"}.get(rd(os.path.join(d, "operstate")) or "", rd(os.path.join(d, "operstate"))),
            "speed": speed if speed and speed > 0 else None,
            "duplex": {"full": "Full-duplex", "half": "Half-duplex"}.get(rd(os.path.join(d, "duplex")) or ""),
            "ipv4": ipv4, "ipv6": ipv6, "gateway": gws.get(name),
            "up": bool(st.isup) if st else None,
        }
        if wireless:
            item["wifi"] = _wifi(name)
        res.append(item)
    res.sort(key=lambda x: (x["virtual"], x["state"] != "Conectado", x["name"]))
    return res


def _prefix(mask):
    try:
        return sum(bin(int(x)).count("1") for x in mask.split("."))
    except ValueError:
        return mask


def net_counters():
    if not psutil:
        return {}
    try:
        c = psutil.net_io_counters(pernic=True)
    except Exception:
        return {}
    return {k: (v.bytes_recv, v.bytes_sent, v.errin + v.errout, v.dropin + v.dropout) for k, v in c.items()}


def net_globals():
    return {"hostname": socket.gethostname(), "dns": _dns()}


# --------------------------------------------------------------------------
# Bateria
# --------------------------------------------------------------------------
def batteries():
    res, ac = [], None
    for d in sorted(glob.glob(P("/sys/class/power_supply/*"))):
        typ = rd(os.path.join(d, "type"))
        if typ == "Mains":
            ac = rd(os.path.join(d, "online")) == "1"
            continue
        if typ != "Battery" or rd(os.path.join(d, "scope")) == "Device":
            continue

        def g(n):
            return rd_int(os.path.join(d, n))
        ef, efd, en = g("energy_full"), g("energy_full_design"), g("energy_now")
        unit = "Wh"
        if ef is None:
            ef, efd, en = g("charge_full"), g("charge_full_design"), g("charge_now")
            unit = "Ah"
        vnow = g("voltage_now")
        pnow = g("power_now")
        cnow = g("current_now")
        watts = pnow / 1e6 if pnow else (cnow * vnow / 1e12 if cnow and vnow else None)
        status = rd(os.path.join(d, "status"))
        cap = g("capacity")
        tleft = None
        if watts and en is not None and unit == "Wh":
            if status == "Discharging":
                tleft = en / 1e6 / watts * 3600
            elif status == "Charging" and ef:
                tleft = (ef - en) / 1e6 / watts * 3600
        res.append({
            "name": os.path.basename(d), "manufacturer": rd(os.path.join(d, "manufacturer")),
            "model": rd(os.path.join(d, "model_name")), "serial": rd(os.path.join(d, "serial_number")),
            "technology": rd(os.path.join(d, "technology")),
            "status": {"Charging": "Carregando", "Discharging": "Descarregando", "Full": "Carregada",
                       "Not charging": "Não está carregando", "Unknown": "Desconhecido"}.get(status, status),
            "capacity": cap, "full": ef / 1e6 if ef else None, "design": efd / 1e6 if efd else None,
            "now": en / 1e6 if en is not None else None, "unit": unit,
            "health": ef / efd * 100 if ef and efd else None, "cycles": g("cycle_count"),
            "voltage": vnow / 1e6 if vnow else None, "voltage_design": g("voltage_min_design"),
            "watts": watts, "time_left": tleft, "raw_status": status,
            "threshold_end": g("charge_control_end_threshold"),
        })
    return res, ac


# --------------------------------------------------------------------------
# Ventoinhas
# --------------------------------------------------------------------------
def _cfg_path(name):
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "hwscope", name)


def load_fan_names():
    try:
        with open(_cfg_path("fans.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_fan_names(names):
    p = _cfg_path("fans.json")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump(names, f, indent=1, ensure_ascii=False)
        return True
    except OSError:
        return False


def fans(chips):
    """Todas as ventoinhas do hwmon, com PWM (%) quando disponível."""
    res = []
    for c in chips:
        for s in c["sensors"]:
            if s["type"] != "fan":
                continue
            idx = re.sub(r"\D", "", s["key"].split("/")[-1])
            pwm = rd_int(os.path.join(c["path"], f"pwm{idx}"))
            mode = rd(os.path.join(c["path"], f"pwm{idx}_enable"))
            # chave estável: nome do chip + dispositivo + índice
            dev = os.path.basename(c["device"]) if c.get("device") else c["id"]
            key = f"{c['name']}:{dev}:fan{idx}"
            res.append({"key": key, "skey": s["key"], "chip": c["title"], "chip_name": c["name"], "kind": c["kind"],
                        "label": s["label"], "rpm": s["value"], "pwm": round(pwm / 2.55) if pwm is not None else None,
                        "mode": {"0": "Máximo", "1": "Manual", "2": "Automático", "5": "Smart Fan"}.get(mode or "", mode),
                        "min": rd_int(os.path.join(c["path"], f"fan{idx}_min"))})
    return res


# --------------------------------------------------------------------------
# USB
# --------------------------------------------------------------------------
_USB = None

USB_CLASS = {"00": None, "01": "Áudio", "02": "Comunicação", "03": "HID (teclado/mouse)", "05": "Físico",
             "06": "Imagem/câmera", "07": "Impressora", "08": "Armazenamento", "09": "Hub", "0a": "Dados CDC",
             "0b": "Smart card", "0d": "Segurança", "0e": "Vídeo/webcam", "0f": "Saúde", "10": "Áudio/Vídeo",
             "11": "Billboard", "12": "USB-C bridge", "dc": "Diagnóstico", "e0": "Sem fio (Bluetooth)",
             "ef": "Diversos", "fe": "Específico", "ff": "Específico do fabricante"}


def _usb_db():
    global _USB
    if _USB is not None:
        return _USB
    vendors, products = {}, {}
    for cand in ("/usr/share/hwdata/usb.ids", "/usr/share/misc/usb.ids", "/var/lib/usbutils/usb.ids",
                 os.path.join(HERE, "data", "usb.ids")):
        if os.path.exists(cand):
            try:
                cur = None
                with open(cand, errors="replace") as f:
                    for line in f:
                        if line.startswith("#") or not line.strip():
                            continue
                        if line.startswith("C "):
                            break
                        if line[0] != "\t":
                            p = line.rstrip("\n").split("  ", 1)
                            if len(p) == 2:
                                cur = p[0].lower()
                                vendors[cur] = p[1].strip()
                        elif line[1] != "\t" and cur:
                            p = line.strip().split("  ", 1)
                            if len(p) == 2:
                                products[(cur, p[0].lower())] = p[1].strip()
                break
            except OSError:
                continue
    _USB = (vendors, products)
    return _USB


def usb_name(vid, pid):
    v, p = _usb_db()
    vid, pid = (vid or "").lower(), (pid or "").lower()
    return " ".join(x for x in (v.get(vid), p.get((vid, pid))) if x) or None


def _usb_speed(s):
    try:
        x = float(s)
    except (TypeError, ValueError):
        return s
    return {1.5: "USB 1.0 (1,5 Mb/s)", 12: "USB 1.1 (12 Mb/s)", 480: "USB 2.0 (480 Mb/s)",
            5000: "USB 3.2 Gen 1 (5 Gb/s)", 10000: "USB 3.2 Gen 2 (10 Gb/s)",
            20000: "USB 3.2 Gen 2x2 (20 Gb/s)", 40000: "USB4 (40 Gb/s)", 80000: "USB4 v2 (80 Gb/s)"}.get(x, f"{s} Mb/s")


def usb_devices():
    res = []
    for d in sorted(glob.glob(P("/sys/bus/usb/devices/*"))):
        b = os.path.basename(d)
        if ":" in b or not os.path.exists(os.path.join(d, "idVendor")):
            continue
        vid, pid = rd(os.path.join(d, "idVendor")), rd(os.path.join(d, "idProduct"))
        cls = (rd(os.path.join(d, "bDeviceClass")) or "00").lower()
        classes = []
        drivers = []
        for itf in sorted(glob.glob(d + "/" + b + ":*")):
            ic = (rd(os.path.join(itf, "bInterfaceClass")) or "").lower()
            if USB_CLASS.get(ic) and USB_CLASS[ic] not in classes:
                classes.append(USB_CLASS[ic])
            dl = os.path.join(itf, "driver")
            if os.path.exists(dl):
                dn = os.path.basename(os.path.realpath(dl))
                if dn not in drivers:
                    drivers.append(dn)
        if USB_CLASS.get(cls) and cls != "ef":
            classes.insert(0, USB_CLASS[cls])
        is_root = b.startswith("usb")
        name = " ".join(x for x in (rd(os.path.join(d, "manufacturer")), rd(os.path.join(d, "product"))) if x)
        dbn = usb_name(vid, pid)
        res.append({
            "path": b, "bus": rd(os.path.join(d, "busnum")), "port": b.split("-", 1)[1] if "-" in b else "raiz",
            "name": name or dbn or f"{vid}:{pid}", "db_name": dbn, "id": f"{vid}:{pid}",
            "speed": _usb_speed(rd(os.path.join(d, "speed"))), "version": rd(os.path.join(d, "version")),
            "class": ", ".join(classes) or "—", "driver": ", ".join(drivers) or None,
            "power": rd(os.path.join(d, "bMaxPower")), "serial": rd(os.path.join(d, "serial")),
            "root": is_root, "removable": rd(os.path.join(d, "removable")),
        })
    return res


# --------------------------------------------------------------------------
# Áudio
# --------------------------------------------------------------------------
def audio():
    cards = []
    txt = rd(P("/proc/asound/cards")) or ""
    for m in re.finditer(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(.+?)\s*\n\s+(.+)$", txt, re.M):
        idx, cid, drv, longname = m.group(1), m.group(2), m.group(3), m.group(4)
        cdir = P(f"/proc/asound/card{idx}")
        codecs = []
        for cf in sorted(glob.glob(os.path.join(cdir, "codec#*"))):
            head = (rd(cf) or "").splitlines()
            cd = {}
            for line in head[:12]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    cd[k.strip()] = v.strip()
            if cd.get("Codec"):
                codecs.append(cd["Codec"])
        pcms = []
        for pf in sorted(glob.glob(os.path.join(cdir, "pcm*p", "info"))) + sorted(glob.glob(os.path.join(cdir, "pcm*c", "info"))):
            info = rd(pf) or ""
            nm = re.search(r"^name: (.+)$", info, re.M)
            st = re.search(r"^stream: (\w+)", info, re.M)
            if nm:
                pcms.append(("Saída" if st and st.group(1) == "PLAYBACK" else "Entrada") + ": " + nm.group(1))
        sysdev = P(f"/sys/class/sound/card{idx}/device")
        hwname = None
        if os.path.exists(os.path.join(sysdev, "vendor")):
            n = hw.pci_names(rd(os.path.join(sysdev, "vendor")), rd(os.path.join(sysdev, "device")))
            hwname = n["device"]
        elif os.path.exists(sysdev):
            up = os.path.realpath(sysdev)
            for _ in range(3):
                if os.path.exists(os.path.join(up, "idVendor")):
                    hwname = rd(os.path.join(up, "product")) or usb_name(rd(os.path.join(up, "idVendor")), rd(os.path.join(up, "idProduct")))
                    break
                up = os.path.dirname(up)
        cards.append({"index": idx, "id": cid, "driver": drv, "name": longname, "hw": hwname,
                      "codecs": codecs, "pcms": pcms})
    server = None
    default_sink = default_source = None
    out = run(["pactl", "info"], timeout=3)
    if out:
        m = re.search(r"Server Name: (.+)", out)
        server = m.group(1).strip() if m else None
        m = re.search(r"Default Sink: (.+)", out)
        default_sink = m.group(1).strip() if m else None
        m = re.search(r"Default Source: (.+)", out)
        default_source = m.group(1).strip() if m else None
        sinks = run(["pactl", "list", "sinks"], timeout=3) or ""
        for blk in sinks.split("Sink #"):
            if default_sink and f"Name: {default_sink}" in blk:
                m = re.search(r"Description: (.+)", blk)
                if m:
                    default_sink = m.group(1).strip()
                m = re.search(r"Sample Specification: (.+)", blk)
                if m:
                    default_sink += f"  ({m.group(1).strip()})"
    return {"cards": cards, "server": server, "default_sink": default_sink, "default_source": default_source}
