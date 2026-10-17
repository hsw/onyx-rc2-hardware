# sdboot: boot the stock RC2 kernel from a microSD card

The RK3026 BootROM tries the microSD card before the eMMC on every reset ([`../README.md`](../README.md)). sdboot uses that. It
builds a card image that the ROM accepts. The card runs the stock DDR init, then our **stage2**. stage2 loads the stock kernel
Image, a ramdisk and the panel waveform from the card, sets up the hand-off like the stock loader, and jumps to the kernel.
Nothing on this path reads or writes the eMMC. Pull the card, and the book boots from its eMMC as before.

The kernel is the stock ONYX **3.0.36+ vendor kernel**, booted the way its loader boots it: ATAGs, machine number 3066 (MACH RK30),
no device tree. sdboot is not a loader for a mainline kernel.

Everything here was checked on one RC2 (pcb V1.73, stock firmware 1.8.2). Confidence marks as in the
[top README](../../README.md#confidence-marks).

```
power on / reset
 └ BootROM: SD init, IDB header at card LBA 64 (RC4), init stage -> SRAM 0x10080800
    └ stock FlashData (DDR init), returns 0 to the ROM
 └ BootROM: loads the boot part (= stage2) in 2 KB chunks to DDR 0x60000000, jumps to it
    └ stage2: power hold, relocate to 0x60080000, boot table (LBA 8192), kernel / ramdisk / waveform through the ROM's
      own SD read routine 0x168c, CRC32 of each, ATAGs, CPU1 reset, remap, caches off, jump to 0x60408000
       └ stock kernel 3.0.36+ -> initramfs /init
```

## Requirements

| Step | Needs |
|---|---|
| write a card: `write-card.sh` (+ `diskguard.py`, `mbrguard.py`, `formatdata.py`) | macOS built-ins only: `diskutil`, `dd`, `newfs_msdos`, `fsck_msdos`, `shasum`, `stat`, `mktemp`, and `python3` with the standard library only (`/usr/bin/python3` of the Xcode Command Line Tools, 3.9, is enough). No Homebrew |
| card image: `mkcard.py` | `python3` (standard library) and e2fsprogs for partition 1: `brew install e2fsprogs` on macOS (keg-only: used from `/opt/homebrew/opt/e2fsprogs/sbin`, `E2FSPROGS_SBIN` overrides), `/usr/sbin` on Linux. Same bytes for one e2fsprogs version (1.47.4 here). `mkdata.sh` (a prefilled `--data-img`) also needs mtools and dosfstools |
| stage2: `stage2/build.sh` | Homebrew `llvm` and `lld` (`brew install llvm lld`; Apple clang has no `ld.lld` or `llvm-objcopy`; `LLVM`/`LLD` override the paths). Same toolchain, same bytes: built with clang/LLD 23.1.3 (recorded in `toolchain.txt` next to `stage2.bin`), `stage2.bin` is `b95cfad9…` (`tests/run.sh` checks it whenever the toolchain is 23.1.3); another version may give other bytes |
| tests: `tests/run.sh` | all of the above, and `uv` (Unicorn 2.1.4 and Capstone 5.0.7 come as inline script dependencies, Python ≥ 3.10). Optional: mtools and dosfstools (FAT32 cross-checks, `SKIP` lines without them), shellcheck. `test_format_data.py` needs macOS (`diskutil image attach`), `SKIP` elsewhere |

## Status

Tested on the RC2 with a 2 GB SanDisk SDSU02G card (SDSC, byte addressing) [CONFIRMED]:

- The ROM takes the card before the intact eMMC loader, on a warm reset (`adb reboot`) and on a cold power-on with the charger
  attached. So the SD supply (ACT8931 LDO3) is on at ROM time.
- HALT card (stage2 loads and checks everything, does not jump): LED codes 1 to 5, then the HALT pattern. The stage2 log in DDR
  survived into the next Android boot and was read there.
- Test ramdisk (`ramdisk-sd/`): the kernel and the ramdisk run from the card. `/proc/cpuinfo` shows 2 CPUs (CPU1 came up through the
  remap), the kernel sees the card (`mmcblk0`, `mmcblk0p1`), and the ramdisk decoded the stage2 log from DDR.
- A Linux root file system on partition 1 (ext4) with a reader application, and the FAT32 data partition (p2) for books: booted
  and used, also after warm reboots and on battery after a warm reboot.
- After every SD test, the card was pulled and Android booted from the eMMC as before.

Only in emulation (Unicorn on the BootROM dump, [Tests](#tests)): SDHC cards (block addressing), SD read errors and retries,
every failure path of stage2, and `--chunk` values above 4.

The stage2 binary in the tests above has sha256 `11e3dec2a942ffd5ee66a80b435791b852bfee46729692df55d9287cb8aefa83` (6536 B),
built from the sources before the L1 invalidate at entry. The current stage2 (with it, see [Fixed](#fixed)) has sha256
`b95cfad9fe6be2d1933d8281d0e5f4b8956d401a9354300b92a02eaa676260a5` (6628 B); it was used on the book for the warm-reset
tests from mainline Linux. `stage2/build.sh` with clang and LLD 23.1.3 (Homebrew on macOS, or the official release on Linux)
rebuilds exactly these bytes.

### Known failures

- **Cold power-on on battery boots Android, not the card** [CONFIRMED, cause VERIFY]. With the card in, every warm reset and every
  cold power-on with USB attached boots the card. A cold power-on without USB boots the eMMC; the DDR log area held no stage2 log,
  so the ROM skipped the card. Either the card is not ready within the ROM's ACMD41 budget (2040 polls without delay, about 1 s)
  when everything powers up at once, or LDO3 is off at a cold start without VBUS. Workaround: power on into Android, then reboot.
- **Reset pinhole with the card in: the ROM skipped the card** [CONFIRMED, cause VERIFY]. First seen with a card inserted into a
  running book; later every pinhole reset with the card already in booted the eMMC (more than ten tries), while software resets
  (`reboot`, the watchdog) boot the card. A cold power-on with the card worked. Insert the card, then power on.
- One boot reached `jump` and then showed a blank panel; the stage2 log read back afterwards had bit flips. Not reproduced.
- The test ramdisk's LED heartbeat goes through the stock `leds-ctl` driver, which prints a line to the kernel log on every write.

### Fixed

- **Warm reset from a kernel that leaves dirty cache lines** [CONFIRMED with mainline Linux]. The Cortex-A9 does not
  invalidate its caches on reset. Like stock FlashBoot, stage2 up to `11e3dec2…` invalidated only the I-cache and the branch
  predictor and ran with the D-cache off. The stock kernel cleans its caches before it resets, so `reboot` from it was fine;
  mainline's restart path, or a watchdog reset of a hung kernel, left the dead kernel's lines in L1, and the next kernel
  faulted right after the decompressor's jump. stage2 now invalidates the whole L1 D-cache by set/way (invalidate only,
  never clean) plus TLBs, I-cache and branch predictor at entry ([stage2](#stage2),
  [`../../soc/README.md`](../../soc/README.md) §4.5). With `b95cfad9…` on the card, `reboot -f` (`GLB_SRST_SND`),
  and `GLB_SRST_FST` from mainline Linux came back to the card [CONFIRMED].

## Hand-off: stock loader vs stage2

What the stock loader (FlashBoot 2.32) does at the jump was read from its code and checked against the kernel. stage2 does the same,
except where the table says otherwise.

| | stock FlashBoot 2.32 | stage2 |
|---|---|---|
| r0 / r1 / r2 | 0 / 3066 (MACH RK30, the kernel's only `machine_desc`) / 0x60000800 | same |
| entry, CPSR | 0x60408000, SVC with IRQ and FIQ masked | same |
| MMU, caches | off (D-cache cleaned, L2 disabled) | off (stage2 never enables the D-cache, L2 or MMU); L1 D-cache, TLBs, I-cache and branch predictor invalidated at entry (warm reset, [Fixed](#fixed)) |
| ATAGs | CORE (flags 0, pagesize 0, rootdev 0) + CMDLINE + NONE; no MEM, INITRD, SERIAL, REVISION | same layout |
| memory size | none: the kernel's `rk2928_fixup` reads it from the DDR controller | none |
| initrd | cmdline `initrd=0x62000000,<size>`, size rounded up to 64 KiB (+256 KiB slack) | exact size |
| cmdline | from `parameter` (+ `mtdparts`) + ` bootver=2016-04-12#2.32 firmware_ver=5.0.0` | `console=ttyFIQ0 androidboot.console=ttyFIQ0 waveform_addr=0x7ff00000 init=/init initrd=0x62000000,0x<size> pcb_ver=2 onyx_emmc=1 rc2.root=sd` |
| power hold GPIO1_A2 | high (early, and again before the jump) | high, first instructions |
| GRF_SOC_CON0 bit 12 | set at FlashBoot entry | set as the very last write before the jump |
| CPU1 | soft reset asserted | same |
| waveform at 0x7ff00000 | 256 KiB from eMMC user sectors 0x1800–0x19FF, which are all zero on this book | `ebc_waveform.bin` from the card |
| PLLs, DDR, PMIC, watchdog, USB | not touched (as the DDR init left them; the kernel reprograms them) | not touched |
| NAND controller flash info (0x10501000), eMMC | prepared for `rk30xxnand_ko` | **never touched** |

- **GRF_SOC_CON0 bit 12** (`0x20008140` = `0x10001000`) maps IMEM at address 0 instead of the ROM
  ([`../../soc/README.md`](../../soc/README.md) §1.3). The kernel starts CPU1 through
  that mapping, so without it the kernel runs on one CPU. stage2 still needs the ROM at address 0 for its reads, so it sets the bit
  as its last write, after all reads are done. On hardware the kernel then reported 2 CPUs [CONFIRMED].
- **CPU1**: stage2 writes the reset assert (`CRU_SOFTRST_CON0` = `0x00100010`) as stock does. On the RK3026 that write
  restarts CPU1 into the ROM wait loop instead of holding it; the kernel starts it with a reset pulse (§4.3 and §1.3 of
  [`../../soc/README.md`](../../soc/README.md)).
- `onyx_emmc=1` must stay. It moves the SD card-detect to GPIO2_A3, as on the eMMC boards. Without it the kernel does not see the card.
- `pcb_ver=2` is what the stock loader passes on this board.
- `mtdparts` is dropped. Only the NAND/eMMC module `rk30xxnand_ko` uses it, and that module must not be loaded on the SD path.
- The stock kernel overwrites the waveform at 0x7ff00000 with `/ebc_waveform.bin` from the initramfs. On this book the stock
  loader's copy is zeros (the eMMC area is empty, [`../../device/README.md`](../../device/README.md)), so the initramfs file is
  the only waveform; stage2 loads the same file so the area is valid from the start.
- `rc2.root=sd` is a flag for the ramdisk's `/init`: the system was started from the card ([Ramdisk](#ramdisk)).

## Storage access: the ROM's own read routine

stage2 has no SD driver. It calls the BootROM routine `0x168c read(sector, buf, bytes)` (0 = OK, 1 = error) at its address in the ROM
alias at 0. The ROM uses the same routine to load stage2 itself.

- **Proven on hardware in this very state.** After the DDR init returns, the ROM loads the boot part with this routine:
  `0x1820` calls `0x168c(sector, 0x60000000 + 0x800·n, 0x800)` [CONFIRMED].
- **IMEM state it needs** [CONFIRMED in the code; checked in Unicorn by filling the rest of IMEM with garbage]:
  - `IMEM+0x00`: delay factor (24, or `0xC0` after the PLL setup);
  - `IMEM+0x40`: card class. `& 0x84` means block addressing; otherwise the address is `sector << 9`;
  - `IMEM+0x44`: controller. 0 = SDMMC0; anything else selects the eMMC controller.
  
  The ROM's SD init leaves these values. The DDR init does not touch them: it runs from `0x10080800`, and the ROM stacks are at
  `+0x2b8`..`+0x767`. **stage2 refuses to call the ROM unless `IMEM+0x44` is 0**, so a read can never go to the eMMC controller.
- **Contract:** one sector → CMD17; more → CMD18 + CMD12. BYTCNT = bytes, BLKSIZ = 512, PIO through the FIFO with **32-bit
  stores**, so the buffer must be 4-byte aligned. No DMA, no interrupt. Data CRC, end-bit, start-bit and read-timeout errors
  (RINTSTS `0xa280`), or a FIFO wait of 100 000 polls, return 1.
- **Read only:** the whole read closure (`0x168c`, `0x115c`, `0x17a8`, `0x1738`, `0x176c`, `0x64c`, `0xd8`) writes only the
  command values `0x2351` (CMD17), `0x2352` (CMD18) and `0x1414c` (CMD12). The DesignWare write bit `0x400` is never set. The ROM has
  no write command at all ([`../README.md`](../README.md) §6).
- **Timing:** the ROM's poll timeouts are delay loops calibrated for uncached execution; the ROM never enables the I-cache.
  `rom_call` switches the I-cache and branch prediction off for each call and restores them after, so the ROM runs as it did when it
  loaded stage2.
- A failed chunk is retried twice. Reads have no side effects.
- **Chunk:** 4 sectors (2 KB) per call by default, the size the ROM itself uses. `mkcard.py --chunk N` (N ≤ 128) is untested on
  hardware.

## Card layout

**Card size.** Data layout (`--data-partition`): nothing to pass. The image ends with p1 (320 MiB); `write-card.sh` sets p2's
length in the MBR from the card it writes to (disk size rounded down to 32 KiB) and formats p2 there (below). Full images (single
layout, or the data layout with `--data-img`): the image has exactly `mkcard.py --card-bytes N` bytes, and the last partition
ends at N. The default is the 2 GB test card: 1 977 614 336 B = 3 862 528 sectors of 512 B; the numbers below are for it, and only
the last partition changes with the size. N must be a multiple of 32 KiB (the write block), at least the layout's minimum (single:
boot area + 256 MiB p1 = 335 544 320 B; data: boot area + p1 + the smallest FAT32 p2 = 608 141 312 B) and at most 32 GiB
(34 359 738 368 B). Use your card's size (`diskutil info diskN`, "Disk Size") or anything smaller. `manifest.json` records
`image_bytes` and `card_bytes` (null in the data layout).

Why 32 GiB: that is the SDHC ceiling, and the RC2's spec is believed to be microSD up to 32 GB. An SDXC card comes formatted exFAT,
and the stock 3.0 kernel has vfat but no exFAT, so it would need FAT32 anyway. The real limit for booting is the ROM's OCR rule
(**OCR bug** below): only the 2 GB SDSC card is tested on the device.

| LBA | Size | Content |
|---|---|---|
| 0 | 512 B | MBR, disk signature `RC2S`, no boot flag (the ROM ignores the MBR) |
| 64 | 7 + 8 + stage2 sectors | IDBlock copy 0, every sector RC4'd: the stock header from your IDB with `init_boot_size` = 8 + stage2 sectors; stock sectors 1–3; the stock FlashData (8 sectors, the DDR init); stage2, padded to 2 KB |
| 1088, 2112, 3136, 4160 | | the ROM's IDB copies 1–4: left zero on purpose (one place to inspect or erase) |
| 8192 | 1024 B | boot table (below) |
| 16384 | 7 766 052 B | kernel Image → 0x60408000 |
| 32768 | | ramdisk (gzip cpio) → 0x62000000 |
| next 1 MiB boundary | 256 003 B | `ebc_waveform.bin` → 0x7ff00000 |
| 131072 | | partition 1 (and 2) |

Blobs start at 8 MiB on 1 MiB boundaries and must end before 64 MiB. The first 64 MiB are the **boot area**.

**Single layout** (default): p1 at LBA 131072 to the end of the card, type 0x83, ext4 labelled `rc2root`. It is empty, or
`--rootfs-img` copied as is. The ext4 feature set is one the 3.0 kernel can mount (no `metadata_csum`, `64bit`, `flex_bg`,
`huge_file`; `mke2fs.conf`).

**Data layout** (`--data-partition`): a new root file system does not overwrite the user data.

| Partition | LBA | Sectors | Type | Content |
|---|---|---|---|---|
| p1 | 131072 | 524 288 (256 MiB) | 0x83 | ext4 `rc2root`: empty, or `--rootfs-img` resized to 65536 blocks of 4 KiB (`e2fsck`, `resize2fs`, `tune2fs -T`) |
| p2 | 655 360 | to the card end, rounded down to 32 KiB (2 GB card: 3 207 168) | 0x0C | FAT32 `RC2DATA`, formatted on the card by `write-card.sh`; or `--data-img` in a full image |

- **p2 is formatted on the card, not shipped in the image.** `sdcard.img` holds only [0, end of p1) = 335 544 320 B; p2's MBR
  entry carries a placeholder length (the 2 GB card's) and the manifest marks p2 `format_on_write`. The whole write puts the
  card's p2 length into a copy of the first 32 KiB block (only MBR bytes 474..477 change), writes and reads back, then
  `formatdata.py` formats p2 with macOS `newfs_msdos -F 32`: label `RC2DATA`, serial `0x52433244`, hidden sectors 655 360, two
  FATs, reserved area and both FATs in whole 32 KiB units, data region at a 4 MiB multiple, and 32 KiB clusters where FAT32
  still has more than 65 525 of them, else 16, 8 or 4 KiB. The 2 GB card gets **16 KiB** clusters (32 KiB would leave 49 984
  clusters: FAT16 by count); 4 GiB and larger get 32 KiB. The boot sector is read back and checked, then `fsck_msdos -n`.

- The stock 3.0 kernel has vfat with `nls_cp437` and `nls_iso8859-1` but no `nls_utf8`. Mount p2 with
  `-t vfat -o utf8,codepage=437,iocharset=iso8859-1,shortname=mixed` to get UTF-8 long names.
- `--data-img` makes a full image with a prebuilt p2 (`--card-bytes` applies). `mkdata.sh OUT.img DIR [CARD_BYTES]` makes a
  filled p2 image (mtools, dosfstools; the empty volume from `fat32.py`, a deterministic FAT32 writer with 4 KiB clusters);
  `fat32.py --card-bytes N` an empty one. `--data-img` must be exactly the p2 size of that card size.

**OCR bug.** The card layout supports SDSC cards and SDHC cards whose ready OCR is exactly `0xC0FF8000` or `0xC0FF8080`. Any other
SDHC/SDXC card is byte-addressed by the ROM ([`../README.md`](../README.md) "The OCR bug"): ROM sector *s* is read from card block
512·*s*. Such a card would need the IDB header at block 32768 and every 2 KB chunk *n* of the payload at block 34816 + 2048·*n*,
and stage2's own reads would land at 512·*s* too. mkcard.py does not build that. On such a card the ROM finds no IDB magic at block
32768 (the ramdisk starts there) and boots the eMMC [STRONG, not tested].

**Reproducible.** The same inputs and tools give the same `sdcard.img`, byte for byte: fixed UUID, hash seed and timestamps for
ext4 (`E2FSPROGS_FAKE_TIME`, `tune2fs -T` with `TZ=UTC`), a stdlib FAT32 writer. One e2fsprogs version gives one result (tested with
1.47.4).

`manifest.json` / `manifest.txt` record the sha256 of the whole image, of the boot area, of the first 320 MiB (data layout: boot
area + p1), of every partition and of every input, plus the MBR table bytes.

### Boot table (LBA 8192, 1024 bytes, little endian; `stage2/bootinfo.h`)

| Offset | Field |
|---|---|
| 0x00 | magic `0x54423252` ("R2BT"), version 1, size 1024, flags (bit 0 HALT: load and check, never jump; bit 1 QUIET: no progress blinks) |
| 0x10 | machine 3066, ATAGs 0x60000800, entry 0x60408000, chunk_sectors |
| 0x20 | nblobs (1..4), cmdline_len |
| 0x40 | 4 × {kind (1 kernel, 2 ramdisk, 3 data), lba, size, load, crc32 (zlib), 3 × reserved} |
| 0x100 | cmdline, NUL-terminated, printable ASCII, < 764 bytes |
| 0x3fc | CRC32 of bytes 0..0x3fb |

stage2 checks everything before it loads anything: magic, version, CRC, machine ≠ 0, ATAGs inside the first 1 MiB of DDR and away
from stage2, blob 0 is the kernel and its load address is the entry, every blob between LBA 8194 and 131072, load addresses
word-aligned in DDR, no overlap with stage2 (0x60080000–0x600c0000), the log page, the ATAGs or another blob.

## stage2

- `stage2/`: `start.S`, `stage2.c`, `bootinfo.h`, `stage2.ld`, `build.sh`. Bare-metal ARMv7 (Cortex-A9, ARM state), 6.5 KB.
  Built with `-mno-unaligned-access`: with the MMU off every access is strongly ordered.
- Memory: the ROM loads it at 0x60000000; it moves itself to 0x60080000 (image, bss and a 16 KB stack, all below 0x600c0000), so
  0x60000800 is free for the ATAGs, as with stock.
- Order: power hold → caches off as stock → L1 D-cache invalidate by set/way + TLBIALL/ICIALLU/BPIALL → relocate → log →
  LED → CPU1 reset → I-cache on (only for CRC and LED timing) → `IMEM+0x44` check → boot table → per blob: read, CRC32 →
  ATAGs → jump (LED flicker, LED off, remap, caches off).
- L1 invalidate at entry (not in stock FlashBoot): after a warm reset (`GLB_SRST_FST`/`SND`, watchdog) from a kernel that
  did not clean its caches, L1 keeps that kernel's dirty lines; the decompressor turns the D-cache on without invalidating
  it and the stale lines corrupt the new kernel image ([Fixed](#fixed)). Invalidate only (never clean), once: stage2 never
  sets SCTLR.C, and with the MMU off no line is allocated before the jump. The geometry comes from CCSIDR, the walk is the
  one of Linux `v7_invalidate_l1`.

### LED codes (status LED GPIO2_B7, blue, active high)

Short blink = 150 ms on / 250 ms off; groups are separated by 0.7 s dark. Timings assume about 600 MHz with the I-cache on.
Without USB power the blue LED did not light on our book, so the codes can only be read on the charger.

| Pattern | Meaning |
|---|---|
| 1 short | stage2 runs (power hold already set) |
| 2 short | boot table read and valid |
| 3 short | kernel read, CRC OK (several seconds after 2) |
| 4 short | ramdisk read, CRC OK |
| 5 short | waveform read, CRC OK |
| 3 very fast flickers, then dark | jumping to the kernel |
| 2.5 s on / 0.3 s off, forever | HALT card: everything loaded and checked; stage2 stops on purpose |
| **1.5 s on**, then *N* blinks, [1 s, *M* blinks], 2.5 s dark, repeated | **failure**, stage2 spins. N = 1 boot table bad, 2 SD read error (after 3 tries), 3 CRC mismatch, 4 ROM state (controller ≠ SDMMC0). M = blob: 1 kernel, 2 ramdisk, 3 waveform |
| nothing at all, panel unchanged | the ROM did not take the card, or the DDR init hung |

### Log in DDR

A 4 KiB text log at **0x7fff0000**: header `{magic 0x474c3253 "S2LG", version, len, stage, fail, fail_arg, fail_val, retries}`, then
text. The page is the end of the kernel's reserved 1 MiB waveform window. The EBC driver fills only the first 256 003 bytes of it,
so the kernel never touches the log. Read it with `busybox devmem` or another mmap of `/dev/mem`; a `read()` of `/dev/mem` fails there
because the window is not kernel RAM. On hardware the log survived a reset into Android [CONFIRMED]. Example (emulated):

```
RC2 sdboot stage2 v1
load 0x60000000 run 0x60080000 size 0x00001988
rom 0x32393243 imem0 0x00000018 sdclass 0x00000008 ctl 0x00000000 rca 0x00001234
table ok flags 0x00000000 blobs 3 chunk 4
blob 0 kind 1 lba 16384 size 7766052 -> 0x60408000
...
cmdline console=ttyFIQ0 ... rc2.root=sd
jump
```

## Ramdisk

`ramdisk-sd/` builds a minimal test ramdisk ("m0"). Its `/init` mounts proc, sysfs, devtmpfs and tmpfs only, writes the uptime, CPU
count, `/proc/cmdline`, the `mmcblk` lines of `/proc/partitions` and the decoded stage2 log to tmpfs, and blinks the LED 1 s on /
1 s off. If the ramdisk carries `/sbin/ebc-console` (a text console for the panel, not in this repository), it shows these on the
panel. No insmod, no block device, no write outside tmpfs. The on-device run used an `/init` that started ebc-console
unconditionally; the published one checks for it first.

Any ramdisk that boots from this card must follow these rules:

1. **Never** load `rk30xxnand_ko` and never touch `/proc/mtd`, `/dev/mtd*` or the eMMC partitions. [DANGER] On the SD path the
   loader's flash-info hand-off is missing, so the module's behaviour is unknown, and every read-write mount of an eMMC partition
   writes to it.
2. Find the root by label: wait (up to about 10 s) for `LABEL=rc2root` (busybox `findfs` or `blkid`), mount it
   `-t ext4 -o rw,noatime`, `switch_root`.
3. Keep `/ebc_waveform.bin` in the initramfs: the stock EBC driver reads it from there.
4. `rc2.root=sd` on the cmdline tells `/init` that it was started from the card.

## Inputs

None of the vendor files are in this repository. You need these from your own device or firmware:

| Input | `mkcard.py` option | Where it comes from |
|---|---|---|
| IDB dump | `--idb` | Rockusb loader mode (`adb reboot loader`), then `rkflashtool i 0 12 > idb.bin` (or more sectors). The dump has 528-byte sectors. The stock header, sectors 1–3 and the DDR init (FlashData) are taken from it |
| RC4 key | `--rc4-key` or `RK_RC4_KEY` | the standard Rockchip IDBlock key, 32 hex digits. Public copies: U-Boot `tools/rkcommon.c` (`rc4_key`), rkdeveloptool. A wrong key is refused: the header does not decrypt to `0x0FF0AA55` |
| kernel Image | `--kernel` | the `kernel` partition (`KRNL` image: strip the 8-byte header and the 4-byte CRC at the end), or `kernel.img` of a firmware update package. Ours: 7 766 052 B, sha256 `47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af` (firmware 1.8.2). The 1.9.1 kernel was not tried |
| waveform | `--waveform` | `/ebc_waveform.bin` in the stock boot ramdisk (the `boot` partition, a `KRNL` image of a gzip cpio). Ours: 256 003 B, sha256 `fe72b4ba1721e85dacb35c052e02f82d26cdd95b6df7f856df3dcb5e2bbc8ca8` |
| loader file (optional) | `--loader` | the RKBOOT loader in your firmware update package (ours: `RK3026Loader(L)_V2.32`). Cross-check: its FlashData must equal the IDB dump's |
| ramdisk | `--ramdisk` | any gzip cpio; `ramdisk-sd/mkramdisk-sd.py --busybox … --waveform …` builds the test one from a static ARM busybox |
| stage2 | `--stage2` | `stage2/build.sh OUTDIR` |

## Build and write a card

Tools: see [Requirements](#requirements).

```sh
stage2/build.sh out/stage2
ramdisk-sd/mkramdisk-sd.py --out out/rd --busybox busybox-armv7 --waveform ebc_waveform.bin
export RK_RC4_KEY=<32 hex digits>
./mkcard.py --out out/card-halt --halt --stage2 out/stage2/stage2.bin --idb idb.bin --kernel Image \
  --waveform ebc_waveform.bin --ramdisk out/rd/ramdisk-sd.cpio.gz
./mkcard.py --out out/card --stage2 out/stage2/stage2.bin --idb idb.bin --kernel Image \
  --waveform ebc_waveform.bin --ramdisk your-ramdisk.cpio.gz [--data-partition --rootfs-img rootfs.ext4]
```

Writing on macOS: `sudo ./write-card.sh diskN out/card [--boot-area | --rootfs | --format-data]`, with the card in a **USB**
reader (the built-in reader timed out on raw I/O). The image size is the manifest's `image_bytes` and must equal the file size;
the sha256 (of the unpatched file) must match the manifest. Before anything is unmounted or written, `diskguard.py` checks the disk from `diskutil info -plist` and
`diskutil list -plist` (parsed with `plistlib`) and refuses:

| Guard | Refuses |
|---|---|
| id | an argument that is not `^disk[0-9]+$` (partitions like `disk7s1`, names, paths), an unknown id, or not a whole disk |
| internal | `Internal` true: the Mac's SSD, and the built-in SD reader |
| bus | `BusProtocol` other than `USB` (built-in reader, disk images) |
| removable | neither `RemovableMedia` nor `Ejectable` |
| bootdisk | the parent whole disk of `/` or the whole disk of any APFS physical store of `/` |
| volumes | a volume mounted at `/`, under `/System` or `/Volumes/Macintosh HD`, or any APFS container or physical store on the disk (erase an APFS-formatted card to FAT first) |
| size | a disk smaller than the image or larger than 32 GiB (`RC2_CARD_MAX_BYTES` raises the cap); with `RC2_CARD_BYTES` set, any other size (`sudo RC2_CARD_BYTES=1977614336 ./write-card.sh …` pins the exact card) |

It prints the disk's media name, size and protocol, asks you to type the disk id back (`--yes` skips only that), checks again and
then writes in 32 KiB blocks and reads back. A disk larger than a full image is fine; the rest of it is not touched. In the data
layout the whole write **erases RC2DATA** (a warning comes before the typed confirmation): it writes [0, end of p1) with the
card's p2 length, the MBR block last (macOS rereads the partition table at once and holds the disk busy), checks the readback
(the image with only MBR bytes 474..477 changed), then formats p2 and runs `fsck_msdos -n`.
`./write-card.sh --check diskN [out/card [mode]]` runs every guard (with a card dir also the image checks), prints the verdict and
exits 0 or 1 without unmounting, writing or reading the raw disk; it needs no sudo.

- `--boot-area` writes the first 64 MiB (new stage2, kernel or ramdisk). `--rootfs` (data layout) writes the first 320 MiB, so p2
  stays. `--format-data` (data layout) only reformats p2 as an empty `RC2DATA`. All three refuse unless the card's partition
  table already equals the image's (`mbrguard.py`); in the data layout p2 is compared by type and start only, and the card keeps
  its p2 length. `--check` with a data-layout card dir also prints the p2 length the whole write would set.
- On Linux: `dd if=sdcard.img of=/dev/sdX bs=32K conv=fsync`, then compare the sha256 of what you read back with the manifest
  (full images; a data-layout card needs the p2 length set and p2 formatted, which `write-card.sh` does on macOS).

First boot: the HALT card. Book off, card in, charger attached, power on. Expect LED 1 to 5, then the HALT pattern.

**Recovery, any time:** pull the card, then press the reset pinhole. The next boot is the eMMC, unchanged. Do not leave the card in
the book: the ROM takes it at every reset. A long press on the power key does not help while stage2 or a kernel spins.

## Safety: the eMMC is never written

- The ROM has no write command for any medium ([`../README.md`](../README.md) §6).
- stage2 accesses no storage controller itself. `tests/check_nowrite.py` scans every 32-bit word, every `movw`/`movt` pair and every
  immediate in `stage2.bin`: none may point into the eMMC, SDIO, NAND, SPI or SD controller. The only ROM routine it references is
  `0x168c`, and there is exactly one indirect call (`rom_call`). Mutation-tested: an eMMC address in the binary fails the check.
- With the ROM dump, `check_nowrite.py` also walks the ROM read closure: it sends only CMD17, CMD18 and CMD12, without the write bit,
  and chooses between SDMMC0 and the eMMC controller only by `IMEM+0x44`, which stage2 checks before the first call.
- In the Unicorn tests the eMMC, SDIO and NAND controllers are traps: any access fails the test. Any SD command outside the ROM's
  read-only set fails it too.
- The stock kernel has no eMMC driver of its own; only the `rk30xxnand_ko` module brings the eMMC up. The test ramdisk never loads
  it ([Ramdisk](#ramdisk)).

## Tests

```sh
tests/run.sh OUTDIR
```

It builds everything twice and compares the bytes, then runs all host tests. No device and no disk is touched. Without inputs it
uses synthetic stand-ins (`tests/fake_inputs.py`: seeded random bytes in the IDB dump format, a filler kernel and waveform) and
skips what needs the real thing, with a `SKIP` line. Environment variables enable more:

| Variable | Enables |
|---|---|
| `RC2_BOOTROM` | the Unicorn tests on your 16 KB BootROM dump (sha256 `18dda933…`; how to read it: [`../README.md`](../README.md) "Method") |
| `RK_RC4_KEY` | with `RC2_BOOTROM`: the full chain ROM → IDB → stage2 (the test checks the key against the ROM's own S-box) |
| `RC2_IDB`, `RC2_KERNEL`, `RC2_WAVEFORM` (+ `RC2_LOADER`) | cards built from your stock files instead of the stand-ins |
| `RC2_BUSYBOX`, `RC2_EBC_CONSOLE` | the real binaries in the test ramdisk |

| Test | Checks |
|---|---|
| reproducibility | `stage2.bin`, `ramdisk-sd.cpio.gz` and `sdcard.img` (both layouts) are byte-identical across two builds |
| `check_nowrite.py` | [Safety](#safety-the-emmc-is-never-written) |
| `test_rom_sd.py` (ROM) | the ROM's SD init (`0x1728`) and reads of 1, 4 and 64 sectors (also through the `0x10100000` alias) against an emulated DesignWare controller and card: SDSC → class 8, byte addresses; SDHC → class 4, sector addresses; the data equals the card; a data CRC error returns 1 and the next read works; only `IMEM+0`, `+0x40`, `+0x44` matter |
| `test_stage2.py` (ROM) | **chain**: the ROM's own SD init and IDB loader read the card image, decrypt the header, load and call FlashData (stubbed after a hash compare), load stage2 to 0x60000000 and jump; stage2 runs to the kernel entry. At the entry: pc, r0–r2, CPSR, SCTLR; kernel, ramdisk and waveform in DDR equal the card; the ATAG list; the log; the first three peripheral writes are the power hold; CPU1 reset; the remap written once and last; only CMD17/18/12; every ROM call went to `0x168c`; progress 1–5. Also: SDHC, transient read errors (retried), and the failure paths (bad magic, bad CRC, blob in partition 1, ramdisk onto stage2, read errors, kernel CRC mismatch, controller id 2, HALT): each stops with the right code and never reaches the kernel |
| `test_card_layout.py` | data layout built twice → identical; MBR entries; manifest hashes recomputed; p1 grown and shrunk to 65536 blocks, `e2fsck -fn` clean, a test file intact; the `fat32.py` p2 by an independent FAT32 reader (`check_fat32.py`), `fsck.fat -n`, mtools round trip; `--data-img` (full image = the data-layout image + that p2); every refusal; `mbrguard.py`; `write-card.sh` refusals before any disk access |
| `test_card_layout.py` (card size) | the data-layout image (320 MiB, p2 placeholder, `format_on_write`) and full images with `--card-bytes` 4 GiB (single; data with a 4 GiB `--data-img`) give a consistent MBR and manifest (`image_bytes`, partitions, MBR table, sha256); `mbrguard.py` p2 length for 2 GB and 32 GiB disks, the patched block (only bytes 474..477 differ), its hash, the readback check, `--p2-any-length`; refused: not a multiple of 32 KiB, above 32 GiB, below the layout minimum, 0, `--card-bytes` with the data layout without `--data-img` |
| `test_format_data.py` | macOS, disk images only (sparse 2 GB and 32 GiB files attached with `diskutil image attach --noMount`; anything diskutil does not report as a disk image is refused): the data-layout whole write as `write-card.sh` runs it (p2 length, `dd`, readback, MBR check), `formatdata.py`, `fsck_msdos -n`, mounts as FAT32 `RC2DATA`, boot sector alignment (2 GB: 16 KiB clusters, 32 GiB: 32 KiB), `fsck.fat -n` on the 2 GB p2; `formatdata.py` refuses a single-layout disk and a partition id |
| `check_write_guard.py` | the disk guards on saved `diskutil` plists (`tests/fixtures/diskutil/`: a Mac's internal SSD and a disk image, trimmed; hand-written USB card readers, the built-in reader, a USB SSD, an APFS card, a USB boot disk, diskutil failures); on macOS `write-card.sh --check` on `disk0`, a bogus id, a partition id and `/` must refuse, with `dd` and every `diskutil` verb except info/list trapped |
| `test_ramdisk_init.sh` | `sh -n`, shellcheck, no storage commands, only proc/sysfs/devtmpfs/tmpfs mounts; with the ROM: the `devmem` log decoder against the emulated log, byte for byte |

## Files

- `stage2/`: bare-metal stage2 (`start.S`, `stage2.c`, `bootinfo.h`, `stage2.ld`, `build.sh`)
- `mkcard.py`: card image builder (MBR, IDB, boot table, blobs, ext4 `rc2root`, optional FAT32 `RC2DATA` entry, manifest)
- `rkidb.py`: IDB helpers (RC4 with a key you supply, stock IDB parts, RKBOOT entries, IDB builder)
- `fat32.py`, `mkdata.sh`: FAT32 geometry for formatting p2 and deterministic FAT32 writer; filled p2 image for `--data-img`
- `write-card.sh`, `mbrguard.py`, `diskguard.py`, `formatdata.py`: card writer for macOS with readback; partition-table guard and
  p2 length at write time; disk guards (external USB card only, `--check`); p2 formatting (`newfs_msdos`)
- `mke2fs.conf`: ext4 settings the 3.0 kernel can mount
- `ramdisk-sd/`: `init` and `mkramdisk-sd.py`, the test ramdisk
- `tests/`: `run.sh`, `fake_inputs.py`, `rc2emu.py` (Unicorn: ROM dump, emulated DesignWare SD controller and card), the tests above, `fixtures/diskutil/` (plists for `check_write_guard.py`)

Not included: the Ghidra and capstone scripts we used to read the stock loader (they only produce listings of vendor code), and
every vendor binary. Code: MIT (`LICENSE`). Text: CC BY 4.0.
