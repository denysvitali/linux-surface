// SPDX-License-Identifier: GPL-2.0
/*
 * SPX: kprobe tracer for qcom_swrm_cmd_fifo_wr_cmd -- logs every SoundWire
 * write command (value, device, register) so the exact on-wire programming
 * sequence during a stream start/stop can be compared against expectations.
 * No ftrace in this kernel; CONFIG_KPROBES=y is enough for this.
 *
 * insmod spx_wr_trace.ko [max=N]   -- start tracing (caps at N lines)
 * rmmod  spx_wr_trace               -- stop
 */
#include <linux/kprobes.h>
#include <linux/module.h>

static int max = 600;
module_param(max, int, 0644);
MODULE_PARM_DESC(max, "max lines to log before going quiet");

static atomic_t count = ATOMIC_INIT(0);

static int spx_wr_pre(struct kprobe *p, struct pt_regs *regs)
{
	int n = atomic_inc_return(&count);

	/* aarch64: x0=ctrl, x1=cmd_data, x2=dev_addr, x3=reg_addr */
	if (n <= max)
		pr_info("spxwr %4d dev=%llu addr=0x%04llx val=0x%02llx\n",
			n, regs->regs[2], regs->regs[3], regs->regs[1]);
	else if (n == max + 1)
		pr_info("spxwr: cap reached (%d), muting\n", max);
	return 0;
}

static struct kprobe spx_kp = {
	.symbol_name = "qcom_swrm_cmd_fifo_wr_cmd",
	.pre_handler = spx_wr_pre,
};

static int __init spx_wr_trace_init(void)
{
	int ret = register_kprobe(&spx_kp);

	pr_info("spx_wr_trace: register_kprobe = %d\n", ret);
	return ret;
}

static void __exit spx_wr_trace_exit(void)
{
	unregister_kprobe(&spx_kp);
	pr_info("spx_wr_trace: total writes seen: %d\n", atomic_read(&count));
}

module_init(spx_wr_trace_init);
module_exit(spx_wr_trace_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX SoundWire write-command kprobe tracer");
