// SPDX-License-Identifier: GPL-2.0
/*
 * SPX: read-only WCD9340 AUDD-SPI4 oracle.
 *
 * Windows reaches the codec register file over SPI4 at 24 MHz with RELIABLE
 * reads (docs/windows-re/07); every flaky-read wall we hit lives on the
 * SLIMbus interface element Linux uses instead. This module borrows the
 * read half of drivers/mfd/wcd934x-wdsp.c — CLKREQ clock wake, RDSR status,
 * IRR internal-register reads, MIOR flat-24-bit memory reads — and nothing
 * else: it never boots the WDSP, never writes a codec register, and never
 * issues MIOW/IRW/WREN.
 *
 * Validation loop: spx_wcd_gpio writes GPIO dir/val regs 0x42/0x43 through
 * the SLIMbus regmap; this module reads them back over SPI4. Agreement on
 * a value we control proves the transport, where the SLIMbus bridge cannot
 * (its reads return fabricated data — see spx-bridge-returns-fake-register-
 * data).
 *
 * insmod spx_spi4_oracle.ko mior=0x0021,0x0022,0x0023,0x0042,0x0043
 * Always "fails" load with -EAGAIN so it can be re-run without rmmod.
 */
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/module.h>
#include <linux/spi/spi.h>

#define WCD_SPI_CMD_NOP		0x00
#define WCD_SPI_CMD_RDSR	0x05
#define WCD_SPI_CMD_CLKREQ	0xda
#define WCD_SPI_CMD_IRR		0x81
#define WCD_SPI_CMD_MIOR	0x83

#define WCD_SPI_READ_SINGLE_LEN	0x13
#define WCD_SPI_ADDR_MASK	GENMASK(23, 0)

/* CHIP_TIER_CTRL chip-id bytes: stable silicon identity. */
static char *mior = "0x0021,0x0022,0x0023,0x0042,0x0043,0x00c85,0x00c96";
module_param(mior, charp, 0400);
MODULE_PARM_DESC(mior, "comma list of flat addresses to MIOR-read (hex)");

/* SPI slave's own internal registers (SLAVE_CONFIG 0x0c, TRNS_LEN 0x50). */
static char *irr = "0x0c,0x50";
module_param(irr, charp, 0400);
MODULE_PARM_DESC(irr, "comma list of internal regs to IRR-read (hex)");

static char *dev = "spi1.0";
module_param(dev, charp, 0400);
MODULE_PARM_DESC(dev, "SPI device name (default spi1.0 = 88c000.cs0)");

static bool force;
module_param(force, bool, 0400);
MODULE_PARM_DESC(force, "read even when the CLKREQ/RDSR wake fails");

static int retries = 1;
module_param(retries, int, 0400);
MODULE_PARM_DESC(retries, "CLKREQ wake attempts before giving up");

static int spx_oracle_spi_sync(struct spi_device *spi, const void *tx,
			       size_t tx_len, void *rx, size_t rx_len)
{
	struct spi_transfer xfers[2] = {
		{ .tx_buf = tx, .len = tx_len, },
		{ .rx_buf = rx, .len = rx_len, },
	};

	return spi_sync_transfer(spi, xfers, rx_len ? 2 : 1);
}

static int spx_oracle_clock_enable(struct spi_device *spi, bool *on)
{
	u8 nop = WCD_SPI_CMD_NOP;
	u8 clkreq[4] = { WCD_SPI_CMD_CLKREQ, 0xba, 0x80, 0x00 };
	u8 rdsr = WCD_SPI_CMD_RDSR;
	__be32 raw = 0;
	u32 status;
	int attempt, ret;

	for (attempt = 0; attempt < retries; attempt++) {
		ret = spi_write(spi, &nop, sizeof(nop));
		if (ret)
			return ret;
		ret = spi_write(spi, clkreq, sizeof(clkreq));
		if (ret)
			return ret;
		usleep_range(500, 550);
		ret = spi_write(spi, &nop, sizeof(nop));
		if (ret)
			return ret;
		ret = spx_oracle_spi_sync(spi, &rdsr, sizeof(rdsr), &raw,
					  sizeof(raw));
		if (ret)
			return ret;
		status = be32_to_cpu(raw);
		dev_info(&spi->dev,
			 "SPX SPI4 RDSR try %d/%d status = 0x%08x%s\n",
			 attempt + 1, retries, status,
			 status ? " (clock awake)" : "");
		if (status) {
			*on = true;
			return 0;
		}
	}
	dev_info(&spi->dev, "SPX SPI4 wake FAILED after %d tries\n", retries);
	return -EIO;
}

static int spx_oracle_irr(struct spi_device *spi, u8 reg, u32 *val)
{
	u8 cmd[4] = { WCD_SPI_CMD_IRR, reg, 0, 0 };
	__be32 raw;
	int ret;

	ret = spx_oracle_spi_sync(spi, cmd, sizeof(cmd), &raw, sizeof(raw));
	if (!ret)
		*val = be32_to_cpu(raw);
	return ret;
}

static int spx_oracle_mior(struct spi_device *spi, u32 addr, u32 *val)
{
	u8 cmd[WCD_SPI_READ_SINGLE_LEN] = {};
	__be32 frame = cpu_to_be32((WCD_SPI_CMD_MIOR << 24) |
				   (addr & WCD_SPI_ADDR_MASK));
	__be32 raw;
	int ret;

	memcpy(cmd, &frame, sizeof(frame));
	ret = spx_oracle_spi_sync(spi, cmd, sizeof(cmd), &raw, sizeof(raw));
	if (!ret)
		*val = be32_to_cpu(raw);
	return ret;
}

static int spx_oracle_list(struct spi_device *spi, char *list, bool internal)
{
	char *s, *cursor, *tok;
	int ret = 0;

	s = kstrdup(list, GFP_KERNEL);
	if (!s)
		return -ENOMEM;
	cursor = s;
	while ((tok = strsep(&cursor, ",")) != NULL) {
		unsigned long v;

		if (!*tok)
			continue;
		if (kstrtoul(tok, 0, &v))
			continue;
		if (internal) {
			u32 val = 0;

			ret = spx_oracle_irr(spi, (u8)v, &val);
			dev_info(&spi->dev,
				 "SPX SPI4 IRR  0x%02lx -> 0x%08x (rc=%d)\n",
				 v, val, ret);
		} else {
			u32 val = 0;

			ret = spx_oracle_mior(spi, (u32)v, &val);
			dev_info(&spi->dev,
				 "SPX SPI4 MIOR 0x%06lx -> 0x%08x (rc=%d)\n",
				 v, val, ret);
		}
		if (ret)
			break;
	}
	kfree(s);
	return ret;
}

static int __init spx_spi4_oracle_init(void)
{
	struct device *d;
	struct spi_device *spi;
	bool clock_on = false;
	int ret;

	d = bus_find_device_by_name(&spi_bus_type, NULL, dev);
	if (!d) {
		pr_warn("spx_spi4_oracle: device %s not found\n", dev);
		return -ENODEV;
	}
	spi = to_spi_device(d);

	/* Read-only session: clock wake, then IRR/MIOR reads. No MIOW/IRW. */
	ret = spx_oracle_clock_enable(spi, &clock_on);
	if (ret && !force)
		goto out;
	if (ret)
		ret = 0;

	ret = spx_oracle_list(spi, irr, true);
	if (ret)
		goto out;
	ret = spx_oracle_list(spi, mior, false);

out:
	put_device(d);
	pr_warn("spx_spi4_oracle: done rc=%d (clock %s)\n", ret,
		clock_on ? "left ON (read-only session, no IPC_CTL write)" :
			   "never woken");
	/* Always fail the load so the module can be re-run without rmmod. */
	return ret ? ret : -EAGAIN;
}

static void __exit spx_spi4_oracle_exit(void)
{
}

module_init(spx_spi4_oracle_init);
module_exit(spx_spi4_oracle_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX read-only WCD9340 AUDD-SPI4 register oracle");
