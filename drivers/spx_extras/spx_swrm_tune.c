// SPDX-License-Identifier: GPL-2.0
/* One-shot SPX SoundWire master data-port register writer. */
#include <linux/delay.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>

#define SPX_BRIDGE_WR_DATA	0xc85
#define SPX_BRIDGE_WR_ADDR	0xc89
#define SPX_SWRM_DP_FIRST	0x0000
#define SPX_SWRM_DP_LAST		0x173c

static uint swrm_reg;
module_param(swrm_reg, uint, 0400);
MODULE_PARM_DESC(swrm_reg, "SoundWire master data-port register address");

static uint swrm_val;
module_param(swrm_val, uint, 0400);
MODULE_PARM_DESC(swrm_val, "32-bit value to write");

static int __init spx_swrm_tune_init(void)
{
	struct wcd934x_ddata *ddata;
	struct device *dev;
	u32 addr = swrm_reg;
	int ret;

	if (swrm_reg < SPX_SWRM_DP_FIRST || swrm_reg > SPX_SWRM_DP_LAST)
		return -EINVAL;

	dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
	if (!dev)
		return -ENODEV;

	ddata = dev_get_drvdata(dev);
	if (!ddata || !ddata->regmap) {
		ret = -ENODEV;
		goto out_put;
	}

	ret = regmap_bulk_write(ddata->regmap, SPX_BRIDGE_WR_DATA,
				&swrm_val, sizeof(swrm_val));
	if (ret)
		goto out_put;

	ret = regmap_bulk_write(ddata->regmap, SPX_BRIDGE_WR_ADDR,
				&addr, sizeof(addr));
	if (!ret) {
		usleep_range(500, 550);
		dev_info(dev, "SPX: SWRM register 0x%04x <- 0x%08x\n",
			 swrm_reg, swrm_val);
	}

out_put:
	put_device(dev);
	return ret;
}

static void __exit spx_swrm_tune_exit(void)
{
}

module_init(spx_swrm_tune_init);
module_exit(spx_swrm_tune_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX one-shot SoundWire master data-port tuner");
