# Mainline Linux status for the RC2 (checked against v7.2)

What mainline Linux **v7.2** already has for the RK3026 and the RC2 board, what is close, and what is missing. Checked by reading
the v7.2 tree (and, for the removed touch driver, the parent of its removal commit); nothing was booted. The register facts behind
each line are in [`../soc/README.md`](../soc/README.md) and [`../pmic/README.md`](../pmic/README.md); the wiring in
[`../board/README.md`](../board/README.md); the E-Ink controller in [onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc).

Marks: **[CONFIRMED-src]** = read in the v7.2 tree (file named); **[CONFIRMED-device]** = seen on the RC2; **[STRONG]**,
**[VERIFY]**, **[GUESS]** as in the [top README](../README.md#confidence-marks). Size estimates are [GUESS]: S up to ~100 lines,
M 100–800, L above 800.

## Summary

- **v7.2 has no line about the RK3026**: `grep -ril rk3026` over the tree is empty [CONFIRMED-src].
- **The platform without E-Ink is about a dozen small series** (clocks, pinctrl, I2C, USB PHY, eFuse, power domains, ACT8931,
  TPS65185, device trees), a few thousand lines in total, mostly data tables for existing drivers.
- **The big items are three:** the EBC (E-Ink) driver, suspend-to-RAM (code in IMEM, no PMU), and the cyttsp4 touch driver (removed
  from mainline in 2024).
- **Easy to miss:** without `rockchip,rk3026` in the machine's `dt_compat` list the kernel never enables the PL310 L2 cache; without an
  `onyx` vendor prefix a board DTS fails `dt_binding_check`; the `act8865` compatible writes an undocumented register on the
  ACT8931; the TPS65185 driver insists on a PWR_GOOD GPIO.

## 1. Per block

| Block / node | In v7.2 | Missing for RK3026 / RC2 | Size |
|---|---|---|---|
| **Machine, L2 cache** | `arch/arm/mach-rockchip/rockchip.c`: `dt_compat` = rk2928, rk3066a/b, rk3188, rk3228, rk3288, rv1108. Only this machine sets `l2c_aux_*`; without it the PL310 stays off | add `"rockchip,rk3026"` to `dt_compat` [CONFIRMED-src]. PL310 attributes after stock `AUX_CTRL` 0x76030001 [VERIFY] | S |
| **SoC dtsi** | none; the Cortex-A9 part matches `rk3xxx.dtsi`, the peripherals `rk3036.dtsi` | a new `rk3026.dtsi` with `GIC_SPI n−32` interrupts and TIMER1 at 0x20044020; `rockchip,rk3026-…` compatibles in ~15 IP bindings, each with a fallback (`rk2928`/`rk3066`/`rk3036`) | M |
| **Clocks (CRU)** | `clk-rk3036.c` (3 PLLs), `clk-rk3128.c` (4 PLLs, CPLL at `RK2928_PLL_CON(8)`, mode bit 8, as on RK3026) | a new `clk-rk3026.c` + `rk3026-cru.h`: PLL part after `clk-rk3128.c` (but 1-bit parent muxes), peripheral gates/resets after `clk-rk3036.c`, CPU1 reset bit 4, `dclk_ebc` retuning CPLL to 640 MHz for 160 MHz; CLKSEL23 is not a hiword register | M |
| **pinctrl** | `rockchip,rk2928-pinctrl` data: mux at 0xa8, RK2928 pulls at 0x118, 4 banks | own `rk3026` bank data with `IOMUX_GPIO_ONLY` for ports 3A/3B; without it a GPIO request there (GPIO3_B3, the ADC-key IRQ) writes the non-existent mux registers 0xd8/0xdc [CONFIRMED-src] | S |
| **I2C** | `i2c-rk3x`: GRF controller-select only at 0x154 (rk3066) and 0x0a4 (rk3188); the bit formula `BIT(27+n) \| BIT(11+n)` fits | `rk3026_soc_data` with `grf_offset = 0x144` and v0 timings; aliases `i2c0`/`i2c2` are required in the DTS | S |
| **USB PHY** | `phy-rockchip-inno-usb2`: the `rk3036_phy_cfgs` control registers fit; its status bits are shifted by one; the id detection of `rk3128_phy_cfgs` matches RK3026 | `rk3026_phy_cfgs` (bvalid `{0x14c,7,7}`, line state `{0x14c,9,8}`, id `{0x14c,10,10}`, id IRQs from rk3128); IRQs bvalid `GIC_SPI 35`, id `GIC_SPI 51`. Also: without a `chg_det` table the driver runs BC1.2 detection anyway and writes GRF+0x000 bit 0 on every VBUS event; a fix helps RK3036 boards too | S |
| **USB controllers** | `dwc2` with `rockchip,rk3066-usb` | DTS only: OTG `dr_mode = "peripheral"` for adb, the second DWC2 as host for Wi-Fi | — |
| **SMP** | `rockchip,rk3036-smp` (no PMU; SCU + trampoline in `smp-sram` on a Cortex-A9) | DTS only (`enable-method`, `resets` in `cpu@1`, `smp-sram@0`), but this Cortex-A9 branch has never run in mainline (RK3036 is a Cortex-A7): test it. The loader must set the IMEM remap | S |
| **Power domains** | `pm-domains.c` type `DOMAIN_RK3036` (idle requests only) | own table: RK3026 req bits 8–13, ack 16–21, idle 22–27; domain-to-bit mapping [VERIFY]; not needed for a first boot | S |
| **SAR-ADC** | `rockchip,saradc`: 3 channels | the stock ok/menu ADC keys read channel 3, but the datasheet says 2 channels on RK3026: read channel 3 on the device first [VERIFY]; only matters if those keys exist on V1.73 | S |
| **eFuse** | `rockchip,rk3066a-efuse`: address field shifted by 6 | RK3026 shifts by 8; `rk3066a` would read the wrong bytes. Only needed for the chip version (4 on the RC2) | S |
| **dw_mmc (SD)** | `rockchip,rk2928-dw-mshc` (no phase clocks) | DTS only; no UHS on the RC2 | — |
| **PWM, SPI, DMA, UART, timer, GPIO** | `pwm-rockchip` (`rk2928`, no polarity), `spi-rockchip`, `pl330`, `dw-apb-uart`, `rockchip,rk3036-timer`, `gpio-rockchip` | DTS only (the frontlight is active high, no polarity needed) | — |
| **Reboot flags** | `syscon-reboot-mode` (as `rk3036.dtsi`, offset 0x1d8) | DTS: `mode-bootloader = <BOOT_BL_DOWNLOAD>` (the RC2 loader knows LOADER and RECOVER only), `mode-recovery`; mainline's `mode-normal` writes 0x5242C300 where stock writes 0 [VERIFY the loader's reaction] | S |
| **Power-off, restart** | `gpio-poweroff`, ACT8931 MSTROFF via `system-power-controller`; restart via `GLB_SRST_FST` in the clock driver | choose: the power-hold GPIO1_A2 path is what stock uses; MSTROFF and `GLB_SRST_FST` are untested on the RC2 [VERIFY] | S |
| **cpufreq** | `cpufreq-dt`; `cpufreq-dt-platdev` creates the device for `operating-points-v2` without an allowlist | DTS: stock has one point, 912 MHz at 1.40 V; `cpu-supply` = ACT8931 DCDC3 **only with `active-semi,vsel-high`** | S |
| **Suspend-to-RAM** | `arch/arm/mach-rockchip/pm.c` supports RK3288 only (its PMU does the work); there is **no suspend-to-RAM for any Cortex-A9 Rockchip** | a new `pm-rk3026` with SRAM code (DDR self-refresh, PLLs down, clock gates, VSEL low with VSET1 programmed beforehand over normal I²C). Without it `echo mem > /sys/power/state` falls back to s2idle (DDR and PLLs stay up) | L |
| **IO domains** | `io-domain.c` | not needed: the RK3026 GRF has no IO-voltage-select registers | — |
| **GPU, RGA, VPU, codec, LCDC** | `lima` (needs a `rk3026-mali` line with two PPs), RGA2+ only, `hantro` (`rk3066-vpu` probably fits), `inno_rk3036` (DAC part), VOP tables | not needed on an e-reader: KOReader draws on the CPU, there is no speaker on V1.73 and no LCD | — |

## 2. Board chips

| Chip | In v7.2 | What the RC2 needs | Size |
|---|---|---|---|
| **ACT8931** (system PMIC) | no `act8931` anywhere; `act8865-regulator.c` knows ACT8600, ACT8846, ACT8865. **The ACT8931 regulator map equals the ACT8865's bit for bit** (VSET1/VSET2/CTRL addresses, voltage curve, ON = bit 7, DIS, MODE, MSTROFF). But the ACT8865 type writes **0xEF to register 0x0B** (undocumented on the ACT8931) at the end of every probe, and writes the `*_SUS` registers (absent on the ACT8931) when the DTS has suspend states | a new `active-semi,act8931` type: ACT8865 tables without the 0x0B write and without `set_suspend_*`, plus the charger as a `power_supply` (online = 0x78 INDAT, status from 0x7A CSTATE), after the ACT8600 charger code in the same file. DTS: **`active-semi,vsel-high`** (VSEL = GPIO0_A3 high, live bank VSET2), DCDC1–3 `regulator-always-on` + `regulator-boot-on`, LDO4 consumer-controlled. Details in [`../pmic/README.md`](../pmic/README.md) §1.6 | S–M |
| **TPS65185** (E-Ink PMIC) | `drivers/regulator/tps65185.c` (since 7.0). **`pwr-good-gpios` is required** in code and binding (the GPIO also provides the IRQ); without nINT each temperature read waits for a 200 ms timeout; WAKEUP is driven high at probe and never touched; it registers a thermal zone, but the binding has no `#thermal-sensor-cells` | a small patch: make `pwr-good` optional and poll PG (0x0F, mask 0xFA) when it is absent; optionally poll CONV_END without nINT, PM callbacks for WAKEUP, `#thermal-sensor-cells` in the binding. `vin-supply` = an always-on fixed regulator (not LDO4). Stock requests no PWR_GOOD GPIO; whether PWR_GOOD reaches a SoC pin is [VERIFY by board] | S |
| **CW2015** (fuel gauge) | `cw2015_battery`: profile via `cellwise,battery-profile` (64 bytes), "charging" = `power_supply_am_i_supplied()` through `power-supplies`, ALRT unused. **Bug:** when the CONFIG register's ATHD differs from the alert level, the driver ORs in `~CW2015_ATHD(...)` instead of the value, sets ATHD 31 % and the UFG flag, and the battery profile then never loads | a one-line fix (drop the `~`). On the RC2 the condition does not trigger (stock sets ATHD 0) and the chip already holds the stock profile ([`../pmic/README.md`](../pmic/README.md) §3). For "charging", point `power-supplies` at the ACT8931 charger | S |
| **cyttsp4** (touch, Cypress TrueTouch Gen4) | **removed in 2024** (platform data only, no users). `cyttsp5` is a different protocol (PIP over HID-over-I²C) and cannot be extended to Gen4 | bring the core + I²C parts back as a DT driver (`reset-gpios` GPIO0_D3, `interrupts` GPIO1_A0, `vdd-supply` LDO1, `touchscreen-swapped-x-y` + `touchscreen-inverted-y`). The axis maxima come from the controller's sysinfo, not from platform data: the RC2 reports X 0..1447, Y 0..1071, 32 slots [CONFIRMED-device], while the vendor board data's 758/1024 is an unused template | L |
| **HYM8563** (RTC) | `rtc-hym8563` | DTS (IRQ level low, `wakeup-source`). The RTC keeps UTC | — |
| **Keys, LED, vibrator, frontlight** | `gpio-keys`, `leds-gpio`, `gpio-vibrator`, `pwm-backlight` | DTS; keys and cover sensor with `bias-disable` (external pull-ups, [`../soc/README.md`](../soc/README.md) §5.2) | — |
| **RTL8723BU** (Wi-Fi/BT on USB) | `rtl8xxxu` matches `0bda:b720`; BT through the generic Realtek match in `btusb` + `btrtl` (`rtl_bt/rtl8723b_fw`) | DTS: a `regulator-fixed` on GPIO1_A5, active low; firmware `rtlwifi/rtl8723bu_nic.bin` | — |
| **Panel SPI flash** (MX25U) | `spi-nor` + `spi-rockchip` | no mechanism to borrow GPIO1_B0..B3 from their interrupt users for a read; not needed to run the panel ([`../panel-flash/README.md`](../panel-flash/README.md)) | — |
| **Vendor prefix** | `vendor-prefixes.yaml` has `numonyx` and `eink`, no `onyx` | add `onyx` with the first board DTS | S |

## 3. E-Ink

v7.2 has no driver for an EPD controller inside a SoC (neither Rockchip EBC nor i.MX EPDC), no waveform helper and no UAPI for an
update mode; only SPI panels with their own controller (`repaper`, `pixpaper`) and the generic `FB_DAMAGE_CLIPS` plane property
[CONFIRMED-src]. The RK3128 clock driver already describes `DCLK_EBC`/`HCLK_EBC`, but no EBC node or driver exists. The
register-level description of the RK3026 EBC and a sketch of a minimal in-kernel driver are in
[onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc) (`driver/registers.md`, `driver/new-driver.md`).

## 4. Order that makes sense

1. The CW2015 one-liner (no dependencies).
2. The RK3026 base: clocks, pinctrl, I2C, SoC dtsi + bindings + `onyx` prefix + reboot-mode + a minimal RC2 DTS (SD, keys, LED,
   RTC, battery), with the `dt_compat` line for L2.
3. The ACT8931 type, right with or after step 2 (the DTS cannot control LDO4/LDO1 without it).
4. USB PHY (with the BC1.2 fix) and SMP.
5. TPS65185 (once the PWR_GOOD wiring is known), the ACT8931 charger, eFuse, power domains, OPP, SAR-ADC.
6. cyttsp4 as its own series; suspend after everything else works.
7. The EBC driver and its UAPI last: it needs agreement on how userspace selects an update mode.

The platform part does not depend on E-Ink and is useful to other RK3026 devices (Rockchip's reference tablets, other RK3026
e-readers, and the RC2's sibling C67ML).
