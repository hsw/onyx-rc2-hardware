# Board-file tools

Static-analysis helpers used for [`../README.md`](../README.md). They only read the kernel Image; nothing is executed.

| File | What it does |
|---|---|
| `kdis.py` | GNU objdump over a VA range or one function of the raw Image, annotated with kallsyms names, strings, data pointers, GPIO numbers (`128 + 32*bank + 8*port + pin`) and RK3026 iomux codes; `--callers` scans the text for BL/B and pointer references |
| `kdump.py` | word dump of `.data`/`.init.data` at a VA with the same annotations (platform devices and platform data) |
| `run.sh` | everything at once, plus a Ghidra headless decompilation of the functions in `board.list` |
| `ImportKallsymsRaw.java`, `DecompileList.java` | Ghidra postScripts used by `run.sh`: split the raw import into text/rodata/data/bss, label all kallsyms symbols, decompile a list |
| `board.list` | the 104 functions (board file, its consumers, `onyx_misc`, leds-ctl, codec, vibrator) |

Inputs (not in this repository):
- **IMAGE**: the raw (uncompressed) stock RC2 kernel Image. All addresses in these tools and in the README refer to the stock RC2
  kernel built 2017-11-07 (firmware 1.8.2, sha256 `47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af`), which is
  not public. The public firmware update (1.9.1, from the ONYX support page linked in the top-level README) carries a 2019-11-05
  kernel; whether the board-file function addresses match there is [VERIFY] (the EBC driver span was checked and matches; the board
  code was not). `run.sh` checks the sha256 and refuses another Image.
- **KALLSYMS**: `python3 -I ../../kernel/extract_kallsyms.py IMAGE kallsyms.txt` (format: `VA type name` per line).
- Env: `OBJDUMP` (GNU objdump with ARM support; default `objdump`), `RY_IOMUX` (optional path to `arch/arm/mach-rk3026/include/mach/iomux.h`
  of [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources), for iomux names), `GHIDRA_HEADLESS`, `JAVA_HOME`.

```
python3 -I kdis.py IMAGE kallsyms.txt machine_rk30_board_init
python3 -I kdump.py IMAGE kallsyms.txt 0xc0a70f90 1500
./run.sh IMAGE kallsyms.txt out/ work/
```

The outputs (listings, `board.decomp.c`) are derived from vendor code; keep them local.
