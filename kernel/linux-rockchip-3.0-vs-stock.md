# Public Rockchip stable-3.0 tree vs stock RC2 kernel

Static comparison (2026-10-08) of [linux-rockchip/linux-rockchip](https://github.com/linux-rockchip/linux-rockchip)
(`mirror/stable-3.0`, HEAD d08bfac2cc, 2014-08-04) with the stock RC2 kernel; the device was not used. The tree is ~identical to the
Nu3001 BSP kernel ([Nu3001/kernel_rk3188](https://github.com/Nu3001/kernel_rk3188); 125 files differ). Stock Image = the stock RC2
kernel (built 2017-11-07, sha256 `47a13cf3…30af`, not public; VA = file offset + 0xC0408000), symbols recovered from its own kallsyms
table ([`extract_kallsyms.py`](extract_kallsyms.py)).

## Summary

| # | Topic | Result |
|---|---|---|
| 1 | CPU frequencies | **The stock ARM DVFS table has exactly one entry: 912 MHz at 1.40 V** [CONFIRMED]. The 4PDA claim "912–912 MHz" is true and is kernel-bound. The public tree has 312/504/816/912/1008 MHz. |
| 2 | Sleep / wake | The `usb_pcd` wakelock is held while the USB gadget is connected (expected). On VBUS/ID change the kernel injects **KEY_WAKEUP (143)**, which the stock `rk29-keypad.kl` maps to `NOTIFICATION WAKE` → plug/unplug wakes the device independently of `config_unplugTurnsOnScreen` [CONFIRMED]. |
| 3 | fb ABI, keypad, battery, Wi-Fi, PMIC | See section 3 below. |
| 4 | Config | 568 of 569 `__FILE__` paths of the stock Image exist in the public tree; the only missing one is `rk_epd/epdpower/tps65185.c`. Governors in stock = defconfig `rk3026_*` (interactive default, performance, powersave, userspace, ondemand, conservative). ONYX-only built-in drivers: see section 4. |

## 1. CPU frequency table

Public tree, `arch/arm/mach-rk3026/`:

| Board file | ARM table (MHz @ mV) |
|---|---|
| `board-rk3026-tb.c:1126` | 312@950, 504@1000, 816@1200, 912@1250, 1008@1350; then `adjust_dvfs_table(soc_version, …)` |
| `board-rk3026-86v.c:1866` (v0) | 312@1200, 504@1200, 816@1250, 912@1350, 1008@1350 |
| `board-rk3026-86v.c:1878` (v1) | 312@1200, 504@1200, 816@1275, 912@1350, 1008@1400 |

GPU 200/266/400 MHz @1200 mV (tb), DDR 200 (suspend) / 300 (video) / 400 (normal) MHz @1200 mV.

Stock RC2 (`board_clock_init` @0xc040eaa8, same shape as the tb board: `adjust_dvfs_table` @0xc045dc08, then three
`dvfs_set_freq_volt_table` @0xc0463bf8 calls with `r4`, `r4+16`, `r4+48`, `r4` = 0xc0a71cb8):

| Table | VA | Content |
|---|---|---|
| ARM | 0xc0a71cb8 | **{912 000 kHz, 1 400 000 µV}, END** — one entry |
| GPU | 0xc0a71cc8 | 200, 266, 400 MHz @1200 mV (= tb board) |
| DDR | 0xc0a71ce8 | 200 (+1 suspend flag), 300 (+2 video), 400 (+256 normal) MHz @1200 mV (= tb board) |
| adjust per SoC version | 0xc08c2d10 → 0xc0a70ca0 / 0xc0a70cc0 / 0xc0a70ce8 | v0 {312 +200, 504 +200, 912 +50 mV}; v1 = v2 {504 +50, 816 +75, 912 +50, 1008 +50}; v3 = v4 empty (public tree: v0 {312 +250, 504 +200, 816 +50, 912 +100}, v1 {504 +50, 816 +75, 912 +100, 1008 +50}) |

The RC2 boots with `rk3026 soc version:4` [CONFIRMED: device dmesg], so the adjust table is empty and the CPU runs at
912 MHz / 1.40 V whenever it is awake. Consequences:
- `scaling_available_frequencies` = 912000 only; `min = max = 912000`. Governors exist but have nothing to choose.
- The `power.rk3026.so` clamp of `scaling_max_freq` to 816 MHz on screen-off is a no-op: `cpufreq_frequency_table_verify`
  raises a max below the lowest table entry back to 912 MHz [STRONG, 3.0 cpufreq core].
- `rk3026 cpufreq version 2.2, suspend freq 912 MHz` in dmesg follows from the same table (driver default 816,
  `mach-rk3188/cpufreq.c:70`, but 816 is not in the table).
- Why ONYX pinned it is unknown (E-Ink conversion and EBC timing are CPU work; or simply the safe choice). Lower
  frequencies would save awake power, but only by changing the kernel. A device read of `scaling_available_frequencies` would only
  confirm it.
- Deep sleep is unaffected [CONFIRMED: ~105 s of kernel deep sleep without USB on the device].

## 2. Sleep, wakelocks and wake sources

- `usb_pcd` wakelock (`drivers/usb/dwc_otg/dwc_otg_pcd.c:1967`) is taken by `dwc_otg_msc_lock` (l.1640) when the gadget
  is connected/configured and released on disconnect (l.1734, 1744, 1816, 1847). Stock has the same (`dwc_otg_msc_lock`
  @0xc0695b74). So "with a cable the device does not suspend" is by design; nothing to fix.
- `drivers/usb/dwc_otg/usbdev_rk3026.c:432-445, 446-480`: the BVALID (VBUS) and OTG-ID interrupts schedule `do_wakeup`
  after 100 ms: a 10 s `usb_detect` wakelock **and `rk28_send_wakeup_key()`**, which reports KEY_WAKEUP down/up through
  the rk29-keypad input device (`drivers/input/keyboard/rk29_keys.c:168`). Stock: `do_wakeup` @0xc069cae4 calls
  `rk28_send_wakeup_key` @0xc06b28e4 [CONFIRMED, disassembly]. The stock ADC battery driver also injects it from
  `bat_low_detect_do_wakeup` @0xc06e940c and `dc_detect_do_wakeup` @0xc06e956c (charger plug).
- The stock `rk29-keypad.kl` has `key 143 NOTIFICATION WAKE`, so every plug/unplug and a low-battery
  event wakes the device. `config_unplugTurnsOnScreen=false` alone would **not** stop it; removing `WAKE` from key 143
  would (and would also stop low-battery wakes).
- In the public tree, suspend for rk3026 is `mach-rk2928/pm.c` (rk3026 Makefile builds `../mach-rk2928/pm.o`). The stock kernel has
  the newer RK3026 suspend code instead (section 4; [`../power/README.md`](../power/README.md)).

## 3. fb ABI, keypad, battery, Wi-Fi, PMIC

Full report: [`rk-fb-keypad-battery-wifi.md`](rk-fb-keypad-battery-wifi.md) (same day; disassembly of stock `rk_fb_ioctl` @0xc0602d24). Main point:
**for these drivers the stock kernel is the older RK3026 ebook SDK generation (rychly tree), not stable-3.0/Nu3001** [STRONG], so
ABI questions go to rychly + stock disassembly, not to the Nu3001 headers.

- **fb:** `rk3188_lcdc` in hardware-EBC mode, LCDC IRQ count 0 (never scans out); rk_fb unchanged by ONYX; no fences
  (`rk_fd_fence_wait` absent); fb0 18 MiB @0x7e500000, 1448×3216 virtual = 3 buffers, fb1 without memory; `RK_FBIOSET_CONFIG_DONE`
  takes a 4-byte `wait_fs` (stable-3.0/Nu3001: 92-byte struct with fence fds — incompatible); `FBIO_WAITFORVSYNC` and the vsync node
  do nothing; var.width/height = 216×135 mm explain the stock xdpi 170 / ydpi 201.
- **keypad:** `key_switching`, `touchkeyena/dis`, vibrator are ONYX-only (no public tree has them); the ebook board swapped
  PageUp/PageDown only at compile time.
- **battery:** CW2015 fuel gauge driver v1.2 (rychly version); ONYX added the EBC battery hooks; nothing to improve from userspace
  beyond reading `capacity` honestly (already done).
- **Wi-Fi:** stock `8723bu.ko` v4.3.16.3 (2016, out of tree) is newer than stable-3.0's v4.3.0; `/sys/class/rkwifi/` exists only in
  stable-3.0/Nu3001, so on the stock kernel userspace has to insmod the module itself. Keep the stock module.
- **board/PMIC:** the stock board file = rychly ebook board + `onyx_*` functions; act8931 values: [`../board/README.md`](../board/README.md) §2.

## 4. Built-in code of the stock Image that the public tree does not have

Method: the 623 initcall functions of the stock Image (`__initcall_<fn><level>` in kallsyms) searched as identifiers in every
`.c/.h/.S` of the tree (a 14 s Python scan; working notes, not published). 12 are missing:

| Initcall (stock VA) | What it is |
|---|---|
| `rk29_ebc_init` @0xc0419b1c, `spi_flash_init` @0xc0419c30, `lm_proc_init` @0xc0419c3c, `tps65185_init` @0xc0419c6c | E-Ink stack `drivers/video/rockchip/rk_epd/` (EBC, waveform SPI flash, LUT proc node, PMIC); source only in rychly (partly as `.uu` objects) and `ridi/linux-paper` |
| `cyttsp4_{bus,core,device_access,i2c,mt}_init` | Cypress TrueTouch Gen4 touch (cyttsp4); in rychly |
| `onyx_misc_driver_init` | ONYX `onyx_misc.0` (sysfs contract in [`sysfs-attributes.md`](sysfs-attributes.md)); in no public tree |
| `rk3026_pm_init` @0xc040db44 (+ `rk3026_pm_prepare/enter/finish/dump_irq` @0xc045c470…, `set_arm_suspend_volt`, `set_logic_suspend_volt`, `pm_suspend_volt_seting`, `early_param_rk_soc_pm_ctr`) | **A newer Rockchip RK3026 suspend implementation** with suspend voltages and an `rk_soc_pm_ctr` boot parameter. The public tree still builds `mach-rk2928/pm.c` for rk3026, so the stock kernel is newer than this 2014 snapshot here. Relevant only for reading suspend behaviour. **Correction:** this code is public in the rychly RK3026 E-Ink SDK tree (`arch/arm/mach-rk3026/pm.c`); see [`../power/README.md`](../power/README.md) |
| `idle_init` @0xc0411b18 (between `suspend_time_debug_init` and cgroups, i.e. `kernel/power/`) | ONYX or later-RK addition in `kernel/power/` (the Nu3001 tree also differs from the public one in `kernel/power`). **Correction:** it is `kernel/power/idle_control.c` of the rychly tree; `/proc/idle` always reads 1 ([`../power/README.md`](../power/README.md) §2.3) |

So outside E-Ink, touch, `onyx_misc` and the newer PM code, the stock kernel is this tree. `__FILE__` paths agree: 568 of 569
exist here; the only missing one is `rk_epd/epdpower/tps65185.c`.

## What to take from the tree

- The tree is a **readable reference** for the stock kernel (same code except ONYX additions), for core code and cpufreq/DVFS; for
  rk_fb, keypad, battery and the board file the rychly ebook tree is the closer reference.
- Concrete uses: the cpufreq answer above; the wake-key path; rk_fb/lcdc (section 3); per-driver sysfs semantics when a new node
  shows up (list them with [`sysfs_attrs.py`](sysfs_attrs.py)).
