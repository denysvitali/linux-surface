// SPDX-License-Identifier: GPL-2.0-only
/* Query the firmware-provisioned TPM app through the existing SCM API. */
#include <linux/firmware/qcom/qcom_scm.h>
#include <linux/firmware/qcom/qcom_qseecom.h>
#include <linux/firmware/qcom/qcom_tzmem.h>
#include <linux/err.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/sizes.h>
#include <linux/unaligned.h>

static bool query_info;
static bool register_client;
static struct qseecom_client *tpm_client;
static struct device *qsee_parent;
module_param(query_info, bool, 0400);
module_param(register_client, bool, 0400);
MODULE_PARM_DESC(query_info, "Also perform the confirmed read-only QUERY_INFO_2 request");
MODULE_PARM_DESC(register_client, "Register the confirmed named auxiliary client for live driver testing");

static void spx_tpm_client_release(struct device *dev)
{
	struct qseecom_client *client = container_of(dev, struct qseecom_client,
						    aux_dev.dev);

	kfree(client);
}

static int spx_tpm_register_client(u32 app_id)
{
	int ret;

	qsee_parent = bus_find_device_by_name(&platform_bus_type, NULL,
					    "qcom_qseecom");
	if (!qsee_parent)
		return -ENODEV;
	tpm_client = kzalloc_obj(*tpm_client);
	if (!tpm_client) {
		ret = -ENOMEM;
		goto put_parent;
	}
	tpm_client->app_id = app_id;
	tpm_client->aux_dev.name = "tpm";
	tpm_client->aux_dev.dev.parent = qsee_parent;
	tpm_client->aux_dev.dev.release = spx_tpm_client_release;
	ret = auxiliary_device_init(&tpm_client->aux_dev);
	if (ret) {
		kfree(tpm_client);
		goto clear_client;
	}
	/* Match the in-tree provider's auxiliary namespace without rebinding it. */
	ret = __auxiliary_device_add(&tpm_client->aux_dev, "qcom_qseecom");
	if (!ret)
		return 0;
	auxiliary_device_uninit(&tpm_client->aux_dev);
clear_client:
	tpm_client = NULL;
put_parent:
	put_device(qsee_parent);
	qsee_parent = NULL;
	return ret;
}

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

	/* The default only looks up the named application. */
	ret = qcom_scm_qseecom_app_get_id("qcom.tz.tpm", &app_id);
	pr_info("SPX TPM named lookup: ret=%d app_id=%u\n", ret, app_id);
	if (ret)
		return ret;
	if (query_info || register_client) {
		ret = spx_tpm_query_info(app_id);
		if (ret)
			return ret;
	}
	if (register_client)
		return spx_tpm_register_client(app_id);
	return 0;
}
module_init(spx_tpm_lookup_init);

static void __exit spx_tpm_lookup_exit(void)
{
	if (tpm_client) {
		auxiliary_device_delete(&tpm_client->aux_dev);
		auxiliary_device_uninit(&tpm_client->aux_dev);
		put_device(qsee_parent);
	}
}
module_exit(spx_tpm_lookup_exit);

MODULE_DESCRIPTION("Surface Pro X firmware TPM named-app lookup");
MODULE_LICENSE("GPL");
