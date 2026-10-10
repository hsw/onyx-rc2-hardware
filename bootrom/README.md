# RK3026 BootROM: boot order and SD boot

What the RK3026 mask ROM does at reset, read from its code: which media it tries and in what order, how it loads the IDBlock from
a microSD card, and what it never does (write storage).

Source: the 16 KB BootROM read from one RC2 (sha256 `18dda9330dd3c74901ccc335a38071f073f4d79897602d645eb359ec55b02d88`; the dump
itself is not published, it is Rockchip code). The ROM is part of the RK3026 SoC, so this applies to every RK3026 device (C67ML,
Monte Cristo, Boyue T61/T62, …), not only the RC2. Marks: [CONFIRMED] = read directly from the ROM
code or data. [STRONG] = follows from the code plus one assumption that is stated. [VERIFY] = needs a hardware test. [DANGER] =
risk to the device.

Addresses are ROM offsets. The ROM runs from the alias at address 0, so its literal pointers (vectors, the media table) are
`0x0000xxxx`. Physical address = `0x10100000` + offset.

## TL;DR

**Q1: boot order.** The ROM tries the media in a fixed order, and nothing reads a strap or GPIO to change it [CONFIRMED]:

1. **microSD (SDMMC0, `0x10214000`)**
2. NAND (`0x10500000`)
3. SPI NOR (SPI0)
4. SPI NAND (SPI0)
5. **eMMC**, read with the JEDEC *boot operation*. While it waits for eMMC boot data, the ROM also listens on UART2 for a download.
   If no eMMC boot data arrives in time, the ROM retries the eMMC controller once with the SD protocol.
6. USB OTG download (MaskROM, 2207:292c) together with UART2. This loops forever.

**SD is tried before eMMC, on every reset.** A card with a valid IDBlock therefore wins over an intact eMMC loader. The often-quoted
order SD → eMMC → NAND → USB is not right for this ROM: NAND and SPI come before eMMC.

**Q5: fallback.** If the card is missing, does not answer the SD init, or holds no IDBlock with a valid header in any of its 5
copies, the ROM moves on and boots the eMMC as usual [CONFIRMED]. So pulling the card, or erasing its IDBlock on another computer,
is a safe recovery. If the card's IDBlock is accepted and its code then hangs, nothing rescues it. The ROM never arms the watchdog
and never returns to the next medium on its own. You have to reset (pinhole or power) **with the card removed** [STRONG].

**Q6: writes.** The ROM never writes to SD, eMMC, NAND or SPI. It contains no write or erase command [CONFIRMED].

**Prerequisite that only hardware can check:** whether the card has power at ROM time. The SD rail is ACT8931 LDO3, and the ROM
does not touch the PMIC. On the C67ML sibling an SD card boots (reported by another developer), which suggests LDO3 is on at power-up there [VERIFY on the RC2].

## 1. Boot-media order (Q1)

### Control flow [CONFIRMED]

| Offset | What |
|---|---|
| `0x000` | Vector table, `ldr pc,[pc,#…]`. Undefined/SWI/prefetch/FIQ → `b .`. Data abort → `subs pc,lr,#4`, which skips the faulting instruction. IRQ → `0x038` → `0x2230` (USB). Extra entry `0x020` → `0x29d0`, the download loop; loaded code can jump there. |
| `0x058` | Reset. A secondary CPU (MPIDR≠0) waits until IMEM `0x10080004` == `0xDEADBEAF`, then jumps to `[0x10080008]`. CPU0 places its stacks at IMEM `0x100802b8…0x10080768`, then `ldr pc,=0x450`. No code is copied to SRAM. The ROM executes in place; only the RC4 S-box is copied. |
| `0x450` | `main`: delay factor `IMEM+0 = 24` (24 MHz OSC), CRU setup `0x678`, secure flag `0x368` → `IMEM+0xc`. If secure: PLL setup `0x6a4`. Then `0x1bb0` (media loop) and `0x29d0` (eMMC boot op + download). It never returns: `b .`. |
| `0x1bb0` | `for i in 0..3: mode = table[i].init(); load_idb(i, mode)`. Every medium is tried unconditionally. `load_idb` returns only on failure. |
| `0x29d0` | `table[4].init()` (eMMC boot op), UART2 init, then poll `0x0ff0`. Boot data started → `load_idb(4, 0)`. Timeout → `0x1730` (eMMC controller in SD mode) → `load_idb(0, 0)`. After that, or on an error: PLL `0x6a4`, USB OTG init `0x1c10`, and an endless UART2/USB download loop. |

The media table at `0x2f48` has 5 entries × `{init, read(sector, buf, bytes), read_header(sector, buf), copy→sector(k), copies}`
[CONFIRMED]:

| # | Medium | init | read | hdr | copy k → start | copies |
|---|---|---|---|---|---|---|
| 0 | SDMMC0 (SD card). Also the eMMC controller in SD mode, when IMEM `+0x44` = 2 | `0x1728` → `0x15ac(0)` | `0x168c` | `0x1714` | `0x171c`: `64 + 1024·k` (sectors) | 5 |
| 1 | NAND | `0x0aa4` | `0x0c44` (BCH16, then BCH24) / `0x0e00` (no ECC, CRC16) | `0x0d9c` | `0x0df0`: `k · pages_per_block` | 50 |
| 2 | SPI NOR | `0x07d8` | `0x086c` (cmd `03`) | `0x0978` | `0x0a0c`: `0, 4, 8, 16, …` units | 13 |
| 3 | SPI NAND | `0x0830` (`FF` reset) | `0x086c` (cmds `13`, `0F/C0`, `03`) | `0x0978` | `0x0a0c` | 13 |
| 4 | eMMC boot operation | `0x0f44` | `0x1068` (FIFO stream) | `0x1128` | `0x1130`: always 0 | 1 |

### No strap, GPIO or boot-mode flag selects the order [CONFIRMED]

- Every GRF access in the ROM is an iomux **write**. The ROM never reads a GRF or PMU register that a loader could use as a
  "reboot to MaskROM" flag. The only IMEM values it reads are ones it wrote itself.
- The ROM reads exactly one GPIO: GPIO3_A4 (`GPIO3+0x50` bit 4, `0x368`). It is half of the secure-boot gate, together with an efuse
  word (§3.5). It changes clocks and signature checks, not the order.
- `0x20080040` in the USB code is a USB register value that happens to equal a GPIO1 address, not a GPIO access.

### When a medium counts as "failed" [CONFIRMED]

- **init fails**, so the medium is skipped:
  - SD: no response to CMD55/ACMD41, ACMD41 not ready after 2040 polls, or an error in CMD2/3/7/16/ACMD42. Result `0xfe`.
  - NAND: READ ID returns `00`, `FF`, `0F` or `F0`. Result `0xff`.
  - SPI: init itself always succeeds; a missing chip fails at the header step.
- **per copy** (`0x1820`), the ROM goes to the next copy when:
  - the sector read fails;
  - the first raw word ≠ `0xFCDC8C3B` (RC4 of `0x0FF0AA55`);
  - a payload read fails;
  - the decrypted init stage does not start with `"RK30"`;
  - the init stage returns non-zero;
  - (secure only) the hash or RSA check fails.
- After the last copy of the last mode, the ROM moves to the next medium.
- In non-secure mode there is **no checksum** on the header or the payload. The CRC16/CRC32 words in IDB sectors 1–3 are never
  read; the ROM reads only sector 0 and then the payload. The one exception is NAND without ECC, which checks a CRC16 per
  sector against the spare bytes.

### The NAND "mode" loop (`0x184c`)

`init` returns a mode. For NAND, modes 1/2/3/7 select the page/block geometry (`IMEM+0x2c` = 0x800, 0x20 or 0x100) and ECC. All
copies are retried for each mode. Mode 0 on SD, SPI or eMMC means "one pass".

## 2. The SD path (Q2)

### Controller and pins [CONFIRMED]

- Controller: SDMMC0 at `0x10214000` (DesignWare MMC).
- Clock: CRU `+0x70` (CLKSEL11) = `0x007F0040`, i.e. MMC0 from GPLL with div 1. In the secure case it is `…43`, div 4.
- iomux, matching the RC2 board file:
  - GRF `+0xbc` = `0x50005000`: GPIO1_B6 MMC0_PWREN, GPIO1_B7 MMC0_CMD.
  - GRF `+0xc0` = `0x05510551`: GPIO1_C0 CLKOUT, C2–C5 D0–D3.
- **Card detect GPIO1_C1 is not muxed and not read.** A card counts as present only if it answers commands.
- PWREN register = 0.
- No PMIC access. LDO3 must already be on [VERIFY].

### Init sequence (`0x15ac` → `0x1388`) [CONFIRMED]

1. Controller reset (CTRL=3). CLKDIV=0x1e (div 60) and update-clock.
   - With the PLLs still in their reset bypass (24 MHz), that is **400 kHz** [STRONG].
2. CMD0 (`0x8100`, with the 80-clock init sequence).
3. CMD8, arg `0x1AA`:
   - answered → ACMD41 argument `0x40FF8000` (HCS set);
   - response timeout → `0x00FF8000` (SD v1);
   - any other error → fail.
4. Up to 2040 × (CMD55 + ACMD41), with no delay between tries, until OCR bit 31 (ready) is set. Then the card is classified
   (`IMEM+0x40`):
   - CMD8 timed out → `0x10` (v1, byte addressing);
   - OCR == `0xC0FF8000` or `0xC0FF8080` → `0x04` (**block addressing**);
   - OCR == `0x80FF8000` or `0x80FF8080` → `0x08` (SDSC v2, byte addressing);
   - **anything else → `0x00`, byte addressing.**
5. CMD2, CMD3 (RCA → `IMEM+0x46`). CLKDIV=1, which gives **12 MHz** [STRONG]. CMD7 (select), CMD16 (blocklen 512).
6. ACMD42 arg 0: disconnect the DAT3 pull-up. Volatile, card state only.
7. ACMD6 arg 2, and CTYPE=1 on success: **4-bit bus**. If ACMD6 fails, the ROM stays 1-bit and carries on.
8. Read: `0x168c`.
   - The address is `sector << 9` unless `IMEM+0x40 & 0x84` is set, in which case it is `sector`.
   - One sector → CMD17. More → CMD18 + CMD12.
   - Payload reads are always 0x800 bytes (4 sectors).

### The "OCR bug" [CONFIRMED in code. Which cards trigger it: STRONG]

The ROM chooses block addressing only for two exact OCR values, `0xC0FF8000` and `0xC0FF8080`. CCS (bit 30) alone is not enough. An
SDHC/SDXC card whose ready OCR differs in any other bit is treated as a byte-addressed card. Examples: bit 29 (UHS-II status), bit
24 (S18A, which some cards report although the ROM never asks for 1.8 V), or a narrower voltage window. The card then interprets
`sector·512` as a **block number**, so ROM sector *s* is read from card block *512·s*.

A card layout that adds a second loader copy for the OCR bug (header at card block 32768, payload at 34816), checked against the
code:

- Header copy 0: sector 64 → card block **32768** = 64·512. Matches.
- Payload: it starts at `64 + init_offset` = 68 → block **34816** = 68·512. Matches for the **first 2 KB only**.
  - The ROM reads the payload in 4-sector chunks at sectors `68 + 4n`. These land at card blocks `(68+4n)·512 = 34816 + 2048·n`.
  - A payload written contiguously from 34816 is therefore correct only for chunk 0.
  - If the init stage is larger than 2 KB (`init_size` > 4), or the ROM also loads a boot part, then chunk *n* must sit at block
    `34816 + 2048·n`.
- Header copies 1–4 for such a card would sit at blocks `32768 + 524288·k`.

## 3. IDBlock handling (Q3) [CONFIRMED unless marked]

1. **Probe:** the start sector of copy *k* comes from the table. On SD that is 64, 1088, 2112, 3136 and 4160, with 5 copies. For
   each copy the ROM reads 1 sector and compares the raw first word with `0xFCDC8C3B`. **The header must be RC4-encrypted.** A
   plaintext `55 AA F0 0F` is rejected.
2. **Decryption:** `0x5a8` is RC4.
   - The state is not built from the key at run time. The 256-byte S-box at `0x2e34` is copied to IMEM `0x10080064` for every
     call. The S-box is the key schedule of the standard Rockchip IDBlock key, the one Rockchip's own tools use (checked
     byte for byte).
   - Every 512-byte sector is decrypted from a fresh state: the header once, then each of the 4 sectors of every chunk.
3. **Header fields used:** `+0x0c` init_offset (u16, not range-checked), `+0x1fa` init_size, `+0x1fc` init_boot_size (sectors,
   counted from init_offset).
   - Sanitising: if init_boot_size ∉ [5, 0x7fff], it is replaced by 10. If init_size ∉ [4, 64], or is not a multiple of 4, or
     exceeds init_boot_size, it is replaced by 4.
   - **`+0x08` (disable_rc4) is never read. The payload is always RC4-decrypted.** A mainline U-Boot `rksd` image built the
     rk3036 way (`spl_rc4 = false`) will not run on RK3026 unless its payload is encrypted. Working SD cards for RK3026 must
     therefore carry an encrypted payload [STRONG].
4. **Load:**
   - Chunks of 2 KB are read from `base + init_offset + 4n` and decrypted.
   - The **init stage** (init_size sectors) goes to **SRAM `0x10080800`**.
   - Its first word must be `"RK30"` (`0x2e2c`). The ROM then calls it with `blx 0x10080804`, in ARM state.
   - The stock DDR init `3028A_DDR3_NEW_300M` starts with `"RK30"` + `ldr r0,=0x10080811; bx r0` and ends `movs r0,#0; pop {…,pc}`.
     This confirms the load address and the return-to-ROM convention.
5. **Back to the ROM:** the init stage must **return 0**. The ROM then loads the remaining `init_boot_size − init_size` sectors in
   2 KB chunks to **DDR `0x60000000`** and jumps there (`blx`, no return expected). This is the Rockchip "back to bootrom".
   - Stock RC2 IDB (eMMC boot area): init_offset 4, init_size 8 (4 KB DDR init), init_boot_size 232 (8 + 224 sectors of
     FlashBoot, 114 688 B).
   - Hook [STRONG on purpose, unused by stock]: the init stage may write a sector offset to IMEM `0x10080030`. The ROM then reads
     the boot part from `base + init_offset + value`; `0xFFFFFFFF` aborts.
6. **Size limits:**
   - The ROM allows up to 64 init sectors (32 KB).
   - The SRAM behind `0x10080800` is smaller. The 3.0 kernel maps IMEM as 8 KB, which would leave about 6 KB for the init stage.
     The exact RK3026 SRAM size is [VERIFY].
   - The stock init stage is 4 KB.
7. **Checks:** in non-secure mode there is no checksum, size check or signature on the payload: only the header magic and `"RK30"`.
8. **`"RK30RSAK"` (`0x2e2c`)** is two adjacent 4-byte magics:
   - `"RK30"`: the init-stage tag above.
   - `"RSAK"` (`0x2e30`): the tag of an RSA key block that may occupy the first chunk of the init area. In non-secure mode a chunk
     starting with `"RSAK"` is skipped.
   - **Secure boot** (`IMEM+0xc` ≠ 0) needs **GPIO3_A4 high and efuse word (macro 0, bytes 0x1c–0x1f) == `0xEFFE1001`** (`0x368`).
     In secure mode [STRONG on the details]:
     - The first chunk is the key block. SHA-256 (crypto block at `0x10200000`) of the 512 bytes at block+`[0xc]` must equal the
       32-byte efuse hash (macro 1, `0x3a4`).
     - The init stage is verified with RSA-2048: operands are copied to crypto `+0x500/+0x600/+0x700` (`0x2e8`).
     - The signature for the boot part is kept at IMEM `0x10080164` and checked after loading (`0x3fc`).
   - **It is not enforced on the RC2** [STRONG]: the stock IDB has no `"RSAK"` block and the RKBOOT sign flag is 0, yet it boots.
     Secure mode would reject it.

## 4. eMMC, NAND and SPI for comparison (Q4)

### eMMC (`0x1021c000`)

The eMMC shares pins with NAND: GPIO1_C6/C7 CMD/RSTN, GPIO1_D0–D7 data, GPIO2_A5 PWREN, GPIO2_A7 CLK.

**Primary path, the boot operation** (`0x0f44`) [CONFIRMED encoding]:

- CMD register `0x81002200` = start | **enable_boot** | wait_prvdata | data_expected, with boot_mode = 0. This is the mandatory boot
  mode: CMD held low, no boot ack.
- BYTCNT is 16 MB. Bus 1-bit (CTYPE untouched).
- Clock: CRU CLKSEL12 div 64 and CLKDIV 0. That is about **375 kHz** with the PLLs in bypass [STRONG].
- `0x0ff0` polls RINTSTS:
  - bit 9 (boot data start) → stream;
  - error bits `0xA0CE` → give up;
  - after 0x903 polls → timeout.
- **One copy only, at sector 0 of the boot stream.** The stream is read forward through the FIFO.

**Fallback:** only on timeout, `0x1730` runs the SD-protocol init on the eMMC controller (4-bit) with table entry 0: sectors
`64 + 1024k`, 5 copies. Its sequence (CMD8 / CMD55 + ACMD41, no CMD1) cannot initialise a real eMMC. It exists for SD-protocol
parts on that controller [STRONG].

**So the RC2 eMMC boots through the boot operation** [STRONG]. The IDB that the ROM reads therefore starts at sector 0 of the eMMC
boot area, most likely boot partition 1. Evidence:

- the device boots, and the boot operation is the only ROM path a real eMMC can pass;
- `rkflashtool` (Rockusb `i 0 0x1000`) returns a 2 MiB "IDB area" (a typical boot-partition size) with copy 0 at sector 0 and copies at
  1024/2048/3072;
- logical LBA 0 holds `parameter`, not an IDB (no magic in 0..0x2000);
- loader 2.32 has EXT_CSD helpers for `PARTITION_CONFIG` (179, it sets BOOT_PARTITION_ENABLE=1 if it reads 0) and
  `BOOT_BUS_WIDTH` (177).

Which boot partition is used, and the exact EXT_CSD values, are [VERIFY]. Read EXT_CSD from a Linux with the mmc subsystem; the stock
kernel uses rk30xxnand.

[DANGER] Never change EXT_CSD 177/179 or the boot partition from a custom kernel. That is the only eMMC boot path, and losing it leaves
only USB MaskROM.

### NAND (`0x10500000`)

- Probe: reset `FF`, READ ID `90`. The maker/device byte is looked up in a 20-byte table at `0x2f34`.
- Reads: `00/30` with BCH16, then BCH24, or `00` without ECC plus CRC16. No program/erase opcodes.
- 50 copies, one per block.
- On the RC2 the NAND probe drives the shared eMMC pins and reads ID `00/FF`, so NAND is skipped. It is harmless: the RC2 boots
  through it every time [STRONG].

### SPI (SPI0, GPIO1_B0–B3, mux GRF `+0xbc` = `0x00FF0055`)

- NOR: `03` read with a 24-bit address of `unit << 10`. That is 2 KB of data per 4 KB of flash, the `rkspi` layout [STRONG].
- SPI NAND: `13` page read, `0F C0` status poll, `03` cache read.
- The header is searched in the first 32 bytes at an offset of up to 0x1c.
- On the RC2, SPI0 goes to the panel's MX25U only while GPIO2_B2 `spi_ctl` is high. The ROM never drives it, so this probe
  finds nothing [STRONG]. Even with the gate open, the panel flash holds no IDB magic.

## 5. Fallback and hangs (Q5)

**Card absent, blank, or with a bad IDB**

- Absent: SD init fails on CMD55/ACMD41 within milliseconds.
- Blank or no magic: 5 header reads fail.
- Bad payload: no `"RK30"`, or the init stage returns non-zero.

In every case the ROM continues with NAND → SPI → eMMC and boots the internal loader unchanged [CONFIRMED]. A card with a valid
IDBlock wins at **every** reset until it is removed or its header is destroyed.

**Accepted IDB, then a hang**

- If the init stage never returns, or the stage at `0x60000000` hangs, the ROM is gone. The watchdog (`0x2004c000`) is never
  referenced, and the DW watchdog is disabled after reset [STRONG].
- The device stays hung until reset or power-off. Then **pull the card**, and the next reset boots the eMMC.
- The RC2 has a reset pinhole. Whether the board stays powered while hung, with power hold GPIO1_A2 not driven, is [VERIFY]
  (harmless either way).

**Init stage returns non-zero.** The ROM tries the next copy, then the next medium. eMMC boots normally [CONFIRMED].

**eMMC boot fails as well.** Download mode: UART2 (115200 8N1 on GPIO2_C6/C7, the EBC_BORDER pins on RK3026) plus USB OTG MaskROM
(VID 2207 PID 292c, bcdDevice 0x0100, descriptor at `0x2fac`).

- Vendor request `0x0c`: wIndex `0x471` loads to SRAM `0x10080800`, `0x472` to DDR `0x60000000`. The image must start with
  `"RK30"`, and the ROM jumps to +4.
- While it waits for eMMC boot data, the ROM also sends `D2 "RK292C" D2` on UART2 about every 50 ms [STRONG].

## 6. Writes (Q6) [CONFIRMED]

Complete list of commands the ROM can issue:

- **MMC:** CMD0, 2, 3, 7, 8, 12, 16, 17, 18, 55, ACMD6/41/42, and the boot operation. The data-direction bit (`0x400`) is never set,
  and there is no CMD24/25/32/33/38.
- **NAND:** `FF 90 00 30` only.
- **SPI:** `FF 13 0F 03` only.

ACMD42 and ACMD6 change only volatile card state. **The ROM never writes any storage.** Download mode writes only to SRAM/DDR.

## 7. Hardware-only questions and a safe test

**Still [VERIFY]:**

1. Is SD LDO3 on at power-up, and do the card's pull-ups work before the kernel sets them? If not, the ROM never sees a card on
   the RC2, whatever the code does.
2. Does a given card report one of the two "good" OCR values (block addressing) or hit the OCR bug?
3. The ACMD41 budget is 2040 polls with no delay. A slow card might time out; the expected cost is about 1 s, not measured.
4. Which eMMC boot partition and EXT_CSD values are used.
5. The SRAM size behind `0x10080800`.
6. Power behaviour while hung.

**Safest test** (no flashing, no writes to the book):

1. Build a **spin-forever IDBlock**:
   - Header sector: magic `0x0FF0AA55`, init_offset 4, init_size 4, init_boot_size 8, RC4-encrypted.
   - 4 payload sectors: `"RK30"` + `0xEAFFFFFE` (`b .`), each sector RC4-encrypted.
2. Card A: the IDBlock only at LBA 64.
3. Boot with card A, ideally on the charger, and watch USB for 2207:292c.
   - **Hang** (no boot animation, no USB) = the ROM took the SD with block addressing.
   - **Normal boot** = SD not seen (power or OCR) or fell through.
4. Card B: the same IDBlock only at the OCR-bug location (header block 32768, payload block 34816; one chunk is enough because the
   init stage is 4 sectors). A hang on B and not on A proves the OCR bug for that card.
5. Exit after a hang: pull the card, then the reset pinhole.

The payload is 8 bytes that can be audited by eye. The ROM writes nothing, and the eMMC is never touched before the hang.

A follow-up, only after A or B works: stock DDR init + stock `rk30usbplug` as the boot part. The book should then enumerate as
Rockusb without loading Android. Do not run write tools against it.

## Method

### Dump

- Read on the running stock 3.0.36+ kernel as root with [`rc2peek`](../panel-flash/tools/rc2peek.c) in mmap mode: mmap of
  `/dev/mem` at `0x10100000`, 16 KB (`rc2peek mmap 10100000 4000`). `pread` on `/dev/mem` refuses addresses below RAM on this
  kernel. The vendor kernel itself reads the ROM at run time (`RK30_ROM_BASE`), so the window is mapped and safe to read.
- Two reads were byte-identical (sha256 above).
- [DANGER] A 64 KB read from `0x10100000` ran past the ROM and hung the bus; the device needed the reset pinhole. Read 16 KB only.

### The dump is complete [STRONG]

- Code and data end at `0x2fe8`. The rest is zero, except the version at `0x3ff0`: `C29231029250101V`. Read per 4-byte word,
  that is `292C 2013 0529 V101`, the same date and V101 that rkflashtool reports.
- No code references anything at or above `0x3000`.
- All code is ARM, except a Thumb-2 `memcmp` at `0x2cac`. `memcpy` is at `0x2d00`.

### Tools

- GNU objdump; Python 3 with capstone.
- Register map from [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources)
  `arch/arm/mach-rk2928/include/mach/io.h` and `mach-rk3026/include/mach/iomux.h` (pin functions); CRU clock selects from
  `mach-rk3026/clock_data.c`.
- Cross-checks against the stock RC2 loader (`RK3026Loader(L)_V2.32`, RKBOOT entries decrypted per 512 B with the same key), the
  stock IDB headers, and the IDB sector-0 layout in [rkdeveloptool](https://github.com/rockchip-linux/rkdeveloptool) (`RK28_IDB_SEC0`).
- [`tools/romdis.py`](tools/romdis.py) (MIT): capstone ARM at VMA 0 with `skipdata`; every `bl` target becomes a `sub_xxxx` header
  with its callers; every `ldr rX,[pc,#…]` is annotated with the pool value, and with `PERIPH+off` when the value falls in a 16 KB
  window of a known peripheral.

```sh
objdump -b binary -m arm -D --adjust-vma=0x10100000 rom.bin > rom-arm.lst
python3 tools/romdis.py rom.bin > rom-annot.lst
```

The RC4 S-box at `0x2e34` was compared byte for byte with the key schedule of the standard Rockchip IDBlock key; they match.

### IMEM map used by the ROM [CONFIRMED]

| Address | Contents |
|---|---|
| `+0x000` | delay factor: 24, or `0xC0` after the PLL is set up |
| `+0x004`, `+0x008` | CPU1 mailbox |
| `+0x00c` | secure flag |
| `+0x014`–`0x018` | SPI type and offset |
| `+0x01c`–`0x02c` | NAND parameters |
| `+0x030` | boot-part sector hook |
| `+0x034`–`0x03c` | eMMC boot-op stream state |
| `+0x040` | SD class |
| `+0x044` | controller id |
| `+0x046` | RCA |
| `+0x050` | USB state |
| `+0x064` | RC4 S-box |
| `+0x164` | saved signature |
| `+0x2b8`–`+0x767` | stacks |
| `+0x800` | init-stage load address |
