// SPDX-License-Identifier: GPL-2.0
/*
 * One-use recovery for the live-health observer's bus/controller lock
 * inversion.  Keep loaded until the observer init thread has returned.
 */
#include <linux/device.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/soundwire/sdw.h>

static int target_pid;
module_param(target_pid, int, 0400);

static struct sdw_bus *target_bus;
static bool repaired;
static bool probe_registered;

static int repair_bus_owner(struct kprobe *probe, struct pt_regs *regs)
{
	if (!repaired && task_pid_nr(current) == target_pid &&
	    mutex_trylock(&target_bus->bus_lock)) {
		repaired = true;
		pr_info("spxrescue: observer thread re-acquired its bus lock\n");
	}
	return 0;
}

static struct kprobe repair_probe = {
	.symbol_name = "qcom_swrm_ahb_reg_read",
	.pre_handler = repair_bus_owner,
};

static int __init spx_swrm_deadlock_rescue_init(void)
{
	struct device *dev;
	int ret;

	if (target_pid <= 0)
		return -EINVAL;
	dev = bus_find_device_by_name(&platform_bus_type, NULL,
				      "wcd934x-soundwire.5.auto");
	if (!dev)
		return -ENODEV;
	target_bus = dev_get_drvdata(dev);
	put_device(dev);
	if (!target_bus)
		return -ENODEV;

	ret = register_kprobe(&repair_probe);
	if (ret)
		return ret;
	probe_registered = true;

	/*
	 * The target observer is asleep on controller_lock while still owning
	 * bus_lock.  Let the controller IRQ finish; the probe above restores
	 * real ownership to the same target before its normal mutex_unlock().
	 */
	mutex_unlock(&target_bus->bus_lock);
	pr_info("spxrescue: released observer bus lock to break inversion\n");
	return 0;
}

static void __exit spx_swrm_deadlock_rescue_exit(void)
{
	if (probe_registered)
		unregister_kprobe(&repair_probe);
	pr_info("spxrescue: unloaded repaired=%d\n", repaired);
}

module_init(spx_swrm_deadlock_rescue_init);
module_exit(spx_swrm_deadlock_rescue_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX one-use observer lock-inversion rescue");
