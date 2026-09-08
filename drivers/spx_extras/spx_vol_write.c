// SPDX-License-Identifier: GPL-2.0
/* Write WCD9340 RX volume registers directly via regmap. */
#include <linux/device.h>
#include <linux/mfd/wcd934x/registers.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>

#define SPX_CODEC_DEVICE "217:250:1:0"

static uint vol_reg = 0x0bd1;
module_param(vol_reg, uint, 0400);
MODULE_PARM_DESC(vol_reg, "Register address to write");

static uint vol_val = 84;
module_param(vol_val, uint, 0400);
MODULE_PARM_DESC(vol_val, "Value to write (0-124)");

static int __init spx_vol_write_init(void)
{
	struct wcd934x_ddata *ddata;
	struct device *dev;
	unsigned int before, after, readback;
	int ret;

	dev = bus_find_device_by_name(&slimbus_bus, NULL, SPX_CODEC_DEVICE);
	if (!dev)
		return -ENODEV;

	ddata = dev_get_drvdata(dev);
	if (!ddata || !ddata->regmap) {
		ret = -ENODEV;
		goto out_put;
	}

	ret = regmap_read(ddata->regmap, vol_reg, &before);
	if (ret) {
		dev_err(dev, "SPX: read before failed: %d\n", ret);
		goto out_put;
	}

	ret = regmap_write(ddata->regmap, vol_reg, vol_val);
	if (ret) {
		dev_err(dev, "SPX: write failed: %d\n", ret);
		goto out_put;
	}

	ret = regmap_read(ddata->regmap, vol_reg, &after);
	if (ret) {
		dev_err(dev, "SPX: read after failed: %d\n", ret);
		goto out_put;
	}

	/* Retain paged-selector bookkeeping while obtaining a fresh value. */
	ret = regcache_drop_region(ddata->regmap, vol_reg, vol_reg);
	if (ret)
		goto out_put;
	ret = regmap_read(ddata->regmap, vol_reg, &readback);
	if (ret) {
		dev_err(dev, "SPX: raw read failed: %d\n", ret);
		goto out_put;
	}

	dev_info(dev, "SPX: reg 0x%04x: before=0x%02x wrote=0x%02x cached=0x%02x raw=0x%02x\n",
		 vol_reg, before, vol_val, after, readback);

out_put:
	put_device(dev);
	return ret;
}

static void __exit spx_vol_write_exit(void)
{
}

module_init(spx_vol_write_init);
module_exit(spx_vol_write_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX WCD9340 volume register writer");
