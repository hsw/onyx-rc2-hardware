#!/bin/bash
# SPDX-License-Identifier: MIT
# Decompile the ONYX board file of the stock RC2 kernel Image with Ghidra (headless, raw binary import) and write
# annotated objdump listings. Same approach as the EBC-driver tools (function list instead of an address range).
# Usage: run.sh IMAGE KALLSYMS OUTDIR WORKDIR
#   IMAGE     raw (uncompressed) stock RC2 kernel Image, 2017-11-07 build (sha256 checked below)
#   KALLSYMS  symbol list written by ../../kernel/extract_kallsyms.py IMAGE KALLSYMS
#   OUTDIR    where the listings and the decompilation go (vendor code: do not redistribute)
#   WORKDIR   scratch dir for the Ghidra project and log
# Env: GHIDRA_HEADLESS (Ghidra's analyzeHeadless; default: analyzeHeadless on PATH), JAVA_HOME (a JDK for Ghidra),
#      OBJDUMP (GNU objdump with ARM support), RY_IOMUX (optional, see kdis.py).
# Needs: Ghidra 12.1.4, a JDK (21 was used), GNU binutils, python3. The Image is only read, never executed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ $# -ne 4 ]; then
  echo "usage: $0 IMAGE KALLSYMS OUTDIR WORKDIR" >&2
  exit 2
fi
IMG="$1"
SYMS="$2"
OUT="$3"
WORK="$4"
GH="${GHIDRA_HEADLESS:-analyzeHeadless}"
echo "47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af  $IMG" | shasum -a 256 -c -
mkdir -p "$WORK/proj" "$OUT/fn"
"$GH" "$WORK/proj" rc2board -import "$IMG" -overwrite -noanalysis \
  -loader BinaryLoader -loader-baseAddr 0xc0408000 -processor ARM:LE:32:v7 \
  -scriptPath "$HERE" \
  -postScript ImportKallsymsRaw.java "$SYMS" "$HERE/board.list" \
  -postScript DecompileList.java "$OUT/board.decomp.c" "$HERE/board.list" \
  > "$WORK/ghidra.log" 2>&1
grep -E "ImportKallsymsRaw|DecompileList|ERROR|Exception" "$WORK/ghidra.log" | sed 's/^INFO  //' | head -40 || true
# objdump listings (the arbiter): board span, init-section board code, every listed function
python3 -I "$HERE/kdis.py" "$IMG" "$SYMS" 0xc045de28 0xc045f4cc > "$OUT/board-span.s"
python3 -I "$HERE/kdis.py" "$IMG" "$SYMS" 0xc040e264 0xc040ecc0 > "$OUT/init-board.s"
grep -v '^#' "$HERE/board.list" | while read -r f; do
  [ -n "$f" ] && python3 -I "$HERE/kdis.py" "$IMG" "$SYMS" "$f" > "$OUT/fn/$f.s" 2>/dev/null || true
done
# board .data (platform devices and platform data, resolved through literal pools)
python3 -I "$HERE/kdump.py" "$IMG" "$SYMS" 0xc0a70f90 1500 > "$OUT/board-data.txt"
python3 -I "$HERE/kdump.py" "$IMG" "$SYMS" 0xc042bb08 110 > "$OUT/board-initdata.txt"
python3 -I "$HERE/kdis.py" "$IMG" "$SYMS" --callers $(grep -v '^#' "$HERE/board.list" | head -58) > "$OUT/callers.txt"
echo "outputs in $OUT"
