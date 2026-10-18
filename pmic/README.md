# PMIC and fuel-gauge registers read on the device

On 2026-10-11 the registers of the ACT8931 (system PMIC), the TPS65185 (E-Ink PMIC) and the CW2015 (fuel gauge) were read on a
running RC2, one byte per I²C transfer, with nothing written. State at read time: the stock 3.0.36+ kernel (with two small fixes in its EBC driver), Android, display idle
after the last update, USB cable attached, Wi-Fi off, **no suspend since boot**. Side effects of reading: the TPS65185 INT1/INT2
and the ACT8931 0x78 status bits clear on read; neither driver uses them on the RC2.

This page decodes those values and compares them with what the stock kernel reports and with what a mainline device tree should
say. The wiring of the rails is in [`../board/README.md`](../board/README.md) §2; the SoC side (pins, GRF, clocks) in
[`../soc/README.md`](../soc/README.md); the mainline drivers in [`../mainline/README.md`](../mainline/README.md).

References: **DS** = the Active-Semi ACT8931 datasheet, Rev 3 (2012-11-29), printed page numbers. Qorvo's last edition, Rev D
(January 2020, 46 pp.), is the same document re-templated: a text and register-map diff finds no technical change (same
register map, defaults, ordering table, electrical tables and sequencing text), and it has no revision history or errata
section; its page numbers are shifted. **ML** = mainline Linux v7.2;
**RY** = [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources).

Marks: **[CONFIRMED-device]** = read on the device; **[CONFIRMED-src]** = read in the datasheet or in a source tree;
**[STRONG]**, **[VERIFY]**, **[GUESS]** as in the [top README](../README.md#confidence-marks).

## Summary

- **The stock kernel's ACT8931 voltage table is off by one entry above 2.8 V.** It has 65 entries with an extra **2850 mV** after
  2800; the datasheet and mainline have 64. Every rail the stock kernel sets **at or above 2.85 V runs 100 mV higher than the
  kernel reports**: VCCIO (DCDC1) is **3.4 V**, not 3.3 V (3.5 V with Wi-Fi on, not 3.4 V); the LDOs are **3.1 V**, not 3.0 V.
  DDR (1.35 V) and ARM (1.40 V) are below 2.4 V, where both tables agree, and are unaffected [CONFIRMED-device on the registers].
- **VSET1 = VSET2** on all three DCDCs; **VSEL = GPIO0_A3 is high**, so the live bank is **VSET2**.
- **LDO2 and LDO4 are off at idle.** LDO4 is the EPD logic supply, switched by the EBC driver per update.
- **ACT8931 behaviour (§1.7):** ON bits are edge-triggered; 0x78 status bits clear on read; the registers survive reboots and
  power-off on battery, so the next OS sees what the last one wrote (DCDC1 0x3b after Android); nIRQ reaches no readable
  GPIO; the part is most likely the ACT8931AQJ633-T; datasheet Rev D (2020) is technically Rev 3 (2012).
- **TPS65185 answers on I²C while LDO4 is off**, so its VIN is not LDO4.
- **TPS65185**: r1p2, VCOM 1.66 V, the stock power-up sequence UPSEQ0/1 = 0x39/0x11 (not TI's defaults), PG = 0 with the rails off.
- **CW2015**: the battery profile in the chip is byte-identical to the 64-byte profile in the stock kernel Image, so a mainline
  driver given that profile will not reload it.

## 1. ACT8931 (i2c0 0x5b)

### 1.1 Voltage curve (DS Table 6, p. 32)

A 6-bit selector n gives:

| n | Voltage |
|---|---|
| 0–23 | 0.600 + 0.025·n V (0.600 … 1.175 V) |
| 24–47 | 1.200 + 0.050·(n − 24) V (1.20 … 2.35 V) |
| 48–63 | 2.400 + 0.100·(n − 48) V (2.4 … 3.9 V) |

Mainline `act8865_voltage_ranges` (`drivers/regulator/act8865-regulator.c`) is exactly this curve [CONFIRMED-src]. The stock
kernel (and RY `act8931.c`) uses a 65-entry table with an extra 2850 after 2800 (in the stock Image at 0xc08e7944 and 0xc08e7a48)
[CONFIRMED-src + disassembly]. The datasheet's own defaults confirm the 64-entry curve: the LDO default 0x36 = 54 is listed as
3.0 V in the ordering information (p. 4, p. 9); the stock table would call 54 "2.9 V".

### 1.2 Registers

| Reg | Value | Decoded | Stock kernel says |
|---|---|---|---|
| 0x00 SYS | 0x57 | TRST 0 (260 ms reset), nSYSMODE 1 (interrupt, no auto shutdown), nSYSLEVMSK 0, **nSYSSTAT 1**, SYSLEV 0111 = 3.0 V. VSYS is ≥ 4.19 V here, so nSYSSTAT = 1 means "above threshold"; the DS sentence is inverted relative to the bit name [STRONG] | — |
| 0x01 SYS | 0x01 | MSTROFF 0; SCRATCH = 1 (the stock probe sets bit 0) | — |
| 0x20 / 0x21 | 0x3A / 0x3A | DCDC1 VSET1 = VSET2 = 58 → **3.40 V** | `act_dcdc1` 3.3 V |
| 0x22 | 0x81 | ON, MODE 0 (power-save at light load), DELAY 0, OK 1 | |
| 0x30 / 0x31 | 0x1B / 0x1B | DCDC2 = 27 → **1.35 V** (DDR) | 1.35 V |
| 0x32 | 0x85 | ON, DELAY 1, OK 1 | |
| 0x40 / 0x41 | 0x1C / 0x1C | DCDC3 = 28 → **1.40 V** (ARM at 912 MHz) | 1.40 V |
| 0x42 | 0x85 | ON, DELAY 1, OK 1 | |
| 0x50 / 0x51 | 0x37 / 0xC1 | LDO1 = 55 → **3.10 V**; ON, DIS 1 | 3.0 V, enabled (touch) |
| 0x54 / 0x55 | 0x37 / 0x41 | LDO2 3.10 V; **off** | 3.0 V, disabled |
| 0x60 / 0x61 | 0x37 / 0xC1 | LDO3 3.10 V; ON (microSD, codec) | 3.0 V, enabled |
| 0x64 / 0x65 | 0x37 / 0x41 | LDO4 3.10 V; **off** (EPD logic, switched per update) | 3.0 V, disabled |
| 0x70 | 0xFF | reserved (DS default 0x50) | |
| 0x71 | 0x28 | SUSCHG 0 (charging allowed), total timer 5 h, precondition timer 80 min, OVP 6.6 V | |
| 0x78 | 0x07 | interrupt status bits 7:4 (TIMRSTAT, TEMPSTAT, INSTAT, CHGSTAT) 0, **cleared by every read** (DS charger sections); plain status bits 3:0: **TEMPDAT 1** (battery temperature valid), **INDAT 1** (valid CHGIN), **CHGDAT 1** (end of charge) | `rk-usb` online, battery full 100 % |
| 0x79 | 0x00 | all charger interrupts disabled (the RY driver has them under `#if 0`) | |
| 0x7A | 0xDD | **CSTATE (bits 5:4) = 01** = end of charge (§1.5); **ACINSTAT 0** (ACIN below 1.2 V → USB mode); bits 7:6, 3:2 and 0 read 1 although the DS calls them reserved/0 | |
| 0x0B | **0x00** | not in the DS (ACT8865's unlock register); answers 0, unlike the absent registers | |
| 0x24/0x34/0x44/0x52/0x56/0x62/0x66 | 0xFF each | ACT8865's `*_SUS` registers: not implemented, read as all ones | |

The OK bit (bit 0 of each control register) reads 1 on LDO2 and LDO4 although they are off; do not use it as an enable status.

### 1.3 What stock believes and what the chip does

| Rail | Stock prints | Selector | Real (DS) |
|---|---|---|---|
| DCDC1 VCCIO (pcb V1.73) | 3.3 V | 58 | **3.4 V** |
| DCDC1 with Wi-Fi on | 3.4 V | 59 | **3.5 V** |
| DCDC1 in suspend (write 0x20 = 0x36) | 2.9 V | 54 | **3.0 V** |
| LDO1 touch (`setup vcc_tp to 3.0V`), LDO3 SD, LDO4 EPD logic | 3.0 V | 55 | **3.1 V** |
| LDO1 at power-up, LDO2 in suspend | 2.8 V | 52 | 2.8 V |
| DCDC2 DDR | 1.35 V | 27 | 1.35 V |
| DCDC2 in suspend (0x30 = 0x19) | 1.25 V | 25 | 1.25 V |
| DCDC3 ARM: 1.2 / 1.40 / suspend 0.85 V | | 24 / 28 / 10 | the same |

The suspend rows are the raw writes listed in [`../board/README.md`](../board/README.md) §2, now decoded with the datasheet curve.
The values in the board-file tables are what stock *believes*; this table is what the chip *outputs*. None of this needs a
multimeter: the register contents and the datasheet curve are enough.

### 1.4 VSEL and the two banks

- DS: VSEL low selects VSET1 (0x20/0x30/0x40), VSEL high selects VSET2 (0x21/0x31/0x41) (pp. 10–11, 31); in the reference
  connection to an RK2928 VSEL goes to a SoC GPIO (Table 4, p. 26) [CONFIRMED-src].
- On the RC2, **GPIO0_A3 (`pmu_gpio`) is an output driven high** while the system runs [CONFIRMED-device], and the ONYX SRAM
  suspend code drives it low ([`../power/README.md`](../power/README.md) §1.2).
- Before suspend stock writes the sleep values (DCDC3 0.85 V, DDR 1.25 V) into **VSET1** while the CPU still runs at 912 MHz and
  never restores them. That would crash the CPU if VSET1 were live; the device does not crash, so the live bank is VSET2 and
  **GPIO0_A3 is VSEL** [STRONG, was GUESS].
- In this readback VSET1 = VSET2 on all DCDCs (3.40 / 1.35 / 1.40 V) because the device had not been in stock suspend since boot.
  After any stock suspend, VSET1 holds 0.85 V (ARM) and 1.25 V (DDR) until the next cold start.
- How GPIO0_A3 behaves across a SoC reset (internal pull) is [VERIFY]; a warm reboot into another kernel after Android works in
  practice [STRONG].

### 1.5 Charger (APCH)

- 0x78 INDAT = 1 with the USB cable attached [CONFIRMED-device]; the reading without the cable is still missing [VERIFY]. If CHGIN
  is VBUS (the RC2 charges only from USB [STRONG]), INDAT is the best "online" signal on this board.
- CSTATE: DS Table 10 (p. 38) gives 11 precondition, 10 fast charge / top-off, 01 end of charge, 00 suspended / disabled /
  fault, and the text puts CSTATE[1:0] at 0x7A bits 5:4 (p. 14). The register-map row on p. 9 lists the two names the other
  way round (CSTATE[0] at bit 5). The RC2's 0xDD read as bits 5:4 = 01 = end of charge, which matches CHGDAT = 1 and the
  full battery, only in the text order: read bit 5 as CSTATE[1] [STRONG].
- ACINSTAT = 0: USB mode (450/90 mA by CHGLEV). On the SoC side GPIO1_B2 is low and GPIO1_A1 high (the charge-current selects of
  the board file); that GPIO1_B2 drives ACIN is a [GUESS].

### 1.6 For a mainline device tree

- **`active-semi,vsel-high` is mandatory.** Without it the `act8865` driver programs VSET1, the sleep bank: after a stock suspend
  cpufreq would "set" 1.40 V while the CPU actually keeps 0.85 V. Keep GPIO0_A3 as a `gpio-hog` `output-high`; the driver does not
  touch VSEL.
- **State the real voltages, if any**: DCDC1 3.4 V, DCDC2 1.35 V, DCDC3 1.40 V, LDO1/LDO3 3.1 V. Writing stock's numbers
  ("3.3 V" / "3.0 V") would lower VCCIO and the LDOs by 100 mV. With `regulator-min-microvolt == regulator-max-microvolt` the
  kernel applies the value at boot, so do not set voltages before checking the registers on the first boot (regmap debugfs).
- **DCDC1–3 need `regulator-always-on` and `regulator-boot-on`.** A regulator described in the DTS without `always-on` and without
  consumers is switched off by the kernel about 30 s after boot (`regulator_late_cleanup`); for DDR that is fatal. MODE 0 is the
  stock state.
- **LDO4 must be a consumer-controlled supply of the EBC/panel node, not `always-on`**: stock keeps it off between updates. LDO1
  (touch) and LDO3 (SD + codec) are on; LDO2 is unused.
- **Do not use `compatible = "active-semi,act8865"` as a stand-in.** The ACT8865 type writes 0xEF to the undocumented register
  0x0B at the end of every probe, and with `regulator-state-mem` it writes the `*_SUS` registers, which the ACT8931 does not have.
  The regulator map is otherwise identical bit for bit (VSET1/VSET2/CTRL addresses, the voltage curve, ON = bit 7, DIS, MODE,
  MSTROFF). The right fix is an `active-semi,act8931` type in the same driver: the ACT8865 regulator tables without the 0x0B write
  and without `set_suspend_*`, plus a `power_supply` for the charger (online = 0x78 bit 1, status from CSTATE), modelled on the
  ACT8600 charger code that already lives in that driver. See [`../mainline/README.md`](../mainline/README.md).
- `system-power-controller` (MSTROFF, 0x01 bit 5) is documented and is what stock does at power-off on battery, but on the RC2
  only the power-hold path has been tested: GPIO1_A2 low switches the book off on battery with no PMIC write, and with USB
  power present the board stays up [CONFIRMED, [`../power/README.md`](../power/README.md) §5]. So a `gpio-poweroff` on GPIO1_A2
  (active low) is enough; MSTROFF stays untested [VERIFY].

### 1.7 Behaviour a driver has to know

- **The ON bits are edge-triggered** (DS p. 31 for the step-down regulators, p. 33 for the LDOs): "The regulator accept
  rising or falling edge of ON[ ] bit as on/off signal"; to enable, clear ON and then set it, to disable, set it and then
  clear it [CONFIRMED-src]. A read of ON therefore shows the last edge written, not the output state, and a
  read-modify-write that finds ON already set enables nothing. The OK bit is no substitute on the LDOs (§1.2).
- **0x78 bits 7:4 clear on every read** (TIMRSTAT, TEMPSTAT, INSTAT, CHGSTAT: "automatically cleared to 0 upon reading",
  DS charger sections) [CONFIRMED-src]. With 0x79 = 0 nothing uses them; if an interrupt consumer is ever added, every read of
  0x78 is also its acknowledge. The vendor's SRAM code reads 0x78 for INDAT too (RY `arch/arm/mach-rk2928/i2c_sram.c`,
  `act8931_dc_det`).
- **The registers keep their values until the power is gone.** DS p. 9, note 2: bits return to their defaults only when the
  input power is removed or falls below the system UVLO (VSYS 2.2–2.65 V); a battery-fed book never gets there. What the
  last OS wrote is still in the chip in the next boot, after a warm reset and after a power-off alike: boots that followed
  stock Android read DCDC1 VSET1/VSET2 = **0x3b/0x3b** (3.5 V by the DS, stock's "3.4 V"), once VSET1 = **0x36** (stock's
  suspend value for the bank that is not live, 3.0 V by the DS) with VSET2 = 0x3b [CONFIRMED-device]. Stock writes 0x3b
  while the Wi-Fi/BT module is powered (§1.3; [`../board/README.md`](../board/README.md) §2) and 0x3a with it off, as in
  §1.2 [STRONG: the stock table and board code; a dump with Wi-Fi on is missing]; the DS default is 0x39 (3.3 V). Even
  3.5 V on VCCIO is inside the RK3026's range: DS V1.2 Table 8 (p. 51) VDDIO 2.97–3.63 V, Table 7 (p. 50) 3.63 V absolute
  maximum [CONFIRMED-src].
- **nIRQ is not wired to a readable SoC GPIO.** nIRQ is an open-drain output (DS p. 5, p. 27). With the charger-input
  interrupt armed (INCON and INDIS in 0x79, INSTAT in 0x78), the input levels of all four GPIO banks were sampled for
  600 s while the USB cable was pulled and plugged again; the charger saw 5 input events (CSTATE and INSTAT changed), no
  input pin moved [STRONG, device test]. Either nIRQ is not connected or it goes to a pin without a pull-up. The stock
  kernel requests no ACT8931 interrupt either ([`../board/README.md`](../board/README.md) §2); a driver has to poll.
- **Which part.** Both datasheet editions list one ordering code, **ACT8931AQJ633-T** (TQFN55-40, "Advanced PMU for
  Rockchip RK2928/RK2926"), and the register-map defaults are that part's. The RC2's OTP-only sequencing bits match it
  (DELAY 0 on REG1 and the LDOs, 1 on REG2/REG3: CTRL 0x81, 0x85, 0x85, 0xC1/0x41), and stock relies on the QJ6##
  behaviour "MSTROFF … automatically cleared when … a valid CHGIN voltage is detected" (p. 10) [STRONG]. The top mark is
  unread: this RC2 has not been opened, and the PMIC in the public board photos
  ([`../device/README.md`](../device/README.md#board-revision-and-chip-markings)) shows no readable mark.

## 2. TPS65185 (i2c2 0x68; WAKEUP high)

Field names as in mainline `drivers/regulator/tps65185.c` and RY `rk_epd/epdpower/tps65185.c`.

| Reg | Value | Decoded |
|---|---|---|
| 0x00 TMST_VALUE | 0x18 | 24 °C |
| 0x01 ENABLE | 0x20 | ACTIVE 0, STANDBY 0, **V3P3_EN 1** (the 3.3 V switch stays on at idle), VCOM_EN 0, VDDH/VPOS/VEE/VNEG 0 |
| 0x02 VADJ | 0x03 | VPOS/VNEG = ±15.0 V |
| 0x03 / 0x04 VCOM1 / VCOM2 | 0xA6 / 0x00 | **VCOM = 166 × 10 mV = 1.66 V** (stock log `vcomvalue = 166`; the panel flash says −2.06 V, see the top README) |
| 0x05 INT_EN1 | 0x7F | all but bit 7 enabled |
| 0x06 INT_EN2 | 0xFE | bit 0 (end of temperature conversion) disabled; mainline enables it at probe |
| 0x07 / 0x08 INT1 / INT2 | 0x00 / 0x01 | INT2 bit 0 = conversion end latched (cleared by this read) |
| 0x09 UPSEQ0 | **0x39** | strobe order VDDH 1, VNEG 2, VEE 3, VPOS 4. RY writes 0xE4 |
| 0x0A UPSEQ1 | **0x11** | delays 6 / 3 / 6 / 3 ms. RY writes 0 |
| 0x0B / 0x0C DWNSEQ0 / 1 | 0x00 / 0x00 | all rails off at strobe 1, 6 ms each; the same as RY's init (which never sets DWNSEQ0) |
| 0x0D TMST1 | 0x20 | CONV_END 1 |
| 0x0E TMST2 | 0x78 | hot/cold thresholds (default) |
| 0x0F PG | **0x00** | no rail in power-good (rails off) |
| 0x10 REVID | 0x65 | **TPS65185 r1p2** (`detected device with ID=65 (TPS65185r1p2)` in the log) |

For a mainline device tree:
- **WAKEUP (GPIO3_C1) is held high by stock too**, so the chip stays awake and readable at idle; the mainline driver's
  "high forever" matches stock.
- **PG is readable at idle**, so polling the PG register (0x0F, mask 0xFA = all rails good, as stock does) instead of a
  `pwr-good-gpios` GPIO works on this board [CONFIRMED-device for readability]. Stock requests no PWR_GOOD or nINT GPIO at all;
  whether PWR_GOOD is wired to a SoC pin is still [VERIFY by board]. Mainline currently **requires** `pwr-good-gpios` (code and
  binding); see [`../mainline/README.md`](../mainline/README.md).
- **VIN is not LDO4**: the chip answers every register while LDO4 is off, so `vin-supply` is an always-on rail (VSYS/battery,
  a `regulator-fixed` without a GPIO) [STRONG]. LDO4 may feed the panel logic or VIN3P3 [GUESS]; it stays under the EBC driver.
- **The power-up sequence is stock-written.** Mainline writes none of UPSEQ0/1, DWNSEQ0/1 and has no binding for them; after a
  WAKEUP-low reset the chip reloads TI's defaults, so a mainline kernel would power the panel with TI's order and delays rather than
  stock's 0x39/0x11 [VERIFY which one the panel needs].
- VCOM: mainline reads 166 as 1.66 V and does not touch the EEPROM; leave `regulator-min/max-microvolt` off the `vcom` node so the
  kernel does not change it.
- GPIO2_C0 (VCOM_CTRL) is a GPIO output **high** at idle; during updates stock switches it to the EBC_VCOM function. Giving it to
  the TPS65185 driver as `vcom-ctrl-gpios` would take it away from the EBC; either works, it is a choice for the EBC driver.

## 3. CW2015 (i2c0 0x62)

| Reg | Value | Decoded (field names of mainline `cw2015_battery.c`) |
|---|---|---|
| 0x00 VERSION | 0x6F | |
| 0x02–0x03 VCELL | 0x35B5 | 4189 mV by the mainline formula; sysfs 4.190 V |
| 0x04–0x05 SOC | 0x64 0x00 | 100.0 % |
| 0x06–0x07 RRT_ALERT | 0x1FFF | ALRT 0; remaining time 8191 min (= not discharging) |
| 0x08 CONFIG | 0x02 | **ATHD 0 %**, **UFG 1** (profile loaded) |
| 0x0A MODE | 0x00 | normal |
| 0x10–0x4F | 64 bytes | the battery profile: **byte-identical** to the 64-byte profile in the stock kernel Image (0xc0a71628, the only occurrence) |

With this state the mainline driver, given the Image's profile in `cellwise,battery-profile`, finds a matching profile and does
not reload it or reset the gauge; ATHD 0 also keeps it away from the mainline ATHD bug (see [`../mainline/README.md`](../mainline/README.md))
[CONFIRMED-device + source]. The profile bytes are not reproduced here; take them from your own kernel Image or chip.

## 4. Still [VERIFY]

- ACT8931 0x78 without the cable (INDAT = 0?), what register 0x0B really is, the chip's top mark (OTP and date code), the
  real DCDC voltages with a meter.
- GPIO0_A3 across a SoC reset.
- TPS65185 PWR_GOOD and nINT wiring; which power-up sequence the ED060KD1 needs.
