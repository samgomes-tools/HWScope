"""
Base de codinomes de CPUs x86 (família/modelo CPUID -> codinome, processo, soquete).
Valores de soquete são os típicos de desktop; notebooks usam BGA.
"""
import re

# (família, modelo) -> (codinome, tecnologia, soquete desktop/geral)
INTEL = {
    0x2A: ("Sandy Bridge", "32 nm", "LGA 1155"), 0x2D: ("Sandy Bridge-E", "32 nm", "LGA 2011"),
    0x3A: ("Ivy Bridge", "22 nm", "LGA 1155"), 0x3E: ("Ivy Bridge-E", "22 nm", "LGA 2011"),
    0x3C: ("Haswell", "22 nm", "LGA 1150"), 0x45: ("Haswell-ULT", "22 nm", "BGA 1168"),
    0x46: ("Haswell (Crystal Well)", "22 nm", "BGA"), 0x3F: ("Haswell-E", "22 nm", "LGA 2011-3"),
    0x3D: ("Broadwell-U", "14 nm", "BGA 1168"), 0x47: ("Broadwell", "14 nm", "LGA 1150"),
    0x4F: ("Broadwell-E", "14 nm", "LGA 2011-3"), 0x56: ("Broadwell-DE", "14 nm", "BGA"),
    0x4E: ("Skylake-U/Y", "14 nm", "BGA 1356"), 0x5E: ("Skylake", "14 nm", "LGA 1151"),
    0x55: ("Skylake-X / Cascade Lake", "14 nm", "LGA 2066 / LGA 3647"),
    0x8E: ("Kaby Lake-U", "14 nm", "BGA 1356"), 0x9E: ("Kaby Lake", "14 nm", "LGA 1151"),
    0xA5: ("Comet Lake", "14 nm", "LGA 1200"), 0xA6: ("Comet Lake-U", "14 nm", "BGA 1528"),
    0x66: ("Cannon Lake", "10 nm", "BGA"), 0x7D: ("Ice Lake", "10 nm", "BGA 1526"),
    0x7E: ("Ice Lake-U/Y", "10 nm", "BGA 1526"), 0x6A: ("Ice Lake-SP", "10 nm", "LGA 4189"),
    0x6C: ("Ice Lake-D", "10 nm", "BGA"), 0x8C: ("Tiger Lake-U", "10 nm SuperFin", "BGA 1449"),
    0x8D: ("Tiger Lake-H", "10 nm SuperFin", "BGA 1787"), 0xA7: ("Rocket Lake", "14 nm", "LGA 1200"),
    0x97: ("Alder Lake-S", "Intel 7", "LGA 1700"), 0x9A: ("Alder Lake-P", "Intel 7", "BGA 1744"),
    0xBE: ("Alder Lake-N", "Intel 7", "BGA 1264"), 0xB7: ("Raptor Lake-S", "Intel 7", "LGA 1700"),
    0xBA: ("Raptor Lake-P", "Intel 7", "BGA 1744"), 0xBF: ("Raptor Lake-S", "Intel 7", "LGA 1700"),
    0xAA: ("Meteor Lake", "Intel 4", "BGA 2049"), 0xAC: ("Meteor Lake", "Intel 4", "BGA"),
    0xBD: ("Lunar Lake", "TSMC N3B", "BGA 2833"), 0xC5: ("Arrow Lake-H", "TSMC N3B", "BGA"),
    0xC6: ("Arrow Lake-S", "TSMC N3B", "LGA 1851"), 0xB5: ("Arrow Lake-U", "Intel 3", "BGA"),
    0xCC: ("Panther Lake", "Intel 18A", "BGA"), 0x8F: ("Sapphire Rapids", "Intel 7", "LGA 4677"),
    0xCF: ("Emerald Rapids", "Intel 7", "LGA 4677"), 0xAD: ("Granite Rapids", "Intel 3", "LGA 7529"),
    0xAF: ("Sierra Forest", "Intel 3", "LGA 7529"),
    0x5C: ("Apollo Lake", "14 nm", "BGA 1296"), 0x7A: ("Gemini Lake", "14 nm", "BGA 1090"),
    0x86: ("Snow Ridge", "10 nm", "BGA"), 0x96: ("Elkhart Lake", "10 nm", "BGA 1493"),
    0x9C: ("Jasper Lake", "10 nm", "BGA 1338"), 0x37: ("Bay Trail", "22 nm", "BGA"),
    0x4C: ("Cherry Trail / Braswell", "14 nm", "BGA"), 0x1E: ("Lynnfield", "45 nm", "LGA 1156"),
    0x1A: ("Bloomfield", "45 nm", "LGA 1366"), 0x25: ("Clarkdale", "32 nm", "LGA 1156"),
    0x2C: ("Gulftown", "32 nm", "LGA 1366"), 0x17: ("Penryn / Wolfdale", "45 nm", "LGA 775"),
    0x0F: ("Conroe / Merom", "65 nm", "LGA 775"),
}

# Ajustes por stepping para modelos reaproveitados pela Intel
INTEL_STEP = {
    (0x8E, 10): ("Coffee Lake-U / Kaby Lake-R", "14 nm", "BGA 1528"),
    (0x8E, 11): ("Whiskey Lake-U", "14 nm", "BGA 1528"), (0x8E, 12): ("Comet Lake-U", "14 nm", "BGA 1528"),
    (0x9E, 10): ("Coffee Lake", "14 nm", "LGA 1151"), (0x9E, 11): ("Coffee Lake", "14 nm", "LGA 1151"),
    (0x9E, 12): ("Coffee Lake Refresh", "14 nm", "LGA 1151"), (0x9E, 13): ("Coffee Lake Refresh", "14 nm", "LGA 1151"),
    (0x55, 7): ("Cascade Lake", "14 nm", "LGA 2066 / LGA 3647"), (0x55, 11): ("Cooper Lake", "14 nm", "LGA 4189"),
    (0x97, 5): ("Alder Lake-S", "Intel 7", "LGA 1700"),
}

# AMD: (família, faixa de modelos) -> (codinome, tecnologia, soquete)
AMD = [
    (0x15, range(0x00, 0x10), ("Bulldozer / Piledriver", "32 nm", "AM3+")),
    (0x15, range(0x10, 0x20), ("Trinity / Richland", "32 nm", "FM2")),
    (0x15, range(0x30, 0x40), ("Kaveri / Godavari", "28 nm", "FM2+")),
    (0x15, range(0x60, 0x80), ("Carrizo / Bristol Ridge", "28 nm", "AM4 / FP4")),
    (0x16, range(0x00, 0x40), ("Kabini / Mullins / Beema", "28 nm", "AM1 / FT3")),
    (0x17, range(0x00, 0x08), ("Summit Ridge", "14 nm", "AM4")),
    (0x17, range(0x08, 0x10), ("Pinnacle Ridge", "12 nm", "AM4")),
    (0x17, range(0x10, 0x18), ("Raven Ridge", "14 nm", "AM4 / FP5")),
    (0x17, range(0x18, 0x20), ("Picasso", "12 nm", "AM4 / FP5")),
    (0x17, range(0x20, 0x30), ("Dalí / Pollock", "14 nm", "FP5")),
    (0x17, range(0x30, 0x40), ("Castle Peak / Rome", "7 nm", "sTRX4 / SP3")),
    (0x17, range(0x60, 0x68), ("Renoir", "7 nm", "AM4 / FP6")),
    (0x17, range(0x68, 0x70), ("Lucienne", "7 nm", "FP6")),
    (0x17, range(0x70, 0x80), ("Matisse", "7 nm", "AM4")),
    (0x17, range(0x90, 0xA0), ("Van Gogh", "7 nm", "FF3")),
    (0x17, range(0xA0, 0xB0), ("Mendocino", "6 nm", "FT6")),
    (0x19, range(0x00, 0x08), ("Milan", "7 nm", "SP3")),
    (0x19, range(0x08, 0x10), ("Chagall", "7 nm", "sWRX8")),
    (0x19, range(0x10, 0x20), ("Genoa", "5 nm", "SP5")),
    (0x19, range(0x20, 0x30), ("Vermeer", "7 nm", "AM4")),
    (0x19, range(0x40, 0x50), ("Rembrandt", "6 nm", "FP7")),
    (0x19, range(0x50, 0x60), ("Cezanne / Barcelo", "7 nm", "AM4 / FP6")),
    (0x19, range(0x60, 0x70), ("Raphael", "5 nm", "AM5")),
    (0x19, range(0x70, 0x78), ("Phoenix / Hawk Point", "4 nm", "AM5 / FP8")),
    (0x19, range(0x78, 0x80), ("Phoenix 2", "4 nm", "AM5 / FP8")),
    (0x19, range(0xA0, 0xB0), ("Bergamo / Siena", "5 nm", "SP5 / SP6")),
    (0x1A, range(0x00, 0x20), ("Turin", "4 nm / 3 nm", "SP5")),
    (0x1A, range(0x20, 0x30), ("Strix Point", "4 nm", "FP8")),
    (0x1A, range(0x40, 0x50), ("Granite Ridge", "4 nm", "AM5")),
    (0x1A, range(0x60, 0x70), ("Krackan Point", "4 nm", "FP8")),
    (0x1A, range(0x70, 0x80), ("Strix Halo", "4 nm", "FP11")),
]

# Revisão (stepping) conhecida -> nome
AMD_REV = {(0x19, 0x21, 0): "B0", (0x19, 0x21, 2): "B2", (0x17, 0x71, 0): "B0", (0x17, 0x08, 2): "B2",
           (0x17, 0x01, 1): "B1", (0x19, 0x61, 2): "B2", (0x1A, 0x44, 0): "B0", (0x19, 0x50, 0): "A0",
           (0x19, 0x74, 1): "A1", (0x19, 0x75, 2): "A2"}


def lookup(vendor, family, model, stepping, name=""):
    try:
        fam, mod, st = int(family), int(model), int(stepping)
    except (TypeError, ValueError):
        return {}
    res = None
    if vendor == "Intel" and fam == 6:
        res = INTEL_STEP.get((mod, st)) or INTEL.get(mod)
        # i3/i5/i7 sufixos: Raptor Lake Refresh
        if res and mod in (0xB7, 0xBF) and re.search(r"\b1[34]\d{3}", name or ""):
            res = ("Raptor Lake-S Refresh" if re.search(r"\b14\d{3}", name) else "Raptor Lake-S",) + res[1:]
    elif vendor in ("AMD", "Hygon"):
        for f, rng, val in AMD:
            if f == fam and mod in rng:
                res = val
                break
    out = {}
    if res:
        out = {"codename": res[0], "technology": res[1], "package": res[2]}
        if re.search(r"\d{4,5}(?:U|H|HS|HX|HK|HQ|P|Y)\b|Ryzen AI|Core\(TM\) Ultra|Core Ultra|Mobile", name or ""):
            if "LGA" in res[2] or "AM" in res[2]:
                out["package"] = "BGA (notebook)"
    rev = AMD_REV.get((fam, mod, st))
    if rev:
        out["revision"] = rev
    return out


def cpuid_fields(family, model, stepping):
    """Campos como o CPU-Z mostra: Family/Model/Stepping + Ext. Family/Ext. Model (hex)."""
    try:
        fam, mod = int(family), int(model)
    except (TypeError, ValueError):
        return {}
    base_fam = fam if fam < 0xF else 0xF
    return {"Família": f"{base_fam:X}", "Modelo": f"{mod & 0xF:X}", "Stepping": f"{int(stepping):X}" if stepping not in (None, "") else "—",
            "Família est.": f"{fam:X}", "Modelo est.": f"{mod:X}"}
