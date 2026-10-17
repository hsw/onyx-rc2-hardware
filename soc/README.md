# RK3026 SoC map for a device tree

The RK3026 has no public Technical Reference Manual. This page collects what a `rk3026.dtsi` and an RC2 board file need: the
MMIO map, interrupt numbers in both numberings, the clock unit (CRU), the general register file (GRF), pin muxing and pulls of
the RC2 pins, and the places where the public datasheets contradict each other. The mainline status of each block is in
[`../mainline/README.md`](../mainline/README.md); the PMIC registers read on the same day are in [`../pmic/README.md`](../pmic/README.md).

Sources, in order of weight:
1. **The RC2 itself**: `/proc/iomem`, `/proc/interrupts`, boot logs ([`../device/proc/`](../device/proc/)), and a read-only
   register dump taken on 2026-10-11 on the running system: CRU, GRF, GPIO0–3 and EBC read as 32-bit MMIO words with `devmem`,
   nothing written. State at dump time: the stock 3.0.36+ kernel (with two small fixes in its EBC driver), Android, display idle after the last update, USB cable attached,
   Wi-Fi off, no suspend since boot.
2. **The stock RC2 kernel Image** (disassembly; addresses refer to the 2017-11-07 kernel, as in the rest of this repository).
3. **RY** = the public vendor 3.0 tree [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources):
   `arch/arm/mach-rk3026/include/mach/{cru,grf,iomux,irqs}.h`, `mach-rk2928/include/mach/io.h`, `mach-rk3026/clock_data.c`,
   `mach-rk3026/reset.c`.
4. **ML** = mainline Linux **v7.2**: `arch/arm/boot/dts/rockchip/{rk3036,rk3xxx}.dtsi`, `drivers/clk/rockchip/{clk-rk3036,clk-rk3128,clk-pll}.c`,
   `drivers/pinctrl/pinctrl-rockchip.c`, `arch/arm/mach-rockchip/platsmp.c`, `drivers/i2c/busses/i2c-rk3x.c`,
   `drivers/phy/rockchip/phy-rockchip-inno-usb2.c`, `drivers/pmdomain/rockchip/pm-domains.c`.
5. **DS** = the Rockchip datasheets `RK3026_datasheet_V1.1` and `RK302X_datasheet_V1.2` (pins, electrical data, feature
   list; no registers).
6. **ML-RC2** = mainline Linux v7.1.13 with Mario Rugiero's RK3026 tree ([Oppen/linux](https://github.com/Oppen/linux), branch
   `boox-c67ml`) plus a few RC2 patches ([`../mainline/README.md`](../mainline/README.md) §0), and a mainline-based U-Boot,
   both booted on the RC2 from microSD on 2026-10-16/17. CPU1 start, warm resets, the watchdog, power-off and the USB OTG core
   were exercised there.

Confidence marks on this page:
- **[CONFIRMED-device]**: seen on the RC2 (log, `/proc`, register readback);
- **[CONFIRMED-dis]**: read in the stock kernel disassembly (address given);
- **[CONFIRMED-src]**: written in the vendor 3.0 source or in mainline, not checked on the chip;
- **[STRONG]**, **[VERIFY]**, **[GUESS]**: as in the [top README](../README.md#confidence-marks).

## Summary

- **The MMIO map of the vendor `io.h` is right wherever it could be checked**: 21 blocks appear in `/proc/iomem` of the stock
  kernel at those addresses; CRU, GRF, GPIO1/2 and IMEM are also written by a small custom loader that boots the stock kernel
  from microSD, and it works. One correction: **TIMER1 is at 0x20044020** (inside the TIMER0 block), not at 0x20046000 (§1).
- **The Cortex-A9 cluster** (SCU, GIC, global and private timers, PL310 L2 of 256 KiB) sits exactly where `rk3xxx.dtsi`
  (RK3066/RK3188) puts it.
- **Peripherals are nearly RK3036** (`rk3036.dtsi`): the same bases for SD/SDIO/eMMC/I2S/NAND/CRU/GRF/timer/PWM/I2C/UART/SPI/
  DMA/GPIO, and the same SPI numbers for the 20 shared interrupts. Differences: the GIC (Cortex-A9 GIC, not GIC-400), the
  display side (LCDC at 0x1010e000, plus EBC, IEP and LCDC1; no VOP), crypto instead of EMAC at 0x10200000, four GPIO banks
  instead of three.
- **Interrupts:** the vendor Linux number is the GIC INTID, so in a device tree use **`GIC_SPI (n − 32)`**. EBC 81 →
  `GIC_SPI 49` (§2).
- **DMA:** one PL330 at 0x20078000, the same node as `rk3036.dtsi`/`rk3128.dtsi` and the same request lines for the shared
  peripherals (eMMC = line 12). The
  stock kernel has no dmaengine; its drivers use the vendor `rk29_dma_*` API (§1.1).
- **CRU:** the register layout and the PLL type are those of `clk-rk3036.c` (`RK2928_*` offsets, `pll_rk3036`), but the RK3026
  has **four PLLs** (CPLL too), 1-bit parent muxes, different fields for SDIO/eMMC/`uart_pll`, CPU1 reset at bit 4, and the EBC
  clock. It needs its own `clk-rk3026.c`; the PLL part can follow `clk-rk3128.c` (§3).
- **GRF:** pinctrl is exactly the `rockchip,rk2928-pinctrl` layout. Different from RK3036: the USB status bits (shifted by one),
  the idle-request bits, the **I2C controller select in `GRF_SOC_CON1` bits 11–14**, and **`GRF_LVDS_CON0` bit 0, which routes
  the EBC data lines (SDDO0–7, SDCE0/1) to the LVDS pads** (§4).
- **Reboot flags:** stock writes `GRF_OS_REG4` (0x1d8) with the same values as mainline `syscon-reboot-mode`; the stock loader
  acts on `0x5242C301` (Rockusb) and `0x5242C303` (recovery) and boots normally on most other values (§4.2).
- **CPU1:** there is no PMU, and the core soft reset does not hold the core: **the assert write itself restarts CPU1 at
  address 0**, the deassert does nothing. Address 0 is IMEM only while `GRF_SOC_CON0` bit 12 is set. Mainline
  `rockchip,rk3036-smp` brings CPU1 up on this Cortex-A9 with two changes: a reset pulse once the trampoline is in place, and
  the remap set only around that pulse. Hotplug works (§4.3).
- **Warm resets:** `GLB_SRST_SND`, `GLB_SRST_FST` and a watchdog reset all restart through the BootROM (microSD first) and keep
  the DDR contents. The Cortex-A9 keeps L1 cache lines across them, so a first-stage loader must invalidate L1 at entry (§4.5).
- **Measured on the device:** APLL 912, DPLL 792 (DDR 396), **CPLL 640**, GPLL 768 MHz; `dclk_ebc` 160 MHz from CPLL; the keys,
  the cover sensor and I2C2 run with the internal pull disabled (external pull-ups, DTS `bias-disable`).

## 1. MMIO map

Bases and sizes from RY `mach-rk2928/include/mach/io.h` (RK3026 includes it). "RC2" = the stock kernel's `/proc/iomem` line or
other evidence on the device. "ML" = the closest existing node; a `rockchip,rk3026-…` compatible is still needed in front of it.

| Base | Size | Block | RC2 evidence | ML candidate | Mark |
|---|---|---|---|---|---|
| 0x10080000 | 8 KiB | IMEM (SRAM) | stock keeps its sleep code and the CPU1 trampoline there; the custom loader runs from it | `mmio-sram` + `rockchip,rk3066-smp-sram` at offset 0 (as `rk3036.dtsi`) | CONFIRMED-device |
| 0x10090000 | 64 KiB | GPU Mali-400 **MP2** | `Mali_GP` +0, `Mali_L2` +0x1000, `GP_MMU` +0x3000, `PP0_MMU` +0x4000, `PP1_MMU` +0x5000, `PP0` +0x8000, `PP1` +0xa000 | `arm,mali-400` (lima); RK3036 has one PP | CONFIRMED-device |
| 0x10100000 | 16 KiB | BootROM | dumped, see [`../bootrom/README.md`](../bootrom/README.md) | — | CONFIRMED-device |
| 0x10104000 | 16 KiB | VPU | `vpu` (VEPU +0, VDPU +0x200) | `rockchip,rk3066-vpu` at the same address in `rk3xxx.dtsi` | CONFIRMED-device |
| 0x10108000 | 8 KiB | IEP | — | — | CONFIRMED-src |
| 0x1010a000 | 8 KiB | CIF (camera) | — | — | CONFIRMED-src |
| 0x1010c000 | 8 KiB | RGA (first generation) | `rga` | none: mainline `rga.c` handles RGA2 and later only | CONFIRMED-device |
| 0x1010e000 | 8 KiB | LCDC0 | `rk30-lcdc` | an RK2928-generation LCDC, not a VOP; the RC2 has no LCD | CONFIRMED-device |
| 0x10110000 | 8 KiB | LCDC1 | — (the EBC driver enables `aclk_lcdc1` and `pd_lcdc1`, §3.3) | — | CONFIRMED-src |
| **0x10114000** | 16 KiB | **EBC** (E-Ink controller) | `ebc reg` / `rk29-ebc` 10114000–10117fff | none ([onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc)) | CONFIRMED-device |
| 0x10128000 | 32 KiB | CPU AXI bus / QoS | — | RK3036 has `rockchip,rk3036-qos` at 0x1012d000…; RK3026 offsets unknown | CONFIRMED-src; QoS [VERIFY] |
| 0x10138000 | 16 KiB | L2C PL310 | boot log: `CACHE_ID 0x4100c0c9, AUX_CTRL 0x76030001, Cache size: 262144 B` | `arm,pl310-cache` (as `rk3xxx.dtsi`) | CONFIRMED-device |
| 0x1013c000 | 256 B | SCU | 2 CPUs | `arm,cortex-a9-scu` | CONFIRMED-src + ML |
| 0x1013c100 | 256 B | GIC CPU interface | | `arm,cortex-a9-gic`, second `reg` | CONFIRMED-src + ML |
| 0x1013c200 | 1 KiB | global timer | | `arm,cortex-a9-global-timer`, PPI 11, **edge rising** (§2.1) | CONFIRMED-src + ML; edge CONFIRMED-device |
| 0x1013c600 | 2.5 KiB | private timer + watchdog (TWD) | `LOC` in `/proc/interrupts` (Linux 29 = PPI 13) | `arm,cortex-a9-twd-timer`, PPI 13, **edge rising** (§2.1) | CONFIRMED-src + ML; edge CONFIRMED-device |
| 0x1013d000 | 4 KiB | GIC distributor | | `arm,cortex-a9-gic`, first `reg` | CONFIRMED-src + ML |
| 0x10180000 | 256 KiB | USB OTG (DWC2) | `usb20_otg`, IRQ 42 | `snps,dwc2` + `rockchip,rk3066-usb`; FIFO RAM 972 words (§1.2) | CONFIRMED-device |
| 0x101c0000 | 256 KiB | USB host, **also DWC2** (not EHCI/OHCI) | `usb20_host`, IRQ 43; the RTL8723BU Wi-Fi sits on it | `snps,dwc2`, host mode | CONFIRMED-device |
| 0x10200000 | 16 KiB | crypto | — | — (EMAC on RK3036) | CONFIRMED-src |
| 0x10214000 | 16 KiB | SDMMC0 (microSD) | `rk29_sdmmc.0` | `rockchip,rk2928-dw-mshc` | CONFIRMED-device |
| 0x10218000 | 16 KiB | SDIO | `rk29_sdmmc.1` (unused) | same | CONFIRMED-device |
| 0x1021c000 | 16 KiB | eMMC | IRQ 48 `emmc`; the region is taken by the vendor NAND/eMMC module, not listed in `/proc/iomem` | same | CONFIRMED-device (IRQ) |
| 0x10220000 | 8 KiB | I2S | `rk29_i2s.0` | `rockchip,rk3066-i2s` | CONFIRMED-device |
| 0x10234000 / 0x1023c000 / 0x10300000 | | AHB arbiters, peripheral AXI window | — | — | CONFIRMED-src |
| 0x10400000 | 1 MiB | GPS | — | — | CONFIRMED-src; presence [VERIFY] |
| 0x10500000 | 16 KiB | NAND controller | `rk29xxnand` | `rockchip,rk3036-nfc` | CONFIRMED-device |
| **0x20000000** | 4 KiB | **CRU** | written by the custom loader (`CRU_SOFTRST_CON0`) | new `rockchip,rk3026-cru` (§3) | CONFIRMED-device |
| 0x20004000 | 16 KiB | DDR PCTL | — | do not describe (the loader sets up DDR) | CONFIRMED-src |
| **0x20008000** | 4 KiB | **GRF** | `rk3026-lvds` 20008150–2000815c; written by the custom loader | `syscon`, `simple-mfd` | CONFIRMED-device |
| 0x2000a000 | 24 KiB | DDR PHY | — | do not describe | CONFIRMED-src |
| 0x20020000 | 64 KiB | debug (CoreSight) | — | — | CONFIRMED-src |
| 0x20030000 | 16 KiB | ACODEC (internal codec) | `rk3026-codec` | `rockchip,rk3036-codec` covers the DAC part only | CONFIRMED-device |
| 0x20034000 | 16 KiB | HDMI | — | **not in RK3026**: DS V1.2 "HDMI … only by RK3028A" | — |
| 0x20044000 | 0x20 | TIMER0 | IRQ 60 `rk_timer0` (clockevent) | `rockchip,rk3036-timer`, `reg <0x20044000 0x20>` | CONFIRMED-device |
| **0x20044020** | 0x20 | **TIMER1** | the stock clocksource (`Switching to clocksource rk_timer`); the timer resource in the Image holds this address | a second timer node, or leave it out | CONFIRMED-src (RY `mach-rk3026/rk_timer.c`: TIMER0 + 0x20); STRONG (disassembly) |
| 0x2004c000 | 4 KiB | watchdog | not enabled by stock. Armed by a mainline-based U-Boot and fed by Linux `dw_wdt`; its reset restarts through the BootROM (microSD first) and keeps DDR (§4.5) | `snps,dw-wdt`; without `snps,watchdog-tops` the driver prints `No valid TOPs array specified` and uses its default table | CONFIRMED-device (ML-RC2) |
| 0x20050000 | 4 KiB | PWM, channel n at +0x10·n | PWM0 = frontlight | `rockchip,rk2928-pwm`, `reg <0x20050000 0x10>` | CONFIRMED-src; DS: 2 PWMs on RK3026 |
| 0x20054000 / 0x20058000 / 0x2005c000 / 0x20070000 | 4 KiB | the old (rk29) I2C1/2/3/0 controllers | unused | — | CONFIRMED-src |
| 0x20072000 | 4 KiB | I2C0 (rk30 controller) | `rk30_i2c.0`: ACT8931 0x5b, CW2015 0x62, HYM8563 0x51 | `rockchip,rk3066-i2c`-type with a GRF select (§4.1) | CONFIRMED-device |
| 0x20056000 | 4 KiB | I2C1 | `rk30_i2c.1`, no devices | same, `status = "disabled"` | CONFIRMED-device |
| 0x2005a000 | 4 KiB | I2C2 | `rk30_i2c.2`: cyttsp4 0x24, TPS65185 0x68 | same | CONFIRMED-device |
| 0x2005e000 | 4 KiB | I2C3 | `rk30_i2c.3`, no devices; GPIO0_A6/A7 muxed to I2C3 and its clock open | leave out: DS says "3 I2C in RK3026" | region CONFIRMED-device; block [VERIFY] |
| 0x20060000 | 4 KiB | UART0 | `ttyS0 at MMIO 0x20060000 (irq = 52)` | `snps,dw-apb-uart` | CONFIRMED-device |
| 0x20064000 | 4 KiB | UART1 | — | same | CONFIRMED-src |
| 0x20068000 | 4 KiB | UART2 | the stock FIQ debugger runs on it (init call with this base, IRQ 54, signal IRQ 127, @0xc040dfc8); also the BootROM download UART (§6) | same | CONFIRMED-dis |
| 0x2006c000 | 4 KiB | SAR-ADC | `rk30-adc` | `rockchip,saradc` (3 channels in ML; see §6) | CONFIRMED-device |
| 0x20074000 | 16 KiB | SPI0 | `rk29xx_spim.0` (panel flash) | `rockchip,rk3036-spi` | CONFIRMED-device |
| 0x20078000 | 16 KiB | DMAC PL330 | `rk29-pl330`, IRQ 32/33 | `arm,pl330` | CONFIRMED-device |
| 0x2007c000 / 0x20080000 / 0x20084000 / 0x20088000 | 4 KiB | GPIO0…GPIO3 | GPIO1/GPIO2 data and direction registers written by the custom loader | `rockchip,gpio-bank`, `reg <… 0x100>` | CONFIRMED-device |
| 0x20090000 | 4 KiB | eFuse | chip version (`rk3026 soc version:4` in every log) | not `rk3066a-efuse` as is: the address field in CTRL is shifted by 8, not 6 | CONFIRMED-src |
| 0x60000000 | 512 MiB | DDR | `System RAM 60000000-7d0fffff` plus reserved regions; MemTotal 524288 kB | `memory` node | CONFIRMED-device |

The memory the stock kernel reserves (for `reserved-memory`, if the layout is kept) is listed in the top README.

The vendor kernel's virtual addresses (`0xFEA…` = phys + 0xEEA00000, `0xFED…` = phys + 0xDED00000, IMEM at 0xFEF00000) only
matter for reading the stock disassembly. **The EBC is not in the static map**: its driver uses `ioremap`, so there is no fixed
virtual EBC address.

### 1.1 DMA controller (PL330)

Static analysis of the stock kernel Image, checked against the vendor 3.0 source (RY `arch/arm/common/pl330.c`,
`arch/arm/plat-rk/dma-pl330.c`, `plat/dma-pl330.h`; no difference found in the functions compared) and the device.

- **One DMA controller**: an ARM PL330 at 0x20078000 (16 KiB), IRQ 32/33 (`GIC_SPI 0/1`), platform device `rk29-pl330`
  from `mach-rk2928/devices.c` (also used for the RK3026). The boot log reports `Num_Chans-8 Num_Peri-14 Num_Events-16`
  (data buffer 64 × 8 bytes); `/proc/interrupts` shows both lines, only IRQ 32 counting [CONFIRMED-device]. The driver
  never enables a clock and relies on the CRU reset default (no `clk_get`/`clk_enable` in `pl330_probe` @0xc045f810)
  [CONFIRMED-dis].
- **Stock driver**: Rockchip's two layers, `common/pl330.c` (PL330 core, microcode generation) and `plat-rk/dma-pl330.c`
  (the S3C-style `rk29_dma_*` API). **There is no dmaengine**: no `dma_async_*`, `dma_request_channel` or
  `drivers/dma/pl330.c` symbols, so `CONFIG_DMADEVICES` is off [CONFIRMED-dis]. In-kernel users: `rk29_sdmmc` (microSD,
  SDIO), the SPI master (`rk29_spim`, panel flash) and I2S/PCM; UART, EBC and LCDC do not use DMA. The closed NAND/eMMC
  module uses it for the eMMC ([`../device/README.md`](../device/README.md#rk30xxnand_ko-and-the-emmc)).
- **Microcode**: peripheral transfers are always burst handshakes without `FLUSHP` (the vendor source has it commented
  out "for sdmmc sdio"); memory-to-memory uses read/write barriers. A buffer of 128 bytes per request (mainline: 256)
  [CONFIRMED-dis].

Request lines (the vendor platform data `rk29_pl330_platdata.peri[]` in the Image @0xc0a6ff04, identical to RY)
[CONFIRMED-dis], against mainline v7.2 `dmas = <&pdma n>` [CONFIRMED-src]:

| Line | Stock (`enum dma_ch` number) | `rk3036.dtsi` | `rk3128.dtsi` |
|---|---|---|---|
| 0 / 1 | I2S 8-ch TX/RX (4/5) | `i2s` | `i2s_2ch` |
| 2 / 3 | UART0 TX/RX (0/1) | — | `uart0` |
| 4 / 5 | UART1 TX/RX (2/3) | — | `uart1` |
| 6 / 7 | UART2 TX/RX (16/17) | — | `uart2` |
| 8 / 9 | SPI0 TX/RX (20/21) | `spi` | `spi0` |
| 10 | SDMMC (12) | — | `sdmmc` |
| 11 | SDIO (13) | — | `sdio` |
| 12 | **eMMC (14 = `DMACH_EMMC`)** | `emmc` | `emmc` |
| 13 | reserved for memory-to-memory (25) | — | `spdif` |
| 14 / 15 | unused | — | `i2s_8ch` |

- Mainline describes the same controller in both files: `dma-controller@20078000`, `arm,pl330`, `GIC_SPI 0/1`,
  **`arm,pl330-periph-burst`** and **`arm,pl330-broken-no-flushp`**, which is exactly what the stock microcode does (burst
  only, no `FLUSHP`). Differences: line 13 is SPDIF on the RK3128 and memory-to-memory in stock; the RK3128 puts its 8-channel
  I2S on 14/15, beyond the 14 lines the RC2 controller reports; mainline needs the clock (`ACLK_DMAC2` in `rk3036.dtsi`,
  `ACLK_DMAC` in `rk3128.dtsi`), which stock never touches. A `rk3026.dtsi` can copy the `rk3036.dtsi` node and use lines
  10–12 for SDMMC/SDIO/eMMC [STRONG].
- **The API channel number is not the request line.** `rk29_dma_request()` takes an `enum dma_ch` value: eMMC is channel
  14 on request line 12; `rk29_sdmmc` picks channels 12/13/14 by `pdev->id` [CONFIRMED-dis].

`rk29_dma_*` quirks that matter for a module built against the stock kernel (all also in the public source):
- Addresses passed to `rk29_dma_enqueue()` are physical; the API does no mapping and no cache maintenance. Callers do
  the cache work with `___dma_single_cpu_to_dev`/`___dma_single_dev_to_cpu`, which handle L1 and the PL310 L2 themselves
  (`BUG()` for a buffer outside lowmem) [CONFIRMED-dis].
- `rk29_dma_enqueue()` returns 0 even when the submit to the PL330 fails (the error arrives in the callback);
  `rk29_dma_config()` silently ignores out-of-range values and returns 0, and loops forever when the transfer unit is not
  a power of two; `rk29_dma_setflags()` always returns 0 [CONFIRMED-dis].
- `RK29_DMAOP_STOP` aborts the current request and immediately starts the next queued one; `FLUSH` cancels everything;
  `PAUSE`/`RESUME` are no-ops [CONFIRMED-src].
- Completion callbacks run in hard-IRQ context; the next transfer is submitted from the IRQ [CONFIRMED-dis].
- For `DMACH_EMMC` the driver forces a burst length of 16 [CONFIRMED-dis].
- Coherent DMA pool (`CONSISTENT_DMA_SIZE`) is 8 MiB; there is no dmabounce or swiotlb [CONFIRMED-dis].

The **NAND controller** at 0x10500000 is NandC v6 (mainline `rockchip,rk3036-nfc` with the `rockchip,rk2928-nfc`
fallback, `rockchip-nand-controller.c` `NFC_V6`) [STRONG]. It has its own bus-master DMA (buffer addresses in its
`DMA_DATA_BUF`/`DMA_OOB_BUF` registers) and does not use the PL330. The vendor module contains that path, but it is not
executed on the RC2, which has eMMC and no raw NAND.

### 1.2 USB OTG controller (DWC2)

Read on the device from a mainline-based U-Boot and checked against mainline Linux `dwc2` on the same board (ML-RC2)
[CONFIRMED-device unless marked]:

- `GSNPSID` 0x4f54291a (core release 2.91a); `GHWCFG1..4` = 0x00006664, 0x22aa2450, 0x03cc00e8, 0xdbf04060.
- `GHWCFG3` bits 31:16 = 0x3cc: **972 words of FIFO RAM** (Linux: "dedicated fifos, 972 entries in SPRAM"). Transfer-size
  counter 19 bits, packet counter 10 bits (Linux `hw_params`: `max_transfer_size` 524287, `max_packet_count` 1023).
  `GHWCFG4`: 6 IN endpoints with dedicated TX FIFOs.
- FIFO layout: U-Boot's non-DM Rockchip gadget path ignores the DT and programs RX 512 + non-periodic TX 16 + 6 × 128 =
  1296 words, more than the core has. A layout that fits and works in both U-Boot and Linux: `g-rx-fifo-size` 275,
  `g-np-tx-fifo-size` 16, `g-tx-fifo-size` 256 128 128 64 64 32 = 963 words. TX FIFO 1 (bulk IN) = 256 words = two
  high-speed packets, the same depth as Rockchip's own Rockusb code programs (RX 528, NP TX 16, IN FIFO 1 256, IN FIFO 2 16;
  `board/rockchip/common/common/rockusb/` of the RK30 vendor U-Boot,
  [radxa/u-boot-rockchip](https://github.com/radxa/u-boot-rockchip) branch `u-boot-rk3188`) [CONFIRMED-src].
- Bulk IN DMA size: that Rockusb code never programs more than 64 KiB per IN transfer. In U-Boot, reads to the host went
  wrong twice with a whole 128 KiB request (256 packets, within both counters) per IN DMA, and were right in every variant
  of two later rounds with IN split into 16 KiB DMA chunks like OUT [STRONG; the exact cause of the bad reads is not pinned
  down]. Keep IN transfers at 16 KiB.
- AHB burst: the stock 3.0 kernel (`dwc_otg_cil.c`) and mainline `dwc2` (`dwc2_set_rk_params`) use INCR16 on this core
  [CONFIRMED-src]; in U-Boot, reads were right with INCR16 and with INCR4.
- Mainline Linux runs the OTG port as a peripheral: a configfs gadget with CDC ACM (console on `ttyGS0`) and mass storage
  (the microSD exported to the host; about 18 MB/s read and 19 MB/s write from a Mac) works. U-Boot's CDC ACM console and
  `ums` work too; after a `ums` run ended by an eject the ACM console stays deaf (the host keeps resetting the bus and
  the device only enumerates at full speed) [CONFIRMED-device; cause VERIFY].

## 2. Interrupts

### 2.1 Numbering

- The vendor Linux number on this platform equals the GIC interrupt ID (INTID); shared peripheral interrupts start at 32
  (RY `mach-rk3026/common.c`, `gic_init`). **In a device tree: `GIC_SPI (n − 32)`.** For all 20 blocks shared with RK3036,
  `rk3036.dtsi` uses exactly n − 32 (SDMMC 46 → `GIC_SPI 14`, UART0 52 → 20, I2C0 56 → 24, TIMER0 60 → 28, GPIO0 68 → 36,
  OTG 42 → 10, bvalid 67 → 35, otg-id 83 → 51) [STRONG].
- PPIs: the private timer is Linux 29 = PPI 13, the global timer PPI 11 (as in `rk3xxx.dtsi`). Both are **rising edge**, with
  read-only configuration bits in the distributor. A level-high description (copied from `rk3036.dtsi`, whose Cortex-A7 arch
  timer is a different block) makes mainline print `GIC: PPI13 is secure or misconfigured` for every CPU that comes online;
  `IRQ_TYPE_EDGE_RISING`, as `rk3xxx.dtsi` has it for the other Rockchip Cortex-A9 SoCs, removes the warning
  [CONFIRMED-device, ML-RC2].
- `NR_GIC_IRQS` = 128, so 96 SPIs (RY `mach-rk2928/include/mach/irqs.h`).

### 2.2 Table

Numbers from RY `irqs.h`. "RC2" = the name in the stock `/proc/interrupts` ([`../device/proc/proc_interrupts.txt`](../device/proc/proc_interrupts.txt)).

| Linux | DT `GIC_SPI` | Block | RC2 | Mark |
|---|---|---|---|---|
| 32, 33 | 0, 1 | DMAC 0/1 | `rk29-pl330` | CONFIRMED-device |
| 34 | 2 | DDR PCTL | — | src |
| 35, 36, 37 | 3, 4, 5 | GPU GP / MMU / PP | `mali_gp`, `mali_mmu`, `mali_pp` | CONFIRMED-device |
| 38, 39 | 6, 7 | VEPU, VDPU | `vepu`, `vdpu` | CONFIRMED-device |
| 40 | 8 | CIF | — | src |
| 41 | 9 | LCDC0 | `rk30-lcdc.0` (never fires on the RC2) | CONFIRMED-device |
| 42 | 10 | USB OTG | `dwc_otg` | CONFIRMED-device |
| 43 | 11 | USB host | `dwc_otg, host20_hcd` | CONFIRMED-device |
| 44, 45 | 12, 13 | GPS, GPS timer | — | src |
| 46 | 14 | SDMMC | `rk29_sdmmc.0` | CONFIRMED-device |
| 47 | 15 | SDIO | `rk29_sdmmc.1` | CONFIRMED-device |
| 48 | 16 | eMMC | `emmc` | CONFIRMED-device |
| 49 | 17 | SAR-ADC | `rk30-adc` | CONFIRMED-device |
| 50 | 18 | NANDC | `nandc` | CONFIRMED-device |
| 51 | 19 | I2S | — (on RK3036 I2S is SPI 51; do not mix them up) | src |
| 52, 53, 54 | 20, 21, 22 | UART0/1/2 | UART0 = `ttyS0`; UART2 = FIQ debugger (an FIQ, not listed) | CONFIRMED-device / -dis |
| 55 | 23 | SPI0 | `rk29xx_spim` | CONFIRMED-device |
| 56–59 | 24–27 | I2C0–I2C3 | `rk30_i2c.0` … `.3` | CONFIRMED-device |
| 60, 61 | 28, 29 | TIMER0/1 | `rk_timer0`; TIMER1 is the clocksource, no IRQ | CONFIRMED-device |
| 62–64 | 30–32 | PWM0–2 | — | src (DS: PWM2 only on RK3028A) |
| 66 | 34 | watchdog | — | src |
| **67** | **35** | OTG bvalid | `bvalid` | CONFIRMED-device |
| 68–71 | 36–39 | GPIO0–3 (bank) | chained; single GPIOs appear from 160 | CONFIRMED-device |
| 72 | 40 | crypto | — | src |
| 73, 74 | 41, 42 | peripheral AHB USB / EMEM arbiter | — | src |
| 75 | 43 | LCDC1 | — | src |
| 76 | 44 | RGA | `rga` | CONFIRMED-device |
| 77 | 45 | HDMI | — | not in RK3026 |
| 78, 79 | 46, 47 | SDMMC detect, SDIO detect | — | src |
| 80 | 48 | IEP | — | src |
| **81** | **49** | **EBC** | `rk29-ebc` | CONFIRMED-device |
| **83** | **51** | OTG0 id | `otg-id` | CONFIRMED-device |
| 84, 85 | 52, 53 | OTG0 / OTG1 line state | — | src; matches the `usb2phy` node of `rk3036.dtsi` |
| 86 | 54 | SD detect (n) | — | src |
| 118 | 86 | ARM PMU | — | src; one interrupt for both cores or one each [VERIFY] |
| 127 | 95 | UART signal (`debug-signal`) | `debug-signal` | CONFIRMED-device; a software-raised SPI of the FIQ debugger, not needed in a DT |

### 2.3 GPIO interrupts on the RC2

GPIO numbering of the vendor kernel: `gpio = 128 + 32·bank + 8·port + pin`, and `gpio_to_irq()` is the identity
(`rk30_gpio_init: 128 gpio irqs in 4 banks` in the log) [CONFIRMED-device]. In a DT: `<&gpioB RK_Pxn IRQ_TYPE_…>`.
Triggers as programmed by stock (GPIO `INTTYPE_LEVEL`/`INT_POLARITY` registers read on the device; all unmasked, none pending):

| IRQ | GPIO | Stock name | What | Trigger now | DTS |
|---|---|---|---|---|---|
| 160 | GPIO1_A0 | `main_ttsp_core.cyttsp4_i2c_adapter` | touch | level low | `IRQ_TYPE_LEVEL_LOW` |
| 164 | GPIO1_A4 | `play` | power key | edge falling | `gpio-keys` (the vendor driver flips the polarity itself) |
| 168 | GPIO1_B0 | `magic_int` | cover (magnet) sensor | edge falling | `IRQ_TYPE_EDGE_FALLING` |
| 169 | GPIO1_B1 | `bat_low_detect` | CW2015 ALRT | edge falling | not used by mainline `cw2015_battery` |
| 171 | GPIO1_B3 | `rtc_hym8563` | RTC | level low | `IRQ_TYPE_LEVEL_LOW` (the mainline default) |
| 195 | GPIO2_A3 | `sd_detect` | microSD card detect | level low | `cd-gpios … GPIO_ACTIVE_LOW` |
| 205, 206 | GPIO2_B5, B6 | `pageup`, `pagedown` | page keys | edge falling | `gpio-keys` |
| 211 | GPIO2_C3 | `esc` | back key | edge falling | `gpio-keys` |
| 235 | GPIO3_B3 | `adc_irq_io` | ADC-key interrupt | edge rising | only if the ADC keys exist on V1.73 |

## 3. CRU (0x20000000)

### 3.1 Registers

Offsets from RY `mach-rk3026/include/mach/cru.h`; they match the mainline `RK2928_*` macros in `drivers/clk/rockchip/clk.h`
exactly [CONFIRMED-src].

| Register | Offset | Write rule |
|---|---|---|
| `PLL_CON(id, 0..3)` | `0x10·id + 4·i`: APLL 0x00, DPLL 0x10, **CPLL 0x20**, GPLL 0x30 | CON0/CON1 hiword-masked; CON2 (fraction) a plain 32-bit register |
| `MODE_CON` | 0x040; bit `4·id`: 0 = slow (24 MHz), 1 = normal | hiword |
| `CLKSEL_CON0..34` | 0x044 + 4·i | hiword, **except** the 32-bit fractional dividers CON7 (I2S) and CON17–19 (UART0–2); by their reset value 0x0BB8EA60 also CON6, 8, 9, 20. **CON23 (`dclk_ebc`) is not hiword either** (below) |
| `CLKGATE_CON0..9` | 0x0d0 + 4·i | hiword; 1 = clock gated |
| `GLB_SRST_FST` / `SND` | 0x100 / 0x104 | magic value |
| `SOFTRST_CON0..8` | 0x110 + 4·i | hiword; 1 = held in reset |
| `MISC_CON`, `GLB_CNT_TH` | 0x134, 0x140 | |

**Hiword mask:** bits 31:16 enable the write of the matching bits 15:0. A write without the mask bit leaves that bit alone,
so no read-modify-write is needed. In mainline these are the `CLK_*_HIWORD_MASK` and `ROCKCHIP_SOFTRST_HIWORD_MASK` flags
that every Rockchip clock driver sets; a plain syscon regmap does not work without them.

**CLKSEL23 keeps its upper half** [value CONFIRMED-device, conclusion STRONG]: stock writes the `dclk_ebc` divider as a hiword
write (`0xFF000000 | 3 << 8`) and the register reads back exactly **0xFF000300**. Every other hiword CLKSEL in the dump reads
with a zero upper half (CLKSEL27/28 read 0xFF01 after the same kind of write). So model `dclk_ebc` as a plain read-modify-write
mux/divider, or check with one write first [VERIFY].

### 3.2 PLLs

- Ids: APLL 0 (ARM), DPLL 1 (DDR), CPLL 2 ("codec PLL"), GPLL 3.
- Fields: CON0 FBDIV[11:0], POSTDIV1[14:12], BYPASS[15]; CON1 REFDIV[5:0], POSTDIV2[8:6], LOCK[10] (read), DSMPD[12],
  PWR_DN[13]; CON2 FRAC[23:0]. **This is the `pll_rk3036` type** of mainline `clk-pll.c` [CONFIRMED-src]. Integer mode
  (DSMPD = 1): `Fout = 24 MHz × FBDIV / REFDIV / POSTDIV1 / POSTDIV2`.
- Read on the device [CONFIRMED-device]:

| PLL | CON0 / CON1 | FBDIV | REFDIV | POSTDIV1 / 2 | Fout | Kernel view |
|---|---|---|---|---|---|---|
| APLL | 0x204C / 0x1441 | 76 | 1 | 2 / 1 | **912 MHz** | `arm_pll` 912 MHz |
| DPLL | 0x2042 / 0x1441 | 66 | 1 | 2 / 1 | **792 MHz** | DDR 396 MHz (`DDR DEBUG: init success!!! freq=396MHz`) |
| CPLL | 0x1050 / 0x1443 | 80 | 3 | 1 / 1 | **640 MHz** | `codec_pll` 640 MHz |
| GPLL | 0x1020 / 0x1441 | 32 | 1 | 1 / 1 | **768 MHz** | `general_pll` 768 MHz |

  All four are in normal mode (`MODE_CON` 0x1111), all with DSMPD = 1 and LOCK = 1. These are the entries a `clk-rk3026.c`
  rate table needs.
- **CPLL is retuned by the EBC driver once.** RY's board header sets CPLL to 594 MHz at boot; the EBC probe asks for
  `dclk_ebc` = 4 × 40 MHz = 160 MHz, and the vendor clock code then scans 700 MHz downward for the first exact multiple
  (div 4 → CPLL 640 MHz). With the display idle CPLL is still 640 MHz: it is set once at probe and never moved back or retuned
  per update [CONFIRMED-device]. Side effects on the other CPLL children: `hclk_disp_pre` 320 MHz (asked 300), I2S 12.164 MHz
  (asked 11.2896; there is no speaker on V1.73).
- The loader (FlashData) leaves APLL 600 MHz, GPLL 132 MHz and DDR 300 MHz; under the stock kernel DDR runs at 396 MHz.

### 3.3 Clocks, gates and resets of the RC2 blocks

From RY `mach-rk3026/clock_data.c` and `cru.h`. Gate number = 16·CON + bit, reset number = 16·CON + bit; written CON/bit.

| Block | Clock: register / field (parents) | Gates | Resets |
|---|---|---|---|
| **EBC** | `dclk_ebc`: CLKSEL23 div[15:8], src[0] (0 = CPLL, 1 = GPLL). On the device: div 3, src 0 → **160 MHz** from CPLL 640 MHz [CONFIRMED-device] | `DCLK_EBC_SRC` 3/4; `HCLK_EBC` 9/9 (from `hclk_disp_pre`: CLKSEL30 div[12:8], src[15], gate 0/11). Stock also enables `aclk_lcdc1` (9/6, through `ACLK_VIO1` 9/10, parent CLKSEL31) and the `pd_lcdc1` domain | `EBC_AXI` 7/11, `EBC_AHB` 7/12 |
| SDMMC0 | CLKSEL11 div[5:0], src[6] (CPLL/GPLL) | `MMC0_SRC` 2/11; `HCLK_SDMMC0` 5/10 | `MMC0` 5/1 |
| SDIO | CLKSEL12 div[5:0], src[6] | `SDIO_SRC` 2/13; `HCLK_SDIO` 5/11 | `SDIO` 5/2 |
| eMMC | CLKSEL12 div[13:8], src[7] | `EMMC_SRC` 2/14; `HCLK_EMMC` 7/0 | `EMMC` 5/3 |
| USB OTG / host | PHY from 12 MHz | `OTGPHY0` 1/5, `OTGPHY1` 1/6; `HCLK_OTG0` 5/13, `HCLK_OTG1` 7/3, both need `HCLK_USB_PERI` 9/13 | `USBOTG0` 4/5, `OTGC0` 4/7, `USBOTG1` 4/8, `OTGC1` 4/10, `UTMI0/1` 6/7–8, `USBPOR` 6/9, `USB_PERI` 3/15 |
| I2C0–3 | `pclk_peri` only | `PCLK_I2C0..3` 8/4–7 | `I2C0..3` 2/11–14 |
| UART0–2 | `uart_pll` src CLKSEL12[15] (GPLL/CPLL); div CLKSEL13–15 [6:0]; fraction CLKSEL17–19; mux CLKSEL13–15 [9:8] (div / frac / 24 MHz) | `UARTn_SRC` 1/8,10,12; `UARTn_FRAC` 1/9,11,13; `PCLK_UARTn` 8/0–2 | `UART0..2` 2/7–9 |
| PWM0/1 | `pclk_peri` | `PCLK_PWM01` 7/10 | `PWM0` 3/0, `PWM1` 3/1 |
| SPI0 | CLKSEL25 div[6:0], src[8] | `SPI0_SRC` 2/9; `PCLK_SPI0` 7/12 | `SPI0` 5/4 |
| SAR-ADC | from 24 MHz, CLKSEL24 div[15:8] (device: 200 kHz) | `SARADC_SRC` 2/8; `PCLK_SARADC` 7/14 | `SARADC` 5/7 |
| TIMER0/1 | mux CLKSEL2 [4]/[5] (24 MHz) | `TIMER0/1` 1/0–1; `PCLK_TIMER0` 7/7 (see below) | `TIMER0/1` 1/11–12 |
| GPIO0–3 | `pclk_peri` | `PCLK_GPIO0..3` 8/9–12 | `GPIO0..3` 2/0–3 |
| Peripheral buses | `aclk_peri` CLKSEL10 div[4:0], src[15] (GPLL/CPLL); hclk [9:8], pclk [13:12] (powers of two) | 2/0–3 | |
| CPU1 | — | — | `CORE1` **0/4** (`MCORE` 0/2, `CORE0` 0/3) |

Seen on the device:
- **The EBC clocks are never gated at idle** [CONFIRMED-device]: `dclk_ebc`, `hclk_ebc`, `aclk_lcdc1` and `pd_lcdc1` all have a
  use count equal to the number of display updates since boot plus one, so the stock driver enables them on every update and
  never disables them. Whether the EBC survives gating between updates is untested [VERIFY].
- **TIMER1 runs with its own gate closed**: `PCLK_TIMER1` (7/8) is gated while TIMER1 at 0x20044020 is the running
  clocksource. TIMER1 sits in the TIMER0 APB block and lives on `PCLK_TIMER0` (7/7); gate 7/8 belongs to the unused RK2928-style
  block at 0x20046000. Mainline needs one `pclk_timer`, as for RK3036 [CONFIRMED-device + STRONG].
- UART2 (the FIQ debugger) runs from `xin24m` through the CLKSEL15 mux.
- `SOFTRST_CON0..8` read 0: nothing held in reset, CPU1 released.

### 3.4 Against mainline `clk-rk3036.c` and `clk-rk3128.c`

| What | RK3026 | RK3036 (`clk-rk3036.c`) | Verdict |
|---|---|---|---|
| Register layout, PLL type | `RK2928_*`, `pll_rk3036` | same | same |
| PLLs | APLL, DPLL, **CPLL**, GPLL; mode bits 0/4/8/12 | APLL, DPLL, GPLL (mode bits 0/4/12) | RK3036 has no CPLL; `clk-rk3128.c` has 4 PLLs with CPLL at `RK2928_PLL_CON(8)` and mode bit 8, like RK3026 |
| Parent muxes | 1 bit (CPLL/GPLL) | 2 bits (APLL/DPLL/GPLL) | different (RK3128: 2–3 bits) |
| SDMMC | CLKSEL11 div[5:0], src[6] | mux CLKSEL12[9:8], div CLKSEL11[6:0] | different |
| SDIO / eMMC / `uart_pll` | CLKSEL12 [5:0]+[6] / [13:8]+[7] / [15] | other fields | different |
| UART div/frac/mux, timers, SPI div, `hclk_disp_pre` div | | | same (except the mux width) |
| Peripheral gates (SDMMC/SDIO/EMMC/OTG/I2S hclks, timer/PWM/SPI/WDT/UART/I2C/GPIO pclks, OTGPHY0, LCDC) | | | bit for bit the same |
| Peripheral resets | | | the same numbers |
| Core resets (CON0) | MCORE 2, CORE0 3, **CORE1 4** | CORE0 0, CORE1 1 | different |
| EBC, IEP, LCDC0, CIF, crypto | present | absent | RK3026 only (RK3128 also has EBC clocks in mainline) |

Verdict [STRONG]: a new `clk-rk3026.c` with its own `dt-bindings/clock/rk3026-cru.h`; PLL part after `clk-rk3128.c`, peripheral
gates and resets after `clk-rk3036.c`. Restart: the vendor reboots through a core reset run from SRAM (RY `reset.c`), not
through the global resets. On the RC2 `GLB_SRST_SND` (0xeca8, the mainline restart handler) and `GLB_SRST_FST` (0xfdb9) both
restart through the BootROM, once the IMEM remap is off and the first stage invalidates L1 (§4.5) [CONFIRMED-device, ML-RC2].

## 4. GRF (0x20008000)

### 4.1 Registers that matter

Offsets from RY `mach-rk3026/include/mach/grf.h`. All control registers below are hiword-masked, except `OS_REG*` and
`CHIP_TAG`. "Device" = value read on the RC2 at idle [CONFIRMED-device].

| Offset | Register | Meaning on the RC2 | Device | Mainline |
|---|---|---|---|---|
| 0x0a8 + 0x10·bank + 4·port | `GPIOnX_IOMUX` | 2 bits per pin, function 0…3 (§5). GPIO3 has only C (0xe0) and D (0xe4); ports 3A/3B have no mux register | §5 | `rockchip,rk2928-pinctrl`: mux at 0xa8, 4 banks × 32 — same |
| 0x118 + 8·bank + 4·(pin/16) | `GPIOnL/H_PULL` | 1 bit per pin: **1 = pull disabled**, 0 = pull enabled in the pin's own direction (up or down; the datasheet gives GPIO2_B/C a pull-down) | §5.2 | `rk2928_calc_pull_reg_and_bit`; DTS: only `bias-disable` / `bias-pull-pin-default` |
| 0x140 | `SOC_CON0` | **bit 12: IMEM mapped at address 0** (set by the loader for CPU1; the vendor clears it only before a reboot). Survives a warm reset (§4.5) | 0x1420: remap still on at run time | RK3026 mainline: set only around the CPU1 reset pulse (§4.3) |
| 0x144 | `SOC_CON1` | **bits 11–14: I2C0…I2C3 served by the new rk30 controller** (mask bits 27–30) | 0x7802: all four set | `i2c-rk3x` writes `BIT(27+n) \| BIT(11+n)`, but no SoC uses offset 0x144: a `rockchip,rk3026-i2c` with `grf_offset = 0x144` is needed |
| 0x148 | `SOC_CON2` | idle requests, bits 8–13 | 0x0082: no requests | `rk3036_pm_domains` uses bits 8–14 at the same offset |
| 0x14c | `SOC_STATUS0` | idle acks 16–21, idle 22–27; **USB: bvalid bit 7, DP/DM 9:8, id bit 10** | 0x04BF with the cable: bvalid 1, id 1 (B-device), line state 0 | RK3036 table: bvalid bit 8, line state 10:9, id bit 11 — **shifted by one**, so the RK3036 data does not fit |
| **0x150** | `LVDS_CON0` | **bit 0 `DATA_SEL`: 1 = the EBC data lines drive the LVDS pads (`LCDC_D0..D9`)**, 0 = LCDC; bit 8 LVDS PLL off; bit 9 LVTTL mode. Stock sets bit 0 when the panel powers up and writes 0xFFFF0300 at power-down | 0x0300 at idle: EBC lines off the pads | an EBC driver must do this itself (through `rockchip,grf`) |
| 0x17c | `UOC0_CON0` | OTG PHY: bvalid IRQ enable/status bits 14/15, line-state bits 12/13 | 0x4002 | `rk3036_phy_cfgs` uses the same register and bits |
| 0x190, 0x194 | `UOC1_CON0/1` | host PHY; 0x194 = suspend | 0x01D5 with Wi-Fi off | same offset (RK3036 suspend value 0x1d1) |
| 0x1a0 | `UOC_CON` | OTG id interrupt: rise enable/status bits 0/1, fall bits 2/3 | 0xC2A5: both enabled, none pending | RK3036 has no id detection; the RK3128 table (`rk3128_phy_cfgs`) has exactly this layout |
| 0x1c8–0x1e4 | `OS_REG0..7` | 4 and 5 = reboot flags (§4.2) | `OS_REG4` 0xC3524200 after a normal boot, `OS_REG5` 0; `OS_REG1` **0x6281** = the DDR geometry word the vendor DDR init writes: DDR3, 1 channel, 1 rank, column 10, 8 banks, row 15, ×16 die [CONFIRMED-device: read after the stock DDR init; the open RK3026 DDR init in Mario Rugiero's U-Boot ([Oppen/u-boot](https://github.com/Oppen/u-boot), branch `bringup/rk3026-mainline`) writes the same word for this geometry, and the kernel log prints the same geometry] | `syscon-reboot-mode` at offset 0x1d8 (as `rk3036.dtsi`) |
| 0x280 / 0x2a0 | `USBPHY0/1_CON0..7` | PHY tuning | PHY0: 0x861F, 0xE007, 0x8EA8, 0x0200, 0x5556, 0x5555, 0x0005, 0x68C0; PHY1: 0x8618, 0xE007, 0x82AA, 0x0200, 0x5556, 0x5555, 0x0005, 0x68C0 | `phy_tuning` of RK3036 is its own; take RK3026 values from the device. PHY0 CON2 = 0x8EA8 is the value of a line commented out in RY ("fix otg signal"); RY's PHY1 CON7 write (0x78000000) is not visible [VERIFY why] |
| 0x300 | `CHIP_TAG` | nobody reads it | 0x292C | — |

Other words read at idle: `GPIO_DS` 0, `DMAC_CON0/2` 0xFFFE / 0x03D0, `CPU_CON0..5` 0x8207, 0, 0x7000, 0, 0x0600, 0x0E00, `OS_REG3`
0x13247865 (the cold-boot marker of the stock DDR init, §8). 0xd8 and 0xdc (no `GPIO3A/B_IOMUX`) were deliberately not read.

For mainline [STRONG]:
- pinctrl: the `rk2928` register layout fits, but **bank 3 ports A/B need `IOMUX_GPIO_ONLY`**: mainline counts mux offsets
  consecutively, so without the flag a GPIO request on 3A/3B (on the RC2: GPIO3_B3, the ADC-key IRQ) writes 0xd8/0xdc, which the
  RK3026 does not have. With the flag the mux write is skipped.
- `usb2phy`: the control registers are those of RK3036, the status bits are not; a `rk3026_phy_cfgs` = RK3036 base +
  `utmi_bvalid {0x14c,7,7}`, `utmi_ls {0x14c,9,8}`, `utmi_id {0x14c,10,10}` + id detection from RK3128.
- Power domains: there is no PMU (RY `pmu.h`: `pmu_power_domain_is_on` is always true), only idle requests in the GRF. The bit
  layout differs from `rk3036_pm_domains`; which bit is which domain (CPU, PERI, GPU, VIDEO, VIO) is [VERIFY].
- There are no IO-voltage-select registers in this GRF, so no `io-domains` node.

### 4.2 Reboot flags (`OS_REG4` 0x1d8, `OS_REG5` 0x1dc)

Vendor scheme (RY `reset.c`): `OS_REG4` is for the loader (`SYS_LOADER_REBOOT_FLAG` 0x5242C300 + type), `OS_REG5` the mode for
Linux. Then all CRU gates are opened, the IMEM remap is cleared, and control goes to a reset routine in SRAM.

Stock RC2 (`rk30_arch_reset` @0xc045c2a0) [CONFIRMED-dis]:

| `reboot` argument | `OS_REG4` | `OS_REG5` |
|---|---|---|
| `loader`, `bootloader` | 0x5242C301 | 6 (REBOOT) |
| `recovery` | 0x5242C303 | 6 |
| `charge` | 0 | 3 (CHARGE) |
| none | 0 | 6; after a panic 7 (PANIC) |

- The stock loader rewrites the flag into the "kernel" form: boot logs show `flag: NORMAL (0xc3524200)` and
  `RECOVER (0xc3524203)`, and the register reads 0xC3524200 after a normal boot [CONFIRMED-device].

What the stock loader (FlashBoot 2.32) does with `OS_REG4` at entry, read in its code [STRONG; 01 and 03 CONFIRMED-device,
they are `adb reboot loader` and `adb reboot recovery`]. It reads and writes the register as one 32-bit word and writes back
the "kernel" form 0xC35242xx (0xC3524200 for anything it does not know):

| `OS_REG4` at loader entry | Loader does |
|---|---|
| 0x5242C301 | Rockusb |
| 0x5242C302 (maskrom) | nothing, boots normally. The BootROM reads no flag either; the Rockusb "reset to maskrom" command takes another route: it writes `OS_REG4` = 0xEF08A53C and jumps to the BootROM, and the stock DDR init stage then refuses to run, so every copy fails and the ROM ends in USB MaskROM (§8) [STRONG, not tried on the device] |
| 0x5242C303 | recovery |
| 0x5242C304 | suppresses a recovery request |
| 0x5242C306 / 0x5242C307 | recovery with `--wipe_data` / `--wipe_all` |
| 0x1888AAFF | Rockusb. The loader writes this value itself before each write to the eMMC boot partitions, so an interrupted loader write comes back to Rockusb |
| anything else (0, 0x5242C300, 0x5242C305, 08, 09) | normal boot |

- Mainline `rk3036.dtsi` has `syscon-reboot-mode` at 0x1d8 with `BOOT_BL_DOWNLOAD` = 0x5242C301 and `BOOT_RECOVERY` = 0x5242C303:
  the same values as stock. Differences: mainline `mode-normal` writes 0x5242C300 (stock writes 0) and RK3036's
  `mode-bootloader` is `BOOT_FASTBOOT` (+9); both fall into the loader's "anything else" row and boot normally. Use
  `mode-bootloader = <BOOT_BL_DOWNLOAD>` for Rockusb [STRONG].
- `OS_REG5` survives a warm reset. Neither the BootROM [STRONG] nor the microSD stage2 of [`../bootrom/sdboot/`](../bootrom/sdboot/README.md)
  reads `OS_REG4`, so on the microSD path the flags only matter to a later stage that reads them.

### 4.3 CPU1

**The core soft reset does not hold the core** [CONFIRMED-device, ML-RC2]. Writing the assert value of `SRST_CORE1`
(`CRU_SOFTRST_CON0` bit 4, write 0x00100010) restarts CPU1 at address 0 at once; the bit then reads 1 and stays 1, and the
deassert write (0x00100000) does nothing to the core. Shown with a diagnostic kernel that put a recording stub at address 0
and then asserted only: the record appeared within microseconds of the assert write, the bit still read 1 100 ms later, and
the deassert left the record unchanged. So CPU1 runs whatever sits at address 0 **at the moment of the assert write**.

- Address 0 is the BootROM, or IMEM (0x10080000) while `GRF_SOC_CON0` bit 12 is set.
- **A secondary core in the BootROM** [CONFIRMED-dis on the ROM, [`../bootrom/README.md`](../bootrom/README.md)]: every core
  first writes 1 to IMEM+4; a core with MPIDR ≠ 0 then waits in a WFE loop until IMEM+4 == **0xDEADBEAF** and jumps to the
  address in IMEM+8, with no cache, MMU or SCU setup. Every SEV from CPU0 (each `spin_unlock`) wakes it for one more check, so
  if the remap is switched on while a core waits there, the next SEV resumes it in IMEM data.
- **Stock:** the loader sets the remap, puts its own vector table at address 0 (it sends a secondary core back to the ROM
  loop) and then asserts the CPU1 reset; it never deasserts it. The kernel copies its trampoline to IMEM+0 first and then
  writes assert and deassert back to back (the "power on" of the CPU1 domain, RY `pmu.h`); hotplug "power off" only leaves
  the core in a WFI loop. The reboot path clears the remap before any reset (§4.2).
- A custom loader that repeats the loader's steps boots the stock kernel from microSD with both cores up (`CPU1: Booted
  secondary processor`, `Brought up 2 CPUs`) [CONFIRMED-device].
- **Mainline** (`arch/arm/mach-rockchip/platsmp.c`): `rockchip,rk3066-smp` needs a PMU and does not fit.
  **`rockchip,rk3036-smp`** (`has_pmu = false`) enables the SCU, copies the trampoline to the `smp-sram` node at IMEM+0 and
  controls CPU1 only through the `resets` of `cpu@1` (`SRST_CORE1` = CON0 bit 4, id 4 when `rk3026-cru.h` numbers resets as
  16 · CON + bit). As is, it fails here: `rockchip_smp_prepare_cpus()` asserts the reset *before* it copies the trampoline,
  so CPU1 restarts into stale IMEM, and `rockchip_boot_secondary()` only deasserts. A clean v7.1.13 kernel prints `CPU1:
  failed to come online` [CONFIRMED-device]. What it needs [CONFIRMED-device with both]:
  1. without a PMU, assert right before the deassert in the "on" path (the trampoline is in IMEM by then) and skip the
     assert in the "off" path, which would restart a core that just went offline; no delay between the two writes;
  2. own the remap: set `GRF_SOC_CON0` bit 12 only around that pulse and clear it again once the new core runs from DDR. A
     remap left set for the whole uptime makes any later restart at address 0 land in the trampoline instead of the
     BootROM (§4.5).

  With both, 2 CPUs come up at boot (`smp: Brought up 1 node, 2 CPUs`), CPU1 hotplug (`echo 0` / `echo 1` to
  `cpu1/online`, three cycles) works with the offline core parked in its WFI loop, and a kernel started by kexec brings
  CPU1 up again [CONFIRMED-device].
- `CORE1_DBG` (bit 9) and the other core resets were never touched. Any other writer of `SRST_CORE1` starts the core.
- RK3036 (Cortex-A7, same method) cannot show this: a restarted core there waits in its BootROM for the mailbox.

### 4.4 Chip version

Nobody reads `CHIP_TAG`. The vendor takes the SoC version from the eFuse (byte 24 or 5; RY `plat-rk/efuse.c`); every RC2 log
prints `rk3026 soc version:4` [CONFIRMED-device].

### 4.5 Warm resets

Tested on the RC2 from mainline Linux and a mainline-based U-Boot started from microSD (ML-RC2). "Back" = the BootROM ran
its normal order again and booted the microSD card [CONFIRMED-device]:

| Reset | Write | Result |
|---|---|---|
| `GLB_SRST_SND` | CRU+0x104 = 0xeca8 (the mainline restart handler) | back; DDR kept |
| `GLB_SRST_FST` | CRU+0x100 = 0xfdb9 | back; DDR kept |
| core reset, the stock way | from IMEM: PLLs to slow mode, then `CRU_SOFTRST_CON0` = 0x801cffff (MCORE, CORE0, CORE1, L2C) | back; DDR kept |
| watchdog | dw-wdt at 0x2004c000 expires (a halted or spinning kernel that nobody feeds) | back; DDR kept |
| kexec | — | not a reset; the second kernel comes up with both CPUs |

"DDR kept": a boot counter word near the top of RAM, the stage2 log page and the ramoops buffer survive. After a kernel
panic and a watchdog reset, U-Boot's `pstore display` on the ramoops area (0x7ff40000, reserved in the DT) shows the whole
panic log, and the next kernel's `/sys/fs/pstore` still holds it.

What a warm reset does **not** clear, and what follows from it:

- **L1 caches.** The Cortex-A9 does not invalidate its caches on reset; software must. The stock kernel cleans and disables
  them before it resets, mainline's restart path does not, and a watchdog reset of a hung kernel cannot. A first stage that,
  like stock FlashBoot, only invalidates the I-cache and the branch predictor and runs with the D-cache off leaves the dead
  kernel's lines in L1 until the next kernel's decompressor turns the D-cache on (Linux `__armv7_mmu_cache_on` does not
  invalidate). Observed: after a reset from mainline the second kernel took an exception right at the decompressor's jump
  into the kernel. With a first stage that invalidates the whole L1 D-cache by set/way (DCISW over the CCSIDR geometry,
  invalidate only) plus TLBIALL, ICIALLU and BPIALL at entry, SND and FST resets from mainline come back
  [observation CONFIRMED-device; mechanism STRONG]. The sdboot stage2 ([`../bootrom/sdboot/`](../bootrom/sdboot/README.md))
  does exactly this at entry. U-Boot's `enable_caches` invalidates L1 before it turns the MMU on.
- **The GRF**, including the IMEM remap (`SOC_CON0` bit 12) [STRONG for SND: the vendor clears the remap before every reset,
  and every reset on the device came back only with it off; VERIFY for FST]. With the remap set, a core that restarts at
  address 0 lands in IMEM, not in the BootROM.
- **IMEM.** The BootROM rewrites only IMEM+0 (delay factor), +4 (mailbox) and +0xc (secure flag) [CONFIRMED-dis]; anything
  else a kernel left in IMEM 0x00–0x3f is still there in the next boot, right where a restarted CPU1 lands while the remap
  is set. With a diagnostic kernel that kept the remap set and left data there, warm resets into itself died between
  frames; clearing the remap and zeroing IMEM 0x00–0x3f before every reset, and setting the remap only around the CPU1
  pulse, made every such reset come back with 2 CPUs [fix CONFIRMED-device; mechanism (CPU1 running loose in IMEM) STRONG].
- **The power hold** (GPIO1_A2) stays high, so the board stays powered. A reset that never reaches the BootROM therefore
  leaves the book "dead" (panel black, no USB, the power key ignored because nothing reads it) until the reset pinhole
  [CONFIRMED-device for the symptom; STRONG for the explanation].

A reset with the pinhole, with the card left in, booted the eMMC every time so far, while a reset from software boots the
card [CONFIRMED-device; cause VERIFY, see [`../bootrom/sdboot/README.md`](../bootrom/sdboot/README.md) "Known failures"].

## 5. Pins

### 5.1 Mux of the RC2 pins

Register = 0xa8 + 0x10·bank + 4·port, field `[2·pin+1 : 2·pin]` (RY `iomux.h`). In a DTS: `rockchip,pins = <bank RK_Pxn k &pcfg_…>`
with the same function number k. Wiring from [`../board/README.md`](../board/README.md) §1 and §7(b). The "Idle" column is the
state read on the device with the display idle [CONFIRMED-device].

| Pin | GRF / bits | On the RC2 | Function k | Other functions | Idle |
|---|---|---|---|---|---|
| GPIO0_A0 / A1 | 0xa8 [1:0] / [3:2] | I2C0 SCL / SDA | 1 | — | as listed |
| GPIO0_A2 | 0xa8 [5:4] | vibrator, active low | 0 | 1 = I2C1_SCL | output high (off) |
| GPIO0_A3 | 0xa8 [7:6] | ACT8931 VSEL (`pmu_gpio`) | 0 | 1 = I2C1_SDA | **output high** |
| GPIO0_D2 | 0xb4 [5:4] | PWM0 frontlight | 1 | — | PWM, pad 0 (light off) |
| GPIO0_D3 | 0xb4 [7:6] | touch reset, active low | 0 | 1 = PWM1 | output high (released) |
| GPIO1_A0 | 0xb8 [1:0] | touch IRQ | 0 | 1 = I2S0_MCLK | input |
| GPIO1_A1 | 0xb8 [3:2] | charge-current select 2 | 0 | I2S0_SCLK | output high |
| GPIO1_A2 | 0xb8 [5:4] | **power hold** | 0 | I2S0_LRCKRX, GPS_CLK | output high |
| GPIO1_A4 | 0xb8 [9:8] | power key | 0 | I2S0_SDO, GPS_MAG | input |
| GPIO1_A5 | 0xb8 [11:10] | Wi-Fi/BT power, active low | 0 | I2S0_SDI, GPS_SIGN, 3 = JTAG_TCK | output high (Wi-Fi off) |
| GPIO1_B0…B3 | 0xbc [7:0] | cover sensor IRQ, CW2015 ALRT, charge-current select, RTC IRQ | 0; 1 = SPI0 CLK/TXD/RXD/CS0 only while the panel flash is read | 2 = UART1 CTSN/SOUT/SIN/RTSN; B2: 3 = JTAG_TMS | GPIO; B2 output low |
| GPIO1_B7, C0, C2–C5 | 0xbc [15:14]; 0xc0 | microSD CMD, CLK, D0–D3 | 1 | C4/C5 switch to JTAG by themselves while `sdmmc0_detectn` is inactive (not a mux function) | GPIO low with no card |
| GPIO1_C6, C7, D0–D7; GPIO2_A5, A7 | | eMMC CMD, RSTN, D0–D7, PWREN, CLKOUT | 2 | NAND | eMMC |
| GPIO2_A3 | 0xc8 [7:6] | microSD card detect (eMMC boards) | 0 | 1 = NAND_RDN | **muxed to NAND_RDN on stock** (the eMMC module rewrites the whole GPIO2A register); the GPIO input still reads the pad. Keep it GPIO in a DTS |
| GPIO2_B0 / B1 / B3 | 0xcc [1:0] / [3:2] / [7:6] | EBC SDCLK / SDLE / GDCLK | 2 | 1 = LCDC0 DCLK / HSYNC / DEN | parked as GPIO output low |
| GPIO2_B2 | 0xcc [5:4] | panel-flash power, high | 0 | 2 = EBC_SDOE (unused) | output low |
| GPIO2_B4 | 0xcc [9:8] | `lcd_d10`, low (high in SRAM suspend) | 0 | 2 = EBC_SDCE2 | output low |
| GPIO2_B5 / B6 | 0xcc [11:10] / [13:12] | page up / down | 0 | 2 = EBC_SDCE3 / SDCE4 | input |
| GPIO2_B7 | 0xcc [15:14] | status LED, high | 0 | 2 = EBC_SDCE5 | output low |
| GPIO2_C0 | 0xd0 [1:0] | EBC_VCOM while the panel is on, otherwise GPIO | 2 / 0 | LCDC0_D14 | GPIO **output high** |
| GPIO2_C1 / C2 | 0xd0 [3:2] / [5:4] | EBC GDOE / GDSP | 2 | LCDC0_D15 / D16 | parked as GPIO output low |
| GPIO2_C3 | 0xd0 [7:6] | back key | 0 | 2 = EBC_GDPWR0 | input |
| GPIO2_C4 / C5 | 0xd0 [9:8] / [11:10] | **I2C2 SDA / SCL** (touch, TPS65185) | **3** | 2 = EBC_GDRL / EBC_SDSHR | as listed |
| GPIO2_C6 / C7 | 0xd0 [13:12] / [15:14] | **UART2 RX / TX** (stock FIQ debugger; BootROM download) | 3 | 2 = EBC_BORDER0 / BORDER1 | as listed; RX reads 0 with its internal pull on (nothing pulls it up) |
| GPIO2_D0 / D1 | 0xd4 [1:0] / [3:2] | EBC GDPWR1 / GDPWR2 | 2 | LCDC0_D22 / D23 | stay in the EBC function |
| GPIO3_B3 | none | ADC-key IRQ | GPIO | — | input |
| GPIO3_C1 | 0xe0 [3:2] | TPS65185 WAKEUP | **0** | 1 = OTG_DRV_VBUS (do not select) | **output high** |
| `LCDC_D0…D9` pads (LVDS_TX0P…TX3N, LVDS_CLKP/N) | **`GRF_LVDS_CON0` bit 0** | **EBC SDDO0–7, SDCE0, SDCE1**: the panel source data | 1 = EBC | 0 = LCDC/LVDS | 0 (off between updates) |

- **The EBC pins are eight GPIO2 pins in function 2 plus the `DATA_SEL` bit** in the GRF (the data lines are not in the iomux at
  all; DS V1.2, pins 47–56). SDOE, SDCE2–5, GDPWR0, GDRL, SDSHR and BORDER0/1 are used for other things on the RC2.
- SPI0 shares GPIO1_B0..B3 with interrupt lines; the DTS needs a separate pinctrl state for the panel-flash read, not a permanent
  mux ([`../panel-flash/README.md`](../panel-flash/README.md)).
- Beyond the table, stock also muxes GPIO0_A6/A7 to I2C3, GPIO0_C0–C3 to UART0 (with `PCLK_UART0` gated), GPIO1_B6 to MMC0_PWREN
  and GPIO2_A0–A4/A6 to NAND.

### 5.2 Pulls

Read on the device [CONFIRMED-device]:

| Register | Value | Pull disabled on | Pin levels |
|---|---|---|---|
| GPIO0L/H (0x118/0x11c) | 0 / 0 | none | — |
| GPIO1L (0x120) | 0x0110 | **A4** (power key), **B0** (cover sensor) | both 1 |
| GPIO1H (0x124) | 0 | none | — |
| GPIO2L (0x128) | 0x6000 | **B5, B6** (page keys) | both 1 |
| GPIO2H (0x12c) | 0x0038 | **C3** (back key), **C4, C5** (I2C2) | all 1 |
| GPIO3L/H (0x130/0x134) | 0 / 0 | none | — |

- **Keys and cover sensor: stock disables the internal pull and the lines idle high, so the board has external pull-ups → DTS
  `bias-disable`** for GPIO1_A4, GPIO1_B0, GPIO2_B5, GPIO2_B6, GPIO2_C3. (The datasheet gives GPIO2_B/C a pull-down, which would
  fight an active-low key if left on.)
- I2C2: pull disabled, idle high → external pull-ups. I2C0 keeps the internal pull.
- The touch IRQ GPIO1_A0, CW2015 ALRT GPIO1_B1 and RTC IRQ GPIO1_B3 keep the internal pull **enabled** (the board file suggested
  "no pull" for GPIO1_A0; the register says otherwise) [CONFIRMED-device for the register state].

## 6. Datasheet contradictions, resolved

| Question | DS V1.1 | DS V1.2 | Answer |
|---|---|---|---|
| BootROM download UART | "USB OTG, **UART1**" | "USB OTG, **UART2**" | **UART2** [CONFIRMED]: in the BootROM disassembly the eMMC-boot wait initialises UART2 (115200 8N1 on GPIO2_C6/C7) and sends `D2 "RK292C" D2` ([`../bootrom/README.md`](../bootrom/README.md)). In the V1.2 pin table these pins are `LCDC_D20/EBC_border0/UART2_RX/GPIO2_C6` and `LCDC_D21/EBC_border1/UART2_TX/GPIO2_C7` |
| DDR per rank | "2 ranks, 1 GB (max) per rank" (revision note: "Update 512MB to 1GB") | "2 ranks, 256 MB (max) per rank" | V1.2 is wrong for the RC2 [CONFIRMED]: the kernel prints `DDR DEBUG: 1 CS, ROW=15, Bank=8, COL=10, Total Capability=512MB`: **one rank of 512 MB** (DDR3 4 Gb ×16 on a 16-bit bus) |
| I2C, PWM, HDMI | | "4 I2C in RK3028A and 3 in RK3026", "Three PWMs in RK3028A and 2 in RK3026", "HDMI … only by RK3028A" | the stock kernel still registers an I2C3 region (no devices) and muxes its pins; whether the block physically exists is [VERIFY] |
| SAR-ADC channels | | "2-channel in RK3026", pins `SARADC_AIN[2:0]` | the stock key table reads **channel 3** (ok/menu ADC keys, which may not be fitted on V1.73) [VERIFY by reading channel 3] |
| EPD LUT size | | "up to 128 frames", "LUT updateable (8KB)" | both generations of the vendor driver use a 6-bit frame count and a 4 KB LUT window (64 frames × 16 words); see [onyx-rc2-ebc](https://github.com/hsw/onyx-rc2-ebc) `driver/registers.md` |

Other boot facts (BootROM order SD → NAND → SPI NOR → SPI NAND → eMMC → USB OTG + UART2, fixed, no strap) are in
[`../bootrom/README.md`](../bootrom/README.md). There is no UART connector on the RC2 and no test points for UART2 have been found;
the stock FIQ debugger on UART2 is therefore of little use.

## 7. Still [VERIFY]

- What lies at GRF 0xd8/0xdc (no `GPIO3A/B_IOMUX`) and whether writing there is safe.
- Whether `GLB_SRST_FST` keeps the GRF (`OS_REG4/5`, the IMEM remap) as SND does (§4.5); both global resets themselves work.
- After a halt and a watchdog reset CPU1 once failed to come online in the next mainline boot; not reproduced in two
  repeats.
- Why a pinhole reset skips the microSD card while software resets boot it (§4.5).
- The ARM PMU interrupt (SPI 86): shared or per core.
- Physical presence of I2C3, PWM2, GPS; SAR-ADC channel 3.
- Bits of the idle requests in `SOC_CON2` / `SOC_STATUS0` per domain; QoS offsets in the CPU AXI window.
- CLKSEL23 write behaviour (one test write); EBC clock gating between updates.
- PL310 attributes for mainline (stock `AUX_CTRL` 0x76030001).
- Whether the eMMC controller has the dw_mmc internal DMA (IDMAC, `BMOD`/`DBADDR`): stock uses the external PL330 through
  the controller's DMA interface (§1.1); a register dump or a test would tell.

## 8. DDR init by the stock first stage (FlashData)

The init stage of the stock loader's IDB (FlashData, banner `DDR Version 1.08 20140618`) is a complete DDR3 bring-up. Read
from its code and an emulated run [STRONG; the resulting `GRF_OS_REG1` CONFIRMED-device]. Mario Rugiero's open RK3026 DDR
init ([Oppen/u-boot](https://github.com/Oppen/u-boot), branch `bringup/rk3026-mainline`, SPL) issues the same DDR controller,
PHY and NoC writes in the same emulation; it leaves out the clock setup, the detection and the memory test.

- **Clocks:** APLL 600 MHz (CON0/CON1 0x7fff304b / 0x11ff1041: 24 × 75 / 3), GPLL 132 MHz, sdmmc0 = GPLL / 4; then DPLL
  600 MHz = **DDR 300 MHz** (the stock kernel later runs DDR at 396 MHz).
- **Controller:** PCTL and PHY soft reset (`CRU_SOFTRST_CON5` bits 8–11), PHY DLL setup, uPCTL DFI and timing registers
  (at 300 MHz: TCL 6, TCWL 5, TRFC 105, TREFI 78, TRAS 12, TRC 16, TRCD 6, TRP 6, TWR 5), MCFG 0x00050021 (BL8, DDR3, no
  auto power-down), no auto self-refresh; `GRF_SOC_CON2` bit 7 (DDR3 select of the memory scheduler); NoC DdrTiming
  (0x1012800c) = 0x24716310, ReadLatency (0x10128014) = 0x3f, DdrConf 2.
- **PHY:** DQ drive (REG25/26) 0xbb = 44 Ω, DQ ODT (REG27/28) 0x44 = 216 Ω (codes from the RK3026 tables of the vendor
  `ddr.c` in RY); CL 6, AL 0, BL8.
- **Mode registers:** MR2 = 0 (CWL 5), MR3 = 0, MR1 = 0x42 (DLL on, drive RZQ/7 = 34 Ω, Rtt_Nom RZQ/2 = 120 Ω), MR0 = 0x320
  (BL8, CL 6, WR 5, DLL reset); then ZQCL.
- **DQS squelch (gate) calibration** by the PHY, then two refreshes. No write leveling, no read-eye training, no PHY impedance
  calibration (fixed drive and ODT codes).
- **Geometry probing** with test patterns at a few addresses near the start of DRAM: column 10, 8 banks, row 15, 1 rank,
  ×16 die = 512 MiB → DdrConf 2 and **`GRF_OS_REG1` = 0x6281** (§4.1); then an address-in-address memory test.
- **Cold and warm path:** a power-on finds no marker, clears `OS_REG0..7` and sets `OS_REG3` = 0x13247865. With the marker
  present and a geometry in `OS_REG1` it takes a warm path: the same controller init with the stored geometry, and no
  DRAM write at all, which keeps DRAM contents across a warm reset. Even a cold run writes only its probe and memory-test
  words at the bottom of DRAM, not the top of RAM where ramoops and the loader logs live.
- **MaskROM gate:** with the marker present and `OS_REG4[15:0]` = 0xa53c it returns "failed" without touching DDR; the BootROM
  then tries the next copy and the next medium and ends in USB MaskROM. That is how the stock loader's "reset to maskrom"
  works (§4.2) [STRONG, not tried on the device].
- **Console:** UART2 at 115200 8N1 on GPIO2_C6/C7; without VBUS it switches the USB PHY to UART mode (GRF 0x20008190), so the
  banner goes out on the USB D+/D− pins.
