"""Gera uma árvore /sys + /proc simulada de um PC (Ryzen 7 5800X, RX 6700 XT, NVMe, HD SATA,
DDR4 com SPD, bateria, USB, áudio e rede). Usada pelos testes."""
import os


def build(R):
    def w(path, content):
        p = R + path
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(str(content) + "\n")


    def ln(target_abs, link_abs):
        lp = R + link_abs
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        rel = os.path.relpath(R + target_abs, os.path.dirname(lp))
        if not os.path.lexists(lp):
            os.symlink(rel, lp)


    # CPU: Ryzen 7 5800X, 8C/16T
    cpu = []
    for i in range(16):
        cpu.append(f"""processor\t: {i}
    vendor_id\t: AuthenticAMD
    cpu family\t: 25
    model\t\t: 33
    model name\t: AMD Ryzen 7 5800X 8-Core Processor
    stepping\t: 0
    microcode\t: 0xa201205
    cpu MHz\t\t: 3800.000
    cache size\t: 512 KB
    physical id\t: 0
    core id\t\t: {i % 8}
    bogomips\t: 7586.21
    flags\t\t: fpu mmx sse sse2 ht lm nx pni ssse3 fma sse4_1 sse4_2 popcnt aes avx f16c rdrand svm sse4a avx2 bmi1 bmi2 sha_ni adx constant_tsc
    """)
    w("/proc/cpuinfo", "\n".join(cpu))
    for i in range(16):
        b = f"/sys/devices/system/cpu/cpu{i}"
        w(f"{b}/cpufreq/scaling_cur_freq", 3600000 + i * 61000)
        w(f"{b}/cpufreq/cpuinfo_min_freq", 2200000)
        w(f"{b}/cpufreq/cpuinfo_max_freq", 4850000)
        w(f"{b}/cpufreq/scaling_driver", "amd-pstate-epp")
        w(f"{b}/cpufreq/scaling_governor", "powersave")
        w(f"{b}/cpufreq/energy_performance_preference", "balance_performance")
        core = i % 8
        for idx, (lvl, typ, size, shared, ways) in enumerate([
                (1, "Data", "32K", f"{core},{core+8}", 8), (1, "Instruction", "32K", f"{core},{core+8}", 8),
                (2, "Unified", "512K", f"{core},{core+8}", 8), (3, "Unified", "32768K", "0-15", 16)]):
            c = f"{b}/cache/index{idx}"
            w(f"{c}/level", lvl); w(f"{c}/type", typ); w(f"{c}/size", size)
            w(f"{c}/shared_cpu_list", shared); w(f"{c}/ways_of_associativity", ways)
    w("/sys/devices/system/cpu/cpufreq/boost", 1)
    w("/sys/devices/system/cpu/vulnerabilities/spectre_v2", "Mitigation: Retpolines")

    # DMI
    for k, v in {"board_vendor": "ASUSTeK COMPUTER INC.", "board_name": "ROG STRIX B550-F GAMING",
                 "board_version": "Rev X.0x", "bios_vendor": "American Megatrends Inc.",
                 "bios_version": "3611", "bios_date": "12/13/2023", "bios_release": "5.17",
                 "sys_vendor": "ASUS", "product_name": "System Product Name", "chassis_type": "3"}.items():
        w(f"/sys/class/dmi/id/{k}", v)
    os.makedirs(R + "/sys/firmware/efi", exist_ok=True)

    # hwmon: k10temp
    k = "/sys/devices/pci0000:00/0000:00:18.3/hwmon/hwmon1"
    w(f"{k}/name", "k10temp"); w(f"{k}/temp1_input", 54250); w(f"{k}/temp1_label", "Tctl")
    w(f"{k}/temp3_input", 51500); w(f"{k}/temp3_label", "Tccd1")
    ln("/sys/devices/pci0000:00/0000:00:18.3", k + "/device")
    ln(k, "/sys/class/hwmon/hwmon1")

    # Super I/O nct6798
    n = "/sys/devices/platform/nct6775.656/hwmon/hwmon3"
    w(f"{n}/name", "nct6798")
    for i, (lab, val) in enumerate([("SYSTIN", 36000), ("CPUTIN", 41500), ("AUXTIN0", 30000)], 1):
        w(f"{n}/temp{i}_input", val); w(f"{n}/temp{i}_label", lab)
    w(f"{n}/fan1_input", 0); w(f"{n}/fan2_input", 1180); w(f"{n}/fan2_label", "CPU fan" if False else "fan2")
    w(f"{n}/in0_input", 1240); w(f"{n}/in0_label", "Vcore"); w(f"{n}/in1_input", 1016)
    ln(n, "/sys/class/hwmon/hwmon3")

    # GPU amdgpu RX 6700 XT
    g = "/sys/devices/pci0000:00/0000:00:03.1/0000:0a:00.0"
    for kk, vv in {"vendor": "0x1002", "device": "0x73df", "subsystem_vendor": "0x1da2",
                   "subsystem_device": "0xe445", "revision": "0xc1", "current_link_speed": "16.0 GT/s PCIe",
                   "max_link_speed": "16.0 GT/s PCIe", "current_link_width": 16, "max_link_width": 16,
                   "vbios_version": "113-D5121100-100", "boot_vga": 1,
                   "mem_info_vram_total": 12868124672, "mem_info_vram_used": 1873563648,
                   "mem_info_gtt_total": 16777216000, "mem_info_gtt_used": 90000000,
                   "mem_info_vram_vendor": "samsung", "gpu_busy_percent": 37, "mem_busy_percent": 12,
                   "power_dpm_force_performance_level": "auto"}.items():
        w(f"{g}/{kk}", vv)
    w(f"{g}/pp_dpm_sclk", "0: 500Mhz\n1: 1850Mhz *\n2: 2622Mhz")
    w(f"{g}/pp_dpm_mclk", "0: 96Mhz\n1: 456Mhz\n2: 1000Mhz *")
    os.makedirs(R + "/sys/bus/pci/drivers/amdgpu", exist_ok=True)
    ln("/sys/bus/pci/drivers/amdgpu", g + "/driver")
    gh = g + "/hwmon/hwmon2"
    w(f"{gh}/name", "amdgpu")
    for i, (lab, val) in enumerate([("edge", 58000), ("junction", 71000), ("mem", 66000)], 1):
        w(f"{gh}/temp{i}_input", val); w(f"{gh}/temp{i}_label", lab)
    w(f"{gh}/temp2_crit", 110000)
    w(f"{gh}/fan1_input", 1420); w(f"{gh}/pwm1", 92); w(f"{gh}/power1_average", 87000000)
    w(f"{gh}/power1_cap", 186000000); w(f"{gh}/in0_input", 1062); w(f"{gh}/in0_label", "vddgfx")
    w(f"{gh}/freq1_input", 1850000000); w(f"{gh}/freq1_label", "sclk")
    ln(g, gh + "/device")
    ln(gh, "/sys/class/hwmon/hwmon2")
    ln(g, "/sys/class/drm/card1/device")
    os.makedirs(R + "/sys/class/drm/card1-DP-1", exist_ok=True)

    # NVMe
    nv = "/sys/devices/pci0000:00/0000:00:01.1/0000:01:00.0"
    w(f"{nv}/current_link_speed", "16.0 GT/s PCIe"); w(f"{nv}/current_link_width", 4)
    ctrl = nv + "/nvme/nvme0"
    w(f"{ctrl}/model", "Samsung SSD 980 PRO 1TB"); w(f"{ctrl}/serial", "S5GXNF0R123456")
    w(f"{ctrl}/firmware_rev", "5B2QGXA7")
    blk = ctrl + "/nvme0n1"
    w(f"{blk}/size", 1953525168); w(f"{blk}/queue/rotational", 0); w(f"{blk}/removable", 0)
    w(f"{blk}/queue/logical_block_size", 512); w(f"{blk}/queue/physical_block_size", 512)
    w(f"{blk}/queue/scheduler", "[none] mq-deadline")
    os.makedirs(R + blk + "/nvme0n1p1", exist_ok=True)
    ln(ctrl, blk + "/device")
    ln(blk, "/sys/block/nvme0n1")
    nh = ctrl + "/hwmon4"
    w(f"{nh}/name", "nvme"); w(f"{nh}/temp1_input", 43850); w(f"{nh}/temp1_label", "Composite")
    w(f"{nh}/temp1_crit", 84850); w(f"{nh}/temp2_input", 47850); w(f"{nh}/temp2_label", "Sensor 1")
    ln(ctrl, nh + "/device")
    ln(nh, "/sys/class/hwmon/hwmon4")

    # SATA HDD + drivetemp
    sd = "/sys/devices/pci0000:00/0000:02:00.1/ata2/host1/target1:0:0/1:0:0:0"
    w(f"{sd}/model", "WDC WD20EZBX-00A"); w(f"{sd}/vendor", "ATA"); w(f"{sd}/rev", "1A01")
    sb = sd + "/block/sda"
    w(f"{sb}/size", 3907029168); w(f"{sb}/queue/rotational", 1); w(f"{sb}/removable", 0)
    w(f"{sb}/queue/logical_block_size", 512); w(f"{sb}/queue/physical_block_size", 4096)
    w(f"{sb}/queue/scheduler", "none [mq-deadline]")
    ln(sd, sb + "/device")
    ln(sb, "/sys/block/sda")
    dh = sd + "/hwmon/hwmon5"
    w(f"{dh}/name", "drivetemp"); w(f"{dh}/temp1_input", 35000)
    ln(sd, dh + "/device")
    ln(dh, "/sys/class/hwmon/hwmon5")

    w("/etc/os-release", 'PRETTY_NAME="Linux Mint 22 Wilma"')


    # ---- PCI (chipset) ----
    for addr, cls, v, d in (("0000:00:00.0", "0x060000", "0x1022", "0x1480"),
                            ("0000:00:14.3", "0x060100", "0x1022", "0x790e"),
                            ("0000:02:00.0", "0x0c0330", "0x1022", "0x43ee"),
                            ("0000:00:01.1", "0x060400", "0x1022", "0x1483")):
        base = f"/sys/devices/pci0000:00/{addr}"
        w(f"{base}/class", cls); w(f"{base}/vendor", v); w(f"{base}/device", d); w(f"{base}/revision", "0x51")
        ln(base, f"/sys/bus/pci/devices/{addr}")
    w("/sys/devices/pci0000:00/0000:00:01.1/max_link_speed", "16.0 GT/s PCIe")
    ln(g, "/sys/bus/pci/devices/0000:0a:00.0")
    w(f"{g}/class", "0x030000")
    w(f"{g}/max_link_speed", "16.0 GT/s PCIe")
    # BAR0 = 16 GiB (Resizable BAR ativo)
    w(f"{g}/resource", "0x0000007c00000000 0x0000007fffffffff 0x000000000014220c\n"
                       "0x0000000000000000 0x0000000000000000 0x0000000000000000\n"
                       "0x0000007e00000000 0x0000007e001fffff 0x000000000014220c\n")
    w(f"{gh}/power1_cap_default", 186000000); w(f"{gh}/power1_cap_max", 203000000); w(f"{gh}/power1_cap_min", 0)
    w(f"{g}/gtt_used_dummy", 0)

    # ---- monitor com EDID ----
    edid = bytearray(128)
    edid[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    code = ((ord("D") - 64) << 10) | ((ord("E") - 64) << 5) | (ord("L") - 64)
    edid[8], edid[9] = code >> 8, code & 0xFF
    # detailed timing 2560x1440@144 (pclk 592.25 MHz)
    pclk = 59225
    dt = bytearray(18)
    dt[0], dt[1] = pclk & 0xFF, pclk >> 8
    h, hb, v, vb = 2560, 160, 1440, 41
    dt[2], dt[3], dt[4] = h & 0xFF, hb & 0xFF, ((h >> 8) << 4) | (hb >> 8)
    dt[5], dt[6], dt[7] = v & 0xFF, vb & 0xFF, ((v >> 8) << 4) | (vb >> 8)
    dt[12], dt[13], dt[14] = 597 & 0xFF, 336 & 0xFF, ((597 >> 8) << 4) | (336 >> 8)
    edid[54:72] = dt
    name = bytearray(18); name[3] = 0xFC; name[5:18] = b"DELL S2721DGF"
    edid[72:90] = name
    os.makedirs(R + "/sys/class/drm/card1-DP-1", exist_ok=True)
    w("/sys/class/drm/card1-DP-1/status", "connected")
    open(R + "/sys/class/drm/card1-DP-1/edid", "wb").write(bytes(edid))

    # ---- SPD DDR4 (2 pentes) ----
    def spd_ddr4(serial):
        b = [0] * 512
        b[0] = 0x23; b[1] = 0x11; b[2] = 0x0C; b[3] = 0x02; b[4] = 0x85; b[5] = 0x21; b[12] = 0x09; b[13] = 0x03; b[14] = 0x80
        b[18] = 0x05; b[19] = 0x0D
        cl = 0
        for c in range(10, 25):
            cl |= 1 << (c - 7)
        b[20], b[21], b[22], b[23] = cl & 255, (cl >> 8) & 255, (cl >> 16) & 255, (cl >> 24) & 255
        b[24] = b[25] = b[26] = 0x6E; b[27] = 0x11; b[28] = 0x00; b[29] = 0x6E; b[30] = 0x30; b[31] = 0x11
        b[320] = 0x01; b[321] = 0x98; b[323] = 0x21; b[324] = 0x35
        b[325:329] = serial
        b[329:349] = list(b"KF436C17BB/16       "); b[350] = 0x80; b[351] = 0xAD
        # XMP 2.0 DDR4-3600 CL17-19-19-39
        b[384] = 0x0C; b[385] = 0x4A; b[386] = 1; b[387] = 0x20
        p = 393
        b[p] = 0xA3; b[p + 3] = 0x05; b[p + 38] = (256 - 69) & 0xFF   # 0.625-0.069=0.556ns
        b[p + 8] = 0x4C; b[p + 37] = (256 - 6) & 0xFF                    # 9.5-0.006 -> CL17
        b[p + 9] = 0x55; b[p + 36] = 0                                     # 10.625 -> 19.1
        b[p + 10] = 0x55
        b[p + 11] = 0x10; b[p + 12] = 0xAE; b[p + 13] = 0x06               # tRAS 21.75ns? -> adjust
        b[p + 12] = 0xAD                                                   # 173*0.125=21.6 -> 39
        b[p + 11] = 0x10; b[p + 13] = 0x5A                                 # tRC (0x15A)*.125=43.25 -> 78
        return bytes(b)

    for addr, ser in (("0-0050", [0x11, 0x22, 0x33, 0x44]), ("0-0052", [0x55, 0x66, 0x77, 0x88])):
        d = f"/sys/devices/pci0000:00/0000:00:14.0/i2c-0/{addr}"
        os.makedirs(R + d, exist_ok=True)
        open(R + d + "/eeprom", "wb").write(spd_ddr4(ser))
        ln(d, f"/sys/bus/i2c/drivers/ee1004/{addr}")


    # ---- bateria + carregador ----
    b = "/sys/class/power_supply/BAT0"
    for k, v in {"type": "Battery", "manufacturer": "SMP", "model_name": "L19M4PF0", "technology": "Li-poly",
                 "serial_number": "1234", "status": "Discharging", "capacity": 76, "energy_full": 49800000,
                 "energy_full_design": 60000000, "energy_now": 37848000, "power_now": 9450000,
                 "voltage_now": 15820000, "cycle_count": 312, "charge_control_end_threshold": 80}.items():
        w(f"{b}/{k}", v)
    w("/sys/class/power_supply/AC/type", "Mains"); w("/sys/class/power_supply/AC/online", 0)

    # ---- USB ----
    def usbdev(path, vid, pid, man, prod, speed, cls="00", itf=None, drv=None, bus="1", power="100mA", root=False):
        d = f"/sys/devices/pci0000:00/0000:00:14.0/{path}"
        for k, v in {"idVendor": vid, "idProduct": pid, "speed": speed, "bDeviceClass": cls, "busnum": bus,
                     "bMaxPower": power, "version": " 2.00"}.items():
            w(f"{d}/{k}", v)
        if man: w(f"{d}/manufacturer", man)
        if prod: w(f"{d}/product", prod)
        if itf:
            i = f"{d}/{path.split('/')[-1]}:1.0"
            w(f"{i}/bInterfaceClass", itf)
            if drv:
                os.makedirs(R + f"/sys/bus/usb/drivers/{drv}", exist_ok=True)
                ln(f"/sys/bus/usb/drivers/{drv}", i + "/driver")
        ln(d, f"/sys/bus/usb/devices/{path.split('/')[-1]}")
    usbdev("usb1", "1d6b", "0002", "Linux Foundation", "xHCI Host Controller", "480", "09", root=True)
    usbdev("usb2", "1d6b", "0003", "Linux Foundation", "xHCI Host Controller", "10000", "09", bus="2", root=True)
    usbdev("usb1/1-3", "046d", "c52b", "Logitech", "USB Receiver", "12", "00", "03", "usbhid", power="98mA")
    usbdev("usb1/1-4", "0bda", "5634", None, None, "480", "ef", "0e", "uvcvideo", power="500mA")
    usbdev("usb2/2-1", "0781", "5583", "SanDisk", "Ultra Fit", "5000", "00", "08", "usb-storage", bus="2", power="896mA")

    # ---- áudio ----
    w("/proc/asound/cards", " 0 [Generic        ]: HDA-Intel - HD-Audio Generic\n                      HD-Audio Generic at 0xfcb00000 irq 88\n"
                            " 1 [Generic_1      ]: HDA-Intel - HD-Audio Generic\n                      HD-Audio Generic at 0xfc080000 irq 89\n")
    w("/proc/asound/card1/codec#0", "Codec: Realtek ALC1220\nAddress: 0\nVendor Id: 0x10ec1220\n")
    w("/proc/asound/card0/codec#0", "Codec: ATI R6xx HDMI\nAddress: 0\n")
    w("/proc/asound/card1/pcm0p/info", "card: 1\nname: ALC1220 Analog\nstream: PLAYBACK\n")
    w("/proc/asound/card1/pcm0c/info", "card: 1\nname: ALC1220 Analog\nstream: CAPTURE\n")
    w("/proc/asound/card0/pcm3p/info", "card: 0\nname: HDMI 0\nstream: PLAYBACK\n")

    # ---- rede ----
    nd = "/sys/devices/pci0000:00/0000:00:02.2/0000:05:00.0"
    w(f"{nd}/vendor", "0x8086"); w(f"{nd}/device", "0x2723")
    os.makedirs(R + "/sys/bus/pci/drivers/iwlwifi", exist_ok=True); ln("/sys/bus/pci/drivers/iwlwifi", nd + "/driver")
    wl = nd + "/net/wlp5s0"
    for k, v in {"address": "a4:b1:c1:00:11:22", "mtu": 1500, "operstate": "up", "type": 1}.items():
        w(f"{wl}/{k}", v)
    os.makedirs(R + wl + "/wireless", exist_ok=True)
    ln(nd, wl + "/device"); ln(wl, "/sys/class/net/wlp5s0")
    ed = "/sys/devices/pci0000:00/0000:00:02.1/0000:04:00.0"
    w(f"{ed}/vendor", "0x10ec"); w(f"{ed}/device", "0x8125")
    os.makedirs(R + "/sys/bus/pci/drivers/r8169", exist_ok=True); ln("/sys/bus/pci/drivers/r8169", ed + "/driver")
    en = ed + "/net/enp4s0"
    for k, v in {"address": "70:85:c2:aa:bb:cc", "mtu": 1500, "operstate": "down", "type": 1, "speed": -1}.items():
        w(f"{en}/{k}", v)
    ln(ed, en + "/device"); ln(en, "/sys/class/net/enp4s0")
    w("/proc/net/wireless", "Inter-| sta-|   Quality        |   Discarded packets\n face | tus | link level noise |  nwid  crypt\n wlp5s0: 0000   58.  -52.  -256        0      0\n")
    w("/proc/net/route", "Iface\tDestination\tGateway \tFlags\nwlp5s0\t00000000\t0101A8C0\t0003\n")
    w("/etc/resolv.conf", "nameserver 192.168.1.1\n")


    # ---- sensores de RAM (jc42), PWM das ventoinhas, swap e RAPL ----
    os.remove(R + "/sys/class/hwmon/hwmon5")       # disco SATA sem drivetemp: testa o caminho UDisks
    for i, (addr, t) in enumerate([("0-0018", 39500), ("0-001a", 41250)]):
        d = f"/sys/devices/pci0000:00/0000:00:14.0/i2c-0/{addr}/hwmon/hwmon{6 + i}"
        w(f"{d}/name", "jc42"); w(f"{d}/temp1_input", t); w(f"{d}/temp1_crit", 85000)
        ln(d, f"/sys/class/hwmon/hwmon{6 + i}")
    n = "/sys/devices/platform/nct6775.656/hwmon/hwmon3"
    w(f"{n}/pwm2", 128); w(f"{n}/pwm2_enable", 5); w(f"{n}/fan3_input", 860); w(f"{n}/pwm3", 90); w(f"{n}/pwm3_enable", 2)
    w("/proc/swaps", "Filename\tType\tSize\tUsed\tPriority\n/dev/zram0 partition\t8126460\t1532112\t100\n/swapfile file\t4194300\t0\t-2\n")
    w("/sys/block/zram0/comp_algorithm", "lzo-rle lzo lz4 [zstd]")
    w("/sys/block/zram0/mm_stat", "1568882688 412000000 430000000 0 430000000 0 0 0")
    w("/proc/sys/vm/swappiness", 180); w("/proc/sys/vm/vfs_cache_pressure", 100); w("/proc/sys/vm/page-cluster", 0)
    for z, nm in (("intel-rapl:0", "package-0"), ("intel-rapl:0:0", "core")):
        w(f"/sys/class/powercap/{z}/name", nm)
        w(f"/sys/class/powercap/{z}/max_energy_range_uj", 262143328850)

    return R


if __name__ == "__main__":
    import sys
    build(sys.argv[1])
