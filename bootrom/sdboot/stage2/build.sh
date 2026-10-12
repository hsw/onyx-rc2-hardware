#!/bin/bash
# SPDX-License-Identifier: MIT
# Build sdboot stage2 with LLVM (clang + ld.lld). Reproducible: same toolchain -> same bytes.
# usage: build.sh OUTDIR
# Toolchain: $LLVM (directory with clang, llvm-objcopy, llvm-objdump, llvm-nm) and $LLD (ld.lld). Defaults: the Homebrew
# kegs on macOS if present, else the tools on PATH.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out=${1:?usage: build.sh OUTDIR}
if [ -z "${LLVM:-}" ]; then
  if [ -x /opt/homebrew/opt/llvm/bin/clang ]; then LLVM=/opt/homebrew/opt/llvm/bin
  else LLVM=$(dirname "$(command -v clang)"); fi
fi
if [ -z "${LLD:-}" ]; then
  if [ -x /opt/homebrew/opt/lld/bin/ld.lld ]; then LLD=/opt/homebrew/opt/lld/bin/ld.lld
  elif [ -x "$LLVM/ld.lld" ]; then LLD=$LLVM/ld.lld
  else LLD=$(command -v ld.lld); fi
fi
sha256() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }
mkdir -p "$out"
CFLAGS=(--target=armv7a-none-eabi -mcpu=cortex-a9 -marm -mfloat-abi=soft -mno-unaligned-access
        -ffreestanding -fno-builtin -fno-common -fno-pic -fno-stack-protector -fno-exceptions -fno-unwind-tables
        -fno-asynchronous-unwind-tables -ffunction-sections -fdata-sections -Os -Wall -Wextra -Werror
        "-ffile-prefix-map=$here=stage2" "-fdebug-prefix-map=$here=stage2")
"$LLVM/clang" "${CFLAGS[@]}" -c "$here/start.S" -o "$out/start.o"
"$LLVM/clang" "${CFLAGS[@]}" -c "$here/stage2.c" -o "$out/stage2.o"
"$LLD" -T "$here/stage2.ld" --gc-sections --no-undefined --build-id=none -Map="$out/stage2.map" \
  "$out/start.o" "$out/stage2.o" -o "$out/stage2.elf"
"$LLVM/llvm-objcopy" -O binary "$out/stage2.elf" "$out/stage2.bin"
"$LLVM/llvm-objdump" -d --triple=armv7a-none-eabi --mcpu=cortex-a9 "$out/stage2.elf" > "$out/stage2.dis"
"$LLVM/llvm-nm" -n "$out/stage2.elf" > "$out/stage2.sym"
{ "$LLVM/clang" --version | head -1; "$LLD" --version; } > "$out/toolchain.txt"
( cd "$out" && sha256 stage2.bin stage2.elf > SHA256SUMS )
echo "stage2.bin $(wc -c <"$out/stage2.bin" | tr -d ' ') B  sha256 $(sha256 "$out/stage2.bin" | cut -d' ' -f1)"
