"""
Especificações de chips gráficos (chip completo), no estilo da base do GPU-Z.
Campos: arquitetura, processo, área do die (mm²), transistores (milhões), lançamento,
tipo de memória, largura do barramento (bits), shaders, TMUs, ROPs.
Para placas com chip cortado, shaders/TMUs são recalculados pelas unidades de
computação reportadas pelo OpenCL quando disponível.
"""
import re

#        chave         arquitetura      processo        die   trans   ano   memória     bus  shaders TMU ROP
_RAW = """
Navi 48      |RDNA 4          |TSMC N4P       |357 |53900 |2025 |GDDR6      |256 |4096 |256 |128
Navi 44      |RDNA 4          |TSMC N4P       |199 |29700 |2025 |GDDR6      |128 |2048 |128 |64
Navi 31      |RDNA 3          |TSMC N5 + N6   |529 |57700 |2022 |GDDR6      |384 |6144 |384 |192
Navi 32      |RDNA 3          |TSMC N5 + N6   |346 |28100 |2023 |GDDR6      |256 |3840 |240 |96
Navi 33      |RDNA 3          |TSMC N6        |204 |13300 |2023 |GDDR6      |128 |2048 |128 |64
Navi 21      |RDNA 2          |TSMC N7        |520 |26800 |2020 |GDDR6      |256 |5120 |320 |128
Navi 22      |RDNA 2          |TSMC N7        |335 |17200 |2021 |GDDR6      |192 |2560 |160 |64
Navi 23      |RDNA 2          |TSMC N7        |237 |11060 |2021 |GDDR6      |128 |2048 |128 |64
Navi 24      |RDNA 2          |TSMC N6        |107 |5400  |2022 |GDDR6      |64  |1024 |64  |32
Navi 10      |RDNA 1          |TSMC N7        |251 |10300 |2019 |GDDR6      |256 |2560 |160 |64
Navi 14      |RDNA 1          |TSMC N7        |158 |6400  |2019 |GDDR6      |128 |1536 |96  |32
Vega 20      |GCN 5           |TSMC N7        |331 |13230 |2019 |HBM2       |4096|4096 |256 |64
Vega 10      |GCN 5           |GloFo 14 nm    |495 |12500 |2017 |HBM2       |2048|4096 |256 |64
Ellesmere    |GCN 4 (Polaris) |GloFo 14 nm    |232 |5700  |2016 |GDDR5      |256 |2304 |144 |32
Baffin       |GCN 4 (Polaris) |GloFo 14 nm    |123 |3000  |2016 |GDDR5      |128 |1024 |64  |16
Lexa         |GCN 4 (Polaris) |GloFo 14 nm    |101 |2200  |2017 |GDDR5      |64  |512  |32  |16
Fiji         |GCN 3           |TSMC 28 nm     |596 |8900  |2015 |HBM        |4096|4096 |256 |64
Tonga        |GCN 3           |TSMC 28 nm     |366 |5000  |2014 |GDDR5      |256 |2048 |128 |32
Hawaii       |GCN 2           |TSMC 28 nm     |438 |6200  |2013 |GDDR5      |512 |2816 |176 |64
Strix        |RDNA 3.5 (iGPU) |TSMC N4P       |232 |0     |2024 |Sistema    |128 |1024 |64  |32
Phoenix      |RDNA 3 (iGPU)   |TSMC N4        |178 |25390 |2023 |Sistema    |128 |768  |48  |32
Hawk Point   |RDNA 3 (iGPU)   |TSMC N4        |178 |25390 |2024 |Sistema    |128 |768  |48  |32
Rembrandt    |RDNA 2 (iGPU)   |TSMC N6        |208 |13100 |2022 |Sistema    |128 |768  |48  |32
Raphael      |RDNA 2 (iGPU)   |TSMC N6 (IOD)  |122 |3400  |2022 |Sistema    |128 |128  |8   |4
Granite Ridge|RDNA 2 (iGPU)   |TSMC N6 (IOD)  |122 |3400  |2024 |Sistema    |128 |128  |8   |4
Cezanne      |GCN 5 (iGPU)    |TSMC N7        |180 |10700 |2021 |Sistema    |128 |512  |32  |8
Renoir       |GCN 5 (iGPU)    |TSMC N7        |156 |9800  |2020 |Sistema    |128 |512  |32  |8
Picasso      |GCN 5 (iGPU)    |GloFo 12 nm    |210 |4940  |2019 |Sistema    |128 |704  |44  |16
Raven Ridge  |GCN 5 (iGPU)    |GloFo 14 nm    |210 |4940  |2018 |Sistema    |128 |704  |44  |16
Van Gogh     |RDNA 2 (iGPU)   |TSMC N7        |163 |2400  |2022 |Sistema    |128 |512  |32  |8
GB202        |Blackwell       |TSMC 4N        |750 |92200 |2025 |GDDR7      |512 |24576|768 |192
GB203        |Blackwell       |TSMC 4N        |378 |45600 |2025 |GDDR7      |256 |10752|336 |112
GB205        |Blackwell       |TSMC 4N        |263 |31100 |2025 |GDDR7      |192 |6400 |200 |80
GB206        |Blackwell       |TSMC 4N        |181 |21900 |2025 |GDDR7      |128 |4608 |144 |48
GB207        |Blackwell       |TSMC 4N        |149 |16900 |2025 |GDDR6      |128 |2560 |80  |32
AD102        |Ada Lovelace    |TSMC 4N        |609 |76300 |2022 |GDDR6X     |384 |18432|576 |192
AD103        |Ada Lovelace    |TSMC 4N        |379 |45900 |2022 |GDDR6X     |256 |10240|320 |112
AD104        |Ada Lovelace    |TSMC 4N        |294 |35800 |2023 |GDDR6X     |192 |7680 |240 |80
AD106        |Ada Lovelace    |TSMC 4N        |190 |22900 |2023 |GDDR6      |128 |4608 |144 |48
AD107        |Ada Lovelace    |TSMC 4N        |159 |18900 |2023 |GDDR6      |128 |3072 |96  |48
GA102        |Ampere          |Samsung 8N     |628 |28300 |2020 |GDDR6X     |384 |10752|336 |112
GA103        |Ampere          |Samsung 8N     |496 |22000 |2022 |GDDR6      |320 |7680 |240 |96
GA104        |Ampere          |Samsung 8N     |392 |17400 |2020 |GDDR6      |256 |6144 |192 |96
GA106        |Ampere          |Samsung 8N     |276 |12000 |2021 |GDDR6      |192 |3840 |120 |48
GA107        |Ampere          |Samsung 8N     |200 |8700  |2021 |GDDR6      |128 |2560 |80  |32
TU102        |Turing          |TSMC 12 nm FFN |754 |18600 |2018 |GDDR6      |384 |4608 |288 |96
TU104        |Turing          |TSMC 12 nm FFN |545 |13600 |2018 |GDDR6      |256 |3072 |192 |64
TU106        |Turing          |TSMC 12 nm FFN |445 |10800 |2018 |GDDR6      |256 |2304 |144 |64
TU116        |Turing          |TSMC 12 nm FFN |284 |6600  |2019 |GDDR6      |192 |1536 |96  |48
TU117        |Turing          |TSMC 12 nm FFN |200 |4700  |2019 |GDDR5      |128 |1024 |64  |32
GP102        |Pascal          |TSMC 16 nm     |471 |11800 |2016 |GDDR5X     |384 |3840 |240 |96
GP104        |Pascal          |TSMC 16 nm     |314 |7200  |2016 |GDDR5X     |256 |2560 |160 |64
GP106        |Pascal          |TSMC 16 nm     |200 |4400  |2016 |GDDR5      |192 |1280 |80  |48
GP107        |Pascal          |Samsung 14 nm  |132 |3300  |2016 |GDDR5      |128 |768  |48  |32
GP108        |Pascal          |Samsung 14 nm  |74  |1800  |2017 |GDDR5      |64  |384  |24  |16
GM200        |Maxwell 2.0     |TSMC 28 nm     |601 |8000  |2015 |GDDR5      |384 |3072 |192 |96
GM204        |Maxwell 2.0     |TSMC 28 nm     |398 |5200  |2014 |GDDR5      |256 |2048 |128 |64
GM206        |Maxwell 2.0     |TSMC 28 nm     |228 |2940  |2015 |GDDR5      |128 |1024 |64  |32
GM107        |Maxwell         |TSMC 28 nm     |148 |1870  |2014 |GDDR5      |128 |640  |40  |16
GK110        |Kepler          |TSMC 28 nm     |561 |7080  |2013 |GDDR5      |384 |2880 |240 |48
GK104        |Kepler          |TSMC 28 nm     |294 |3540  |2012 |GDDR5      |256 |1536 |128 |32
GK106        |Kepler          |TSMC 28 nm     |221 |2540  |2012 |GDDR5      |192 |960  |80  |24
GK107        |Kepler          |TSMC 28 nm     |118 |1270  |2012 |GDDR5      |128 |384  |32  |16
GK208        |Kepler          |TSMC 28 nm     |87  |1020  |2013 |GDDR5      |64  |384  |16  |8
Battlemage G31|Xe2-HPG        |TSMC N5        |368 |0     |2025 |GDDR6      |256 |4096 |256 |128
Battlemage G21|Xe2-HPG        |TSMC N5        |272 |19600 |2024 |GDDR6      |192 |2560 |160 |80
ACM-G10      |Xe-HPG          |TSMC N6        |406 |21700 |2022 |GDDR6      |256 |4096 |256 |128
ACM-G11      |Xe-HPG          |TSMC N6        |157 |7200  |2022 |GDDR6      |96  |1024 |64  |32
"""

DB = {}
for line in _RAW.strip().splitlines():
    p = [x.strip() for x in line.split("|")]
    DB[p[0]] = {"arch": p[1], "tech": p[2], "die": int(p[3]), "transistors": int(p[4]),
                "release": p[5], "mem_type": p[6], "bus": int(p[7]), "shaders": int(p[8]),
                "tmus": int(p[9]), "rops": int(p[10])}

# Shaders por unidade de computação OpenCL (CU / SM / EU)
SHADERS_PER_CU = {"RDNA": 64, "GCN": 64, "Blackwell": 128, "Ada": 128, "Ampere": 128, "Turing": 64,
                  "Pascal": 128, "Maxwell": 128, "Kepler": 192, "Xe": 8}
TMUS_PER_CU = {"RDNA": 4, "GCN": 4, "Blackwell": 4, "Ada": 4, "Ampere": 4, "Turing": 4, "Pascal": 8,
               "Maxwell": 8, "Kepler": 16, "Xe": 0.5}

# Fator do clock de memória reportado -> taxa efetiva (MT/s)
MEM_RATE = {"GDDR7": 4, "GDDR6X": 8, "GDDR6": 8, "GDDR5X": 8, "GDDR5": 4, "HBM2": 2, "HBM": 2}


def find(chip, name=""):
    """chip: texto do pci.ids (ex.: 'Navi 22 [Radeon RX 6700 XT]' ou 'GA104 [GeForce RTX 3070]')."""
    txt = f"{chip or ''} {name or ''}"
    if re.search(r"\bDG2\b|Arc A", txt):
        key = "ACM-G11" if re.search(r"A3[1-8]0|A[35]\d0M|A310|A380", txt) else "ACM-G10"
        return key, DB[key]
    if re.search(r"Arc B[57]", txt):
        key = "Battlemage G31" if "B770" in txt else "Battlemage G21"
        return key, DB[key]
    if re.search(r"Polaris 2[0-9]|RX (470|480|570|580|590)", txt):
        return "Ellesmere", DB["Ellesmere"]
    best = None
    for k in DB:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?![0-9])", txt):
            if best is None or len(k) > len(best):
                best = k
    return (best, DB[best]) if best else (None, None)


def per_cu(arch, table):
    for k, v in table.items():
        if arch.startswith(k):
            return v
    return None
