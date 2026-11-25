"""Nota de saúde dos discos (estilo CrystalDiskInfo)."""
from core import health

ATA = {"smart_status": {"passed": True}, "serial_number": "WX1", "power_on_time": {"hours": 24088},
       "ata_smart_attributes": {"table": [
           {"id": 5, "name": "Reallocated_Sector_Ct", "value": 199, "worst": 199, "thresh": 140,
            "when_failed": "", "raw": {"value": 8, "string": "8"}},
           {"id": 197, "name": "Current_Pending_Sector", "value": 200, "worst": 200, "thresh": 0,
            "when_failed": "", "raw": {"value": 0, "string": "0"}}]}}

NVME = {"smart_status": {"passed": True}, "serial_number": "S5G",
        "nvme_smart_health_information_log": {"critical_warning": 0, "available_spare": 100,
                                              "available_spare_threshold": 10, "percentage_used": 3,
                                              "data_units_written": 41234567, "media_errors": 0}}


def test_ata_caution_with_reallocated():
    r = health.assess_smartctl(ATA)
    assert r["status"] == health.CAUTION
    assert r["counters"] == {"setores realocados": 8}


def test_nvme_good_and_life():
    r = health.assess_smartctl(NVME)
    assert r["status"] == health.GOOD and r["life"] == 97 and r["written"].endswith("TB")


def test_failed_smart_is_bad():
    r = health.assess_smartctl({**NVME, "smart_status": {"passed": False}})
    assert r["status"] == health.BAD


def test_history_detects_worsening():
    assert health.compare_and_store("SER1", {"setores realocados": 2}) == []
    warns = health.compare_and_store("SER1", {"setores realocados": 8})
    assert warns and "2 → 8" in warns[0]


def test_udisks_parse():
    txt = """/org/freedesktop/UDisks2/block_devices/sda:
  org.freedesktop.UDisks2.Block:
    Drive:                      '/org/freedesktop/UDisks2/drives/WDC'
/org/freedesktop/UDisks2/drives/WDC:
  org.freedesktop.UDisks2.Drive.Ata:
    SmartEnabled:               true
    SmartFailing:               false
    SmartNumBadSectors:         8
    SmartPowerOnSeconds:        86716800
    SmartSupported:             true
    SmartTemperature:           308.15
    SmartUpdated:               1795450000
"""
    r = health.parse_udisks(txt)["sda"]
    assert r["status"] == health.CAUTION and r["hours"] == 24088 and r["temp"] == 35
