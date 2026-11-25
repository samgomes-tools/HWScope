"""Rede, bateria, ventoinhas, USB e áudio no PC simulado."""
from core import devices, hwinfo as hw


def test_battery():
    bats, ac = devices.batteries()
    b = bats[0]
    assert ac is False and b["capacity"] == 76 and b["cycles"] == 312
    assert round(b["health"]) == 83 and b["status"] == "Descarregando"


def test_usb_tree():
    devs = devices.usb_devices()
    names = {d["name"] for d in devs}
    assert "Logitech USB Receiver" in names
    stick = next(d for d in devs if "SanDisk" in d["name"])
    assert stick["speed"].startswith("USB 3.2 Gen 1") and stick["class"] == "Armazenamento"


def test_network():
    nets = {n["name"]: n for n in devices.net_interfaces()}
    assert nets["wlp5s0"]["type"] == "Wi-Fi" and nets["wlp5s0"]["state"] == "Conectado"
    assert nets["enp4s0"]["state"] == "Desconectado"


def test_audio_codecs():
    a = devices.audio()
    assert any("Realtek ALC1220" in c["codecs"] for c in a["cards"])


def test_fans_with_pwm():
    fans = devices.fans(hw.read_hwmon())
    f2 = next(f for f in fans if f["label"] == "fan2")
    assert f2["rpm"] == 1180 and f2["pwm"] == 50 and f2["mode"] == "Smart Fan"


def test_fan_names_persist():
    devices.save_fan_names({"nct6798:x:fan2": "CPU"})
    assert devices.load_fan_names()["nct6798:x:fan2"] == "CPU"
