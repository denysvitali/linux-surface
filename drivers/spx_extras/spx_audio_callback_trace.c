// SPDX-License-Identifier: GPL-2.0
/* Passive, bounded observation of codec initialization and controller writes. */
#include <linux/atomic.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/sched.h>

static atomic_t events = ATOMIC_INIT(0);
static int observe(struct kprobe *p, struct pt_regs *regs)
{
	if (atomic_inc_return(&events) <= 160)
		pr_info("spxcb %s pid=%d comm=%s arg1=%#llx arg2=%#llx\n",
			p->symbol_name, current->pid, current->comm,
			regs->regs[1], regs->regs[2]);
	return 0;
}
NOKPROBE_SYMBOL(observe);

static struct kprobe probes[] = {
	{ .symbol_name = "wsa881x_init", .pre_handler = observe },
	{ .symbol_name = "wsa881x_update_status", .pre_handler = observe },
	{ .symbol_name = "qcom_swrm_irq_handler", .pre_handler = observe },
	{ .symbol_name = "qcom_swrm_ahb_reg_write", .pre_handler = observe },
};

static int __init spx_callback_init(void)
{
	int i, ret;

	for (i = 0; i < ARRAY_SIZE(probes); i++) {
		ret = register_kprobe(&probes[i]);
		if (ret) {
			while (i--)
				unregister_kprobe(&probes[i]);
			return ret;
		}
	}
	pr_info("spxcb started\n");
	return 0;
}

static void __exit spx_callback_exit(void)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(probes); i++)
		unregister_kprobe(&probes[i]);
	pr_info("spxcb finished events=%d\n", atomic_read(&events));
}
module_init(spx_callback_init);
module_exit(spx_callback_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX passive audio callback observer");
