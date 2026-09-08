// SPDX-License-Identifier: GPL-2.0
/* Locked, read-only snapshot of the live WCD9340 SoundWire master. */
#include <linux/completion.h>
#include <linux/device.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/soundwire/sdw.h>

struct dentry;
struct spx_qcom_swrm_prefix {
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
};

typedef int (*spx_read_fn)(void *ctrl, int reg, u32 *val);

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

static int __init spx_swrm_live_health_init(void)
{
	static const struct {
		u32 reg;
		const char *name;
	} regs[] = {
		{ 0x0004, "COMP_CFG" },
		{ 0x0014, "COMP_STATUS" },
		{ 0x0018, "LINK_EE" },
		{ 0x0200, "IRQ_STATUS" },
		{ 0x0204, "IRQ_MASK" },
		{ 0x0210, "IRQ_CPU_EN" },
		{ 0x030c, "FIFO_STATUS" },
		{ 0x0314, "FIFO_CFG" },
		{ 0x0500, "ENUM_CFG" },
		{ 0x0538, "DEV1_ID1" },
		{ 0x053c, "DEV1_ID2" },
		{ 0x0540, "DEV2_ID1" },
		{ 0x0544, "DEV2_ID2" },
		{ 0x101c, "FRAME_B0" },
		{ 0x105c, "FRAME_B1" },
		{ 0x1048, "MCP_CFG" },
		{ 0x1044, "BUS_CTRL" },
		{ 0x104c, "MCP_STATUS" },
		{ 0x1090, "SLV_STATUS" },
		{ 0x1124, "DP1_PORT_B0" },
		{ 0x1164, "DP1_PORT_B1" },
		{ 0x1128, "DP1_CTRL2_B0" },
		{ 0x1168, "DP1_CTRL2_B1" },
		{ 0x112c, "DP1_BLOCK1" },
		{ 0x1130, "DP1_BLOCK2" },
		{ 0x1134, "DP1_HCTRL" },
		{ 0x1138, "DP1_BLOCK3" },
		{ 0x1424, "DP4_PORT_B0" },
		{ 0x1464, "DP4_PORT_B1" },
		{ 0x1428, "DP4_CTRL2_B0" },
		{ 0x1468, "DP4_CTRL2_B1" },
		{ 0x142c, "DP4_BLOCK1" },
		{ 0x1430, "DP4_BLOCK2" },
		{ 0x1434, "DP4_HCTRL" },
		{ 0x1438, "DP4_BLOCK3" },
	};
	struct spx_qcom_swrm_prefix *ctrl;
	struct device *dev;
	struct regmap *wcd;
	unsigned int saved_access;
	spx_read_fn read;
	unsigned int i;

	dev = bus_find_device_by_name(&platform_bus_type, NULL,
				      "wcd934x-soundwire.5.auto");
	if (!dev)
		return -ENODEV;
	ctrl = dev_get_drvdata(dev);
	wcd = dev_get_regmap(dev->parent, NULL);
	read = resolve_symbol("qcom_swrm_ahb_reg_read");
	if (!ctrl || !wcd || !read) {
		put_device(dev);
		return -ENOENT;
	}
	if (regmap_read(wcd, 0x0c95, &saved_access)) {
		put_device(dev);
		return -EIO;
	}

	mutex_lock(&ctrl->controller_lock);
	for (i = 0; i < ARRAY_SIZE(regs); i++) {
		u32 val = ~0U;
		int ret;

		regmap_write(wcd, 0x0c95, 0x0c);
		ret = read(ctrl, regs[i].reg, &val);
		pr_info("spxhealth %-12s reg=%#x val=%#x ret=%d\n",
			regs[i].name, regs[i].reg, val, ret);
	}
	mutex_unlock(&ctrl->controller_lock);
	regmap_write(wcd, 0x0c95, saved_access);
	put_device(dev);
	return 0;
}

static void __exit spx_swrm_live_health_exit(void)
{
	pr_info("spx_swrm_live_health: unloaded\n");
}

module_init(spx_swrm_live_health_init);
module_exit(spx_swrm_live_health_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX locked read-only live SoundWire health snapshot");
