"""Decodificação de SPD (DDR3 / DDR4) e tabela de fabricantes JEDEC."""
from core import spd


def _ddr3_kingston():
    b = [0] * 256
    b[0:13] = [0x92, 0x10, 0x0B, 0x02, 0x03, 0x11, 0, 0x09, 0x03, 0x11, 1, 8, 0x0A]
    b[14], b[15] = 0xFE, 0x00
    b[16] = b[18] = b[20] = 0x69
    b[21], b[22], b[23], b[24], b[25] = 0x11, 0x18, 0x81, 0x20, 0x08
    b[117], b[118] = 0x01, 0x98
    b[120], b[121] = 0x14, 0x22
    b[128:146] = list(b"99U5471-020.A00LF ")
    b[148], b[149] = 0x80, 0xCE
    return bytes(b)


def test_ddr3_jedec_timings():
    d = spd.decode(_ddr3_kingston())
    assert d["type"] == "DDR3"
    assert d["max_mts"] == 1600 and d["pc"] == "PC3-12800"
    assert d["size"] == 4 * 1024 ** 3 and d["ranks"] == 2
    assert d["manufacturer"] == "Kingston" and d["dram_manufacturer"] == "Samsung"
    top = d["timings"][-1]
    assert (top["mts"], top["CL"], top["tRCD"], top["tRP"], top["tRAS"]) == (1600, 11, 11, 11, 28)
    assert [r["mts"] for r in d["timings"]] == [800, 1066, 1333, 1600]


def test_ddr4_from_fake_eeprom():
    import conftest
    mods, msg = spd.read_all(conftest.FAKE_ROOT)
    assert len(mods) == 2 and msg == ""
    m = mods[0]
    assert m["type"] == "DDR4" and m["manufacturer"] == "Kingston"
    jedec = [r for r in m["timings"] if r["label"].startswith("JEDEC")]
    assert jedec[-1]["mts"] == 3200 and jedec[-1]["CL"] == 22


def test_priv_output_parsing():
    out = "#LOG EEPROMs SPD já expostos: 0\n#LOG driver i2c_i801 carregado\n"
    mods, msg = spd.parse_priv_output(out)
    assert mods == [] and "SMBus" in msg and "Registro" in msg


def test_jedec_vendor_lookup():
    assert spd.jedec_vendor(0x04, 0xCD).startswith("G")  # G.Skill (banco 5)
    assert spd.jedec_vendor(0x00, 0x2C) == "Micron Technology"
