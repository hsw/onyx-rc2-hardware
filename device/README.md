# Device facts: ONYX BOOX Robinson Crusoe 2 (MC_Kepler_R2)

Captured from one RC2 running stock firmware 1.8.2 over adb (uid shell, no root) and in Rockusb loader mode, 2026-10-06.
Raw captures (excerpts, no serials or personal data) are in [`proc/`](proc/).

## Identity

| Field | Value |
|---|---|
| ro.product.model / device / board | MC_Kepler_R2 |
| ro.board.platform | rk3026 |
| ro.build.display.id | 1.8.2-mc 20171102 00e95a3 |
| ro.build.fingerprint | Onyx/MC_Kepler_R2/MC_Kepler_R2:4.2.2/JDQ_1711072143/1023:user/release-keys |
| Android | 4.2.2, API 17, user build, ro.secure=1, ro.debuggable=0 |
| Kernel | Linux 3.0.36+ #1 SMP PREEMPT Tue Nov 7 21:44:55 CST 2017, gcc 4.6.x-google ([`proc_version.txt`](proc/proc_version.txt)) |
| Loader (from cmdline) | bootver=2016-04-12#2.32, firmware_ver=5.0.0 |
| PCB | pcb_ver=2 (= V1.73, see [`../board/README.md`](../board/README.md) §5) |
| Storage | onyx_emmc=1 (eMMC through the rk29xxnand / `rk30xxnand_ko` MTD layer) |
| waveform_addr | 0x7ff00000 (from cmdline) |
| initrd | 0x62000000, size 0x00130000 (runtime) |
| console | ttyFIQ0 |
| CPU | 2 × Cortex-A9 (`CPU part 0xc09`, rev 1), NEON, VFPv3; `Hardware: RK30board` ([`proc_cpuinfo.txt`](proc/proc_cpuinfo.txt)) |
| RAM | 512 MiB (`MemTotal: 524288 kB`; System RAM 0x60000000–0x7d0fffff, the rest reserved for fb0/EBC, [`proc_iomem.txt`](proc/proc_iomem.txt)) |

## Partition map (from `/proc/cmdline` mtdparts, units are 512-byte sectors)

| mtd | name | offset (sect) | size (sect) | size | offset bytes |
|---|---|---|---|---|---|
| mtd0 | misc | 0x2000 | 0x2000 | 4 MiB | 0x00400000 |
| mtd1 | kernel | 0x4000 | 0x4000 | 8 MiB | 0x00800000 |
| mtd2 | boot | 0x8000 | 0x8000 | 16 MiB | 0x01000000 |
| mtd3 | recovery | 0x10000 | 0x10000 | 32 MiB | 0x02000000 |
| mtd4 | backup | 0x20000 | 0x100000 | 512 MiB | 0x04000000 |
| mtd5 | cache | 0x120000 | 0x100000 | 512 MiB | 0x24000000 |
| mtd6 | userdata | 0x220000 | 0x200000 | 1 GiB | 0x44000000 |
| mtd7 | kpanic | 0x420000 | 0x2000 | 4 MiB | 0x84000000 |
| mtd8 | system | 0x422000 | 0x200000 | 1 GiB | 0x84400000 |
| mtd9 | user | 0x622000 | to the end | 4415488 KiB ≈ 4.21 GiB | 0xC4400000 |

Sectors 0x0–0x2000 (the first 4 MiB) hold the loader/IDB area and `parameter`; they are not exposed as an MTD partition.
The partitions `parameter`, `uboot`, `charge`, `cust`, `custom` (listed in the public C67ML TWRP device tree,
[AnClark/twrp_device_onyx_c67ml_carta2](https://github.com/AnClark/twrp_device_onyx_c67ml_carta2)) **do not exist on this device**:
the RC2 1.8.2 uses a different (later) layout.

**The mtd numbering depends on the boot slot** [CONFIRMED]: for the `boot` slot the loader passes
`mtdparts=rk29xxnand:0x00002000@0x00002000(misc),…` (mtd0 misc … mtd9 user, as above), while for the `recovery` slot it prepends
`(parameter)`, so every index shifts by +1 (user = mtd10). `/dev/block/mtd/by-name/*` does not depend on the slot; sysfs paths do.
`user` (mtd9) is the FAT32 book partition (`/sys/devices/virtual/mtd/mtd9/mtdblock9`). microSD: `/sys/devices/platform/rk29_sdmmc.0/mmc_host/mmc0`
(the second controller `rk29_sdmmc.1/mmc_host/mmc1` is the unused SDIO). USB host: `/sys/devices/platform/usb20_host`, OTG: `usb20_otg`.

## Hardware found

| Subsystem | Device / driver | Source |
|---|---|---|
| E-Ink controller | platform `rk29-ebc.0`, class `/sys/class/ebc_class/ebc`, debug node `ebc_dbg` ([`sys_ebc_nodes.txt`](proc/sys_ebc_nodes.txt)) | sysfs |
| E-Ink PMIC | **tps65185** @ i2c2-0x68 | sysfs i2c |
| EPD SPI flash | spi driver `epd_spi_flash` (`spi0.0`): the panel's own flash with panel ID, VCOM and a waveform (see the top-level README) | sysfs |
| Touch | **cyttsp4** (Cypress TrueTouch Gen4) @ i2c2-0x24, active, input `cyttsp4_mt`; the Goodix-TS driver @ i2c2-0x5d is also registered (alternative panel, absent here) | sysfs, getevent |
| Keys | `rk29-keypad` (event0) | getevent |
| System PMIC | act8931 @ i2c0-0x5b | sysfs |
| Fuel gauge | cw201x @ i2c0-0x62 | sysfs |
| RTC | hym8563 @ i2c0-0x51 | sysfs |
| GPU | mali + ump (modules) | /proc/modules |
| VPU/IPP | vpu_service, rk29_ipp (modules) | /proc/modules |
| NAND/eMMC | rk30xxnand_ko (module) | /proc/modules |
| Bluetooth | rtk_btusb (module) | /proc/modules |
| Wi-Fi | Realtek modules in /system/lib/modules: 8188eu, 8189es, 8192cu, 8723as/au/bu; the chip is an RTL8723BU (USB `0bda:b720`, `8723bu.ko`) | ls, logs |
| HAL | gralloc.rk30board.so, hwcomposer.rk30board.so, gpu.rk30board.so, lights.rk30board.so, power.rk3026.so, sensors.rk30board.so, camera.rk30board.so | /system/lib/hw |

I²C devices ([`sys_i2c_names.txt`](proc/sys_i2c_names.txt)), platform devices ([`sys_bus_devices.txt`](proc/sys_bus_devices.txt)),
input devices ([`getevent.txt`](proc/getevent.txt): the touchscreen reports X 0..1447, Y 0..1071, 32 slots), interrupts
([`proc_interrupts.txt`](proc/proc_interrupts.txt)), MMIO ([`proc_iomem.txt`](proc/proc_iomem.txt)), char devices
([`proc_devices.txt`](proc/proc_devices.txt)), modules ([`proc_modules.txt`](proc/proc_modules.txt)) and power supplies
([`power_supply.txt`](proc/power_supply.txt): `rk-ac`, `rk-bat`, `rk-usb`) are in [`proc/`](proc/).

## Stock userspace notes

- ONYX native libraries in /system: libonyx_ink.so, libonyx_pdf.so, libonyx_cropper.so, libonyx_algorithm.so,
  libonyx_stardict/dsl/mdict/babylon.so, libonyxfileutil.so, libonyx_aging_rtc_test.so, libonyx_memory_test.so. Apps include
  OnyxOtaService.apk and OnyxData-release.apk. No file in /system has epd/ebc/wave in its name.
- adb on stock runs as uid shell without `su`: `/dev/block/mtdblock*` and `/dev/mtd/*` are root-only, `dmesg` fails
  (`klogctl: Operation not permitted`), and there is no `/proc/config.gz`. busybox on the device has no sha256sum (md5sum, cksum,
  cpio and find exist).

## Rockusb loader mode

- Entry: `adb reboot loader`; the device appears as Rockusb, `rkflashtool v` → `Detected RK3026`, chip version `302A-2013.05.29-V101`.
  Exit: `rkflashtool b`.
- `rkflashtool n`: flash ID `45 4d 4d 43 20` ("EMMC "), Samsung, **7456 MB** (0xE90000 sectors), block 512 KB, page 2 KB.
- `rkflashtool p`: `parameter` is read from offset 0, size 0x29b ([`parameter.txt`](proc/parameter.txt)). MACHINE_MODEL rk30sdk,
  MACHINE 3066 (Rockchip generic id), FIRMWARE_VER 5.0.0, KERNEL_IMG 0x60408000, WAV_ADDR 0x7ff00000, RECOVER_KEY 0,2,b,5,0.
  The CMDLINE in `parameter` matches the runtime `/proc/cmdline` except `initrd=0x62000000,0x00800000` (in `parameter`) versus
  `0x00130000` (runtime, the actual ramdisk size), and the loader adds `bootver=2016-04-12#2.32 firmware_ver=5.0.0`.
- The first 4 MiB hold 8 copies of the `PARM` block every 512 KiB (0x0, 0x80000, …, 0x380000), the standard Rockchip parameter
  redundancy. PARM format: `PARM` + LE32 length + text + CRC32.
- IDB (`rkflashtool i 0 0x40`): the data is RC4-encrypted (as expected for a Rockchip IDB/loader).
- `misc` is all zeros on a normally booting device (empty BCB).

## Image formats

| Image | Header | Contents |
|---|---|---|
| kernel | `KRNL`, payload 7 766 052 B | raw kernel Image 3.0.36+ |
| boot | `KRNL`, payload 999 649 B | gzip'd cpio ramdisk (41 entries), **not** the ANDROID! format |
| recovery | `ANDROID!`, page 16384, kernel_size 7 766 052 (the same kernel), ramdisk addr 0x62000000 | a standard Android boot image with the recovery ramdisk |
| system | ext4 | /system |

`KRNL` images: 4-byte magic + LE32 payload length + payload (+ CRC at the end).

## Boot ramdisk (from `boot`)

Files: `init`, `init.rc`, `init.rk30board.rc`, `init.rk30board.usb.rc`, `init.rk30board.bootmode.emmc.rc`,
`init.rk30board.bootmode.unknown.rc`, `init.goldfish.rc`, `init.trace.rc`, `init.usb.rc`, `ueventd*.rc`, `default.prop`,
**`ebc_waveform.bin`** (256 003 B), **`rk30xxnand_ko.ko.3.0.36+`** (181 130 B).

- **`ebc_waveform.bin`**: identification string `320_R110_AE4D21_ED060KD1C2_TC` (panel **ED060KD1C2**). The kernel reads
  `/ebc_waveform.bin` from the ramdisk and copies it over the RAM copy at `waveform_addr=0x7ff00000`; the waveform in the panel's own
  SPI flash is not used for display [CONFIRMED by disassembly and log]. Format and decoder:
  [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform).
- **`rk30xxnand_ko.ko.3.0.36+`**: vermagic `3.0.36+ SMP preempt mod_unload ARMv7`, contains the eMMC adapter
  (`drivers/mtd/rknand/EMMC/hw_SDPlatAdapt.c`), which provides the MTD layer on top of eMMC (`onyx_emmc=1`).
- `ro.bootmode=unknown` on the running system, so init uses `init.rk30board.bootmode.unknown.rc` (the MTD/rk29xxnand branch), not
  the emmc variant, and `/dev/block/mtdblock*` are mounted.

## `backup` partition = factory RKAF package [CONFIRMED]

`backup` (512 MiB at sector 0x20000) starts with `RKAF`: a Rockchip AFPTool container (the inner part of an `update.img`),
407 783 424 B, model `rk30sdk`, id `007`, version 0x5000000. Recovery uses it for a factory reset (`recover-script`: rewrite system,
format cache/data) and a full restore (`update-script`: kernel, boot, recovery, system, backup, parameter, loader in MISC @0xC000).

Parts: `package-file`, **`RK3026Loader(L)_V2.32_otp.bin`** (182 606 B, `BOOT` header, version 2.32, date 2016-04-12, which is the
`bootver=2016-04-12#2.32`), `parameter` (PARM format), `misc.img` (48 KiB), `kernel.img` (7 766 064 B), `boot.img` (999 661 B),
`recovery.img` (20 234 240 B), `system.img` (378 535 936 B, ext4 image of the build with the same filesystem UUID as the live
/system), `update-script`, `recover-script`.

Compared with the live partitions: kernel, boot and recovery are **byte-identical** to the prefix of the live partition; misc differs
from 0x4000 (the live misc is zeros, the RKAF one has data); the live system differs from the RKAF `system.img` (the partition had been
mounted 286 times) but has the same UUID, so it is the same build. The `parameter` in RKAF is textually identical to the live one (only
line endings differ).

## EBC buffer info [CONFIRMED on the device]

`GET_EBC_BUFFER_INFO` (ioctl 0x7003 on `/dev/ebc`): width 1448, height 1072, vir_width 1448, vir_height 1072, fb_width 1448,
fb_height 1072, color_panel 0, **rotate 270**; ioctl 0x7004 → 3028; the mmap'd pool is vir_w × vir_h × 4 = 6 209 024 B (4 slots of
vir_w × vir_h). A frame is 4 bits per pixel, left pixel in the low nibble, 0 = black, 15 = white; rotation is done in software. The
full `/dev/ebc` ABI: [onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc).
