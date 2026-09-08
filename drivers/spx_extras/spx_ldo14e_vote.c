// SPDX-License-Identifier: GPL-2.0
/* Temporary LDO14E vote through the normal RPMh regulator driver.
 * The overlay is built for the current live DT supply phandle (155).
 * Load only with the speaker PAs muted. Unload releases the vote and overlay.
 */
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/firmware.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/regulator/consumer.h>

#define RSC_PATH "/soc@0/rsc@18200000"
#define SOURCE_PATH RSC_PATH "/pmc8180-e-rpmh-regulators"
#define CONSUMER_PATH RSC_PATH "/spx-ldo14e-consumer"

static struct device *consumer;
static struct regulator *rail;
static int overlay_id;
static bool enabled;

static void release_test(void)
{
	int ret;

	if (rail) {
		if (enabled) {
			ret = regulator_disable(rail);
			pr_info("spxldovote: disable rc=%d\n", ret);
		}
		regulator_put(rail);
		rail = NULL;
	}
	if (consumer) {
		root_device_unregister(consumer);
		consumer = NULL;
	}
	if (overlay_id) {
		ret = of_overlay_remove(&overlay_id);
		pr_info("spxldovote: overlay removal rc=%d\n", ret);
	}
}

static int __init spx_ldo_init(void)
{
	const struct firmware *fw;
	struct device_node *np, *child;
	u32 vin;
	int ret, attempt;

	if (!of_machine_is_compatible("microsoft,surface-pro-x"))
		return -ENODEV;
	np = of_find_node_by_path(SOURCE_PATH);
	if (!np)
		return -ENODEV;
	child = of_get_child_by_name(np, "ldo14");
	ret = of_property_read_u32(np, "vdd-l7-l12-l14-l15-supply", &vin);
	of_node_put(np);
	if (child) {
		of_node_put(child);
		return -EEXIST;
	}
	if (ret || vin != 155)
		return -EINVAL;

	consumer = root_device_register("spx-ldo14e-test");
	if (IS_ERR(consumer)) {
		ret = PTR_ERR(consumer);
		consumer = NULL;
		return ret;
	}
	ret = request_firmware(&fw, "spx-ldo14e-test.dtbo", consumer);
	if (ret)
		goto fail;
	ret = of_overlay_fdt_apply(fw->data, fw->size, &overlay_id, NULL);
	release_firmware(fw);
	if (ret)
		goto fail;
	np = of_find_node_by_path(CONSUMER_PATH);
	if (!np) {
		ret = -ENODEV;
		goto fail;
	}
	for (attempt = 0; attempt < 20; attempt++) {
		rail = of_regulator_get_optional(consumer, np, "ldo");
		if (!IS_ERR(rail))
			break;
		ret = PTR_ERR(rail);
		rail = NULL;
		if (ret != -EPROBE_DEFER)
			break;
		msleep(100);
	}
	of_node_put(np);
	if (!rail)
		goto fail;
	ret = regulator_enable(rail);
	if (ret)
		goto fail;
	enabled = true;
	pr_info("spxldovote: LDO14E enabled voltage=%d state=%d\n",
		regulator_get_voltage(rail), regulator_is_enabled(rail));
	return 0;
fail:
	pr_err("spxldovote: setup failed rc=%d\n", ret);
	release_test();
	return ret;
}

module_init(spx_ldo_init);
module_exit(release_test);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Reversible Surface LDO14E regulator vote diagnostic");
