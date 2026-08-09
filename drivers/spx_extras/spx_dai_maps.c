// SPDX-License-Identifier: GPL-2.0
/* Read-only dump of the live ASoC DAI channel maps on Surface Pro X. */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <sound/soc.h>

#define SPX_MAX_CHANNELS 16

static void spx_dump_dai(const char *kind, const char *link_name,
			 struct snd_soc_dai *dai)
{
	unsigned int tx[SPX_MAX_CHANNELS] = {};
	unsigned int rx[SPX_MAX_CHANNELS] = {};
	unsigned int tx_num = 0, rx_num = 0;
	int ret;
	int i;

	ret = snd_soc_dai_get_channel_map(dai, &tx_num, tx, &rx_num, rx);
	pr_info("spx_dai_maps: link=%s %s=%s id=%d ret=%d tx_num=%u rx_num=%u\n",
		link_name, kind, dai->name, dai->id, ret, tx_num, rx_num);
	if (ret)
		return;

	for (i = 0; i < min_t(unsigned int, tx_num, SPX_MAX_CHANNELS); i++)
		pr_info("spx_dai_maps:   tx[%d]=0x%x\n", i, tx[i]);
	for (i = 0; i < min_t(unsigned int, rx_num, SPX_MAX_CHANNELS); i++)
		pr_info("spx_dai_maps:   rx[%d]=0x%x\n", i, rx[i]);
}

static int __init spx_dai_maps_init(void)
{
	struct snd_soc_pcm_runtime *rtd;
	struct snd_soc_card *card;
	struct snd_soc_dai *dai;
	struct device *dev;
	int i;

	dev = bus_find_device_by_name(&platform_bus_type, NULL, "sound");
	if (!dev)
		return -ENODEV;

	card = dev_get_drvdata(dev);
	if (!card) {
		put_device(dev);
		return -ENODEV;
	}

	for_each_card_rtds(card, rtd) {
		if (strcmp(rtd->dai_link->name, "SLIM Playback"))
			continue;

		for_each_rtd_cpu_dais(rtd, i, dai)
			spx_dump_dai("cpu", rtd->dai_link->name, dai);
		for_each_rtd_codec_dais(rtd, i, dai)
			spx_dump_dai("codec", rtd->dai_link->name, dai);
	}

	put_device(dev);
	return -EAGAIN;
}

static void __exit spx_dai_maps_exit(void)
{
}

module_init(spx_dai_maps_init);
module_exit(spx_dai_maps_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Surface Pro X read-only ASoC DAI channel-map dump");
