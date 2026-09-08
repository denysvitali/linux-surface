// SPDX-License-Identifier: GPL-2.0
/* One-shot SPX fix for the WCD934x internal SoundWire NPL delay. */
#include <linux/device.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>

#define SPX_CODEC_DEVICE "217:250:1:0"
#define WCD934X_TEST_DEBUG_NPL_DLY_TEST_1 0x803e
#define WCD934X_SWR_NPL_DELAY BIT(4)

static bool enable_delay;
module_param(enable_delay, bool, 0400);
MODULE_PARM_DESC(enable_delay, "Set rather than clear the SWR NPL delay bit");

static struct device *spx_dev;
static struct regmap *spx_regmap;
static unsigned int spx_saved;
static bool spx_changed;

static int __init spx_wcd_npl_init(void)
{
	struct wcd934x_ddata *ddata;
	unsigned int before, after;
	int ret;

	spx_dev = bus_find_device_by_name(&slimbus_bus, NULL,
					  SPX_CODEC_DEVICE);
	if (!spx_dev)
		return -ENODEV;

	ddata = dev_get_drvdata(spx_dev);
	if (!ddata || !ddata->regmap) {
		ret = -ENODEV;
		goto err_put;
	}
	spx_regmap = ddata->regmap;

	ret = regmap_read(spx_regmap,
			  WCD934X_TEST_DEBUG_NPL_DLY_TEST_1, &before);
	if (ret)
		goto err_put;
	spx_saved = before;

	ret = regmap_update_bits(spx_regmap,
				 WCD934X_TEST_DEBUG_NPL_DLY_TEST_1,
				 WCD934X_SWR_NPL_DELAY,
				 enable_delay ? WCD934X_SWR_NPL_DELAY : 0);
	if (ret)
		goto err_put;
	spx_changed = true;

	ret = regmap_read(spx_regmap,
			  WCD934X_TEST_DEBUG_NPL_DLY_TEST_1, &after);
	if (!ret)
		dev_info(spx_dev, "SPX: SWR NPL delay 0x%02x -> 0x%02x\n",
			 before, after);
	if (ret)
		goto err_restore;

	return 0;

err_restore:
	regmap_write(spx_regmap, WCD934X_TEST_DEBUG_NPL_DLY_TEST_1,
		     spx_saved);
	spx_changed = false;
err_put:
	put_device(spx_dev);
	spx_dev = NULL;
	spx_regmap = NULL;
	return ret;
}

static void __exit spx_wcd_npl_exit(void)
{
	if (spx_changed)
		regmap_write(spx_regmap,
			     WCD934X_TEST_DEBUG_NPL_DLY_TEST_1, spx_saved);
	if (spx_dev)
		put_device(spx_dev);
	pr_info("spx_wcd_npl: restored 0x%02x and unloaded\n", spx_saved);
}

module_init(spx_wcd_npl_init);
module_exit(spx_wcd_npl_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX one-shot WCD934x SoundWire NPL delay fix");
