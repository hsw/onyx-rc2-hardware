/* SPDX-License-Identifier: MIT */
/* sdboot stage2: linked at STAGE2_BASE (bootinfo.h); the ROM loads it at 0x60000000 and start.S copies it here. */
ENTRY(_start)
MEMORY { ram (rwx) : ORIGIN = 0x60080000, LENGTH = 0x40000 }
SECTIONS
{
    .text : { KEEP(*(.text.start)) *(.text .text.*) } > ram
    .rodata : { *(.rodata .rodata.*) } > ram
    .data : { *(.data .data.*) } > ram
    . = ALIGN(4);
    __image_end = .;
    .bss (NOLOAD) : { __bss_start = .; *(.bss .bss.* COMMON) . = ALIGN(4); __bss_end = .; } > ram
    . = ALIGN(16);
    . = . + 0x4000;
    __stack_top = .;
    ASSERT(__stack_top <= 0x600c0000, "stage2 image + bss + stack exceeds STAGE2_END")
    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) *(.note*) }
}
