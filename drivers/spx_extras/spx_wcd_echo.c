// SPDX-License-Identifier: GPL-2.0
/* Select or clear the WCD9340 RX7/RX8 digital echo paths for loopback tests. */
#include <linux/device.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>
#include <sound/soc.h>

#define SPX_CODEC_DEVICE		"217:250:1:0"

#define WCD934X_RX_MIX_CFG0		0x0d13
#define WCD934X_RX_MIX_TX0_MASK		GENMASK(3, 0)
#define WCD934X_RX_MIX_TX1_MASK		GENMASK(7, 4)
#define WCD934X_RX_MIX_TX0_RX7		FIELD_PREP(WCD934X_RX_MIX_TX0_MASK, 8)
#define WCD934X_RX_MIX_TX1_RX8		FIELD_PREP(WCD934X_RX_MIX_TX1_MASK, 9)
#define WCD934X_RX_MIX_MASK		(WCD934X_RX_MIX_TX0_MASK | \
					 WCD934X_RX_MIX_TX1_MASK)
#define WCD934X_RX_MIX_VALUE		(WCD934X_RX_MIX_TX0_RX7 | \
					 WCD934X_RX_MIX_TX1_RX8)

static bool enable = true;
module_param(enable, bool, 0400);
MODULE_PARM_DESC(enable, "Route RX7/RX8 mixes to echo TX0/TX1");

static const struct snd_soc_dapm_route spx_echo_routes[] = {
	{
		.sink = "CDC_IF TX0 MUX",
		.control = "RX_MIX_TX0",
		.source = "RX INT7 SEC MIX",
	},
	{
		.sink = "CDC_IF TX1 MUX",
		.control = "RX_MIX_TX1",
		.source = "RX INT8 SEC MIX",
	},
};

static struct device *spx_codec_dev;
static struct snd_soc_component *spx_component;
static bool spx_route_added;

static int spx_match_codec(struct device *dev, const void *data)
{
	return dev->driver && !strcmp(dev->driver->name, "wcd934x-codec");
}

static void spx_remove_route(void)
{
	if (spx_route_added) {
		snd_soc_dapm_del_routes(snd_soc_component_to_dapm(spx_component), spx_echo_routes,
					ARRAY_SIZE(spx_echo_routes));
		snd_soc_dapm_sync(snd_soc_component_to_dapm(spx_component));
		spx_route_added = false;
	}

	if (spx_codec_dev) {
		put_device(spx_codec_dev);
		spx_codec_dev = NULL;
		spx_component = NULL;
	}
}

static int __init spx_wcd_echo_init(void)
{
	struct wcd934x_ddata *ddata;
	struct device *dev;
	unsigned int value;
	int ret;

	dev = bus_find_device_by_name(&slimbus_bus, NULL, SPX_CODEC_DEVICE);
	if (!dev)
		return -ENODEV;

	ddata = dev_get_drvdata(dev);
	if (!ddata || !ddata->regmap) {
		ret = -ENODEV;
		goto out_put;
	}

	ret = regmap_update_bits(ddata->regmap, WCD934X_RX_MIX_CFG0,
				 WCD934X_RX_MIX_MASK,
				 enable ? WCD934X_RX_MIX_VALUE : 0);
	if (ret)
		goto out_put;

	if (enable) {
		spx_codec_dev = device_find_child(dev, NULL, spx_match_codec);
		if (!spx_codec_dev) {
			ret = -ENODEV;
			goto out_clear;
		}

		spx_component = snd_soc_lookup_component(spx_codec_dev, NULL);
		if (!spx_component) {
			ret = -ENODEV;
			goto out_remove;
		}

		ret = snd_soc_dapm_add_routes(snd_soc_component_to_dapm(spx_component),
					      spx_echo_routes,
					      ARRAY_SIZE(spx_echo_routes));
		if (ret)
			goto out_remove;
		spx_route_added = true;

		ret = snd_soc_dapm_sync(snd_soc_component_to_dapm(spx_component));
		if (ret)
			goto out_remove;
	}

	ret = regmap_read(ddata->regmap, WCD934X_RX_MIX_CFG0, &value);
	if (!ret)
		dev_info(dev, "SPX: RX7/RX8 digital echo %s (reg 0x%04x = 0x%02x)\n",
			 enable ? "enabled" : "disabled", WCD934X_RX_MIX_CFG0,
			 value);
	goto out_put;

out_remove:
	spx_remove_route();
out_clear:
	regmap_update_bits(ddata->regmap, WCD934X_RX_MIX_CFG0,
			   WCD934X_RX_MIX_MASK, 0);

out_put:
	put_device(dev);
	return ret;
}

static void __exit spx_wcd_echo_exit(void)
{
	struct wcd934x_ddata *ddata;
	struct device *dev;

	spx_remove_route();

	dev = bus_find_device_by_name(&slimbus_bus, NULL, SPX_CODEC_DEVICE);
	if (!dev)
		return;

	ddata = dev_get_drvdata(dev);
	if (ddata && ddata->regmap)
		regmap_update_bits(ddata->regmap, WCD934X_RX_MIX_CFG0,
				   WCD934X_RX_MIX_MASK, 0);
	put_device(dev);
}

module_init(spx_wcd_echo_init);
module_exit(spx_wcd_echo_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX WCD9340 RX7/RX8 digital echo selector");
