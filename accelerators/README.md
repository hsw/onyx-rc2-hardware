# RK3026 accelerators: what was checked on the RC2

Every hardware accelerator in the RK3026 that a reader could use (video and JPEG, 2D, image processing, GPU, crypto),
and only what was **seen or measured on one RC2** (pcb V1.73): under the stock kernel (3.0.36+, Android 4.2.2) and under
an out-of-tree mainline kernel (7.1.13 with RK3026 patches, [`../mainline/README.md`](../mainline/README.md) §0) booted
from microSD. Capabilities that only the datasheet states are left out; addresses and interrupts of every block are in
[`../soc/README.md`](../soc/README.md) §1–2. Everything below is **[CONFIRMED]** (on the device) unless marked.

## Summary

| Block | Base | Stock kernel on the RC2 | Mainline on the RC2 |
|---|---|---|---|
| VPU (Hantro VEPU + VDPU, JPEG) | 0x10104000 | driver up, encoder id 0x8270; Gallery decodes H.264 through it, if ION has the memory | **`hantro` works** with an RK3026 variant (decoder at +0x200): H.264 and VP8 bit-exact up to 1080p, MPEG-2 right, post-processor right after a driver fix, JPEG encode; needs ~96 MiB CMA for 1080p through the post-processor |
| RGA, first generation (2D) | 0x1010c000 | driver up, measured: ~650 MB/s read, no grey (Y8) output, two driver bugs | no driver (mainline `rga` is RGA2+) |
| IPP | — | module loaded, but `/dev/rk29-ipp` is never created: every user falls back to software | — |
| IEP, CIF | 0x10108000, 0x1010a000 | no driver, never used | clocks gated at idle, nothing else |
| GPU Mali-400 MP2 | 0x10090000 | vendor `mali`/`ump`, EGL/GLES probed ([`../gpu/README.md`](../gpu/README.md)) | **lima works**: render node, Mesa, glmark2, devfreq 192–384 MHz, glamor |
| Crypto engine | 0x10200000 | never used (secure boot is off) | correct SHA-1/SHA-256 at ~150 MB/s from userspace; AES-128/192/256 and DES/TDES pass their known answers; AES over DMA right, 32 MB/s; `rk3288_crypto` does not fit ([`../soc/README.md`](../soc/README.md) §1.5) |
| CPU (NEON) crypto | — | OpenSSL with NEON measured | kernel `aes-neonbs` +20–42 % over scalar AES |

## VPU (Hantro), 0x10104000

- Stock `/proc/iomem`: `vpu 10104000-10107fff` with `vepu_io 10104000-1010417f` and `vdpu_io 10104200-10104393`;
  interrupts 38 `vepu` and 39 `vdpu` registered (GIC IDs; `GIC_SPI 6`/`7`), `/dev/vpu_service` present
  ([`../device/proc/`](../device/proc/)).
- Every stock boot log shows `VPU_SERVICE: checking hw id 8270`: the encoder reports **0x8270**.
- Stock Gallery plays H.264 through `RkOn2Decoder` → `libvpu`, which takes its buffers from ION: about 5–6 MB for a 360p
  clip and 18 MB for 720p. With a 20 MB ION carve-out the 720p clip logs hundreds of `ION_IOC_ALLOC … Out of memory`
  lines; with no ION carve-out there is no hardware decoder at all (`MediaPlayer error (1,1)`). A 5 MP JPEG in Gallery
  uses no ION, so it is decoded in software [STRONG].
- The software fallback is not a way out on stock: with `OMX.google.h264` the vendor `SoftwareRenderer` crashes
  mediaserver at 360p (a 640×368 buffer against a 640×360 crop) and freezes at 720p.

### What the silicon reports

Read on the RC2 (2026-11-03) under mainline with the VPU clock gates opened by hand, nothing written. Field layout after
Hantro's `dwl_defs.h` (synthesis words at decoder registers 50, 54, 57 and the post-processor's at 100) and the vendor
`vpu_service.h`.

| Register | Value | Meaning |
|---|---|---|
| encoder ID (+0x000) | `0x82701110` | product **0x8270**, the smaller H1: its registers end at 0x200, so the **decoder sits at +0x200**, not +0x400 |
| decoder ID (+0x200) | `0x67311148` | product **0x6731**, the G1 of the RK3066/RK3188 class |
| decoder reg 50 (synthesis 1) | `0xFBB56F80` | H.264 high profile, MPEG-4 ASP, MPEG-2, VC-1 advanced profile, JPEG (not progressive), VP6, Sorenson Spark, reference buffer, post-processor present, max width **1920** |
| decoder reg 54 (synthesis 2) | `0xE4C00000` | **VP8 yes**, RealVideo yes, AVS yes, JPEG extensions, custom MPEG-4; VP7 no, MVC no, no double reference buffer |
| decoder reg 57 (fuse) | `0xFFF7FFFF` | every codec fuse set except AVS (bit 19); all width fuses set |
| post-processor reg 100 | `0x1B870780` | scaling, deinterlacing, alpha blending, dithering; max output width 1920. Reg 99 (PP fuse) `0xFFFFFFFF` |
| encoder reg 63 | `0x1B522780` | max encode width 1920; H.264 and JPEG; no VP8 encode [STRONG: bit layout not checked against a source] |

Nothing is fused off. The vendor kernel reads its second config word from register 51, which reads 0 on this G1, so its
`get_hw_info()` reports no VP8 or RealVideo here although the silicon has them.

### Mainline (`hantro`)

The block is RK3066's with the smaller encoder, so mainline's `rk3066_vpu_variant` (decoder at +0x400 for the 0x4831
encoder) does not fit. Out of tree ([github.com/hsw/linux](https://github.com/hsw/linux), branch `rc2/vpu-hantro`), measured
on the RC2 2026-11-03/04 [CONFIRMED-device unless marked]:

- **Variant and node:** `rockchip,rk3026-vpu`, RK3066's decoder formats, codec ops and post-processor at `dec_offset 0x200`;
  codecs H.264, MPEG-2 and VP8 decode plus JPEG encode (what mainline's `hantro` offers for this generation; the silicon's MPEG-4,
  VC-1 and JPEG decode it does not drive). Node: `reg <0x10104000 0x800>`, interrupts `GIC_SPI 6` (`vepu`)
  and `GIC_SPI 7` (`vdpu`), clocks `aclk_vdpu` (CLKGATE_CON3 bit 11; it needed its own clock id), `aclk_vcodec` and the
  shared `hclk_vcodec`, both AXI clocks parented to GPLL. **No power domain and no IOMMU**, so every buffer is physically
  contiguous (CMA). Both video nodes bind; decoder `v4l2-compliance` 50/50.
- **Decoder: bit-exact.** H.264 Constrained Baseline, Main and High (B-frames, CABAC) at 320x240, 640x480, 854x480,
  1280x720 and 1920x1080, and VP8 at 640x480 to 1080p: NV12 output equals a software decode on every frame (11 clips,
  422 frames), twice, deterministic. MPEG-2 480p: PSNR 71.8 dB against software (MPEG-2 allows IDCT mismatch, so not
  bit-exact by design). 1080p H.264 High: 50 frames in 1.36 s (~37 fps, 0.2 s CPU) against 5.0 s with two-thread
  software decode.
- **Post-processor (NV12 → YUYV in the decoder's pipeline): needs a driver fix.** The G1 PP takes its input height in
  macroblocks as 8 bits in register 72 plus a 3-bit extension in register 92 (bits 10:8 of the same count). Mainline
  shifts the height in *lines* into the extension, so any input of 256 lines or more gets an extension of 1: 640x480 is
  programmed as 286 MB rows, 1280x720 as 301. The picture is right except the **bottom-left 48 pixels of the last 4
  lines**: garbage Cr for H.264 (non-deterministic low bits), and for VP8 a damaged reference that every inter frame
  predicts from (key frames right). 320x240 (extension 0) and, measured, 1920x1080 came out right. With the macroblock
  count shifted instead all 241 PP frames at 480 and 720 lines and both 1080p clips equal the model. The bug is in the
  generic G1 post-processor code, not RK3026-specific.
- **JPEG encode:** works once the encoder's coded `sizeimage` is clamped: GStreamer asked for **32 MiB** per CAPTURE
  buffer (8192x8192/2, the format's maximum), which a 32-96 MiB CMA area cannot serve. Clamped to the frame (615 024 bytes
  at 640x480) five JPEGs encode, PSNR Y 34.3 dB.
- **CMA needed** (default `shared-dma-pool`, `reusable`): 1080p H.264 to NV12 holds 33-46 MiB (each NV12 plus
  motion-vector buffer 1020 pages, bitstream buffers 765 pages); 1080p through the PP up to **88.5 MiB** (YUYV
  1920x1088 = 893 pages per buffer, up to 11, plus the decoder's own NV12 buffers). On a 96 MiB area that run hit three
  `-EBUSY` (not `-ENOMEM`) allocations: free pages existed, but each aligned range held a movable page that would not
  migrate. They were trailing buffer requests, so decoding went on with fewer buffers and stayed right. At 32 MiB a
  1080p NV12 decode still ran but left 1.6 MB free and retried on `-EBUSY`. The E-Ink controller's 4 MiB image region stays separate.
- **Clean unload:** after `rmmod hantro_vpu` no DMA mapping of the device is left (DMA-API debug).

## RGA (first generation), 0x1010c000

Stock driver (`rga: Driver loaded succesfully`, `/dev/rga` misc 10,60, interrupt 76 = `GIC_SPI 44`), measured with a
bench that copies the 1072×1448 RGBA framebuffer (6.2 MB):

- **The engine reads about 650 MB/s**: a full-frame bitblt from the (write-combining) framebuffer takes 16.9 ms wall,
  of which 8.0 ms CPU, against 25–27 ms (227–248 MB/s) for a CPU `memcpy` of the same frame. The CPU part is the
  driver's `get_user_pages` on the destination, about 5 µs per page. With the cache clean and the grey conversion the
  RGA path takes 28.1 ms wall / 19.2 ms CPU, no faster than converting straight from the framebuffer (26.5 ms); reading
  through a cacheable alias after a cache invalidate beats both. So the RGA saves CPU, not time.
- **No grey output**: the RGA1 has no YCbCr or Y8 destination. A Y8 request (format 0xa) is masked to `& 3` and writes
  RGBA5551; there are no RGB→Y coefficients. For an E-Ink pipeline the RGA can only produce RGB565/4444/5551 (exact
  truncation; 11.1 ms wall / 4.25 ms CPU to RGB565), and the grey conversion stays on the CPU.
- **Driver bugs**: without a cache clean before the blit 19 488 bytes came out wrong (dirty lines); with a source base
  that is not page-aligned `rga_buf_size_cal` ignores the in-page offset (3 584 wrong bytes). Page-aligned bases plus a
  `y_offset` avoid it.
- Mainline: mainline's `rockchip-rga` handles RGA2 and later only; nothing ran.

## IPP

The stock kernel loads `rk29_ipp` (`IPP init, version rk30-ipp 1.003`), but **`/dev/rk29-ipp` is never created**: every
library that opens it falls back to software. `/proc/iomem` carries an empty `ipp buf` reserve.

## IEP and CIF

Nothing on the device beyond their idle state: no stock driver, and under mainline their clocks are among the gates
closed at idle (below). No camera is fitted to the RC2.

## GPU: Mali-400 MP2, 0x10090000

Stock: the vendor `mali` (r3p2) and `ump` modules, `/dev/mali` and `/dev/ump`, interrupts 35–37 active; the EGL/GLES
probe is [`../gpu/README.md`](../gpu/README.md). The Mali driver holds about 52 MB in a running Android 4.4 system, 23 MB
of it in the launcher.

Mainline, `lima` with Mesa 25.0.7:
- lima binds as a render-only device (`renderD128`: GP, PP0, PP1, Mali-400 1.1) next to the E-Ink controller on `card0`;
  Mesa picks it without `MESA_LOADER_DRIVER_OVERRIDE`. kmscube, x11perf, glmark2 and a soak ran with no oops, MMU fault
  or job timeout; the panel picture matched X's picture to the pixel.
- **Clock**: brought up at `aclk_gpu` = CPLL/6 = 107 MHz, where stock idles at 128 MHz and its DVFS uses 192/256/384
  (384 never seen in use). glmark2: 39 / 66 / 81 at 107 / 192 / 256 MHz.
- **devfreq** with an OPP table of 192 / 256 / 384 MHz on GPLL scales 192 ↔ top and stops while runtime PM gates the
  clock: 1 h soak at 192/256 (glmark2 83 every run), 30 min with 384 (103), no fault or timeout; GPU-bound work
  1.40–1.45x over 256 MHz. All on the RC2's fixed 1.40 V supply.
- At idle `aclk_gpu` is gated without `clk_ignore_unused`.
- **glamor vs pixman** (x11perf, ops/s): fills 322 → 702, anti-aliased text 55 800 → 98 500, pixmap→window copy
  231 → 653; but window→window copy, composite and scroll drop from 225–237 to 96. Those last ones are the common case
  on a reader. The same-pixmap path is GPU-bound (PP 80–86 % busy, ~2.9 ms per job pair per 500-pixel op).
- A whole-buffer cache sync in the E-Ink driver costs +25 ms per full-screen commit (11.0 → 36.2 ms); the picture was
  identical with and without it.

## Crypto engine, 0x10200000

The register map, the interrupt, the byte order and the speed are in [`../soc/README.md`](../soc/README.md) §1.5; the
ROM's use of it in [`../bootrom/README.md`](../bootrom/README.md) §8. In short: correct SHA-1/SHA-256 at ~150 MB/s on
64 KiB (124 MB/s on 4 KiB, ~9.8 µs per message), input read as big-endian words; mainline `rk3288_crypto` bound to it
times out on every request. The block also has AES and DES/TDES at RK3288's register layout without `CONF`: fed by the
CPU, the FIPS-197 AES-128/192/256 vectors (encrypt and decrypt), DES and TDES-EDE3 all come out right, but only at
7.2 MB/s for AES, and CBC/CTR do nothing in that mode. Over its own DMA (source, destination and length in words at
`0x0c`/`0x10`/`0x14`, start `CTRL` bit 2) two-block ECB, CBC encrypt and CBC decrypt tests come out right. Memory
is byte-swapped per word on that path, and the engine's writes are not coherent with the CPU caches; the output is
in memory microseconds after the start. ECB over DMA runs at **32 MB/s** (64 KiB and 1 MiB alike), level with the
kernel's NEON AES below. So the engine saves CPU time, not wall time, on AES; on SHA-256 it is ~2.7x faster.

## CPU crypto with NEON

The Cortex-A9 has NEON but no ARMv8 crypto instructions (OpenSSL detects `ARMV7_NEON` only).

Mainline kernel, 912 MHz, MB/s on a 1504-byte TLS record (16 KiB in brackets):

| | scalar `aes-lib` | `aes-neonbs` (`CONFIG_CRYPTO_AES_ARM_BS`) |
|---|---|---|
| `ecb(aes)` | 22.5 (26.4) | 30.1 (38.3) |
| `cbc(aes)` | 18.3 | 22.0 |
| `ctr(aes)` | 20.5 (23.8) | 29.2 (37.8) |
| `gcm(aes)` | 15.9 (18.9) | 20.6 (26.1) |
| `xts(aes)` | — | 28.4 |

On 64-byte messages NEON is slightly slower (`ctr` 3.78 vs 4.16 MB/s): the bit-sliced key schedule is per request. Hashes
(arch-optimised library code): SHA-1 69.6 (104.6), SHA-256 43.1 (55.2), HMAC-SHA256 40.0 (54.2). All implementations
passed their known-answer tests.

Userspace OpenSSL 4.0.3 on the stock system, NEON on vs off, MB/s at 8–16 KiB: ChaCha20-Poly1305 101 vs 54.9, SHA-256
57.3 vs 40.8, SHA-512 35.9 vs 18.6, AES-CTR 42.8 vs 31.7, AES-GCM 18.7 vs 16.8; RSA-2048 sign 41.1 vs 24.1/s, verify
1969 vs 974/s. **ChaCha20-Poly1305 is 5.4x faster than AES-GCM on this CPU**, so a TLS client here should prefer it.

## Idle clock gating under mainline

Without `clk_ignore_unused` the kernel gates the unclaimed clocks (GPU, VPU, LCDC0 among 26), and USB, SD, I²C, the
E-Ink controller and KOReader keep working. With 13 more gates modelled (CIF, crypto, RGA, IEP, VDPU, …) the gate
registers CLKGATE_CON3/6/9 read `0x7bef` / `0x2c33` / `0x01a0`, the same values as under the stock kernel.

Power, measured as overnight battery drains on the CW2015 gauge (same kernel, same userspace, KOReader idle on a page,
frontlight off, Wi-Fi off, cable out; draw compared within the same voltage bands): the awake idle draw is about 0.9 W
with `clk_ignore_unused` and about 570 mW without it (-37 %), and a full charge lasts 17.1 h from 100 to 1 % instead of
about 12 h. Gating the same clocks at runtime with the gate bits alone saved only about 22 % (~200 mW), so part of the
saving may come from what the kernel does at boot beyond the gate bits (unused clocks unprepared, e.g. PLLs) [VERIFY].
Stopping KOReader's process at idle changed the draw by less than the method resolves (~50 mW).

## Not checked on the device

- The hardware JPEG decoder, the VPU's MPEG-4/VC-1 decode and its pre-processor, H.264 encoding, the post-processor's
  scaling (present in the synthesis word, not used by mainline).
- Any RGA, IEP or CIF access under mainline.
- The crypto engine's CTR mode and TDES over DMA, and its RSA unit.
