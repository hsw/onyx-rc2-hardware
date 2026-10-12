/* SPDX-License-Identifier: MIT */
/* sdboot stage2 for the ONYX BOOX RC2 (RK3026): load the stock kernel Image and a ramdisk from the microSD card through
 * the BootROM's own SD read routine, check CRC32s, build the ATAG list exactly like stock FlashBoot (loader 2.32), jump.
 *
 * Storage access: ONLY the BootROM read routine 0x168c (CMD17/CMD18 + CMD12 on SDMMC0, no write command exists in the
 * ROM). This file has no MMC/eMMC/NAND register access of its own; tests/check_nowrite.py enforces that on the binary.
 * Design, hand-off facts and LED codes: ../README.md. */
#include "bootinfo.h"

_Static_assert(sizeof(struct boot_table) == BT_SIZE, "boot table must be 1024 bytes");
_Static_assert(__builtin_offsetof(struct boot_table, cmdline) == BT_CMDLINE_OFF, "cmdline offset");
_Static_assert(__builtin_offsetof(struct boot_table, crc32) == BT_CRC_OFF, "crc offset");

#define REG(a)            (*(volatile unsigned *)(a))
#define GRF_BASE          0x20008000u
#define GRF_GPIO2B_IOMUX  (GRF_BASE + 0xcc)
#define GRF_SOC_CON0      (GRF_BASE + 0x140)
#define CRU_SOFTRST_CON0  0x20000110u
#define GPIO2_BASE        0x20084000u
#define LED_BIT           (1u << 15)       /* GPIO2_B7, active high (board/README.md §8.1) */
#define IMEM              0x10080000u
#define ROM_VERSION_WORD  0x10103ff0u      /* "C292" on our RK3026 ROM */
#define ROM_C292          0x32393243u
#define ROM_A292_ADDR     0x101027f0u
#define ROM_A292          0x32393241u
#define ROM_SD_READ       0x0000168cu      /* read(sector, buf, bytes) -> 0 ok, 1 error; ROM alias at 0 (no remap yet) */

#define ATAG_CORE         0x54410001u
#define ATAG_CMDLINE      0x54410009u

extern unsigned rom_call(unsigned fn, unsigned a0, unsigned a1, unsigned a2);
extern void jump_kernel(unsigned entry, unsigned machine, unsigned atags) __attribute__((noreturn));
extern void icache_on(void);
extern unsigned read_cpsr(void), read_sctlr(void), read_mpidr(void);
extern void delay_loops(unsigned n);
extern char _start[], __image_end[], __stack_top[];

/* ~1 ms at 600 MHz (APLL after stock FlashData) with the I-cache on; only the LED rhythm depends on it. */
volatile unsigned loops_per_ms = 300000;

static struct boot_table bt __attribute__((aligned(4)));
static unsigned crc_table[256];
static unsigned quiet;

/* ---------------------------------------------------------------- log in DDR (read later through /dev/mem) */
struct log_hdr {
    unsigned magic, version, len, stage;     /* stage: last progress step reached (1..), 'H' halted, 'J' jumping */
    unsigned fail, fail_arg, fail_val;       /* fail: FAIL_* or 0 */
    unsigned retries;                        /* ROM read calls repeated after an error */
};
#define LOG_TEXT_MAX (LOG_SIZE - sizeof(struct log_hdr) - 1)

static struct log_hdr *const lh = (struct log_hdr *)LOG_BASE;
static char *const ltext = (char *)(LOG_BASE + sizeof(struct log_hdr));

static void lputc(char c)
{
    if (lh->len < LOG_TEXT_MAX) {
        ltext[lh->len++] = c;
        ltext[lh->len] = 0;
    }
}

static void lputs(const char *s) { while (*s) lputc(*s++); }

static void lhex(unsigned v)
{
    lputs("0x");
    for (int i = 28; i >= 0; i -= 4) lputc("0123456789abcdef"[(v >> i) & 15]);
}

static void ldec(unsigned v)
{
    char b[11]; int n = 0;
    do { b[n++] = (char)('0' + v % 10); v /= 10; } while (v);
    while (n) lputc(b[--n]);
}

static void log_init(void)
{
    lh->magic = LOG_MAGIC; lh->version = 1; lh->len = 0; lh->stage = 0;
    lh->fail = 0; lh->fail_arg = 0; lh->fail_val = 0; lh->retries = 0;
    ltext[0] = 0;
}

/* ---------------------------------------------------------------- LED */
static void led(int on)
{
    unsigned v = REG(GPIO2_BASE + 0x00);
    REG(GPIO2_BASE + 0x00) = on ? (v | LED_BIT) : (v & ~LED_BIT);
}

static void led_init(void)
{
    REG(GRF_GPIO2B_IOMUX) = 0xc0000000u;     /* B7 bits [15:14] = GPIO, write-enable mask */
    led(0);
    REG(GPIO2_BASE + 0x04) |= LED_BIT;       /* output */
}

static void delay_ms(unsigned ms) { while (ms--) delay_loops(loops_per_ms); }

static void blink(unsigned on_ms, unsigned off_ms) { led(1); delay_ms(on_ms); led(0); delay_ms(off_ms); }

/* progress: n short blinks, then a pause (LED off) */
static void progress(unsigned n)
{
    lh->stage = n;
    lputs("stage "); ldec(n); lputc('\n');
    if (quiet) return;
    while (n--) blink(150, 250);
    delay_ms(700);
}

/* failure: forever { 1.5 s on; `code` short blinks; if blob: 1 s pause, `blob` short blinks; 2.5 s off } */
static void __attribute__((noreturn)) fail(unsigned code, unsigned blob, unsigned val)
{
    lh->fail = code; lh->fail_arg = blob; lh->fail_val = val;
    lputs("FAIL "); ldec(code); lputs(" blob "); ldec(blob); lputs(" val "); lhex(val); lputc('\n');
    for (;;) {
        led(1); delay_ms(1500); led(0); delay_ms(600);
        for (unsigned i = 0; i < code; i++) blink(200, 300);
        if (blob) {
            delay_ms(1000);
            for (unsigned i = 0; i < blob; i++) blink(200, 300);
        }
        delay_ms(2500);
    }
}

/* ---------------------------------------------------------------- CRC32 (zlib polynomial) */
static void crc_init(void)
{
    for (unsigned i = 0; i < 256; i++) {
        unsigned c = i;
        for (int k = 0; k < 8; k++) c = (c & 1) ? 0xedb88320u ^ (c >> 1) : c >> 1;
        crc_table[i] = c;
    }
}

static unsigned crc32(const void *p, unsigned n)
{
    const unsigned char *b = p;
    unsigned c = 0xffffffffu;
    while (n--) c = crc_table[(c ^ *b++) & 0xff] ^ (c >> 8);
    return c ^ 0xffffffffu;
}

/* ---------------------------------------------------------------- SD read through the BootROM */
#define READ_TRIES 3                         /* a read is side-effect free; retry a failed chunk twice */
static int sd_read(unsigned lba, unsigned nsec, unsigned dst, unsigned chunk)
{
    while (nsec) {
        unsigned n = nsec < chunk ? nsec : chunk, k;
        for (k = 0; k < READ_TRIES; k++) {
            if (rom_call(ROM_SD_READ, lba, dst, n * 512u) == 0) break;
            lh->retries++;
            lputs("read error lba "); ldec(lba); lputs(" n "); ldec(n); lputc('\n');
        }
        if (k == READ_TRIES) return -1;
        lba += n; dst += n * 512u; nsec -= n;
    }
    return 0;
}

/* ---------------------------------------------------------------- boot table checks */
static int overlaps(unsigned a, unsigned alen, unsigned b, unsigned blen)
{
    return a < b + blen && b < a + alen;
}

static unsigned round_sec(unsigned n) { return (n + 511u) & ~511u; }

static unsigned check_table(void)          /* 0 = OK, else the failing check number (logged) */
{
    if (bt.magic != BT_MAGIC) return 1;
    if (bt.version != BT_VERSION || bt.size != BT_SIZE) return 2;
    if (crc32(&bt, BT_CRC_OFF) != bt.crc32) return 3;
    if (bt.machine == 0) return 4;
    if (bt.atags < DDR_BASE || bt.atags + ATAGS_MAX > ATAGS_WINDOW_END || (bt.atags & 3)) return 5;
    if (overlaps(bt.atags, ATAGS_MAX, STAGE2_BASE, STAGE2_END - STAGE2_BASE)) return 6;
    if (bt.chunk_sectors < 1 || bt.chunk_sectors > 128) return 7;
    if (bt.nblobs < 1 || bt.nblobs > BT_MAX_BLOBS) return 8;
    if (bt.cmdline_len >= BT_CMDLINE_MAX || bt.cmdline[bt.cmdline_len] != 0) return 9;
    for (unsigned i = 0; i < bt.cmdline_len; i++)
        if (bt.cmdline[i] < 0x20 || bt.cmdline[i] > 0x7e) return 10;
    if (bt.blob[0].kind != BLOB_KERNEL || bt.entry != bt.blob[0].load) return 11;
    for (unsigned i = 0; i < bt.nblobs; i++) {
        const struct bt_blob *b = &bt.blob[i];
        unsigned len = round_sec(b->size), nsec = len / 512u;
        if (b->kind < BLOB_KERNEL || b->kind > BLOB_DATA) return 20 + i;
        if (b->size == 0 || b->size > 0x08000000u) return 24 + i;
        if (b->lba < BT_MIN_BLOB_LBA || b->lba + nsec > BT_MAX_LBA) return 28 + i;
        if ((b->load & 3) || b->load < DDR_BASE || b->load > DDR_END - len) return 32 + i;
        if (overlaps(b->load, len, STAGE2_BASE, STAGE2_END - STAGE2_BASE)) return 36 + i;
        if (overlaps(b->load, len, LOG_BASE, LOG_SIZE)) return 40 + i;
        if (overlaps(b->load, len, bt.atags, ATAGS_MAX)) return 44 + i;
        for (unsigned j = 0; j < i; j++)
            if (overlaps(b->load, len, bt.blob[j].load, round_sec(bt.blob[j].size))) return 48 + i;
    }
    return 0;
}

/* ---------------------------------------------------------------- ATAGs: exactly stock FlashBoot 0x600176b4 */
static void build_atags(void)
{
    unsigned *t = (unsigned *)bt.atags;
    t[0] = 5; t[1] = ATAG_CORE; t[2] = 0; t[3] = 0; t[4] = 0;   /* flags 0, pagesize 0, rootdev 0 */
    t += 5;
    if (bt.cmdline_len) {
        t[0] = (bt.cmdline_len + 13u) >> 2;                         /* = 2 + words(string + NUL) */
        t[1] = ATAG_CMDLINE;
        char *d = (char *)&t[2];
        for (unsigned i = 0; i <= bt.cmdline_len; i++) d[i] = bt.cmdline[i];
        t += t[0];
    }
    t[0] = 0; t[1] = 0;                                             /* ATAG_NONE */
}

/* ---------------------------------------------------------------- main */
void stage2_main(unsigned load_addr)
{
    log_init();
    led_init();
    lputs("RC2 sdboot stage2 v1\nload "); lhex(load_addr);
    lputs(" run "); lhex((unsigned)_start); lputs(" size "); lhex((unsigned)(__image_end - _start));
    lputs("\ncpsr "); lhex(read_cpsr()); lputs(" sctlr "); lhex(read_sctlr()); lputs(" mpidr "); lhex(read_mpidr());
    lputs("\nrom "); lhex(REG(ROM_VERSION_WORD));
    lputs(" imem0 "); lhex(REG(IMEM + 0x00)); lputs(" sdclass "); lhex(REG(IMEM + 0x40));
    lputs(" ctl "); lhex(*(volatile unsigned char *)(IMEM + 0x44));
    lputs(" rca "); lhex(*(volatile unsigned short *)(IMEM + 0x46)); lputc('\n');

    unsigned rom = REG(ROM_VERSION_WORD), rom_a = REG(ROM_A292_ADDR);
    if (rom == ROM_C292)                    /* stock FlashBoot 0x600002e8: CPU1 held in soft reset; the kernel's */
        REG(CRU_SOFTRST_CON0) = 0x00100010u; /* boot_secondary pulses it again when it powers CPU1 up */

    icache_on();
    crc_init();
    progress(1);                             /* stage2 entered */

    if (*(volatile unsigned char *)(IMEM + 0x44) != 0)  /* the ROM read would go to the eMMC controller */
        fail(FAIL_STATE, 0, *(volatile unsigned char *)(IMEM + 0x44));

    if (sd_read(BT_LBA, BT_SECTORS, (unsigned)&bt, BT_SECTORS) != 0) fail(FAIL_READ, 0, BT_LBA);
    unsigned bad = check_table();
    if (bad) { lputs("table check "); ldec(bad); lputc('\n'); fail(FAIL_TABLE, 0, bad); }
    quiet = bt.flags & BT_FLAG_QUIET;
    lputs("table ok flags "); lhex(bt.flags); lputs(" blobs "); ldec(bt.nblobs);
    lputs(" chunk "); ldec(bt.chunk_sectors); lputc('\n');
    progress(2);                             /* boot table OK */

    for (unsigned i = 0; i < bt.nblobs; i++) {
        const struct bt_blob *b = &bt.blob[i];
        lputs("blob "); ldec(i); lputs(" kind "); ldec(b->kind); lputs(" lba "); ldec(b->lba);
        lputs(" size "); ldec(b->size); lputs(" -> "); lhex(b->load); lputc('\n');
        if (sd_read(b->lba, round_sec(b->size) / 512u, b->load, bt.chunk_sectors) != 0)
            fail(FAIL_READ, i + 1, b->lba);
        unsigned c = crc32((const void *)b->load, b->size);
        if (c != b->crc32) fail(FAIL_CRC, i + 1, c);
        progress(3 + i);                     /* 3 = kernel, 4 = ramdisk, 5 = third blob ... */
    }

    build_atags();
    lputs("atags "); lhex(bt.atags); lputs(" machine "); ldec(bt.machine); lputs(" entry "); lhex(bt.entry);
    lputs("\ncmdline "); lputs(bt.cmdline); lputc('\n');

    if (bt.flags & BT_FLAG_HALT) {           /* dry run: all loaded and verified, do not jump */
        lputs("HALT flag: not jumping\n");
        lh->stage = 0x48;                    /* 'H' */
        for (;;) { blink(2500, 300); }      /* "ready, halted": mostly on, short dark gaps */
    }

    lputs("jump\n");
    lh->stage = 0x4a;                        /* 'J' */
    for (int k = 0; k < 3; k++) blink(60, 60);   /* "jumping": 3 fast flickers, then LED off until the kernel's */
    led(0);                                       /* machine init switches it on again */
    if (rom == ROM_C292 || rom_a == ROM_A292)     /* stock FlashBoot 0x60000248: GRF_SOC_CON0 bit 12, the remap that */
        REG(GRF_SOC_CON0) = 0x10001000u;          /* lets CPU1 start from IMEM at 0; after this, 0 is IMEM, not ROM */
    jump_kernel(bt.entry, bt.machine, bt.atags);
}
