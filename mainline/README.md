# Mainline Linux status for the RC2 (checked against v7.2)

What mainline Linux **v7.2** already has for the RK3026 and the RC2 board, what is close, and what is missing. Checked by reading
the v7.2 tree (and, for the removed touch driver, the parent of its removal commit). Since then an out-of-tree RK3026 kernel has
been booted on the RC2 (§0); the per-block tables below still describe the v7.2 tree. The register facts behind
each line are in [`../soc/README.md`](../soc/README.md) and [`../pmic/README.md`](../pmic/README.md); the wiring in
[`../board/README.md`](../board/README.md); the E-Ink controller in [onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc).

Marks: **[CONFIRMED-src]** = read in the v7.2 tree (file named); **[CONFIRMED-device]** = seen on the RC2; **[STRONG]**,
**[VERIFY]**, **[GUESS]** as in the [top README](../README.md#confidence-marks). Size estimates are [GUESS]: S up to ~100 lines,
M 100–800, L above 800.

## 0. Booted on the RC2 (2026-10-16/17)

Mario Rugiero's RK3026 tree for the ONYX BOOX C67ML ([Oppen/linux](https://github.com/Oppen/linux), branch `boox-c67ml`, based
on v7.1-rc4), rebased onto **v7.1.13** with the twelve RC2 patches below, **boots on the RC2 from microSD to a shell**: both
CPUs up, a USB CDC ACM console and USB mass storage on the OTG port, a working watchdog, warm reboot and power-off
[CONFIRMED-device]. The kernel is started by a small loader that hands over like the stock one (microSD through the BootROM,
[`../bootrom/sdboot/`](../bootrom/sdboot/README.md)), or by a mainline-based U-Boot loaded the same way; the eMMC is not
touched (its controller nodes are deleted in the board DTS).

The RC2 patches on top of that tree (not yet upstream):
1. dt-bindings: clock: rk3026-cru: number soft resets as 16 * CON + bit
2. ARM: dts: rockchip: rk3026: describe what CPU1 bring-up needs
3. ARM: dts: rockchip: add ONYX BOOX Robinson Crusoe 2 (first light)
4. ARM: configs: add rk3026_onyx_rc2.config fragment
5. ARM: rockchip: pulse the core reset when starting a core without PMU
6. ARM: dts: rockchip: rk3026: Cortex-A9 timer PPIs are edge-rising
7. ARM: dts: rockchip: rk3026-onyx-rc2: enable the PMIC I2C buses
8. ARM: configs: rk3026_onyx_rc2: build in the DesignWare watchdog driver
9. ARM: rockchip: rk3026: map the SRAM at 0 only while starting a core
10. ARM: configs: rk3026_onyx_rc2: configfs ACM + mass storage gadget, kexec
11. ARM: dts: rockchip: rk3026-onyx-rc2: power off through the power hold
12. ARM: configs: rk3026_onyx_rc2: build in the GPIO power-off driver

What the runs showed [CONFIRMED-device unless marked]:
- **Soft-reset numbering:** the reset ids must be 16 · CON + bit, as the clock driver registers them. With dense numbering
  `SRST_CORE1` = 1 hit CON0 bit 1, a reserved bit, and CPU1 could never start; CPU1 is CON0 bit 4.
- **CPU1** needs a reset pulse after the trampoline is in IMEM, because on the RK3026 the assert write itself restarts the
  core and the deassert does nothing. Without it a clean v7.1.13 kernel reports `CPU1: failed to come online`; with it 2
  CPUs, and hotplug and kexec work. The kernel owns the IMEM remap (`GRF_SOC_CON0` bit 12) and sets it only around the
  pulse ([`../soc/README.md`](../soc/README.md) §4.3, IMEM usage in §1.3).
- **Timer PPIs** (global timer, TWD) are rising edge on the Cortex-A9; the level-high form gives `GIC: PPI13 is secure or
  misconfigured` for every CPU.
- **Hard-float userspace needs `CONFIG_VFP`/`CONFIG_VFPv3`/`CONFIG_NEON`.** The C67ML slim defconfig sets
  `KERNEL_MODE_NEON` without VFP, so `olddefconfig` drops both and an armhf `/init` dies with SIGILL on its first VFP
  instruction.
- **Restart:** the mainline `GLB_SRST_SND` handler, `GLB_SRST_FST` and a dw-wdt reset all restart through the BootROM (microSD
  first) and keep DDR, provided the IMEM remap is off and the first stage invalidates L1, since the Cortex-A9 keeps L1 lines
  over a warm reset ([`../soc/README.md`](../soc/README.md) §4.5). After a panic and a watchdog reset the ramoops buffer
  (0x7ff40000) still holds the panic log. **On battery** the mainline restart switches the book off instead (LED dark, ramoops
  empty on the next boot), while the stock kernel restarts on battery. Cause [CONFIRMED-device]: `GLB_SRST_SND` and
  `GLB_SRST_FST` reset the GPIO1 block (a value written to GPIO1's debounce register reads 0 after either, while the GRF
  OS_REGs survive), so the power hold GPIO1_A2 drops and, without USB power, the ACT8931 switches off. A cores-only
  soft reset (SOFTRST_CON0, the stock way) keeps GPIO1: on battery the book restarts and DDR (ramoops) survives. A
  restart handler for battery use therefore has to do the stock-like core reset, not a global one (what each reset clears:
  [`../soc/README.md`](../soc/README.md) §4.5).
- **Power-off:** `gpio-poweroff` on the power hold GPIO1_A2 (active low) switches the book off on battery; no PMIC write is
  needed. With USB power the ACT8931 keeps the board up, so the kernel waits with the line low and the book goes off when
  the cable is pulled ([`../power/README.md`](../power/README.md) §5).
- **USB:** the OTG DWC2 works as a peripheral with a configfs ACM + mass storage gadget; the core has 972 words of FIFO RAM
  ([`../soc/README.md`](../soc/README.md) §1.2).
- **Watchdog:** `dw_wdt` binds (it warns `No valid TOPs array specified` without `snps,watchdog-tops`) and keeps a watchdog
  armed by the loader fed.
- **PMIC buses:** with i2c0 and i2c2 enabled and no client nodes, the ACT8931 and the TPS65185 answer through `i2c-dev`; nothing
  writes them.
- **DDR at 396 MHz:** a mainline-based U-Boot SPL with the stock kernel's 396 MHz register set runs the RC2 and passes
  memory tests in U-Boot and in Linux under load ([`../soc/README.md`](../soc/README.md) §8.1). With FlashData's table the
  mainline system runs DDR at 300 MHz for its whole uptime (there is no DDR frequency driver).
- **CPLL after an EBC unload:** unloading an out-of-tree EBC driver module powers CPLL down (`CPLL_CON1` bit 13 set, read
  0x3043). A cores-only restart keeps the CRU state, so the next boot's SD clock, parented on CPLL during card
  identification, is dead and the card is not found. The kernel has to power the PLLs up at clock init and before a
  restart; with that, unload then restart came back 9 times out of 9.
- **E-Ink under DRAM load: the EBC's AHB fetch clock.** With an out-of-tree EBC driver, a CPU loop that streams memory (`dd
  bs=4M`, far beyond the L2) made the panel show grey noise or streaked bands on page turns, while every EBC scan completed
  all 38 frames and the driver's image was normal; with a 16 KiB buffer (L1-resident) the panel stayed crisp, so DRAM
  traffic is the trigger. The EBC fetches its images over AHB, clocked by `hclk_ebc` = `hclk_disp_pre` (CLKSEL_CON30,
  CRU+0xbc), which the mainline clock setup leaves at GPLL / 1 = **132 MHz** (stock: 256 MHz, GPLL 768 / 3; 320 MHz from
  CPLL after an Android boot). Raising it live to about 213 MHz (CPLL / 3) made all 14 page turns under the same load crisp,
  in two series; 132 MHz in the same boot gave garbage [CONFIRMED-device; starvation of the AHB fetch as the mechanism
  STRONG]. Not the cause: NoC QoS priorities (EBC port 0xF, LCDC1 0xF, CPU ports already 0;
  [`../soc/README.md`](../soc/README.md) §1.4), the AXI NIU clock `aclk_lcdc1_src` (132 → about 213 MHz), DDR 396 instead of
  300 MHz. A board kernel should set `hclk_disp_pre` to the stock 256 MHz, or at least well above `dclk_ebc` (160 MHz). A
  kernel that sets the stock bus clocks (GPLL 768 MHz, `hclk_disp_pre` 256 MHz) gave 14 of 14 loaded and 7 of 7 idle page
  turns crisp [CONFIRMED-device]. Register values: [`../soc/README.md`](../soc/README.md) §3.6.

## Summary

- **v7.2 has no line about the RK3026**: `grep -ril rk3026` over the tree is empty [CONFIRMED-src].
- **Out of tree it boots:** Mario Rugiero's RK3026 kernel, rebased onto v7.1.13 with twelve RC2 patches, runs on the RC2 from
  microSD with 2 CPUs, a USB console, mass storage, warm reboot and power-off (§0) [CONFIRMED-device].
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
| **USB controllers** | `dwc2` with `rockchip,rk3066-usb` | DTS only: OTG `dr_mode = "peripheral"` (ACM + mass storage gadget work [CONFIRMED-device]), the second DWC2 as host for Wi-Fi; FIFO sizes within 972 words, e.g. 275 / 16 / 256 128 128 64 64 32 | — |
| **SMP** | `rockchip,rk3036-smp` (no PMU; SCU + trampoline in `smp-sram` on a Cortex-A9) | DTS (`enable-method`, `resets` in `cpu@1`, `smp-sram@0`, `scu`) plus two `platsmp.c` changes, tested on the RC2 (§0): a core reset pulse once the trampoline is in place (the RK3026 assert write restarts the core), and the IMEM remap set only around that pulse [CONFIRMED-device] | S |
| **Power domains** | `pm-domains.c` type `DOMAIN_RK3036` (idle requests only) | own table: RK3026 req bits 8–13, ack 16–21, idle 22–27; domain-to-bit mapping [VERIFY]; not needed for a first boot | S |
| **SAR-ADC** | `rockchip,saradc`: 3 channels | the stock ok/menu ADC keys read channel 3, but the datasheet says 2 channels on RK3026: read channel 3 on the device first [VERIFY]; only matters if those keys exist on V1.73 | S |
| **eFuse** | `rockchip,rk3066a-efuse`: address field shifted by 6 | RK3026 shifts by 8; `rk3066a` would read the wrong bytes. Only needed for the chip version (4 on the RC2) | S |
| **dw_mmc (SD)** | `rockchip,rk2928-dw-mshc` (no phase clocks) | DTS only; no UHS on the RC2. Not the `rk3288` type: the RK3026 controller has no internal / 2, and with that type the card ran at twice the requested clock and failed with CRC errors ([`../soc/README.md`](../soc/README.md) §3.7) [CONFIRMED-device] | — |
| **PWM, SPI, DMA, UART, timer, GPIO** | `pwm-rockchip` (`rk2928`, no polarity), `spi-rockchip`, `pl330`, `dw-apb-uart`, `rockchip,rk3036-timer`, `gpio-rockchip` | DTS only (the frontlight is active high, no polarity needed). The Cortex-A9 global timer and TWD PPIs are `IRQ_TYPE_EDGE_RISING` [CONFIRMED-device] | — |
| **Watchdog** | `snps,dw-wdt` | DTS; works on the RC2, its reset restarts through the BootROM with DDR kept [CONFIRMED-device]; it is a global reset that clears GPIO1, so on battery it would drop the power hold ([`../soc/README.md`](../soc/README.md) §4.5) [STRONG] | — |
| **Reboot flags** | `syscon-reboot-mode` (as `rk3036.dtsi`, offset 0x1d8) | DTS: `mode-bootloader = <BOOT_BL_DOWNLOAD>` (the RC2 loader knows LOADER and RECOVER only), `mode-recovery`; mainline's `mode-normal` 0x5242C300 (stock writes 0) is an unknown value to the stock loader and boots normally [STRONG, loader code] | S |
| **Power-off, restart** | `gpio-poweroff`, ACT8931 MSTROFF via `system-power-controller`; restart via `GLB_SRST_FST` in the clock driver (Mario's `clk-rk3026.c` uses `GLB_SRST_SND`) | power-off: `gpio-poweroff` on GPIO1_A2, active low, works on battery with no PMIC write [CONFIRMED-device]; MSTROFF untested [VERIFY]. Restart: SND and FST both reach the BootROM once the IMEM remap is off and the loader invalidates L1 [CONFIRMED-device]; both reset GPIO1 and drop the power hold, so on battery they power the book off (tried with SND); a cores-only reset restarts it [CONFIRMED-device] | S |
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
[CONFIRMED-src]. The RK3128 clock driver already describes `DCLK_EBC`/`HCLK_EBC`, but no EBC node or driver exists. The RK3128 EBC is the
same IP as the RK3026's (same registers, interrupt bits, base and IRQ in ONYX's RK3128 kernels; RK3036 has no EBC), so one
driver can serve both ([onyx-rc2-ebc `driver/other-controllers.md`](https://github.com/hsw/onyx-rc2-ebc/blob/main/driver/other-controllers.md) §8). The
register-level description of the RK3026 EBC and a sketch of a minimal in-kernel driver are in
[onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc) (`driver/registers.md`, `driver/new-driver.md`). Its clock tree must keep
`hclk_ebc` (`hclk_disp_pre`) well above `dclk_ebc` (§0, "E-Ink under DRAM load").

- **Precedent: `repaper`.** `drivers/gpu/drm/tiny/repaper.c` (in mainline since 2017, GPL-2.0+) drives Pervasive Displays
  e-paper panels over SPI as a plain DRM driver with **no new UAPI**: a `drm_simple_display_pipe`, XRGB8888 converted to 1 bit
  in the kernel (`drm_fb_xrgb8888_to_mono`), fbdev emulation, the update policy inside the driver (full-screen updates only),
  and the panel temperature from a thermal zone named in the DT (`pervasive,thermal-zone`) [CONFIRMED-src]. A first RK3026 EBC
  series can take the same shape (full GC16 updates, fbdev for existing programs, temperature from the TPS65185 thermal zone) and
  leave the update-mode property to a later series.
- **Interfaces still missing** for a SoC E-Ink controller: an update-mode property on the plane, a defined meaning of the commit
  event as "update finished on the panel", a simple LUT-firmware format, a binding for the EBC and one for E Ink panels (timings,
  `vcom`/rail supplies, thermal zone, size). The image buffer (`DRM_FORMAT_R4`/`R8`) and the update area (`FB_DAMAGE_CLIPS`)
  already exist [CONFIRMED-src]. The Kindle's EPDC driver has the completion part as an ioctl: `MXCFB_WAIT_FOR_UPDATE_COMPLETE`
  wakes when the update's LUT has finished on the panel [CONFIRMED-src].
- **Waveform conversion outside the kernel has an open example:** [epdiy](https://github.com/vroland/epdiy) (LGPL-3.0) turns a
  `.wbf` into tables with its fork of inkwave (WBF → JSON) and `scripts/waveform_hdrgen.py` (JSON → a C header per mode and
  temperature range). The same split fits the EBC: a userspace tool (for the RC2 file, the decoder in
  [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform)) writes plain LUT tables that the kernel loads with
  `request_firmware()`. The Kindle Paperwhite 3 does exactly this: its firmware ships no waveform file. At boot
  `/etc/upstart/display` reads the panel's own WBF from the panel flash (`/proc/eink/panel/waveform/data`), converts it in
  userspace (`parse_waveform`) and caches the result; udev serves it to the driver's `request_firmware()`, and the kernel never
  parses a WBF stream [CONFIRMED in the 5.16.2.1.1 update image and kernel source].
- **Panel data in the panel:** the RC2's panel SPI flash uses E Ink's generic layout, which the Kindle Paperwhite 3 kernel reads
  too ([`../panel-flash/README.md`](../panel-flash/README.md)), so the passport (VCOM, part number, waveform name) can be described
  once as an nvmem layout for any E Ink panel. The TPS65185 driver has no binding for the power-up sequence registers that stock
  sets ([`../panel/README.md`](../panel/README.md) §3).
- **Two traps before the first good picture:** without `GRF_LVDS_CON0` bit 0 the EBC data lines never reach the panel pads
  ([`../soc/README.md`](../soc/README.md) §4, [onyx-rc2-ebc `driver/registers.md`](https://github.com/hsw/onyx-rc2-ebc/blob/main/driver/registers.md));
  the waveform is made for 85 Hz while stock drives the panel at 83.64 Hz ([`../panel/README.md`](../panel/README.md) §1).

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
