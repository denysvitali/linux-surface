// SPDX-License-Identifier: GPL-2.0
/*
 * Unloadable one-shot reproduction of qcauddev8180's AUTO_ENUM_FAILED
 * recovery: write ENUMERATOR_CFG 0, then 1, without resetting the controller.
 */
#include <linux/device.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/platform_device.h>

#define SWRM_ENUMERATOR_CFG 0x0500

typedef int (*spx_ahb_write_fn)(void *ctrl, int reg, int val);

static struct device *swrm_dev;

static int __init spx_swrm_rearm_once_init(void)
{
	struct kprobe resolver = {
		.symbol_name = "qcom_swrm_ahb_reg_write",
	};
	spx_ahb_write_fn swrm_write;
	void *swrm_ctrl;
	int ret0, ret1;
	int ret;

	swrm_dev = bus_find_device_by_name(&platform_bus_type, NULL,
					   "wcd934x-soundwire.5.auto");
	if (!swrm_dev)
		return -ENODEV;

	swrm_ctrl = dev_get_drvdata(swrm_dev);
	if (!swrm_ctrl) {
		ret = -ENODEV;
		goto err_put_device;
	}

	ret = register_kprobe(&resolver);
	if (ret)
		goto err_put_device;

	swrm_write = (spx_ahb_write_fn)resolver.addr;
	unregister_kprobe(&resolver);
	if (!swrm_write) {
		ret = -ENOENT;
		goto err_put_device;
	}

	ret0 = swrm_write(swrm_ctrl, SWRM_ENUMERATOR_CFG, 0);
	ret1 = swrm_write(swrm_ctrl, SWRM_ENUMERATOR_CFG, 1);
	pr_info("spx_swrm_rearm_once: Windows ENUM_CFG 0->1 results %d,%d\n",
		ret0, ret1);
	if (ret0 || ret1) {
		ret = ret0 ? ret0 : ret1;
		goto err_put_device;
	}

	return 0;

err_put_device:
	put_device(swrm_dev);
	swrm_dev = NULL;
	return ret;
}

static void __exit spx_swrm_rearm_once_exit(void)
{
	if (swrm_dev)
		put_device(swrm_dev);
	pr_info("spx_swrm_rearm_once: unloaded\n");
}

module_init(spx_swrm_rearm_once_init);
module_exit(spx_swrm_rearm_once_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX unloadable Windows-compatible SoundWire enum rearm");
