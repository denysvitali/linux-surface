// SPDX-License-Identifier: GPL-2.0
/*
 * Unloadable, read-only poller for the running qcom SoundWire master.
 *
 * It resolves the driver's private, mutex-protected AHB read helper through
 * the kprobe API, then uses that helper without unloading soundwire_qcom.
 */
#include <linux/device.h>
#include <linux/jiffies.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/workqueue.h>

#define SWRM_COMP_STATUS		0x0014
#define SWRM_INTERRUPT_STATUS		0x0200
#define SWRM_ENUMERATOR_CFG		0x0500
#define SWRM_ENUMERATOR_ID1(dev)	(0x0530 + 8 * (dev))
#define SWRM_ENUMERATOR_ID2(dev)	(0x0534 + 8 * (dev))
#define SWRM_MCP_SLV_STATUS		0x1090

typedef int (*spx_ahb_read_fn)(void *ctrl, int reg, u32 *val);

static int samples = 100;
module_param(samples, int, 0444);
MODULE_PARM_DESC(samples, "Number of read-only samples");

static int interval_ms = 20;
module_param(interval_ms, int, 0444);
MODULE_PARM_DESC(interval_ms, "Milliseconds between samples");

static struct device *swrm_dev;
static void *swrm_ctrl;
static spx_ahb_read_fn swrm_read;
static struct delayed_work poll_work;
static int sample_count;
static u32 previous_irq = U32_MAX;
static u32 previous_slave = U32_MAX;
static u32 previous_enum = U32_MAX;

static int spx_read(int reg, u32 *val)
{
	int ret = swrm_read(swrm_ctrl, reg, val);

	if (ret)
		pr_warn_ratelimited("spx_swrm_poll: read %#x failed: %d\n",
				    reg, ret);
	return ret;
}

static void spx_poll_work(struct work_struct *work)
{
	u32 comp = 0, irq = 0, enum_cfg = 0, slave = 0;
	u32 id1 = 0, id2 = 0;
	int id_dev = 0;
	int dev;
	bool changed;

	spx_read(SWRM_COMP_STATUS, &comp);
	spx_read(SWRM_INTERRUPT_STATUS, &irq);
	spx_read(SWRM_ENUMERATOR_CFG, &enum_cfg);
	spx_read(SWRM_MCP_SLV_STATUS, &slave);
	for (dev = 1; dev <= 12; dev++) {
		spx_read(SWRM_ENUMERATOR_ID1(dev), &id1);
		spx_read(SWRM_ENUMERATOR_ID2(dev), &id2);
		if (id1 || id2) {
			id_dev = dev;
			break;
		}
	}

	changed = irq != previous_irq || slave != previous_slave ||
		  enum_cfg != previous_enum || id_dev;
	sample_count++;
	if (changed || sample_count == 1 || sample_count == samples)
		pr_info("spxpoll %d/%d comp=%#x irq=%#x enum=%#x slave=%#x iddev=%d id1=%#x id2=%#x\n",
			sample_count, samples, comp, irq, enum_cfg, slave,
			id_dev, id1, id2);

	previous_irq = irq;
	previous_slave = slave;
	previous_enum = enum_cfg;

	if (sample_count < samples)
		schedule_delayed_work(&poll_work,
				      msecs_to_jiffies(interval_ms));
	else
		pr_info("spx_swrm_poll: sampling complete\n");
}

static int __init spx_swrm_poll_init(void)
{
	struct kprobe resolver = {
		.symbol_name = "qcom_swrm_ahb_reg_read",
	};
	int ret;

	if (samples < 1 || samples > 10000 ||
	    interval_ms < 1 || interval_ms > 60000)
		return -EINVAL;

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

	swrm_read = (spx_ahb_read_fn)resolver.addr;
	unregister_kprobe(&resolver);
	if (!swrm_read) {
		ret = -ENOENT;
		goto err_put_device;
	}

	INIT_DELAYED_WORK(&poll_work, spx_poll_work);
	schedule_delayed_work(&poll_work, 0);
	pr_info("spx_swrm_poll: active (read-only, unloadable)\n");
	return 0;

err_put_device:
	put_device(swrm_dev);
	swrm_dev = NULL;
	return ret;
}

static void __exit spx_swrm_poll_exit(void)
{
	cancel_delayed_work_sync(&poll_work);
	if (swrm_dev)
		put_device(swrm_dev);
	pr_info("spx_swrm_poll: stopped after %d samples\n", sample_count);
}

module_init(spx_swrm_poll_init);
module_exit(spx_swrm_poll_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX unloadable read-only qcom SoundWire poller");
