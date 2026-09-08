// SPDX-License-Identifier: GPL-2.0
/* Apply the downstream WCD934x SoundWire speaker-path defaults on SPX. */
#include <linux/device.h>
#include <linux/mfd/wcd934x/registers.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>

#define SPX_CODEC_DEVICE "217:250:1:0"

struct spx_reg_default {
	unsigned int reg;
	unsigned int mask;
	unsigned int val;
	unsigned int restore_val;
	const char *name;
};

static const struct spx_reg_default spx_speaker_defaults[] = {
	{ WCD934X_CDC_COMPANDER7_CTL3, 0x80, 0x80, 0x00, "COMPANDER7_CTL3" },
	{ WCD934X_CDC_COMPANDER8_CTL3, 0x80, 0x80, 0x00, "COMPANDER8_CTL3" },
	{ WCD934X_CDC_COMPANDER7_CTL7, 0x01, 0x01, 0x00, "COMPANDER7_CTL7" },
	{ WCD934X_CDC_COMPANDER8_CTL7, 0x01, 0x01, 0x00, "COMPANDER8_CTL7" },
	{ WCD934X_CDC_BOOST0_BOOST_CTL, 0x7c, 0x50, 0x30, "BOOST0_BOOST_CTL" },
	{ WCD934X_CDC_BOOST1_BOOST_CTL, 0x7c, 0x50, 0x30, "BOOST1_BOOST_CTL" },
	{ WCD934X_CDC_TOP_TOP_CFG1, 0x03, 0x03, 0x00, "TOP_TOP_CFG1" },
};

static bool restore;
module_param(restore, bool, 0400);
MODULE_PARM_DESC(restore, "Restore the live pre-test SPX register values");

static int __init spx_wcd_speaker_defaults_init(void)
{
	struct wcd934x_ddata *ddata;
	struct device *dev;
	unsigned int before, after;
	int i, ret;

	dev = bus_find_device_by_name(&slimbus_bus, NULL, SPX_CODEC_DEVICE);
	if (!dev)
		return -ENODEV;

	ddata = dev_get_drvdata(dev);
	if (!ddata || !ddata->regmap) {
		ret = -ENODEV;
		goto out_put;
	}

	for (i = 0; i < ARRAY_SIZE(spx_speaker_defaults); i++) {
		const struct spx_reg_default *d = &spx_speaker_defaults[i];

		ret = regmap_read(ddata->regmap, d->reg, &before);
		if (ret)
			goto out_put;
		ret = regmap_update_bits(ddata->regmap, d->reg, d->mask,
				 restore ? d->restore_val : d->val);
		if (ret)
			goto out_put;
		ret = regmap_read(ddata->regmap, d->reg, &after);
		if (ret)
			goto out_put;

		dev_info(dev, "SPX: %-20s 0x%02x -> 0x%02x\n",
			 d->name, before, after);
	}

out_put:
	put_device(dev);
	return ret;
}

static void __exit spx_wcd_speaker_defaults_exit(void)
{
}

module_init(spx_wcd_speaker_defaults_init);
module_exit(spx_wcd_speaker_defaults_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX WCD934x downstream speaker defaults");
