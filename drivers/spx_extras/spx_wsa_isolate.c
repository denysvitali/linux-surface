// SPDX-License-Identifier: GPL-2.0
/*
 * Reversible WSA isolation diagnostic for Surface Pro X.
 *
 * Save the WCD GPIO state, shut down both WSA881x amplifiers, wake one,
 * and reproduce Windows' ENUMERATOR_CFG 0->1 recovery through the running
 * qcom driver's mutex-protected AHB helper.  Restore the saved GPIO state
 * when this module is unloaded.
 */
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>

#define WCD_GPIO_DIR			0x0042
#define WCD_GPIO_VAL			0x0043
#define WCD_SWR_AHB_ACCESS_CFG		0x0c95
#define WCD_SWR_CLK_CONTROL		0x0d43
#define WSA_GPIO_MASK			(BIT(1) | BIT(2))
#define SWRM_ENUMERATOR_CFG		0x0500

typedef int (*spx_ahb_write_fn)(void *ctrl, int reg, int val);

static int active_pin;
module_param(active_pin, int, 0444);
MODULE_PARM_DESC(active_pin,
		 "WCD GPIO pin to wake (1=left, 2=right, 3=both)");

static bool rearm_enum = true;
module_param(rearm_enum, bool, 0444);
MODULE_PARM_DESC(rearm_enum,
		 "Perform Windows ENUMERATOR_CFG 0->1 after GPIO change");

static struct device *swrm_dev;
static struct regmap *wcd_regmap;
static unsigned int saved_dir;
static unsigned int saved_val;
static bool gpio_changed;

static int __init spx_wsa_isolate_init(void)
{
	struct kprobe resolver = {
		.symbol_name = "qcom_swrm_ahb_reg_write",
	};
	unsigned int access_cfg, swr_clk;
	spx_ahb_write_fn swrm_write;
	void *swrm_ctrl;
	unsigned int active_mask;
	int ret0, ret1;
	int ret;

	if (active_pin != 1 && active_pin != 2 && active_pin != 3)
		return -EINVAL;
	active_mask = active_pin == 3 ? WSA_GPIO_MASK : BIT(active_pin);

	swrm_dev = bus_find_device_by_name(&platform_bus_type, NULL,
					   "wcd934x-soundwire.5.auto");
	if (!swrm_dev)
		return -ENODEV;

	swrm_ctrl = dev_get_drvdata(swrm_dev);
	wcd_regmap = dev_get_regmap(swrm_dev->parent, NULL);
	if (!swrm_ctrl || !wcd_regmap) {
		ret = -ENODEV;
		goto err_put_device;
	}

	ret = regmap_read(wcd_regmap, WCD_GPIO_DIR, &saved_dir);
	if (ret)
		goto err_put_device;
	ret = regmap_read(wcd_regmap, WCD_GPIO_VAL, &saved_val);
	if (ret)
		goto err_put_device;
	ret = regmap_read(wcd_regmap, WCD_SWR_AHB_ACCESS_CFG, &access_cfg);
	if (ret)
		goto err_put_device;
	ret = regmap_read(wcd_regmap, WCD_SWR_CLK_CONTROL, &swr_clk);
	if (ret)
		goto err_put_device;

	ret = register_kprobe(&resolver);
	if (ret)
		goto err_put_device;
	swrm_write = (spx_ahb_write_fn)resolver.addr;
	unregister_kprobe(&resolver);
	if (!swrm_write) {
		ret = -ENOENT;
		goto err_put_device;
	}

	/*
	 * WSA881x SD_N is active-low: physical LOW is shutdown and HIGH is
	 * active.  Program LOW before changing direction so neither amplifier
	 * is accidentally pulsed awake.
	 */
	ret = regmap_update_bits(wcd_regmap, WCD_GPIO_VAL,
				 WSA_GPIO_MASK, 0);
	if (ret)
		goto err_put_device;
	ret = regmap_update_bits(wcd_regmap, WCD_GPIO_DIR,
				 WSA_GPIO_MASK, WSA_GPIO_MASK);
	if (ret)
		goto err_restore;
	gpio_changed = true;
	msleep(20);

	ret = regmap_update_bits(wcd_regmap, WCD_GPIO_VAL,
				 active_mask, active_mask);
	if (ret)
		goto err_restore;
	msleep(20);

	ret0 = 0;
	ret1 = 0;
	if (rearm_enum) {
		ret0 = swrm_write(swrm_ctrl, SWRM_ENUMERATOR_CFG, 0);
		ret1 = swrm_write(swrm_ctrl, SWRM_ENUMERATOR_CFG, 1);
	} else {
		ret0 = swrm_write(swrm_ctrl, SWRM_ENUMERATOR_CFG, 0);
	}
	pr_info("spx_wsa_isolate: pin%d active; saved dir=%#x val=%#x; d43=%#x c95=%#x; enum results=%d,%d\n",
		active_pin, saved_dir, saved_val, swr_clk, access_cfg,
		ret0, ret1);
	if (ret0 || ret1) {
		ret = ret0 ? ret0 : ret1;
		goto err_restore;
	}

	return 0;

err_restore:
	regmap_update_bits(wcd_regmap, WCD_GPIO_VAL,
			   WSA_GPIO_MASK, 0);
	regmap_update_bits(wcd_regmap, WCD_GPIO_DIR,
			   WSA_GPIO_MASK, saved_dir & WSA_GPIO_MASK);
	regmap_update_bits(wcd_regmap, WCD_GPIO_VAL,
			   WSA_GPIO_MASK, saved_val & WSA_GPIO_MASK);
	gpio_changed = false;
err_put_device:
	put_device(swrm_dev);
	swrm_dev = NULL;
	return ret;
}

static void __exit spx_wsa_isolate_exit(void)
{
	if (gpio_changed) {
		/* Quiesce both first, then restore the exact saved bits. */
		regmap_update_bits(wcd_regmap, WCD_GPIO_VAL,
				   WSA_GPIO_MASK, 0);
		msleep(20);
		regmap_update_bits(wcd_regmap, WCD_GPIO_DIR,
				   WSA_GPIO_MASK, saved_dir & WSA_GPIO_MASK);
		regmap_update_bits(wcd_regmap, WCD_GPIO_VAL,
				   WSA_GPIO_MASK, saved_val & WSA_GPIO_MASK);
	}
	if (swrm_dev)
		put_device(swrm_dev);
	pr_info("spx_wsa_isolate: restored dir=%#x val=%#x and unloaded\n",
		saved_dir, saved_val);
}

module_init(spx_wsa_isolate_init);
module_exit(spx_wsa_isolate_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX unloadable reversible single-WSA isolation diagnostic");
