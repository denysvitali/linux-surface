// SPDX-License-Identifier: GPL-2.0-only
/* Query the firmware-provisioned TPM app through the existing SCM API. */
#include <linux/firmware/qcom/qcom_scm.h>
#include <linux/firmware/qcom/qcom_tzmem.h>
#include <linux/err.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/sizes.h>
#include <linux/unaligned.h>

static bool query_info;
module_param(query_info, bool, 0400);
MODULE_PARM_DESC(query_info, "Also perform the confirmed read-only QUERY_INFO_2 request");

static int spx_tpm_query_info(u32 app_id)
{
	const struct qcom_tzmem_pool_config config = {
		.initial_size = SZ_4K,
		.policy = QCOM_TZMEM_POLICY_STATIC,
	};
	struct qcom_tzmem_pool *pool;
	u8 *buffer;
	int ret;

	pool = qcom_tzmem_pool_new(&config);
	if (IS_ERR(pool))
		return PTR_ERR(pool);
	/* Four-byte request, eight-byte aligned response, twelve-byte response. */
	buffer = qcom_tzmem_alloc(pool, 20, GFP_KERNEL);
	if (!buffer) {
		qcom_tzmem_pool_free(pool);
		return -ENOMEM;
	}
	memset(buffer, 0, 20);
	put_unaligned_le32(0x4012, buffer);
	ret = qcom_scm_qseecom_app_send(app_id, buffer, 4, buffer + 8, 12);
	if (!ret)
		pr_info("SPX TPM QUERY_INFO_2: ret=0 nv_store_size=%u control_area=0x%llx\n",
			get_unaligned_le32(buffer + 8), get_unaligned_le64(buffer + 12));
	else
		pr_info("SPX TPM QUERY_INFO_2: ret=%d\n", ret);
	qcom_tzmem_free(buffer);
	qcom_tzmem_pool_free(pool);
	return ret;
}

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
	if (ret || !query_info)
		return ret;
	return spx_tpm_query_info(app_id);
}
module_init(spx_tpm_lookup_init);

static void __exit spx_tpm_lookup_exit(void)
{
}
module_exit(spx_tpm_lookup_exit);

MODULE_DESCRIPTION("Surface Pro X firmware TPM named-app lookup");
MODULE_LICENSE("GPL");
