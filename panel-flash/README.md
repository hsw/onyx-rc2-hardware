# Panel SPI flash

The ED060KD1 panel module of the RC2 carries a small SPI NOR flash. It holds the panel's identity, its VCOM and the waveform made
for this panel. The stock kernel reads only the identity strings from it. For the display it uses the waveform file from the boot
ramdisk instead.

Everything here comes from one device (pcb V1.73) on the stock 3.0.36+ kernel. The flash was only read, never written. Confidence
marks are as in the [top README](../README.md#confidence-marks).

## Chip and wiring

| | |
|---|---|
| Chip | Macronix **MX25U** series, JEDEC ID `c2 25 33`, **512 KiB**, 1.8 V part [CONFIRMED: JEDEC read on the device; size from the address wrap below] |
| Bus | SPI0, chip select 0, 6 MHz in the stock board data (`epd_spi_flash`) [CONFIRMED] |
| Pins | SPI0 CLK/TXD/RXD/CS0 on GPIO1_B0..B3, muxed to SPI only while the flash is read [CONFIRMED] |
| Enable | GPIO2_B2 (the EBC_SDOE pin, reused) driven **high** during the access [CONFIRMED: dmesg `spi_ctl_pins_enable: enable =1/0`] |
| Shared lines | GPIO1_B0 is the magnet-sensor IRQ, GPIO1_B1 the CW2015 ALRT, GPIO1_B2 a charge-current select, GPIO1_B3 the RTC IRQ. The stock code masks the fuel-gauge IRQ for the duration of the read [CONFIRMED] |
| VCCIO | pcb 0 (V1.4/V1.6) lowers VCCIO to 1.8 V during the read; V1.73 keeps 3.3 V [STRONG] |

The sequence is `spi_ctl_pins_enable()` in [`../board/README.md`](../board/README.md) §6; the SPI device is in §3. For a
mainline device tree, use a `jedec,spi-nor` node on spi0 with two pinctrl states: GPIO by default, SPI only while the flash is read.
A permanent SPI mux would take the four interrupt lines away.

Reading past 512 KiB wraps around: a 1 MiB read returns the same 512 KiB twice.

## Layout

| Offset | Size | Content | |
|---|---|---|---|
| 0x000000 | 0x669 | Unknown block of 16-bit words (`0000 a000 ff03 0060 0160 …`). It looks like a command or register table. No stock code reads it | [VERIFY] |
| 0x000669 | | zeros | |
| 0x000886 | 287 192 B | **Complete E Ink WBF waveform `320_R177_AE6A41_ED060KD1U7_TC`**. Its whole-file CRC-32 checks out | [CONFIRMED] |
| 0x046a5e | | zeros up to 0x070000 | |
| 0x070000 | 0x310 | **Panel passport**, encoded as described below | [CONFIRMED] |
| rest | | 0xFF (erased) | |

### Passport (0x70000)

Each field sits in a 16-byte-aligned slot and is padded with 0xFF.

| Offset | Value on this unit | Read by the stock kernel as |
|---|---|---|
| 0x70000 | `ED060KD1U7` | part number, `/proc/panel_info` |
| 0x70010 | `-2.06` | VCOM in volts, used by the VCOM auto-fix |
| 0x70020 | `320_R177_AE6A41_ED060KD1U7_TC` | waveform version, `/proc/panel_info` |
| 0x70040 | `R177` | not read |
| 0x70050 | 33-character panel barcode starting with `ENT` (withheld: it is a serial number) | barcode, `/proc/panel_info` |
| 0x70080 | `1448x1072` | not read |
| 0x70090 | `122.356mmX90.584mm` (active area) | not read |
| 0x700b0 | `1.8` (meaning unknown; perhaps the flash's 1.8 V interface) | not read [VERIFY] |
| 0x70300 | `Ver_1.0` (passport format version) | not read |

Character encoding (stock `panel_data_translate`) [CONFIRMED]:

| Byte | Character |
|---|---|
| 0–9 | `0`–`9` |
| 10 | `_` |
| 11 | `.` |
| 12 | `-` |
| 0xCB–0xE4 | `a`–`z` |
| 0xE5–0xFE | `A`–`Z` |
| 0xFF | empty (end of field) |

## What the stock kernel does with it

- **At probe** it reads the passport strings and prints them in dmesg. They are shown in `/proc/panel_info` (part number, VCOM,
  waveform version, barcode, waveform MD5).
- **VCOM auto-fix.** If the TPS65185 VCOM EEPROM holds a factory default (1.25 or 1.80 V), the kernel programs it to panel VCOM
  − 0.40 V once. See [TPS65185 and VCOM](../README.md#tps65185-and-vcom). On this unit the PMIC holds 1.66 V = 2.06 − 0.40.
- **The waveform in the flash is not used for display.** The EBC driver loads `/ebc_waveform.bin` from the boot ramdisk
  (`320_R110_AE4D21_ED060KD1C2_TC`, a different panel lot). The physical memory at `waveform_addr` (0x7ff00000) holds that ramdisk
  file byte for byte, not the flash content [CONFIRMED]. Stock ships it that way.
- `/dev/spi_flash` (chrdev 250:0, mode 0600) has a `read()` that loads 0x40000 bytes from flash offset 0x886 into a kmalloc buffer
  and logs `WAVEFORM CHECKSUM`. It then returns the buffer's **kernel address as the byte count** and never frees the buffer. Only
  the first 256 KiB of the 287 KiB waveform are read this way [CONFIRMED].
- `/proc/panel_info` (mode 0444) prints the passport lines and then **stale kernel memory**: any app can read it. Stock bug,
  [CONFIRMED].

## R177 (panel flash) against R110 (ramdisk)

Both are WBF mode_version 0x19, 8 modes, 14 temperature ranges over 0–48 °C with the same bounds, and 5 bits per level. The frame
counts are almost the same: only INIT and one or two DU cells differ. The transition tables themselves differ. Below is the share of
differing 32×32 cells over all frames, in %, by temperature range 0…13:

```
INIT    1  2  2  7  3  7  8 38 43  0  0  0  0  0
DU      0  0  0  2  0  0  0  4  0  0  0  0  0  0
GC16    6  8  7  9  8  8  8  8  9 10 10 11  8 11
GL16    7  8  7  9  8  7  8  8  9 10 10 11  8 11   (GLR16 and GLD16 are the same tables as GL16 in both files)
A2      0  …  0   (< 1 %)
DU4     1  …  1
```

The grey modes of R177 are tuned differently (6–11 % of cells), while A2 and DU are nearly the same. Whether R177 looks better on
this panel (ghosting, even grey steps) has not been tested [VERIFY]. The decoder used is in
[onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform).

The flash dump and the R177 file are not published: they are vendor data from one panel.

## Reading it yourself

The tools in [`tools/`](tools/) need root and the stock kernel. They only read.

- [`tools/rc2spidump.c`](tools/rc2spidump.c) (GPL-2.0, kernel module; build with [`tools/Kbuild`](tools/Kbuild)). It borrows the
  stock `spi_device` from `spi_flash_info` and checks that it is `spi0.0` / `epd_spi_flash`. Then it calls
  `spi_ctl_pins_enable(1)`, sends JEDEC 0x9F and READ 0x03 in 16-byte transfers (as the stock `SPIFlashRead` does), and calls
  `spi_ctl_pins_enable(0)`. The data stays in a page block until `rmmod`; dmesg prints its physical address. 512 KiB take about
  2.5 s.
  - The `devp` default (0xc0d2aba8) is for the 2017-11-07 kernel. Take `spi_flash_info` + 8 from your kernel's kallsyms: data
    addresses differ in the 2019 kernel.
  - Build against [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources) with `rk3026_epd_defconfig`,
    `arm-eabi-4.6` and `LOCALVERSION=+`. This gives vermagic `3.0.36+ SMP preempt mod_unload ARMv7`; MODVERSIONS is off in stock.
    Before `insmod`, check that the `.gnu.linkonce.this_module` layout matches a stock module.
- [`tools/rc2peek.c`](tools/rc2peek.c) (MIT, static ARM binary; musl works, a static glibc does not on a 3.0 kernel).
  - `dump` copies physical memory through `pread` on `/dev/mem`.
  - `mmap` reads I/O and ROM below RAM, where `pread` is refused. Read only inside a region you know is decoded: a read past the
    end of the 16 KiB BootROM hung the device.
