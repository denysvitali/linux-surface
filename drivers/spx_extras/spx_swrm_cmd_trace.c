// SPDX-License-Identifier: GPL-2.0
/*
 * Read-only kprobe trace of the running Qualcomm SoundWire command path.
 * This module observes transactions; it never submits or changes one.
 */
#include <linux/atomic.h>
#include <linux/kprobes.h>
#include <linux/module.h>

#define SWRM_INTERRUPT_STATUS	0x0200
#define SWRM_FIFO_RD_CMD		0x0304
#define SWRM_FIFO_CMD		0x0308
#define SWRM_FIFO_STATUS	0x030c
#define SWRM_FIFO_RD_DATA	0x0318

static int max_events = 1000;
module_param(max_events, int, 0444);
MODULE_PARM_DESC(max_events, "Maximum trace lines");

static atomic_t events = ATOMIC_INIT(0);

static bool take_event(void)
{
	int n = atomic_inc_return(&events);

	if (n <= max_events)
		return true;
	if (n == max_events + 1)
		pr_info("spxcmd: cap %d reached; muting\n", max_events);
	return false;
}

struct cmd_call {
	u8 dev;
	u16 reg;
	u32 len;
	u8 *rval;
};

static int cmd_entry(struct kretprobe_instance *ri, struct pt_regs *regs)
{
	struct cmd_call *call = (struct cmd_call *)ri->data;

	/* aarch64: x0=ctrl, x1=dev, x2=reg, x3=len, x4=result */
	call->dev = regs->regs[1];
	call->reg = regs->regs[2];
	call->len = regs->regs[3];
	call->rval = (u8 *)regs->regs[4];
	if (take_event())
		pr_info("spxcmd CALL dev=%u reg=%#06x len=%u\n",
			call->dev, call->reg, call->len);
	return 0;
}
NOKPROBE_SYMBOL(cmd_entry);

static int cmd_return(struct kretprobe_instance *ri, struct pt_regs *regs)
{
	struct cmd_call *call = (struct cmd_call *)ri->data;

	if (take_event())
		pr_info("spxcmd RET  dev=%u reg=%#06x ret=%ld data=%#04x\n",
			call->dev, call->reg,
			(long)regs_return_value(regs),
			call->rval ? READ_ONCE(*call->rval) : 0);
	return 0;
}
NOKPROBE_SYMBOL(cmd_return);

static struct kretprobe cmd_probe = {
	.kp.symbol_name = "qcom_swrm_cmd_fifo_rd_cmd",
	.entry_handler = cmd_entry,
	.handler = cmd_return,
	.data_size = sizeof(struct cmd_call),
	.maxactive = 16,
};

static int write_entry(struct kprobe *probe, struct pt_regs *regs)
{
	unsigned int reg = regs->regs[1];

	if ((reg == SWRM_FIFO_RD_CMD || reg == SWRM_FIFO_CMD) &&
	    take_event())
		pr_info("spxcmd MWR  reg=%#06x val=%#010llx\n",
			reg, regs->regs[2]);
	return 0;
}
NOKPROBE_SYMBOL(write_entry);

static struct kprobe write_probe = {
	.symbol_name = "qcom_swrm_ahb_reg_write",
	.pre_handler = write_entry,
};

struct read_call {
	unsigned int reg;
	u32 *val;
};

static int read_entry(struct kretprobe_instance *ri, struct pt_regs *regs)
{
	struct read_call *call = (struct read_call *)ri->data;

	call->reg = regs->regs[1];
	call->val = (u32 *)regs->regs[2];
	return 0;
}
NOKPROBE_SYMBOL(read_entry);

static int read_return(struct kretprobe_instance *ri, struct pt_regs *regs)
{
	struct read_call *call = (struct read_call *)ri->data;

	if ((call->reg == SWRM_FIFO_STATUS ||
	     call->reg == SWRM_FIFO_RD_DATA ||
	     call->reg == SWRM_INTERRUPT_STATUS) &&
	    take_event())
		pr_info("spxcmd MRD  reg=%#06x val=%#010x ret=%ld\n",
			call->reg, call->val ? READ_ONCE(*call->val) : 0,
			(long)regs_return_value(regs));
	return 0;
}
NOKPROBE_SYMBOL(read_return);

static struct kretprobe read_probe = {
	.kp.symbol_name = "qcom_swrm_ahb_reg_read",
	.entry_handler = read_entry,
	.handler = read_return,
	.data_size = sizeof(struct read_call),
	.maxactive = 32,
};

static bool cmd_registered;
static bool write_registered;
static bool read_registered;

static int __init spx_swrm_cmd_trace_init(void)
{
	int ret;

	ret = register_kretprobe(&cmd_probe);
	if (ret)
		return ret;
	cmd_registered = true;

	ret = register_kprobe(&write_probe);
	if (ret)
		goto err;
	write_registered = true;

	ret = register_kretprobe(&read_probe);
	if (ret)
		goto err;
	read_registered = true;

	pr_info("spx_swrm_cmd_trace: active (read-only, unloadable)\n");
	return 0;
err:
	if (write_registered)
		unregister_kprobe(&write_probe);
	if (cmd_registered)
		unregister_kretprobe(&cmd_probe);
	return ret;
}

static void __exit spx_swrm_cmd_trace_exit(void)
{
	if (read_registered)
		unregister_kretprobe(&read_probe);
	if (write_registered)
		unregister_kprobe(&write_probe);
	if (cmd_registered)
		unregister_kretprobe(&cmd_probe);
	pr_info("spx_swrm_cmd_trace: stopped after %d events, missed=%d/%d\n",
		atomic_read(&events), cmd_probe.nmissed, read_probe.nmissed);
}

module_init(spx_swrm_cmd_trace_init);
module_exit(spx_swrm_cmd_trace_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX unloadable read-only SoundWire command trace");
