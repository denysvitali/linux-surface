// SPDX-License-Identifier: GPL-2.0-only
/* Fixed, read-only TZ_PIL_GET_MEM_AREA query; spare argument is zero. */
#include <linux/arm-smccc.h>
#include <linux/module.h>
#include <linux/of.h>

static int __init spx_pil_memory_area_init(void)
{
	struct arm_smccc_res res = {};
	unsigned long fid = ARM_SMCCC_CALL_VAL(ARM_SMCCC_FAST_CALL,
			ARM_SMCCC_SMC_64, ARM_SMCCC_OWNER_SIP, 0x0209);

	if (!of_machine_is_compatible("microsoft,surface-pro-x"))
		return -ENODEV;

	/* Qualcomm PIL service 2, command 9, one value argument (spare=0). */
	arm_smccc_smc(fid, 1, 0, 0, 0, 0, 0, 0, &res);
	pr_info("SPX PIL memory area: fid=0x%lx a0=0x%lx a1=0x%lx a2=0x%lx a3=0x%lx\n",
		fid, res.a0, res.a1, res.a2, res.a3);
	return 0;
}
module_init(spx_pil_memory_area_init);

static void __exit spx_pil_memory_area_exit(void)
{
}
module_exit(spx_pil_memory_area_exit);

MODULE_DESCRIPTION("Surface Pro X read-only PIL relocation memory range query");
MODULE_LICENSE("GPL");
