# RK3026 memory system on the RC2: DRAM, NoC arbitration, L2, display fetch

How the RK3026's masters reach DRAM, what arbitrates between them, and what the stock kernel sets that a mainline kernel
or boot loader has to set too. The case that drove it: under CPU memory load a mainline kernel's E-Ink scans garble the
panel while the driver sees nothing wrong (two independent causes, §4). Register facts that belong to the MMIO map stay in
[`../soc/README.md`](../soc/README.md) (§1.4 QoS port addresses, §3.6 the EBC fetch clock, §8 DDR init); the mainline kernel
in [`../mainline/README.md`](../mainline/README.md) §0.

Sources:
1. **The RC2 itself**: read-only register dumps (one aligned 32-bit read per word) of the CRU, GRF, DDR controller and PHY,
   memory scheduler, QoS ports, PL310 and EBC, on 2026-10-18 and 2026-10-20, under the stock kernel (3.0.36+, Android) and
   under ML-RC2; E-Ink updates under controlled loads, judged by a camera on the glass.
2. **RY** = the vendor 3.0 tree [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources):
   `arch/arm/mach-rk3026/common.c` (`cpu_axi_init`, `l2_cache_init`), `mach-rk3026/include/mach/cpu_axi.h` (port bases),
   `plat-rk/include/plat/cpu_axi.h` (port layout), `mach-rk2928/ddr.c`.
3. **The RK3308 TRM** Part 2, chapter 1 "Interconnect"
   ([Rockchip RK3308TRM V1.1 Part2](https://dl2.radxa.com/rockpis/docs/hw/datasheets/Rockchip%20RK3308TRM%20V1.1%20Part2-20180810.pdf)),
   §1.3.2 "QoS management" and §1.4.2–1.4.5. It documents the same Arteris FlexNoC QoS generator (same register offsets,
   same memory-scheduler ReadLatency register). The RK3026 has no public TRM.
4. **ML** = mainline Linux v7.2 (`arch/arm/mm/cache-l2x0.c`, `Documentation/devicetree/bindings/cache/l2c2x0.yaml`,
   `drivers/pmdomain/rockchip/pm-domains.c`) and upstream U-Boot (`arch/arm/mach-rockchip/rk3288/rk3288.c`).
5. **ML-RC2** = Mario Rugiero's RK3026 kernel ([Oppen/linux](https://github.com/Oppen/linux), branch `boox-c67ml`) on
   v7.1.13 with the RC2 patches, booted from microSD by a mainline-based U-Boot
   ([`../mainline/README.md`](../mainline/README.md) §0), with an out-of-tree EBC driver.

Confidence marks on this page:
- **[CONFIRMED-device]**: seen on the RC2 (register readback, the glass, a measured time);
- **[CONFIRMED-src]**: written in RY, mainline or upstream U-Boot, not checked on the chip;
- **[CONFIRMED-doc]**: written in the RK3308 TRM; for the RK3026 the same statement is at most [STRONG];
- **[STRONG]**, **[VERIFY]**, **[GUESS]**: as in the [top README](../README.md#confidence-marks).

## Summary

- **Each DRAM master port has a NoC QoS generator** (0x1012a000…0x1012f29c) in front of the memory scheduler
  (0x10128000), the uPCTL and the PHY; DDR3L at 396 MHz under the stock kernel (§1, §2).
- **After a power cycle the CPU cluster's QoS ports are at the top level** (CPU1 write and read = 0xF); the vendor kernel
  writes 0 to them, and a warm reset keeps that 0. With the reset values one CPU copy loop starves the EBC's fetch and
  garbles the glass; 0 on the two CPU1 ports cures it (§3) [CONFIRMED-device].
- **The EBC fetch needs two things**: its AHB clock `hclk_disp_pre` well above `dclk_ebc` (stock 256 MHz, the loader's
  132 MHz starves it), and the CPU QoS ports at the vendor's 0. Either one missing garbles the glass under load (§4)
  [CONFIRMED-device].
- **The stock PL310 setup is bigger and prefetches** (16-way 256 KiB, I+D prefetch, double linefill); a kernel that keeps
  the reset AUX value runs 8-way 128 KiB without prefetch, and a full-frame load/store pass is then 40 % slower at the
  same CPU clock (§5) [CONFIRMED-device].
- **The DDR controller set is the same** on stock and on a mainline SPL with the stock 396 MHz set, apart from the stock
  power-down policy (§6).
- **Measure from a power cycle**, never only after a warm reset from the stock kernel (§7).

## 1. Path from masters to DRAM

```
 Cortex-A9 x2 + PL310 L2 (0x10138000) ──┬─ QoS CPU0   0x1012a000 ─────┐
                                        ├─ QoS CPU1W  0x1012a080 ─────┤
                                        └─ QoS CPU1R  0x1012a100 ─────┤
 peripheral-bus masters ────────────────── QoS PERI   0x1012c000 ─────┤
 GPU (Mali-400 MP2) ────────────────────── QoS GPU    0x1012d000 ─────┤
 VPU ───────────────────────────────────── QoS VPU    0x1012e000 ─────┤
 LCDC1, EBC, IEP, LCDC0, CIF0, RGA ─────── QoS 0x1012f000…0x1012f280 ─┤
                                                                      │
                                                                    memory scheduler 0x10128000
                                                                    uPCTL 0x20004000 + DDR PHY 0x2000a000
                                                                    DDR3L ×16, 1 rank, 512 MiB
```

- **Port map** from RY `mach-rk3026/include/mach/cpu_axi.h`; the full table with values is §2.2 [CONFIRMED-src].
- **CPU ports.** The PL310 has two AXI master ports. The QoS ports named "CPU1W"/"CPU1R" carry the cluster's DRAM traffic
  whichever core runs the load: with a copy loop pinned to core 0, zeroing only those two cures the underrun, and
  zeroing only "CPU0" does not (§3) [CONFIRMED-device]. So "CPU1" is not core 1. That they are the write and read
  generators of the PL310 port the DRAM traffic leaves through (the vendor kernel does not set the PL310 address filter),
  and what "CPU0" carries, is [VERIFY] against the PL310 TRM.
- **Memory scheduler** (0x10128000): DdrConf (+0x08) 2, DdrTiming (+0x0c) 0x24717315 at 396 MHz, ReadLatency (+0x14)
  0x3F, equal under the stock kernel and ML-RC2 [CONFIRMED-device]. The vendor `cpu_axi_init()` writes ReadLatency 0x3f;
  the stock DDR init and a mainline SPL write it as well. DDR timings and the init: [`../soc/README.md`](../soc/README.md)
  §8, §8.1.
- **EBC.** It fetches its two 4-bpp images over AHB, clocked by `hclk_ebc` = `hclk_disp_pre` (CLKSEL_CON30), not by its
  AXI clock `aclk_lcdc1_src` (CLKSEL_CON31) ([`../soc/README.md`](../soc/README.md) §3.6) [CONFIRMED-device]. Its QoS port
  is 0x1012f080. It has no underrun status: the driver sees a complete scan (38 of 38 frames, 454 ms) also
  when the glass shows garbage [CONFIRMED-device].

## 2. NoC QoS generators

### 2.1 Registers and their meaning

Per port: PRIORITY +0x08, MODE +0x0c, BANDWIDTH +0x10, SATURATION +0x14, EXTCONTROL +0x18 (RY `plat-rk/include/plat/
cpu_axi.h` has +0x08…+0x14; the RK3308 TRM and mainline `pm-domains.c` add +0x18) [CONFIRMED-src]. Meaning, from the
RK3308 TRM §1.3.2, §1.4.3 [CONFIRMED-doc; for the RK3026 STRONG]:

| Register | Meaning |
|---|---|
| PRIORITY | two 2-bit levels P1 and P0. Old packing, used by the RK3026 vendor macro and upstream U-Boot's RK3288 code: `(P1 << 2) \| P0`; newer chips (RK3308, PX30) put P1 at bits 9:8. In fixed and limiter mode P1 is the read level and P0 the write level; in regulator mode P1 is the level while the port is under its bandwidth budget and P0 the level while it is over it (P1 ≥ P0) |
| MODE | 3 = regulator on both chips. RY's macro: 0 none, 1 fixed, 2 limiter; the RK3308 TRM: 0 fixed, 1 limiter, 2 bypass. Which encoding the RK3026 uses for 0–2 is [VERIFY] |
| BANDWIDTH | the regulator's budget, in 1/256 byte per generator clock cycle (MB/s = BANDWIDTH × f / 256) |
| SATURATION | the regulator's window, in units of 16 bytes |
| EXTCONTROL | bit 0: 0 = the generator alone sets the level, 1 = the higher of the generator's and the master's own level |

Regulator mode: the generator credits the bytes a port moves and debits its budget every cycle; while the count stays in
the lower half of the window the port gets P1, above it P0. Over-budget requests are still sent, at the lower level
[CONFIRMED-doc]. The memory scheduler then orders by that level, then by DRAM bank and page state [STRONG].

### 2.2 The RK3026 ports

| PRIORITY | Master | Vendor `cpu_axi_init` | After a power cycle | After the stock kernel and warm resets | MODE | BANDWIDTH | SATURATION | Read under the stock kernel |
|---|---|---|---|---|---|---|---|---|
| 0x1012a008 | CPU0 | 0 | **0x8** (2, 0) | 0 | 3 | 0x7 | 0x40 | reads (0) |
| 0x1012a088 | CPU1 write | 0 | **0xF** (3, 3) | 0 | 3 | 0x49 | 0x40 | reads (0) |
| 0x1012a108 | CPU1 read | 0 | **0xF** (3, 3) | 0 | 3 | 0x49 | 0x40 | reads (0) |
| 0x1012c008 | peripherals | 0 | 0x4 (1, 0) | 0x4 | 3 | 0x2A | 0x40 | reads (0) |
| 0x1012d008 | GPU | 0x9 (2, 1) | not read | 0xD | 3 | 0x18A | 0x40 | **hangs** (0x1012d000) |
| 0x1012e008 | VPU | — | not read | 0x9 | 3 | 0x66 | 0x40 | not tried |
| 0x1012f008 | LCDC1 | 0xF (3, 3) | 0xE (3, 2) | 0xE | 3 | 0x166 | 0x40 | **hangs** |
| 0x1012f088 | EBC | — | 0x8 (2, 0) | 0x8 | 3 | 0xAA | 0x40 | **hangs** |
| 0x1012f108 | IEP | — | not read | 0x8 | 3 | 0x2BB | 0x40 | not tried |
| 0x1012f188 | LCDC0 | 0xF (3, 3) | not read | 0xE | 3 | 0x166 | 0x40 | not tried |
| 0x1012f208 | CIF0 | — | not read | 0x8 | 3 | 0x55 | 0x40 | not tried |
| 0x1012f288 | RGA | — | not read | 0x8 | 3 | 0x2BB | 0x40 | not tried |

- Vendor values: the whole of RY `cpu_axi_init()` (`mach-rk3026/common.c:22-34`), run once at boot; the EBC port is never
  written; MODE, BANDWIDTH and SATURATION are never written [CONFIRMED-src].
- Reads [CONFIRMED-device]: "after a power cycle" from ML-RC2 cold boots (PRIORITY and MODE), through a mainline-based
  U-Boot that does not touch these ports; that they are the hardware reset values, not BootROM writes, is [STRONG].
  "After the stock kernel" from ML-RC2 booted through warm resets after the stock kernel had run; the MODE, BANDWIDTH and
  SATURATION columns from that state too. Since nothing writes those three, they are taken as the reset values [STRONG].
  EXTCONTROL reads 0 on every port. Under the stock kernel the CPU and peripheral ports read MODE 3, BANDWIDTH and
  SATURATION as in the table.
- **Only the three CPU ports keep the vendor value across a warm reset.** The peripherals port reads 0 under the stock
  kernel and 0x4 again after the warm resets, and the GPU and LCDC1 ports show 0xD and 0xE, not the vendor's 0x9 and 0xF
  [CONFIRMED-device]. Whether those blocks are reset by the warm reset or the vendor writes to them never landed is
  [VERIFY].
- **Reads that hang under the stock kernel** [CONFIRMED-device]: `0x1012f008`, `0x1012f088` and `0x1012d000` never return
  and the system stops answering (no abort; only a reset gets out). The CPU ports, the peripherals port and the memory
  scheduler read back. Under ML-RC2 every port reads. The stock kernel gates the GPU clock and `aclk_vio0` at idle
  (CLKGATE reads) [CONFIRMED-device], which fits the GPU word's hang [STRONG]; why the LCDC1 and EBC words hang is
  [VERIFY].

## 3. The CPU QoS ports and the EBC fetch underrun

**After a power cycle CPU0 = 0x8, CPU1W = 0xF, CPU1R = 0xF and PERI = 0x4, all in MODE 3** [CONFIRMED-device]. CPU1 at
(3, 3) is level 3 whether the regulator finds the port under or over its budget, so CPU DRAM traffic always runs at the
top level, above the EBC port's reset (2, 0) [STRONG, from §2.1]. The vendor kernel writes 0 to all four. Earlier tests
had read the CPU ports as 0 and ruled QoS out: those boots came after the stock kernel through warm resets only.

Runs on ML-RC2 (`hclk_disp_pre` 256 MHz, GPLL 768, DDR 396, ARM 600, `dclk_ebc` 160) with no stock kernel run since the
last power cycle. The update is a partial (PART) scan of a grey ramp over a black rectangle; the load starts before it
and runs through it; "copy loop" = `cat` of a 6 MB tmpfs file to another tmpfs file, in a loop. Every scan completed (38/38, 454 ms) with the driver's image
equal to the target; only the glass differs [CONFIRMED-device]. Rows 2 and 3 come from a boot that read only CPU0 (0x8),
so CPU1 at its reset 0xF there is [STRONG]; row 1 was seen in that boot and again in one that read all three:

| CPU0 | CPU1W / CPU1R | Load | Glass |
|---|---|---|---|
| 0x8 | 0xF / 0xF (reset) | 1 or 2 copy loops | **garbage**: fine horizontal streaks over the whole changed area |
| 0x8 | 0xF / 0xF | 2 read-only loops (`cat file > /dev/null`) | **garbage**, coarser streaks |
| 0x8 | 0xF / 0xF | 2 loops of `dd if=/dev/zero of=/dev/null bs=4M` | the changed area is not driven at all (2 of 2) |
| 0 | 0 / 0 | 1 or 2 copy loops; 1 memcpy loop (8 MiB buffers) | clean |
| 0x8 | 0xF / 0xF, written back | 1 copy loop | **garbage** |
| 0 | 0xF / 0xF | 1 copy loop | **garbage** |
| 0x8 | 0 / 0 | 1 copy loop; the same pinned to core 0 | clean |
| 0 | 0 / 0 | 1 copy loop pinned to core 0 | clean |

- **Not a cure with the CPU ports at reset** [CONFIRMED-device]: the EBC and LCDC1 ports at 0xF turn the streaks into coarse
  grey blocks; `hclk_disp_pre` at 320 MHz changes nothing. With CPU1 also at level 3 the EBC can at best tie with it
  [STRONG]. Tried in the boot of rows 2 and 3.
- **The stock kernel** (CPU ports 0) stayed clean under two copy loops (100 % CPU where sampled), partial and full
  updates, 70 photos [CONFIRMED-device]; its loops copied on ext4, not tmpfs, so that dose is not known to match.
- **Fix: write the vendor values to CPU0, CPU1W, CPU1R and PERI on every boot**, whatever ran before. A mainline-based
  U-Boot for the RC2 does it in `arch_cpu_init()`, as upstream U-Boot sets the RK3288 VOP QoS priority in its
  `arch_cpu_init()` [CONFIRMED-src]. From a power cycle, with no manual register write, the four words read 0 and the
  glass stayed clean under 1 and 2 copy loops and 1 and 2 memcpy loops, 5 runs of 5 [CONFIRMED-device]. It leaves the GPU and display-side
  ports (0x1012d000 and up) alone, since reads there hang under the stock kernel; they are not needed for the fix. A
  kernel-side write would cover other boot loaders.
- **Margin, not tested:** the EBC port at PRIORITY 0xA (2, 2) or 0xF, or fixed mode, set by the EBC driver while its
  clocks run [VERIFY].

## 4. Two causes of the EBC underrun, both needed

| `hclk_disp_pre` | CPU1 ports | Load | Glass |
|---|---|---|---|
| 132 MHz (the loader's GPLL / 1) | 0 (after the stock kernel) | a `dd if=/dev/zero of=/dev/null bs=4M` loop, page turns | garbage, every turn |
| ≈ 213 MHz (CPLL / 3), live in the same boot | 0 | the same | clean, 14 of 14 turns in two series |
| 256 MHz (stock bus clocks) | 0xF (power cycle) | copy, read-only and zero-fill loops (§3) | garbage or undriven |
| 256 MHz | 0 | 1 and 2 copy loops, 1 and 2 memcpy loops | clean |

So the clock is a cause with the CPU ports at 0, and the CPU ports are a cause at the stock clock [CONFIRMED-device]. A
board needs both: `hclk_disp_pre` at 256 MHz (or at least well above `dclk_ebc` 160 MHz) and the CPU ports at 0. Not
tested: two zero-fill `dd` loops with both fixes; a copy loop at 132 MHz with the CPU ports at 0. Register values of the
clock tests: [`../soc/README.md`](../soc/README.md) §3.6.

The EBC's demand and its budget [arithmetic from the panel timings, [`../README.md`](../README.md#panel-timings)]: each
frame fetches both 4-bpp images, 2 × 776 128 B, in 11.96 ms: **about 130 MB/s** on average; a line pair is 1448 B in the
9.05 µs active part of an 11.05 µs line: **about 160 MB/s** within a line. The EBC port's BANDWIDTH 0xAA is 170 MB/s if the
generator runs at 256 MHz (its clock [VERIFY]). On those numbers the EBC stays under its budget and gets its P1 level
2, which loses to CPU1 at 3 and wins over CPU1 at 0; whether its bursts push it over budget within the window is [VERIFY].

## 5. L2 cache and the memory floor

| PL310 (r3p3, `CACHE_ID` 0x4100C0C9) | Stock kernel | ML-RC2 (AUX as found) |
|---|---|---|
| AUX_CTRL `0x10138104` | **0x76030001**: 16 ways × 16 KiB = 256 KiB, I and D prefetch, early BRESP, full line of zeros | 0x46020001: 8 ways, 128 KiB, no prefetch |
| PREFETCH_CTRL `0x10138f60` | **0x70000003**: double linefill, I and D prefetch, offset 3 | 0 |
| CACHE_TYPE `0x10138004` | 0x9E140140 | 0x9E100100 |
| tag / data RAM latency `0x10138108` / `0x1013810c` | 0x000 / 0x021 | 0x000 / 0x021 |

Read on both [CONFIRMED-device]; the vendor `l2_cache_init()` sets the stock values once at boot [CONFIRMED-src]
([`../soc/README.md`](../soc/README.md) §3.5).

**The memory floor.** A NEON load/store-only pass over a full 1448 × 1072 frame (6.2 MB read, 0.78 MB written), cold, white
page [CONFIRMED-device]:

| | no `pld` | `pld` 256 B ahead |
|---|---|---|
| stock kernel, 912 MHz | 8.45 ms | 7.29 ms |
| ML-RC2, 912 MHz | 11.81 ms | 9.05 ms |
| ML-RC2, 600 MHz | 12.48 ms | 9.65 ms |

At the same 912 MHz mainline is 40 % slower without `pld` and 24 % with it; 600 → 912 MHz gains only 5 %: the pass is
memory-bound. The L2 setup is the likely cause [STRONG]; the CPU-side dividers differ as well (CLKSEL_CON1 0x3133 on stock
at 912 MHz, 0x3115 on ML-RC2 at 600 MHz) [CONFIRMED-device]. For a mainline DT, set the L2 explicitly
([`../mainline/README.md`](../mainline/README.md) §1, "Machine, L2 cache", for the machine entry that enables it):
`cache-size = <262144>`, `cache-sets = <512>`, `cache-line-size = <32>` (the driver needs both size and sets),
`prefetch-data = <1>`, `prefetch-instr = <1>`, `arm,double-linefill = <1>`, `arm,prefetch-offset = <3>`,
`arm,tag-latency = <1 1 1>`, `arm,data-latency = <3 1 2>` [property names CONFIRMED-src (ML `cache-l2x0.c`); the values
STRONG; the effect on the floor VERIFY until measured].

## 6. DDR controller and PHY, stock vs mainline

The stock kernel's 396 MHz set and the mainline SPL that writes it: [`../soc/README.md`](../soc/README.md) §8.1. In the
2026-10-20 dumps (stock kernel against ML-RC2 on that SPL) [CONFIRMED-device]:
- **Equal:** the memory scheduler (DdrConf, DdrTiming, ReadLatency) and every uPCTL timing word.
- **Different, policy only:** MCFG `0x20004080` 0x00054021 vs 0x00050021 (stock `pd_idle` 0x40: CKE power-down after 64
  idle cycles) and MCFG1 `0x2000407c` 0x80000000 vs 0 (`hw_exit_idle_en`). Both cost latency on a wake, so they cannot
  make stock faster under load [STRONG]. MCMD (`+0x40`) holds the last command issued.
- **Different, measured:** PHY_REG60 `0x2000a3e0` 0xA9 vs 0x89, the DQS gate calibration result (Dllsel 5 vs 4), not a
  setting [STRONG].

## 7. How to measure

- **Read-only register dumps:** one aligned 32-bit read per word (`devmem`, or a small static `/dev/mem` reader where the
  stock Android has none). Under the stock kernel never read the QoS windows from 0x1012d000 up: the bus hangs (§2.2).
  CPU and peripheral ports, the memory scheduler, the uPCTL, the PHY, the PL310 and the EBC read safely there.
- **The symptom is only on the glass.** The driver reports complete scans and holds the right image, so judge by a photo
  of the panel; a partial update of a grey ramp over a black area shows it.
- **The load:** one or two copy loops of a file far beyond the L2, or a user-space memcpy loop that prints its rate. On
  ML-RC2 at 600 MHz an 8 MiB memcpy loop ran 2974 MB/s alone and 1408 + 1420 MB/s as two [CONFIRMED-device]. A loop on a
  16 KiB buffer (L1-resident) does not trigger it: DRAM traffic does, not CPU activity [CONFIRMED-device].
- **Start from a power cycle.** Warm resets keep the CPU QoS ports at whatever the last kernel wrote (§2.2), so a reading
  after the stock kernel says nothing about the reset state. Replugging the USB cable does not reset the battery-powered
  book; on ML-RC2 a `poweroff -f` with the cable attached gave a cold start [CONFIRMED-device].

## 8. Still [VERIFY]

- The MODE encoding for values 0–2 on the RK3026; the generator clock of each port (it scales BANDWIDTH).
- Which PL310 master port the CPU1 generators sit behind, and what the CPU0 port carries.
- Why the LCDC1 and EBC QoS words hang a read under the stock kernel; whether a warm reset resets the peripherals, GPU
  and display ports or the vendor's writes to them do not land.
- The EBC port's behaviour against its budget in line bursts; the margin values of §3.
- The memory floor with the stock L2 setup in a mainline DT.
