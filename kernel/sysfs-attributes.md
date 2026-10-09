# sysfs attributes of the stock RC2 kernel: ONYX nodes (rk29-keypad, onyx_misc)

Extracted 2026-10-08 from the stock Image (built 2017-11-07, sha256 `47a13cf3…30af`, not public) without the device. These are the
nodes behind the capacitive-key, vibration, Hall and LED controls of the ONYX framework class `android.hardware.DeviceController`.
Confidence: what the code does [STRONG] (disassembly of this exact Image); what the physical buttons/hardware are [VERIFY].

## Method (reproducible)

- Image: the uncompressed ARM stock kernel Image (not in this repository), **VA = file offset + 0xC0408000** (not 0xC0008000; an early
  pass with the wrong base produced bogus addresses). Symbols: recovered from the Image with [`extract_kallsyms.py`](extract_kallsyms.py).
- `sysfs_attrs.py` scans the Image for `struct device_attribute` = 4 words `{name, mode, show, store}` (no lockdep on this kernel):
  name → printable string, mode ≤ 0777, show/store = 0 or exactly a text symbol. The full list has 787 attributes.
  `--refs` adds the strings/symbols in the handlers' literal pools:
  `python3 -I sysfs_attrs.py IMAGE kallsyms.txt '^(touchkey|vibrator|hall_en)' --refs`
- Control flow: GNU binutils objdump disassembles the raw Image directly, addresses are VAs:
  ```
  objdump -D -b binary -m arm --adjust-vma=0xc0408000 \
      --start-address=0xc06b1d44 --stop-address=0xc06b1e44 IMAGE
  ```
  LLVM alternative: wrap once with
  `llvm-objcopy -I binary -O elf32-littlearm IMAGE kimg.elf`, then `llvm-objdump -D --triple=armv7a --adjust-vma=0xc0408000`
  with `--start/--stop-address` given as **file offsets** (VA − 0xc0408000).
  Call targets resolve with kallsyms (e.g. `0xc05e7e48 strncasecmp`, `0xc04b865c disable_irq_nosync`, `0xc04b8720 enable_irq`).
- No LSM in this kernel ([`config-reconstruction.md`](config-reconstruction.md)): file mode is the only access control, so 0666 means any app uid can write.

## `/sys/devices/platform/rk29-keypad/` (driver `rk29-keypad`, input `event0`)

| Attribute | Mode | show / store | Contract |
|---|---|---|---|
| `touchkeyena` | 0666 | `onyx_keypad_control_get` / `onyx_touchkey_enable` | write `back`, `pageup` or `pagedown` (`strncasecmp` prefix of 4/6/8 chars, one key per write, else printk "Unknown key"); enables the irq of every board button with KEY_BACK 158 / KEY_PAGEUP 104 / KEY_PAGEDOWN 109 |
| `touchkeydis` | 0666 | `onyx_keypad_control_get` / `onyx_touchkey_disable` | same names, disables (`disable_irq_nosync`) |
| `vibrator` | 0666 | `onyx_keypad_control_get` / `onyx_vibrator_control` | first char `'0'` → off, anything else → on (stores the flag twice at `0xc0b522ec`, used by `onyx_vibrator_enable`) |
| `key_switching` | 0666 | `key_switching_status` / `key_switching_store` | `sscanf %d`, cases 0..8, else "Uknown key swithcing case"; show "Current Key Switching Case: %d". Case 0 (boot default) makes the left page key report KEY_BACK; case 1 makes it PAGE_UP [CONFIRMED on the device] |
| `rk29key` | 0660 | – / `rk29key_set` | Rockchip key-name remap (`menu`, `home`, `sensor`, `play`, `vol+`, `vol-`, `right`, `pageup`, `pagedown` → `MENU`…`VOLDOWN`); stock `init.rk30board.rc` writes it |
| `get_adc_value` | 0644 | `adc_value_show` | "adc_value: %d" |

**State read (any of the three ONYX nodes):** `"Vibrator:%d\nKEYBACK:%d\nKEYPAGEUP:%d\nKEYPAGEDOWN:%d\n"`, 1 = enabled. The key part
comes from a flag word at `0xc159205c` (bss; `0xc1592058` holds the key-switching case): bit 0 back, bit 1 pageup, bit 2 pagedown,
**set = disabled**. Enable acts only if the bit is set and disable only if it is clear, so repeated writes do not unbalance the irq
depth. Boot state: all enabled. Nothing persists across reboot.

**Board key table** (`0xc0a7166c`.., 44-byte entries): play→116 POWER, pageup→104, pagedown→109, ok→158, esc→158, menu→59.
The desc → code pairing is [STRONG]: in all six entries `code` sits 7 words before the `desc` pointer, `gpio` = −1 (INVALID_GPIO)
5 words before it, and `adc_value` 3 words before it. Public `rk29_keys_button` (rychly `arch/arm/plat-rk/include/plat/key.h`)
is only 32 bytes (`code, code_long_press, gpio, adc_value, adc_state, active_low, desc, wakeup`), so ONYX extended the struct. The
rychly `board-rk3026-ebook.c` table (`flush` F5, `esc` KEY_BACK, `pageup`/`pagedown` on GPIO) is a different board; it confirms only
`esc` = KEY_BACK. Which physical key is `ok` and which is `esc` (both 158, ADC 302/400) is not in any source [VERIFY on device]. Two buttons carry 158. `key_switching` remaps codes at report time (the table
stays), and in case 0 the left page key reports 158 like the bottom key. So `back` very likely
switches **both** the bottom key and the left page key, and `pageup` the button whose table code is 104 [VERIFY with `getevent`].
The face keys are capacitive; kernel log "Keycode [104] config changed to GPIO[205]".

**Correction** (from the later board-file pass, [`../board/README.md`](../board/README.md) §3 and §7c): the ADC values above are shifted
by one entry. The table is ok 158 ADC 505, esc 158 ADC 302, menu 59 ADC 400; on pcb V1.73 pageup, pagedown and esc are rewritten
to GPIO keys at boot (GPIO2_B5/B6/C3), so the physical BACK is the `esc` entry on GPIO2_C3, and `ok` (ADC) is probably not fitted.

## `/sys/devices/platform/onyx_misc.0/` (driver `onyx_misc`; the device exists on the RC2, [stock platform-device list](../device/proc/sys_bus_devices.txt))

| Attribute | Mode | show / store | What it does |
|---|---|---|---|
| `hall_en` | 0666 | `hallsensor_disable_get` / `_set` | only when `onyx_get_pcb_version() == 3` ("v176"); otherwise printk "Do not support hall sensor control below pcbv176" and return −ENODEV (`mvn r0,#18`) — the read fails, which stock Java turns into its −19. The version comes from cmdline `pcb_ver=` (`onyx_pcb_ver_setup`); this RC2 boots with `pcb_ver=2` ([`/proc/cmdline`](../device/proc/proc_cmdline.txt)), so most likely unsupported [VERIFY: `cat hall_en`]. Power via `onyx_hall_sensor_power` (regulator `act_ldo1`) |
| `bt_pwr` | 0666 | `bt_pwr_get` / `bt_pwr_set` | `'1'` → `onyx_combo_module_bt_power(1)`, else 0: BT power of the Wi-Fi/BT combo (shared with Wi-Fi by a refcount, [`../board/README.md`](../board/README.md) §4) |
| `hp_ctl` | 0666 | `hp_ctl_get` / `hp_ctl_set` | `'1'` → delayed work after 20 ms, else `codec_set_spk(0)`: speaker-amplifier enable; on pcb V1.73 its GPIO is −1, so it is a no-op ([`../board/README.md`](../board/README.md) §8.2) |
| `input_disable` | 0666 | `input_disable_get` / `_set` | stores `first char == '1'` in a flag at `0xc0d3b46c`; when set, `input_event()` drops every input event ([`../board/README.md`](../board/README.md) §7a) |
| `verify` | 0666 | `verify_get` / `verify_set` | anti-tamper challenge: md5 over `oN-%s-%s-Yx` with `vdd_cpu`, "Exists"/"Non-exists"/"Check failed"; used by stock `DeviceController.systemIntegrityCheck` |
| `support_regal` | 0444 | `support_regal_get` | `%d`; SF/gralloc REGAL support flag |
| `vcom_value` | 0666 | `vcom_get` / `vcom_set` | "Set Vcom value [%d]"; a write programs the TPS65185 VCOM EEPROM (EBC-driver analysis, [onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc)) |
| `pmic_temp` | 0444 | `temp_get` | `%d`; always prints "25", it never reads the PMIC (EBC-driver analysis) |

Also EPD: `vcom_mv` 0666 (`vcom_mv_get/_set`, "set vcom to: %dmV", tps65185 side; reads return the VCOM cached at probe in 10 mV units, writes program the PMIC EEPROM). Touch: `virtualkeys.cyttsp4_mt` 0444.
