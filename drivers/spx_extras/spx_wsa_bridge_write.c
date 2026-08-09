// SPDX-License-Identifier: GPL-2.0
/*
 * SPX: write WSA881x slave registers by driving the SWR master's command FIFO
 * over the *paged* WCD9340 bridge, bypassing soundwire_qcom entirely.
 *
 * Why this exists: qcom_swrm_ahb_reg_write() goes over the same AHB bridge path
 * that stops completing partway through a session, and qcom_swrm_cmd_fifo_wr_cmd()
 * discards its return value outright --
 *
 *     "Its assumed that write is okay as we do not get any status back"
 *
 * -- so every sdw_write_no_pm() reports rc=0 whether or not the command ever
 * reached the master. A perfect-looking write trace can therefore be entirely
 * fictional. The paged bridge (500us settle, level-high status bit 0, throwaway
 * first read) keeps working when the qcom path does not, so this module reaches
 * the FIFO through it and reports what the master actually accepted.
 *
 *   insmod spx_wsa_bridge_write.ko dev=1 seq=0x311a:0xfc:600,0x311a:0x7c:400
 *
 * Fails with -EAGAIN by design so it can be re-run without rmmod.
 */
#include <linux/delay.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>

#define BR_WR_DATA		0x0c85
#define BR_RD_ADDR		0x0c8d
#define BR_RD_DATA		0x0c91
#define BR_STATUS		0x0c96

#define SWRM_CMD_FIFO_WR_CMD	0x0300
#define SWRM_CMD_FIFO_CMD	0x0308
#define SWRM_CMD_FIFO_STATUS	0x030c
#define SWRM_CMD_FIFO_FLUSH	0x1

/* (reg) | (id << 16) | (dev << 20) | (data << 24) */
#define SWRM_REG_VAL_PACK(data, dev, id, reg)	\
	((reg) | ((id) << 16) | ((dev) << 20) | ((data) << 24))

static char *seq = "";
module_param(seq, charp, 0400);
MODULE_PARM_DESC(seq, "comma list of reg:val:delay_ms entries (hex ok)");

static int dev_num = 1;
module_param_named(dev, dev_num, int, 0400);
MODULE_PARM_DESC(dev, "SoundWire device number to address (15 = broadcast)");

static struct regmap *map;

static int br_read(u32 reg, u32 *val)
{
	u32 addr = reg, first = 0, v = 0;
	int i, ret;

	ret = regmap_bulk_write(map, BR_RD_ADDR, (u8 *)&addr, 4);
	if (ret)
		return ret;
	usleep_range(500, 550);
	for (i = 0; i < 200; i++) {
		u32 st;

		if (!regmap_read(map, BR_STATUS, &st) && (st & 1))
			break;
		udelay(5);
	}
	ret = regmap_bulk_read(map, BR_RD_DATA, &first, 4);
	if (ret)
		return ret;
	usleep_range(500, 550);
	ret = regmap_bulk_read(map, BR_RD_DATA, &v, 4);
	if (ret)
		return ret;
	*val = v;
	return 0;
}

static int br_write(u32 reg, u32 val)
{
	u32 request[2] = { val, reg };
	int ret;

	ret = regmap_bulk_write(map, BR_WR_DATA, (u8 *)request,
				sizeof(request));
	usleep_range(500, 550);
	return ret;
}

static int __init spx_bridge_write_init(void)
{
	struct wcd934x_ddata *dd;
	struct device *dev;
	char *s, *cursor, *entry, *tok;
	u32 status = 0;
	int n = 0;

	if (dev_num < 0 || dev_num > 15)
		return -EINVAL;

	dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
	if (!dev)
		return -ENODEV;
	dd = dev_get_drvdata(dev);
	put_device(dev);
	if (!dd || !dd->regmap)
		return -ENODEV;
	map = dd->regmap;

	s = kstrdup(seq, GFP_KERNEL);
	if (!s)
		return -ENOMEM;

	cursor = s;
	while ((entry = strsep(&cursor, ",")) != NULL) {
		unsigned int reg, val, ms = 0;
		u32 packed;
		int rc;

		if (!*entry)
			continue;
		tok = strsep(&entry, ":");
		if (!tok || kstrtouint(tok, 0, &reg))
			continue;
		tok = strsep(&entry, ":");
		if (!tok || kstrtouint(tok, 0, &val))
			continue;
		tok = strsep(&entry, ":");
		if (tok && kstrtouint(tok, 0, &ms))
			ms = 0;

		if (reg > 0xffff || val > 0xff) {
			pr_warn("spx_brwr: skip bad entry 0x%x:0x%x\n",
				reg, val);
			continue;
		}

		/* Flush first: the SPX write-FIFO count reads stale. */
		br_write(SWRM_CMD_FIFO_CMD, SWRM_CMD_FIFO_FLUSH);
		usleep_range(500, 550);

		/*
		 * Device address 15 is the SoundWire broadcast address and
		 * needs the broadcast command id to match, otherwise the
		 * master tags it as an ordinary addressed command.
		 */
		packed = SWRM_REG_VAL_PACK(val, dev_num,
					   dev_num == 15 ? 0xF : 0, reg);
		rc = br_write(SWRM_CMD_FIFO_WR_CMD, packed);
		usleep_range(1200, 1300);

		br_read(SWRM_CMD_FIFO_STATUS, &status);
		pr_info("spx_brwr %3d: dev=%d 0x%04x <- 0x%02x packed=0x%08x rc=%d fifo_status=0x%08x\n",
			++n, dev_num, reg, val, packed, rc, status);

		if (ms)
			fsleep(ms * 1000);
	}
	kfree(s);

	return -EAGAIN;
}

static void __exit spx_bridge_write_exit(void)
{
}

module_init(spx_bridge_write_init);
module_exit(spx_bridge_write_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX: write WSA registers via the paged bridge command FIFO");
