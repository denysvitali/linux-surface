// SPDX-License-Identifier: GPL-2.0
/* One-shot SPX SoundWire transport health snapshot. Run only while PCM is idle. */
#include <linux/bitops.h>
#include <linux/delay.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>

#define SPX_CODEC_DEVICE	"217:250:1:0"

#define SPX_BRIDGE_WR_DATA	0xc85
#define SPX_BRIDGE_WR_ADDR	0xc89
#define SPX_BRIDGE_RD_ADDR	0xc8d
#define SPX_BRIDGE_RD_DATA	0xc91

#define SWRM_INT_STATUS		0x0200
#define SWRM_INT_CLEAR		0x0208

#define SWRM_INT_MASTER_CLASH	BIT(3)
#define SWRM_INT_RD_OVERFLOW	BIT(4)
#define SWRM_INT_RD_UNDERFLOW	BIT(5)
#define SWRM_INT_WR_OVERFLOW	BIT(6)
#define SWRM_INT_CMD_ERROR	BIT(7)
#define SWRM_INT_DOUT_COLLISION	BIT(8)
#define SWRM_INT_RD_MISMATCH	BIT(9)
#define SWRM_INT_ENUM_FAILED	BIT(11)
#define SWRM_INT_ENUM_FULL	BIT(12)
#define SWRM_INT_CMD_IGNORED	BIT(19)

#define SWRM_FAULT_MASK		(SWRM_INT_MASTER_CLASH | \
				 SWRM_INT_RD_OVERFLOW | \
				 SWRM_INT_RD_UNDERFLOW | \
				 SWRM_INT_WR_OVERFLOW | \
				 SWRM_INT_CMD_ERROR | \
				 SWRM_INT_DOUT_COLLISION | \
				 SWRM_INT_RD_MISMATCH | \
				 SWRM_INT_ENUM_FAILED | \
				 SWRM_INT_ENUM_FULL | \
				 SWRM_INT_CMD_IGNORED)

static bool clear;
module_param(clear, bool, 0400);
MODULE_PARM_DESC(clear, "Clear latched SoundWire interrupt status after reading");

static int spx_bridge_read(struct regmap *map, u32 addr, u32 *val)
{
	int ret;

	ret = regmap_bulk_write(map, SPX_BRIDGE_RD_ADDR, &addr, sizeof(addr));
	if (ret)
		return ret;

	usleep_range(500, 550);
	ret = regmap_bulk_read(map, SPX_BRIDGE_RD_DATA, val, sizeof(*val));
	if (ret)
		return ret;

	/* The first bridge result can be stale on SPX. */
	usleep_range(500, 550);
	return regmap_bulk_read(map, SPX_BRIDGE_RD_DATA, val, sizeof(*val));
}

static int spx_bridge_write(struct regmap *map, u32 addr, u32 val)
{
	int ret;

	ret = regmap_bulk_write(map, SPX_BRIDGE_WR_DATA, &val, sizeof(val));
	if (ret)
		return ret;

	ret = regmap_bulk_write(map, SPX_BRIDGE_WR_ADDR, &addr, sizeof(addr));
	if (!ret)
		usleep_range(500, 550);

	return ret;
}

static int __init spx_swrm_health_init(void)
{
	struct wcd934x_ddata *ddata;
	struct device *dev;
	u32 status;
	int ret;

	dev = bus_find_device_by_name(&slimbus_bus, NULL, SPX_CODEC_DEVICE);
	if (!dev)
		return -ENODEV;

	ddata = dev_get_drvdata(dev);
	if (!ddata || !ddata->regmap) {
		ret = -ENODEV;
		goto out_put;
	}

	ret = spx_bridge_read(ddata->regmap, SWRM_INT_STATUS, &status);
	if (ret)
		goto out_put;

	pr_info("spx_swrm_health: status=0x%08x faults=0x%08x%s\n",
		status, (u32)(status & SWRM_FAULT_MASK),
		(status & SWRM_FAULT_MASK) ? " FAIL" : " PASS");

	if (clear) {
		ret = spx_bridge_write(ddata->regmap, SWRM_INT_CLEAR, status);
		if (!ret)
			pr_info("spx_swrm_health: cleared status 0x%08x\n", status);
	}

out_put:
	put_device(dev);
	return ret;
}

static void __exit spx_swrm_health_exit(void)
{
}

module_init(spx_swrm_health_init);
module_exit(spx_swrm_health_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX one-shot SoundWire transport health snapshot");
