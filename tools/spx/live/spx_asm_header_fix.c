// SPDX-License-Identifier: GPL-2.0-only
/*
 * Live equivalent of q6asm_add_hdr() initializing src_svc, without reloading
 * the Q6 stack and invalidating retained DSP mappings. Temporary until the
 * corrected q6asm module is loaded on a fresh boot.
 */
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/ptrace.h>
#include <linux/soc/qcom/apr.h>

static int spx_asm_header(struct kprobe *probe, struct pt_regs *regs)
{
	struct apr_device *adev = (void *)regs_get_kernel_argument(regs, 0);
	struct apr_pkt *pkt = (void *)regs_get_kernel_argument(regs, 1);

	/* ASM has no Windows client-identity override; other services do. */
	if (adev->svc.id == APR_SVC_ASM)
		pkt->hdr.src_svc = 0;
	return 0;
}

static struct kprobe asm_header_probe = {
	.addr = (kprobe_opcode_t *)apr_send_pkt,
	.pre_handler = spx_asm_header,
};

static int __init spx_asm_header_fix_init(void)
{
	if (!of_machine_is_compatible("microsoft,surface-pro-x"))
		return -ENODEV;
	return register_kprobe(&asm_header_probe);
}

static void __exit spx_asm_header_fix_exit(void)
{
	unregister_kprobe(&asm_header_probe);
}

module_init(spx_asm_header_fix_init);
module_exit(spx_asm_header_fix_exit);
MODULE_DESCRIPTION("SPX live ASM APR source-service initialization fix");
MODULE_LICENSE("GPL");
