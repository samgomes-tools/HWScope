"""Coleta de CPU, sensores, GPU, discos, placa-mãe e swap no PC simulado."""
from core import hwinfo as hw


def test_cpu_static():
    c = hw.cpu_static()
    assert c["name"].startswith("AMD Ryzen 7 5800X")
    assert (c["cores"], c["threads"]) == (8, 16)
    assert c["db"]["codename"] == "Vermeer" and c["db"]["package"] == "AM4"
    assert c["microarch"] == "Zen 3"
    assert c["cpuid"]["Família est."] == "19" and c["cpuid"]["Modelo est."] == "21"
    assert "AVX2" in c["instructions"]
    assert c["caches"]["L3"].startswith("32 MB")


def test_sensors_and_temperatures():
    chips = hw.read_hwmon()
    names = {c["name"] for c in chips}
    assert {"k10temp", "amdgpu", "nvme", "nct6798", "jc42"} <= names
    assert hw.pick_cpu_temp(chips) == 54.25
    assert [t for _, t in hw.ram_temps(chips)] == [39.5, 41.25]
    nvme = next(c for c in chips if c["name"] == "nvme")
    assert nvme["block"] == "nvme0n1" and "980 PRO" in nvme["title"]


def test_gpu_details():
    g = hw.gpus()[0]
    assert g["codename"] == "Navi 22" and g["driver"] == "amdgpu"
    assert g["vram_total"] == 12868124672 and g["temp"] == 58.0
    assert g["rebar"].startswith("Ativado")
    assert g["monitors"][0]["name"] == "DELL S2721DGF"
    x = hw.gpu_static_extra(g, {})
    assert x["rops"] == 64 and x["mem_type"].startswith("GDDR6")


def test_disks_and_chipset():
    disks = {d["name"]: d for d in hw.disks_static()}
    assert disks["nvme0n1"]["kind"] == "SSD NVMe" and "PCIe 4.0" in disks["nvme0n1"]["interface"]
    assert disks["sda"]["interface"] == "SATA" and disks["sda"]["rotational"]
    cs = hw.chipset_info()
    assert cs["Chipset"] == "AMD 500 Series"


def test_swap_info():
    sw = hw.swap_info()
    kinds = [d["kind"] for d in sw["devices"]]
    assert kinds[0].startswith("zram") and kinds[1] == "Arquivo"
    assert sw["devices"][0]["algoritmo"] == "zstd"
    assert sw["swappiness"] == "180"


def test_report_builds():
    static = {"cpu": hw.cpu_static(), "system": hw.system_info(), "dimms": [], "disks": hw.disks_static(),
              "chipset": hw.chipset_info(), "spd": []}
    txt = hw.build_report(static, {"mem": hw.mem_dynamic(), "gpus": hw.gpus(), "chips": hw.read_hwmon()})
    assert "Vermeer" in txt and "PLACA DE VÍDEO" in txt


def test_dependencies_listing():
    d = hw.dependencies()
    assert any(x["exe"] == "smartctl" for x in d["deps"])
    assert d["family"] in ("apt", "dnf", "pacman", "zypper")
