// SPDX-License-Identifier: GPL-2.0
/*
 * Live test of qcauddev8180's observed COMP_SW_RESET=1,1 sequence.
 *
 * Invoke the running driver's normal qcom_swrm_init(), including its internal
 * controller lock, while a temporary kprobe changes only its second reset
 * write from 0 to 1.  The probe is disarmed immediately after the call.
 */
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/platform_device.h>

#define SWRM_COMP_SW_RESET	0x0008
#define SWRM_COMP_STATUS	0x0014
#define SWRM_INTERRUPT_STATUS	0x0200
#define SWRM_ENUM_ID1		0x0530
#define SWRM_ENUM_ID2		0x0534
#define SWRM_SLV_STATUS		0x1090

typedef int (*spx_init_fn)(void *ctrl);
typedef int (*spx_ahb_read_fn)(void *ctrl, int reg, u32 *val);

static struct device *swrm_dev;
static bool armed;
static unsigned int substitutions;

static void *resolve_symbol(const char *name)
{
	struct kprobe resolver = {
		.symbol_name = name,
	};
	void *addr;
	int ret;

	ret = register_kprobe(&resolver);
	if (ret)
		return NULL;
	addr = resolver.addr;
	unregister_kprobe(&resolver);
	return addr;
}

static int reset_write_entry(struct kprobe *probe, struct pt_regs *regs)
{
	/* aarch64: x0=ctrl, x1=register, x2=value */
	if (armed && regs->regs[1] == SWRM_COMP_SW_RESET &&
	    regs->regs[2] == 0) {
		regs->regs[2] = 1;
		substitutions++;
		pr_info("spx_swrm_reset_twice: substituted reset write 0 -> 1\n");
	}
	return 0;
}
NOKPROBE_SYMBOL(reset_write_entry);

static struct kprobe reset_write_probe = {
	.symbol_name = "qcom_swrm_ahb_reg_write",
	.pre_handler = reset_write_entry,
};

static int __init spx_swrm_reset_twice_init(void)
{
	spx_ahb_read_fn swrm_read;
	spx_init_fn swrm_init;
	void *ctrl;
	u32 comp = 0;
	u32 irq = 0;
	u32 slv = 0;
	u32 id1 = 0;
	u32 id2 = 0;
	int sample;
	int ret;

	swrm_dev = bus_find_device_by_name(&platform_bus_type, NULL,
					   "wcd934x-soundwire.5.auto");
	if (!swrm_dev)
		return -ENODEV;
	ctrl = dev_get_drvdata(swrm_dev);
	swrm_init = resolve_symbol("qcom_swrm_init.isra.0");
	swrm_read = resolve_symbol("qcom_swrm_ahb_reg_read");
	if (!ctrl || !swrm_init || !swrm_read) {
		ret = -ENOENT;
		goto err_put;
	}

	ret = register_kprobe(&reset_write_probe);
	if (ret)
		goto err_put;
	armed = true;
	ret = swrm_init(ctrl);
	armed = false;
	unregister_kprobe(&reset_write_probe);
	if (ret)
		goto err_put;
	if (substitutions != 1) {
		pr_err("spx_swrm_reset_twice: expected one substitution, got %u\n",
		       substitutions);
		ret = -EIO;
		goto err_put;
	}

	for (sample = 0; sample < 200; sample++) {
		swrm_read(ctrl, SWRM_COMP_STATUS, &comp);
		swrm_read(ctrl, SWRM_INTERRUPT_STATUS, &irq);
		swrm_read(ctrl, SWRM_SLV_STATUS, &slv);
		swrm_read(ctrl, SWRM_ENUM_ID1, &id1);
		swrm_read(ctrl, SWRM_ENUM_ID2, &id2);
		if (slv || id1 || id2)
			pr_info("spxrst %d/200 comp=%#x irq=%#x slv=%#x id1=%#x id2=%#x\n",
				sample + 1, comp, irq, slv, id1, id2);
		msleep(5);
	}
	pr_info("spx_swrm_reset_twice: complete comp=%#x irq=%#x slv=%#x id1=%#x id2=%#x\n",
		comp, irq, slv, id1, id2);
	return 0;

err_put:
	if (armed) {
		armed = false;
		unregister_kprobe(&reset_write_probe);
	}
	put_device(swrm_dev);
	swrm_dev = NULL;
	return ret;
}

static void __exit spx_swrm_reset_twice_exit(void)
{
	if (swrm_dev)
		put_device(swrm_dev);
	pr_info("spx_swrm_reset_twice: unloaded\n");
}

module_init(spx_swrm_reset_twice_init);
module_exit(spx_swrm_reset_twice_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX live Windows COMP_SW_RESET=1,1 diagnostic");
