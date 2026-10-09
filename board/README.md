# The ONYX board file in the stock RC2 kernel (`MC_Kepler_R2`, pcb V1.73)

Static analysis, 2026-10-08. Target: the stock RC2 kernel Image (Linux 3.0.36+, built 2017-11-07, firmware 1.8.2, sha256
`47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af`, not public; raw ARM, VA = file offset + 0xc0408000), symbols
recovered from the Image's own kallsyms table (`../kernel/extract_kallsyms.py`). The device was not touched for this pass; device
evidence comes from earlier captures on the same unit. The ONYX board source is not public; the reference is the Rockchip
E-Ink SDK board `arch/arm/mach-rk3026/board-rk3026-ebook.c` in [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources)
(**RY** below).

All addresses refer to that 2017-11-07 kernel. The public firmware update (1.9.1, see the top-level README) carries a 2019-11-05
kernel; whether the board-file function addresses match there is [VERIFY] (the EBC driver span was checked and matches; the board
code was not).

Scope: the board span 0xc045de28–0xc045f4cc, the init-section board code 0xc040e264–0xc040ecc0 (`rk30_reserve`, the two `__setup`
handlers, `machine_rk30_board_init`, `last_log_init`), the board's `.data`/`.init.data` (platform devices and platform data, read
through literal pools), and the consumers of the board helpers (`onyx_misc`, cyttsp4, act8931, cw2015, keypad, PM). Section 8 adds
three small ONYX patches outside the board span (leds-ctl, `codec_get_spk`, `onyx_vibrator_enable`). The EBC driver span
0xc060a840–0xc0617800 is out of scope (see [onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc)); only the board-side `ebc_*` hooks
are covered.

Confidence marks:
- [CONFIRMED]: disassembly + a device log or device dump (stock-device boot dmesg, `/proc` and sysfs listings).
- [STRONG]: read directly in the objdump listing or the board data, no device evidence.
- [VERIFY] / [GUESS]: not proven.
- [DTS]: hardware wiring relevant for a mainline device tree (§7).

GPIO numbering (RK3026 uses the rk2928 plat): `gpio = 128 + 32*bank + 8*port + pin`, so 160 = GPIO1_A0, 205 = GPIO2_B5. On this
platform `gpio_to_irq()` is the identity, so `/proc/interrupts` shows GPIO IRQs under their GPIO number. Iomux codes are
`0x<bank><port A..D><pin><function>` (RY `arch/arm/mach-rk3026/include/mach/iomux.h`).

## Summary

- **This RC2 is pcb V1.73.** The cmdline has `pcb_ver=2`. `onyx_pcb_ver_setup` maps "0".."3" to index 0..3, and the name table is
  `{"V1.4/V1.6", "V1.7", "V1.73", "V1.76"}`. Every boot log prints `[ONYX] pcb version is [V1.73]` [CONFIRMED]. `is_onyx_pcb_v17x()`
  is true for index 2 and 3 only (V1.7 = index 1 is *not* "v17x"). Only V1.76 (index 3) has the `hall_en` switch.
- **The board is RY with I2S, NAND-CS and spare EBC pins reused as GPIOs.** On v17x the machine init rewrites part of the board data at
  boot:
  - the touch IRQ moves from GPIO1_B0 to GPIO1_A0, and the "magic" (magnet/Hall) IRQ moves from GPIO1_A0 to GPIO1_B0;
  - page up/down and back become GPIO keys (GPIO2_B5/B6/C3) instead of ADC keys;
  - a vibrator (timed-gpio on GPIO0_A2) is registered;
  - the CW2015 `chg_ok_pin` (GPIO0_A2) and the codec `spk_ctl_gpio` (GPIO1_C6) are set to −1, so the vibrator owns GPIO0_A2, there is
    no "charge done" input, and there is no speaker-amp GPIO;
  - on eMMC boot the SD card-detect moves to GPIO2_A3.
  `/proc/interrupts` on the stock device matches all of this [CONFIRMED].
- **Wi-Fi/BT power:** one GPIO, GPIO1_A5, active low, powers the RTL8723BU combo. It is reference-counted between Wi-Fi
  (`wifi_activate_usb` → `onyx_combo_module_wifi_power`) and BT (`/sys/devices/platform/onyx_misc.0/bt_pwr` →
  `onyx_combo_module_bt_power`). While the module is on, VCCIO (ACT8931 DCDC1) is raised to 3.4 V; when it is off, VCCIO returns to
  3.3 V on v17x. There is no rfkill device for BT. The stock Realtek `libbt-vendor.so` powers BT with `echo %d > …/bt_pwr`
  [STRONG; Wi-Fi half CONFIRMED by logs].
- **ACT8931:** DCDC1 VCCIO 3.0 V in the table, forced to 3.3 V on v17x [CONFIRMED log]. DCDC2 DDR 1.35 V. DCDC3 `vdd_cpu` 1.2 V.
  LDO1 2.8 V (touch; cyttsp4 then sets it to 3.0 V), LDO2 off, LDO3 3.0 V (SD card, codec), LDO4 3.0 V (EBC/panel logic; RY had 1.8 V).
  The ONYX `act8931_i2c_suspend` writes four suspend set-points (pcb-dependent), and resume restores nothing [STRONG].
- **The magic IRQ is a magnet sensor that presses POWER.** The IRQ is GPIO1_B0, falling edge, wake-enabled. When the system is not in
  mem suspend, the handler injects KEY_POWER down/up. Stock counted 22 such IRQs in one boot (`/proc/interrupts`)
  [STRONG; hardware VERIFY].
- **ONYX `idle` suspend state:** `/sys/power/state` accepts `idle` (pm_states[2]). Only in that state are the touch IRQ (GPIO1_A0 on
  v17x) and the ADC-key IRQ (GPIO3_B3) armed as wake sources [STRONG]. Details: [`../power/README.md`](../power/README.md).
- **Section 8 (other ONYX patches):**
  - `leds-ctl` is a single GPIO LED on GPIO2_B7, controlled through `/sys/class/leds-ctl/leds-ctl/ledsctl` (0666). The `/dev/leds-ctl`
    chrdev does nothing. Stock userspace turns the LED off at boot-complete and on at shutdown.
  - `codec_get_spk` / `onyx_misc.0/hp_ctl` drive the codec's speaker-amp GPIO, but on V1.73 that GPIO is −1, so `hp_ctl` is a no-op
    (it would be GPIO1_C6 on pcb 0/1).
  - `onyx_vibrator_enable` pulses GPIO0_A2 (active low) for 50 ms on every non-power key press when `rk29-keypad/vibrator` is 1, and
    for 100 ms at boot. `/sys/class/timed_output/vibrator` exists on V1.73.
- **Corrections and surprises** (§7c):
  - the panel's own SPI flash identifies an **ED060KD1U7** with waveform `320_R177_AE6A41_ED060KD1U7_TC`, while the kernel runs the
    ramdisk waveform `320_R110_AE4D21_ED060KD1C2_TC` [CONFIRMED log];
  - the keypad ADC values in [`../kernel/sysfs-attributes.md`](../kernel/sysfs-attributes.md) are shifted by one entry;
  - "RC2 has no Hall sensor" is only true for the `hall_en` power switch.

## 1. Pin map (pcb V1.73 unless noted)

Columns: GPIO (number), function on RC2, direction / active level, set by, pcb dependence, evidence.

| GPIO (no.) | Function | Dir / level | Set by | pcb dependence | Conf. |
|---|---|---|---|---|---|
| GPIO1_A0 (160) | Touch (cyttsp4) IRQ | in, no pull; IRQ; wake source only in `idle` | `machine_rk30_board_init` writes 160 into `onyx_get_tp_irq_pin` var and cyttsp4 core pdata `irq_gpio` | v17x; pcb 0/1: this is the magic IRQ | CONFIRMED (dmesg `IRQ gpio=160`, `/proc/interrupts` 160 `main_ttsp_core…`) |
| GPIO0_D3 (155) | Touch reset (`onyx_get_tp_rst_pin`) | out, active low (xres 1→0→1, 20/40/20 ms) | cyttsp4 pdata `rst_gpio` | all; V1.76: driven low in `rk30_pm_power_off` | CONFIRMED (dmesg `RST gpio=155`) |
| GPIO1_B0 (168) | "magic" IRQ = magnet/Hall sensor → KEY_POWER | in, no pull, falling edge, `irq_set_irq_wake(…,1)` | `magic_init` (gpio from data+0x4fc, rewritten to 168 on v17x) | v17x; pcb 0/1: GPIO1_A0 (and 168 is the touch IRQ there). Muxed to SPI0_CLK while the panel flash is read | CONFIRMED (`/proc/interrupts` 168 `magic_int`, 22 hits) |
| GPIO1_A5 (165) | Wi-Fi/BT combo power (RTL8723BU) | out, **active low** (0 = on); boot state high (off) | `rk29sdk_wifi_bt_gpio_control_init` (inline in machine init, label `wifi_power`); `onyx_wifi_bt_module_power` | all | STRONG (logs show the refcount messages) |
| GPIO1_A2 (162) | PWR_HOLD ("system power on") | out high; low at power-off | machine init `gpio_request_one(…, OUT_INIT_HIGH)`; `rk30_pm_power_off` | all | STRONG |
| GPIO1_A4 (164) | Power key (`play`, KEY_POWER 116) | in, active low, wakeup=1 | keypad table entry 0 | all | CONFIRMED (`/proc/interrupts` 164 `play`; resume log `wakeup gpio1: 00000010` = bit 4) |
| GPIO2_B5 (205) | Page up key (KEY_PAGEUP 104) | in, active low, wakeup=1 | machine init rewrites table entry (ADC 177 → GPIO) | v17x; pcb 0/1: ADC key | CONFIRMED (dmesg `Keycode [104] config changed to GPIO[205]`) |
| GPIO2_B6 (206) | Page down key (KEY_PAGEDOWN 109) | in, active low, wakeup=1 | same (ADC 100 → GPIO) | v17x | CONFIRMED |
| GPIO2_C3 (211) | Back key (`esc`, KEY_BACK 158) | in, active low, wakeup=1 | same (only the 158 entry whose ADC value is 302) | v17x | CONFIRMED |
| GPIO3_B3 (235) | ADC-key IRQ (`adc_irq_io`, ADC channel 3) for `ok` (158, ADC 505) and `menu` (59, ADC 400) | in; wake source in `idle` | keypad pdata | all | CONFIRMED (`/proc/interrupts` 235) |
| GPIO0_A2 (130) | Vibrator (timed-gpio `vibrator`, max 1000 ms) | out, **active low** | timed-gpio pdata; registered only on v17x | v17x | STRONG (`/sys/class/timed_output/vibrator` exists on stock) |
| GPIO0_A2 (130) | CW2015 `chg_ok_pin` (charge done), pull-up, level 1 | in | cw201x pdata +40 | **pcb 0/1 only**: machine init writes −1 on v17x (data+0x690), so the driver skips it | STRONG (no request error in any log) |
| GPIO1_B1 (169) | CW2015 ALRT (`bat_low_detect`), pull-up, active low | in, IRQ | cw201x pdata +32 | all | CONFIRMED (`/proc/interrupts` 169) |
| GPIO1_B2 (170) | CW2015 `chg_mode_sel_pin` (charge-current select) | out, init 1 | cw201x pdata +16/+24 | all | STRONG |
| GPIO1_A1 (161) | CW2015 `chg_mode_sel_pin1` (2nd charge-current select, ONYX field) | out, init 1 | cw201x pdata +20/+28 | all | STRONG |
| — | DC detect | none (`dc_det_pin = -1`); USB-only charging (`is_usb_charge = 1`), VBUS from dwc_otg `bvalid` | | | STRONG |
| GPIO1_B3 (171) | HYM8563 RTC IRQ | in | i2c0 board info irq | all | CONFIRMED (`/proc/interrupts` 171; resume `wakeup gpio1: 00000800`) |
| GPIO0_A3 (131) | `pmu_gpio` (ACT8931 control pin, probably VSEL) | out high; low during SRAM suspend ([`../power/README.md`](../power/README.md) §1.2) | `act8931_set_init` | all | STRONG (pin), GUESS (VSEL) |
| GPIO0_D2 (154) | Frontlight PWM0 | PWM, active high (`bl_ref = 1`) | `rk29_backlight_io_init`; suspend: GPIO, mdelay(5) then freed; resume: mdelay(6), PWM again | all; **no BL_EN GPIO** (RY had GPIO0_D3/GPIO1_A1) | STRONG |
| GPIO2_B7 (207) | Status LED (blue; the init label says `LED_GREEN`), `leds-ctl` | out, 1 = on; on at boot | machine init (`led_en`) then `gpio_led_init` (`leds-ctl`) | all | STRONG (stock scripts use it) |
| GPIO1_C6 (182) | Speaker amp enable (`spk_ctl_gpio` of rk3026-codec) | out, 1 = on, init 0 | codec pdata +0 | **pcb 0/1 only**: machine init writes −1 on v17x (data+0x6d8). On V1.73 the pin is not touched by the kernel | STRONG |
| GPIO2_B2 (202) | `spi_ctl`: panel SPI flash enable (EBC_SDOE pin reused) | out, 1 during flash access | `spi_ctl_pins_enable` | all | CONFIRMED (dmesg `spi_ctl_pins_enable: enable =1/0` around `panel_get_id`) |
| GPIO1_B0..B3 | SPI0 CLK/TXD/RXD/CS0 to the panel flash, only while `spi_ctl_pins_enable(1)` | mux switch | `spi_ctl_pins_enable` | all; pcb 0 also drops VCCIO to 1.8 V during the read | CONFIRMED |
| GPIO2_B4 (204) | `lcd_d10` (EBC_SDCE2 pin), held low; driven **high** during SRAM suspend ([`../power/README.md`](../power/README.md) §1.2) | out 0 | machine init | all | STRONG (purpose unknown [VERIFY]; not the touch reset on RC2, which is GPIO0_D3) |
| GPIO2_B0/B1/B3, C1/C2, D0/D1 | EBC SDCLK, SDLE, GDCLK, GDOE, GDSP, GDPWR1, GDPWR2 | EBC function | `ebc_io_init` | all | STRONG |
| GPIO2_C0 (208) | EBC_VCOM function while the panel is powered; tps65185 `vcom_ctl_pin` in pdata | EBC fn / GPIO | `ebc_power_on/off`, tps65185 pdata | all | STRONG |
| GPIO3_C1 (241) | tps65185 WAKEUP | out | tps65185 pdata | all | STRONG |
| — | tps65185 PWRUP | none (`pwr_up_pin = -1`) | | | STRONG |
| — | tps65185 PWR_GOOD / nINT | not in the board pdata (only wake/vcom/pwrup) | — | | VERIFY in the tps65185 driver (EBC span) |
| GPIO2_C4/C5 | I2C2 SDA/SCL. Requested, pull disabled, muxed to I2C2, then freed | | machine init | all | STRONG |
| GPIO2_A7 (199) | SD card-detect; on eMMC boot: EMMC_CLKOUT | in / EMMC fn | sdmmc0 pdata `det_pin_info`; machine init | `onyx_emmc=1` and v17x | STRONG |
| GPIO2_A3 (195) | SD card-detect on eMMC boards | in, active low | machine init writes 195 into sdmmc0 `det_pin_info.io` | `onyx_emmc=1` and v17x | CONFIRMED (`/proc/interrupts` 195 `sd_detect`) |
| GPIO1_B7, C0, C2–C5 | SD (MMC0) CMD, CLK, D0–D3 | MMC fn; driven as GPIOs by `rk29_sdmmc_gpio_open` around power changes | | all | STRONG |
| GPIO0_B0, B1, B3–B6 | MMC1 (SDIO) CMD, CLK, D0–D3. Unused: Wi-Fi is USB. D1–D3 are driven low at init | | | all | STRONG (IRQ count of `rk29_sdmmc.1` = 0) |
| — | Headphone detect / `hp_ctl_gpio` | none (`hp_ctl_gpio = -1`; dmesg `rk3026 hp_ctl_gpio is NULL!`) | | | CONFIRMED |
| — | BT wake / host-wake | none: BT is the USB function of RTL8723BU, so there are no UART/wake pins in the board data | | | STRONG |

## 2. Regulators and voltages (ACT8931 @ i2c0-0x5b, no IRQ)

Regulator table (`act8931_dcdc_info` in .data at 0xc0a710b4, `act8931_ldo_info` in rodata at 0xc08c2dcc; struct
`pmu_info {name, min_uv, max_uv, suspend_vol, enable}`). Applied by the ONYX `act8931_set_init` @0xc045e930:

| Rail | Supply name(s) | Stock value | RY value | Consumer on RC2 | Conf. |
|---|---|---|---|---|---|
| DCDC1 | `act_dcdc1` | 3.0 V in the table; **3.3 V on v17x** (`[ONYX] Set VCCIO initial voltage to 3.3v`) | 3.2 V | VCCIO (GPIO banks; RTL8723BU supply follows it) | CONFIRMED (`act_dcdc1 =3300000mV`) |
| DCDC2 | `act_dcdc2` | 1.35 V | 1.35 V | DDR3 | CONFIRMED |
| DCDC3 | `act_dcdc3`, `vdd_cpu` | 1.2 V at init (DVFS later asks 1.40 V for 912 MHz, [`../kernel/linux-rockchip-3.0-vs-stock.md`](../kernel/linux-rockchip-3.0-vs-stock.md) §1) | 1.2 V | ARM | CONFIRMED (init value) |
| LDO1 | `act_ldo1` | 2.8 V on; cyttsp4 sets **3.0 V** on v17x | 3.3 V `vcc_tp` | Touch controller (v176: Hall sensor instead) | CONFIRMED (`act_ldo1 =2800000mV`, `[CYTTSP4] setup vcc_tp to 3.0V`) |
| LDO2 | `act_ldo2` | 3.0 V, **disabled** | 3.0 V off | — | CONFIRMED (not printed as enabled) |
| LDO3 | `act_ldo3` | 3.0 V on | 3.0 V | microSD (`vmmc` regulator of sdmmc0) and the codec `power_set` (`rk3026_power_on`) | CONFIRMED |
| LDO4 | `act_ldo4` | **3.0 V** on | 1.8 V `vcc_lcd` | EBC/panel logic: `ebc_power_on/off` enable/disable it (`ebc_platform_data.regulator`) | CONFIRMED (value), STRONG (consumer) |

Regulator constraints are 0.6–3.9 V for all rails (`ACT_*` init data at 0xc0a7297c…).

**VCCIO switching** (`onyx_vccio_set_voltage` @0xc045ebac): it sets DCDC1 to the requested value. On v17x a request ≤ 3.3 V is clamped
to 3.3 V (`vccio should not lower than 3.3v`), and mdelay(20) follows every change. Callers:
- `onyx_wifi_bt_module_power`: 3.4 V on the first user, 3.0 V (so 3.3 V on v17x) after the last;
- `rk29sdk_wifi_power` (the Broadcom `bcmdhd_wlan` path, unused on RC2): the same pair.
The clamp message appears in device logs after Wi-Fi off [CONFIRMED].
`spi_ctl_pins_enable` uses `regulator_set_voltage(dcdc1, 1.8 V, 3.0 V)` during a panel-flash read and 3.0 V after, but only on pcb 0
(V1.4/V1.6) [STRONG].

**Touch power** (`onyx_tp_power_set_voltage` / `onyx_tp_power_enable`): LDO1 set-voltage and enable/disable, with msleep(20) after
enable. Both are **no-ops on V1.76**, where the touch panel is on another supply and LDO1 feeds the Hall sensor
(`onyx_hall_sensor_power`, 2.8 V).

**Suspend** (ONYX `act8931_i2c_suspend` @0xc061b17c, legacy i2c suspend; `act8931_i2c_resume` is an empty `return 0`). Raw VSET0
writes, decoded with the driver's `buck/ldo_voltage_map`:

| Register | Value | Decoded | Condition |
|---|---|---|---|
| 0x20 DCDC1 VSET0 | 0x36 | 2.9 V | v17x only |
| 0x30 DCDC2 VSET0 | 0x19 | 1.25 V | always |
| 0x54 LDO2 VSET | 0x34 | 2.8 V | always |
| 0x40 DCDC3 VSET0 | 0x0a | 0.85 V | always |

The register writes are [STRONG]. The meaning is [VERIFY]: writing 0.85 V into the live ARM set-point while the CPU still runs, with
no restore on resume, only makes sense if VSET0 is the *sleep* set-point selected by a VSEL pin during the SRAM suspend. GPIO0_A3
`pmu_gpio` driven high would then be VSEL. Supporting evidence: the ONYX SRAM pin helper at 0xfef014f0 drives GPIO0_A3 **low** (and
GPIO2_B4 high) in suspend and reverses both on resume ([`../power/README.md`](../power/README.md) §1.2). So GPIO0_A3 = ACT8931 VSEL is
[STRONG-GUESS]. Deep sleep and resume work on the device with this kernel, so the sequence is safe in practice. The SRAM-side voltage code
(`rk30_suspend_voltage_set/resume`) is documented in [`../power/README.md`](../power/README.md).

`rk30_pwm_suspend_voltage_set` / `_resume_` are empty stubs (no PWM regulator). `board_gpio_suspend/resume` are the empty weak
defaults. The EBC `ebc_suspend/ebc_resume` hooks are `return 0` stubs (RY gated `vcc_lcd` there), so the panel rail is switched only by
`ebc_power_on/off` [STRONG].

## 3. I2C, SPI and platform devices

**I2C** (`i2c_register_board_info` from machine init; 44-byte RK `i2c_board_info` with `udelay`):

| Bus | Addr | Device | IRQ (GPIO) | Platform data | On device |
|---|---|---|---|---|---|
| 0 | 0x62 | `cw201x` (CW2015 fuel gauge) | – (driver requests ALRT GPIO1_B1 itself) | ONYX `cw_bat_platform_data` at 0xc0a715f8: `is_dc_charge 0, dc_det -1, is_usb_charge 1, chg_mode_sel GPIO1_B2 (1), chg_mode_sel1 GPIO1_A1 (1), bat_low GPIO1_B1 (0), chg_ok GPIO0_A2 (1; −1 on v17x)` + **inline** 64-byte battery profile (RY had a pointer and one sel pin) | CONFIRMED |
| 0 | 0x5b | `act8931` | none | `{7 regulators, set_init = act8931_set_init}` | CONFIRMED |
| 0 | 0x51 | `rtc_hym8563` | GPIO1_B3 (171) | – | CONFIRMED |
| 1 | – | (registered with 0 entries) | | | |
| 2 | 0x24 | `cyttsp4_i2c_adapter` | static 168 in board info; runtime GPIO1_A0 from core pdata | adapter id string. Core pdata (0xc0a71784): `irq_gpio, rst_gpio=155, level 5?, xres/init/power/irq_stat`, button keymap `HOME(102) MENU BACK SEARCH VOLDOWN VOLUP CAMERA POWER`; MT pdata: flags 0x28 (FLIP+INV_Y), X 0..758, Y 0..1024, vkeys 720×1280 | CONFIRMED |
| 2 | 0x5d | `Goodix-TS` (alternative panel; the first driver to probe sets `onyx_system_tp_probed` and the other one skips) | none | none (uses `onyx_get_tp_irq/rst_pin`, `onyx_tp_power_enable`) | CONFIRMED (registered; `GTP i2c test failed` → absent) |
| 2 | 0x68 | `tps65185` (EPD PMIC) | none | `{wake_up_pin GPIO3_C1, vcom_ctl_pin GPIO2_C0, pwr_up_pin -1}` (= RY) | CONFIRMED (`tps65185_probe vcomvalue = 166`; the panel flash separately reports `vcom:[-2.06]`; relation: see §7b) |
| 3 | – | (0 entries) | | | |

**SPI** (`spi_register_board_info`):
- `epd_spi_flash`, bus 0, CS 0, **6 MHz** (RY 12 MHz), the panel's waveform/ID flash. Read only between `spi_ctl_pins_enable(1/0)` [CONFIRMED].
- `test_drv` with platform data `"helloword"`: a leftover Rockchip SPI test device [STRONG].

**Platform devices** (`devices[]` at 0xc042bc10, 7 entries, then the display devices):

| Device | Data |
|---|---|
| `ion-rockchip` | carveout `norheap` 20 MiB at 0x7d100000 |
| `bcmdhd_wlan.1` | `rk29sdk_wifi_power/reset/set_carddetect/mem_prealloc`; resource `bcmdhd_wlan_irq` = -1. Broadcom leftover, no consumer on RC2 |
| `rk3026-codec` | SoC acodec; `{spk_ctl_gpio GPIO1_C6 (−1 on v17x), (new field) -1, hp_ctl_gpio -1, delay_time 10, power_set rk3026_power_on (LDO3)}`. The probe tests `spk_ctl_gpio == 0`, so −1 prints nothing (dmesg only has `hp_ctl_gpio is NULL!`), and the request of −1 fails silently |
| `rk29-ebc.0` | resources: reg 0x10114000–0x10117fff, IRQ 81, `ebc buf` (1 MiB waveform at 0x7ff00000), **`ebc disp buf` 8 MiB at 0x7f700000** (new vs RY); pdata `{ebc_io_init, NULL, ebc_power_on, ebc_power_off, vcom_on/off stubs, suspend/resume stubs, "act_ldo4"}` |
| `leds-ctl` | `{GPIO2_B7, 1, 0}` (§8.1) |
| `spi_gpio.3` | all pins -1 → probe fails `-22` (dmesg) — leftover |
| `onyx_misc.0` | sysfs only ([`../kernel/sysfs-attributes.md`](../kernel/sysfs-attributes.md)) |
| `rk-fb`, `rk30-lcdc.0`, `rk29_backlight` | fb resources (fb0 18 MiB at 0x7e500000); lcdc0 reg 0x1010e000, IRQ 41; backlight pdata below |
| `timed-gpio` | only on v17x: `{"vibrator", GPIO0_A2, 1000 ms, active_low 1}` |

Not registered (present in RY or the driver set): `rfkill_rk` (so the `rfkill_rk_init` driver binds nothing and there is no `rfkill0`),
`rk_headsetdet`, `rk30-battery` (ADC battery), `matrix-keypad`, `pwm-voltage-regulator`, `epd_lm75`.

**Backlight** (`rk29_bl_info` at 0xc0a72898): PWM0, `bl_ref = 1` (duty ∝ brightness; RY 0), min 0, max 255, `brightness_mode = LINE`
(RY CONIC), `delay_ms = 0`, `pre_div = 0` → driver default 1000 [STRONG]. Sysfs is `/sys/class/backlight/rk28_bl/`.

**SD / SDIO:** sdmmc0 (microSD): caps 4-bit|MMC_HS|SD_HS, OCR 2.5–3.6 V, DMA `sd_mmc`, regulator `act_ldo3`, no power-enable or WP
GPIO, `enable_sd_wakeup = 0`. sdmmc1 (SDIO, unused): caps include SDIO_IRQ, OCR 2.5–3.4 V, status = `rk29sdk_wifi_status`.
`rk31sdk_get_sdmmc0_pin_io_voltage` = 3300 mV, `rk31sdk_get_sdio_wifi_voltage` = 3000 mV.

**Keypad** (`rk29_keys_platform_data` at 0xc0a720bc): 6 buttons, ADC channel 3, `adc_irq_io` GPIO3_B3. The ONYX entry is 44 bytes:
`code +0, gpio +8, adc_value +16, active_low +24, desc +28, wakeup +32, two extra words +36/+40`.

| # | desc | code | as built | after machine init on v17x |
|---|---|---|---|---|
| 0 | play | 116 POWER | GPIO1_A4, wakeup | unchanged |
| 1 | pageup | 104 | ADC 177 | GPIO2_B5, wakeup |
| 2 | pagedown | 109 | ADC 100 | GPIO2_B6, wakeup |
| 3 | ok | 158 BACK | ADC 505 | unchanged (ADC) |
| 4 | esc | 158 BACK | ADC 302 | GPIO2_C3, wakeup |
| 5 | menu | 59 F1 | ADC 400 | unchanged (ADC) |

**Reserved memory** (`rk30_reserve`): `ebc waveform buf` 1 MiB (then replaced by `waveform_addr=` from the cmdline, 0x7ff00000),
`ebc disp buf` 8 MiB, `fb0 buf` = `get_fb_size()` (18 MiB), `ion` 20 MiB [CONFIRMED dmesg].

## 4. Power sequences

**EBC** (`ebc_platform_data` hooks, called by the EBC driver):
- `ebc_io_init`: iomux SDCLK, SDLE, GDCLK, GDOE, GDSP, GDPWR1, GDPWR2 to EBC; GRF+0x150 |= 1 (write-masked). RY also muxed
  SDOE and SDCE2–5; ONYX reuses those pins as GPIOs (§1).
- `ebc_power_on`:
  1. `act_ldo4` on if it is off;
  2. free the five parking GPIOs;
  3. re-mux SDCLK, SDLE, GDCLK, **EBC_VCOM (GPIO2_C0)**, GDOE, GDSP to EBC;
  4. GRF+0x150 |= 1.
  No delays.
- `ebc_power_off`:
  1. mux GPIO2_B0..B3 and C0..C2 to GPIO;
  2. drive `lcdc_clk` B0, `lcdc_hsync` B1, `lcdc_den` B3, `lcd_dat15` C1, `lcd_dat16` C2 low (outputs);
  3. GRF+0x150 = 0xffff0300;
  4. `act_ldo4` off.
  No delays.
- `ebc_vcom_power_on/off`, `ebc_suspend/resume`: stubs returning 0. VCOM is handled by the tps65185 driver and the EBC_VCOM pin
  function [STRONG].

**Touch** (cyttsp4 board callbacks):
- `cyttsp4_init(on)`:
  1. on v17x print `[CYTTSP4] setup vcc_tp to 3.0V` and call `onyx_tp_power_set_voltage(3.0 V)`;
  2. `onyx_tp_power_enable(1)` (LDO1 on, msleep 20);
  3. request RST and set it high;
  4. request IRQ as input.
  Off: free both GPIOs, `onyx_tp_power_enable(0)`.
- `cyttsp4_xres`: RST 1, 20 ms, 0, 40 ms, 1, 20 ms.
- `cyttsp4_power` (wake): IRQ pin output low for 2 ms, then input.
[CONFIRMED by dmesg order: `TP power On` → `INIT CYTTSP RST gpio=155 and IRQ gpio=160` → `RESET`.]

**Wi-Fi/BT module** (`onyx_wifi_bt_module_power(enable)` @0xc045ec54, use count at bss 0xc0b71440+0x68):
- On, count 0→1: VCCIO 3.4 V (mdelay 20 inside), then GPIO1_A5 = 0, state = 1.
- Off, count 1→0: GPIO1_A5 = 1, state = 0, then VCCIO 3.0 V (3.3 V on v17x).
- Prints `onyx_wifi_bt_module_power ---- enable=%d use_count=%d`.
- Wrappers `onyx_combo_module_wifi_power` and `onyx_combo_module_bt_power` drop repeated requests (`Duplicant … power state`), so
  each of Wi-Fi and BT holds at most one count.
- Wi-Fi: `wifi_activate_usb` → `wifi_turn_on_card(5)` → `wifi_turn_on_rtl8192c_card` → `onyx_combo_module_wifi_power(1)` (msleep 1000
  if a flag is set), then msleep 100. Off: `onyx_combo_module_wifi_power(0)`, msleep 5, callback, msleep 100. [CONFIRMED log: the
  USB device 0bda:b720 enumerates about 2.4 s after `enable=1`]
- BT: `onyx_misc.0/bt_pwr` store `'1'`/other → `onyx_combo_module_bt_power(1/0)`. `bt_pwr` show prints the **module** state (Wi-Fi
  or BT), not the BT state [STRONG].
- `onyx_wifi_bt_module_power_init` (end of machine init) tries to request GPIO1_A5 as `system power on` and fails, because the
  inline wifi init already holds it as `wifi_power` (dmesg `Failed to request 'system power on'`). This is harmless [CONFIRMED].

**Power-off** (`rk30_pm_power_off` @0xc045e350, installed as `pm_power_off`; RY had it commented out):
1. If `g_pmic_type == ACT8931` (SRAM var), busy-wait about 12k loops.
2. If the charger is present (`act8931_charge_det`), loop forever:
   - if PWR_HOLD GPIO1_A2 reads high, print `POWER_ON_PIN is high` and drive it low;
   - busy-wait;
   - only once `system_state == SYSTEM_POWER_OFF`, check the power key GPIO1_A4: if it stays low for about 50 iterations, call
     `arm_pm_restart`. This is the "power key while charging boots it" path.
3. Without a charger:
   - on V1.76 only, drive the touch RST GPIO0_D3 low;
   - `act8931_device_shutdown` (reg 0x01 bits 0x23).
4. Finally drive GPIO1_A2 low and spin.
[STRONG]

**`rk3026_power_on(enable)`** (codec `power_set`): `act_ldo3` on (msleep 20) / off. LDO3 is also the SD rail, so the codec and the
microSD share it [STRONG].

**Suspend / resume hooks:**
- `act8931_i2c_suspend` (§2).
- Backlight PWM suspend: free PWM0, request it as a GPIO output low, mdelay(5), free. Resume: mdelay(6), free, iomux PWM0.
- `suspend_irqwake_set(state)` (`kernel/power/irqwake.c`, public in rychly; `pm_irqwake_enable` is ONYX-modified): when entering
  state 2 `idle` it arms the touch IRQ (160 on v17x, 168 otherwise) and the ADC-key IRQ 235 as wake sources. They are disarmed on
  return to ON/MEM. Full idle-vs-mem analysis: [`../power/README.md`](../power/README.md).
- Wake sources in normal `mem` suspend:
  - keys with `wakeup = 1` (power; and on v17x page up/down and back);
  - the magic IRQ (`irq_set_irq_wake` in `magic_init`);
  - RTC;
  - USB/charger (`bvalid`, `do_wakeup`).
  Logs show `wakeup gpio1: 00000010` (GPIO1_A4 power key) and `00000800` (GPIO1_B3 RTC) [CONFIRMED].

## 5. `pcb_ver=` and `onyx_emmc=`

`onyx_pcb_ver_setup` @0xc040e35c (`__setup("pcb_ver=")`): `"0"`→0, `"1"`→1, `"2"`→2, `"3"`→3, otherwise `WARN: unknown onyx pcb
version` (the value stays 0). For `"3"` it also clears an SRAM flag at 0xfef01cec (default 1; [`../power/README.md`](../power/README.md) §1.2; consumer [VERIFY]). It prints `Setup PCB
version [%d]`. `onyx_get_pcb_version()` prints `[ONYX] pcb version is [%s]` from `onyx_pcb_version_str[]` on *every* call, which is
why the boot logs repeat it.

| Behaviour | 0 V1.4/V1.6 | 1 V1.7 | **2 V1.73 (this RC2)** | 3 V1.76 |
|---|---|---|---|---|
| `is_onyx_pcb_v17x` | no | no | **yes** | yes |
| Touch IRQ / magic IRQ | GPIO1_B0 / GPIO1_A0 | same | **GPIO1_A0 / GPIO1_B0** | same as 2 |
| Page / back keys | ADC | ADC | **GPIO2_B5 / B6 / C3** | GPIO |
| Vibrator (timed-gpio) | no | no | **yes, GPIO0_A2** | yes |
| CW2015 `chg_ok_pin` GPIO0_A2 | yes | yes | **no (−1)** | no |
| Codec `spk_ctl_gpio` GPIO1_C6 | yes | yes | **no (−1)** | no |
| VCCIO at init / floor | 3.0 V / none | 3.0 V / none | **3.3 V / 3.3 V** | 3.3 V / 3.3 V |
| VCCIO 1.8 V during panel-flash read | yes | no | no | no |
| Suspend DCDC1 VSET0 = 2.9 V | no | no | yes | yes |
| cyttsp4 sets LDO1 to 3.0 V | no | no | yes | yes |
| Touch power via LDO1 | yes | yes | yes | **no** (functions are no-ops) |
| `hall_en` / LDO1 = Hall sensor | no (−ENODEV) | no | no | **yes** |
| Touch RST low at power-off | no | no | no | yes |
| SD card-detect move on eMMC | no | no | yes | yes |

`onyx_bootmedia_setup` @0xc040e2f8 (`__setup("onyx_emmc=")`): `"1"` sets the `emmcboot` flag (`boot from emmc [1]`). It matters only in
the v17x branch of the machine init, where it prints `[ONYX]Setup emmc boot`, muxes GPIO2_A7 to EMMC_CLKOUT and moves the SD
card-detect to GPIO2_A3. `onyx_get_emmcboot()` has no caller in the kernel. The recovery script `sbin/boot_check.sh` greps the
cmdline for `onyx_emmc=1` [CONFIRMED].

## 6. The small helpers

- **`magic_init` / `magic_int_handler`:** a magnet (Hall) sensor IRQ.
  - Init: `gpio_request`, pull disabled, input, `request_threaded_irq(gpio, handler, NULL, IRQF_TRIGGER_FALLING, "magic_int")`, then
    `irq_set_irq_wake(gpio, 1)`. It is called unconditionally from machine init.
  - Handler: `disable_irq_nosync`; unless `get_suspend_state() == 3` (mem), print `______magic schedule suspend state:%d` and
    `rk29_send_power_key(1)` then `(0)`; then `enable_irq`.
  - So closing a magnetic cover toggles the screen exactly like POWER, and the falling edge also wakes from mem suspend.
  - On V1.73 the sensor has no software power switch (LDO1 is shared with the touch panel). `hall_en` exists only on V1.76
    [STRONG; whether the RC2 shell has the sensor fitted: VERIFY with a magnet, though the 22 stock IRQs suggest yes].
- **`spi_ctl_pins_enable(enable)`** (exported; called by `spi_flash_probe`/`spi_flash_read` of the EBC panel flash):
  - Enable:
    1. `cw_disable_batt_low_irq(0)` (the CW2015 ALRT pin GPIO1_B1 is SPI0_TXD);
    2. on pcb 0 only, VCCIO 1.8–3.0 V;
    3. GPIO2_B2 `spi_ctl` high;
    4. iomux GPIO1_B0..B3 to SPI0 CLK/TXD/RXD/CS0, then verify with `iomux_is_set`.
  - Disable:
    1. iomux back to GPIO;
    2. `spi_ctl` low;
    3. on pcb 0 only, VCCIO 3.0 V;
    4. mdelay(10);
    5. `cw_disable_batt_low_irq(1)` (re-enable);
    6. mdelay(10).
  - During that window the magic IRQ, the CW2015 ALRT, the charge-select pin and the RTC IRQ lose their pins. It happens once at
    boot (1.12 s) [CONFIRMED].
- **`last_log_*`:** the stock Rockchip `plat-rk/last_log.c` (public; "version 2.1"). The 512 KiB printk buffer is moved to fresh pages
  and the previous content is copied into a static buffer, exposed as `/proc/last_log` (0444) with the symlink `/proc/last_kmsg`.
  `last_log_get` is used by the FIQ debugger. Not ONYX [STRONG]. It survives only a warm reboot (RAM retention).
- **`wrapper_sram_i2c_write`:** `blx 0xfef01740`, which is the SRAM copy (image VA 0xc0b6f730) of `sram_i2c_write(slave, reg, val)`
  from `mach-rk3026/i2c_sram.c`. The wrapper always returns 0. It has no caller (only the kallsyms table references it), so it is dead
  code [STRONG].
- `rk29sdk_wifi_mac_addr` (bcmdhd only) takes the MAC from bytes 506..511 of the NAND "SN sector" (`GetSNSectorInfo`). It is not
  used by the Realtek driver. `rk29sdk_wifi_reset` only prints and stores the value [STRONG].
- `cyttps4_virtualkeys_show`: the RY string (BACK, MENU, HOME, SEARCH at x=1360), unused (`enable_vkeys = 0`).

## 7. Notes on the stock system, DTS material, corrections

### (a) Stock-system notes

1. **Bluetooth power** [STRONG]. The power path is userspace → `/sys/devices/platform/onyx_misc.0/bt_pwr` (0666) → GPIO1_A5
   (+ VCCIO 3.4 V), shared with Wi-Fi by a refcount.
   - There is no rfkill node; the stock Realtek `libbt-vendor.so` powers BT through its `BT_VND_OP_POWER_CTRL` path
     (`echo %d > …/bt_pwr`, `/dev/rtk_btusb` from `rtk_btusb.ko`).
   - Because power is shared, BT-off with Wi-Fi on keeps the chip powered, and `cat bt_pwr` reports the module, not BT.
2. **Status LED** [STRONG]. GPIO2_B7 is on from power-up. Stock switches it off at `dev.bootcomplete=1` (service `blueled_ctl`), and
   `ShutdownThread` (via `DeviceController.led(true)`) and recovery's `boot_check.sh` turn it on. Without `blueled_ctl` the LED stays
   on while the device is awake.
3. **"Idle" suspend** [STRONG]. The kernel accepts `idle`, and only that state arms touch and ADC keys as wake sources. In `mem` only
   the GPIO keys, magnet, RTC and USB wake. See [`../power/README.md`](../power/README.md); the board facts here only add the pin names.
4. **Magnet cover** [STRONG]. It is a KEY_POWER injection in the kernel; userspace needs nothing. `hall_en` returning −19 (no
   sensor control) is correct for V1.73; only the claim "RC2 has no hall sensor" is inaccurate.
5. **Vibrator** [STRONG/VERIFY]. `/sys/class/timed_output/vibrator/enable` exists on V1.73, so Android haptics reach GPIO0_A2. The
   keypad also buzzes 50 ms per key in-kernel when `rk29-keypad/vibrator` = 1 (boot default [VERIFY]). Stock `mc_kepler_r2.json` says
   `has_vibration=True`; the motor is fitted (§8.3).
6. **Headphone/speaker:** on V1.73 `hp_ctl` does nothing (the speaker-amp GPIO is −1). No jack detect exists (`hp_ctl_gpio = -1`, no
   `rk_headsetdet`). Stock 4.2 uses the AOSP stub audio HAL.
7. **Suspend power:** VCCIO stays at 3.4 V while Wi-Fi is on. Switching Wi-Fi off in sleep also drops VCCIO to 3.3 V. The ACT8931
   suspend set-points are fixed in the kernel.
8. `input_disable` (0666) drops **every** input event in `input_event()`. Stock `charge_helper` uses it in off-mode charging. Any app
   can lock the device out until reboot (there is no SELinux on this kernel).
9. `/proc/last_kmsg` exists and survives a warm reboot.

### (b) Material for a mainline DTS of RC2 (and the sibling C67ML)

Mark: **[DTS]**. Each one is hardware wiring rather than vendor driver behaviour. The C67ML may differ: it is presumably another pcb
revision of the same board (pcb_ver 0/1 vs 2/3), so the pcb table in §5 is the most useful thing to share.

- [DTS] PMIC ACT8931 @ i2c0 0x5b (no IRQ). DCDC1 VCCIO 3.3 V (3.4 V with Wi-Fi), DCDC2 DDR 1.35 V, DCDC3 ARM, LDO1 touch 3.0 V,
  LDO3 SD 3.0 V, LDO4 EPD logic 3.0 V, LDO2 unused. Power hold GPIO1_A2 (active high); GPIO0_A3 driven high (VSEL?).
- [DTS] Fuel gauge CW2015 @ i2c0 0x62, ALRT GPIO1_B1 active low (pull-up); charge-current selects GPIO1_B2 and GPIO1_A1 (driven
  high); USB-only charging; no charge-done input on V1.73 (GPIO0_A2 on pcb 0/1). Battery profile: 64 bytes inline at 0xc0a71628 (extractable).
- [DTS] RTC HYM8563 @ i2c0 0x51, IRQ GPIO1_B3.
- [DTS] Touch cyttsp4 @ i2c2 0x24, IRQ GPIO1_A0 (V1.73+; GPIO1_B0 on older boards), reset GPIO0_D3 active low, supply LDO1 3.0 V,
  X 0..758, Y 0..1024, flip + invert Y. Optional Goodix @ i2c2 0x5d on other panels.
- [DTS] EPD PMIC TPS65185 @ i2c2 0x68, WAKEUP GPIO3_C1, VCOM_CTRL on GPIO2_C0 (EBC_VCOM function), no PWRUP GPIO. The panel flash of
  this RC2 stores VCOM −2.06 V; the PMIC reads back 166 (`read_vcom_mv`) [VERIFY units]. The EBC-driver analysis reads 166 as 1.66 V (10 mV units), which is 2.06 − 0.40 V,
  the driver's VCOM auto-fix rule ([onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc); summary in the top-level README).
- [DTS] EBC pins: SDCLK GPIO2_B0, SDLE B1, GDCLK B3, GDOE C1, GDSP C2, GDPWR1 D0, GDPWR2 D1, VCOM C0. SDOE/SDCE2–5/GDPWR0 are *not*
  used for the panel.
- [DTS] Panel SPI flash on SPI0 (GPIO1_B0..B3, 6 MHz), gated by GPIO2_B2 high. These pins are shared with interrupt lines
  (magnet, CW2015 ALRT, charge-select, RTC), so a DTS needs a pinctrl state switch, not a permanent SPI mux.
- [DTS] Keys: power GPIO1_A4, page up GPIO2_B5, page down GPIO2_B6, back GPIO2_C3 (all active low, wakeup). ADC keys on SARADC
  channel 3 (ok ≈ 505, menu ≈ 400 of 1023; may not be fitted), ADC-key IRQ GPIO3_B3.
- [DTS] Magnet sensor GPIO1_B0, falling edge (→ `gpio-keys` KEY_POWER or SW_LID). Vibrator GPIO0_A2 active low. Status LED GPIO2_B7
  active high. Frontlight PWM0 (GPIO0_D2), active high, no enable GPIO.
- [DTS] RTL8723BU on USB host (usb20_host), power enable GPIO1_A5 **active low** (a `regulator-fixed` with `gpio` low-active, or a USB
  `reset`/power sequence).
- [DTS] microSD on MMC0, supply LDO3, card-detect GPIO2_A3 (eMMC boards) or GPIO2_A7. eMMC on the eMMC controller (GPIO2_A7 =
  EMMC_CLKOUT). The SDIO controller is unused.
- [DTS] Audio: RK3026 internal acodec, no jack detect; the speaker-amp enable is GPIO1_C6 on pcb 0/1 only, none on V1.73.

### (c) Corrections and surprises

- **Panel identity.** The waveform in the ramdisk (`ebc_waveform.bin`) names `…ED060KD1C2…`, R110, and the kernel log
  `spi_id_buffer = 320_R110_AE4D21_ED060KD1C2_TC` names the waveform in use (the driver loads the ramdisk `/ebc_waveform.bin`; see
  [onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc)). But the panel's own SPI flash reports `panel id:
  [ED060KD1U7]`, `wfm_ver: [320_R177_AE6A41_ED060KD1U7_TC]` in every boot log (14 logs checked) [CONFIRMED].
  So the RC2 runs a C2 waveform on a U7 panel, and stock does the same.
- **Keypad table in [`../kernel/sysfs-attributes.md`](../kernel/sysfs-attributes.md):** the ADC values are ok 505, esc 302, menu 400
  (not ok/esc 302/400). On V1.73 pageup, pagedown and esc become GPIO keys at boot (§3), so the physical BACK is the `esc` entry on
  GPIO2_C3. The left page key's KEY_BACK in `key_switching` case 0 is a remap of a GPIO key. `ok` (ADC) is probably not fitted [VERIFY].
- **[`../kernel/rk-fb-keypad-battery-wifi.md`](../kernel/rk-fb-keypad-battery-wifi.md) §E:** the ACT8931 values were [VERIFY]; they
  are now resolved in §2. LDO4 is 3.0 V, not RY's 1.8 V. `magic_*` is the magnet/Hall wake, now [STRONG].
- **LED init:** `leds_init` @0xc041ed50 is the standard LED-class init (`/sys/class/leds`). The ONYX `leds-ctl` is created by
  `gpio_led_init` @0xc041eda8, which replaced the leds-gpio driver init.
- **"RC2 has no codec" is wrong:** the SoC-internal acodec does probe (`rk3026-codec`); on V1.73 the board data removes the
  speaker-amp GPIO, and there is no jack detect [STRONG].
- **GPIO0_A2 is not double-booked on V1.73:** the board data lists it both as the vibrator and as the CW2015 `chg_ok_pin`, but the v17x
  branch of the machine init sets `chg_ok_pin` (and the codec `spk_ctl_gpio`) to −1 before the drivers probe. This is consistent with
  the logs (no request error) [STRONG].

## 8. Other ONYX driver patches

### 8.1 `leds-ctl` (status LED)

- **Init:** `gpio_led_init` @0xc041eda8 (initcall level 6; it replaces the stock leds-gpio driver init) does the following:
  - `alloc_chrdev_region(…, "leds-ctl")`: the major is dynamic, **247** on stock (`/proc/devices`), minor 0;
  - `cdev_add` with fops `{open = leds_open, read = leds_read → 0, write = leds_write → 0}` and no ioctl;
  - `class_create("leds-ctl")` and `device_create("leds-ctl")` → `/dev/leds-ctl` (crw------- root on stock) and
    `/sys/class/leds-ctl/leds-ctl/` (= `/sys/devices/virtual/leds-ctl/leds-ctl/`);
  - sysfs attribute **`ledsctl` 0666**;
  - then `gpio_free(207)`, `gpio_request(207, "leds-ctl")`, output **1** (LED on).
  [STRONG; nodes CONFIRMED in stock-device listings]
- **Protocol:** `ledsctl` show prints `gpio_get_value(GPIO2_B7)`. Store: `'1'` → on, `'0'` → off; it only acts if the state changes,
  under a mutex. The chrdev carries no protocol. The exported `led_on_off(gpio, val)` is a bare `__gpio_set_value` with no caller.
  The platform device `leds-ctl` (pdata `{207, 1, 0}`) has no matching driver.
- **Hardware:** one LED on GPIO2_B7, active high. Machine init labels it `led_en` / "LED_GREEN"; on the device it lights blue. It is not a
  charge LED; charging indication, if any, is outside the kernel [VERIFY].
- **Stock users:**
  - `/system/bin/blueled_ctl` (`echo 0 > …/ledsctl`), started on `dev.bootcomplete=1` (stock `init.rc` l.568–574);
  - framework `DeviceController.led(boolean)` → `ShutdownThread` calls `led(true)` at shutdown;
  - the ONYX launcher (ContentBrowser) calls `led(false)` at start;
  - recovery `sbin/boot_check.sh` blinks it 4× on a wrong-flash-type panic.

### 8.2 `codec_get_spk` / `hp_ctl`

- `codec_get_spk` @0xc074f0c8 (exported): if the codec private struct exists, it returns `gpio_get_value(priv->spk_ctl_gpio) == 1`.
  `priv+0x14` = pdata `spk_ctl_gpio`: GPIO1_C6 in the board data, but **−1 on v17x** (machine init). If the GPIO is −1 it returns 0;
  without the codec it returns −1 with a printk.
- Its only kernel caller is `onyx_misc` `hp_ctl_get`. `hp_ctl_set` with `'1'` schedules `hp_enable_work_func` after 20 ms, which
  calls `codec_set_spk(1)`; anything else calls `codec_set_spk(0)` → `gpio_set_value(spk_ctl_gpio, 0/1)`, which returns early when
  the GPIO is −1. The codec itself also forces the speaker off in `rk3026_codec_power_down` and `rk3026_codec_resume`.
- So `hp_ctl` is "speaker amplifier enable", not a headphone switch, and on this V1.73 RC2 it is a complete no-op (`cat hp_ctl` → 0). There is no headphone detect (`hp_ctl_gpio = -1`, no headset
  driver).
- The RC2 has no speaker GPIO, and the stock 4.2 build uses the AOSP stub audio HAL [STRONG].

### 8.3 `onyx_vibrator_enable` / vibrator

- **Device:** timed-gpio `vibrator` on **GPIO0_A2, active low, max 1000 ms**. It is registered only on v17x, so it exists on this V1.73
  RC2. `/sys/class/timed_output/vibrator` is present in the stock `/sys/class` listing [CONFIRMED]. At probe the driver buzzes 100 ms
  (`gpio_enable(…, 100)`) and creates the wakelock `timed_gpio_wake`.
- **`onyx_vibrator_enable(ms)`** @0xc07308b0: it uses the first timed-gpio:
  - `hrtimer_cancel`;
  - set the GPIO to the active level (`active_low ? !on : on`), retried up to 3×;
  - if ms > 0, arm the hrtimer for `min(ms + adjust_time, max_timeout)` ms, and the timer callback switches it off.
- **Callers:** `keys_isr` and `keys_timer` (rk29-keypad) call it with 50 ms on a key event for any key except POWER (116), gated by the
  `rk29-keypad/vibrator` flag (`onyx_vibrator_control`, [`../kernel/sysfs-attributes.md`](../kernel/sysfs-attributes.md)).
- **Motor present?** The kernel registers it only on V1.73/V1.76 boards, and stock `mc_kepler_r2.json` has `has_vibration=True`, so
  probably yes. **Confirmed on the device: the motor is fitted and buzzes on the left/right page keys** (the in-kernel keypad buzz)
  [CONFIRMED].

## Method and reproduce

Nothing was executed natively. The Image is only read by objdump, Python and Ghidra. The kernel Image and the kallsyms list are not
in this repository: `IMG` is the raw (uncompressed) stock kernel, `SYMS` the list written by
`python3 -I ../kernel/extract_kallsyms.py $IMG $SYMS`. All addresses below are for the 2017-11-07 stock kernel
(sha256 `47a13cf3…30af`); see [`tools/README.md`](tools/README.md).

```
# annotated objdump (GPIO numbers, iomux names from the RY iomux.h via $RY_IOMUX, kallsyms names, strings, data pointers)
python3 -I tools/kdis.py $IMG $SYMS 0xc045de28 0xc045f4cc      # board span
python3 -I tools/kdis.py $IMG $SYMS machine_rk30_board_init     # one function
python3 -I tools/kdis.py $IMG $SYMS --callers onyx_get_pcb_version spi_ctl_pins_enable
# board .data / .init.data (platform devices and pdata), zero runs collapsed
python3 -I tools/kdump.py $IMG $SYMS 0xc0a70f90 1500   # board data anchor (used by every board fn)
python3 -I tools/kdump.py $IMG $SYMS 0xc042bb08 110    # i2c0/i2c2 info, devices[], spi, cyttsp4
python3 -I tools/kdump.py $IMG $SYMS 0xc08c2d40 60     # pcb names, act8931_ldo_info (rodata)
# everything at once + Ghidra decompile of the 104 functions in tools/board.list (about 15 s)
tools/run.sh $IMG $SYMS <out-dir> <ghidra-work-dir>
```

- `tools/kdis.py` and `tools/ImportKallsymsRaw.java` / `DecompileList.java` are extended versions of the tools used for the EBC
  driver analysis: GPIO, iomux and data-pointer annotations; a function list instead of an address range.
- Ghidra 12.1.4 with JDK 21. objdump is the arbiter. Ghidra mangled `cyttsp4_irq_stat` and `hp_enable_work_func` (tail calls merged
  with neighbours), and those were read in objdump.
- The anchors that make data readable:
  - the board code addresses one block at **0xc0a70f90** (section anchor), and offsets from it reach every board pdata;
  - the bss block **0xc0b71440** holds the ONYX state: +0x44/+0x48/+0x4c wifi status callback, +0x50 module power state,
    +0x58 pcb index, +0x64 emmcboot, +0x68 module use count, +0x6c BT state, +0x70 Wi-Fi state.
- Device evidence used: stock-device `/proc/interrupts`, `/proc/devices`, `/proc/cmdline`, `/sys/class`, `/dev` and I²C name
  listings (excerpts in [`../device/`](../device/README.md)), a stock-kernel boot dmesg with full board init, Wi-Fi power logs, stock
  `/system` scripts and `framework.odex` strings.
- The run's outputs (`board.decomp.c`, `board-span.s`, `init-board.s`, `fn/*.s`, `board-data.txt`, `board-initdata.txt`,
  `callers.txt`) are working notes and are not published; `board.decomp.c` is a decompilation of vendor code.

## Still [VERIFY]

- Whether a Hall sensor is fitted (the vibration motor is, §8.3): test with `echo 200 > /sys/class/timed_output/vibrator/enable` and a magnet
  near the screen edge (`cat /proc/interrupts | grep magic`).
- The ACT8931 suspend set-points: VSET0 versus VSEL, and the role of GPIO0_A3.
- tps65185 PWR_GOOD/nINT wiring (not in the board pdata; EBC-span driver).
- The consumer of the SRAM flag cleared for pcb "3" (0xfef01cec), and the role of GPIO2_B4 (high in suspend).
- Whether `ok`/`menu` ADC keys exist physically.
- Which LED colour or colours are behind GPIO2_B7.
