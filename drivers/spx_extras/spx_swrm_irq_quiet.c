// SPDX-License-Identifier: GPL-2.0
/* Emergency one-shot: stop a WCD9340 SoundWire threaded-IRQ relatch loop. */
#include <linux/completion.h>
#include <linux/device.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/soundwire/sdw.h>

struct clk;
struct dentry;
struct spx_qcom_swrm_to_intr_mask {
	struct sdw_bus bus;
	struct device *dev;
	struct regmap *regmap;
	u32 max_reg;
	const unsigned int *reg_layout;
	void __iomem *mmio;
	struct reset_control *audio_cgcr;
#ifdef CONFIG_DEBUG_FS
	struct dentry *debugfs;
#endif
	struct completion broadcast;
	struct completion enumeration;
	struct mutex ahb_lock;
	struct mutex controller_lock;
	struct mutex port_lock;
	struct clk *hclk;
	int irq;
	unsigned int version;
	int wake_irq;
	int num_din_ports;
	int num_dout_ports;
	int cols_index;
	int rows_index;
	unsigned long port_mask;
	u32 intr_mask;
};

typedef int (*spx_write_fn)(void *ctrl, int reg, int val);

static void *resolve_symbol(const char *name)
{
	struct kprobe resolver = { .symbol_name = name };
	void *addr;
	int ret = register_kprobe(&resolver);

	if (ret)
		return NULL;
	addr = resolver.addr;
	unregister_kprobe(&resolver);
	return addr;
}

static int __init spx_swrm_irq_quiet_init(void)
{
	struct device *dev;
	struct regmap *wcd;
	spx_write_fn write;
	void *ctrl;
	int ret;

	dev = bus_find_device_by_name(&platform_bus_type, NULL,
				      "wcd934x-soundwire.5.auto");
	if (!dev)
		return -ENODEV;
	ctrl = dev_get_drvdata(dev);
	wcd = dev_get_regmap(dev->parent, NULL);
	write = resolve_symbol("qcom_swrm_ahb_reg_write");
	if (!ctrl || !wcd || !write) {
		ret = -ENOENT;
		goto out;
	}
	WRITE_ONCE(((struct spx_qcom_swrm_to_intr_mask *)ctrl)->intr_mask, 0);
	ret = regmap_write(wcd, 0x0c95, 0x03);
	if (ret)
		goto out;
	ret = write(ctrl, 0x0210, 0);
	if (!ret)
		ret = write(ctrl, 0x0204, 0);
	if (!ret)
		pr_info("spxirqquiet: software/hardware master IRQ masks disabled\n");
out:
	put_device(dev);
	return ret;
}

static void __exit spx_swrm_irq_quiet_exit(void) {}
module_init(spx_swrm_irq_quiet_init);
module_exit(spx_swrm_irq_quiet_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX one-shot SoundWire IRQ livelock breaker");
