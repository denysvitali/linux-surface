// SPDX-License-Identifier: GPL-2.0
/*
 * Unloadable, read-only observer for the private qcom SoundWire functions.
 *
 * The controller module is unsafe to unload on Surface Pro X after it has
 * mutated the shared SLIMbus/ADSP state.  Kprobes let us observe that running
 * driver without replacing it or issuing any bus transaction of our own.
 */
#include <linux/atomic.h>
#include <linux/kprobes.h>
#include <linux/module.h>

#define SWRM_COMP_STATUS		0x0014
#define SWRM_INTERRUPT_STATUS		0x0200
#define SWRM_INTERRUPT_MASK		0x0204
#define SWRM_INTERRUPT_CLEAR		0x0208
#define SWRM_INTERRUPT_CPU_EN		0x0210
#define SWRM_CMD_FIFO_STATUS		0x030c
#define SWRM_CMD_FIFO_CFG		0x0314
#define SWRM_ENUMERATOR_CFG		0x0500
#define SWRM_ENUMERATOR_ID_FIRST	0x0530
#define SWRM_ENUMERATOR_ID_LAST		0x05a4
#define SWRM_MCP_BUS_CTRL		0x1044
#define SWRM_MCP_CFG			0x1048
#define SWRM_MCP_STATUS			0x104c
#define SWRM_MCP_SLV_STATUS		0x1090

static int max_events = 1000;
module_param(max_events, int, 0444);
MODULE_PARM_DESC(max_events, "Maximum event lines before the observer mutes");

static atomic_t event_count = ATOMIC_INIT(0);

static bool spx_interesting_reg(unsigned int reg)
{
	return reg == SWRM_COMP_STATUS ||
	       reg == SWRM_INTERRUPT_STATUS ||
	       reg == SWRM_INTERRUPT_MASK ||
	       reg == SWRM_INTERRUPT_CLEAR ||
	       reg == SWRM_INTERRUPT_CPU_EN ||
	       reg == SWRM_CMD_FIFO_STATUS ||
	       reg == SWRM_CMD_FIFO_CFG ||
	       reg == SWRM_ENUMERATOR_CFG ||
	       (reg >= SWRM_ENUMERATOR_ID_FIRST &&
		reg <= SWRM_ENUMERATOR_ID_LAST) ||
	       reg == SWRM_MCP_BUS_CTRL ||
	       reg == SWRM_MCP_CFG ||
	       reg == SWRM_MCP_STATUS ||
	       reg == SWRM_MCP_SLV_STATUS;
}

static bool spx_take_event(void)
{
	int count = atomic_inc_return(&event_count);

	if (count <= max_events)
		return true;
	if (count == max_events + 1)
		pr_info("spx_swrm_observe: event cap %d reached; muting\n",
			max_events);
	return false;
}

struct spx_read_data {
	unsigned int reg;
	u32 *val;
};

static int spx_read_entry(struct kretprobe_instance *ri, struct pt_regs *regs)
{
	struct spx_read_data *data = (struct spx_read_data *)ri->data;

	/* aarch64: x0=ctrl, x1=master register, x2=result pointer */
	data->reg = (unsigned int)regs->regs[1];
	data->val = (u32 *)regs->regs[2];
	return 0;
}
NOKPROBE_SYMBOL(spx_read_entry);

static int spx_read_return(struct kretprobe_instance *ri, struct pt_regs *regs)
{
	struct spx_read_data *data = (struct spx_read_data *)ri->data;
	int ret = (int)regs_return_value(regs);

	if (spx_interesting_reg(data->reg) && spx_take_event()) {
		if (!ret)
			pr_info("spxobs RD reg=%#06x val=%#010x ret=%d\n",
				data->reg, READ_ONCE(*data->val), ret);
		else
			pr_info("spxobs RD reg=%#06x ret=%d\n",
				data->reg, ret);
	}
	return 0;
}
NOKPROBE_SYMBOL(spx_read_return);

static struct kretprobe spx_read_probe = {
	.kp.symbol_name = "qcom_swrm_ahb_reg_read",
	.entry_handler = spx_read_entry,
	.handler = spx_read_return,
	.data_size = sizeof(struct spx_read_data),
	.maxactive = 64,
};

static int spx_write_entry(struct kprobe *probe, struct pt_regs *regs)
{
	unsigned int reg = (unsigned int)regs->regs[1];

	/* aarch64: x0=ctrl, x1=master register, x2=value */
	if (spx_interesting_reg(reg) && spx_take_event())
		pr_info("spxobs WR reg=%#06x val=%#010llx\n",
			reg, regs->regs[2]);
	return 0;
}
NOKPROBE_SYMBOL(spx_write_entry);

static struct kprobe spx_write_probe = {
	.symbol_name = "qcom_swrm_ahb_reg_write",
	.pre_handler = spx_write_entry,
};

static int spx_irq_entry(struct kprobe *probe, struct pt_regs *regs)
{
	if (spx_take_event())
		pr_info("spxobs IRQ irq=%llu ctrl=%px\n",
			regs->regs[0], (void *)regs->regs[1]);
	return 0;
}
NOKPROBE_SYMBOL(spx_irq_entry);

static struct kprobe spx_irq_probe = {
	.symbol_name = "qcom_swrm_irq_handler",
	.pre_handler = spx_irq_entry,
};

static int spx_status_entry(struct kprobe *probe, struct pt_regs *regs)
{
	if (spx_take_event())
		pr_info("spxobs STATUS ctrl=%px\n", (void *)regs->regs[0]);
	return 0;
}
NOKPROBE_SYMBOL(spx_status_entry);

static struct kprobe spx_status_probe = {
	.symbol_name = "qcom_swrm_get_device_status",
	.pre_handler = spx_status_entry,
};

static int spx_enum_entry(struct kprobe *probe, struct pt_regs *regs)
{
	if (spx_take_event())
		pr_info("spxobs ENUM bus=%px\n", (void *)regs->regs[0]);
	return 0;
}
NOKPROBE_SYMBOL(spx_enum_entry);

static struct kprobe spx_enum_probe = {
	.symbol_name = "qcom_swrm_enumerate.isra.0",
	.pre_handler = spx_enum_entry,
};

static bool read_registered;
static bool write_registered;
static bool irq_registered;
static bool status_registered;
static bool enum_registered;

static int __init spx_swrm_observe_init(void)
{
	int ret;

	ret = register_kretprobe(&spx_read_probe);
	if (!ret)
		read_registered = true;
	else
		pr_warn("spx_swrm_observe: read probe unavailable: %d\n", ret);

	ret = register_kprobe(&spx_write_probe);
	if (!ret)
		write_registered = true;
	else
		pr_warn("spx_swrm_observe: write probe unavailable: %d\n", ret);

	ret = register_kprobe(&spx_irq_probe);
	if (!ret)
		irq_registered = true;
	else
		pr_warn("spx_swrm_observe: IRQ probe unavailable: %d\n", ret);

	ret = register_kprobe(&spx_status_probe);
	if (!ret)
		status_registered = true;
	else
		pr_warn("spx_swrm_observe: status probe unavailable: %d\n", ret);

	ret = register_kprobe(&spx_enum_probe);
	if (!ret)
		enum_registered = true;
	else
		pr_warn("spx_swrm_observe: enum probe unavailable: %d\n", ret);

	if (!read_registered && !write_registered && !irq_registered &&
	    !status_registered && !enum_registered)
		return -ENOENT;

	pr_info("spx_swrm_observe: active (read-only, unloadable)\n");
	return 0;
}

static void __exit spx_swrm_observe_exit(void)
{
	if (enum_registered)
		unregister_kprobe(&spx_enum_probe);
	if (status_registered)
		unregister_kprobe(&spx_status_probe);
	if (irq_registered)
		unregister_kprobe(&spx_irq_probe);
	if (write_registered)
		unregister_kprobe(&spx_write_probe);
	if (read_registered)
		unregister_kretprobe(&spx_read_probe);

	pr_info("spx_swrm_observe: stopped after %d events; missed reads=%d\n",
		atomic_read(&event_count), spx_read_probe.nmissed);
}

module_init(spx_swrm_observe_init);
module_exit(spx_swrm_observe_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX unloadable read-only qcom SoundWire observer");
