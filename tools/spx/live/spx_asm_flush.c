// SPDX-License-Identifier: GPL-2.0-only
/*
 * One-shot SPX playback recovery experiment. A closed MM1 PCM retains its
 * ASM client and mappings. Pause/flush that existing session after EOS.
 * Optional explicit restart/remap never unmaps or starts playback.
 */
#include <linux/device.h>
#include <linux/module.h>
#include <linux/of.h>
#include <sound/soc.h>
#include "../../../sound/soc/qcom/qdsp6/q6asm.h"
#include "../../../sound/soc/qcom/qdsp6/q6adm.h"

static bool restart;
module_param(restart, bool, 0444);
MODULE_PARM_DESC(restart, "After pause/flush ACK, close and reopen 48k stereo S16 playback; retain mappings");

static bool remap;
module_param(remap, bool, 0444);
MODULE_PARM_DESC(remap, "Remap session 1 to the retained speaker COPP after an explicit ASM restart");

static int spx_remap_playback(struct snd_soc_card *card, int port)
{
	struct route_payload payload = {
		.num_copps = 1,
		.session_id = 1,
		.copp_idx = { 0 },
		.port_id = { port },
	};
	struct snd_soc_component *component;
	struct device *dev;
	int ret = -ENODEV;

	component = snd_soc_lookup_component_by_name("service@8:routing");
	if (!component || port < 0)
		return -ENODEV;
	dev = get_device(component->dev);
	device_lock(dev);
	if (dev->driver && try_module_get(dev->driver->owner)) {
		component = snd_soc_lookup_component(dev, NULL);
		if (component && component->card == card)
			/* The first COPP on this backend is index 0. The API
			 * requires a cached COPP and resolves its real DSP ID;
			 * it fails without sending if that entry is absent.
			 */
			ret = q6adm_matrix_map(dev, ADM_PATH_PLAYBACK,
					      payload, LEGACY_PCM_MODE);
		module_put(dev->driver->owner);
	}
	device_unlock(dev);
	put_device(dev);
	pr_info("spx_asm_flush: playback remap port=%d result=%d\n", port, ret);
	return ret < 0 ? ret : 0;
}

static int __init spx_asm_flush_init(void)
{
	struct snd_soc_component *component;
	struct snd_soc_pcm_runtime *rtd;
	struct snd_pcm_substream *substream;
	struct audio_client *client;
	struct snd_pcm *pcm = NULL;
	struct device *dev;
	struct module *owner;
	int ret = -ENODEV, pointer, port = -1;

	if (!of_machine_is_compatible("microsoft,surface-pro-x"))
		return -ENODEV;
	component = snd_soc_lookup_component_by_name("service@7:dais");
	if (!component)
		return -ENODEV;
	dev = get_device(component->dev);
	device_lock(dev);
	if (!dev->driver || !try_module_get(dev->driver->owner))
		goto put_device;
	owner = dev->driver->owner;
	component = snd_soc_lookup_component(dev, NULL);
	if (!component || !component->card || !component->card->instantiated)
		goto put_module;
	for_each_card_rtds(component->card, rtd) {
		struct snd_soc_dai *cpu = snd_soc_rtd_to_cpu(rtd, 0);

		if (rtd->dai_link->no_pcm &&
		    !strcmp(rtd->dai_link->name, "SLIM Playback"))
			port = cpu->driver->id;
		if (!rtd->dai_link->no_pcm && cpu->component == component &&
		    cpu->driver->id == 0)
			pcm = rtd->pcm;
	}
	if (!pcm)
		goto put_module;
	mutex_lock(&pcm->open_mutex);
	substream = pcm->streams[SNDRV_PCM_STREAM_PLAYBACK].substream;
	if (!substream || substream->ref_count || substream->runtime) {
		ret = -EBUSY;
		goto unlock_pcm;
	}
	/*
	 * This API gets a reference to an existing client without changing its
	 * callback. A nonzero consumed pointer proves this is a used session;
	 * reject an accidentally allocated empty client before sending commands.
	 * FE 0 owns playback session 1; capture uses a different FE/session.
	 */
	client = q6asm_audio_client_alloc(dev, NULL, NULL, 0, LEGACY_PCM_MODE);
	if (IS_ERR(client)) {
		ret = PTR_ERR(client);
		goto unlock_pcm;
	}
	pointer = q6asm_get_hw_pointer(client, SNDRV_PCM_STREAM_PLAYBACK);
	if (q6asm_get_session_id(client) != 1 || pointer <= 0) {
		ret = -ENODATA;
		goto put_client;
	}
	ret = q6asm_cmd(client, 1, CMD_PAUSE);
	pr_info("spx_asm_flush: parked playback pointer=%d pause=%d\n",
		pointer, ret);
	if (!ret) {
		ret = q6asm_cmd(client, 1, CMD_FLUSH);
		pr_info("spx_asm_flush: playback flush=%d; no RUN/CLOSE/UNMAP\n",
			ret);
	}
	if (!ret && restart) {
		ret = q6asm_cmd(client, 1, CMD_CLOSE);
		pr_info("spx_asm_flush: playback close=%d\n", ret);
		if (!ret) {
			ret = q6asm_open_write(client, 1, FORMAT_LINEAR_PCM,
					      0, 16, false);
			pr_info("spx_asm_flush: playback open=%d\n", ret);
			if (!ret) {
				ret = q6asm_media_format_block_multi_ch_pcm(client,
						1, 48000, 2, NULL, 16);
				pr_info("spx_asm_flush: playback format=%d\n", ret);
			}
		}
	}
	if (!ret && remap)
		ret = spx_remap_playback(component->card, port);
put_client:
	q6asm_audio_client_free(client);
unlock_pcm:
	mutex_unlock(&pcm->open_mutex);
put_module:
	module_put(owner);
put_device:
	device_unlock(dev);
	put_device(dev);
	return ret;
}

static void __exit spx_asm_flush_exit(void)
{
}

module_init(spx_asm_flush_init);
module_exit(spx_asm_flush_exit);
MODULE_DESCRIPTION("SPX WIP one-shot retained playback pause/flush");
MODULE_LICENSE("GPL");
