// SPDX-License-Identifier: GPL-2.0
/* Replay the SPX WSA881x DAPM power sequence after forced SoundWire attach. */
#include <linux/device.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/soundwire/sdw.h>
#include <linux/soundwire/sdw_type.h>
#include <sound/soc.h>

static char *device = "sdw:0:0:0217:2010:00:1";
module_param(device, charp, 0444);
MODULE_PARM_DESC(device, "SoundWire codec whose DAPM speaker pin is cycled");
#define SPX_WSA_PIN	"SPKR"
static char *card_pin;
module_param(card_pin, charp, 0444);
MODULE_PARM_DESC(card_pin, "Optional terminal card pin, e.g. Right Spk");
static bool cold_init;
module_param(cold_init, bool, 0444);
MODULE_PARM_DESC(cold_init, "Replay codec initialization while the terminal pin is disabled");
static bool stream_route;
module_param(stream_route, bool, 0444);
MODULE_PARM_DESC(stream_route, "Add the single-speaker SPKR Playback to RDAC route");

static int __init spx_wsa_dapm_cycle_init(void)
{
	struct snd_soc_component *component;
	struct snd_soc_dapm_context *dapm;
	const char *pin;
	struct device *dev;
	int ret;
	int (*initialize)(void *) = NULL;
	struct kprobe resolver = { .symbol_name = "wsa881x_init" };

	if (cold_init) {
		ret = register_kprobe(&resolver);
		if (ret)
			return ret;
		initialize = (void *)resolver.addr;
		unregister_kprobe(&resolver);
	}

	dev = bus_find_device_by_name(&sdw_bus_type, NULL, device);
	if (!dev)
		return -ENODEV;

	component = snd_soc_lookup_component(dev, NULL);
	if (!component) {
		ret = -ENODEV;
		goto out_put;
	}
	if (stream_route) {
		const struct snd_soc_dapm_route route = {
			"RDAC", NULL, "SPKR Playback"
		};
		ret = snd_soc_dapm_add_routes(snd_soc_component_to_dapm(component), &route, 1);
		if (ret)
			goto out_put;
	}

	dapm = card_pin ? snd_soc_card_to_dapm(component->card) : snd_soc_component_to_dapm(component);
	pin = card_pin ? card_pin : SPX_WSA_PIN;
	ret = snd_soc_dapm_disable_pin(dapm, pin);
	if (ret)
		goto out_put;
	ret = snd_soc_dapm_sync(dapm);
	if (ret)
		goto out_put;
	if (initialize) {
		ret = initialize(dev_get_drvdata(dev));
		if (ret)
			goto out_put;
	}

	ret = snd_soc_dapm_enable_pin(dapm, pin);
	if (ret)
		goto out_put;
	ret = snd_soc_dapm_sync(dapm);
	if (!ret)
		dev_info(dev, "SPX: requested DAPM cycle of %s\n", pin);

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
