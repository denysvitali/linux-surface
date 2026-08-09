// SPDX-License-Identifier: GPL-2.0
/* Broadcast the known WSA881x DAC/COMP/BOOST SoundWire port schedule on SPX. */
#include <linux/device.h>
#include <linux/module.h>
#include <linux/soundwire/sdw.h>
#include <linux/soundwire/sdw_registers.h>
#include <linux/soundwire/sdw_type.h>

#define SPX_WSA_DEVICE "sdw:0:0:0217:2010:00:1"
#define SPX_SCP_HOST_CLK_DIV2_B0 0xe0
#define SPX_SCP_HOST_CLK_DIV2_B1 0xf0

struct spx_sdw_reg {
	u32 reg;
	u8 val;
	const char *name;
};

static const struct spx_sdw_reg spx_wsa_port_config[] = {
	{ SPX_SCP_HOST_CLK_DIV2_B0, 0x01, "HOST_CLK_DIV2_B0" },
	{ SPX_SCP_HOST_CLK_DIV2_B1, 0x01, "HOST_CLK_DIV2_B1" },
	{ SDW_SCP_FRAMECTRL_B0, 0x07, "FRAMECTRL_B0" },
	{ SDW_SCP_FRAMECTRL_B1, 0x07, "FRAMECTRL_B1" },

	{ SDW_DPN_PORTCTRL(1), 0x00, "DP1_PORTCTRL" },
	{ SDW_DPN_SAMPLECTRL1_B0(1), 0x06, "DP1_SAMPLECTRL1_B0" },
	{ SDW_DPN_SAMPLECTRL1_B1(1), 0x06, "DP1_SAMPLECTRL1_B1" },
	{ SDW_DPN_OFFSETCTRL1_B0(1), 0x01, "DP1_OFFSETCTRL1_B0" },
	{ SDW_DPN_OFFSETCTRL1_B1(1), 0x01, "DP1_OFFSETCTRL1_B1" },
	{ SDW_DPN_OFFSETCTRL2_B0(1), 0x00, "DP1_OFFSETCTRL2_B0" },
	{ SDW_DPN_OFFSETCTRL2_B1(1), 0x00, "DP1_OFFSETCTRL2_B1" },
	{ SDW_DPN_HCTRL_B0(1), 0x07, "DP1_HCTRL_B0" },
	{ SDW_DPN_HCTRL_B1(1), 0x07, "DP1_HCTRL_B1" },
	{ SDW_DPN_BLOCKCTRL3_B0(1), 0x00, "DP1_BLOCKCTRL3_B0" },
	{ SDW_DPN_BLOCKCTRL3_B1(1), 0x00, "DP1_BLOCKCTRL3_B1" },

	{ SDW_DPN_PORTCTRL(2), 0x00, "DP2_PORTCTRL" },
	{ SDW_DPN_SAMPLECTRL1_B0(2), 0x1e, "DP2_SAMPLECTRL1_B0" },
	{ SDW_DPN_SAMPLECTRL1_B1(2), 0x1e, "DP2_SAMPLECTRL1_B1" },
	{ SDW_DPN_OFFSETCTRL1_B0(2), 0x02, "DP2_OFFSETCTRL1_B0" },
	{ SDW_DPN_OFFSETCTRL1_B1(2), 0x02, "DP2_OFFSETCTRL1_B1" },
	{ SDW_DPN_OFFSETCTRL2_B0(2), 0x00, "DP2_OFFSETCTRL2_B0" },
	{ SDW_DPN_OFFSETCTRL2_B1(2), 0x00, "DP2_OFFSETCTRL2_B1" },
	{ SDW_DPN_BLOCKCTRL3_B0(2), 0x00, "DP2_BLOCKCTRL3_B0" },
	{ SDW_DPN_BLOCKCTRL3_B1(2), 0x00, "DP2_BLOCKCTRL3_B1" },

	{ SDW_DPN_PORTCTRL(3), 0x03, "DP3_PORTCTRL" },
	{ SDW_DPN_SAMPLECTRL1_B0(3), 0x3e, "DP3_SAMPLECTRL1_B0" },
	{ SDW_DPN_SAMPLECTRL1_B1(3), 0x3e, "DP3_SAMPLECTRL1_B1" },
	{ SDW_DPN_OFFSETCTRL1_B0(3), 0x0c, "DP3_OFFSETCTRL1_B0" },
	{ SDW_DPN_OFFSETCTRL1_B1(3), 0x0c, "DP3_OFFSETCTRL1_B1" },
	{ SDW_DPN_OFFSETCTRL2_B0(3), 0x1f, "DP3_OFFSETCTRL2_B0" },
	{ SDW_DPN_OFFSETCTRL2_B1(3), 0x1f, "DP3_OFFSETCTRL2_B1" },
	{ SDW_DPN_HCTRL_B0(3), 0x07, "DP3_HCTRL_B0" },
	{ SDW_DPN_HCTRL_B1(3), 0x07, "DP3_HCTRL_B1" },
	{ SDW_DPN_BLOCKCTRL3_B0(3), 0x00, "DP3_BLOCKCTRL3_B0" },
	{ SDW_DPN_BLOCKCTRL3_B1(3), 0x00, "DP3_BLOCKCTRL3_B1" },
};

static int __init spx_wsa_port_config_init(void)
{
	struct sdw_slave *slave;
	struct device *dev;
	int i, pass, ret = 0;

	dev = bus_find_device_by_name(&sdw_bus_type, NULL, SPX_WSA_DEVICE);
	if (!dev)
		return -ENODEV;

	slave = dev_to_sdw_dev(dev);
	if (slave->status != SDW_SLAVE_ATTACHED || !slave->dev_num) {
		ret = -ENODEV;
		goto out_put;
	}

	/* Both physical amplifiers have device number 1. Repeating the write
	 * protects this one-shot setup from their shared-address alert noise.
	 */
	for (pass = 0; pass < 3; pass++) {
		for (i = 0; i < ARRAY_SIZE(spx_wsa_port_config); i++) {
			const struct spx_sdw_reg *r = &spx_wsa_port_config[i];

			ret = sdw_write_no_pm(slave, r->reg, r->val);
			if (ret < 0)
				goto out_put;
		}
	}

	if (!ret)
		dev_info(dev, "SPX: DAC/COMP/BOOST port schedule programmed\n");
out_put:
	put_device(dev);
	return ret;
}

static void __exit spx_wsa_port_config_exit(void)
{
}

module_init(spx_wsa_port_config_init);
module_exit(spx_wsa_port_config_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX WSA881x broadcast SoundWire port configuration");
