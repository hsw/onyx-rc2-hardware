# Power management in the stock RC2 kernel and its 4.2 userspace

Static analysis, 2026-10-08. Target: the stock RC2 kernel Image (Linux 3.0.36+, built 2017-11-07, firmware 1.8.2, sha256
`47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af`, not public; raw ARM, VA = file offset + 0xc0408000), symbols
recovered from the Image's own kallsyms table (`../kernel/extract_kallsyms.py`), and the stock 4.2 `/system`. Nothing was run on the
device for this pass; device evidence comes from earlier captures on the same unit. All addresses refer to that 2017-11-07 kernel;
see [`tools/README.md`](tools/README.md) for the public 1.9.1 kernel.

Confidence marks:
- [CONFIRMED]: read directly in the objdump listing (kernel, ARM) or in the Thumb listing / decompiled Java (userspace) at the given address, or seen in a device log.
- [STRONG]: an inference from several confirmed facts.
- [VERIFY]: not proven; needs the device.
- [GUESS]: an estimate.

Public references:
- **RY** = [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources) (RK3026 E-Ink SDK);
- **PUB** = [linux-rockchip/linux-rockchip](https://github.com/linux-rockchip/linux-rockchip) `mirror/stable-3.0` (RK stable-3.0, 2014).

## Summary

- **Correction of the starting premise.** Most of this code is **public in RY**:
  - `arch/arm/mach-rk3026/pm.c`: `rk3026_pm_*`, `rk_soc_pm_ctr_*`, `rk_soc_pm_helps_*`, `pm_pll_pwr_up`, the SRAM suspend;
  - `arch/arm/mach-rk3026/i2c_sram.c`;
  - `kernel/power/irqwake.c`: `pm_irqwake_*`, `suspend_irqwake_set`, `suspend_valid_idle_mem`;
  - `kernel/power/idle_control.c`: `idle_init`, `/proc/idle`;
  - `kernel/power/suspend.c` with `[PM_SUSPEND_IDLE] = "idle"`;
  - `kernel/power/suspend_time.c`;
  - `drivers/regulator/charge-regulater-adc.c`: `act8931_charge_*`;
  - `plat-rk/ddr_freq.c`.

  [`../kernel/linux-rockchip-3.0-vs-stock.md`](../kernel/linux-rockchip-3.0-vs-stock.md) compared against PUB only and so listed `rk3026_pm_*` and `idle_init` as "without source". The stock
  kernel is RY plus a few ONYX edits. The real ONYX/stock-only deltas are listed below, each with its address.
- **What "idle" is.** It is a **full deep-sleep suspend entered with the screen on**:
  - `/sys/power/state` accepts it: `pm_states[] = {on, standby, idle, mem}`, and `.valid = suspend_valid_idle_mem` accepts 2 and 3.
    `cat /sys/power/state` prints `idle mem` on the device [CONFIRMED].
  - It goes through the same earlysuspend → wakelock → `pm_suspend()` path as "mem", with freezer, device suspend, CPU1 offline, APLL/CPLL/DPLL
    off, DDR self-refresh and WFI in SRAM [CONFIRMED].
  - It differs from "mem" in only four ways:
    1. **Extra wake IRQs**: the cyttsp4 touch IRQ 160 and `adc_irq_io` 235, armed by the ONYX-modified `pm_irqwake_enable`.
    2. **Idle-aware drivers keep running** (they check `get_suspend_state()`): the touch controller is not put to sleep, the frontlight stays
       on, the TPS65185 pins are not dropped, and the keypad early-suspend state is not reset.
    3. **The touch supply stays on**: the board's SRAM routine turns ACT8931 LDO1 (`act_ldo1`, touch 3.0 V) off and LDO2 on only for
       "mem" (registers 0x51/0x55; rail names from [`../board/README.md`](../board/README.md)).
    4. No 1 ms post-WFI delay.

  The SoC deep-sleep state itself is the same in both modes. Stock idle suspend is therefore as deep as screen-off sleep, and
  touch, page keys or Power wake it [STRONG].
- **`/proc/idle` is a constant capability flag**: `idle_proc_read` stores 1 before printing it, so reads always return "1"; writes
  have no effect. Nobody needs to write it [CONFIRMED].
- **Stock userspace chain** [CONFIRMED]:
  1. ONYX PMS drops the "screen on" and "user activity" terms from `isCpuNeededLocked()`, so the kernel `PowerManagerService` wakelock is
     released whenever no app holds a wakelock.
  2. 3 s after the last user activity (`persist.sys.idle-delay`, default 3000) `mIdleTimer` calls `nativeIdle()`.
  3. That calls `autosuspend_idle(gScreenOn)`. libsuspend checks `/proc/idle` and `sys.wifi.noidle`, then writes "idle" (screen on) or
     "mem" (screen off).
  4. Any user activity → `resetIdle(true)` → `nativeWake()` → "on".
  5. While suspended, the screen-off timeout and auto power-off are carried by RTC alarms (`user_timeout_action`, `auto_poweroff_action`).

  **Wi-Fi on disables idle suspend** (`WifiStateMachine.setWifiEnabled` sets `sys.wifi.noidle=1` and takes wakelocks).
- **Deltas from RY** in the stock suspend path:
  - (a) GPLL is kept running in suspend; RY powers it down. CLKSEL10 is saved but never restored. [CONFIRMED]
  - (b) `rk3026_sram_suspend` has no `state == MEM` gates; RY skips volt/UART/clock gating for idle. [CONFIRMED]
  - (c) The board's SRAM `rk30_suspend_voltage_set` does not lower ARM or logic voltage. It only switches ACT8931 LDO1 (touch) off and LDO2 on for "mem". [CONFIRMED]
  - (d) `pm_irqwake_*` is ONYX: pcb-dependent touch IRQ and `adc_irq_io`. [CONFIRMED]
  - (e) `request_suspend_state` lacks RY's "mem → idle refused" guard. [CONFIRMED]
  - (f) ddrfreq registers no early-suspend handler, so the 198 MHz "suspend" DDR rate is never used. [CONFIRMED]
- **`rk_suspend_ctr_bits`, `rk_suspend_arm_volt` and `rk_suspend_logic_volt`** are not on the loader cmdline, and the ctr bits could not work
  anyway: `rk_soc_pm_ctr_bits_prepare` (copy to SRAM) has no caller, so the SRAM copy stays 0 and every power-down step always runs
  [CONFIRMED].
- **Charger/battery:**
  - `act8931_charge_*` is a GPIO-less stub on RC2 (both GPIOs −1). No kernel code selects the charge current.
  - Battery-low comes from the CW2015 ALRT pin at **ATHD = 0 %**. The ONYX handler takes a permanent wakelock and injects KEY_WAKEUP
    when not charging. The AOSP BatteryService then shuts down at level 0.
  - The ONYX PowerManagerService 3-hour `checkBatteryLow` (≤ 3450 mV) reads `/sys/class/power_supply/battery/voltage_now`, which does
    not exist on RC2 (`rk-bat`). It reads `0x7fffffff` and is dead [CONFIRMED].
  - `hym8563_disable_alarm` is an ONYX hook in `alarm_suspend`: if no Android alarm is queued, it clears the RTC AIE/TIE so a stale RTC
    alarm cannot wake the device. It is not related to auto power-off [CONFIRMED].

## 1. RK3026 suspend implementation (`mach-rk3026/pm.c` + SRAM)

### 1.1 Registration and entry

- `rk3026_pm_init` @0xc040db44 → `suspend_set_ops(0xc0a6e0e4)` [CONFIRMED]. The ops are:
  - `.valid = suspend_valid_idle_mem` (0xc04b04ac);
  - `.prepare = rk3026_pm_prepare` (`disable_hlt`);
  - `.enter = rk3026_pm_enter` (0xc045c764);
  - `.finish = rk3026_pm_finish` (`enable_hlt`).

  This equals RY with `CONFIG_IDLE=y`; stock has no `pm_set_vt_switch` call.
- `rk3026_pm_enter(state)` @0xc045c764. It stores `state` to `sram_pm_state` (0xfef01cd4) and prints `0`–`5` on the debug UART via
  `sram_printch` (SRAM 0xfef01288). It then does the following, each step gated by the SRAM ctr copy (always 0, §1.4) [CONFIRMED]:
  - **clk gating, first stage:** saves `CRU_CLKGATES_CON(0..9)` to 0xc0b71398…, applies the hold mask table at 0xc08c2bf8 (RY
    `clkgt_first_w_msk`), then ungates PCLK_GPIO0.
  - **PLL suspend** (differs from RY, [CONFIRMED]):
    - APLL: slow mode, CLKSEL0 = `0x3f1f0000`, CLKSEL1 = `0x737f0000` (dividers /1, CPU from APLL), `PLL_CON1 = 0x20002000` (power down).
    - CPLL: slow mode + power down.
    - **GPLL: only CLKSEL10 is written (`0x03000000` = PERI HCLK div field set to /1). GPLL stays locked and in normal mode.** RY also
      puts GPLL in slow mode and powers it down.
    - On resume CPLL is powered up only if it was up before. APLL is powered up, then CLKSEL1/CLKSEL0/mode are restored.
      **CLKSEL10 is saved (0xc0b713d4) but never restored**, so after the first suspend the PERI HCLK divider stays /1. The effect is
      [VERIFY]; on the device it has gone unnoticed.
  - `rk30_pwm_suspend_voltage_set` (0xc045f244, board file, empty `bx lr`) and `board_gpio_suspend`. The latter is the weak default
    `bx lr` @0xc045c718; no board override exists [CONFIRMED].
  - `interface_ctr_reg_pread` @0xc045c3b0 flushes caches and TLB and pre-touches SRAM, GRF, DDR PCTL/PHY, GPIO0–3 and I2C0. Same as RY.
  - `rk3026_suspend(state)` @0xc045c728 switches SP to SRAM 0xfef01ff8, `blx 0xfef013d0` (`rk3026_sram_suspend`), then restores SP.
  - Resume runs in reverse. At the end, `rk3026_pm_dump_irq` @0xc045c474 prints `wakeup irq: <GIC pending 32-63> <64-95> <96-127>`
    and `wakeup gpioN: <INT_STATUS>` for every GPIO bank whose GIC line (IRQ 68 + N) is pending.

### 1.2 SRAM code: where and how big

- `rk29_sram_init` @0xc040edd8 sets things up [CONFIRMED; dmesg prints "CPU SRAM: copied sram code from c0b6e000 to fef00010 - fef01b28"]:
  - `iotable_init(sram_io_desc)`. Two entries (0xc042bc98), same as RY `plat-rk/sram.c`:
    - VA 0xfef00000 → PA 0, 1 MiB, `MT_MEMORY` (cached alias);
    - VA 0xfea80000 → PA 0x10080000, 8 KiB, `MT_MEMORY_NONCACHED`.
  - Zeroes the SRAM.
  - Copies **code: 6936 B** (0x1b18) from LMA 0xc0b6e000 (Image file offset 0x766000) to 0xfef00010–0xfef01b28.
  - Copies **data: 492 B** (0x1ec) from LMA 0xc0b6fb18 (file offset 0x767b18) to 0xfef01b28–0xfef01d14.
  - `sram_log_dump` @0xc040edc4 only clears the SRAM log pointer at 0xfef01cf8.
- `tools/sram_extract.py` writes the blob and a labelled listing.
- Contents (labels from this analysis; names as in RY `pm.c`/`i2c_sram.c`/`mach-rk2928/ddr.c`):

  | SRAM VA | Function | Notes |
  |---|---|---|
  | 0xfef013d0 | `rk3026_sram_suspend(state)` | prints `5`/`6`/`7`; ddr_suspend; volt; uart; clk gating; core div; `dsb; wfi`; reverse [CONFIRMED] |
  | 0xfef00a4c / 0xfef00b80 | `ddr_suspend` / `ddr_resume` | DDR **self-refresh**, DPLL to slow mode and powered down (`CRU+0x14 = 0x20002000`); resume relocks DPLL [CONFIRMED-dis, same structure as RY `ddr.c`] |
  | 0xfef01364 / 0xfef0139c | `rk_pm_soc_sram_volt_suspend/resume` | → `rk30_suspend_voltage_set(1000000)` / `_resume(1100000)` + empty weak `rk30_pwm_logic_*`, `board_pmu_*` |
  | 0xfef011ec / 0xfef01214 | `…uart_suspend/resume` | GRF_UOC1_CON0 = 0x30000000 (UART pins off USB PHY) |
  | 0xfef01110 / 0xfef01194 | `…clk_gating/ungating` | gates everything except the `clkgt_sram_w_msk` hold set (DDR PHY, CPU bus, GRF, DDR ctl, PWM01, GPIO0–3, L2C); if all four GPIO PCLKs were already gated it also gates CLKGATE2 |
  | 0xfef01238 / 0xfef01264 | `…sys_clk_suspend/resume` | CLKSEL0 = `0x001f001f`: core = 24 MHz / 32 |
  | 0xfef017f0 / 0xfef01888 | `rk30_suspend_voltage_set/resume` (board, ACT8931 @0x5b over SRAM I2C0) | see §1.3 |
  | 0xfef0152c, 0xfef01584, 0xfef01740, 0xfef01794 | `sram_i2c_init/deinit/write/read` | |
  | 0xfef014f0 | ONYX pin helper | arg 0 (suspend): GPIO0_A3 low and GPIO2_B4 high; arg 1: the reverse. Runs in idle and mem. [`../board/README.md`](../board/README.md): GPIO0_A3 = `pmu_gpio`, an ACT8931 control pin, probably VSEL to the sleep set-points [STRONG pin, GUESS VSEL]; GPIO2_B4 = `lcd_d10` (EBC_SDCE2 pin), purpose [VERIFY] (the RC2 touch reset is GPIO0_D3) |
  | 0xfef01288, 0xfef019fc, 0xfef01a24 | `sram_printch/printascii/printhex` | debug UART |

  Data: 0xfef01cd0 = `rk_soc_pm_ctr_flags_sram` (0); 0xfef01cd4 = `sram_pm_state`; 0xfef01cec = ONYX flag (1, cleared by `onyx_pcb_ver_setup`
  for `pcb_ver=3`); 0xfef01ff8 = suspend stack top.

### 1.3 What is powered down, idle vs mem

| Step | idle (state 2) | mem (state 3) | Evidence |
|---|---|---|---|
| Freezer, `dpm_suspend`, `CPU1` offline, `syscore_suspend` | yes | yes | generic `suspend_devices_and_enter` [CONFIRMED] |
| Early-suspend handlers (`request_suspend_state(state != ON)`) | yes, but idle-aware drivers skip (§2.4) | yes | [CONFIRMED] |
| First-stage clock gating, APLL+CPLL off, CPU on 24 MHz | yes | yes | `rk3026_pm_enter` has no state test [CONFIRMED] |
| GPLL | **running** | **running** | [CONFIRMED] |
| DDR self-refresh + DPLL off | yes | yes | `rk3026_sram_suspend` has no state test [CONFIRMED] |
| SRAM clock gating, UART GRF, core /32 | yes | yes | stock differs from RY, which skips these for idle [CONFIRMED] |
| ARM/logic voltage | unchanged | unchanged | no write to ACT8931 DCDC registers; `pm_suspend_volt_seting` is a no-op without cmdline volts (it only prints "pmic set pm_suspend_volt:") [CONFIRMED] |
| ACT8931 LDO1 ctrl 0x51 ← 0x41 (**touch supply off**; read back, up to 4 tries), LDO2 ctrl 0x55 ← 0xe1 (on) | **no** | yes (LDO1 only if flag 0xfef01cec = 1, i.e. pcb ≠ 3; on V1.76 LDO1 feeds the Hall sensor) | `rk30_suspend_voltage_set` tests `sram_pm_state == 3` [CONFIRMED]. Resume: 0x55 ← 0x41, 0x51 ← 0xc1. Rails from [`../board/README.md`](../board/README.md) (LDO1 = `act_ldo1` touch; LDO2 = `act_ldo2`, disabled at runtime; RY's `CLK_SWITCH_TO_GND` comment says LDO2 is needed in sleep, purpose [VERIFY]) |
| Pin helper 0xfef014f0 | yes | yes | [CONFIRMED] |
| Post-WFI 1 ms delay | no | yes | `cmp r4,#3` @0xfef01454 [CONFIRMED] |
| Wake IRQs | mem set + touch 160 + adc_irq_io 235 | see §4 | `suspend_irqwake_set` [CONFIRMED] |

### 1.4 `rk_soc_pm_ctr` bits and the cmdline

- `early_param("rk_suspend_ctr_bits")` @0xc040dc80 stores into 0xc0b71390. It is in .bss, so the default is 0.
- `rk_soc_pm_ctr_bits_*` @0xc045c684…0xc045c6f0 are the RY helpers.
- The help table at 0xc0a6e108 (10 entries) defines these bits:

  | Bit | Name |
  |---|---|
  | 0 | NO_PD |
  | 1 | NO_CLK_GATING |
  | 2 | NO_PLL (implies NO_VOLT) |
  | 3 | NO_VOLT |
  | 5 | NO_GPIO |
  | 7 | NO_DDR |
  | 10 | NO_PMIC |
  | 24 | RET_DIRT |
  | 25 | SRAM_NO_WFI |
  | 26 | WAKE_UP_KEY |

  The code also tests these bits: 8 = NO_SYS_CLK and 9 = NO_UART [CONFIRMED].
- **All tests read the SRAM copy at 0xfef01cd0**. That copy is written only by `rk_soc_pm_ctr_bits_prepare`, which has **no caller**
  (same in RY rk3026). The cmdline value is therefore only printed [CONFIRMED]. RET_DIRT and WAKE_UP_KEY are implemented only in RY
  `mach-rk30/pm.c`, not for rk3026.
- `rk_suspend_arm_volt` / `rk_suspend_logic_volt` (0xc0b7138c / 0xc0b71388) feed `regulator_set_suspend_voltage("vdd_cpu"/"vdd_core")`
  in `pm_suspend_volt_seting` @0xc040dbcc. They are 0 by default.
- **Loader cmdline** (stock `parameter`, device dmesg; see [`../device/README.md`](../device/README.md)): `console=ttyFIQ0 … pcb_ver=2 onyx_emmc=1 bootver=… firmware_ver=5.0.0`.
  It has none of the three parameters [CONFIRMED].

## 2. `kernel/power` additions

### 2.1 States

- `pm_states[]` @0xc08c4be8 = `"on"`, `"standby"`, `"idle"`, `"mem"` (index 0–3) [CONFIRMED].
- `state_store` @0xc04ad8c8 is the RY/Android version: a matched state ≠ ON goes through `valid_state()` → `request_suspend_state()`.
  `state_show` lists the valid ones: `idle mem` [CONFIRMED, device log].
- `request_suspend_state` @0xc04afdc8: system_state guard, log `request_suspend_state: (%s -> %s)`, queues early_suspend/late_resume,
  stores `requested_suspend_state` (0xc0a8667c, default 3). **Stock has no RY guard "if requested == MEM && new != ON: return"**, so
  "mem → idle" is accepted [CONFIRMED]. Harmless: with SUSPEND_REQUESTED already set, only the target state changes.
- **Consequence for userspace: always go through "on" when switching between "idle" and "mem"** [STRONG].
  - `request_suspend_state` runs the early-suspend handlers only on the ON → not-ON edge. A direct idle → mem write only changes
    `requested_suspend_state`, so the idle-aware handlers (§2.4) never re-run.
  - idle → mem without "on": the frontlight stays on and the cyttsp4 keeps scanning through a screen-off sleep, but touch is no longer
    wake-armed.
  - mem → idle without "on": touch IRQ 160 is wake-armed while the controller is asleep.
  - Stock userspace never does this: every RTC/user path writes "on" before going to sleep, so the sequence is always idle → on → mem.
- `suspend()` (wakelock.c) @0xc04af3b0 calls `pm_suspend(requested_suspend_state)` [CONFIRMED] → `enter_state` → `valid_state(2)` = true.

### 2.2 `suspend_irqwake_set` and `pm_irqwake_*` (`irqwake.c`, ONYX-modified)

- `suspend_devices_and_enter` (with `suspend_enter` inlined) calls `suspend_irqwake_set(state)` after `arch_suspend_disable_irqs` (0xc04ae184).
  After `syscore_resume` it calls `suspend_irqwake_set(PM_SUSPEND_ON)` (0xc04ae1e4) [CONFIRMED].
- `suspend_irqwake_set` @0xc04b04c0 is the same state machine as RY:
  - ON/MEM → IDLE calls `pm_irqwake_enable`;
  - IDLE → ON/MEM calls `pm_irqwake_disable`;
  - ON ↔ MEM changes nothing.

  `old_state` is at 0xc0c76484.
- **`pm_irqwake_enable` @0xc04b03e4 is ONYX** [CONFIRMED]. It picks the touch IRQ by pcb version (160 = cyttsp4 on pcb 2/3,
  168 otherwise), enables it as a wake source with `irq_set_irq_wake(irq, 1)`, then does the same for IRQ 235 (`adc_irq_io`, the
  ADC-key wake line), and returns the OR of both results.

  RY wakes only the TS (168/162/164 by board). This RC2 boots with `pcb_ver=2` ("V1.73"), so the touch IRQ is 160.
  `/proc/interrupts`: `160 GPIO main_ttsp_core.cyttsp4_i2c_adapter`, `235 GPIO adc_irq_io`.
- `suspend_valid_idle_mem` @0xc04b04ac returns `state ∈ {2,3}` [CONFIRMED].

### 2.3 `/proc/idle` (`idle_control.c`, RY)

- `idle_init` @0xc0411b18 does `alloc_chrdev_region("idle")` and kmallocs the cell (pointer at 0xc0c76490). It then creates
  `/proc/idle` (`create_proc_entry` with mode 0, which procfs turns into the default 0444, plus a write handler). The cdev and class are compiled out (RY `IDLE_DEVICE_DEV/CLASS = 0`) [CONFIRMED].
- `idle_proc_read` @0xc04b0690 **stores 1 into the cell, then prints `"%d\n"`** (RY `__idle_get_val` under `CONFIG_IDLE`), so it always reads "1".
- `idle_proc_write` @0xc04b05a8 runs `simple_strtol` into the cell, and the next read overwrites that value [CONFIRMED].
- Meaning: "the kernel supports idle suspend". Default "1"; nobody writes it; libsuspend reads one byte ('1') [CONFIRMED].

### 2.4 Who looks at `get_suspend_state()` (idle-aware drivers)

`get_suspend_state` @0xc04aff38 returns `requested_suspend_state`. Callers [CONFIRMED, `--callers`]:

| Caller | In idle (2) | In mem (3) |
|---|---|---|
| `rk29_bl_suspend` @0xc0600a40 / `rk29_bl_resume` @0xc060041c (frontlight, early-suspend) | returns at once: **frontlight stays as it is** | cancels work, sets the suspend flag, brightness 0 |
| `cyttsp4_ts_early_suspend` @0xc06c2c60 | nothing: **touch controller keeps scanning** | `cyttsp4_core_sleep` |
| `rk29_keys_early_suspend` @0xc06b27f4 | nothing | saves and clears a key state word at 0xc0b522ec |
| `papyrus_pm_sleep` @0xc0616858 (TPS65185, dev_pm suspend) | sets flag 0xc0d2ac70 = 1; pins untouched | flag 0; unless `support_tps_3v3_always_alive`, drives both PMIC control GPIOs inactive |
| `gtp_pm_suspend` @0xc06bbbf0 (Goodix, absent on RC2) | nothing | sleep cmd |
| `magic_int_handler` @0xc045e678 (board, `magic_int` IRQ 168) | sends a POWER key press/release | nothing. Board-file domain; see [`../board/README.md`](../board/README.md) |

Other early-suspend registrants (`--callers register_early_suspend`) do not check the state:
- fbearlysuspend (`android_power_init`);
- `rk_fb`;
- `cyttsp4_mt`;
- the sensor driver;
- `wm831x` (absent on RC2).

### 2.5 Standard pieces, unmodified

- `stop_drawing_early_suspend`/`wait_for_fb_*` @0xc04aff48–0xc04b0288 are the Android fbearlysuspend: 1 s (`HZ`) timeout, `"sleeping"`/`"awake"`.
  Same as RY/PUB [STRONG].
- `suspend_time_*` @0xc04b0288–0xc04b03e4: Android `suspend_time.c`. `read_persistent_clock` gives 0 here, so dmesg always says
  `Suspended for 0.000 seconds` [CONFIRMED in a device dmesg after sleep].
- `pm_sysrq_init` registers sysrq `o` → `do_poweroff` → `kernel_power_off`. Standard.
- cpuidle (§4.2).

## 3. Charger and battery

### 3.1 `act8931_charge_*` @0xc061bbb0–0xc061c0a8 (RY `charge-regulater-adc.c` + 2 ONYX functions)

- `act8931_charge_init` @0xc061bdc4 is called from `act8931_i2c_probe`. It allocates the 0x44-byte state at 0xc0d2add8 and sets:
  - **`gpio_chglev = gpio_acin = −1`**; RY uses GPIO1_A1 and GPIO1_B2 and requests them;
  - `charge_level = chg_lev_bk = 1` (USB_100MA), so no output at init;
  - timer delay 1000 ms, invalid time 0x4fffffff.
- `act8931_charge_charge_output` skips every `gpio_direction_output` on −1. **On RC2 the charge-current pins are not driven at all**
  [CONFIRMED].
- ONYX additions:
  - `act8931_charge_level_reset` @0xc061bcd8 sets level 1 and outputs it (a no-op);
  - `act8931_charge_charge_level_get` @0xc061bcf8 reads ACIN/CHGLEV back (both −1) and so returns 0.
- `set_vbus_status`, `set_usb_status`, `charge_level_set/get` and `level_reset` have **no callers** in the Image; only `__ksymtab` refers
  to them [CONFIRMED].
- Charging is therefore the ACT8931 hardware default. Charger state comes from the CW2015 driver's `rk-ac`/`rk-usb` (USB detect)
  [STRONG].

### 3.2 CW2015 (`cw2015_battery.c`, RY older version, see [`../kernel/rk-fb-keypad-battery-wifi.md`](../kernel/rk-fb-keypad-battery-wifi.md) §C). Only the PM-relevant ONYX parts:

- **Alert threshold:** `cw_init` @0xc06e8714 forces CONFIG (reg 8) bits 7:3 = 0, so **ATHD = 0 %** (as RY) [CONFIRMED].
- **ALRT IRQ** (`bat_low_detect`, IRQ 169 = GPIO1_B1) is wake-enabled in `cw_bat_probe` (0xc06e923c) [CONFIRMED].
  - `bat_low_detect_irq_handler` @0xc06e93c4 is RY plus a printk: `wake_lock_timeout(1000)`, then queue work in 20 ms.
  - **`bat_low_detect_do_wakeup` @0xc06e940c is ONYX** (RY only calls `cw_get_alt`):
    1. read reg 6; if the ALRT bit is set:
    2. 50 × 1 ms delay;
    3. `cw_get_vol`, `cw_get_capacity`;
    4. **if not charging** (`cw_bat+0x218 == 0`): `"[CW201X] battery low"`, `wake_lock()` (no timeout) and `rk28_send_wakeup_key()`
       (KEY_WAKEUP 143);
    5. `power_supply_changed`;
    6. clear ALRT.
  - Result: at 0 % SOC on battery the device wakes and the screen turns on. The AOSP `BatteryService.shutdownIfNoPowerLocked` (level 0, not
    powered) then shuts it down (stock adds `sys.shutdown.nopower=1`) [STRONG].
- `rk30_adc_battery_get_bat_vol` @0xc06e9ad8 (ONYX) returns 1 if the CW2015 voltage is **≤ 3 500 000 µV** [CONFIRMED].
  - `rk30_adc_ebc_battery_check` @0xc06e9b24 (ONYX) prints "Battery too low" and refreshes the supply state.
  - Both are called **only from `rk29_ebc_probe`** (boot-time low-battery check for the EBC; EBC side:
    [onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc)), not at runtime.
- `cw_disable_batt_low_irq(int enable)` @0xc06e9f10 (ONYX): despite the name, 0 → `disable_irq`, ≠0 → `enable_irq` of the ALRT IRQ ("Disabing"/"Enabling").
  Its only callers are `spi_ctl_pins_enable` (0xc045e6f8, 0xc045e854) in the board file. It masks the ALRT line while its pin
  (GPIO1_B1) is muxed to SPI0_TXD for the panel-flash read ([`../board/README.md`](../board/README.md) §6) [STRONG].
- Battery-low shutdown path, summary: CW2015 ALRT@0% → KEY_WAKEUP → BatteryService level 0 → `ACTION_REQUEST_SHUTDOWN`. The ONYX PMS
  voltage check is dead on RC2 (Summary). Nothing else in the kernel shuts down on voltage [STRONG].

### 3.3 `hym8563_disable_alarm` @0xc06d1324 (ONYX export)

- It reads HYM8563 reg 1 (CTL2), clears bits 1:0 (AIE, TIE) and writes it back.
- **Only caller: `alarm_suspend` @0xc06cfea4** (Android `drivers/rtc/alarm.c`, ONYX-modified) [CONFIRMED]. When no alarm is pending
  in the wakeup queues it prints `No alarm in wake queue`, calls `hym8563_disable_alarm()`, and prints `Failed to disable alarm !!` if
  that fails.

  RY/PUB `alarm.c` have neither string. Purpose: a stale RTC alarm or count-down timer (the HYM8563 driver uses its 1-s count-down timer
  for alarms < 256 s, "use time") cannot wake the device from a suspend that has no pending alarm.
- It is not the auto power-off itself. Auto power-off is an AlarmManager RTC_WAKEUP alarm in the ONYX PowerManagerService. It reaches the chip
  through the normal `alarm_set_rtc` → `hym8563_rtc_set_alarm` path, and wake comes through `rtc_hym8563` IRQ 171 (GPIO1_B3)
  [CONFIRMED wake in a device dmesg after sleep: `wakeup gpio1: 00000800` + `wakeup wake lock: alarm_rtc`].

## 4. Wake sources, cpuidle, ddrfreq

### 4.1 Wake IRQs

IRQ = GPIO number = 128 + 32·bank + pin (`sram_gpio_init` @0xc0461ef0 subtracts 128; GIC lines 68–71 = GPIO banks 0–3). The names
come from the stock device's `/proc/interrupts` ([`../device/proc/proc_interrupts.txt`](../device/proc/proc_interrupts.txt)).

| IRQ | Pin | Name | Wake in mem | Wake in idle | Set by |
|---|---|---|---|---|---|
| 164 | GPIO1_A4 | `play` (POWER) | yes | yes | `keys_suspend` (wakeup=1 in table 0xc0a7167c) [CONFIRMED] |
| 205, 206, 211 | GPIO2_B5/B6, GPIO2_C3 | `pageup`, `pagedown`, `esc` (BACK) | yes | yes | board init rewrites these table entries to GPIO keys **with wakeup=1** on pcb v17x (`machine_rk30_board_init` 0xc040e4ec: stores `+0x20 = 1`; dmesg "Keycode [104] config changed to GPIO[205]") [CONFIRMED] |
| 235 | GPIO3_B3 | `adc_irq_io` (ADC keys `ok` 158 and `menu` 59) | no | **yes** | `pm_irqwake_enable` [CONFIRMED] |
| 160 | GPIO1_A0 | cyttsp4 touch | no (controller is put to sleep) | **yes** | `pm_irqwake_enable` [CONFIRMED] |
| 171 | GPIO1_B3 | `rtc_hym8563` | yes | yes | `hym8563_probe` [CONFIRMED; observed `wakeup gpio1: 00000800`] |
| 169 | GPIO1_B1 | `bat_low_detect` (CW2015 ALRT) | yes | yes | `cw_bat_probe` [CONFIRMED] |
| 168 | GPIO1_B0 | `magic_int` (hall / cover) | yes | yes | `magic_init` (board) [CONFIRMED call; behaviour: board file] |
| 83 | GIC | `otg-id` (OTG ID pin) | yes | yes | `otg_irq_detect_init` @0xc041cdb8 (`irq_set_irq_wake(83, 1)`) [CONFIRMED] |
| 67 | GIC | `bvalid` (VBUS) | not wake-enabled | same | no `irq_set_irq_wake(67)` anywhere [CONFIRMED callers]; whether a cable plug wakes a deep-sleeping (no-USB) device is [VERIFY]. With a cable attached the `usb_pcd` wakelock prevents deep sleep anyway ([`../kernel/linux-rockchip-3.0-vs-stock.md`](../kernel/linux-rockchip-3.0-vs-stock.md) §2) |
| 195 | GPIO2_A3 | `sd_detect` | yes | yes | `rk29_sdmmc_suspend` [STRONG] |
| — | — | BT host-wake (rfkill_rk), `dc_detect` | only if requested | same | not in `/proc/interrupts` on stock → not active [STRONG] |

Observed wakes on the device (stock kernel): `wakeup gpio1: 00000010` = 164 POWER, `00000800` = 171 RTC [CONFIRMED].

### 4.2 cpuidle

- `rk30_cpuidle_init` @0xc040e150 (RY `mach-rk30/cpuidle.c`) registers one state per CPU: `rk30_cpuidle_states` @0xc042baa8 = `{"C1", "idle"}`,
  latency 0, TIME_VALID flag. Its handler does `wfi` until a GIC interrupt is pending [CONFIRMED].
- There is no retention or power-down C-state, so the awake idle floor is WFI at the single DVFS point 912 MHz @1.40 V
  ([`../kernel/linux-rockchip-3.0-vs-stock.md`](../kernel/linux-rockchip-3.0-vs-stock.md) §1).
- `rk3026_pm_prepare` calls `disable_hlt` during suspend.

### 4.3 ddrfreq (`plat-rk/ddr_freq.c`, RY, "verion 3.2 20130917")

- dmesg: `ddrfreq: normal 396MHz video 300MHz video_low 0MHz dualview 0MHz idle 0MHz suspend 198MHz reboot 396MHz`.
- `ddrfreq_clk_pd_{gpu,rga,cif0,cif1,lcdc0,lcdc1}_event` are clock notifiers. `ddrfreq_clk_event` @0xc0462970 sets the status on PRE_ENABLE
  and clears it on POST_DISABLE/ABORT. They only matter for the "idle" DDR rate, which is **0 (disabled)**. This "idle" is unrelated to the
  suspend state.
- **The stock `ddrfreq_late_init` @0xc04623d0 registers no early-suspend handler** (RY does: `register_early_suspend(&ddr.early_suspend)`;
  no `ddrfreq_early_suspend` symbol exists). SYS_STATUS_SUSPEND is never set, so **DDR stays at 396 MHz with the screen off until the
  kernel suspends**. Then DDR goes to self-refresh, so it costs nothing once asleep [CONFIRMED].

### 4.4 USB/VBUS

- Nothing new beyond [`../kernel/linux-rockchip-3.0-vs-stock.md`](../kernel/linux-rockchip-3.0-vs-stock.md) §2. The CW2015 `dc_detect_do_wakeup` also calls `rk28_send_wakeup_key` (unused on RC2,
  `dc_detect` IRQ not requested) [CONFIRMED callers].

## Reproduce

Everything is static; the Image is only read. `IMG` is the raw stock kernel (2017-11-07 build), `SYMS` the list written by
`python3 -I ../kernel/extract_kallsyms.py $IMG $SYMS`; see [`tools/README.md`](tools/README.md).

```sh
tools/run.sh $IMG $SYMS <out-dir>   # sha256 check, then: fn/<name>.s for pm.list, callers.txt, sram-code.{bin,s},
                                    # sram-data.{bin,txt}, tables.txt
# single pieces
python3 -I tools/kdis.py $IMG $SYMS rk3026_pm_enter                 # one function
python3 -I tools/kdis.py $IMG $SYMS --callers get_suspend_state       # BL/B + pointer scan
python3 -I tools/sram_extract.py $IMG <out-dir>                       # SRAM blob + labelled listing
python3 -I tools/kwords.py $IMG c08c4be8:4 c0a6e0e4:9 c0a6e108:20 c0a7167c:66   # pm_states, ops, ctr help, key table
```

- The stock 4.2 userspace side (libsuspend, the PowerManagerService JNI and Java) was read with GNU objdump (Thumb) and a Java
  decompiler; those listings are working notes and are not published.
- Ghidra was not needed: every function here is small enough for objdump.

## Still [VERIFY]

- GPIO0_A3 as ACT8931 VSEL, the purpose of GPIO2_B4 (`lcd_d10`) in sleep, and why LDO2 is switched on in mem ([`../board/README.md`](../board/README.md)).
- The effect of CLKSEL10 (PERI HCLK div) never being restored after suspend.
- `cw_disable_batt_low_irq` use in `spi_ctl_pins_enable`.
- Device test of manual `echo idle > /sys/power/state`: wake by touch, page keys, ADC keys (`ok`/`menu`) and Power; image kept.
- Real battery numbers: idle-awake vs idle-suspend vs screen-off.
