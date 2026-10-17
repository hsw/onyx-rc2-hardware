/* SPDX-License-Identifier: MIT */
/* sdboot stage2 entry. The RK3026 BootROM loads this image to DDR 0x60000000 and jumps to +0 in ARM state
 * (../../README.md §3). First thing: power hold, so the board stays on when the power key is released. Then the
 * same CPU setup as stock FlashBoot's entry (MMU, D-cache, I-cache, branch prediction off), plus an L1 invalidate that
 * stock FlashBoot does not do (below), then a position-independent copy of the whole image to its link address
 * STAGE2_BASE, so that 0x60000800 is free for the ATAG list (the stock place).
 *
 * Why the L1 D-cache invalidate: the Cortex-A9 does not invalidate its caches on reset, software must. After a warm
 * reset (GLB_SRST_FST/SND, watchdog) from a kernel that did not clean its caches first, L1 still holds that kernel's
 * valid and dirty lines. stage2 itself runs with the D-cache off, but the kernel's decompressor turns the D-cache on
 * without invalidating it, so stale lines hit or get written back over the freshly loaded/inflated kernel. On the
 * device (GLB_SRST_FST from mainline Linux, stage2 without this block): ROM, FlashData, stage2 and the decompressor
 * ran normally, then the jump to the kernel at 0x60008000 took an exception before stext (vector 0x08, FSR 8, FAR 0).
 * The stock 3.0 kernel cleans its caches before its reset and reboots fine through the same chain. So stage2
 * invalidates (never cleans: the dead kernel's dirty data must be dropped, not written back) the whole L1 D-cache by
 * set/way, unconditionally (also right after a cold boot), plus TLBs, I-cache and branch predictor. Once at entry is
 * enough: stage2 never sets SCTLR.C (icache_on sets I/Z only, rom_call clears them), and with the MMU off all data
 * accesses are strongly ordered, so no line can be allocated or become dirty between here and jump_kernel. L2 (PL310)
 * is not stage2's job: it is disabled at the decompressor's entry and the kernel invalidates it before enabling it;
 * CPU1's L1 is invalidated by the kernel's secondary startup (../../soc/README.md §4.5). */
/* bootinfo.h is C-only; the few constants used here are repeated */

#define GRF_BASE        0x20008000
#define GPIO1_BASE      0x20080000

    .section .text.start, "ax"
    .arm
    .global _start
_start:
    msr     cpsr_c, #0xd3              @ SVC, IRQ and FIQ masked (= stock FlashBoot entry)

    /* power hold: GPIO1_A2 output high (data first, then direction, as stock FlashBoot 0x60001500 does) */
    ldr     r0, =GRF_BASE
    ldr     r1, =0x00300000             @ GRF_GPIO1A_IOMUX: A2 bits [5:4] = 0 (GPIO), write-enable mask
    str     r1, [r0, #0xb8]
    ldr     r0, =GPIO1_BASE
    ldr     r1, [r0, #0x00]             @ SWPORTA_DR
    orr     r1, r1, #(1 << 2)
    str     r1, [r0, #0x00]
    ldr     r1, [r0, #0x04]             @ SWPORTA_DDR
    orr     r1, r1, #(1 << 2)
    str     r1, [r0, #0x04]

    /* caches off: like stock FlashBoot 0x6000022c */
    mrc     p15, 0, r0, c1, c0, 0
    bic     r0, r0, #0x5                @ M, C
    bic     r0, r0, #0x10000000         @ TRE
    bic     r0, r0, #0x3800             @ Z, I, V
    mcr     p15, 0, r0, c1, c0, 0
    dsb
    isb

    /* invalidate the whole L1 D-cache by set/way (DCISW), geometry from CCSIDR (the same walk as Linux
     * arch/arm/mm/cache-v7.S v7_invalidate_l1); see the header for why */
    mov     r0, #0
    mcr     p15, 2, r0, c0, c0, 0       @ CSSELR = 0: level 1, data cache
    isb
    mrc     p15, 1, r0, c0, c0, 0       @ CCSIDR
    and     r1, r0, #7
    add     r1, r1, #4                  @ r1 = set shift = log2(line bytes)
    ubfx    r2, r0, #3, #10             @ r2 = ways - 1
    clz     r3, r2                      @ r3 = way shift (32 for one way: lsl by 32 gives 0)
    ubfx    r4, r0, #13, #15            @ r4 = sets - 1
5:  mov     r5, r4                      @ r5 = set
6:  lsl     r6, r2, r3
    orr     r6, r6, r5, lsl r1
    mcr     p15, 0, r6, c7, c6, 2       @ DCISW (way r2, set r5)
    subs    r5, r5, #1
    bpl     6b
    subs    r2, r2, #1
    bpl     5b
    dsb
    mov     r0, #0
    mcr     p15, 0, r0, c8, c7, 0       @ TLBIALL
    mcr     p15, 0, r0, c7, c5, 0       @ ICIALLU
    mcr     p15, 0, r0, c7, c5, 6       @ BPIALL
    dsb
    isb

    /* relocate [load address, +image size) -> STAGE2_BASE */
    adr     r0, _start                  @ where the ROM put us
    ldr     r1, =_start                 @ link address
    ldr     r2, =__image_end
    cmp     r0, r1
    beq     2f
1:  ldr     r3, [r0], #4
    str     r3, [r1], #4
    cmp     r1, r2
    blo     1b
2:  ldr     r0, =_start
    adr     r1, _start
    ldr     pc, =relocated

relocated:                              @ r0 = link address, r1 = load address
    ldr     sp, =__stack_top
    ldr     r2, =__bss_start
    ldr     r3, =__bss_end
    mov     r4, #0
3:  cmp     r2, r3
    strlo   r4, [r2], #4
    blo     3b
    mov     r0, r1                      @ main(load_address)
    bl      stage2_main
4:  b       4b

/* rom_call(fn, a0, a1, a2): call a BootROM routine (ARM code) with three arguments. The I-cache and branch prediction
 * are switched off for the call and restored after it: the ROM never enables them, so its delay-based poll timeouts
 * (0x64c, IMEM+0 factor) are calibrated for uncached execution, exactly as during its own load of this image. */
    .text
    .global rom_call
rom_call:
    push    {r4, r5, r6, lr}
    mov     r4, r0
    mrc     p15, 0, r5, c1, c0, 0       @ save SCTLR
    bic     r6, r5, #0x1800             @ I, Z off
    mcr     p15, 0, r6, c1, c0, 0
    mov     r6, #0
    mcr     p15, 0, r6, c7, c5, 0       @ ICIALLU
    mcr     p15, 0, r6, c7, c5, 6       @ BPIALL
    isb
    mov     r0, r1
    mov     r1, r2
    mov     r2, r3
    blx     r4
    mcr     p15, 0, r5, c1, c0, 0       @ restore SCTLR
    isb
    pop     {r4, r5, r6, pc}

/* jump_kernel(entry, machine, atags): caches off as stock FlashBoot 0x60015884 (we never enabled the D-cache, L2 or
 * MMU, so only the I-cache and branch predictor are switched off; L1 D was invalidated at entry and has stayed
 * clean, see the header), CPSR 0xd3, r0 = 0, r1 = machine, r2 = atags. */
    .global jump_kernel
jump_kernel:
    msr     cpsr_c, #0xd3
    mov     r4, r0
    mrc     p15, 0, r3, c1, c0, 0
    bic     r3, r3, #0x1000             @ I
    bic     r3, r3, #0x0800             @ Z
    bic     r3, r3, #0x5                @ M, C
    mcr     p15, 0, r3, c1, c0, 0
    mov     r3, #0
    mcr     p15, 0, r3, c7, c5, 0       @ ICIALLU
    mcr     p15, 0, r3, c7, c5, 6       @ BPIALL
    dsb
    isb
    mov     r0, #0
    bx      r4

/* icache_on(): I-cache + branch prediction on (MMU stays off); only speeds up CRC32. */
    .global icache_on
icache_on:
    mov     r0, #0
    mcr     p15, 0, r0, c7, c5, 0
    mcr     p15, 0, r0, c7, c5, 6
    mrc     p15, 0, r0, c1, c0, 0
    orr     r0, r0, #0x1800
    mcr     p15, 0, r0, c1, c0, 0
    isb
    bx      lr

    .global read_cpsr
read_cpsr:
    mrs     r0, cpsr
    bx      lr

    .global read_sctlr
read_sctlr:
    mrc     p15, 0, r0, c1, c0, 0
    bx      lr

    .global read_mpidr
read_mpidr:
    mrc     p15, 0, r0, c0, c0, 5
    bx      lr

/* delay_loops(n): busy wait, 2 instructions per iteration */
    .global delay_loops
delay_loops:
    subs    r0, r0, #1
    bhi     delay_loops
    bx      lr

    .ltorg
