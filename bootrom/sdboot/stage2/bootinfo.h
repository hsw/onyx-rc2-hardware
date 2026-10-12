/* SPDX-License-Identifier: MIT */
/* sdboot stage2: card layout, boot table format, fixed addresses, status codes.
 * The Python side (../mkcard.py, ../tests/) mirrors these values; the Unicorn tests run the real binary against a card
 * built by mkcard.py, so a mismatch fails the tests. */
#ifndef SDBOOT_BOOTINFO_H
#define SDBOOT_BOOTINFO_H

/* ---- card (512-byte sectors) ---- */
#define BT_LBA            8192u        /* boot table: 2 sectors at 4 MiB */
#define BT_SECTORS        2u
#define BT_SIZE           1024u
#define BT_MAGIC          0x54423252u  /* "R2BT" little endian */
#define BT_VERSION        1u
#define BT_MAX_BLOBS      4u
#define BT_CMDLINE_OFF    0x100u
#define BT_CMDLINE_MAX    764u         /* bytes 0x100..0x3fb, NUL included */
#define BT_CRC_OFF        0x3fcu       /* CRC32 (zlib) of bytes [0, 0x3fc) */
#define BT_MIN_BLOB_LBA   (BT_LBA + BT_SECTORS)
#define BT_MAX_LBA        131072u      /* blobs end before partition 1 (64 MiB) */

#define BT_FLAG_HALT      0x1u         /* load + verify everything, then show "ready" and spin; never jump */
#define BT_FLAG_QUIET     0x2u         /* no progress blinks (failure patterns stay) */

#define BLOB_KERNEL       1u
#define BLOB_RAMDISK      2u
#define BLOB_DATA         3u           /* e.g. ebc_waveform.bin at waveform_addr */

#ifndef __ASSEMBLER__
struct bt_blob {
    unsigned kind, lba, size, load, crc32, rsv[3];
};

struct boot_table {                    /* 1024 bytes, little endian */
    unsigned magic, version, size, flags;
    unsigned machine, atags, entry, chunk_sectors;
    unsigned nblobs, cmdline_len, rsv[6];
    struct bt_blob blob[BT_MAX_BLOBS];  /* 0x40..0xbf */
    unsigned char pad[0x40];            /* 0xc0..0xff */
    char cmdline[BT_CMDLINE_MAX];       /* 0x100..0x3fb */
    unsigned crc32;                     /* 0x3fc */
};
#endif

/* ---- DDR (the ROM loads stage2 at 0x60000000; it moves itself to STAGE2_BASE) ---- */
#define DDR_BASE          0x60000000u
#define DDR_END           0x80000000u  /* 512 MiB */
#define ROM_LOAD_ADDR     0x60000000u
#define STAGE2_BASE       0x60080000u  /* run address (like stock FlashBoot) */
#define STAGE2_END        0x600c0000u  /* image + bss + stack must stay below */
#define ATAGS_MAX         0x500u       /* core 20 + cmdline 8+764 + none 8, rounded */
#define ATAGS_WINDOW_END  0x60100000u  /* 3.0 head.S maps only the first 1 MiB of RAM for the tags */
#define LOG_BASE          0x7fff0000u  /* last 64 KiB of the kernel-reserved 1 MiB waveform window */
#define LOG_SIZE          0x1000u
#define LOG_MAGIC         0x474c3253u  /* "S2LG" */

/* ---- status codes (log + LED) ---- */
#define FAIL_TABLE        1u           /* boot table: bad magic/version/CRC/field */
#define FAIL_READ         2u           /* ROM SD read returned an error */
#define FAIL_CRC          3u           /* blob CRC32 mismatch */
#define FAIL_STATE        4u           /* unexpected ROM state (controller id != SDMMC0) */

#endif
