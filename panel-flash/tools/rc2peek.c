// SPDX-License-Identifier: MIT
/* rc2peek: read-only helpers for the RC2 panel-flash experiment.
 *   rc2peek dump <phys_hex> <len_hex>           pread /dev/mem -> stdout
 *   rc2peek find <phys_hex> <len_hex> <string>  print phys offsets of string
 *   rc2peek trigger                             one read() on /dev/spi_flash (stock driver reads the panel waveform into a leaked kmalloc buffer)
 *   rc2peek mmap <phys_hex> <len_hex>           mmap /dev/mem, 32-bit reads -> stdout (I/O and ROM below RAM, where pread is refused)
 *       [DANGER] only inside a region known to be decoded: BootROM 0x10100000 len 0x4000 is fine; a 64 KB read from
 *       0x10100000 (past the 16 KB ROM) hung the RC2 on 2026-10-10 (adb shell dead, Reset pinhole needed)
 */
#define _FILE_OFFSET_BITS 64
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
static unsigned char buf[1 << 20];
int main(int c, char **v) {
    if (c >= 2 && !strcmp(v[1], "trigger")) {
        int fd = open("/dev/spi_flash", O_RDONLY);
        if (fd < 0) { perror("open"); return 1; }
        long r = read(fd, buf, 64);
        printf("read returned %ld (0x%lx)\n", r, (unsigned long)r);
        close(fd);
        return 0;
    }
    if (c < 4) { fprintf(stderr, "usage\n"); return 2; }
    if (!strcmp(v[1], "mmap")) {
        unsigned long pa = strtoul(v[2], 0, 16), len = strtoul(v[3], 0, 16), pg = pa & ~0xfffUL;
        if ((pa | len) & 3 || len > sizeof buf) { fprintf(stderr, "align 4, len <= 1M\n"); return 2; }
        int fd = open("/dev/mem", O_RDONLY | O_SYNC);
        if (fd < 0) { perror("open"); return 1; }
        size_t ml = (pa - pg + len + 0xfff) & ~0xfffUL;
        void *m = mmap(0, ml, PROT_READ, MAP_SHARED, fd, pg);
        if (m == MAP_FAILED) { perror("mmap"); return 1; }
        volatile const unsigned *w = (volatile const unsigned *)((char *)m + (pa - pg));
        for (unsigned long i = 0; i < len / 4; i++) ((unsigned *)buf)[i] = w[i];
        return write(1, buf, len) == (ssize_t)len ? 0 : 1;
    }
    unsigned long long pa = strtoull(v[2], 0, 16), len = strtoull(v[3], 0, 16);
    int fd = open("/dev/mem", O_RDONLY);
    if (fd < 0) { perror("open"); return 1; }
    const char *pat = c > 4 ? v[4] : 0;
    size_t pl = pat ? strlen(pat) : 0;
    for (unsigned long long o = 0; o < len; o += sizeof buf) {
        size_t n = len - o < sizeof buf ? len - o : sizeof buf;
        ssize_t r = pread(fd, buf, n, pa + o);
        if (r != (ssize_t)n) { fprintf(stderr, "pread 0x%llx: %zd\n", pa + o, r); perror("pread"); return 1; }
        if (!strcmp(v[1], "dump")) { if (write(1, buf, n) != (ssize_t)n) return 1; }
        else for (size_t i = 0; i + pl <= n; i++)  /* misses a match split across chunks; fine for this search */
            if (buf[i] == (unsigned char)pat[0] && !memcmp(buf + i, pat, pl)) printf("0x%llx\n", pa + o + i);
    }
    return 0;
}
