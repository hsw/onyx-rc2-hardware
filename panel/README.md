# Panel timings and power

What the RC2's 6" 1448×1072 E Ink panel (ED060KD1, see [`../panel-flash/README.md`](../panel-flash/README.md)) gets from the
stock kernel, compared with two public references: Amazon's GPL kernel for the **Kindle Paperwhite 3**, which drives 1448×1072
Carta panels of the same size, and TI's public **TPS65185 datasheet (SLVSAQ8)**. Written for a mainline device tree; the stock
register values themselves are in the [top README](../README.md#panel-timings) and [`../pmic/README.md`](../pmic/README.md) §2.

Sources:
- **Kindle** = Amazon, Kindle Paperwhite 3 (7th generation) GPL source, release 5.16.2.1.1
  (`Kindle_src_5.16.2.1.1_4097470002.tar.gz` from the "Kindle Source Code Notice" page), kernel `linux-3.0.35`:
  `arch/arm/mach-mx6/board-mx6sl_wario.c`, `arch/arm/mach-mx6/mx6_wario_gpio.c`, `drivers/video/mxc/mxc_epdc_fb.c`,
  `drivers/video/mxc/mxc_epdc_fb_lab126.c`, `drivers/regulator/max77696-epd.c` (GPL-2.0 / GPL-2.0+). Facts only; no code copied.
- **TI** = TPS65185 datasheet, SLVSAQ8 (public on ti.com).
- **E Ink kit manual** = E Ink's user manual for its 6" ePaper display kit (ED060KC1), public on E Ink's web shop: definitions
  of the update modes.
- **WBF** = the RC2 waveform files, decoded with [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform).

No E Ink panel specification is used here: the ED060KD1's own specification is not public.

Marks: **[CONFIRMED-src]** = read in one of the sources above; **[CONFIRMED-device]** = read or measured on the RC2;
**[STRONG]**, **[VERIFY]**, **[GUESS]** as in the [top README](../README.md#confidence-marks).

## Summary

- **The waveform wants 85 Hz; stock runs 83.64 Hz.** Kindle's mode for 1448×1072 Carta panels (`ED060TC1-3CE`) is
  13/8/362/52 at 40 MHz = 435 clocks per line, **84.99 Hz**; stock RC2 uses 17/8/362/55 = 442 clocks, 83.64 Hz. The vertical
  timing and the gate clock (281) are the same in both. Trying 13/8/362/52 on the RC2 is open [VERIFY on the panel].
- **VGH must be 25 V.** Every voltage-control block in both RC2 waveform files asks for VGH +25 V (and VPOS/VNEG ±15 V, VGL
  −20 V); Kindle also sets 25 V for all its 1448×1072 Carta panels. The TPS65185 makes VDDH with an external divider (22, 25 or
  28 V options); which one the RC2 board has is unknown [VERIFY by board].
- **Logic level:** Kindle runs the EPDC signals of these panels at **1.8 V**, and the panel passport says VDD 1.8; the RC2's
  "EBC/panel logic" rail is ACT8931 LDO4 at 3.1 V. Either the board has a level shifter or a separate 1.8 V supply, or stock
  drives the panel logic at 3.1 V [VERIFY by board; matters for the DTS].
- **VCOM:** Kindle writes the passport value as is (2.06 V for `-2.06`) at every power-up; stock ONYX programs passport −
  0.40 V (1.66 V) into the PMIC EEPROM once. Why ONYX subtracts 0.40 V is unknown.
- **TPS65185 sequence (stock):** up VDDH (VGH) → VNEG → VEE (VGL) → VPOS with 6/3/6/3 ms; down all rails at once. Mainline
  writes no sequence, so after a WAKEUP reset the chip would use TI's defaults instead. Which order this panel needs is not
  public [VERIFY].
- **Physical size for the DT:** `width-mm`/`height-mm` = **122 / 91** for the 1448×1072 scan (passport active area 122.356 ×
  90.584 mm; Kindle uses 122 × 91 too).

## 1. Timings

The stock values come from the 72-byte panel table of the stock EBC driver ([top README](../README.md#panel-timings)). Below
they are written in the property names of Rockchip's later `ebc-dev` device-tree binding (`panel,lsl`, `panel,lbl`, …), in SDCLK
cycles; stock's `hsync`/`hstart`/`hend` map to LSL/LBL/LEL and `vsync`/`vstart`/`vend` to FSL/FBL/FEL [STRONG].

Kindle's i.MX EPDC modes give `pixclock` as the EPDC clock with 2 pixels per clock on an 8-bit bus (the EPDC's
`PIXELS_PER_SDCLK_4` setting with this bus width). With that reading every Kindle panel mode comes out at 85 Hz (1024×758: 85.0;
800×600: 84.96; 1448×1072: 84.99), so the horizontal values in 4-pixel SDCLK cycles are the i.MX values / 2 [STRONG,
arithmetic].

| | Kindle `ED060TC1-3CE` (i.MX values) | → SDCLK 40 MHz, 4 px per clock | RC2 stock |
|---|---|---|---|
| clock | `pixclock` 80 MHz | 40 MHz | 40 MHz (`dclk_ebc` 160 MHz) |
| LSL (`hsync_len`) | 26 | **13** | **17** |
| LBL (`left_margin`) | 16 | 8 | 8 |
| LDL (`xres`) | 1448 | 362 | 362 |
| LEL (`right_margin`) | 104 | **52** | **55** |
| line | 870 EPDC clocks | **435** (10.875 µs) | **442** (11.05 µs) |
| FSL / FBL / FDL / FEL | 2 / 4 / 1072 / 4 | 2 / 4 / 1072 / 4 | 2 / 4 / 1072 / 4 |
| frame | 1082 lines | 11.767 ms, **84.99 Hz** | 11.96 ms, **83.64 Hz** |
| gate clock high time | `gdclk_hp_offs` 562 | 281 | `lgonl` 281 |
| gate clock start | `gdclk_offs` 225 | 112.5 from line start | LSL + `gdck_sta` = 17 + 100 = 117 |
| source output enable | `sdoed`/`sdoez` width 10, delay 20 | 5 / 10 | the EBC has no such signal on this board |
| physical size | 122 × 91 mm | | the LCDC table's 216 × 135 mm is wrong |

[CONFIRMED-src for Kindle; CONFIRMED-device for RC2 by disassembly and log]

- Both WBF files say 85 Hz in their header (`frame_rate` 0x85, BCD). At 83.64 Hz every waveform frame is 1.6 % longer than
  designed. Stock's extra 7 clocks per line (LSL +4, LEL +3 against Kindle) have no known reason [VERIFY]. The Kindle
  numbers are a candidate to try, not a recommendation: change the timing only with a look at the panel (ghosting, grey steps)
  [VERIFY].
- The gate-clock start: Kindle `gdclk_offs` 225 is 112.5 SDCLK under the /2 reading above, stock starts at LSL + `gdck_sta` =
  117. The 4.5-clock gap is this arithmetic, not a Kindle field; the EPDC and the EBC may count it from different points [VERIFY].
- Kindle's mode for 1072×1448 panels scanned along the short side (`EN060TC1_1CE`, with `FLAG_SCAN_X_INVERT`) is a different
  wiring of the same geometry and does not apply here.

### Update times against E Ink's mode definitions

E Ink's kit manual defines four standard modes and their update time at 85 Hz. The RC2's R110 waveform (24–27 °C range) and
the stock frame time give [CONFIRMED-device for frame counts and frame time]:

| E Ink mode | E Ink definition (kit manual, short) | time at 85 Hz | RC2 frames | RC2 time at 83.64 Hz |
|---|---|---|---|---|
| INIT | full erase from an unknown state | not given | 113 | 1.35 s |
| DU | no flash, any grey → black or white, changed pixels only | **260 ms** | **22** | **263 ms** |
| GC16 | flashing, 16 greys, all pixels updated | **450 ms** | **38** | **454 ms** |
| GL16 | 16 greys, little flashing, white pixels that stay white are not driven | **450 ms** | 38 | 454 ms |

At 85 Hz the RC2 counts give 259 ms and 447 ms: the R110 file has the frame counts behind E Ink's published times. A2 (10
frames) and DU4 (24 frames) are not in the manual.

## 2. Logic level and supplies

| | Kindle (1448×1072 Carta panels) | RC2 |
|---|---|---|
| Panel VDD | EPDC pads switched to low-voltage (1.8 V) mode for every panel of this class (a per-barcode flag, `mx6_wario_gpio.c`) | passport field 0xB0 says **1.8** ([`../panel-flash/README.md`](../panel-flash/README.md)); the stock "EBC/panel logic" rail is ACT8931 **LDO4, 3.1 V** (stock reports 3.0 V, [`../pmic/README.md`](../pmic/README.md) §1.3), switched by the EBC power code |
| VGH (gate high) | **25 V** for all 1448×1072 Carta entries of the barcode table (22 V is the PMIC default for the older panels) | TPS65185 VDDH, set by an external divider; options 22, 25 or 28 V (TI) [VERIFY which] |
| VPOS / VNEG | from the PMIC configuration | VADJ 0x03 = ±15.0 V [CONFIRMED-device] |
| VGL (gate low) | from the PMIC configuration | TPS65185 VEE, fixed −20 V (TI) |

What the waveform itself asks for: VPOS +15 V, VNEG −15 V, VGH +25 V, VGL −20 V, VCOM offset 0, in all 79 voltage-control
blocks of both the ramdisk file (R110) and the panel-flash file (R177) [CONFIRMED-device; format from Kindle, see
[onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform#voltage-control-blocks)]. So VPOS/VNEG and VGL match the RC2's
TPS65185 setup, and **VGH is right only if the board's divider is the 25 V one**. A driver can compare these values with its
PMIC configuration at probe and warn on a mismatch.

The 1.8 V question matters for the DTS: if the panel logic really needs 1.8 V, LDO4 at 3.1 V must be feeding something else
(a level shifter, or the TPS65185's VIN3P3), and the panel's VDD comes from a rail not described in the stock board data
[VERIFY by board].

## 3. TPS65185 power sequence (stock, decoded with TI's datasheet)

Register fields as in SLVSAQ8: UPSEQ0 holds the strobe number − 1 for each rail (bits 7:6 VDDH, 5:4 VPOS, 3:2 VEE, 1:0 VNEG);
UPSEQ1 holds the four power-up delays (0/1/2/3 = 3/6/9/12 ms); DWNSEQ0/1 the same for power-down (DWNSEQ1 delays 6/12/24/48
ms).

| Register | Stock RC2 [CONFIRMED-device] | Decoded | TI default after a WAKEUP reset |
|---|---|---|---|
| UPSEQ0 0x09 | **0x39** | strobe 1 **VDDH (VGH)**, strobe 2 **VNEG**, strobe 3 **VEE (VGL)**, strobe 4 **VPOS** | 0xE4: VNEG, VEE, VPOS, VDDH |
| UPSEQ1 0x0A | **0x11** | 6 ms to strobe 1, then 3, 6, 3 ms (≈ 18 ms in total) | 0x55: 6 ms each |
| DWNSEQ0 0x0B | 0x00 | **all four rails off at strobe 1, at once** | 0x1E: VDDH, VPOS, VNEG, VEE |
| DWNSEQ1 0x0C | 0x00 | 6 ms delays (unused when all rails go together), no discharge-factor bit | 0xE0 |

- Stock writes 0x39/0x11 at the first power-up of every boot; the rails then come up in ≈ 25 ms including the PG poll
  ([top README](../README.md#tps65185-and-vcom)).
- Mainline's `tps65185` regulator driver writes none of these registers and has no binding for them, so on mainline the panel
  would come up with TI's default order (gate high last) rather than stock's (gate high first) [CONFIRMED-src for mainline v7.2].
  Stock's order has worked on these devices for years; which order the panel's maker requires is not public. Options for a port:
  copy stock (optional `ti,upseq`-style properties, a small driver patch), or keep TI's defaults and compare on the panel
  [VERIFY].
- Kindle cannot help here: its MAX77696 PMIC has a hardware sequencer register (`EPDSEQ`, 0x69), but the Kindle kernel only
  defines it (`include/max77696_registers.h`) and never writes it, so the PMIC runs its own default order, which is not public
  [CONFIRMED-src for the kernel; U-Boot not checked].

## 4. VCOM

| | Kindle | RC2 stock |
|---|---|---|
| Source | passport string at flash 0x70010 (`-2.06`) → −2 060 000 µV; a broken string gives −2.05 V | the same passport field |
| Correction | +0.25 V if the WBF header's `vcom_shifted` (0x19) is non-zero (for some waveform types); otherwise, before each update, the offset for the current mode and temperature range from the waveform's voltage-control block | **passport − 0.40 V**, once, as a probe-time "auto-fix" when the PMIC EEPROM holds a factory default |
| Where | written to the PMIC's VCOM register before every power-up; nothing in EEPROM | written to the TPS65185 **EEPROM** (166 = 1.66 V on this unit) |
| When enabled | after PWR_GOOD only (wait up to 250 ms), as its own regulator | the EBC drives the VCOM_CTRL pin (GPIO2_C0 as EBC_VCOM) during updates |

On the RC2 files `vcom_shifted` is 0 and every VCOM offset is 0 [CONFIRMED-device], so by Amazon's rules this panel would run
at **2.06 V**, not 1.66 V. The 0.40 V is ONYX's own choice; its reason (board, contrast, a batch correction) is unknown
[VERIFY]. For a port: either Kindle's way (passport value, written to the register at power-up, EEPROM untouched) or stock's
1.66 V; compare on the panel (ghosting, contrast in GC16 and DU) before choosing. The TPS65185 sets VCOM in 10 mV steps.

## 5. For a mainline device tree

- Panel timing in SDCLK cycles: stock 17/8/362/55, 2/4/1072/4, `gdck-sta` 100, `lgonl` 281 at 40 MHz (known to work);
  the Kindle-derived 13/8/362/52 as the 85 Hz candidate [VERIFY].
- `width-mm = <122>`, `height-mm = <91>` with 1448×1072 (landscape scan, as stock).
- TPS65185: `vposneg` 15 V; VCOM node without `regulator-min/max-microvolt` if the EEPROM value (1.66 V) is to be kept;
  the VGH divider and the PWR_GOOD wiring are board facts still to find [VERIFY].
- Check the waveform's voltage-control blocks against this configuration at probe (VGH 25 V).
- Power model worth copying from Kindle (it is also the model of mainline `tps65185`): one regulator for the panel rails, VCOM as
  a separate regulator enabled only after PWR_GOOD with a timeout, one retry after a fault, and a deferred power-off so the rails
  do not cycle between closely spaced updates.
