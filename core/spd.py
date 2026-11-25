"""
Decodificação do SPD (Serial Presence Detect) de pentes DDR4 e DDR5.

DDR4 segue o JEDEC 21-C (mesmos offsets usados pelo decode-dimms do i2c-tools).
Perfis XMP 2.0 (DDR4), XMP 3.0 e EXPO (DDR5) são decodificados com
checagem de sanidade: perfis com valores incoerentes são descartados.
"""
from __future__ import annotations

import glob
import json
import math
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENDORS = None


def _vendors():
    global _VENDORS
    if _VENDORS is None:
        try:
            with open(os.path.join(HERE, "data", "jep106.json"), encoding="utf-8") as f:
                _VENDORS = json.load(f)
        except (OSError, ValueError):
            _VENDORS = []
    return _VENDORS


def _parity_ok(n):
    return bin(n).count("1") % 2 == 1


def jedec_vendor(bank, code):
    """bank = byte de continuação (com paridade), code = código JEP106 (com paridade)."""
    if (bank in (0, 0xFF) and code in (0, 0xFF)):
        return None
    b, c = bank & 0x7F, code & 0x7F
    v = _vendors()
    if c == 0 or b >= len(v) or c - 1 >= len(v[b]):
        return f"Desconhecido (0x{bank:02X}{code:02X})"
    name = v[b][c - 1]
    return name.split(" (former")[0]


def _bcd(x):
    return (x >> 4) * 10 + (x & 0xF)


def _signed(b):
    return b - 256 if b & 0x80 else b


def _text(bs):
    s = bytes(bs).decode("ascii", "replace").strip(" \x00\xff")
    return "".join(ch for ch in s if 32 <= ord(ch) < 127).strip() or None


def _cyc(t_ns, tck):
    return int(math.ceil(t_ns / tck - 0.025)) if tck else None


def _adjust_tck(tck):
    """Arredonda tCK aproximado para o valor padrão (ex.: 0.625 ns = 3200 MT/s)."""
    for mts in (1600, 1866, 2133, 2400, 2666, 2933, 3200, 3466, 3600, 3733, 3866, 4000, 4133, 4266,
                4400, 4600, 4800, 5000, 5200, 5600, 6000, 6200, 6400, 6600, 6800, 7000, 7200,
                7600, 8000, 8200, 8400, 8800):
        std = 2000.0 / mts
        if abs(tck - std) < 0.0015:
            return std
    return tck


# --------------------------------------------------------------------------
DDR4_TYPES = {1: "RDIMM", 2: "UDIMM", 3: "SO-DIMM", 4: "LRDIMM", 5: "Mini-RDIMM", 6: "Mini-UDIMM",
              8: "72b-SO-RDIMM", 9: "72b-SO-UDIMM", 12: "16b-SO-DIMM", 13: "32b-SO-DIMM"}
DDR5_TYPES = {1: "RDIMM", 2: "UDIMM", 3: "SO-DIMM", 4: "LRDIMM", 7: "MRDIMM", 10: "DDIMM",
              11: "Solder down", 14: "CUDIMM", 15: "CSODIMM"}


def _timing_row(label, tck, cl, trcd, trp, tras, trc, volt, extra=None):
    row = {"label": label, "freq": round(1000.0 / tck / 1) if tck else None,
           "mts": int(2000.0 / tck + 1e-6) if tck else None,
           "CL": cl, "tRCD": _cyc(trcd, tck), "tRP": _cyc(trp, tck), "tRAS": _cyc(tras, tck),
           "tRC": _cyc(trc, tck) if trc else None, "volt": volt}
    if extra:
        row.update(extra)
    return row


DDR3_TYPES = {1: "RDIMM", 2: "UDIMM", 3: "SO-DIMM", 4: "Micro-DIMM", 5: "Mini-RDIMM", 6: "Mini-UDIMM",
              7: "Mini-CDIMM", 8: "72b-SO-UDIMM", 9: "72b-SO-RDIMM", 10: "72b-SO-CDIMM", 11: "LRDIMM",
              12: "16b-SO-DIMM", 13: "32b-SO-DIMM"}


def _ddr3_tck(t):
    for i in range(7, 15):
        if abs(t - 7.5 / i) < 0.002:
            return 7.5 / i
    return t


def decode_ddr3(b):
    info = {"type": "DDR3"}
    ftb = ((b[9] >> 4) / (b[9] & 0x0F)) / 1000.0 if b[9] & 0x0F else 0.001
    mtb = b[10] / b[11] if b[11] else 0.125

    def mf(m, f):
        return m * mtb + _signed(f) * ftb
    info["module"] = DDR3_TYPES.get(b[3] & 0x0F, f"0x{b[3]:02X}")
    width = 4 << (b[7] & 7)
    ranks = ((b[7] >> 3) & 7) + 1
    bus = 8 << (b[8] & 7)
    exp = (b[4] & 15) + 28 + (b[8] & 7) + 3 - ((b[7] & 7) + 2)
    info.update(size=(1 << exp) * ranks // 8, ranks=ranks, width=f"x{width}", bus=bus,
                ecc="Sim" if b[8] & 0x18 else "Não", spd_rev=f"{b[1] >> 4}.{b[1] & 0xF}",
                thermal="Sim" if b[32] & 0x80 else "Não")
    volts = ["1.5 V"]
    if b[6] & 2:
        volts.append("1.35 V")
    if b[6] & 4:
        volts.append("1.25 V")
    info["voltage"] = " / ".join(volts)
    tck = _ddr3_tck(mf(b[12], b[34]))
    taa, trcd, trp = mf(b[16], b[35]), mf(b[18], b[36]), mf(b[20], b[37])
    tras = (((b[21] & 0x0F) << 8) + b[22]) * mtb
    trc = mf(((b[21] & 0xF0) << 4) + b[23], b[38])
    trfc = ((b[25] << 8) + b[24]) * mtb
    cas_sup = (b[15] << 8) + b[14]
    cas = [i + 4 for i in range(15) if cas_sup & (1 << i)]
    info["max_mts"] = int(round(2000 / tck)) if tck else None
    info["pc"] = f"PC3-{int(2000 / tck * bus / 8) // 100 * 100}" if tck else None
    info["cas_supported"] = cas
    info["raw_timings_ns"] = {"tCK": tck, "tAA": taa, "tRCD": trcd, "tRP": trp, "tRAS": tras, "tRC": trc, "tRFC1": trfc}
    rows = []
    for t in (2.5, 1.875, 1.5, 1.25, 7.5 / 7, 7.5 / 8):
        if t < tck - 0.001:
            continue
        need = int(math.ceil(taa / t - 0.01))
        cl = next((c for c in sorted(cas) if c >= need), None)
        if cl:
            rows.append(_timing_row(f"JEDEC #{len(rows) + 1}", t, cl, trcd, trp, tras, trc, "1.5 V"))
    if len(b) >= 150:
        info["manufacturer"] = jedec_vendor(b[117], b[118])
        info["dram_manufacturer"] = jedec_vendor(b[148], b[149])
        if b[120] not in (0, 0xFF):
            info["date"] = f"Semana {_bcd(b[121])}/20{_bcd(b[120]):02d}"
        info["serial"] = "".join(f"{x:02X}" for x in b[122:126])
        info["part"] = _text(b[128:146])
    # Intel XMP 1.x (DDR3)
    if len(b) >= 220 and b[176] == 0x0C and b[177] == 0x4A:
        info["xmp"] = f"XMP {b[179] >> 4}.{b[179] & 0xF}"
        for n, (moff, poff) in enumerate(((180, 185), (182, 220))):
            if not (b[178] >> n) & 1 or len(b) < poff + 12:
                continue
            xm = b[moff] / b[moff + 1] if b[moff + 1] else mtb
            p = poff
            v = b[p]
            volt = ((v >> 5) & 3) + (v & 0x1F) * 0.05
            xtck = _ddr3_tck(b[p + 1] * xm)
            if not xtck:
                continue
            xtaa, xtrp, xtrcd = b[p + 2] * xm, b[p + 6] * xm, b[p + 7] * xm
            xtras = (((b[p + 9] & 0x0F) << 8) + b[p + 10]) * xm
            xtrc = (((b[p + 9] & 0xF0) << 4) + b[p + 11]) * xm
            row = _timing_row(f"XMP-{int(round(2000 / xtck))}", xtck, _cyc(xtaa, xtck), xtrcd, xtrp, xtras, xtrc,
                              f"{volt:.2f} V" if 1.1 <= volt <= 1.9 else "—")
            if _sane(row, 1066, 3200):
                rows.append(row)
    info["timings"] = rows
    return info


def decode_ddr4(b):
    info = {"type": "DDR4"}
    mtb, ftb = 0.125, 0.001

    def mf(m, f):
        return m * mtb + _signed(f) * ftb

    info["module"] = DDR4_TYPES.get(b[3] & 0xF, f"0x{b[3]:02X}")
    width = 4 << (b[12] & 7)
    ranks = ((b[12] >> 3) & 7) + 1
    bus = 8 << (b[13] & 7)
    dies = ((b[6] >> 4) & 7) + 1
    cap_mb = (256 << (b[4] & 0xF)) // 8 * (bus // width) * ranks
    if (b[6] & 3) == 2:
        cap_mb *= dies
    info.update(size=cap_mb * 1024 * 1024, ranks=ranks, width=f"x{width}", bus=bus,
                banks=(1 << (b[4] >> 6)) * (4 << ((b[4] >> 4) & 3)),
                thermal="Sim (TSE2004)" if b[14] & 0x80 else "Não",
                ecc="Sim" if b[13] & 0x18 else "Não", spd_rev=f"{b[1] >> 4}.{b[1] & 0xF}",
                voltage="1.20 V")
    tck = _adjust_tck(mf(b[18], b[125]))
    tck_max = mf(b[19], b[124])
    taa, trcd, trp = mf(b[24], b[123]), mf(b[25], b[122]), mf(b[26], b[121])
    tras = (((b[27] & 0xF) << 8) + b[28]) * mtb
    trc = mf(((b[27] & 0xF0) << 4) + b[29], b[120])
    trfc = ((b[31] << 8) + b[30]) * mtb
    cas_sup = b[20] | (b[21] << 8) | (b[22] << 16) | (b[23] << 24)
    base = 23 if b[23] & 0x80 else 7
    cas = [base + i for i in range(30) if cas_sup & (1 << i)]
    info["max_mts"] = int(round(2000 / tck))
    info["pc"] = f"PC4-{(int(2000 / tck * bus / 8)) // 100 * 100}"
    info["cas_supported"] = cas
    info["raw_timings_ns"] = {"tCK": tck, "tAA": taa, "tRCD": trcd, "tRP": trp, "tRAS": tras, "tRC": trc, "tRFC1": trfc}
    rows = []
    for mts in (1600, 1866, 2133, 2400, 2666, 2933, 3200):
        t = 2000.0 / mts
        if t < tck - 0.001 or t > tck_max + 0.001:
            continue
        cl = next((c for c in sorted(cas) if c >= _cyc(taa, t)), None)
        if cl:
            rows.append(_timing_row(f"JEDEC #{len(rows) + 1}", t, cl, trcd, trp, tras, trc, "1.20 V"))
    info["timings"] = rows
    # Fabricante / identificação (bytes 320-351)
    if len(b) >= 352:
        info["manufacturer"] = jedec_vendor(b[320], b[321])
        info["dram_manufacturer"] = jedec_vendor(b[350], b[351])
        if b[323] not in (0, 0xFF):
            info["date"] = f"Semana {_bcd(b[324])}/20{_bcd(b[323]):02d}"
        info["serial"] = "".join(f"{x:02X}" for x in b[325:329])
        info["part"] = _text(b[329:349])
    # XMP 2.0
    if len(b) >= 440 and b[384] == 0x0C and b[385] == 0x4A:
        info["xmp"] = f"XMP {b[387] >> 4}.{b[387] & 0xF}"
        for n, base_off, enabled in ((1, 393, b[386] & 1), (2, 440, b[386] & 2)):
            if not enabled or len(b) < base_off + 47:
                continue
            p = base_off
            v = b[p]
            volt = (v >> 7) + (v & 0x7F) / 100.0
            xtck = _adjust_tck(mf(b[p + 3], b[p + 38]))
            xtaa = mf(b[p + 8], b[p + 37])
            xtrcd = mf(b[p + 9], b[p + 36])
            xtrp = mf(b[p + 10], b[p + 35])
            xtras = (((b[p + 11] & 0xF) << 8) + b[p + 12]) * mtb
            xtrc = mf(((b[p + 11] & 0xF0) << 4) + b[p + 13], b[p + 34])
            row = _timing_row(f"XMP-{int(round(2000 / xtck)) if xtck else '?'}", xtck, _cyc(xtaa, xtck),
                              xtrcd, xtrp, xtras, xtrc, f"{volt:.2f} V")
            if _sane(row, 2133, 6000):
                rows.append(row)
    return info


def decode_ddr5(b):
    info = {"type": "DDR5", "voltage": "1.10 V"}

    def ps(i):
        return (b[i] | (b[i + 1] << 8)) / 1000.0  # ns

    info["module"] = DDR5_TYPES.get(b[3] & 0xF, f"0x{b[3]:02X}")
    dens = {1: 4, 2: 8, 3: 12, 4: 16, 5: 24, 6: 32, 7: 48, 8: 64}.get(b[4] & 0x1F, 0)
    dies = {0: 1, 2: 2, 3: 4, 4: 8, 5: 16}.get((b[4] >> 5) & 7, 1)
    io = 4 << ((b[6] >> 5) & 3)
    ranks = ((b[234] >> 3) & 7) + 1 if len(b) > 235 else 1
    ch_bus = 8 << (b[235] & 7) if len(b) > 235 else 32
    channels = (((b[235] >> 5) & 3) + 1) if len(b) > 235 else 2
    size_gbit = dens * dies * (ch_bus // io) * ranks * channels
    info.update(size=size_gbit * 1024 ** 3 // 8, ranks=ranks, width=f"x{io}", bus=ch_bus * channels,
                channels=channels, spd_rev=f"{b[1] >> 4}.{b[1] & 0xF}",
                thermal="Sim (SPD5118)", ecc="Sim" if len(b) > 235 and (b[235] >> 3) & 3 else "Não")
    tck = _adjust_tck(ps(20))
    tck_max = ps(22) or 1.0
    taa, trcd, trp, tras, trc = ps(30), ps(32), ps(34), ps(36), ps(38)
    cas_sup = sum(b[24 + i] << (8 * i) for i in range(5))
    cas = [20 + 2 * i for i in range(40) if cas_sup & (1 << i)]
    info["max_mts"] = int(round(2000 / tck)) if tck else None
    info["pc"] = f"PC5-{int(2000 / tck * 8) // 100 * 100}" if tck else None
    info["cas_supported"] = cas
    rows = []
    for mts in (3200, 3600, 4000, 4400, 4800, 5200, 5600, 6000, 6400, 6800, 7200, 7600, 8000, 8400, 8800):
        t = 2000.0 / mts
        if t < tck - 0.001 or t > tck_max + 0.001:
            continue
        need = _cyc(taa, t)
        cl = next((c for c in sorted(cas) if c >= need), None)
        if cl:
            rows.append(_timing_row(f"JEDEC #{len(rows) + 1}", t, cl, trcd, trp, tras, trc, "1.10 V"))
    if len(b) >= 554:
        info["manufacturer"] = jedec_vendor(b[512], b[513])
        info["dram_manufacturer"] = jedec_vendor(b[552], b[553])
        if b[515] not in (0, 0xFF):
            info["date"] = f"Semana {_bcd(b[516])}/20{_bcd(b[515]):02d}"
        info["serial"] = "".join(f"{x:02X}" for x in b[517:521])
        info["part"] = _text(b[521:551])
    # XMP 3.0 (0x280) — perfis de 64 bytes a partir de 0x2C0
    if len(b) >= 0x400 and b[0x280] == 0x0C and b[0x281] == 0x4A:
        info["xmp"] = f"XMP {b[0x282] >> 4}.{b[0x282] & 0xF}"
        for n in range(3):
            p = 0x2C0 + n * 0x40
            if not (b[0x283] >> n) & 1:
                continue
            row = _ddr5_profile(b, p, "XMP-")
            if row and _sane(row, 4000, 10000):
                rows.append(row)
    # AMD EXPO (assinatura "EXPO" em 0x340)
    if len(b) >= 0x3C0 and bytes(b[0x340:0x344]) == b"EXPO":
        info["expo"] = "EXPO"
        for n in range(2):
            p = 0x34A + n * 0x28
            row = _ddr5_profile_expo(b, p)
            if row and _sane(row, 4000, 10000):
                rows.append(row)
    info["timings"] = rows
    return info


def _ddr5_volt(v):
    return ((v >> 5) & 3) + (v & 0x1F) * 0.05


def _ddr5_profile(b, p, prefix):
    def ps(i):
        return (b[i] | (b[i + 1] << 8)) / 1000.0
    tck = ps(p + 4)
    if not tck:
        return None
    tck = _adjust_tck(tck)
    cl = _cyc(ps(p + 12), tck)
    return _timing_row(f"{prefix}{int(round(2000 / tck))}", tck, cl + (cl % 2), ps(p + 14), ps(p + 16),
                       ps(p + 18), ps(p + 20), f"{_ddr5_volt(b[p]):.2f} V")


def _ddr5_profile_expo(b, p):
    def ps(i):
        return (b[i] | (b[i + 1] << 8)) / 1000.0
    tck = ps(p + 4)
    if not tck:
        return None
    tck = _adjust_tck(tck)
    cl = _cyc(ps(p + 6), tck)
    return _timing_row(f"EXPO-{int(round(2000 / tck))}", tck, cl + (cl % 2), ps(p + 8), ps(p + 10),
                       ps(p + 12), ps(p + 14), f"{_ddr5_volt(b[p]):.2f} V")


def _sane(row, lo, hi):
    try:
        return (lo <= row["mts"] <= hi and 8 <= row["CL"] <= 80 and 8 <= row["tRCD"] <= 90
                and 8 <= row["tRP"] <= 90 and 15 <= row["tRAS"] <= 200)
    except (TypeError, KeyError):
        return False


def decode(data):
    b = list(data)
    if len(b) < 128:
        return None
    t = b[2]
    try:
        if t == 0x0C:
            return decode_ddr4(b)
        if t in (0x12, 0x13):  # DDR5 / LPDDR5 não suportado em detalhes
            return decode_ddr5(b) if t == 0x12 else {"type": "LPDDR5"}
        if t == 0x0B:
            return decode_ddr3(b) if len(b) >= 128 else {"type": "DDR3"}
    except (IndexError, ZeroDivisionError):
        return {"type": f"0x{t:02X}", "error": "SPD incompleto"}
    return {"type": f"0x{t:02X}"}


# --------------------------------------------------------------------------
SPD_GLOBS = ["/sys/bus/i2c/drivers/ee1004/*/eeprom",
             "/sys/bus/i2c/drivers/spd5118/*/eeprom",
             "/sys/bus/nvmem/devices/spd5118*/nvmem",
             "/sys/bus/i2c/drivers/ee1004/*/nvmem",
             "/sys/bus/i2c/drivers/eeprom/*/eeprom"]


def spd_paths(root=""):
    out = []
    seen = set()
    for g in SPD_GLOBS:
        for p in sorted(glob.glob(root + g)):
            dev = os.path.realpath(os.path.dirname(p))
            if dev in seen:
                continue
            seen.add(dev)
            out.append(p)
    return out


def _addr(path):
    # .../0-0051/eeprom  -> 0x51
    for part in path.split("/"):
        if "-00" in part:
            try:
                return "0x" + part.split("-")[1][2:]
            except IndexError:
                pass
    return os.path.basename(os.path.dirname(path))


# Script executado como root (pkexec). Carrega os drivers do barramento SMBus e
# de SPD, instancia os EEPROMs nos endereços 0x50-0x57 se o kernel não fez isso
# sozinho e despeja o conteúdo em hexadecimal. Só LÊ o SPD.
PRIV_SCRIPT = r"""
TYPE="$1"
log() { echo "#LOG $*"; }
for m in i2c_dev i2c_i801 i2c_piix4 ee1004 spd5118 at24; do
  if modprobe "$m" 2>/dev/null; then log "driver $m carregado"; else log "driver $m indisponível"; fi
done
sleep 0.3
count() { ls /sys/bus/i2c/drivers/ee1004/*/eeprom /sys/bus/i2c/drivers/spd5118/*/eeprom \
            /sys/bus/i2c/drivers/spd5118/*/*/nvmem /sys/bus/i2c/drivers/at24/*-005[0-7]/eeprom \
            /sys/bus/i2c/drivers/eeprom/*/eeprom 2>/dev/null | wc -l; }
log "EEPROMs SPD já expostos: $(count)"
CREATED=""
if [ "$(count)" = "0" ]; then
  case "$TYPE" in
    DDR3|DDR3L|LPDDR3) DRVS="spd" ;;
    DDR4) DRVS="ee1004" ;;
    DDR5) DRVS="spd5118" ;;
    *) DRVS="spd5118 spd" ;;
  esac
  for a in /sys/bus/i2c/devices/i2c-*; do
    [ -e "$a/new_device" ] || continue
    n=$(cat "$a/name" 2>/dev/null)
    case "$n" in
      *PIIX4*port\ 0*|*I801*|*i801*|*"SMBus PIIX4 adapter at"*) ;;
      *) continue ;;
    esac
    bus=${a##*-}
    log "barramento SMBus encontrado: i2c-$bus ($n)"
    for drv in $DRVS; do
      for addr in 50 51 52 53 54 55 56 57; do
        dev="/sys/bus/i2c/devices/$bus-00$addr"
        [ -e "$dev" ] && continue
        if echo "$drv 0x$addr" > "$a/new_device" 2>/dev/null; then
          sleep 0.1
          if [ -e "$dev/driver" ]; then
            log "pente detectado em i2c-$bus 0x$addr ($drv)"
            CREATED="$CREATED $bus:$addr"
          else
            echo "0x$addr" > "$a/delete_device" 2>/dev/null
          fi
        fi
      done
    done
  done
fi
# Sensor térmico dos pentes DDR3/DDR4 (TSOD, endereços 0x18-0x1F): o driver jc42 só se
# associa se o chip responder com IDs válidos, então a tentativa é segura.
case "$TYPE" in DDR3|DDR3L|DDR4|"")
  modprobe jc42 2>/dev/null
  for a in /sys/bus/i2c/devices/i2c-*; do
    [ -e "$a/new_device" ] || continue
    n=$(cat "$a/name" 2>/dev/null)
    case "$n" in *PIIX4*port\ 0*|*I801*|*i801*|*"SMBus PIIX4 adapter at"*) ;; *) continue ;; esac
    bus=${a##*-}
    for addr in 18 19 1a 1b 1c 1d 1e 1f; do
      dev="/sys/bus/i2c/devices/$bus-00$addr"
      [ -e "$dev" ] && continue
      if echo "jc42 0x$addr" > "$a/new_device" 2>/dev/null; then
        sleep 0.1
        if [ -e "$dev/driver" ]; then log "sensor térmico do pente em i2c-$bus 0x$addr (jc42)"
        else echo "0x$addr" > "$a/delete_device" 2>/dev/null; fi
      fi
    done
  done ;;
esac
for f in /sys/bus/i2c/drivers/ee1004/*/eeprom /sys/bus/i2c/drivers/spd5118/*/eeprom \
         /sys/bus/i2c/drivers/spd5118/*/*/nvmem /sys/bus/i2c/drivers/eeprom/*/eeprom \
         /sys/bus/i2c/drivers/at24/*-005[0-7]/eeprom; do
  [ -e "$f" ] || continue
  hex=$(od -An -v -tx1 -N 1024 "$f" 2>/dev/null | tr -d '\n')
  if [ -n "$hex" ]; then
    echo "==$f"; echo "$hex"
  else
    log "falha ao ler $f"
    case "$f" in */drivers/ee1004/*|*/drivers/at24/*)
      d=$(basename "$(dirname "$f")"); b=${d%%-*}; ad=${d##*-00}
      case "$CREATED" in *"$b:$ad"*) echo "0x$ad" > "/sys/bus/i2c/devices/i2c-$b/delete_device" 2>/dev/null ;; esac ;;
    esac
  fi
done
"""


def parse_priv_output(stdout):
    """Interpreta a saída do PRIV_SCRIPT -> (módulos, mensagem)."""
    raw, logs, cur = {}, [], None
    for line in (stdout or "").splitlines():
        if line.startswith("#LOG "):
            logs.append(line[5:])
        elif line.startswith("=="):
            cur = line[2:]
        elif cur:
            try:
                raw[cur] = bytes(int(x, 16) for x in line.split())
            except ValueError:
                pass
            cur = None
    mods = []
    for p, data in raw.items():
        if len(data) >= 128:
            d = decode(data)
            if d:
                d["address"] = _addr(p)
                mods.append(d)
    if mods:
        msg = ""
    elif not any("barramento SMBus encontrado" in x for x in logs) and any("já expostos: 0" in x for x in logs):
        msg = ("nenhum barramento SMBus de memória acessível (o firmware da placa pode bloquear o acesso, "
               "ou o kernel ainda não suporta o controlador SMBus desta placa)")
    else:
        msg = "nenhum pente respondeu no barramento SMBus"
    if logs:
        msg = (msg + "\n\nRegistro:\n  " + "\n  ".join(logs)).strip()
    return mods, msg


def read_all(root="", env=None):
    """Leitura sem privilégios (quando o kernel já expõe os EEPROMs legíveis)."""
    paths = spd_paths(root)
    if not paths:
        return [], "nenhum EEPROM SPD exposto pelo kernel ainda"
    mods, denied = [], False
    for p in paths:
        try:
            with open(p, "rb") as f:
                data = f.read(1024)
        except PermissionError:
            denied = True
            continue
        except OSError:
            continue
        if len(data) >= 128:
            d = decode(data)
            if d:
                d["address"] = _addr(p)
                mods.append(d)
    msg = "" if mods else ("leitura do SPD requer administrador" if denied else "não foi possível ler o SPD")
    return mods, msg
