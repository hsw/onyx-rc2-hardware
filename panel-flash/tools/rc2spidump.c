// SPDX-License-Identifier: GPL-2.0
/*
 * rc2spidump: read-only dump of the RC2 panel SPI flash through the stock kernel's own spi_device.
 * Issues only JEDEC ID (0x9F) and READ (0x03), 16 bytes per transfer like the stock SPIFlashRead.
 * The data stays in a page block until rmmod; userspace reads it through /dev/mem at the printed physical address.
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/gfp.h>
#include <linux/mm.h>
#include <linux/string.h>
#include <linux/spi/spi.h>
#include <asm/memory.h>

extern void spi_ctl_pins_enable(int enable);

static unsigned long devp = 0xc0d2aba8;  /* &spi_flash_info.spi (stock Image, spi_flash_info @0xc0d2aba0 + 8) */
static unsigned long start;
static unsigned long len = 0x100000;
module_param(devp, ulong, 0444);
module_param(start, ulong, 0444);
module_param(len, ulong, 0444);

static unsigned long buf;
static unsigned int order;

static int __init rc2spidump_init(void)
{
	struct spi_device *spi = *(struct spi_device **)devp;
	const char *name;
	u8 cmd[4], id[3];
	unsigned long off;
	int ret = 0;

	if (!spi || (unsigned long)spi < PAGE_OFFSET)
		return -ENODEV;
	name = dev_name(&spi->dev);
	if (!name || strcmp(name, "spi0.0") || !spi->modalias || strcmp(spi->modalias, "epd_spi_flash")) {
		printk(KERN_ERR "rc2spidump: unexpected device %s/%s\n", name ? name : "?", spi->modalias ? spi->modalias : "?");
		return -ENODEV;
	}
	order = get_order(len);
	buf = __get_free_pages(GFP_KERNEL | __GFP_ZERO, order);
	if (!buf)
		return -ENOMEM;

	spi_ctl_pins_enable(1);
	cmd[0] = 0x9f;
	ret = spi_write_then_read(spi, cmd, 1, id, 3);
	printk(KERN_INFO "rc2spidump: jedec ret=%d id=%02x %02x %02x max_speed=%u mode=%u\n",
	       ret, id[0], id[1], id[2], spi->max_speed_hz, spi->mode);
	for (off = 0; off < len && !ret; off += 16) {
		unsigned long a = start + off;
		cmd[0] = 0x03;
		cmd[1] = a >> 16;
		cmd[2] = a >> 8;
		cmd[3] = a;
		ret = spi_write_then_read(spi, cmd, 4, (u8 *)buf + off, min(16UL, len - off));
	}
	spi_ctl_pins_enable(0);

	printk(KERN_INFO "rc2spidump: start=0x%lx len=0x%lx ret=%d virt=0x%lx phys=0x%lx\n",
	       start, len, ret, buf, (unsigned long)virt_to_phys((void *)buf));
	return 0;
}

static void __exit rc2spidump_exit(void)
{
	if (buf)
		free_pages(buf, order);
}

module_init(rc2spidump_init);
module_exit(rc2spidump_exit);
MODULE_LICENSE("GPL");
