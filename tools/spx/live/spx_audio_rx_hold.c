// SPDX-License-Identifier: GPL-2.0-only
/*
 * Live SPX retained-playback experiment: vote for the two digital RX clocks
 * through DAPM without unregistering the card or its DSP-mapped PCM buffers.
 * No amplifier widgets are forced. Unload restores the original pin state.
 */
#include <linux/device.h>
#include <linux/module.h>
#include <linux/of.h>
#include <sound/soc.h>

static const char * const pins[] = { "INT7_CLK", "INT8_CLK" };
static bool connected[ARRAY_SIZE(pins)];
static struct device *codec_dev;
static struct module *codec_owner;

static void restore_pins(struct snd_soc_dapm_context *dapm, unsigned int count)
{
	unsigned int i;

	for (i = 0; i < count; i++) {
		snd_soc_dapm_disable_pin_unlocked(dapm, pins[i]);
		if (connected[i])
			snd_soc_dapm_enable_pin_unlocked(dapm, pins[i]);
	}
	snd_soc_dapm_sync_unlocked(dapm);
}

static int __init spx_audio_rx_hold_init(void)
{
	struct snd_soc_component *component;
	struct snd_soc_dapm_context *dapm;
	struct snd_soc_dapm_widget *w;
	unsigned int i, changed = 0;
	bool found;
	int ret = 0;

	if (!of_machine_is_compatible("microsoft,surface-pro-x"))
		return -ENODEV;

	component = snd_soc_lookup_component_by_name("wcd934x-codec.");
	if (!component || !component->card || !component->card->instantiated)
		return -ENODEV;
	codec_dev = get_device(component->dev);
	device_lock(codec_dev);
	if (!codec_dev->driver ||
	    !try_module_get(codec_dev->driver->owner)) {
		ret = -ENODEV;
		goto put_device;
	}
	codec_owner = codec_dev->driver->owner;
	/* Re-resolve under the device lock in case it was unbound. */
	component = snd_soc_lookup_component(codec_dev, NULL);
	if (!component || !component->card || !component->card->instantiated) {
		ret = -ENODEV;
		goto put_module;
	}
	dapm = snd_soc_component_to_dapm(component);
	snd_soc_dapm_mutex_lock_root(dapm);
	for (i = 0; i < ARRAY_SIZE(pins); i++) {
		found = false;
		for_each_card_widgets(component->card, w) {
			if (w->dapm != dapm || strcmp(w->name, pins[i]))
				continue;
			if (w->id != snd_soc_dapm_supply || w->force) {
				ret = -EBUSY;
				goto unlock;
			}
			connected[i] = w->connected;
			found = true;
			break;
		}
		if (!found) {
			ret = -ENOENT;
			goto unlock;
		}
	}
	for (i = 0; i < ARRAY_SIZE(pins); i++) {
		ret = snd_soc_dapm_force_enable_pin_unlocked(dapm, pins[i]);
		if (ret)
			goto unlock;
		changed++;
	}
	ret = snd_soc_dapm_sync_unlocked(dapm);
unlock:
	if (ret && changed)
		restore_pins(dapm, changed);
	snd_soc_dapm_mutex_unlock(dapm);
	if (!ret) {
		device_unlock(codec_dev);
		pr_info("spx_audio_rx_hold: retaining INT7_CLK and INT8_CLK only\n");
		return 0;
	}
put_module:
	module_put(codec_owner);
put_device:
	device_unlock(codec_dev);
	put_device(codec_dev);
	codec_dev = NULL;
	return ret;
}

static void __exit spx_audio_rx_hold_exit(void)
{
	struct snd_soc_component *component;
	struct snd_soc_dapm_context *dapm;

	device_lock(codec_dev);
	component = snd_soc_lookup_component(codec_dev, NULL);
	if (component && component->card && component->card->instantiated) {
		dapm = snd_soc_component_to_dapm(component);
		snd_soc_dapm_mutex_lock_root(dapm);
		restore_pins(dapm, ARRAY_SIZE(pins));
		snd_soc_dapm_mutex_unlock(dapm);
	}
	device_unlock(codec_dev);
	module_put(codec_owner);
	put_device(codec_dev);
}

module_init(spx_audio_rx_hold_init);
module_exit(spx_audio_rx_hold_exit);
MODULE_DESCRIPTION("SPX WIP digital RX clock retention experiment");
MODULE_LICENSE("GPL");
