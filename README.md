# onyx-rc2-hardware

Hardware notes for the **ONYX BOOX Robinson Crusoe 2** (internal name `MC_Kepler_R2`, Rockchip RK3026, pcb **V1.73**): pins,
regulators, the E-Ink PMIC and VCOM, panel timings, keys, frontlight, power management and device facts, read out of the stock
vendor kernel and checked on one device. Written with a mainline device tree in mind; the RC2's sibling C67ML is probably another
pcb revision of the same board.

Related:
- [onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc): the stock EBC (E-Ink controller) driver, described: `/dev/ebc` ABI, update
  modes, LUT handling, the TPS65185 driver, the panel SPI flash.
- [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform): the panel waveform, its format and a decoder.

The stock firmware itself is not here. ONYX publishes the RC2 firmware update download (1.9.1-simple 2019-11-05_18-20 db0cce3,
MD5 `bce0d3914e8acabb494685159fc9a141`) on its support page: <https://onyx-boox.ru/support/boox_robinson-crusoe2>.

## Device summary

| Part | What | Where documented |
|---|---|---|
| SoC | Rockchip RK3026, 2 × Cortex-A9 (NEON, VFPv3). The stock DVFS table has one point: **912 MHz at 1.40 V** | [`kernel/linux-rockchip-3.0-vs-stock.md`](kernel/linux-rockchip-3.0-vs-stock.md) §1 |
| RAM | 512 MiB DDR3 (ACT8931 DCDC2 1.35 V), DDR at 396 MHz | [`device/README.md`](device/README.md), [`power/README.md`](power/README.md) §4.3 |
| Panel | 6", **1448×1072**. The ramdisk waveform says **ED060KD1C2**, the panel's own SPI flash says **ED060KD1U7** | below; [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform) |
| E-Ink controller | SoC EBC, reg 0x10114000–0x10117fff, IRQ 81 | [onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc) |
| System PMIC | Active-Semi **ACT8931** @ i2c0 0x5b, no IRQ | [`board/README.md`](board/README.md) §2 |
| E-Ink PMIC | TI **TPS65185** @ i2c2 0x68 (`TPS65185r1p2`) | below |
| Touch | Cypress **cyttsp4** (TrueTouch Gen4) @ i2c2 0x24; a Goodix driver @ i2c2 0x5d is registered as an alternative and is absent | [`board/README.md`](board/README.md) §3 |
| Wi-Fi / BT | Realtek **RTL8723BU** on USB (`0bda:b720`), one power GPIO for both | [`board/README.md`](board/README.md) §4 |
| Storage | eMMC, Samsung, 7456 MB, used through Rockchip's MTD layer (`rk29xxnand`, `onyx_emmc=1`) | [`device/README.md`](device/README.md) |
| microSD | MMC0, supply ACT8931 LDO3, card-detect GPIO2_A3 | [`board/README.md`](board/README.md) §3 |
| Keys | power, page up, page down, back on GPIOs; two ADC keys in the table (`ok`, `menu`), probably not fitted | below |
| Frontlight | PWM0 (GPIO0_D2), active high, no enable GPIO | below |
| Battery | Li-ion, **CW2015** fuel gauge @ i2c0 0x62; USB-only charging | [`board/README.md`](board/README.md) §3, [`power/README.md`](power/README.md) §3 |
| RTC | HYM8563 @ i2c0 0x51, IRQ GPIO1_B3 | [`board/README.md`](board/README.md) §3 |
| Other | vibration motor (GPIO0_A2), status LED (GPIO2_B7), magnet (Hall) sensor that acts as POWER (GPIO1_B0), SoC audio codec without speaker or jack on V1.73 | [`board/README.md`](board/README.md) §6, §8 |

## For a mainline device tree

GPIO numbering in the vendor kernel: `gpio = 128 + 32*bank + 8*port + pin` (160 = GPIO1_A0, 205 = GPIO2_B5), and `gpio_to_irq()` is
the identity [STRONG]. Pins and the per-pcb differences are in [`board/README.md`](board/README.md) §1 and §5; the bullets below are
copied from its DTS section with the confidence of the underlying pin-table rows.

- PMIC ACT8931 @ i2c0 0x5b (no IRQ). DCDC1 VCCIO 3.3 V (3.4 V with Wi-Fi), DCDC2 DDR 1.35 V, DCDC3 ARM, LDO1 touch 3.0 V,
  LDO3 SD 3.0 V, LDO4 EPD logic 3.0 V, LDO2 unused. Power hold GPIO1_A2 (active high); GPIO0_A3 driven high (VSEL?).
  [CONFIRMED values from the boot log; STRONG power hold; GUESS VSEL]
- Fuel gauge CW2015 @ i2c0 0x62, ALRT GPIO1_B1 active low (pull-up); charge-current selects GPIO1_B2 and GPIO1_A1 (driven
  high); USB-only charging; no charge-done input on V1.73 (GPIO0_A2 on pcb 0/1). Battery profile: 64 bytes inline in the board data.
  [CONFIRMED address and ALRT IRQ; STRONG the rest]
- RTC HYM8563 @ i2c0 0x51, IRQ GPIO1_B3. [CONFIRMED]
- Touch cyttsp4 @ i2c2 0x24, IRQ GPIO1_A0 (V1.73+; GPIO1_B0 on older boards), reset GPIO0_D3 active low, supply LDO1 3.0 V,
  X 0..758, Y 0..1024, flip + invert Y in the board platform data. Optional Goodix @ i2c2 0x5d on other panels. [CONFIRMED IRQ, reset
  and supply by dmesg; the input device on the running system reports X 0..1447, Y 0..1071, 32 slots ([`device/proc/getevent.txt`](device/proc/getevent.txt))]
- EPD PMIC TPS65185 @ i2c2 0x68, WAKEUP GPIO3_C1, VCOM_CTRL on GPIO2_C0 (EBC_VCOM function), no PWRUP GPIO; PWR_GOOD/nINT are not
  in the board data [STRONG; PG/nINT wiring VERIFY]. VCOM: see below.
- EBC pins: SDCLK GPIO2_B0, SDLE B1, GDCLK B3, GDOE C1, GDSP C2, GDPWR1 D0, GDPWR2 D1, VCOM C0. SDOE/SDCE2–5/GDPWR0 are *not*
  used for the panel. [STRONG]
- Panel SPI flash on SPI0 (GPIO1_B0..B3, 6 MHz), gated by GPIO2_B2 high. These pins are shared with interrupt lines
  (magnet, CW2015 ALRT, charge-select, RTC), so a DTS needs a pinctrl state switch, not a permanent SPI mux. [CONFIRMED]
- Keys: power GPIO1_A4, page up GPIO2_B5, page down GPIO2_B6, back GPIO2_C3 (all active low, wakeup). ADC keys on SARADC
  channel 3 (ok ≈ 505, menu ≈ 400 of 1023; may not be fitted), ADC-key IRQ GPIO3_B3. [CONFIRMED GPIO keys; VERIFY ADC keys fitted]
- Magnet sensor GPIO1_B0, falling edge (→ `gpio-keys` KEY_POWER or SW_LID) [CONFIRMED IRQ; hardware VERIFY]. Vibrator GPIO0_A2
  active low [CONFIRMED motor fitted]. Status LED GPIO2_B7 active high [STRONG]. Frontlight PWM0 (GPIO0_D2), active high, no enable
  GPIO [STRONG].
- RTL8723BU on USB host (usb20_host), power enable GPIO1_A5 **active low** (a `regulator-fixed` with `gpio` low-active, or a USB
  `reset`/power sequence). [STRONG]
- microSD on MMC0, supply LDO3, card-detect GPIO2_A3 (eMMC boards) or GPIO2_A7. eMMC on the eMMC controller (GPIO2_A7 =
  EMMC_CLKOUT). The SDIO controller is unused. [CONFIRMED card-detect; STRONG the rest]
- Audio: RK3026 internal acodec, no jack detect; the speaker-amp enable is GPIO1_C6 on pcb 0/1 only, none on V1.73. [STRONG]
- Memory the vendor kernel reserves (`rk30_reserve`, [CONFIRMED dmesg]): `ebc buf` (waveform) 1 MiB at 0x7ff00000 (`waveform_addr=`
  from the loader), `ebc disp buf` 8 MiB at 0x7f700000, `fb0 buf` 18 MiB at 0x7e500000, ION carveout 20 MiB at 0x7d100000.
- Interrupts in the vendor kernel's numbering ([`device/proc/proc_interrupts.txt`](device/proc/proc_interrupts.txt)): EBC 81, LCDC 41
  (never fires: the LCDC does not scan out on this board), i2c0..3 56..59, SARADC 49, `bvalid` 67, `otg-id` 83.

## Panel timings

The stock EBC driver takes its panel description from a 72-byte table in the kernel data (`set_epd_info`, table at 0xc0a8faa8 in the
2017-11-07 kernel) [CONFIRMED by disassembly; source: the EBC-driver analysis, [onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc)]:

| Field (Rockchip `ebc_panel_info` name) | Value |
|---|---|
| width × height | **1448 × 1072** |
| hsync, hstart, hend | 17, 8, 55 |
| vsync, vstart, vend | 2, 4, 4 |
| frame_rate | 85 |
| pixclock | 40 MHz; the driver calls `clk_set_rate(dclk_ebc, 4·pixclock)` |
| rotate | 270 (the stock `ro.sf.hwrotation=270` is taken from this field) |
| gdck_sta | 100 |
| lgonl | 281 |
| vir_width × vir_height, fb_width × fb_height | 1448 × 1072 |
| color_panel | 0 |

- At 4 px per clock that is (362+80)·1082/40 MHz = **11.96 ms per frame (83.6 Hz)** [STRONG]: 362 = 1448/4 data clocks plus
  17+8+55 = 80 per line, 1072+2+4+4 = 1082 lines. GC16 at 24–27 °C (38 frames) takes 0.454 s; back-to-back PART updates on the device
  are 0.47 s apart [CONFIRMED log].
- The probe writes EPD_CTRL (EBC reg +0x04) as `(hsync+gdck_sta)<<27 | 3 | (…)<<16 | min(width/4,255)<<8`; H/VTIMING0/1 and
  DSP_ACT_INFO (+0x0c..+0x1c) come from the same table (`ebc_panel_scan_set`).
- The waveform file header also says 85 Hz (`frame_rate` 0x85).
- The LCDC side is separate and does not drive the panel: `set_lcd_info` fills the fb var with pixclock 71 MHz, margins
  L100/R18/HS10/U8/L6/VS2, lcdc_aclk 300 MHz, and a wrong physical size of 216×135 mm (the real panel is about 122×91 mm, ≈300 dpi)
  [CONFIRMED]; see [`kernel/rk-fb-keypad-battery-wifi.md`](kernel/rk-fb-keypad-battery-wifi.md) §A.2.

**Not in our sources:** a mapping of these Rockchip field names to the E Ink datasheet terms (LSL/LBL/LDL/LEL, FSL/FBL/FDL/FEL,
SDCK/GDCK timing), and the panel datasheet itself. `gdck_sta` and `lgonl` are used only as numbers here.

## TPS65185 and VCOM

| | |
|---|---|
| Bus | i2c2 0x68, 400 kHz, chip `TPS65185r1p2` [CONFIRMED log] |
| Pins | WAKEUP GPIO3_C1; VCOM_CTRL on GPIO2_C0, which is muxed to the EBC_VCOM function while the panel is powered; PWRUP not connected (`pwr_up_pin = -1`); PWR_GOOD / nINT not in the board data [VERIFY] |
| Logic supply | ACT8931 LDO4 3.0 V (`act_ldo4`), switched on/off by the board's `ebc_power_on/off` with no delays (RY used 1.8 V) [CONFIRMED value, STRONG consumer] |
| Power-up | from the first power-up the driver overrides UPSEQ0/1 to **0x39/0x11** (public driver 0xE4/0x00); read with the TPS65185 register map: strobe order VDDH, VNEG, VEE, VPOS, delays 6/3/6/3 ms [STRONG]. Then ENABLE = 0x20 (3V3 only), 2 ms, ENABLE = 0xAF (all rails, ACTIVE); poll PG == 0xFA up to 30× at ~20 ms; on timeout STANDBY and retry after 200 ms, 3 attempts; a final failure is swallowed. Typical ≈25 ms [CONFIRMED by disassembly] |
| Power-down | ENABLE = 0x6F (STANDBY, 3V3 kept), no wait |
| Suspend | `support_tps_3v3_always_alive()` = 1: the PMIC stays in STANDBY with 3V3 on across system suspend |
| Temperature | from the PMIC; `/proc/epdsensor` prints it; `onyx_misc` `pmic_temp` always prints "25" |

**VCOM.**
- The panel's own SPI flash (read at boot through `spi_ctl_pins_enable`, panel strings at flash offset 0x70000, shown in
  `/proc/panel_info`) holds: part **ED060KD1U7**, **VCOM −2.06 V**, waveform `320_R177_AE6A41_ED060KD1U7_TC` [CONFIRMED log].
- The PMIC's VCOM EEPROM on this unit holds **166** (`tps65185_probe vcomvalue = 166` in dmesg), read as 1.66 V in 10 mV units by
  the EBC-driver analysis. The board-file pass left the unit as [VERIFY].
- The stock kernel never writes VCOM at power-up: the panel always runs on the PMIC EEPROM value. The only automatic writer is a
  probe-time **auto-fix**: if the PMIC holds 1.25 or 1.80 V (factory defaults), it programs the EEPROM to panel VCOM − 400 mV. This
  unit's 1.66 V = 2.06 − 0.40, so the fix ran once [STRONG].
- Other VCOM writers (all program the PMIC EEPROM): `/sys/bus/i2c/drivers/tps65185/vcom_mv` (0666, reads the probe-time cache),
  `onyx_misc.0/vcom_value` (0666), a USB mass-storage vendor SCSI command.
- The kernel displays with the ramdisk waveform `320_R110_AE4D21_ED060KD1C2_TC`, not the one in the panel flash, so the panel ID
  (KD1U7, lot R177) and the waveform in use (KD1C2, lot R110) disagree; stock ships it that way.

## Keypad and frontlight wiring

Keys on pcb V1.73 (the board data is rewritten at boot for "v17x" boards; [`board/README.md`](board/README.md) §3, §5):

| Key | Code | Line | Notes |
|---|---|---|---|
| power (`play`) | KEY_POWER 116 | GPIO1_A4, active low, wakeup | [CONFIRMED] |
| page up | KEY_PAGEUP 104 | GPIO2_B5, active low, wakeup | ADC 177 on pcb 0/1 [CONFIRMED] |
| page down | KEY_PAGEDOWN 109 | GPIO2_B6, active low, wakeup | ADC 100 on pcb 0/1 [CONFIRMED] |
| back (`esc`) | KEY_BACK 158 | GPIO2_C3, active low, wakeup | ADC 302 on pcb 0/1 [CONFIRMED] |
| `ok` | KEY_BACK 158 | SARADC ch 3, ≈505 | probably not fitted [VERIFY] |
| `menu` | KEY_F1 59 | SARADC ch 3, ≈400 | [VERIFY] fitted |

- The ADC-key IRQ line is GPIO3_B3 (`adc_irq_io`); it and the touch IRQ are wake sources only in the vendor "idle" suspend state
  ([`power/README.md`](power/README.md) §2.2, §4.1).
- ONYX runtime controls in `/sys/devices/platform/rk29-keypad/`: `key_switching` (case 0, the boot default, makes the left page key
  report KEY_BACK; case 1 makes it PAGE_UP), `touchkeyena`/`touchkeydis`, `vibrator` (50 ms in-kernel buzz per key)
  ([`kernel/sysfs-attributes.md`](kernel/sysfs-attributes.md)).
- The magnet sensor on GPIO1_B0 (falling edge, wake-enabled) injects KEY_POWER when the system is not in mem suspend.

Frontlight ([`board/README.md`](board/README.md) §3, §4) [STRONG]:
- PWM0 on GPIO0_D2, `bl_ref = 1` (duty ∝ brightness), min 0, max 255, `brightness_mode = LINE`, `delay_ms = 0`, `pre_div = 0` →
  driver default 1000. **No BL_EN GPIO** (the Rockchip reference board had one). Sysfs: `/sys/class/backlight/rk28_bl/`.
- Suspend: PWM0 is taken as a GPIO output low, mdelay(5), freed; resume: mdelay(6), back to PWM. In the vendor "idle" suspend the
  frontlight is left as it is.

## Asked for, not in our sources

- The panel datasheet and the E Ink-terminology timing (see Panel timings).
- TPS65185 PWR_GOOD / nINT wiring; the meaning of UPSEQ 0x39/0x11 against the ED060KD1 specification.
- The frontlight PWM frequency (only `pre_div = 0` → driver default 1000 is known).
- Whether the `ok`/`menu` ADC keys and a Hall sensor are fitted on the RC2 shell (22 magnet IRQs on stock suggest the sensor is).
- GPIO0_A3 as the ACT8931 VSEL pin, the role of GPIO2_B4 (`lcd_d10`) in suspend, the LED colours behind GPIO2_B7.
- A schematic. Everything here comes from the vendor kernel's board code and device observation.

## Repository map

| Path | What |
|---|---|
| [`board/README.md`](board/README.md) | the ONYX board file: pin map, ACT8931 rails, I²C/SPI/platform devices, power sequences, `pcb_ver=`/`onyx_emmc=`, helpers, DTS material, leds-ctl/codec/vibrator |
| [`board/tools/`](board/tools/README.md) | annotated objdump, data dump and Ghidra scripts for the board code |
| [`power/README.md`](power/README.md) | suspend (`idle` vs `mem`), SRAM code, ACT8931 sleep writes, wake sources, charger/battery, cpuidle, ddrfreq |
| [`power/tools/`](power/tools/README.md) | listings, SRAM extract, table dumps |
| [`kernel/rk-fb-keypad-battery-wifi.md`](kernel/rk-fb-keypad-battery-wifi.md) | rk_fb/LCDC ABI, keypad driver, CW2015, RTL8723BU module, compared with public trees |
| [`kernel/sysfs-attributes.md`](kernel/sysfs-attributes.md) | ONYX sysfs nodes (`rk29-keypad`, `onyx_misc`) |
| [`kernel/linux-rockchip-3.0-vs-stock.md`](kernel/linux-rockchip-3.0-vs-stock.md) | what the stock kernel has beyond the public Rockchip 3.0 tree; DVFS table |
| [`kernel/config-reconstruction.md`](kernel/config-reconstruction.md) | the stock kernel configuration reconstructed from the Image |
| [`kernel/extract_kallsyms.py`](kernel/extract_kallsyms.py), [`kernel/sysfs_attrs.py`](kernel/sysfs_attrs.py) | recover kallsyms from a raw Image; list compiled-in sysfs attributes |
| [`device/README.md`](device/README.md), [`device/proc/`](device/proc/) | device facts: identity, partition map, Rockusb, image formats, ramdisk, raw `/proc` and sysfs excerpts |

All addresses refer to the stock RC2 kernel built 2017-11-07 (firmware 1.8.2, sha256
`47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af`), which is not public. The public 1.9.1 update carries a 2019-11-05
kernel. Checked against it: every symbol named in these notes exists there, but many have moved (board file: 59 of 102 at the same
address, 42 moved by −0x34 … +0x23e8; PM: 43 of 57 same, 13 moved), so **use the symbol names, not the addresses**, with that
kernel. Real code changes are only in `machine_rk30_board_init` (1468 → 1488 bytes) and `rk30_adc_ebc_battery_check`
(1004 → 912 bytes); the other functions differ by at most a few relocated words. The EBC driver span is unchanged and at the same
addresses (see [onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc)).

Public reference trees used throughout: [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources) (Rockchip
RK3026 E-Ink SDK, "RY"), [linux-rockchip/linux-rockchip](https://github.com/linux-rockchip/linux-rockchip) `mirror/stable-3.0`
("PUB"), [Nu3001/kernel_rk3188](https://github.com/Nu3001/kernel_rk3188) ("NU").

## Confidence marks

- **[CONFIRMED]**: read in the disassembly and seen on the device (boot log, `/proc`, sysfs), or measured on the device.
- **[STRONG]**: read directly in the disassembly or the board data, or inferred from several confirmed facts; no device evidence.
- **[VERIFY]**: open; needs the device or a document.
- **[GUESS]**: an estimate.
- **[DTS]**: hardware wiring relevant for a device tree (in [`board/README.md`](board/README.md) §7b).

Each document states its exact rule at the top; the power document also counts a direct disassembly read as [CONFIRMED].

## About this work

Not affiliated with ONYX or Rockchip. This came out of porting Android 4.4 to the RC2 on its stock kernel. The analysis was done with an AI coding assistant (Claude); results were checked on the hardware where marked [CONFIRMED]. Reverse engineering was done for interoperability. This repository describes the hardware and the vendor kernel's board code; it contains no vendor code or binaries. Code: MIT (`LICENSE`). Text: CC BY 4.0.

The board code and the EBC driver are part of the vendor's GPLv2 kernel, which ONYX distributes without source; see
[SOURCE-AVAILABILITY.md](https://github.com/hsw/onyx-rc2-ebc/blob/main/SOURCE-AVAILABILITY.md) in onyx-rc2-ebc.
