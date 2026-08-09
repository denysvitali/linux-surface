// SPDX-License-Identifier: GPL-2.0
/* SPX: kretprobe qcom_slim_ngd_enable_stream return value. */
#include <linux/module.h>
#include <linux/kprobes.h>
#include <linux/ptrace.h>

static int en_ret(struct kretprobe_instance *ri, struct pt_regs *regs)
{
	pr_info("spx_en_trace: qcom_slim_ngd_enable_stream ret=%d\n",
		(int)regs->regs[0]);
	return 0;
}
static int xsfer_ret(struct kretprobe_instance *ri, struct pt_regs *regs)
{
	int ret = (int)regs->regs[0];
	if (ret)
		pr_info("spx_en_trace: qcom_slim_ngd_xfer_msg_sync ret=%d\n", ret);
	return 0;
}
static struct kretprobe kp_en = {
	.kp.symbol_name = "qcom_slim_ngd_enable_stream",
	.handler = en_ret, .maxactive = 8,
};
static struct kretprobe kp_xs = {
	.kp.symbol_name = "qcom_slim_ngd_xfer_msg_sync",
	.handler = xsfer_ret, .maxactive = 16,
};
static int __init spx_init(void)
{
	int r1 = register_kretprobe(&kp_en);
	int r2 = register_kretprobe(&kp_xs);
	pr_info("spx_en_trace: en=%d xs=%d\n", r1, r2);
	return r1 ? r1 : r2;
}
static void __exit spx_exit(void) { unregister_kretprobe(&kp_en); unregister_kretprobe(&kp_xs); }
module_init(spx_init); module_exit(spx_exit);
MODULE_LICENSE("GPL"); MODULE_DESCRIPTION("SPX: trace enable_stream ret");
