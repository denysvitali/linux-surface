// SPDX-License-Identifier: GPL-2.0
// Copyright (c) 2011-2017, The Linux Foundation. All rights reserved.
// Copyright (c) 2018, Linaro Limited

#include <dt-bindings/sound/qcom,q6asm.h>
#include <linux/init.h>
#include <linux/err.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <sound/soc.h>
#include <sound/soc-dapm.h>
#include <sound/pcm.h>
#include <linux/spinlock.h>
#include <sound/compress_driver.h>
#include <asm/div64.h>
#include <asm/dma.h>
#include <linux/dma-mapping.h>
#include <linux/iommu.h>
#include <sound/pcm_params.h>
#include "q6asm.h"
#include "q6routing.h"
#include "q6dsp-errno.h"

#define DRV_NAME	"q6asm-fe-dai"

#define PLAYBACK_MIN_NUM_PERIODS    2
#define PLAYBACK_MAX_NUM_PERIODS   8
#define PLAYBACK_MAX_PERIOD_SIZE    65536
#define PLAYBACK_MIN_PERIOD_SIZE    128
#define CAPTURE_MIN_NUM_PERIODS     2
#define CAPTURE_MAX_NUM_PERIODS     8
#define CAPTURE_MAX_PERIOD_SIZE     4096
#define CAPTURE_MIN_PERIOD_SIZE     320
#define SID_MASK_DEFAULT	0xF

/* Default values used if user space does not set */
#define COMPR_PLAYBACK_MIN_FRAGMENT_SIZE (8 * 1024)
#define COMPR_PLAYBACK_MAX_FRAGMENT_SIZE (128 * 1024)
#define COMPR_PLAYBACK_MIN_NUM_FRAGMENTS (4)
#define COMPR_PLAYBACK_MAX_NUM_FRAGMENTS (16 * 4)

#define ALAC_CH_LAYOUT_MONO   ((101 << 16) | 1)
#define ALAC_CH_LAYOUT_STEREO ((101 << 16) | 2)

enum stream_state {
	Q6ASM_STREAM_IDLE = 0,
	Q6ASM_STREAM_STOPPED,
	Q6ASM_STREAM_RUNNING,
};

struct q6asm_dai_rtd {
	bool spx_legacy;
	unsigned int pcm_irq_pos;
	struct snd_pcm_substream *substream;
	struct snd_compr_stream *cstream;
	struct snd_codec codec;
	struct snd_dma_buffer dma_buffer;
	spinlock_t lock;
	phys_addr_t phys;
	unsigned int pcm_size;
	unsigned int pcm_count;
	unsigned int periods;
	uint64_t bytes_sent;
	uint64_t bytes_received;
	uint64_t copied_total;
	uint16_t bits_per_sample;
	snd_pcm_uframes_t queue_ptr;
	uint16_t source; /* Encoding source bit mask */
	struct audio_client *audio_client;
	uint32_t next_track_stream_id;
	bool next_track;
	uint32_t stream_id;
	uint16_t session_id;
	enum stream_state state;
	uint32_t initial_samples_drop;
	uint32_t trailing_samples_drop;
	bool notify_on_drain;
	phys_addr_t alias_iova;	/* SPX: high-window IOVA alias for the ADSP */
	size_t alias_sz;
	struct delayed_work write_watchdog;
	unsigned long period_jiffies;
	bool write_fallback;
	/*
	 * SPX: the firmware ACKs writes but has never been observed to emit a
	 * consumption event, so the fallback worker fakes period progress and
	 * ALSA looks healthy whether or not the DSP renders anything. Count
	 * both paths so a silent stream can be told apart from a dead one.
	 */
	unsigned int n_write_done;
	unsigned int n_fallback;
	unsigned int n_submitted;
	bool client_reused;	/* SPX: audio_client was parked across a close */
};

struct q6asm_dai_data {
	struct snd_soc_dai_driver *dais;
	int num_dais;
	long long int sid;
	/*
	 * SPX: the Microsoft ADSP never ACKs ASM session close, so CMD_CLOSE +
	 * unmap + free on every PCM close leaks DSP-side session state and the
	 * next stream re-maps the same phys into a dangling session -> the DSP
	 * consumes nothing (write_done=0). Park the audio client here instead
	 * and reuse it, mirroring spx_keep_copp at the ADM layer. One slot per
	 * direction and FE DAI (ids 0..15): a capture client that took the stock
	 * CLOSE+UNMAP path wedged every later MEM_MAP on the ADSP (2026-08-24),
	 * killing the boot's playback too, so capture is parked as well.
	 */
	struct audio_client *parked[2][16];
};

static int spx_period_adjust_ms;
module_param(spx_period_adjust_ms, int, 0644);
MODULE_PARM_DESC(spx_period_adjust_ms,
		 "SPX: signed adjustment to fallback write cadence in milliseconds");

/*
 * Keep the recovered audible baseline as the default, but allow a guarded
 * cold-boot A/B against the DSP's real WRITE_DONE events.  The timer path was
 * added when only immediate WRITE acceptance ACKs were visible.  Those ACKs
 * are now filtered in q6asm_stream_callback(), and the v15/v16 first streams
 * each delivered real ASM_DATA_EVENT_WRITE_DONE_V2 events.  Driving the ring
 * from a wall-clock timer while ignoring those events can race DSP consumption
 * and is a plausible source of the remaining static.
 */
static bool spx_force_timer_pacing = true;
module_param(spx_force_timer_pacing, bool, 0644);
MODULE_PARM_DESC(spx_force_timer_pacing,
		 "SPX: force timer-paced playback writes instead of DSP WRITE_DONE pacing");

/*
 * SPX: the Microsoft ADSP never ACKs ASM_STREAM_CMD_CLOSE, so the upstream
 * close path (CMD_CLOSE + unmap + client free) leaks DSP-side session state.
 * The very next stream re-maps the same phys and the DSP never consumes it
 * (write_done=0). Park the audio client across close and reuse it, exactly as
 * spx_keep_copp preserves the COPP/matrix route at the ADM layer. This makes
 * repeated streams (music) render instead of only the first after cold boot.
 */
static bool spx_keep_asm = true;
module_param(spx_keep_asm, bool, 0644);
MODULE_PARM_DESC(spx_keep_asm,
		 "SPX: park and reuse the ASM audio client across PCM closes");

/*
 * SPX (2026-06-22): the address the ADSP is told to map = buf->addr | (sid<<32).
 * RE of the Windows codec mgr (qcadcm8180.sys ADCM\SMMU\POIPU_V1) shows the ADSP
 * audio SMMU IOVA window is [0x1_00000000, 0x1_FFFF0000) (bit32 set; ARID
 * 0x07030000 = apps_smmu SID 0x1b21). sid = 0x1b21 & 0xF = 1, so sid<<32 places
 * the address into that window. The bug: q6asm only IOMMU-maps buf->addr (the
 * LOW IOVA) but tells the DSP the HIGH IOVA -> the DSP access is unmapped
 * (EFAILED) or, with bit32 cleared, out-of-window (ADSP watchdog crash). Fix:
 * alias-map the buffer's pages at the HIGH IOVA in the same apps_smmu context.
 */
static phys_addr_t spx_map_addr(struct q6asm_dai_data *pdata, dma_addr_t iova)
{
	if (pdata->sid < 0)
		return iova;
	return iova | ((phys_addr_t)pdata->sid << 32);
}

/*
 * SPX H4 probe: the ADSP VCM context registry says MemoryCacheType=2; if the
 * ADSP expects device/non-cached and we map IOMMU_CACHE the walk may stall.
 * prot is a module param. On the Surface Pro X the ADSP requires the alias
 * to be non-cacheable; the stock cacheable mapping makes mem-map stall or
 * return EFAILED. Keep the parameter override for A/B testing.
 */
static int spx_alias_prot = IOMMU_READ | IOMMU_WRITE;
module_param_named(alias_prot, spx_alias_prot, int, 0644);
MODULE_PARM_DESC(alias_prot,
		 "SPX: iommu_map prot for the high-IOVA alias (default READ|WRITE)");

static int spx_alias_dbg;
module_param_named(alias_debug, spx_alias_dbg, int, 0644);
MODULE_PARM_DESC(alias_debug, "SPX: log iova_to_phys of the alias first page");

/* Map the buffer pages at the high-window IOVA the ADSP will access. */
static int spx_alias_map(struct device *dev, dma_addr_t low, phys_addr_t high,
			 size_t size)
{
	struct iommu_domain *dom = iommu_get_domain_for_dev(dev);
	size_t off;
	int ret;

	if (!dom || high == low)
		return 0;
	size = ALIGN(size, PAGE_SIZE);
	for (off = 0; off < size; off += PAGE_SIZE) {
		phys_addr_t pa = iommu_iova_to_phys(dom, low + off);

		if (!pa) {
			ret = -EINVAL;
			goto err;
		}
		if (!off && spx_alias_dbg)
			dev_info(dev, "SPX alias: low=%pad high=0x%llx pa=%pa sz=%zu prot=0x%x\n",
				 &low, (unsigned long long)high, &pa, size,
				 spx_alias_prot);
		ret = iommu_map(dom, high + off, pa, PAGE_SIZE,
				spx_alias_prot, GFP_KERNEL);
		if (ret)
			goto err;
	}
	return 0;
err:
	if (off)
		iommu_unmap(dom, high, off);
	return ret;
}

static void spx_alias_unmap(struct device *dev, phys_addr_t high, size_t size)
{
	struct iommu_domain *dom = iommu_get_domain_for_dev(dev);

	if (dom && high && size)
		iommu_unmap(dom, high, ALIGN(size, PAGE_SIZE));
}

static const struct snd_pcm_hardware q6asm_dai_hardware_capture = {
	.info =                 (SNDRV_PCM_INFO_MMAP | SNDRV_PCM_INFO_BATCH |
				SNDRV_PCM_INFO_BLOCK_TRANSFER |
				SNDRV_PCM_INFO_NO_REWINDS | SNDRV_PCM_INFO_SYNC_APPLPTR |
				SNDRV_PCM_INFO_MMAP_VALID |
				SNDRV_PCM_INFO_INTERLEAVED |
				SNDRV_PCM_INFO_PAUSE | SNDRV_PCM_INFO_RESUME),
	.formats =              (SNDRV_PCM_FMTBIT_S16_LE |
				SNDRV_PCM_FMTBIT_S24_LE),
	.rates =                SNDRV_PCM_RATE_8000_48000,
	.rate_min =             8000,
	.rate_max =             48000,
	.channels_min =         1,
	.channels_max =         4,
	.buffer_bytes_max =     CAPTURE_MAX_NUM_PERIODS *
				CAPTURE_MAX_PERIOD_SIZE,
	.period_bytes_min =	CAPTURE_MIN_PERIOD_SIZE,
	.period_bytes_max =     CAPTURE_MAX_PERIOD_SIZE,
	.periods_min =          CAPTURE_MIN_NUM_PERIODS,
	.periods_max =          CAPTURE_MAX_NUM_PERIODS,
	.fifo_size =            0,
};

static const struct snd_pcm_hardware q6asm_dai_hardware_playback = {
	.info =                 (SNDRV_PCM_INFO_MMAP | SNDRV_PCM_INFO_BATCH |
				SNDRV_PCM_INFO_BLOCK_TRANSFER |
				SNDRV_PCM_INFO_MMAP_VALID |
				SNDRV_PCM_INFO_NO_REWINDS | SNDRV_PCM_INFO_SYNC_APPLPTR |
				SNDRV_PCM_INFO_INTERLEAVED |
				SNDRV_PCM_INFO_PAUSE | SNDRV_PCM_INFO_RESUME),
	.formats =              (SNDRV_PCM_FMTBIT_S16_LE |
				SNDRV_PCM_FMTBIT_S24_LE),
	.rates =                SNDRV_PCM_RATE_8000_192000,
	.rate_min =             8000,
	.rate_max =             192000,
	.channels_min =         1,
	.channels_max =         8,
	.buffer_bytes_max =     (PLAYBACK_MAX_NUM_PERIODS *
				PLAYBACK_MAX_PERIOD_SIZE),
	.period_bytes_min =	PLAYBACK_MIN_PERIOD_SIZE,
	.period_bytes_max =     PLAYBACK_MAX_PERIOD_SIZE,
	.periods_min =          PLAYBACK_MIN_NUM_PERIODS,
	.periods_max =          PLAYBACK_MAX_NUM_PERIODS,
	.fifo_size =            0,
};

#define Q6ASM_FEDAI_DRIVER(num) { \
		.playback = {						\
			.stream_name = "MultiMedia"#num" Playback",	\
			.rates = (SNDRV_PCM_RATE_8000_48000 |		\
				  SNDRV_PCM_RATE_12000 |		\
				  SNDRV_PCM_RATE_24000 |		\
				  SNDRV_PCM_RATE_88200 |		\
				  SNDRV_PCM_RATE_96000 |		\
				  SNDRV_PCM_RATE_176400 |		\
				  SNDRV_PCM_RATE_192000),		\
			.formats = (SNDRV_PCM_FMTBIT_S16_LE |		\
					SNDRV_PCM_FMTBIT_S24_LE),	\
			.channels_min = 1,				\
			.channels_max = 8,				\
			.rate_min =     8000,				\
			.rate_max =	192000,				\
		},							\
		.capture = {						\
			.stream_name = "MultiMedia"#num" Capture",	\
			.rates = (SNDRV_PCM_RATE_8000_48000 |		\
				  SNDRV_PCM_RATE_12000 |		\
				  SNDRV_PCM_RATE_24000),		\
			.formats = (SNDRV_PCM_FMTBIT_S16_LE |		\
				    SNDRV_PCM_FMTBIT_S24_LE),		\
			.channels_min = 1,				\
			.channels_max = 4,				\
			.rate_min =     8000,				\
			.rate_max =	48000,				\
		},							\
		.name = "MultiMedia"#num,				\
		.id = MSM_FRONTEND_DAI_MULTIMEDIA##num,			\
	}

static const struct snd_compr_codec_caps q6asm_compr_caps = {
	.num_descriptors = 1,
	.descriptor[0].max_ch = 2,
	.descriptor[0].sample_rates = {	8000, 11025, 12000, 16000, 22050,
					24000, 32000, 44100, 48000, 88200,
					96000, 176400, 192000 },
	.descriptor[0].num_sample_rates = 13,
	.descriptor[0].bit_rate[0] = 320,
	.descriptor[0].bit_rate[1] = 128,
	.descriptor[0].num_bitrates = 2,
	.descriptor[0].profiles = 0,
	.descriptor[0].modes = SND_AUDIOCHANMODE_MP3_STEREO,
	.descriptor[0].formats = 0,
};

static void q6asm_write_watchdog(struct work_struct *work)
{
	struct q6asm_dai_rtd *prtd =
		container_of(to_delayed_work(work), struct q6asm_dai_rtd,
			     write_watchdog);

	if (prtd->state != Q6ASM_STREAM_RUNNING || !prtd->substream)
		return;

	WRITE_ONCE(prtd->write_fallback, true);
	prtd->pcm_irq_pos += prtd->pcm_count;
	snd_pcm_period_elapsed(prtd->substream);
	if (prtd->state != Q6ASM_STREAM_RUNNING)
		return;
	prtd->n_fallback++;
	prtd->n_submitted++;
	q6asm_write_async(prtd->audio_client, prtd->stream_id,
			  prtd->pcm_count, 0, 0, 0);

	mod_delayed_work(system_wq, &prtd->write_watchdog,
			 max_t(unsigned long, 1, prtd->period_jiffies));
}

static void spx_event_handler(uint32_t opcode, uint32_t token,
			  void *payload, void *priv)
{
	struct q6asm_dai_rtd *prtd = priv;
	struct snd_pcm_substream *substream = prtd->substream;

	switch (opcode) {
	case ASM_CLIENT_EVENT_CMD_RUN_DONE:
		if (substream->stream == SNDRV_PCM_STREAM_PLAYBACK) {
			int i;

			if (spx_force_timer_pacing) {
				/* Fill the DSP queue before starting timer pacing. */
				prtd->write_fallback = true;
				prtd->n_submitted += prtd->periods;
				for (i = 0; i < prtd->periods; i++)
					q6asm_write_async(prtd->audio_client,
							  prtd->stream_id,
							  prtd->pcm_count, 0, 0, 0);
				mod_delayed_work(system_wq,
						 &prtd->write_watchdog,
						 max_t(unsigned long, 1,
						       prtd->period_jiffies));
			} else {
				/* Upstream-style one-buffer queue, paced by WRITE_DONE. */
				prtd->write_fallback = false;
				prtd->n_submitted++;
				/* Arm before submit so an immediate completion can claim it. */
				mod_delayed_work(system_wq,
						 &prtd->write_watchdog,
						 max_t(unsigned long, 1,
						       prtd->period_jiffies * 2));
				q6asm_write_async(prtd->audio_client,
						  prtd->stream_id,
						  prtd->pcm_count, 0, 0, 0);
			}
		}
		break;
	case ASM_CLIENT_EVENT_CMD_EOS_DONE:
		prtd->state = Q6ASM_STREAM_STOPPED;
		break;
	case ASM_CLIENT_EVENT_DATA_WRITE_DONE: {
		prtd->n_write_done++;
		if (READ_ONCE(prtd->write_fallback))
			break;
		/*
		 * The completion and watchdog are competing producers.  Claim the
		 * outstanding period by cancelling its pending watchdog before
		 * advancing ALSA or submitting the replacement buffer.  If the
		 * watchdog is already running, it owns this boundary and switches
		 * the stream permanently to timer pacing; processing this completion
		 * as well would double-elapse and double-submit one period.
		 */
		if (!cancel_delayed_work(&prtd->write_watchdog)) {
			WRITE_ONCE(prtd->write_fallback, true);
			break;
		}
		prtd->pcm_irq_pos += prtd->pcm_count;
		snd_pcm_period_elapsed(substream);
		if (prtd->state == Q6ASM_STREAM_RUNNING) {
			prtd->n_submitted++;
			/* Arm before submit so an immediate completion can claim it. */
			mod_delayed_work(system_wq, &prtd->write_watchdog,
					 max_t(unsigned long, 1,
					       prtd->period_jiffies * 2));
			q6asm_write_async(prtd->audio_client, prtd->stream_id,
					   prtd->pcm_count, 0, 0, 0);
		}

		break;
		}
	case ASM_CLIENT_EVENT_DATA_READ_DONE:
		prtd->n_write_done++;	/* SPX: real DSP progress, capture side */
		prtd->pcm_irq_pos += prtd->pcm_count;
		snd_pcm_period_elapsed(substream);
		if (prtd->state == Q6ASM_STREAM_RUNNING)
			q6asm_read(prtd->audio_client, prtd->stream_id);

		break;
	default:
		break;
	}
}

static void event_handler(uint32_t opcode, uint32_t token,
			  void *payload, void *priv)
{
	struct q6asm_dai_rtd *prtd = priv;
	struct snd_pcm_substream *substream = prtd->substream;

	if (prtd->spx_legacy) {
		spx_event_handler(opcode, token, payload, priv);
		return;
	}

	switch (opcode) {
	case ASM_CLIENT_EVENT_CMD_RUN_DONE:
		break;
	case ASM_CLIENT_EVENT_CMD_EOS_DONE:
		break;
	case ASM_CLIENT_EVENT_DATA_WRITE_DONE:
		snd_pcm_period_elapsed(substream);
		break;
	case ASM_CLIENT_EVENT_DATA_READ_DONE:
		snd_pcm_period_elapsed(substream);
		if (prtd->state == Q6ASM_STREAM_RUNNING)
			q6asm_read(prtd->audio_client, prtd->stream_id);

		break;
	default:
		break;
	}
}

static int q6asm_dai_prepare(struct snd_soc_component *component,
			     struct snd_pcm_substream *substream)
{
	struct snd_pcm_runtime *runtime = substream->runtime;
	struct snd_soc_pcm_runtime *soc_prtd = snd_soc_substream_to_rtd(substream);
	struct q6asm_dai_rtd *prtd = runtime->private_data;
	struct q6asm_dai_data *pdata;
	struct device *dev = component->dev;
	int ret, i;

	pdata = snd_soc_component_get_drvdata(component);
	if (!pdata)
		return -EINVAL;

	if (!prtd || !prtd->audio_client) {
		dev_err(dev, "%s: private data null or audio client freed\n",
			__func__);
		return -EINVAL;
	}

	prtd->pcm_count = snd_pcm_lib_period_bytes(substream);
	prtd->pcm_irq_pos = 0;
	prtd->write_fallback = false;
	prtd->n_write_done = 0;
	prtd->n_fallback = 0;
	prtd->n_submitted = 0;
	/*
	 * Derive the deadline from ALSA frames, not significant sample bits.
	 * S24_LE occupies a 32-bit container, so bits_per_sample / 8 would make
	 * its watchdog period 4/3 too long even though the PCM buffer size is
	 * correct.
	 */
	prtd->period_jiffies = DIV_ROUND_UP(
		(unsigned long)bytes_to_frames(runtime, prtd->pcm_count) * HZ,
		runtime->rate);
	if (spx_period_adjust_ms) {
		long adjusted = (long)prtd->period_jiffies +
			DIV_ROUND_CLOSEST((long)spx_period_adjust_ms * HZ, 1000);

		prtd->period_jiffies = max_t(long, 1, adjusted);
	}
	/* rate and channels are sent to audio driver */
	if (prtd->state == Q6ASM_STREAM_RUNNING) {
		/* clear the previous setup if any  */
		ret = q6asm_cmd(prtd->audio_client, prtd->stream_id, CMD_CLOSE);
		if (ret < 0) {
			dev_err(dev, "Failed to close q6asm stream %d\n", prtd->stream_id);
			return ret;
		}

		ret = q6asm_unmap_memory_regions(substream->stream, prtd->audio_client);
		if (ret < 0) {
			dev_err(dev, "Failed to unmap memory regions for q6asm stream %d\n",
				prtd->stream_id);
			return ret;
		}

		q6routing_stream_close(soc_prtd->dai_link->id,
					 substream->stream);
		prtd->state = Q6ASM_STREAM_STOPPED;
	}

	/*
	 * SPX: a reused (parked) client already has the DSP session open, its
	 * memory mapped, and its format set. Re-issuing map/open would collide on
	 * the still-live session (the ADSP never ACKed the CLOSE that parked it)
	 * and make the DSP consume nothing. Skip the ASM (re)setup for it.
	 */
	if (!prtd->client_reused) {
		ret = q6asm_map_memory_regions(substream->stream,
					       prtd->audio_client, prtd->phys,
					       (prtd->pcm_size / prtd->periods),
					       prtd->periods);

		if (ret < 0) {
			dev_err(dev, "Audio Start: Buffer Allocation failed rc = %d\n",
								ret);
			return -ENOMEM;
		}

		if (substream->stream == SNDRV_PCM_STREAM_PLAYBACK) {
			ret = q6asm_open_write(prtd->audio_client, prtd->stream_id,
					       FORMAT_LINEAR_PCM,
					       0, prtd->bits_per_sample, false);
		} else if (substream->stream == SNDRV_PCM_STREAM_CAPTURE) {
			ret = q6asm_open_read(prtd->audio_client, prtd->stream_id,
					      FORMAT_LINEAR_PCM,
					      prtd->bits_per_sample);
		}

		if (ret < 0) {
			dev_err(dev, "%s: q6asm_open_write failed\n", __func__);
			goto open_err;
		}
	}

	prtd->session_id = q6asm_get_session_id(prtd->audio_client);
	ret = q6routing_stream_open(soc_prtd->dai_link->id, LEGACY_PCM_MODE,
			      prtd->session_id, substream->stream);
	if (ret) {
		dev_err(dev, "%s: stream reg failed ret:%d\n", __func__, ret);
		goto routing_err;
	}

	if (prtd->client_reused) {
		/* The parked session keeps its prior media format. */
		ret = 0;
		/* A reused capture session still needs its read buffers queued. */
		if (substream->stream == SNDRV_PCM_STREAM_CAPTURE)
			for (i = 0; i < runtime->periods; i++)
				q6asm_read(prtd->audio_client, prtd->stream_id);
	} else if (substream->stream == SNDRV_PCM_STREAM_PLAYBACK) {
		ret = q6asm_media_format_block_multi_ch_pcm(
				prtd->audio_client, prtd->stream_id,
				runtime->rate, runtime->channels, NULL,
				prtd->bits_per_sample);
	} else if (substream->stream == SNDRV_PCM_STREAM_CAPTURE) {
		ret = q6asm_enc_cfg_blk_pcm_format_support(prtd->audio_client,
							   prtd->stream_id,
							   runtime->rate,
							   runtime->channels,
							   prtd->bits_per_sample);

		/* Queue the buffers */
		for (i = 0; i < runtime->periods; i++)
			q6asm_read(prtd->audio_client, prtd->stream_id);

	}
	if (ret < 0)
		dev_info(dev, "%s: CMD Format block failed\n", __func__);
	else
		prtd->state = Q6ASM_STREAM_RUNNING;

	return ret;

routing_err:
	q6asm_cmd(prtd->audio_client, prtd->stream_id,  CMD_CLOSE);
open_err:
	q6asm_unmap_memory_regions(substream->stream, prtd->audio_client);

	return ret;
}

static int q6asm_dai_ack(struct snd_soc_component *component, struct snd_pcm_substream *substream)
{
	struct snd_pcm_runtime *runtime = substream->runtime;
	struct q6asm_dai_rtd *prtd = runtime->private_data;
	int i, ret = 0, avail_periods;

	if (prtd->spx_legacy)
		return 0;

	if (substream->stream == SNDRV_PCM_STREAM_PLAYBACK && prtd->state == Q6ASM_STREAM_RUNNING) {
		avail_periods = (runtime->control->appl_ptr - prtd->queue_ptr)/runtime->period_size;
		for (i = 0; i < avail_periods; i++) {
			ret = q6asm_write_async(prtd->audio_client, prtd->stream_id,
					   prtd->pcm_count, 0, 0, 0);

			if (ret < 0) {
				dev_err(component->dev, "Error queuing playback buffer %d\n", ret);
				return ret;
			}
			prtd->queue_ptr += runtime->period_size;
		}
	}

	return ret;
}

static int q6asm_dai_trigger(struct snd_soc_component *component,
			     struct snd_pcm_substream *substream, int cmd)
{
	int ret = 0;
	struct snd_pcm_runtime *runtime = substream->runtime;
	struct q6asm_dai_rtd *prtd = runtime->private_data;

	switch (cmd) {
	case SNDRV_PCM_TRIGGER_START:
	case SNDRV_PCM_TRIGGER_RESUME:
	case SNDRV_PCM_TRIGGER_PAUSE_RELEASE:
		ret = q6asm_run_nowait(prtd->audio_client, prtd->stream_id,
				       0, 0, 0);
		break;
	case SNDRV_PCM_TRIGGER_STOP:
		if (prtd->spx_legacy) {
			prtd->state = Q6ASM_STREAM_STOPPED;
			cancel_delayed_work(&prtd->write_watchdog);
		}
		ret = q6asm_cmd_nowait(prtd->audio_client, prtd->stream_id,
				       CMD_EOS);
		break;
	case SNDRV_PCM_TRIGGER_SUSPEND:
	case SNDRV_PCM_TRIGGER_PAUSE_PUSH:
		ret = q6asm_cmd_nowait(prtd->audio_client, prtd->stream_id,
				       CMD_PAUSE);
		break;
	default:
		ret = -EINVAL;
		break;
	}

	return ret;
}

static int q6asm_dai_open(struct snd_soc_component *component,
			  struct snd_pcm_substream *substream)
{
	struct snd_pcm_runtime *runtime = substream->runtime;
	struct snd_soc_pcm_runtime *soc_prtd = snd_soc_substream_to_rtd(substream);
	struct snd_soc_dai *cpu_dai = snd_soc_rtd_to_cpu(soc_prtd, 0);
	struct q6asm_dai_rtd *prtd;
	struct q6asm_dai_data *pdata;
	struct device *dev = component->dev;
	int ret = 0;
	int stream_id;

	stream_id = cpu_dai->driver->id;

	pdata = snd_soc_component_get_drvdata(component);
	if (!pdata) {
		dev_err(dev, "Drv data not found ..\n");
		return -EINVAL;
	}

	prtd = kzalloc_obj(*prtd);
	if (prtd == NULL)
		return -ENOMEM;

	prtd->substream = substream;
	INIT_DELAYED_WORK(&prtd->write_watchdog, q6asm_write_watchdog);
	/*
	 * SPX: the ADSP never ACKs ASM_STREAM_CMD_CLOSE, so the previous stream's
	 * audio client was parked in pdata->parked[] instead of freed. Reuse it so
	 * the DSP keeps consuming the same mapped session instead of colliding on
	 * a fresh one (write_done=0). The FE DAI id (stream_id) indexes the slot.
	 */
	if (spx_keep_asm &&
	    of_machine_is_compatible("microsoft,surface-pro-x") &&
	    stream_id < ARRAY_SIZE(pdata->parked[0]) &&
	    pdata->parked[substream->stream][stream_id]) {
		prtd->audio_client = pdata->parked[substream->stream][stream_id];
		pdata->parked[substream->stream][stream_id] = NULL;
		prtd->client_reused = true;
		q6asm_audio_client_rebind(prtd->audio_client,
					  (q6asm_cb)event_handler, prtd);
		dev_info(dev, "SPX: reusing parked ASM %s session for DAI %d\n",
			 substream->stream == SNDRV_PCM_STREAM_PLAYBACK ?
			 "playback" : "capture", stream_id);
	} else {
		prtd->audio_client = q6asm_audio_client_alloc(dev,
					(q6asm_cb)event_handler, prtd, stream_id,
					LEGACY_PCM_MODE);
		if (IS_ERR(prtd->audio_client)) {
			dev_info(dev, "%s: Could not allocate memory\n", __func__);
			ret = PTR_ERR(prtd->audio_client);
			kfree(prtd);
			return ret;
		}
	}

	/* DSP expects stream id from 1 */
	prtd->stream_id = 1;

	if (substream->stream == SNDRV_PCM_STREAM_PLAYBACK)
		runtime->hw = q6asm_dai_hardware_playback;
	else if (substream->stream == SNDRV_PCM_STREAM_CAPTURE)
		runtime->hw = q6asm_dai_hardware_capture;

	/* Ensure that buffer size is a multiple of period size */
	ret = snd_pcm_hw_constraint_integer(runtime,
					    SNDRV_PCM_HW_PARAM_PERIODS);
	if (ret < 0)
		dev_info(dev, "snd_pcm_hw_constraint_integer failed\n");

	if (substream->stream == SNDRV_PCM_STREAM_PLAYBACK) {
		ret = snd_pcm_hw_constraint_minmax(runtime,
			SNDRV_PCM_HW_PARAM_BUFFER_BYTES,
			PLAYBACK_MIN_NUM_PERIODS * PLAYBACK_MIN_PERIOD_SIZE,
			PLAYBACK_MAX_NUM_PERIODS * PLAYBACK_MAX_PERIOD_SIZE);
		if (ret < 0) {
			dev_err(dev, "constraint for buffer bytes min max ret = %d\n",
				ret);
		}
	}

	ret = snd_pcm_hw_constraint_step(runtime, 0,
		SNDRV_PCM_HW_PARAM_PERIOD_SIZE, 480);
	if (ret < 0) {
		dev_err(dev, "constraint for period bytes step ret = %d\n",
								ret);
	}
	ret = snd_pcm_hw_constraint_step(runtime, 0,
		SNDRV_PCM_HW_PARAM_BUFFER_SIZE, 480);
	if (ret < 0) {
		dev_err(dev, "constraint for buffer bytes step ret = %d\n",
								ret);
	}

	prtd->spx_legacy = of_machine_is_compatible("microsoft,surface-pro-x");
	runtime->private_data = prtd;

	if (substream->stream == SNDRV_PCM_STREAM_PLAYBACK) {
		snd_soc_set_runtime_hwparams(substream, &q6asm_dai_hardware_playback);
		runtime->dma_bytes = q6asm_dai_hardware_playback.buffer_bytes_max;
	} else {
		snd_soc_set_runtime_hwparams(substream, &q6asm_dai_hardware_capture);
		runtime->dma_bytes = q6asm_dai_hardware_capture.buffer_bytes_max;
	}


	return 0;
}

static int q6asm_dai_close(struct snd_soc_component *component,
			   struct snd_pcm_substream *substream)
{
	struct snd_pcm_runtime *runtime = substream->runtime;
	struct snd_soc_pcm_runtime *soc_prtd = snd_soc_substream_to_rtd(substream);
	struct snd_soc_dai *cpu_dai = snd_soc_rtd_to_cpu(soc_prtd, 0);
	struct q6asm_dai_data *pdata = snd_soc_component_get_drvdata(component);
	struct q6asm_dai_rtd *prtd = runtime->private_data;
	int fe_dai = cpu_dai->driver->id;

	cancel_delayed_work_sync(&prtd->write_watchdog);

	/*
	 * SPX: n_write_done == 0 means the ADSP never reported consuming a
	 * single buffer, so every period ALSA saw was manufactured by the
	 * fallback worker. In that case the stream was never rendered and no
	 * downstream (SoundWire/PA/transport) result from it is meaningful.
	 */
	dev_info(component->dev,
		 "SPX ASM stream %u: bits=%u submitted=%u write_done=%u fallback=%u%s\n",
		 prtd->stream_id, prtd->bits_per_sample, prtd->n_submitted,
		 prtd->n_write_done, prtd->n_fallback,
		 prtd->n_write_done ? "" : "  <-- DSP CONSUMED NOTHING");

	/*
	 * SPX: the ADSP never ACKs ASM_STREAM_CMD_CLOSE, so issuing it here
	 * (a 5 s timeout) and freeing the client leaks DSP-side session state;
	 * the next stream then collides on a fresh session and the DSP consumes
	 * nothing. Park the still-open client in the per-DAI slot and reuse it on
	 * the next open. Detach the callback first so a late WRITE_DONE event on
	 * the parked session cannot dereference the prtd we are about to free.
	 */
	if (spx_keep_asm &&
	    of_machine_is_compatible("microsoft,surface-pro-x") &&
	    prtd->state && prtd->audio_client &&
	    fe_dai < ARRAY_SIZE(pdata->parked[0])) {
		q6asm_audio_client_rebind(prtd->audio_client, NULL, NULL);
		pdata->parked[substream->stream][fe_dai] = prtd->audio_client;
		prtd->audio_client = NULL;
		dev_info(component->dev,
			 "SPX: parking ASM %s session for DAI %d across close\n",
			 substream->stream == SNDRV_PCM_STREAM_PLAYBACK ?
			 "playback" : "capture", fe_dai);
	} else if (prtd->audio_client) {
		if (prtd->state == Q6ASM_STREAM_RUNNING) {
			q6asm_cmd(prtd->audio_client, prtd->stream_id,
				  CMD_CLOSE);
			q6asm_unmap_memory_regions(substream->stream,
					   prtd->audio_client);
		}
		q6asm_audio_client_free(prtd->audio_client);
		prtd->audio_client = NULL;
	}
	if (prtd->alias_iova) {
		spx_alias_unmap(component->dev, prtd->alias_iova, prtd->alias_sz);
		prtd->alias_iova = 0;
	}
	q6routing_stream_close(soc_prtd->dai_link->id,
						substream->stream);
	kfree(prtd);
	return 0;
}

static snd_pcm_uframes_t q6asm_dai_pointer(struct snd_soc_component *component,
					   struct snd_pcm_substream *substream)
{

	struct snd_pcm_runtime *runtime = substream->runtime;
	struct q6asm_dai_rtd *prtd = runtime->private_data;
	snd_pcm_uframes_t ptr;

	if (prtd->spx_legacy)
		return bytes_to_frames(runtime, prtd->pcm_irq_pos % prtd->pcm_size);

	ptr = q6asm_get_hw_pointer(prtd->audio_client, substream->stream) * runtime->period_size;
	if (ptr)
		return ptr - 1;

	return 0;
}

static int q6asm_dai_hw_params(struct snd_soc_component *component,
			       struct snd_pcm_substream *substream,
			       struct snd_pcm_hw_params *params)
{
	struct snd_pcm_runtime *runtime = substream->runtime;
	struct q6asm_dai_rtd *prtd = runtime->private_data;
	struct q6asm_dai_data *pdata = snd_soc_component_get_drvdata(component);
	struct snd_dma_buffer *buf = runtime->dma_buffer_p;

	prtd->pcm_size = params_buffer_bytes(params);
	prtd->periods = params_periods(params);

	if (!buf)
		return -ENOMEM;

	prtd->phys = spx_map_addr(pdata, buf->addr);

	/* SPX: alias-map the buffer at the high-window IOVA the ADSP accesses. */
	if (prtd->alias_iova) {
		spx_alias_unmap(component->dev, prtd->alias_iova, prtd->alias_sz);
		prtd->alias_iova = 0;
	}
	if (prtd->phys != buf->addr) {
		int rc = spx_alias_map(component->dev, buf->addr, prtd->phys,
				       buf->bytes);

		if (rc) {
			dev_warn(component->dev,
				 "SPX: high-IOVA alias map failed: %d\n", rc);
		} else {
			prtd->alias_iova = prtd->phys;
			prtd->alias_sz = buf->bytes;
		}
	}

	switch (params_format(params)) {
	case SNDRV_PCM_FORMAT_S16_LE:
		prtd->bits_per_sample = 16;
		break;
	case SNDRV_PCM_FORMAT_S24_LE:
		prtd->bits_per_sample = 24;
		break;
	}

	return 0;
}

static void compress_event_handler(uint32_t opcode, uint32_t token,
				   void *payload, void *priv)
{
	struct q6asm_dai_rtd *prtd = priv;
	struct snd_compr_stream *substream = prtd->cstream;
	u32 wflags = 0;
	uint64_t avail;
	uint32_t bytes_written, bytes_to_write;
	bool is_last_buffer = false;

	guard(spinlock_irqsave)(&prtd->lock);

	switch (opcode) {
	case ASM_CLIENT_EVENT_CMD_RUN_DONE:
		if (!prtd->bytes_sent) {
			q6asm_stream_remove_initial_silence(prtd->audio_client,
						    prtd->stream_id,
						    prtd->initial_samples_drop);

			q6asm_write_async(prtd->audio_client, prtd->stream_id,
					  prtd->pcm_count, 0, 0, 0);
			prtd->bytes_sent += prtd->pcm_count;
		}

		break;

	case ASM_CLIENT_EVENT_CMD_EOS_DONE:
		if (prtd->notify_on_drain) {
			if (substream->partial_drain) {
				/*
				 * Close old stream and make it stale, switch
				 * the active stream now!
				 */
				q6asm_cmd_nowait(prtd->audio_client,
						 prtd->stream_id,
						 CMD_CLOSE);
				/*
				 * vaild stream ids start from 1, So we are
				 * toggling this between 1 and 2.
				 */
				prtd->stream_id = (prtd->stream_id == 1 ? 2 : 1);
			}

			snd_compr_drain_notify(prtd->cstream);
			prtd->notify_on_drain = false;

		}
		break;

	case ASM_CLIENT_EVENT_DATA_WRITE_DONE:

		bytes_written = token >> ASM_WRITE_TOKEN_LEN_SHIFT;
		prtd->copied_total += bytes_written;
		snd_compr_fragment_elapsed(substream);

		if (prtd->state != Q6ASM_STREAM_RUNNING)
			break;

		avail = prtd->bytes_received - prtd->bytes_sent;
		if (avail > prtd->pcm_count) {
			bytes_to_write = prtd->pcm_count;
		} else {
			if (substream->partial_drain || prtd->notify_on_drain)
				is_last_buffer = true;
			bytes_to_write = avail;
		}

		if (bytes_to_write) {
			if (substream->partial_drain && is_last_buffer) {
				wflags |= ASM_LAST_BUFFER_FLAG;
				q6asm_stream_remove_trailing_silence(prtd->audio_client,
						     prtd->stream_id,
						     prtd->trailing_samples_drop);
			}

			q6asm_write_async(prtd->audio_client, prtd->stream_id,
					  bytes_to_write, 0, 0, wflags);

			prtd->bytes_sent += bytes_to_write;
		}

		if (prtd->notify_on_drain && is_last_buffer)
			q6asm_cmd_nowait(prtd->audio_client,
					 prtd->stream_id, CMD_EOS);

		break;

	default:
		break;
	}
}

static int q6asm_dai_compr_open(struct snd_soc_component *component,
				struct snd_compr_stream *stream)
{
	struct snd_soc_pcm_runtime *rtd = stream->private_data;
	struct snd_compr_runtime *runtime = stream->runtime;
	struct snd_soc_dai *cpu_dai = snd_soc_rtd_to_cpu(rtd, 0);
	struct q6asm_dai_data *pdata;
	struct device *dev = component->dev;
	struct q6asm_dai_rtd *prtd;
	int stream_id, size, ret;

	stream_id = cpu_dai->driver->id;
	pdata = snd_soc_component_get_drvdata(component);
	if (!pdata) {
		dev_err(dev, "Drv data not found ..\n");
		return -EINVAL;
	}

	prtd = kzalloc_obj(*prtd);
	if (!prtd)
		return -ENOMEM;

	/* DSP expects stream id from 1 */
	prtd->stream_id = 1;

	prtd->cstream = stream;
	prtd->audio_client = q6asm_audio_client_alloc(dev,
					(q6asm_cb)compress_event_handler,
					prtd, stream_id, LEGACY_PCM_MODE);
	if (IS_ERR(prtd->audio_client)) {
		dev_err(dev, "Could not allocate memory\n");
		ret = PTR_ERR(prtd->audio_client);
		goto free_prtd;
	}

	size = COMPR_PLAYBACK_MAX_FRAGMENT_SIZE *
			COMPR_PLAYBACK_MAX_NUM_FRAGMENTS;
	ret = snd_dma_alloc_pages(SNDRV_DMA_TYPE_DEV, dev, size,
				  &prtd->dma_buffer);
	if (ret) {
		dev_err(dev, "Cannot allocate buffer(s)\n");
		goto free_client;
	}

	prtd->phys = spx_map_addr(pdata, prtd->dma_buffer.addr);

	snd_compr_set_runtime_buffer(stream, &prtd->dma_buffer);
	spin_lock_init(&prtd->lock);
	prtd->spx_legacy = of_machine_is_compatible("microsoft,surface-pro-x");
	runtime->private_data = prtd;

	return 0;

free_client:
	q6asm_audio_client_free(prtd->audio_client);
free_prtd:
	kfree(prtd);

	return ret;
}

static int q6asm_dai_compr_free(struct snd_soc_component *component,
				struct snd_compr_stream *stream)
{
	struct snd_compr_runtime *runtime = stream->runtime;
	struct q6asm_dai_rtd *prtd = runtime->private_data;
	struct snd_soc_pcm_runtime *rtd = stream->private_data;

	if (prtd->audio_client) {
		if (prtd->state == Q6ASM_STREAM_RUNNING) {
			q6asm_cmd(prtd->audio_client, prtd->stream_id,
				  CMD_CLOSE);
			if (prtd->next_track_stream_id) {
				q6asm_cmd(prtd->audio_client,
					  prtd->next_track_stream_id,
					  CMD_CLOSE);
			}

			q6asm_unmap_memory_regions(stream->direction,
					   prtd->audio_client);
		}
		snd_dma_free_pages(&prtd->dma_buffer);
		q6asm_audio_client_free(prtd->audio_client);
		prtd->audio_client = NULL;
	}
	q6routing_stream_close(rtd->dai_link->id, stream->direction);
	kfree(prtd);

	return 0;
}

static int __q6asm_dai_compr_set_codec_params(struct snd_soc_component *component,
					      struct snd_compr_stream *stream,
					      struct snd_codec *codec,
					      int stream_id)
{
	struct snd_compr_runtime *runtime = stream->runtime;
	struct q6asm_dai_rtd *prtd = runtime->private_data;
	struct q6asm_flac_cfg flac_cfg;
	struct q6asm_wma_cfg wma_cfg;
	struct q6asm_alac_cfg alac_cfg;
	struct q6asm_ape_cfg ape_cfg;
	unsigned int wma_v9 = 0;
	struct device *dev = component->dev;
	int ret;
	union snd_codec_options *codec_options;
	struct snd_dec_flac *flac;
	struct snd_dec_wma *wma;
	struct snd_dec_alac *alac;
	struct snd_dec_ape *ape;

	codec_options = &(prtd->codec.options);

	memcpy(&prtd->codec, codec, sizeof(*codec));

	switch (codec->id) {
	case SND_AUDIOCODEC_FLAC:

		memset(&flac_cfg, 0x0, sizeof(struct q6asm_flac_cfg));
		flac = &codec_options->flac_d;

		flac_cfg.ch_cfg = codec->ch_in;
		flac_cfg.sample_rate = codec->sample_rate;
		flac_cfg.stream_info_present = 1;
		flac_cfg.sample_size = flac->sample_size;
		flac_cfg.min_blk_size = flac->min_blk_size;
		flac_cfg.max_blk_size = flac->max_blk_size;
		flac_cfg.max_frame_size = flac->max_frame_size;
		flac_cfg.min_frame_size = flac->min_frame_size;

		ret = q6asm_stream_media_format_block_flac(prtd->audio_client,
							   stream_id,
							   &flac_cfg);
		if (ret < 0) {
			dev_err(dev, "FLAC CMD Format block failed:%d\n", ret);
			return -EIO;
		}
		break;

	case SND_AUDIOCODEC_WMA:
		wma = &codec_options->wma_d;

		memset(&wma_cfg, 0x0, sizeof(struct q6asm_wma_cfg));

		wma_cfg.sample_rate =  codec->sample_rate;
		wma_cfg.num_channels = codec->ch_in;
		wma_cfg.bytes_per_sec = codec->bit_rate / 8;
		wma_cfg.block_align = codec->align;
		wma_cfg.bits_per_sample = prtd->bits_per_sample;
		wma_cfg.enc_options = wma->encoder_option;
		wma_cfg.adv_enc_options = wma->adv_encoder_option;
		wma_cfg.adv_enc_options2 = wma->adv_encoder_option2;

		if (wma_cfg.num_channels == 1)
			wma_cfg.channel_mask = 4; /* Mono Center */
		else if (wma_cfg.num_channels == 2)
			wma_cfg.channel_mask = 3; /* Stereo FL/FR */
		else
			return -EINVAL;

		/* check the codec profile */
		switch (codec->profile) {
		case SND_AUDIOPROFILE_WMA9:
			wma_cfg.fmtag = 0x161;
			wma_v9 = 1;
			break;

		case SND_AUDIOPROFILE_WMA10:
			wma_cfg.fmtag = 0x166;
			break;

		case SND_AUDIOPROFILE_WMA9_PRO:
			wma_cfg.fmtag = 0x162;
			break;

		case SND_AUDIOPROFILE_WMA9_LOSSLESS:
			wma_cfg.fmtag = 0x163;
			break;

		case SND_AUDIOPROFILE_WMA10_LOSSLESS:
			wma_cfg.fmtag = 0x167;
			break;

		default:
			dev_err(dev, "Unknown WMA profile:%x\n",
				codec->profile);
			return -EIO;
		}

		if (wma_v9)
			ret = q6asm_stream_media_format_block_wma_v9(
					prtd->audio_client, stream_id,
					&wma_cfg);
		else
			ret = q6asm_stream_media_format_block_wma_v10(
					prtd->audio_client, stream_id,
					&wma_cfg);
		if (ret < 0) {
			dev_err(dev, "WMA9 CMD failed:%d\n", ret);
			return -EIO;
		}
		break;

	case SND_AUDIOCODEC_ALAC:
		memset(&alac_cfg, 0x0, sizeof(alac_cfg));
		alac = &codec_options->alac_d;

		alac_cfg.sample_rate = codec->sample_rate;
		alac_cfg.avg_bit_rate = codec->bit_rate;
		alac_cfg.bit_depth = prtd->bits_per_sample;
		alac_cfg.num_channels = codec->ch_in;

		alac_cfg.frame_length = alac->frame_length;
		alac_cfg.pb = alac->pb;
		alac_cfg.mb = alac->mb;
		alac_cfg.kb = alac->kb;
		alac_cfg.max_run = alac->max_run;
		alac_cfg.compatible_version = alac->compatible_version;
		alac_cfg.max_frame_bytes = alac->max_frame_bytes;

		switch (codec->ch_in) {
		case 1:
			alac_cfg.channel_layout_tag = ALAC_CH_LAYOUT_MONO;
			break;
		case 2:
			alac_cfg.channel_layout_tag = ALAC_CH_LAYOUT_STEREO;
			break;
		}
		ret = q6asm_stream_media_format_block_alac(prtd->audio_client,
							   stream_id,
							   &alac_cfg);
		if (ret < 0) {
			dev_err(dev, "ALAC CMD Format block failed:%d\n", ret);
			return -EIO;
		}
		break;

	case SND_AUDIOCODEC_APE:
		memset(&ape_cfg, 0x0, sizeof(ape_cfg));
		ape = &codec_options->ape_d;

		ape_cfg.sample_rate = codec->sample_rate;
		ape_cfg.num_channels = codec->ch_in;
		ape_cfg.bits_per_sample = prtd->bits_per_sample;

		ape_cfg.compatible_version = ape->compatible_version;
		ape_cfg.compression_level = ape->compression_level;
		ape_cfg.format_flags = ape->format_flags;
		ape_cfg.blocks_per_frame = ape->blocks_per_frame;
		ape_cfg.final_frame_blocks = ape->final_frame_blocks;
		ape_cfg.total_frames = ape->total_frames;
		ape_cfg.seek_table_present = ape->seek_table_present;

		ret = q6asm_stream_media_format_block_ape(prtd->audio_client,
							  stream_id,
							  &ape_cfg);
		if (ret < 0) {
			dev_err(dev, "APE CMD Format block failed:%d\n", ret);
			return -EIO;
		}
		break;

	default:
		break;
	}

	return 0;
}

static int q6asm_dai_compr_set_params(struct snd_soc_component *component,
				      struct snd_compr_stream *stream,
				      struct snd_compr_params *params)
{
	struct snd_compr_runtime *runtime = stream->runtime;
	struct q6asm_dai_rtd *prtd = runtime->private_data;
	struct snd_soc_pcm_runtime *rtd = stream->private_data;
	int dir = stream->direction;
	struct q6asm_dai_data *pdata;
	struct device *dev = component->dev;
	int ret;

	pdata = snd_soc_component_get_drvdata(component);
	if (!pdata)
		return -EINVAL;

	if (!prtd || !prtd->audio_client) {
		dev_err(dev, "private data null or audio client freed\n");
		return -EINVAL;
	}

	prtd->periods = runtime->fragments;
	prtd->pcm_count = runtime->fragment_size;
	prtd->pcm_size = runtime->fragments * runtime->fragment_size;
	prtd->bits_per_sample = 16;

	if (dir == SND_COMPRESS_PLAYBACK) {
		ret = q6asm_open_write(prtd->audio_client, prtd->stream_id, params->codec.id,
				params->codec.profile, prtd->bits_per_sample,
				true);

		if (ret < 0) {
			dev_err(dev, "q6asm_open_write failed\n");
			goto open_err;
		}
	}

	prtd->session_id = q6asm_get_session_id(prtd->audio_client);
	ret = q6routing_stream_open(rtd->dai_link->id, LEGACY_PCM_MODE,
			      prtd->session_id, dir);
	if (ret) {
		dev_err(dev, "Stream reg failed ret:%d\n", ret);
		goto routing_err;
	}

	ret = __q6asm_dai_compr_set_codec_params(component, stream,
						 &params->codec,
						 prtd->stream_id);
	if (ret) {
		dev_err(dev, "codec param setup failed ret:%d\n", ret);
		goto q6_err;
	}

	ret = q6asm_map_memory_regions(dir, prtd->audio_client, prtd->phys,
				       (prtd->pcm_size / prtd->periods),
				       prtd->periods);

	if (ret < 0) {
		dev_err(dev, "Buffer Mapping failed ret:%d\n", ret);
		ret = -ENOMEM;
		goto q6_err;
	}

	prtd->state = Q6ASM_STREAM_RUNNING;

	return 0;

q6_err:
	q6routing_stream_close(rtd->dai_link->id, dir);
routing_err:
	q6asm_cmd(prtd->audio_client, prtd->stream_id, CMD_CLOSE);

open_err:
	return ret;
}

static int q6asm_dai_compr_set_metadata(struct snd_soc_component *component,
					struct snd_compr_stream *stream,
					struct snd_compr_metadata *metadata)
{
	struct snd_compr_runtime *runtime = stream->runtime;
	struct q6asm_dai_rtd *prtd = runtime->private_data;
	int ret = 0;

	switch (metadata->key) {
	case SNDRV_COMPRESS_ENCODER_PADDING:
		prtd->trailing_samples_drop = metadata->value[0];
		break;
	case SNDRV_COMPRESS_ENCODER_DELAY:
		prtd->initial_samples_drop = metadata->value[0];
		if (prtd->next_track_stream_id) {
			ret = q6asm_open_write(prtd->audio_client,
					       prtd->next_track_stream_id,
					       prtd->codec.id,
					       prtd->codec.profile,
					       prtd->bits_per_sample,
				       true);
			if (ret < 0) {
				dev_err(component->dev, "q6asm_open_write failed\n");
				return ret;
			}
			ret = __q6asm_dai_compr_set_codec_params(component, stream,
								 &prtd->codec,
								 prtd->next_track_stream_id);
			if (ret < 0) {
				dev_err(component->dev, "q6asm_open_write failed\n");
				return ret;
			}

			ret = q6asm_stream_remove_initial_silence(prtd->audio_client,
						    prtd->next_track_stream_id,
						    prtd->initial_samples_drop);
			prtd->next_track_stream_id = 0;

		}

		break;
	default:
		ret = -EINVAL;
		break;
	}

	return ret;
}

static int q6asm_dai_compr_trigger(struct snd_soc_component *component,
				   struct snd_compr_stream *stream, int cmd)
{
	struct snd_compr_runtime *runtime = stream->runtime;
	struct q6asm_dai_rtd *prtd = runtime->private_data;
	int ret = 0;

	switch (cmd) {
	case SNDRV_PCM_TRIGGER_START:
	case SNDRV_PCM_TRIGGER_RESUME:
	case SNDRV_PCM_TRIGGER_PAUSE_RELEASE:
		ret = q6asm_run_nowait(prtd->audio_client, prtd->stream_id,
				       0, 0, 0);
		break;
	case SNDRV_PCM_TRIGGER_STOP:
		ret = q6asm_cmd_nowait(prtd->audio_client, prtd->stream_id,
				       CMD_EOS);
		break;
	case SNDRV_PCM_TRIGGER_SUSPEND:
	case SNDRV_PCM_TRIGGER_PAUSE_PUSH:
		ret = q6asm_cmd_nowait(prtd->audio_client, prtd->stream_id,
				       CMD_PAUSE);
		break;
	case SND_COMPR_TRIGGER_NEXT_TRACK:
		prtd->next_track = true;
		prtd->next_track_stream_id = (prtd->stream_id == 1 ? 2 : 1);
		break;
	case SND_COMPR_TRIGGER_DRAIN:
	case SND_COMPR_TRIGGER_PARTIAL_DRAIN:
		prtd->notify_on_drain = true;
		break;
	default:
		ret = -EINVAL;
		break;
	}

	return ret;
}

static int q6asm_dai_compr_pointer(struct snd_soc_component *component,
				   struct snd_compr_stream *stream,
				   struct snd_compr_tstamp64 *tstamp)
{
	struct snd_compr_runtime *runtime = stream->runtime;
	struct q6asm_dai_rtd *prtd = runtime->private_data;
	uint64_t temp_copied_total;

	guard(spinlock_irqsave)(&prtd->lock);

	tstamp->copied_total = prtd->copied_total;
	temp_copied_total = tstamp->copied_total;
	tstamp->byte_offset = do_div(temp_copied_total, prtd->pcm_size);

	return 0;
}

static int q6asm_compr_copy(struct snd_soc_component *component,
			    struct snd_compr_stream *stream, char __user *buf,
			    size_t count)
{
	struct snd_compr_runtime *runtime = stream->runtime;
	struct q6asm_dai_rtd *prtd = runtime->private_data;
	u32 wflags = 0;
	uint64_t avail, bytes_in_flight = 0;
	void *dstn;
	size_t copy;
	u32 app_pointer;
	uint64_t bytes_received;
	uint64_t temp_bytes_received;

	bytes_received = prtd->bytes_received;
	temp_bytes_received = bytes_received;

	/**
	 * Make sure that next track data pointer is aligned at 32 bit boundary
	 * This is a Mandatory requirement from DSP data buffers alignment
	 */
	if (prtd->next_track) {
		bytes_received = ALIGN(prtd->bytes_received, prtd->pcm_count);
		temp_bytes_received = bytes_received;
	}

	app_pointer = do_div(temp_bytes_received, prtd->pcm_size);
	dstn = prtd->dma_buffer.area + app_pointer;

	if (count < prtd->pcm_size - app_pointer) {
		if (copy_from_user(dstn, buf, count))
			return -EFAULT;
	} else {
		copy = prtd->pcm_size - app_pointer;
		if (copy_from_user(dstn, buf, copy))
			return -EFAULT;
		if (copy_from_user(prtd->dma_buffer.area, buf + copy,
				   count - copy))
			return -EFAULT;
	}

	guard(spinlock_irqsave)(&prtd->lock);

	bytes_in_flight = prtd->bytes_received - prtd->copied_total;

	if (prtd->next_track) {
		prtd->next_track = false;
		prtd->copied_total = ALIGN(prtd->copied_total, prtd->pcm_count);
		prtd->bytes_sent = ALIGN(prtd->bytes_sent, prtd->pcm_count);
	}

	prtd->bytes_received = bytes_received + count;

	/* Kick off the data to dsp if its starving!! */
	if (prtd->state == Q6ASM_STREAM_RUNNING && (bytes_in_flight == 0)) {
		uint32_t bytes_to_write = prtd->pcm_count;

		avail = prtd->bytes_received - prtd->bytes_sent;

		if (avail < prtd->pcm_count)
			bytes_to_write = avail;

		q6asm_write_async(prtd->audio_client, prtd->stream_id,
				  bytes_to_write, 0, 0, wflags);
		prtd->bytes_sent += bytes_to_write;
	}

	return count;
}

static int q6asm_dai_compr_mmap(struct snd_soc_component *component,
				struct snd_compr_stream *stream,
				struct vm_area_struct *vma)
{
	struct snd_compr_runtime *runtime = stream->runtime;
	struct q6asm_dai_rtd *prtd = runtime->private_data;
	struct device *dev = component->dev;

	return dma_mmap_coherent(dev, vma,
			prtd->dma_buffer.area, prtd->dma_buffer.addr,
			prtd->dma_buffer.bytes);
}

static int q6asm_dai_compr_get_caps(struct snd_soc_component *component,
				    struct snd_compr_stream *stream,
				    struct snd_compr_caps *caps)
{
	caps->direction = SND_COMPRESS_PLAYBACK;
	caps->min_fragment_size = COMPR_PLAYBACK_MIN_FRAGMENT_SIZE;
	caps->max_fragment_size = COMPR_PLAYBACK_MAX_FRAGMENT_SIZE;
	caps->min_fragments = COMPR_PLAYBACK_MIN_NUM_FRAGMENTS;
	caps->max_fragments = COMPR_PLAYBACK_MAX_NUM_FRAGMENTS;
	caps->num_codecs = 5;
	caps->codecs[0] = SND_AUDIOCODEC_MP3;
	caps->codecs[1] = SND_AUDIOCODEC_FLAC;
	caps->codecs[2] = SND_AUDIOCODEC_WMA;
	caps->codecs[3] = SND_AUDIOCODEC_ALAC;
	caps->codecs[4] = SND_AUDIOCODEC_APE;

	return 0;
}

static int q6asm_dai_compr_get_codec_caps(struct snd_soc_component *component,
					  struct snd_compr_stream *stream,
					  struct snd_compr_codec_caps *codec)
{
	switch (codec->codec) {
	case SND_AUDIOCODEC_MP3:
		*codec = q6asm_compr_caps;
		break;
	default:
		break;
	}

	return 0;
}

static const struct snd_compress_ops q6asm_dai_compress_ops = {
	.open		= q6asm_dai_compr_open,
	.free		= q6asm_dai_compr_free,
	.set_params	= q6asm_dai_compr_set_params,
	.set_metadata	= q6asm_dai_compr_set_metadata,
	.pointer	= q6asm_dai_compr_pointer,
	.trigger	= q6asm_dai_compr_trigger,
	.get_caps	= q6asm_dai_compr_get_caps,
	.get_codec_caps	= q6asm_dai_compr_get_codec_caps,
	.mmap		= q6asm_dai_compr_mmap,
	.copy		= q6asm_compr_copy,
};

static int q6asm_dai_pcm_new(struct snd_soc_component *component,
			     struct snd_soc_pcm_runtime *rtd)
{
	struct snd_pcm *pcm = rtd->pcm;
	size_t size = q6asm_dai_hardware_playback.buffer_bytes_max;

	return snd_pcm_set_fixed_buffer_all(pcm, SNDRV_DMA_TYPE_DEV,
					    component->dev, size);
}

static const struct snd_soc_dapm_widget q6asm_dapm_widgets[] = {
	SND_SOC_DAPM_AIF_IN("MM_DL1", "MultiMedia1 Playback", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_IN("MM_DL2", "MultiMedia2 Playback", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_IN("MM_DL3", "MultiMedia3 Playback", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_IN("MM_DL4", "MultiMedia4 Playback", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_IN("MM_DL5", "MultiMedia5 Playback", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_IN("MM_DL6", "MultiMedia6 Playback", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_IN("MM_DL7", "MultiMedia7 Playback", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_IN("MM_DL8", "MultiMedia8 Playback", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_OUT("MM_UL1", "MultiMedia1 Capture", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_OUT("MM_UL2", "MultiMedia2 Capture", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_OUT("MM_UL3", "MultiMedia3 Capture", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_OUT("MM_UL4", "MultiMedia4 Capture", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_OUT("MM_UL5", "MultiMedia5 Capture", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_OUT("MM_UL6", "MultiMedia6 Capture", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_OUT("MM_UL7", "MultiMedia7 Capture", 0, SND_SOC_NOPM, 0, 0),
	SND_SOC_DAPM_AIF_OUT("MM_UL8", "MultiMedia8 Capture", 0, SND_SOC_NOPM, 0, 0),
};

static const struct snd_soc_component_driver q6asm_fe_dai_component = {
	.name			= DRV_NAME,
	.open			= q6asm_dai_open,
	.hw_params		= q6asm_dai_hw_params,
	.close			= q6asm_dai_close,
	.prepare		= q6asm_dai_prepare,
	.trigger		= q6asm_dai_trigger,
	.ack			= q6asm_dai_ack,
	.pointer		= q6asm_dai_pointer,
	.pcm_new		= q6asm_dai_pcm_new,
	.compress_ops		= &q6asm_dai_compress_ops,
	.dapm_widgets		= q6asm_dapm_widgets,
	.num_dapm_widgets	= ARRAY_SIZE(q6asm_dapm_widgets),
	.legacy_dai_naming	= 1,
};

static struct snd_soc_dai_driver q6asm_fe_dais_template[] = {
	Q6ASM_FEDAI_DRIVER(1),
	Q6ASM_FEDAI_DRIVER(2),
	Q6ASM_FEDAI_DRIVER(3),
	Q6ASM_FEDAI_DRIVER(4),
	Q6ASM_FEDAI_DRIVER(5),
	Q6ASM_FEDAI_DRIVER(6),
	Q6ASM_FEDAI_DRIVER(7),
	Q6ASM_FEDAI_DRIVER(8),
};

static const struct snd_soc_dai_ops q6asm_dai_ops = {
	.compress_new = snd_soc_new_compress,
};

static int of_q6asm_parse_dai_data(struct device *dev,
				    struct q6asm_dai_data *pdata)
{
	struct snd_soc_dai_driver *dai_drv;
	struct snd_soc_pcm_stream empty_stream;
	struct device_node *node;
	int ret, id, dir, idx = 0;


	pdata->num_dais = of_get_child_count(dev->of_node);
	if (!pdata->num_dais) {
		dev_err(dev, "No dais found in DT\n");
		return -EINVAL;
	}

	pdata->dais = devm_kcalloc(dev, pdata->num_dais, sizeof(*dai_drv),
				   GFP_KERNEL);
	if (!pdata->dais)
		return -ENOMEM;

	memset(&empty_stream, 0, sizeof(empty_stream));

	for_each_child_of_node(dev->of_node, node) {
		ret = of_property_read_u32(node, "reg", &id);
		if (ret || id >= MAX_SESSIONS || id < 0) {
			dev_err(dev, "valid dai id not found:%d\n", ret);
			continue;
		}

		dai_drv = &pdata->dais[idx++];
		*dai_drv = q6asm_fe_dais_template[id];

		ret = of_property_read_u32(node, "direction", &dir);
		if (ret)
			continue;

		if (dir == Q6ASM_DAI_RX)
			dai_drv->capture = empty_stream;
		else if (dir == Q6ASM_DAI_TX)
			dai_drv->playback = empty_stream;

		if (of_property_read_bool(node, "is-compress-dai"))
			dai_drv->ops = &q6asm_dai_ops;
	}

	return 0;
}

static int q6asm_dai_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct device_node *node = dev->of_node;
	struct of_phandle_args args;
	struct q6asm_dai_data *pdata;
	int rc;

	pdata = devm_kzalloc(dev, sizeof(*pdata), GFP_KERNEL);
	if (!pdata)
		return -ENOMEM;

	rc = dma_set_mask_and_coherent(dev, DMA_BIT_MASK(32));
	if (rc)
		dev_warn(dev, "Unable to set DMA mask to 32-bit: %d\n", rc);

	rc = of_parse_phandle_with_fixed_args(node, "iommus", 1, 0, &args);
	if (rc < 0)
		pdata->sid = -1;
	else
		pdata->sid = args.args[0] & SID_MASK_DEFAULT;

	dev_set_drvdata(dev, pdata);

	rc = of_q6asm_parse_dai_data(dev, pdata);
	if (rc)
		return rc;

	return devm_snd_soc_register_component(dev, &q6asm_fe_dai_component,
					       pdata->dais, pdata->num_dais);
}

#ifdef CONFIG_OF
static const struct of_device_id q6asm_dai_device_id[] = {
	{ .compatible = "qcom,q6asm-dais" },
	{},
};
MODULE_DEVICE_TABLE(of, q6asm_dai_device_id);
#endif

static struct platform_driver q6asm_dai_platform_driver = {
	.driver = {
		.name = "q6asm-dai",
		.of_match_table = of_match_ptr(q6asm_dai_device_id),
	},
	.probe = q6asm_dai_probe,
};
module_platform_driver(q6asm_dai_platform_driver);

MODULE_DESCRIPTION("Q6ASM dai driver");
MODULE_LICENSE("GPL v2");
