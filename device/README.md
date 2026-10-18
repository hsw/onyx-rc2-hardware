# Device facts: ONYX BOOX Robinson Crusoe 2 (MC_Kepler_R2)

Captured from one RC2 running stock firmware 1.8.2 over adb (uid shell, no root) and in Rockusb loader mode, 2026-10-06; the
eMMC boot partitions, the user area below `parameter` and the stock loader sections were added on 2026-10-17.
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
| PCB | pcb_ver=2 (= V1.73, see [`../board/README.md`](../board/README.md) §5); silkscreen `BOOX_KEPLER_RK3026_V1.3` on boards with that value ([below](#board-revision-and-chip-markings)) |
| Storage | onyx_emmc=1 (eMMC through the rk29xxnand / `rk30xxnand_ko` MTD layer; how the module drives the eMMC: [below](#rk30xxnand_ko-and-the-emmc)) |
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

Sectors 0x0–0x2000 (the first 4 MiB) hold `parameter` (8 copies, see Rockusb below); they are not exposed as an MTD partition.
These are loader LBAs: LBA 0 is eMMC user sector 0x2000. The loader itself lives in the eMMC hardware boot partitions, and
the 4 MiB of the user area before LBA 0 are described [below](#emmc-user-area-below-parameter-sectors-00x1fff).
The eMMC module adds a firmware offset of 0x2000 sectors to every MTD block address it passes to the eMMC
([below](#rk30xxnand_ko-and-the-emmc)).
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
| NAND/eMMC | rk30xxnand_ko (module): eMMC controller at 0x1021C000, IRQ 48, 8-bit bus, data through the PL330 DMA ([below](#rk30xxnand_ko-and-the-emmc)) | /proc/modules, boot log |
| Bluetooth | rtk_btusb (module) | /proc/modules |
| Wi-Fi | Realtek modules in /system/lib/modules: 8188eu, 8189es, 8192cu, 8723as/au/bu; the chip is an RTL8723BU (USB `0bda:b720`, `8723bu.ko`) | ls, logs |
| HAL | gralloc.rk30board.so, hwcomposer.rk30board.so, gpu.rk30board.so, lights.rk30board.so, power.rk3026.so, sensors.rk30board.so, camera.rk30board.so | /system/lib/hw |

I²C devices ([`sys_i2c_names.txt`](proc/sys_i2c_names.txt)), platform devices ([`sys_bus_devices.txt`](proc/sys_bus_devices.txt)),
input devices ([`getevent.txt`](proc/getevent.txt): the touchscreen reports X 0..1447, Y 0..1071, 32 slots), interrupts
([`proc_interrupts.txt`](proc/proc_interrupts.txt)), MMIO ([`proc_iomem.txt`](proc/proc_iomem.txt)), char devices
([`proc_devices.txt`](proc/proc_devices.txt)), modules ([`proc_modules.txt`](proc/proc_modules.txt)) and power supplies
([`power_supply.txt`](proc/power_supply.txt): `rk-ac`, `rk-bat`, `rk-usb`) are in [`proc/`](proc/).

## Board revision and chip markings

This RC2 has not been opened. The marks below are read from public photos of the same "Kepler" RK3026 board family; the
photos are not copied here, follow the links:

- **iXBT Live**, an RC2 teardown (2017-12-30):
  <https://www.ixbt.com/live/mobilepc/nepotoplyaemyy-robinson-crusoe---tehnologiya-vodozaschity-hzo-na-primere-elektronnoy-knigi-onyx-boox.html>.
  The text says the RC2 uses the Kepler board, coated with parylene; silkscreen `…KEPLER_RK3026_V1.3`; the chip marks
  cannot be read through the coating.
- **FCC ID XR3-KEPLER3026** (ONYX International Inc., grant 2017-06-24, models Kepler, Monte Cristo 2, Kepler Plus/Pro/Lite;
  the RC2 is not listed): internal photos at <https://fccid.io/XR3-KEPLER3026>. Bare board, silkscreen
  `…KEPLER_RK3026_V1.4`. Block diagram and schematics are confidential in the filing.
- **4PDA**, ONYX C67ML topic, post #3489 (2021-12-09), a Monte Cristo 3:
  <https://4pda.to/forum/index.php?showtopic=678336&st=3480>. Silkscreen `BOOX_KEPLER_RK3026_V1.3`; the post quotes the
  unit's `pcb_ver=2`.

| Part | FCC Kepler, V1.4 | 4PDA Monte Cristo 3, V1.3 |
|---|---|---|
| SoC | `RK3026` `SGAK3G802 1529` (2015 week 29) | `RK3026` `SGAK3W313 1720` (2017 week 20; the 7 is faint) |
| DRAM | Samsung `K4B4G1646E-BYK0`: DDR3L, 4 Gb ×16, one chip = 512 MiB | not read |
| Storage | SanDisk 8 GB raw NAND, TSOP (`…GAMA-008G`) | Samsung eMMC `KLM8G1GEME` (8 GB, `SEC 649` = 2016 week 49) |
| Wi-Fi / BT | Realtek `RTL8723BU` | RTL8723BU (Realtek logo, same place) |
| Clock | 24 MHz crystal `24.000` `SJK` | — |
| PMICs | a ~40-pin QFN among the inductors (the ACT8931 by position) and a 48-pin QFN with a boost inductor and diodes (the TPS65185 by position): no readable mark | the same two parts, no readable mark |

On the iXBT RC2 board the storage chip is a smaller BGA in a footprint that also takes the TSOP NAND, i.e. an eMMC, as on
this unit. Marks in the table are read from the photos [CONFIRMED-photo]; part identities by position are [STRONG] at best.

- **Silkscreen vs `pcb_ver`.** The Monte Cristo 3 board with silkscreen V1.3 reports `pcb_ver=2`, the value this RC2's
  loader passes and the stock kernel calls "V1.73" ([`../board/README.md`](../board/README.md) §5); the iXBT RC2 board is a
  V1.3 too. So the kernel's names (V1.4/V1.6, V1.7, V1.73, V1.76) and the silkscreen revision are two numbering schemes,
  and `pcb_ver=2` goes with silkscreen V1.3 [STRONG]. The FCC V1.4 board looks like the older design (2015 SoC, filed
  2017-06) despite the higher number [STRONG]; its `pcb_ver` is unknown.
- The "Samsung" that `rkflashtool` reports for this unit's eMMC is plausible: the V1.3 board above carries a Samsung eMMC.
  This unit's own part is unread.

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
- **`rkflashtool i` does not read the eMMC user area.** The loader's PBA read (Rockusb 0x04) maps PBA 0..0x3FF to the eMMC
  hardware boot partition **boot1** and 0x400..0x7FF to **boot2**, only their first 512 KiB; any PBA ≥ 0x800 folds back
  onto boot1. A 2 MiB `i 0 0x1000` dump is therefore boot1 + boot2 + boot1 + boot1, which looks like "four IDB copies at
  0/1024/2048/3072" [CONFIRMED: loader code, and the eMMC user area below holds no such copies]. On this book **boot1 =
  boot2**. Each copy: IDB header (init_offset 4, init_size 8, init_boot_size 232); the 8 init sectors are the DDR init
  (FlashData) and the 224 boot sectors the loader (FlashBoot), RC4-encrypted per 512 bytes; sector 1 (plain) gives loader
  date 2016-04-12, version 2.32. The 16 spare bytes per 528-byte sector are stale buffer contents.
- The loader writes boot2 itself: at every Rockusb entry (and before its own restore or update writes) it compares the first
  512 KiB of the current boot partition with boot2 and copies them over when they differ [STRONG, loader code]. With boot1 =
  boot2 nothing is written. Anyone editing boot1 alone gets it mirrored to boot2 at the next Rockusb entry [DANGER].
- `rkflashtool r/w` LBA 0 = eMMC user sector **0x2000**. The loader applies that offset only because user sector 0x40 starts
  with the IDB magic (next section).
- With a bootable microSD card inserted, `adb reboot loader` boots the card, not Rockusb: the reboot goes through the BootROM,
  which tries the card first [CONFIRMED]. Take the card out first.
- Idle in Rockusb for about 2 minutes (no command), or about 3.5 minutes without a host, the loader prints `power off` and
  releases the power hold [STRONG, loader code]. A dump script must not pause in loader mode.
- `misc` is all zeros on a normally booting device (empty BCB).

## eMMC user area below `parameter` (sectors 0..0x1FFF)

Dumped read-only on 2026-10-17 over the stock Rockusb, with read commands only, two identical reads [CONFIRMED]:

| User sectors | What the loader uses it for | On this book |
|---|---|---|
| 0x0040–0x005F | IDB header; its magic makes LBA 0 = user 0x2000 | an IDB header with the same fields as boot1 and a different 32-sector payload: a stub for the offset logic, not a bootable copy [STRONG] |
| 0x1800–0x19FF | panel waveform, 256 KiB, copied to `WAV_ADDR` 0x7ff00000 whenever the loader parses `parameter` | **all zero**, and so is the DRAM copy at 0x7ff00000 in loader mode. The waveform lives only in the boot ramdisk (`/ebc_waveform.bin`), which the stock kernel loads over that area |
| 0x1F80 | `SYSD` boot configuration (boot media, `secureBootEn`, …) | near-empty: secure boot off |
| 0x1F81 | `DRMK` key sector (DRM key, public key, secure-boot lock) | near-empty: no keys |
| 0x1F82–0x1F90 | vendor sectors (serial, MAC and the like if a factory tool wrote any) | all zero |
| everything else | not used by the loader | all zero |

Read paths that reach this area over stock Rockusb, all read-only [STRONG from the loader code; used for the dump]: cmd 0x14
(LBA read) with LBA `0xFFFFE000 + s` → user sector s (s < 0x1F00); cmd 0x21 → user 0x1800 + byte offset; cmd 0x14 at
`0xFFFFFF00 + k` → user 0x1F82 + k; cmd 0x17 → DRAM. The boot partitions beyond 512 KiB and EXT_CSD are not reachable over
Rockusb. The stock kernel's `rk30xxnand_ko` reads the same `SYSD`/`DRMK`/vendor sectors and exposes them as
`/dev/rknand_sys_storage`; nothing else in the stock kernel reads below user 0x2000.

## Stock loader (FlashBoot 2.32)

Read in its code [STRONG unless marked]; the kernel hand-off itself is in [`../bootrom/sdboot/README.md`](../bootrom/sdboot/README.md)
("Hand-off").
- It never touches the panel, EBC, LCDC, I2C, PMIC, PWM, watchdog or eFuse: no boot logo, no charge screen, no battery or
  power-on-reason logic. There is no loader-side EBC or TPS65185 sequence to copy for a new kernel.
- Reboot flags in `GRF_OS_REG4`: [`../soc/README.md`](../soc/README.md) §4.2.
- Its soft reset (`rkflashtool b`, and after its own restores) does not use a CRU global reset: IRQs off, USB soft disconnect,
  eMMC back to boot1 access with a pre-idle CMD0, caches off, PLLs to slow mode, IMEM remap cleared, then a jump to the
  BootROM at address 0. The ROM runs its media order again, so an inserted microSD card boots first.
- Other writes of its own: EXT_CSD `WR_REL_SET` = 0x1f once, `PARTITION_CONFIG` on every access switch, `SYSD`/`DRMK` when
  their tags are missing, and a restore of `kernel`/`boot`/`recovery` from the `backup` RKAF when loading one fails
  ("Begin recover...").
- **What it checks on an ANDROID! image** (loaded from `recovery` on a recovery request) — useful for chainloading
  another loader:
  - the page size is fixed at **16 KiB** (the header's `page_size` is only hashed): kernel from partition offset 16 KiB,
    ramdisk after the kernel rounded up to 16 KiB;
  - the kernel goes to the header's **`kernel_addr`**, with no address or size check and no look at the bytes, so any raw
    binary linked there runs (0x60408000, the stock kernel address, is clear of the loader's own memory);
  - the Rockchip **SHA1 `id`** must match (SHA1 over kernel, kernel_size, ramdisk, ramdisk_size, second, second_size,
    tags_addr, page_size, unused, name, cmdline; `id[5..7]` = 0). A mismatch makes the loader **restore `recovery` from
    `backup`** and boot stock recovery [DANGER, recoverable];
  - `second_size` must be 0 (the second stage is hashed from address 0);
  - no signature check while `SYSD` says secure boot is off, as on this book;
  - the cmdline and ATAGs come from `parameter` (the header cmdline is not passed; the `initrd=` size is rewritten from
    `ramdisk_size`); entry as for the normal kernel: r0 0, r1 3066, r2 0x60000800, MMU and caches off, remap set, CPU1 in
    reset, power hold high.

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
  (`drivers/mtd/rknand/EMMC/hw_SDPlatAdapt.c`), which provides the MTD layer on top of eMMC (`onyx_emmc=1`). Embedded
  versions: `rknand_buffer.c version: 4.40 20130830`, `FTL version: 5.0.31 20160325`; not stripped. Static analysis:
  [below](#rk30xxnand_ko-and-the-emmc).
- `ro.bootmode=unknown` on the running system, so init uses `init.rk30board.bootmode.unknown.rc` (the MTD/rk29xxnand branch), not
  the emmc variant, and `/dev/block/mtdblock*` are mounted.

## `rk30xxnand_ko` and the eMMC

The module has no public source. What follows comes from static analysis of the stock module (disassembly with
relocations, nothing executed) and the stock boot log. [CONFIRMED] = disassembly and log agree; [STRONG] = disassembly only.
Addresses are offsets in the module's `.text`.

- **Kernel side.** The module registers no MTD or block device itself: the wrapper built into the stock kernel
  (`drivers/mtd/rknand/rknand_base_ko.c`, platform driver and MTD `rk29xxnand`, `mtdparts=` from the cmdline) hands it its
  `struct rknand_info` through `get_rknand_device`, and the module fills in the FTL read/write/sync/suspend hooks. The
  field offsets after the chip structure are 4 bytes larger than the public header suggests (SMP + PREEMPT ARM enables
  `GENERIC_LOCKBREAK`) [STRONG].
- **Medium choice.** At load time the module reads the `SYSD` block that the loader leaves in the NAND controller's SRAM:
  boot medium 2 and firmware offset 0x2000 on the RC2 (`gBootMedia = 2 gSdmmcFwPartOffset =2000`). Raw-NAND
  initialisation fails and it falls back to the eMMC (`CardId = 2`, `SdmmcInit ret = 0!`) [CONFIRMED]. Every MTD block
  address is then shifted by **0x2000 sectors (4 MiB)** before it reaches the eMMC [CONFIRMED].
- **Controller.** The Synopsys-style SD/MMC controller `emmc` at **0x1021C000** (mapped by a constant address, not from
  platform resources), **IRQ 48** (`emmc`), clock `emmc` set to 50 MHz plus `hclk_emmc`; the log then reports
  `EmmcBus_khz = 96000`, an **8-bit** bus and 0xE90000 user sectors (7456 MiB) [CONFIRMED]. The module has its own SD/MMC
  stack, not the kernel's `mmc_core`. It **also requests IRQ 50 (`nandc`)** even on this eMMC book; the line stays at
  zero in [`proc_interrupts.txt`](proc/proc_interrupts.txt) [CONFIRMED].
- **DMA.** Transfers use the SoC's PL330 through the stock kernel's `rk29_dma_*` API, not dmaengine
  ([`../soc/README.md`](../soc/README.md) §1.1). The channel number **14 (`DMACH_EMMC`) is hard-coded** (request line 12);
  configuration 4-byte unit, burst 16; the peripheral address is the controller FIFO **0x1021C200** (base + 0x200). Per
  transfer: `rk29_dma_devconfig` (direction, FIFO) → `rk29_dma_enqueue` → set the controller's external-DMA enable
  (`CTRL` bit 5) → `rk29_dma_ctrl(START)` → then the command; afterwards `rk29_dma_ctrl(STOP)` and the enable bit is
  cleared (`SDPAM_DMAStart` @0x12d18, `SDC_BusRequest` @0x131d4, `SDPAM_DMAStop` @0x12e58) [STRONG].
- **Cache maintenance only through `___dma_single_cpu_to_dev`/`___dma_single_dev_to_cpu`** (before and after the
  transfer). In the 3.0 kernel these do both L1 and the PL310 L2 themselves; the module imports no `outer_cache`, no
  `dma_map_*`, no `dma_alloc_coherent` [STRONG].
- **Physical address computed inline** as VA − 0x60000000 (PAGE_OFFSET 0xC0000000, RAM at 0x60000000), with **no lowmem
  check**; a vmalloc buffer would get a wrong address. In practice reads of whole 8 KiB pages go straight into the
  caller's (lowmem) buffer, partial pages through a 256 KiB read cache, and every write is first copied into the wrapper's
  static write-back pool and written later by a kernel thread. The RC2 has no highmem [STRONG].
- **Completion by the eMMC interrupt**: the IRQ handler completes the command and the data-transfer-over (DTO) events;
  the data wait has no timeout. The PL330 completion callback only sets a variable nobody reads [STRONG]. On an error the
  module re-initialises the controller and retries up to 3 times.
- **PIO for short transfers**: writes up to 1 KiB and reads up to 512 B go through the FIFO by the CPU, without DMA or
  cache work [STRONG].
- The raw-NAND path (NandC v6 with its own bus-master DMA, the FTL with garbage collection and read-retry tables) is in the
  module but not executed on the RC2.
- **For a port:** the module is bound to the stock kernel by the `rk29_dma_*` channel numbers, the internal
  `___dma_single_*` helpers, the fixed VA→PA formula and the `rknand_info` layout; it cannot be moved to another kernel.
  In mainline the eMMC is `dw_mmc` (`rk3036.dtsi` `emmc` node with `dmas = <&pdma 12>`), and the 0x2000-sector offset
  has to be added to the stock partition offsets [STRONG].
- Open [VERIFY]: whether the controller has the dw_mmc internal DMA (IDMAC) as well; which bus mode (HS SDR or DDR)
  the module picks at 96 MHz.

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
