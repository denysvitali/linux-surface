// SPDX-License-Identifier: GPL-2.0-only
/*
 * Enable the primary Surface Pro X USB-C DisplayPort controller on a
 * running known-good boot. The change is only in the live device tree.
 * A reboot returns to the on-disk DTB, which leaves this node disabled.
 *
 * The probe itself is safe: on boot ab366973 the device bound to
 * msm-dp-display while eDP stayed connected and USB stayed up.
 * Unbinding msm_dpu afterwards is not. On 2026-09-21 that unbind oopsed
 * in msm_gem_lock_vm_and_obj during GEM handle close and the machine
 * froze until a power cycle. Do not unbind or rebind msm_dpu, msm-mdss,
 * or msm-dp-display from this module or from a follow-up script.
 */
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>

static const u8 spx_dp0_dtbo[] = {
#include "spx_dp0_dtbo.inc"
};

static int ovcs_id = -1;

static int __init spx_dp0_enable_init(void)
{
	struct device_node *np;
	struct platform_device *pdev;
	int ret;

	ret = of_overlay_fdt_apply(spx_dp0_dtbo, sizeof(spx_dp0_dtbo),
				   &ovcs_id, NULL);
	if (ret) {
		pr_err("spx_dp0_enable: overlay failed: %d\n", ret);
		return ret;
	}

	np = of_find_node_by_path("/soc@0/display-subsystem@ae00000/displayport-controller@ae90000");
	if (!np || !of_device_is_available(np)) {
		pr_err("spx_dp0_enable: controller node is not available\n");
		of_node_put(np);
		of_overlay_remove(&ovcs_id);
		ovcs_id = -1;
		return -ENODEV;
	}

	pdev = of_find_device_by_node(np);
	if (!pdev)
		pdev = of_platform_device_create(np, NULL, NULL);
	of_node_put(np);
	if (!pdev) {
		pr_err("spx_dp0_enable: platform device was not created\n");
		of_overlay_remove(&ovcs_id);
		ovcs_id = -1;
		return -ENODEV;
	}

	pr_info("spx_dp0_enable: %s driver=%s\n", dev_name(&pdev->dev),
		pdev->dev.driver ? pdev->dev.driver->name : "unbound");
	return 0;
}

static void __exit spx_dp0_enable_exit(void)
{
	/*
	 * Leave the controller in place. Removing the overlay while the
	 * DisplayPort device is bound would unpin a live display resource.
	 */
	pr_info("spx_dp0_enable: unloaded, overlay %d left applied\n", ovcs_id);
}

module_init(spx_dp0_enable_init);
module_exit(spx_dp0_enable_exit);

MODULE_DESCRIPTION("Enable the Surface Pro X primary USB-C DisplayPort controller");
MODULE_LICENSE("GPL");
