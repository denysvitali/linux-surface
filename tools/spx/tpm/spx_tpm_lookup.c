// SPDX-License-Identifier: GPL-2.0-only
/* Query the firmware-provisioned TPM app through the existing SCM API. */
#include <linux/firmware/qcom/qcom_scm.h>
#include <linux/module.h>
#include <linux/of.h>

static int __init spx_tpm_lookup_init(void)
{
	u32 app_id = 0;
	int ret;

	if (!of_machine_is_compatible("microsoft,surface-pro-x"))
		return -ENODEV;
	if (!qcom_scm_is_available())
		return -EPROBE_DEFER;

	/* Named lookup only: no app loading or TPM command is performed. */
	ret = qcom_scm_qseecom_app_get_id("qcom.tz.tpm", &app_id);
	pr_info("SPX TPM named lookup: ret=%d app_id=%u\n", ret, app_id);
	return ret;
}
module_init(spx_tpm_lookup_init);

static void __exit spx_tpm_lookup_exit(void)
{
}
module_exit(spx_tpm_lookup_exit);

MODULE_DESCRIPTION("Surface Pro X firmware TPM named-app lookup");
MODULE_LICENSE("GPL");
