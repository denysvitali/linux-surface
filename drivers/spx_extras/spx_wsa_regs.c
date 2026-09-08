// SPDX-License-Identifier: GPL-2.0
/* One-shot, read-only dump of the SPX WSA881x SoundWire port state. */
#include <linux/device.h>
#include <linux/module.h>
#include <linux/soundwire/sdw.h>
#include <linux/soundwire/sdw_registers.h>
#include <linux/soundwire/sdw_type.h>

#define SPX_WSA_DEVICE "sdw:0:0:0217:2010:00:1"
#define WSA881X_SAMPLE_EDGE_SEL 0x3044

struct spx_wsa_reg {
	u32 reg;
	const char *name;
};

#define SPX_DPN_REGS(n) \
	{ SDW_DPN_PORTCTRL(n), "DP" #n "_PORTCTRL" }, \
	{ SDW_DPN_PREPARESTATUS(n), "DP" #n "_PREPARESTATUS" }, \
	{ SDW_DPN_PREPARECTRL(n), "DP" #n "_PREPARECTRL" }, \
	{ SDW_DPN_CHANNELEN_B0(n), "DP" #n "_CHANNELEN_B0" }, \
	{ SDW_DPN_CHANNELEN_B1(n), "DP" #n "_CHANNELEN_B1" }, \
	{ SDW_DPN_SAMPLECTRL1_B0(n), "DP" #n "_SAMPLECTRL1_B0" }, \
	{ SDW_DPN_SAMPLECTRL1_B1(n), "DP" #n "_SAMPLECTRL1_B1" }, \
	{ SDW_DPN_OFFSETCTRL1_B0(n), "DP" #n "_OFFSETCTRL1_B0" }, \
	{ SDW_DPN_OFFSETCTRL1_B1(n), "DP" #n "_OFFSETCTRL1_B1" }, \
	{ SDW_DPN_OFFSETCTRL2_B0(n), "DP" #n "_OFFSETCTRL2_B0" }, \
	{ SDW_DPN_OFFSETCTRL2_B1(n), "DP" #n "_OFFSETCTRL2_B1" }, \
	{ SDW_DPN_HCTRL_B0(n), "DP" #n "_HCTRL_B0" }, \
	{ SDW_DPN_HCTRL_B1(n), "DP" #n "_HCTRL_B1" }

static const struct spx_wsa_reg spx_wsa_regs[] = {
	{ SDW_SCP_FRAMECTRL_B0, "SCP_FRAMECTRL_B0" },
	{ SDW_SCP_FRAMECTRL_B1, "SCP_FRAMECTRL_B1" },
	{ 0xe0, "SCP_HOST_CLK_DIV2_B0" },
	{ 0xf0, "SCP_HOST_CLK_DIV2_B1" },
	SPX_DPN_REGS(1),
	SPX_DPN_REGS(2),
	{ WSA881X_SAMPLE_EDGE_SEL, "WSA_SAMPLE_EDGE_SEL" },
};

static int __init spx_wsa_regs_init(void)
{
	struct sdw_slave *slave;
	struct device *dev;
	int i, ret = 0;

	dev = bus_find_device_by_name(&sdw_bus_type, NULL, SPX_WSA_DEVICE);
	if (!dev)
		return -ENODEV;

	slave = dev_to_sdw_dev(dev);
	if (slave->status != SDW_SLAVE_ATTACHED || !slave->dev_num) {
		ret = -ENODEV;
		goto out_put;
	}

	dev_info(dev, "SPX: === WSA dev%u SoundWire registers ===\n",
		 slave->dev_num);
	for (i = 0; i < ARRAY_SIZE(spx_wsa_regs); i++) {
		int val = sdw_read_no_pm(slave, spx_wsa_regs[i].reg);

		if (val < 0) {
			dev_err(dev, "SPX: %-24s (0x%04x) read failed: %d\n",
				spx_wsa_regs[i].name, spx_wsa_regs[i].reg, val);
			if (!ret)
				ret = val;
			continue;
		}

		dev_info(dev, "SPX: %-24s (0x%04x) = 0x%02x\n",
			 spx_wsa_regs[i].name, spx_wsa_regs[i].reg, val);
	}
	dev_info(dev, "SPX: === WSA register dump done ===\n");

out_put:
	put_device(dev);
	return ret;
}

static void __exit spx_wsa_regs_exit(void)
{
}

module_init(spx_wsa_regs_init);
module_exit(spx_wsa_regs_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX one-shot WSA881x SoundWire register dump");
