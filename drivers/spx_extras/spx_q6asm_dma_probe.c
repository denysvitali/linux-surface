// SPDX-License-Identifier: GPL-2.0
/* Read-only probe of the ALSA DMA ring immediately before each ASM write. */
#include <linux/atomic.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/ptrace.h>
#include <linux/workqueue.h>
#include <sound/compress_driver.h>
#include <sound/pcm.h>

#define ASM_CLIENT_EVENT_CMD_RUN_DONE 0x1008

struct spx_audio_client_prefix {
	int session;
	void *callback;
	void *priv;
};

static atomic64_t spx_calls = ATOMIC64_INIT(0);
static atomic64_t spx_zero_calls = ATOMIC64_INIT(0);

enum spx_stream_state {
	SPX_STREAM_IDLE = 0,
	SPX_STREAM_STOPPED,
	SPX_STREAM_RUNNING,
};

/* Must track q6asm-dai.c::q6asm_dai_rtd for the live diagnostic override. */
struct spx_q6asm_dai_rtd {
	struct snd_pcm_substream *substream;
	struct snd_compr_stream *cstream;
	struct snd_codec codec;
	struct snd_dma_buffer dma_buffer;
	spinlock_t lock;
	phys_addr_t phys;
	unsigned int pcm_size;
	unsigned int pcm_count;
	unsigned int pcm_irq_pos;
	unsigned int periods;
	u64 bytes_sent;
	u64 bytes_received;
	u64 copied_total;
	u16 bits_per_sample;
	u16 source;
	void *audio_client;
	u32 next_track_stream_id;
	bool next_track;
	u32 stream_id;
	u16 session_id;
	enum spx_stream_state state;
	u32 initial_samples_drop;
	u32 trailing_samples_drop;
	bool notify_on_drain;
	phys_addr_t alias_iova;
	size_t alias_sz;
	struct delayed_work write_watchdog;
	unsigned long period_jiffies;
	bool write_fallback;
};

static unsigned long event_handler_addr;
module_param(event_handler_addr, ulong, 0400);
MODULE_PARM_DESC(event_handler_addr,
	"Live q6asm-dai event_handler address from /proc/kallsyms");

static int spx_q6asm_event_pre(struct kprobe *probe, struct pt_regs *regs)
{
	struct spx_q6asm_dai_rtd *prtd;
	u32 opcode = regs_get_kernel_argument(regs, 0);

	if (opcode != ASM_CLIENT_EVENT_CMD_RUN_DONE)
		return 0;

	prtd = (void *)regs_get_kernel_argument(regs, 3);
	if (!prtd)
		return 0;

	/* Ignore immediate write ACKs from the first submitted period onward. */
	WRITE_ONCE(prtd->write_fallback, true);
	pr_info("spx_q6asm_dma: fallback active at RUN_DONE (offset=%zu)\n",
		offsetof(struct spx_q6asm_dai_rtd, write_fallback));
	return 0;
}

static struct kprobe spx_q6asm_event_probe = {
	.pre_handler = spx_q6asm_event_pre,
};

static int spx_q6asm_write_pre(struct kprobe *probe, struct pt_regs *regs)
{
	struct spx_audio_client_prefix *client;
	struct snd_pcm_substream *substream;
	struct snd_pcm_runtime *runtime;
	unsigned char *area;
	size_t bytes, i;
	u64 call;
	u32 nonzero = 0;
	u32 hash = 2166136261U;

	client = (void *)regs_get_kernel_argument(regs, 0);
	if (!client || !client->priv)
		return 0;

	/* q6asm_dai_rtd::substream is the first member of client->priv. */
	substream = *(struct snd_pcm_substream **)client->priv;
	if (!substream || !substream->runtime)
		return 0;

	runtime = substream->runtime;
	area = READ_ONCE(runtime->dma_area);
	bytes = READ_ONCE(runtime->dma_bytes);
	if (!area || !bytes)
		return 0;

	/* The diagnostic ring is small; scan it without modifying any state. */
	for (i = 0; i < bytes; i++) {
		u8 value = READ_ONCE(area[i]);

		nonzero += value != 0;
		hash = (hash ^ value) * 16777619U;
	}

	call = atomic64_inc_return(&spx_calls);
	if (!nonzero)
		atomic64_inc(&spx_zero_calls);
	if (call <= 16 || !(call % 100))
		pr_info("spx_q6asm_dma: call=%llu session=%d bytes=%zu nonzero=%u hash=%08x\n",
			call, client->session, bytes, nonzero, hash);

	return 0;
}

static struct kprobe spx_q6asm_write_probe = {
	.symbol_name = "q6asm_write_async",
	.pre_handler = spx_q6asm_write_pre,
};

static int __init spx_q6asm_dma_probe_init(void)
{
	int ret;

	if (event_handler_addr) {
		spx_q6asm_event_probe.addr = (void *)event_handler_addr;
		ret = register_kprobe(&spx_q6asm_event_probe);
		if (ret)
			return ret;
	}

	ret = register_kprobe(&spx_q6asm_write_probe);
	if (ret) {
		if (event_handler_addr)
			unregister_kprobe(&spx_q6asm_event_probe);
		return ret;
	}

	pr_info("spx_q6asm_dma: probing writes at %pS, events at %pS\n",
		spx_q6asm_write_probe.addr,
		event_handler_addr ? spx_q6asm_event_probe.addr : NULL);
	return 0;
}

static void __exit spx_q6asm_dma_probe_exit(void)
{
	unregister_kprobe(&spx_q6asm_write_probe);
	if (event_handler_addr)
		unregister_kprobe(&spx_q6asm_event_probe);
	pr_info("spx_q6asm_dma: calls=%lld zero_calls=%lld\n",
		atomic64_read(&spx_calls), atomic64_read(&spx_zero_calls));
}

module_init(spx_q6asm_dma_probe_init);
module_exit(spx_q6asm_dma_probe_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX read-only q6asm ALSA DMA ring probe");
