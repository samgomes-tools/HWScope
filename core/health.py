"""
Saúde dos discos no estilo do CrystalDiskInfo.

- Sem senha: propriedades SMART que o UDisks2 já mantém (udisksctl dump).
- Completo: smartctl -j -a via pkexec, com nota Bom / Cuidado / Ruim, % de vida
  útil e tabela de atributos.
- Histórico em ~/.config/hwscope/smart_history.json para avisar quando setores
  realocados/pendentes ou erros de mídia aumentam.
"""
from __future__ import annotations

import json
import os
import re
import time

GOOD, CAUTION, BAD, UNKNOWN = "Bom", "Cuidado", "Ruim", "Desconhecido"
COLORS = {GOOD: "#4fd18b", CAUTION: "#f5c542", BAD: "#ff5d5d", UNKNOWN: "#8a93a3"}

ATA_NAMES = {
    1: "Taxa de erros de leitura", 3: "Tempo de partida", 4: "Partidas/paradas", 5: "Setores realocados",
    7: "Taxa de erros de busca", 9: "Horas ligado", 10: "Tentativas de partida", 12: "Ciclos de energia",
    170: "Blocos reservados disponíveis", 171: "Falhas de programação", 172: "Falhas de apagamento",
    173: "Desgaste (média de apagamentos)", 174: "Desligamentos inesperados", 177: "Nivelamento de desgaste",
    179: "Blocos reservados usados", 181: "Falhas de programação", 182: "Falhas de apagamento",
    183: "Erros SATA (downshift)", 184: "Erros fim-a-fim", 187: "Erros não corrigíveis reportados",
    188: "Timeouts de comando", 189: "Escritas com cabeça alta", 190: "Temperatura do ar",
    191: "Sensor de impacto", 192: "Desligamentos de emergência", 193: "Ciclos de carga",
    194: "Temperatura", 195: "ECC recuperados", 196: "Eventos de realocação", 197: "Setores pendentes",
    198: "Setores incorrigíveis (offline)", 199: "Erros CRC (cabo SATA)", 200: "Taxa de erros de escrita",
    202: "Vida útil usada (%)", 230: "Vida útil (Samsung)", 231: "Vida útil restante (%)",
    232: "Reserva disponível", 233: "Indicador de desgaste", 234: "Dados lidos", 235: "Blocos bons/livres",
    240: "Horas de voo da cabeça", 241: "Total escrito (LBAs)", 242: "Total lido (LBAs)",
    246: "Total de escritas do host", 247: "Páginas escritas (host)", 248: "Páginas escritas (FTL)",
}
# atributos que indicam defeito quando o valor bruto > 0
CRITICAL_RAW = {5: "setores realocados", 196: "eventos de realocação", 197: "setores pendentes",
                198: "setores incorrigíveis", 187: "erros não corrigíveis"}
LIFE_ATTRS = (231, 233, 177, 169, 202)


# --------------------------------------------------------------------------
# UDisks2 (sem root)
# --------------------------------------------------------------------------
def parse_udisks(txt):
    """Devolve {bloco: {...propriedades SMART do drive...}}."""
    objs, cur, props = {}, None, {}
    for line in txt.splitlines():
        if line.startswith("/org/freedesktop/UDisks2/") and line.rstrip().endswith(":"):
            if cur:
                objs[cur] = props
            cur, props = line.strip().rstrip(":"), {}
            continue
        s = line.strip()
        if cur and ":" in s and not s.startswith("org.freedesktop"):
            k, v = s.split(":", 1)
            k = k.strip()
            if k not in props or props[k] in ("", "0"):
                props[k] = v.strip()
    if cur:
        objs[cur] = props
    out = {}
    for path, p in objs.items():
        if "/block_devices/" not in path:
            continue
        blk = os.path.basename(path)
        drv = (p.get("Drive") or "").strip("'\"")
        if not drv or drv == "/" or not re.match(r"^(sd[a-z]+|nvme\d+n\d+|hd[a-z]+|vd[a-z]+|mmcblk\d+)$", blk):
            continue
        d = objs.get(drv, {})
        if not d:
            continue
        out[blk] = _udisks_assess(d)
    return out


def _num(v, cast=float):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def _udisks_assess(d):
    info = {"source": "UDisks2", "reasons": []}
    supported = d.get("SmartSupported")
    if "SmartCriticalWarning" in d or "SmartPowerOnHours" in d:  # NVMe
        info["kind"] = "nvme"
        hours = _num(d.get("SmartPowerOnHours"), int)
        crit = d.get("SmartCriticalWarning", "")
        crit_list = re.findall(r"'(\w+)'", crit)
        info["hours"] = hours
        if crit_list:
            info["status"] = BAD
            info["reasons"].append("Aviso crítico do controlador: " + ", ".join(crit_list))
        else:
            info["status"] = GOOD if hours is not None or d.get("SmartUpdated") else UNKNOWN
    else:
        info["kind"] = "ata"
        if supported in ("false", "False") or d.get("SmartEnabled") in ("false", "False"):
            info["status"] = UNKNOWN
            info["reasons"].append("SMART não suportado ou desativado")
            return info
        secs = _num(d.get("SmartPowerOnSeconds"), int)
        info["hours"] = secs // 3600 if secs else None
        bad = _num(d.get("SmartNumBadSectors"), int) or 0
        failing_attrs = _num(d.get("SmartNumAttributesFailing"), int) or 0
        past = _num(d.get("SmartNumAttributesFailedInThePast"), int) or 0
        info["bad_sectors"] = bad
        status = GOOD
        if d.get("SmartFailing") in ("true", "True"):
            status = BAD
            info["reasons"].append("O próprio disco prevê falha (SMART FAILING)")
        if failing_attrs:
            status = BAD
            info["reasons"].append(f"{failing_attrs} atributo(s) abaixo do limite")
        if bad:
            status = BAD if status == BAD else CAUTION
            info["reasons"].append(f"{bad} setor(es) defeituoso(s) (realocados + pendentes)")
        if past:
            info["reasons"].append(f"{past} atributo(s) já falharam no passado")
            if status == GOOD:
                status = CAUTION
        if not d.get("SmartUpdated") or d.get("SmartUpdated") == "0":
            status = UNKNOWN if status == GOOD else status
        info["status"] = status
    t = _num(d.get("SmartTemperature"))
    if t and t > 200:
        info["temp"] = round(t - 273.15)
    st = d.get("SmartSelftestStatus")
    if st:
        info["selftest"] = {"success": "Último autoteste: OK", "inprogress": "Autoteste em andamento"}.get(st, f"Último autoteste: {st}")
        if st not in ("success", "inprogress", "aborted", "interrupted", ""):
            info["status"] = BAD
            info["reasons"].append(f"Último autoteste falhou ({st})")
    return info


# --------------------------------------------------------------------------
# smartctl (completo)
# --------------------------------------------------------------------------
def assess_smartctl(j):
    res = {"source": "smartctl", "reasons": [], "attrs": [], "life": None, "status": GOOD}
    if "error" in j:
        return {"error": j["error"]}
    msgs = [m.get("string", "") for m in j.get("smartctl", {}).get("messages", [])]
    st = j.get("smart_status", {})
    if "passed" not in st and not j.get("ata_smart_attributes") and not j.get("nvme_smart_health_information_log"):
        return {"error": "; ".join(msgs) or "SMART indisponível para este dispositivo"}
    if st.get("passed") is False:
        res["status"] = BAD
        res["reasons"].append("SMART overall-health: FALHOU")
    res["model"] = j.get("model_name")
    res["serial"] = j.get("serial_number")
    res["firmware"] = j.get("firmware_version")
    res["hours"] = j.get("power_on_time", {}).get("hours")
    res["cycles"] = j.get("power_cycle_count")
    res["temp"] = j.get("temperature", {}).get("current")
    rot = j.get("rotation_rate")
    res["rotation"] = f"{rot} RPM" if isinstance(rot, int) and rot > 0 else ("SSD" if rot == 0 else None)
    ifs = j.get("interface_speed", {})
    if ifs:
        res["iface"] = f"{ifs.get('current', {}).get('string', '?')} (máx {ifs.get('max', {}).get('string', '?')})"
    nv = j.get("nvme_smart_health_information_log")
    counters = {}
    if nv:
        res["kind"] = "nvme"
        cw = nv.get("critical_warning", 0)
        if cw:
            res["status"] = BAD
            res["reasons"].append(f"Aviso crítico NVMe (0x{cw:02X})")
        used = nv.get("percentage_used")
        if used is not None:
            res["life"] = max(0, 100 - used)
            if used >= 100:
                res["status"] = BAD
                res["reasons"].append("Vida útil nominal esgotada (100% usada)")
            elif used >= 90 and res["status"] == GOOD:
                res["status"] = CAUTION
                res["reasons"].append(f"{used}% da vida útil nominal já usada")
        spare, thr = nv.get("available_spare"), nv.get("available_spare_threshold")
        if spare is not None and thr is not None and spare < thr:
            res["status"] = BAD
            res["reasons"].append(f"Reserva disponível ({spare}%) abaixo do limite ({thr}%)")
        me = nv.get("media_errors", 0)
        counters["media_errors"] = me
        if me and res["status"] == GOOD:
            res["status"] = CAUTION
            res["reasons"].append(f"{me} erro(s) de mídia/integridade")
        labels = [("critical_warning", "Aviso crítico", lambda v: f"0x{v:02X}"),
                  ("temperature", "Temperatura", lambda v: f"{v} °C"),
                  ("available_spare", "Reserva disponível", lambda v: f"{v} %"),
                  ("available_spare_threshold", "Limite da reserva", lambda v: f"{v} %"),
                  ("percentage_used", "Vida útil usada", lambda v: f"{v} %"),
                  ("data_units_read", "Dados lidos", lambda v: _tb(v * 512000)),
                  ("data_units_written", "Dados escritos", lambda v: _tb(v * 512000)),
                  ("host_reads", "Comandos de leitura", str), ("host_writes", "Comandos de escrita", str),
                  ("controller_busy_time", "Tempo ocupado (min)", str),
                  ("power_cycles", "Ciclos de energia", str), ("power_on_hours", "Horas ligado", str),
                  ("unsafe_shutdowns", "Desligamentos inseguros", str),
                  ("media_errors", "Erros de mídia", str), ("num_err_log_entries", "Entradas no log de erros", str),
                  ("warning_temp_time", "Minutos acima da temp. de aviso", str),
                  ("critical_comp_time", "Minutos acima da temp. crítica", str)]
        for k, lab, f in labels:
            if k in nv:
                res["attrs"].append({"id": "", "name": lab, "value": f(nv[k]), "worst": "", "thresh": "", "raw": "", "flag": ""})
        res["written"] = _tb(nv.get("data_units_written", 0) * 512000) if nv.get("data_units_written") else None
    else:
        res["kind"] = "ata"
        rows = j.get("ata_smart_attributes", {}).get("table", [])
        for a in rows:
            aid = a.get("id")
            raw = a.get("raw", {}).get("value", 0)
            raw_s = a.get("raw", {}).get("string", str(raw))
            flag = ""
            wf = a.get("when_failed", "")
            if wf == "now":
                res["status"] = BAD
                res["reasons"].append(f"Atributo {aid} ({a.get('name')}) abaixo do limite AGORA")
                flag = "falhando"
            elif wf == "past":
                flag = "falhou antes"
            if aid in CRITICAL_RAW and isinstance(raw, int) and raw > 0:
                counters[CRITICAL_RAW[aid]] = raw
                flag = flag or "atenção"
                if res["status"] == GOOD:
                    res["status"] = CAUTION
                res["reasons"].append(f"{raw} {CRITICAL_RAW[aid]}")
            if aid == 199 and isinstance(raw, int) and raw > 0:
                flag = flag or "cabo?"
            res["attrs"].append({"id": f"{aid:02X}", "name": ATA_NAMES.get(aid, a.get("name", "").replace("_", " ")),
                                 "value": a.get("value"), "worst": a.get("worst"), "thresh": a.get("thresh"),
                                 "raw": raw_s, "flag": flag})
            if res["life"] is None and aid in LIFE_ATTRS:
                v = a.get("value")
                if aid == 202 and isinstance(raw, int) and raw <= 100:
                    res["life"] = 100 - raw
                elif isinstance(v, int) and 0 < v <= 100:
                    res["life"] = v
            if aid in (241, 246) and isinstance(raw, int) and raw:
                res["written"] = _tb(raw * 512) if aid == 241 else None
        if res["life"] is not None and res["life"] <= 10 and res["status"] == GOOD:
            res["status"] = CAUTION
            res["reasons"].append(f"Vida útil restante baixa ({res['life']}%)")
    res["counters"] = counters
    st_log = (j.get("ata_smart_self_test_log", {}).get("standard", {}).get("table") or
              j.get("nvme_self_test_log", {}).get("table") or [])
    if st_log:
        last = st_log[0]
        s = last.get("status", {})
        txt = s.get("string") if isinstance(s, dict) else str(s)
        res["selftest"] = f"Último autoteste: {txt}"
        if isinstance(s, dict) and s.get("passed") is False:
            res["status"] = BAD
            res["reasons"].append("Último autoteste falhou")
    return res


def _tb(b):
    if b >= 1e12:
        return f"{b / 1e12:.2f} TB"
    return f"{b / 1e9:.1f} GB"


# --------------------------------------------------------------------------
# Histórico (alerta de piora)
# --------------------------------------------------------------------------
def _hist_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "hwscope", "smart_history.json")


def compare_and_store(serial, counters):
    """Compara contadores com a leitura anterior do mesmo disco e grava a atual.
    Devolve lista de avisos de piora."""
    if not serial:
        return []
    path = _hist_path()
    try:
        with open(path) as f:
            hist = json.load(f)
    except (OSError, ValueError):
        hist = {}
    prev = hist.get(serial)
    warns = []
    if prev:
        for k, v in counters.items():
            old = prev["counters"].get(k, 0)
            if v > old:
                warns.append(f"{k}: {old} → {v} desde {prev['date']}")
    hist[serial] = {"date": time.strftime("%d/%m/%Y %H:%M"), "counters": counters}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(hist, f, indent=1)
    except OSError:
        pass
    return warns
