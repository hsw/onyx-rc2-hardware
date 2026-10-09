# Power-management tools

Static-analysis helpers used for [`../README.md`](../README.md). They only read the kernel Image; nothing is executed.

| File | What it does |
|---|---|
| `kdis.py` | GNU objdump over a VA range or one function of the raw Image, annotated with kallsyms names and strings; `--callers` scans the text for BL/B and pointer references |
| `kwords.py` | dump 32-bit words at VAs, resolving pointers to strings (tables such as `pm_states[]`, the suspend ops, the keypad table) |
| `sram_extract.py` | cut the SRAM suspend code and data out of the Image and write a labelled listing (labels from this analysis) |
| `run.sh` | everything at once for the functions in `pm.list` |
| `pm.list` | the functions dumped by `run.sh` |

Inputs (not in this repository):
- **IMAGE**: the raw (uncompressed) stock RC2 kernel Image. All addresses refer to the stock RC2 kernel built 2017-11-07 (firmware
  1.8.2, sha256 `47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af`), which is not public. The public firmware update
  (1.9.1, from the ONYX support page linked in the top-level README) carries a 2019-11-05 kernel; whether these addresses match there
  is [VERIFY] (the EBC driver span was checked and matches; the board and PM code were not). `run.sh` and `sram_extract.py` check
  the sha256.
- **KALLSYMS**: `python3 -I ../../kernel/extract_kallsyms.py IMAGE kallsyms.txt`.
- Env: `OBJDUMP` (GNU objdump with ARM support; default `objdump`).

```
python3 -I kdis.py IMAGE kallsyms.txt rk3026_pm_enter
python3 -I sram_extract.py IMAGE out/
./run.sh IMAGE kallsyms.txt out/
```

The outputs are derived from vendor code; keep them local.
