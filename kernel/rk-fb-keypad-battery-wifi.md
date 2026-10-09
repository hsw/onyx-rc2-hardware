# linux-rockchip stable-3.0 vs stock RC2 kernel: fb, keypad, battery, Wi-Fi, board

Read-only analysis, 2026-10-08. Trees:
- **PUB** = [linux-rockchip/linux-rockchip](https://github.com/linux-rockchip/linux-rockchip) (stable-3.0, HEAD d08bfac2, 2014-08-04)
- **NU** = [Nu3001/kernel_rk3188](https://github.com/Nu3001/kernel_rk3188) (Nu3001 BSP kernel for an Android 4.4 RK3026 build)
- **RY** = [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources) (RK3026 ebook SDK, has `rk_epd/`)
- **STOCK** = the stock RC2 kernel Image (built 2017-11-07, sha256 `47a13cf3…30af`, not public), VA = file offset + 0xC0408000,
  symbols from its own kallsyms table ([`extract_kallsyms.py`](extract_kallsyms.py))

Helper outputs (stock `rk_fb_ioctl` disassembly, symbol list, Image strings) are working notes and are not published; they are plain
`objdump -D -b binary -m arm --adjust-vma=0xc0408000` listings over the function ranges.

**Main conclusion:** for fb, keypad, battery and Wi-Fi sysfs, the stock kernel belongs to the **older RK3026 ebook SDK generation (RY)**, not to PUB/NU. PUB/NU `rk_fb` is a newer generation, with sw_sync fences and a different `RK_FBIOSET_CONFIG_DONE` argument. The ABI contract has to be taken from RY plus the stock disassembly, not from the NU headers. [STRONG]

---

## A. rk_fb / lcdc: ABI seen by userspace

### A.1 Which driver
- On RK3026 the LCDC is the **rk3188_lcdc** driver (`PUB drivers/video/rockchip/lcdc/Kconfig`: `LCDC_RK3188 depends on ... (ARCH_RK3188 || ARCH_RK3026)`). Stock has `rk3188_lcdc_*` at 0xc0604980–0xc0606fbc and `rk_fb_*` at 0xc0602670–0xc0604980. [CONFIRMED]
- Stock rk_fb is the **RY version**. Every non-inlined function of RY `rk_fb.c` is in stock kallsyms, including `get_fb_struct` @c06043d8 and `rk_get_fb` @c0602868. Stock has no extra symbols in the rk_fb / rkfb_sysfs / rk3188_lcdc range, so **there are no signs of ONYX changes to rk_fb** [STRONG]. The stock fb sysfs attributes (read from the Image with [`sysfs_attrs.py`](sysfs_attrs.py)) match `rkfb_sysfs.c`, which is the same in PUB and RY.
- PUB-only symbols, **absent from stock**: `rk_fd_fence_wait` (PUB rk_fb.c:620), `rk_fb_update_reg` (:640), `rk_fb_update_regs_handler` (:669), `rk_fb_free_dma_buf`, `rk_fb_get_list_stat`, `get_extend_fb_id`, `fb_copy_by_rga`, and `sw_sync_timeline_create("rk-fb")` (:2116). **rk_fb has no fences** [CONFIRMED]. The kernel itself does have sync/sw_sync (`sync_fence_*` @c063b970…, exported).
- Stock lcdc runs in **CONFIG_HARDWARE_EBC** mode. In RY `rk3188_lcdc.c:51-79`, `clk_enable`/`clk_disable` only toggle a flag, and the lcdc includes `../rk_epd/ebc.h`. PUB `rk3188_lcdc.c` has **0** EBC references, and PUB has no `rk_epd/`. On the device `/proc/interrupts`: `rk30-lcdc.0 = 0` and `rk29-ebc = 179`, so **the LCDC does not scan out and does not raise interrupts**. fb0 is only a memory pool, and the EBC is driven through `/dev/ebc`. [CONFIRMED by device-info]

### A.2 Number of fb devices and memory
- `/sys/class/graphics/`: **fb0 and fb1**, both `platform/rk-fb` (stock-device sysfs listing). A stock-kernel boot dmesg shows `lcdc0 primary`, `lcdc1 not add`, `fb0:win0 fb1:win1 fb2:win2` (map), and `rk_fb_register` only for fb0 and fb1. [CONFIRMED]
- Memory is allocated only for fb0 (RY rk_fb.c:1599 `if (i == 0) rk_request_fb_buffer`). fb1 has no memory of its own: its buffers are "alloc by android" (RY rk_fb.c:1401-1412), and `fb2 buf` in iomem is 0-0. [STRONG]
- **fb0**: phys **0x7e500000**, len **0x1200000 (18 MiB)** (dmesg `fb0:phy:7e500000>>vir:e0000000>>len:0x1200000`, [`/proc/iomem`](../device/proc/proc_iomem.txt)). Size = stock `get_fb_size` @c0607044 = `ALIGN(w*h*12, 1 MiB)` with w,h from `set_epd_info` (= 3 buffers × 4 bytes/px, the same formula as PUB `screen/rk_screen.c:362-371` under THREE_FB_BUFFER). For 1448×1072: 18 627 072 → 18 MiB. [CONFIRMED]
- So the pool holds 3 buffers: `yres_virtual = 3216 = 3×1072`, `xres_virtual = 1448`, bpp 32, line_length 5792 (stock sysfs: `virtual_size` `1448,3216`, `bits_per_pixel` `32`, mode `U:1448x1072p-0`). "rk fb use 3 buffers" in dmesg is the `RK_FBIOPUT_NUM_BUFFERS` printk. [CONFIRMED]
- Neighbouring reserved areas (not fb): `ebc disp buf` 0x7f700000 (8 MiB) and `ebc buf` (waveform) 0x7ff00000 (1 MiB).
- **Physical size in var is wrong.** Stock `set_lcd_info` @c0606fbc writes screen width=**216** mm and height=**135** mm (instead of about 122×91 mm for a 6" panel), pixclock 71 MHz, margins L100/R18/HS10/U8/L6/VS2, lcdc_aclk 300 MHz. That gives exactly the stock SurfaceFlinger `xdpi=170.27, ydpi=201.69` (stock `dumpsys SurfaceFlinger`; 1448·25.4/216 = 170.27, 1072·25.4/135 = 201.69). **Userspace should not take xdpi/ydpi from var.width/height**; the panel is ≈300 dpi. [CONFIRMED]

### A.3 ioctls (stock `rk_fb_ioctl` @c0602d24–c06030c0, `rk3188_lcdc_ioctl` @c06061f8)
The numbers are "raw" (no `_IOC` dir/size encoding). The `cmp` chain in the disassembly matches RY `include/linux/rk_fb.h:45-62` and RY `rk_fb.c:440-523`. The same numbers are in PUB `include/linux/rk_fb.h:48-67`, plus two that are missing from stock.

| cmd | Name | arg / semantics on stock | Note |
|---|---|---|---|
| 0x4608 | FBIOPUT_FBPHYADD (`include/linux/fb.h:23`) | no arg; **returns `fix.smem_start` as the ioctl return value** (`ldr r4,[r7,#0xec]`) | phys 0x7e500000 is not in the -errno range, so bionic returns it as is |
| 0x4619 | RK_FBIOGET_OVERLAY_STATE | out int = `ovl_mgr(dev,0,0)` | |
| 0x4625 | RK_FBIOPUT_NUM_BUFFERS | in int → `dev_drv->num_buf` (+0x38), printk "rk fb use %d buffers" | does not change memory or var |
| 0x4628 | RK_FBIOSET_CONFIG_DONE | **in int (4 bytes) = wait_fs** → `dev_drv+0xd0`, then `lcdc_reg_update` (+0xf8); always returns 0 | **PUB/NU take `struct rk_fb_win_config_data` here** (PUB rk_fb.h:253: rel_fence_fd[4], acq_fence_fd[16], wait_fs, u8 fence_begin, ret_fence_fd ≈ 92 bytes) and write back ret_fence_fd. Stock reads only the first 4 bytes and writes nothing back. Userspace (HWC/gralloc) built against PUB/NU headers is incompatible here |
| 0x4629 | RK_FBIOSET_VSYNC_ENABLE | in int → `vsync_info.active` (byte +0xa8) | |
| 0x5002 | RK_FBIOSET_YUV_ADDR | in u32[2] → **overwrites `fix.smem_start` and `fix.mmio_start`** | side effect: FBIOGET_FSCREENINFO/mmap afterwards see the new smem_start |
| 0x5018 | RK_FBIOSET_OVERLAY_STATE | in int → `ovl_mgr(dev,ovl,1)` | |
| 0x5019 | RK_FBIOSET_ENABLE | in int → `open(dev, layer, enable!=0)` | stock gralloc does this for fb1 with 0 |
| 0x5020 | RK_FBIOGET_ENABLE | out int = `get_layer_state` | |
| 0x5001 | RK_FBIOGET_PANEL_SIZE (lcdc) | out u32[2] = x_res, y_res | |
| 0x4626 | RK_FBIOPUT_COLOR_KEY_CFG (lcdc) | in `struct color_key_cfg` → WIN0/1_COLOR_KEY | |
| other | → `rk3188_lcdc_ioctl` default | **returns 0 without doing anything** | including **FBIO_WAITFORVSYNC (0x40044620) = instant 0**, and also the PUB-only 0x4630 GET_DSP_ADDR and 0x4631 GET_LIST_STAT |

Offsets from the disassembly (stock): `fb_info`: fix.id +0xdc, fix.smem_start +0xec, fix.mmio_start +0x10c, device +0x23c, par +0x25c. `rk_lcdc_device_driver`: num_buf +0x38, vsync_info.active +0xa8, wait_fs +0xd0, open +0xd8, ioctl +0xe0, lcdc_reg_update +0xf8, get_layer_state +0x104, ovl_mgr +0x108, fb_get_layer +0x110. [CONFIRMED]

### A.4 var semantics, pan, set_par (RY rk_fb.c)
- `var.nonstd` = `format | xpos<<8 | ypos<<20`, where format is a **HAL_PIXEL_FORMAT_*** value (RGBA_8888=1→ABGR888, RGBX=2→XBGR888, BGRA_8888=5→ARGB888, RGB_565=4, …; RY rk_fb.c:777-842). If nonstd&0xff == 0, the format is chosen by bpp (32→ARGB888, 16→RGB565). `var.grayscale` = `xsize<<8 | ysize<<20` (the size of the visible window; 0 = full screen). With a standard AOSP framebuffer.cpp, read var with FBIOGET and **do not zero nonstd/grayscale**. [STRONG]
- `check_var`: only bpp 16/32, xres≥16, non-zero virtual sizes (RY :550).
- **FBIOPAN_DISPLAY**: `rk_pan_display` @c06028ac computes `y_offset=(yoffset*xres_virtual+xoffset)*4` and calls `rk3188_lcdc_pan_display` @c0604c3c, which only writes registers. Its callees are only printk, dev_err and spin_lock/unlock, so **there is no vsync wait** (RY `WAIT_FOR_SYNC` is commented out, rk3188_lcdc.c:47). Pan returns immediately, and **nothing appears on E-Ink from a pan**. Output only goes through `/dev/ebc` (see [onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc)). [CONFIRMED by disassembly]
- `CONFIG_DONE` with wait_fs≠0 → `rk3188_lcdc_reg_update` @c0605c5c waits up to `ft+5` ms for `frame_done` (callee `wait_for_completion_timeout`). The LCDC irq does not fire, so this always times out (printk "wait for new frame start time out!") and the ioctl still returns 0. **Pass wait_fs=0.** No such messages appear in the test dmesg logs, so stock gralloc probably passes 0. [STRONG / VERIFY wait_fs of stock gralloc]

### A.5 vsync
- `/sys/class/graphics/fb0/vsync` 0444 (`rk_fb_vsync_show` @c0602cf4) prints `vsync_info.timestamp` in ns. A kthread `rk_fb_wait_for_vsync_thread` @c0603408 does `sysfs_notify` when the timestamp changes **and** `active` is set (RY rk_fb.c:981-998; NU removed the `active` condition, see below). The timestamp is updated only in `rk3188_lcdc_isr` @c0606834, and that **irq = 0** on the device. **The vsync file never changes and poll() on it blocks forever.** Userspace that relies on hardware vsync will hang; a software vsync is needed. [STRONG; irq=0 CONFIRMED]

### A.6 Nu3001 rk_fb.c diff vs PUB (the only change in the fb area)
NU is an **earlier** snapshot of the same fence-based rk_fb. (1) In `RK_FBIOSET_CONFIG_DONE`, `regs` is allocated before the `if` and freed in `rk_fb_update_reg` (PUB fixed a leak/double-path, PUB :882-940, :650-656). (2) In the vsync thread, NU drops the `&& vsync_info.active` condition (PUB :1448-1452). Neither change matters for stock: that code is not in the stock kernel. `rk3188_lcdc.c` and `rk_fb.h` are identical in NU and PUB (not in the NU-vs-PUB file diff). [CONFIRMED]

## B. rk29-keypad / key_switching

- Driver: `drivers/input/keyboard/rk29_keys.c` (PUB 575 lines, RY 702, NU 839).
- **PUB**: sysfs only `rk29key` (0660, :150) and `get_adc_value` (:312). No `key_switching`, `touchkeyena`, `touchkeydis`, `onyx_*` in any of the three trees (grep over drivers/ and arch/). [CONFIRMED]
- **NU diff** = Bonovo car-radio code (`CPKEY_*` enum, "add by zbiao", rk29_keys.c:+166…), irrelevant to RC2.
- **RY** (ebook SDK) adds: `rk29_send_wakeup_key`, `rk28_send_wakeup_batlow`, `adc_irqio_isr`/`adc_timer_work` (ADC key on an irq GPIO with a 3 s wakelock), `data[10]` instead of a flex array, `in_weak_suspend`. All of these are in stock (0xc06b2274…0xc06b294c).
- **ONYX-only in stock** (not in PUB/RY/NU): `onyx_vibrator_control` c06b1a28, `rk29_keys_early_resume` c06b1a4c / `rk29_keys_early_suspend` c06b27f4, `key_switching_store` c06b1ba4 / `key_switching_status` c06b1c00, `onyx_keypad_control_get` c06b1c38, `onyx_disable_key` c06b1cb8, `onyx_touchkey_enable` c06b1d44 / `onyx_touchkey_disable` c06b1e44, plus an extended `rk29_keys_button` struct. Contract details are in [`sysfs-attributes.md`](sysfs-attributes.md). [CONFIRMED]
- RY `board-rk3026-ebook.c:912-993`: buttons `flush`(F5, ADC 1), `esc`(BACK, ADC 150), pageup/pagedown on GPIO0_PA2/PA3 with **compile-time** swapping (`CONFIG_SWITCH_PAGEUP_PAGEDOWN_E601/E602`), ADC chn 3, `adc_irq_io = RK30_PIN3_PB3`. ONYX `key_switching` replaces this compile-time swap with a runtime one. [STRONG]

## C. Battery

- RC2: **cw201x (CW2015) @ i2c0-0x62**, power_supply `rk-bat`/`rk-ac`/`rk-usb`. The driver is `drivers/power/cw2015_battery.c` "cw2015/cw2013 driver v1.2" (strings in Image). `rk30_adc_battery`/`rk30_factory_adc_battery` are **not** built into stock (no symbols). [CONFIRMED]
- Function set matches PUB/RY `cw2015_battery.c` (helpers are inlined). PUB adds a reset on read error ("report battery capacity error", MODE_SLEEP after 30 retries or 5 reset_loop), and **stock does not have that string**. So stock is the older RY version (`BATTERY_DOWN_MAX_CHANGE_RUN_AC_ONLINE 3600` in RY vs 1800 in PUB). [STRONG]
- **ONYX additions in stock**:
  - `rk30_adc_battery_get_bat_vol` c06e9ad8 (calls only `cw_get_vol`) and `rk30_adc_ebc_battery_check` c06e9b24. These are the interface the precompiled EBC expects (RY `rk_epd/ebc.h:464-465`; in RY they are implemented in `rk30_factory_adc_battery.c:1984-2020`). ONYX reimplemented them on top of CW2015 ("ebc ___ onyx _____gBatteryData->bat_voltage=%d", "Battery too low").
  - `rk_get_system_battery_capacity/_status` (exported), `cw_disable_batt_low_irq` c06e9f10, and the alert/bat-low irq ("[CW201X] battery low", "clearing the alert flag failed").
- **Battery level accuracy:** SOC is computed by the CW2015 itself from the battery profile (`cw_bat_config_info[]`, written to the chip in `cw_update_config_info` c06e84f8 when the UPDATE flag is missing). The driver only smooths it (no jumps up while discharging, and similar rules). With the stock kernel the profile and smoothing are fixed; userspace can only read `capacity` as is. `TIME_TO_EMPTY_NOW=8191` is a constant (the CW2015 RRT alert is not computed on RC2). Nothing more useful for accuracy is in the public trees. [STRONG]

## D. Wi-Fi RTL8723BU

- **Stock `8723bu.ko`**: `version=v4.3.16.3_14887.20150731_BTCOEX20150119-5844`, build "Jul 18 2016", `vermagic=3.0.36+ SMP preempt mod_unload ARMv7`, `srcversion=C3EBAFDE35C7F28AA3E451E`, alias `usb:v0BDApB720`, md5 f9bbe042…. Built out-of-tree from the vendor tree (`…/rk3026epd_onyx/system/wlan/rtl8723bu/…` paths inside). Imports from the kernel: `wifi_activate_usb`/`wifi_deactivate_usb` (exported, `__ksymtab` c0a0a22c/c0a0a234). [CONFIRMED]
- **PUB** `drivers/net/wireless/rkusbwifi/rtl8723bu`: **v4.3.0_10670.20140303_BTCOEX20140123-4A40**, which is *older* than stock (RY has no rtl8723bu at all; NU = PUB). PUB `rtl8723bs` v4.3.0_10579 is the SDIO variant and not relevant. **The public tree has nothing newer.** [CONFIRMED]
- `/sys/class/rkwifi/{power,driver}`: in PUB and NU `wifi_sys/rkwifi_sys_iface.c:490-491` (that is what 4.4 libhardware_legacy expects). In RY and stock they are absent (stock only has chip/p2p/pcba/aidc). So a userspace that expects them (Android 4.4 `libhardware_legacy`) has to load the module itself, as stock 4.2 does. [CONFIRMED]
- **Is a newer build needed or possible?** The stock module works on the stock kernel. A rebuild is possible in theory with the Realtek v4.3.x/v4.4.x or lwfinger `rtl8723bu` sources plus a kernel tree configured to match stock. But **MODVERSIONS is off**, so insmod will not catch mismatches in `net_device`/`sk_buff`/cfg80211 layouts between the NU tree and the stock Image (stock cfg80211 is the 3.0 backport). The risk is a silent oops for little gain: WPA2/KRACK are handled in wpa_supplicant, and there is no WPA3 in 4.4 anyway. Recommendation for the stock kernel: keep the stock module. [STRONG]

## E. Board / i2c / power (brief)

- `i2c-rk30-adapter.c`: the NU diff only comments out a debug print (PUB :564-569). Stock has `rk30_i2c_*` + `i2c_master_reg8_*` exports, the same driver. [CONFIRMED]
- PUB `arch/arm/mach-rk3026/` has only `board-rk3026-{86v,tb}.c` (tablets) and no `pm.c`/`i2c_sram.c`. **There is no ebook board file.** It exists in RY: `board-rk3026-ebook.c`, `-ebook-power.c`, `-ebook-cyttsp4.c`, `board-rk30-sdk-act8931.c`, `pm.c`. [CONFIRMED]
- Stock board (0xc045de28–0xc045f428) = RY ebook board + ONYX functions: `onyx_get_tp_irq_pin/rst_pin`, `onyx_system_tp_probed`, `onyx_get_pcb_version`, `is_onyx_pcb_v17x`, `onyx_hall_sensor_power`, `magic_init`/`magic_int_handler` (the hall/magnet cover; [STRONG] in [`../board/README.md`](../board/README.md) §6), `onyx_tp_power_enable/set_voltage`, `onyx_vccio_set_voltage`, `onyx_wifi_bt_module_power*`, `onyx_combo_module_{wifi,bt}_power`, `onyx_get_emmcboot`, `last_log_read`, `spi_ctl_pins_enable`. [CONFIRMED symbols]
- PMIC act8931 @ i2c0-0x5b: in RY `board-rk3026-ebook.c:1451-1500`, dcdc1 vccio 3.2 V ("modified for adc battery"), dcdc2 DDR 1.35 V, ldo1 vcc_tp 3.3 V, ldo2 off (3.0 V), …. Stock `act8931_set_init` c045e930 / `act8931_set_ldo` c045f24c; actual stock values: now resolved in [`../board/README.md`](../board/README.md) §2. E-Ink PMIC tps65185 (`tps65185_init` c0419c6c).
- Wake sources: `rk3026_pm_enter` c045c764 (RY `pm.c`, prints "wakeup irq/gpio0..3" on resume). In RY, keypad/matrix buttons have `.wakeup = 1` and SD wakeup is off. On RC2 deep sleep and Power wake are already confirmed on the device. The full wake-source table is in [`../power/README.md`](../power/README.md) §4.1.
