// SPDX-License-Identifier: GPL-2.0
/* SPX: kretprobe slim_do_transfer to log SLIMbus channel-activation results. */
#include <linux/module.h>
#include <linux/kprobes.h>
#include <linux/ptrace.h>

struct txn_info { u8 mc; u8 la; };

static int entry_handler(struct kretprobe_instance *ri, struct pt_regs *regs)
{
	struct txn_info *ti = (struct txn_info *)ri->data;
	const u8 *txn = (const u8 *)regs->regs[1]; /* struct slim_msg_txn * */

	ti->mc = txn[2];
	ti->la = txn[7];
	return 0;
}

static int ret_handler(struct kretprobe_instance *ri, struct pt_regs *regs)
{
	struct txn_info *ti = (struct txn_info *)ri->data;
	int ret = (int)regs->regs[0];

	/* reconfig/channel-activation messages: always log */
	if (ti->mc >= 0x40 && ti->mc <= 0x5f)
		pr_info("spx_slim_trace: ACTIVATION mc=0x%02x la=0x%02x ret=%d\n",
			ti->mc, ti->la, ret);
	/* value xfers: log only failures */
	else if ((ti->mc == 0x60 || ti->mc == 0x68) && ret)
		pr_info("spx_slim_trace: VALUE-FAIL mc=0x%02x la=0x%02x ret=%d\n",
			ti->mc, ti->la, ret);
	return 0;
}

static struct kretprobe krp = {
	.kp.symbol_name = "slim_do_transfer",
	.entry_handler = entry_handler,
	.handler = ret_handler,
	.data_size = sizeof(struct txn_info),
	.maxactive = 32,
};

static int __init spx_init(void)
{
	int ret = register_kretprobe(&krp);
	if (ret)
		pr_err("spx_slim_trace: register failed %d\n", ret);
	else
		pr_info("spx_slim_trace: probing slim_do_transfer\n");
	return ret;
}
static void __exit spx_exit(void) { unregister_kretprobe(&krp); }
module_init(spx_init);
module_exit(spx_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX: trace SLIMbus channel activation");
