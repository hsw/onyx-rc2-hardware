# Reconstructed configuration of the stock RC2 kernel (3.0.36+)

Input: the stock kernel Image (uncompressed ARM Image, 7 766 052 B, `Linux version 3.0.36+ (jenkins@jim-hp-workstation-15) … #1 SMP PREEMPT Tue Nov 7 21:44:55 CST 2017` @0x4b9fc1; sha256 `47a13cf3…30af`, firmware 1.8.2, not public).
There is no built-in IKCONFIG, so the configuration was reconstructed from **kallsyms** (recovered completely), strings, ioctl constants in the disassembly and runtime data from the device.

Addressing: VA = file_offset + 0xC0408000 (PAGE_OFFSET 0xC0000000 + TEXT_OFFSET 0x408000; physical load address 0x60408000). Below, "off" means an offset in the Image file.

## 0. Summary

Present: binder (protocol 7, 32-bit ioctls), ashmem, logger (including `log_system`), lowmemorykiller, cgroups cpu/cpuacct/freezer, Android wakelocks with earlysuspend, tmpfs, ext4, **FUSE**, qtaguid/quota2/IDLETIMER, **sync + sw_sync**, ION (old 3.0 ABI), the Android USB gadget with adb/**mtp**/ptp/mass_storage/rndis/accessory/audio_source, MODULES, KALLSYMS.

Absent: **SELinux (CONFIG_SECURITY is off entirely)**, TUN, memcg, ZRAM, KSM, AUDIT, SysV IPC, POSIX MQ, KEYS, AIO, perf, IKCONFIG, **MODVERSIONS**.

Notable ABI facts:
- **ION has the old 3.0 ABI** (`ION_IOC_ALLOC` = 0xC0104900, 16-byte struct, no `heap_id_mask`). A libion built for newer kernels (20-byte struct) gets ENOTTY.
- **rk_fb has no fence support** (no `rk_fd_fence_wait`, which the Nu3001 kernel has). sw_sync itself is in the kernel.
- **Mali r3p2-01rel0 (API_VERSION=19) + UMP are external modules.** The userspace Mali driver must match that API version. MODVERSIONS is off (no `__crc_*`), modules load only by vermagic `3.0.36+ SMP preempt mod_unload ARMv7`, so binary structure mismatches are not caught.

## 1. Recovering kallsyms

[`extract_kallsyms.py`](extract_kallsyms.py) (heuristic: find `kallsyms_token_index`, 256 increasing u16, then walk back to markers/names/num_syms/addresses):

| Table | off |
|---|---|
| kallsyms_addresses | 0x505740 |
| kallsyms_num_syms = **38 721** | 0x52b450 |
| kallsyms_names | 0x52b460 |
| kallsyms_markers (152) | 0x59a860 |
| kallsyms_token_table | 0x59aac0 |
| kallsyms_token_index | 0x59ae50 |

Range 0xC0408000 (`stext`) … 0xC0A52818 (`_etext`). The list of initcalls (= built-in drivers and subsystems) has 637 entries.

## 2. Android options

| Option | Evidence (symbol/string @ off) | Verdict |
|---|---|---|
| ANDROID_BINDER_IPC | `binder_ioctl` @0x327274; `drivers/staging/android/binder.c` @0x5e4d76; `binder.debug_mask` @0x4f78ae; in `binder_ioctl` BINDER_VERSION=0xC0046209 → `mov r2,#7` (@VA 0xc072f6b0), BINDER_WRITE_READ=0xC0186201 (24 bytes, 32-bit) | **present**, protocol **7** (32-bit) |
| ASHMEM | `ashmem_ioctl` @0xf4214; `<6>ashmem: initialized` @0x5ab33e; `dev/ashmem` @0x5ab362; ioctl 0x7701..0x7709 (incl. GET_PIN_STATUS / PURGE_ALL) | **present** |
| ANDROID_LOGGER | `logger_ioctl` @0x3278b4; `log_main` @0x5e6a04, `log_events` @0x5e6a0d, `log_radio` @0x5e6a18, `log_system` @0x5e6a22 | **present** (4 buffers, logger v1) |
| ANDROID_LOW_MEMORY_KILLER | `lowmem_shrink` @0x3289d8; `lowmemorykiller.minfree` @0x4f79e0, `.adj` @0x4f7a0c, `.cost` @0x4f7a34 | **present** |
| CGROUPS | `cgroup_init` @0x9f1c; string `cgroup` @0x5a644e; on the device `none /acct cgroup … cpuacct` and `none /dev/cpuctl cgroup … cpu` are mounted | **present** [CONFIRMED runtime] |
| CGROUP_FREEZER | `freezer_create` @0xae664, `freezer_write`, `freezer_state_strs`; string `freezer` @0x5a572d | **present** |
| CGROUP_CPUACCT | `cpuacct_populate` @0x5eb24, `cpuacct_powerusage_read`, `cpuacct_cpufreq_show` (Android extensions); string `cpuacct` @0x5a269b | **present** |
| CGROUP_SCHED (+RT_GROUP_SCHED) | `cpu_cgroup_create` @0x6f71c, `cpu_cgroup_populate` @0x5eb4c, `free_rt_sched_group`; runtime `/dev/cpuctl` | **present** |
| CGROUP_MEM_RES_CTLR (memcg) | no `mem_cgroup_*` | **absent** (the Nu3001 4.4 config enables it) |
| NETFILTER_XT_MATCH_QTAGUID | `qtaguid_mt` @0x39fca0; `net/netfilter/xt_qtaguid.c` @0x5ee697; `xt_qtaguid.ctrl_perms` @0x50053c | **present** (also registers the `owner` match) |
| NETFILTER_XT_MATCH_QUOTA2 | `quota_mt2_init` @0x1abec; `xt_quota2.event_num` @0x500614 | **present** |
| NETFILTER_XT_TARGET_IDLETIMER | `idletimer_tg_init` @0x1a6ac | **present** |
| WAKELOCK (3.0 Android) | `wake_lock_init` @0xa6624, `wakelocks_init` @0x98d4, `android_power_init` @0x9a6c; sysfs attributes `wake_lock` @0x5a5753 / `wake_unlock` @0x5a575d | **present** |
| EARLYSUSPEND | `register_early_suspend`; `wait_for_fb_sleep` @0x5a6174, `wait_for_fb_wake` @0x5a6186; `earlysuspend.debug_mask` @0x4bcc8c | **present** (no autosleep in 3.0) |
| TMPFS | `shmem_mknod` @0xd7e88, `shmem_show_options` @0xd82cc (both only with CONFIG_TMPFS); `nr_inodes` @0x5a97f3; runtime tmpfs on /dev, /mnt/secure, /mnt/asec, /mnt/obb | **present** [CONFIRMED runtime] |
| EXT4_FS | `ext4_fill_super` @0x172560; `ext4_init_fs` initcall; string `ext4` @0x59ab50; also `init_ext3_fs`, jbd/jbd2 | **present** |
| FUSE_FS | `fuse_fill_super` @0x1acf0c, `fuse_dev_operations`, `fuse_init` initcall; `fusectl` @0x5b64df | **present** |
| TUN | no `tun_*`/`tun_init`, no string `/dev/net/tun` | **absent** |
| SECURITY / SECURITY_SELINUX | no `selinux_*`, `avc_*`, `security_ops`/`register_security`, no `selinuxfs`; only `cap_capable` (commoncap) and `security.capability` @0x5b650e | **absent** (LSM off entirely) |
| AUDIT | no `audit_log_start` | absent |
| SYNC | `sync_fence_ioctl` @0x235398, `sync_fill_pt_info` @0x2352fc, `sync_fence_create`/`merge`/`wait`; tracepoint `include/trace/events/sync.h` @0x5be1d3. ioctl: SYNC_IOC_WAIT 0x40043E00, SYNC_IOC_MERGE 0xC0283E01 (+FENCE_INFO via `sync_fill_pt_info`) | **present**, ABI = Android 4.4 libsync. Backport in `drivers/base/sync.c`, enabled automatically by `select SYNC` from `ARCH_RK3026` |
| SW_SYNC (+user /dev/sw_sync) | `sw_sync_ioctl` @0x235948, `sw_sync_device_init` initcall; string `sw_sync` @0x5be300; ioctl 0xC0285700 (CREATE_FENCE) / 0x40045701 (INC) | **present** |
| Fence support in rk_fb (HWC 1.x) | no `rk_fd_fence_wait` and no fence calls in `rk_fb_*` (the Nu3001 `rk_fb.c` has them) | **absent** |
| ION (+ION_ROCKCHIP) | `ion_ioctl` @0x225f2c; `drivers/gpu/ion/ion.c` in the path list; `ion-rockchip` @0x5a02ed; ioctl ION_IOC_ALLOC=**0xC0104900** (16 bytes), FREE/MAP/SHARE/IMPORT 0xC0044901..; Rockchip 0xC010490A | **present, old 3.0 ABI** |
| ANDROID_PMEM | no `pmem*` in symbols or strings; no such option in the Kconfig of either tree | **absent** |
| USB_G_ANDROID | `android_usb` @0x5cdd8a, `android0` @0x5cdd96, `drivers/usb/gadget/android.c`; `android_usb_unbind` @0x29ac30 | **present** |
| — f_adb | `adb_function_bind_config` @0x29e988, `adb_read` @0x297674; string `android_adb` @0x4ecbf1 | **present** |
| — f_mass_storage | `mass_storage_function_bind_config` @0x29e8b4, `fsg_main_thread` @0x2a032c; `drivers/usb/gadget/f_mass_storage.c` @0x5cd654 | **present** |
| — f_mtp / ptp | `mtp_function_bind_config` @0x29f258, `ptp_function_bind_config` @0x29f24c, `mtp_ioctl` @0x29a440; `mtp_usb` @0x4ecbfd, `f_mtp` @0x5cd7ca | **present** |
| — rndis / accessory / audio_source / acm | `rndis_function_bind_config` @0x2a3d70; `accessory_function_bind_config` @0x29f0b8; `audio_source_function_bind_config` @0x2a180c; `acm_function_bind_config` | **present** |
| — functionfs (f_fs) | no `ffs_*` | absent |
| ANDROID_PARANOID_NETWORK | no direct symbol (inline checks in af_inet) | unknown (behaviour as in stock 4.2) |
| UID_STAT, ALARM_DEV, KEYCHORD, UHID, UINPUT, SWITCH, TIMED_GPIO | `uid_stat_init`, `alarm_dev_init`, `keychord_init`, `uhid_init`, `uinput_init`, `switch_class_init`, `timed_gpio_init` | present |
| DM_CRYPT, BLK_DEV_LOOP | `dm_crypt_init`, `loop_init` | present |
| SWAP | `sys_swapon` (not an alias of sys_ni_syscall) | present; ZRAM **absent** |
| KSM | no `ksm_*` | absent |
| SysV IPC / POSIX MQ / KEYS / AIO / perf / fanotify | `sys_semget`, `sys_mq_open`, `sys_add_key`, `sys_io_setup`, `sys_perf_event_open`, `sys_fanotify_init` are aliases of `sys_ni_syscall` | absent |
| Syscalls used by newer bionic (eventfd2, timerfd, signalfd4, epoll_create1, pipe2, accept4, dup3, inotify_init1, sendmmsg, prlimit64, setns, syncfs) | all present as real functions | present |
| /proc/sys: `kptr_restrict`, `dmesg_restrict`, `mmap_min_addr`, `/proc/<pid>/oom_score_adj` | strings @0x5a33e7, @0x5a33d8, @0x5a35fb, @0x5ad0e9 | present |
| IKCONFIG / MODULES / MODVERSIONS | no `IKCFG_ST`; `proc_modules_init`, .ko files load; no `__crc_*` | IKCONFIG absent, MODULES present, **MODVERSIONS absent** |
| KALLSYMS | `kernel/kallsyms.c` @0x5a56de, tables extracted | present (KALLSYMS_ALL apparently off) |

Netfilter as a whole (initcalls): conntrack (+helpers ftp/h323/irc/pptp/sip/tftp/…), NAT IPv4 (`nf_nat_standalone_init`; MASQUERADE/NETMAP/REDIRECT), iptables filter/mangle/raw, ip6tables filter/mangle/raw (no NAT6), xt matches comment/connbytes/connlimit/conntrack/hashlimit/helper/hl/iprange/length/limit/mac/mark/connmark/pkttype/policy/**qtaguid**/**quota**/**quota2**/socket/state/statistic/string/time/u32, targets CLASSIFY/NFLOG/NFQUEUE/TPROXY/TRACE/**IDLETIMER**/LOG/REJECT. SECMARK/CONNSECMARK are absent (Nu3001 4.4 has them, but they are only needed together with SELinux).

## 3. RC2 drivers and hardware in the kernel

| Subsystem | Evidence | Verdict |
|---|---|---|
| EBC (E-Ink controller) | `rk29_ebc_probe` @0x205254, `rk29_ebc_init` (initcall 6s), `ebc_io_ctl`, `get_ebc_waveform_addr` (+ cmdline `waveform_addr=`), `epd_lut_data_get_pvi`, `epd_lut_from_{array,file,nand,rk_spi,gpio_spi}_init`, `epd_spi_flash_register`, `ebc_buf_*`, `boot_ani_*`, `direct_mode_sARM`/`check_auto_image_sARM` (from the `.uu` objects); chrdev `261 ebc` | present (built-in) |
| EPD PMIC tps65185 (papyrus) | `tps65185_probe` @0x20f238, `papyrus_set_vcom_voltage`, `tps65185_vcom_set/get`; path `drivers/video/rockchip/rk_epd/epdpower/tps65185.c` @0x5bad97 | present |
| Waveform SPI flash | `spi_flash_probe` @0x4ac604, `spi_flash_init`, `vflash_init`; chrdev `250 spi_flash` | present |
| Touch | `cyttsp4_core_probe` @0x2bc060 (+i2c/mt/device_access), `goodix_ts_probe` @0x2b490c (+`gt91xx_config_*`, `gup_*`) | present |
| PMIC / RTC / fuel gauge | `act8931_set_ldo` @0x5724c (+`act8931_charge_*`, an ONYX patch), `wm831x_i2c_init`, `hym8563_init` @0x15988, `cw_bat_init` @0x162ec (CW201x), `rk30_adc_init` | present |
| Storage | `rknand_init` @0x136dc (base in the kernel, FTL in `rk30xxnand_ko.ko`), `rk29_sdmmc_init` @0x16d3c, `mmc_blk_init`; cmdline `onyx_emmc=1` @0x39c8c, `[ONYX]Setup emmc boot` @0x59ff10 | present |
| Display | `rk_fb_*`, `rk3188_lcdc_module_init`, `rk3026_lvds_init`, `rga_init` @0x119fc | present |
| GPU / VPU / IPP | **not in the kernel**: external modules `mali.ko` (r3p2-01rel0, API_VERSION=19, USING_UMP=y), `ump.ko`, `vpu_service.ko`, `rk29_ipp` (`rk29-ipp.ko`, vermagic 3.0.8+!), see [`/proc/modules`](../device/proc/proc_modules.txt) | modules |
| Wi-Fi / BT | `rkwifi_sysif_init`, `rfkill_rk_init`, `cfg80211`/`mac80211` built in; Wi-Fi drivers and `rtk_btusb` are modules | present / modules |
| ONYX-specific | `onyx_misc_driver_init` @0x13054; sysfs names `pmic_temp` @0x5be8fb, `vcom_value` @0x5be905, `verify` @0x5be91e, `input_disable` @0x5be925, `support_regal` @0x5be933, `hall_en` @0x5be941; `onyx_get_pcb_version`, `onyx_hall_sensor_power`, `onyx_tp_power_enable`, `onyx_wifi_bt_module_power`, `onyx_vibrator_enable`, `onyx_keypad_control_get`, `hallsensor_disable_set`; `[ONYX] pcb version is [%s]` @0x59f95d; chrdev `247 leds-ctl` | present (non-public ONYX patches) |

## 4. Comparison with defconfigs

All three defconfigs are saved with `savedefconfig`: a missing option means the Kconfig default. SYNC/SW_SYNC are not listed anywhere, but `ARCH_RK3026` `select`s them (`arch/arm/Kconfig:1111-1112`) in both trees, so they are effectively `=y` everywhere.

| Option | rychly `rk3026_epd_defconfig` | rychly `rk3026_tb_epd_defconfig` | Nu3001 `rk3026_86v_android-4.4_defconfig` | **stock RC2 (from the Image)** |
|---|---|---|---|---|
| BINDER / ASHMEM / LOGGER / LMK | y | y | y | **y** |
| CGROUPS, FREEZER, CPUACCT, CGROUP_SCHED, RT_GROUP_SCHED | y | y | y | **y** |
| RESOURCE_COUNTERS | y | y | y | y (not checked; irrelevant without memcg) |
| CGROUP_MEM_RES_CTLR (+_SWAP) | n | n | **y** | **n** |
| QTAGUID / QUOTA2 / IDLETIMER | y | y | y | **y** |
| WAKELOCK / SUSPEND_TIME / EARLYSUSPEND(def y) | y | y | y | **y** |
| TMPFS / EXT4 / EXT3 / FUSE / VFAT | y | y | y | **y** |
| EXT3/EXT4_FS_XATTR | **n** | y(def) | y | unknown (irrelevant without SELinux) |
| EXT3/EXT4_FS_SECURITY | n | n | **y** | n (no LSM) |
| SECURITY / SECURITY_NETWORK / SECURITY_SELINUX | n | n | **y** | **n** |
| AUDIT | n | n | **y** | **n** |
| NF_CONNTRACK_SECMARK, XT_TARGET_(CONN)SECMARK, IP_NF_SECURITY | n | n | **y** | **n** |
| TUN | n | n | **y** | **n** |
| ZRAM / ZSMALLOC | n | n | **y** | **n** |
| KSM | n | n | **y** | **n** |
| SYNC / SW_SYNC | y (select) | y (select) | y (select) | **y** |
| Fences in rk_fb (code, not an option) | no | no | **yes** (`rk_fd_fence_wait`) | **no** |
| ION / ION_ROCKCHIP | y | y | y | **y** (old ABI) |
| VIDEO_RK29_CAMMEM_ION, VIDEO_RK29 (camera) | n | y | y | n (no camera) |
| RK29_VPU (built-in) | n | n | y | n (`vpu_service.ko`, module) |
| USB_G_ANDROID (default in the choice) | y | y | y | **y** (adb/mtp/ptp/ums/rndis/acc/audio) |
| EBC / EPD (`CONFIG_EBC`, boot animation) | y (A2, LOOP) | y (FULL) | n | **y** |
| Panel | V220_EINK_1024X758 | V220_EINK_800X600 | LCD_RK2926_V86 | 1448×1072 per the panel info in the Image (`set_epd_info`); the Kconfig panel choice itself is not recoverable |
| MACH | RK3026_TB | RK3026_TB | RK3026_86V | ONYX board (unknown) |
| Regulator/PMIC | ACT8931 | ACT8846/TPS65910/WM831X | ACT8846/TPS65910/WM831X | ACT8931 + WM831X |
| RTC | HYM8563 | WM831X/TPS65910 | WM831X/TPS65910 | HYM8563 |
| Touch | GT813 (goodix) | — | GSLX680 | goodix + **cyttsp4** |
| Fuel gauge | RK30 ADC | RK30 ADC | RK30 ADC (AC) | RK30 ADC + **CW201x** |
| Wi-Fi | RTL8188EU | RKWIFI | — | rkwifi sysif + modules |
| IDLE (`/dev/idle`), RK_CLOCK_PROC | y | n | n | `idle_init` present (chrdev `252 idle`) |
| KALLSYMS | n(def?) | — | — | **y** |

Conclusion of the comparison: functionally the stock kernel nearly matches rychly `rk3026_epd_defconfig` (the same Android kernel without SELinux, EBC built in, ACT8931, HYM8563, goodix) plus the non-public ONYX additions (cyttsp4, CW201x, onyx_misc, leds-ctl, hall). The Nu3001-4.4 delta relative to stock is exactly "Android 4.4 hardening": SELinux+AUDIT+SECMARK, TUN, memcg, ZRAM, KSM, fences in rk_fb.

## 5. Which tree the stock kernel is closest to

Trees: [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources) and [Nu3001/kernel_rk3188](https://github.com/Nu3001/kernel_rk3188).

1. **`__FILE__` paths** (569 unique): 568 exist in both trees. `drivers/video/rockchip/rk_epd/epdpower/tps65185.c` exists **only in rychly**.
2. **kallsyms symbols against source tokens** (25 767 unique names after normalisation): in both trees 23 113; **only in rychly 192**; **only in Nu3001 0**; in neither 2 462.
   - Only rychly: the whole E-Ink/EBC stack (`ebc_*`, `epd_lut_*`, `papyrus_*`, `tps65185_*`, `boot_ani_*`, `buf_list_*`), `act8931_charge_*`, the `cyttsp4_*` bus, goodix-tool (`gtp_*`, `gup_*`), `rk3026_pm_*`, `ping_v4_*` (ICMP ping sockets), `idle_init`, `lm_proc_init`.
   - In neither: macro-generated names (ftrace/`fops_*`/`format_*`); functions from the precompiled `.uu` objects (the EBC core `rk29_ebc_*`, `DONE_BUFFER*`, the cyttsp4 driver: rychly only has `cyttsp4.uu` and headers); **ONYX patches**: `onyx_*` (26), `support_regal_get`, `input_disable_{get,set}`, `hallsensor_disable_*`, `vcom_{get,set}`, `act8931_charge_level_*`, `leds_*` (leds-ctl), `spi_flash_*`, `rk29_keys_early_*`, `bt_pwr_*`, `cw_disable_batt_low_irq`, `rk3026_readefuse`.
   - The Nu3001 marker (`rk_fd_fence_wait` in rk_fb) is **absent** from the Image.
3. **Driver versions:** `rk_serial.c v1.4 2013-04-16` (@0x5bcbbb) exists only in rychly; `sensor-dev.c v1.4 … 2013-09-01` in both; `rknand_base.c version: 4.40 20130420` in neither (rknand is a `.uu` there).

**Result:** the stock kernel was built from a tree of the same generation as **rychly `rk3026-linux-sources`** (Rockchip RK3026 E-Ink SDK, 2013), with ONYX patches on top. It differs from Nu3001 `kernel_rk3188` (the 4.4 branch) by the absence of fence code in rk_fb and the presence of the E-Ink stack. The ONYX strings (`onyx_misc`, `support_regal`, `hall_en`, `vcom_value`, `pmic_temp`, `verify`, `input_disable`, `onyx_get_pcb_version`, `onyx_bootmedia`, `onyx_emmc`, `hallsensor_disable`, `onyx_vibrator`) are **found in neither rychly nor Nu3001** (master and kitkat; the hits for `input_disable`/`pcb_ver` are the unrelated `rfkill_input_disabled`/`rpcb_version`). So the ONYX kernel patches have not been published [STRONG].

## 6. Notes

- `rk29-ipp.ko` is built with vermagic **3.0.8+** but loads anyway (apparently forced or an outdated check).
- The loader builds the kernel command line. `parameter` has `initrd=0x62000000,0x00800000`, while the runtime `/proc/cmdline` has `…,0x00130000`, so the loader substitutes the actual ramdisk size; the ramdisk must fit the 8 MiB window from `parameter`. The loader also appends `bootver=… firmware_ver=…` itself. `onyx_emmc=1 pcb_ver=2` come from `parameter`; the kernel reads `onyx_emmc=`/`pcb_ver=` through `__setup` (`onyx_bootmedia_setup`, `onyx_pcb_ver_setup`). [STRONG] See [`../device/README.md`](../device/README.md).

## 7. Method

`strings -a -t x -n 4` → grep; [`extract_kallsyms.py`](extract_kallsyms.py); `objdump -D -b binary -m arm --adjust-vma=0xc0408000` over function ranges from kallsyms for the ioctl constants; token comparison of the symbols against the rychly and Nu3001 trees (read only).
