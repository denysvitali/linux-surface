// SPDX-License-Identifier: GPL-2.0
/* Replay the SPX WSA881x DAPM power sequence after forced SoundWire attach. */
#include <linux/device.h>
#include <linux/module.h>
#include <linux/soundwire/sdw.h>
#include <linux/soundwire/sdw_type.h>
#include <sound/soc.h>

#define SPX_WSA_DEVICE	"sdw:0:0:0217:2010:00:1"
#define SPX_WSA_PIN	"SPKR"

static int __init spx_wsa_dapm_cycle_init(void)
{
	struct snd_soc_component *component;
	struct device *dev;
	int ret;

	dev = bus_find_device_by_name(&sdw_bus_type, NULL, SPX_WSA_DEVICE);
	if (!dev)
		return -ENODEV;

	component = snd_soc_lookup_component(dev, NULL);
	if (!component) {
		ret = -ENODEV;
		goto out_put;
	}

	ret = snd_soc_dapm_disable_pin(&component->dapm, SPX_WSA_PIN);
	if (ret)
		goto out_put;
	ret = snd_soc_dapm_sync(&component->dapm);
	if (ret)
		goto out_put;

	ret = snd_soc_dapm_enable_pin(&component->dapm, SPX_WSA_PIN);
	if (ret)
		goto out_put;
	ret = snd_soc_dapm_sync(&component->dapm);
	if (!ret)
		dev_info(dev, "SPX: replayed post-attach RDAC/PA DAPM sequence\n");

out_put:
	put_device(dev);
	return ret;
}

static void __exit spx_wsa_dapm_cycle_exit(void)
{
}

module_init(spx_wsa_dapm_cycle_init);
module_exit(spx_wsa_dapm_cycle_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX post-attach WSA881x DAPM power-cycle helper");
