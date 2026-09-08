// SPDX-License-Identifier: GPL-2.0
/* One-shot writer for the SPX WSA881x registers under active investigation. */
#include <linux/device.h>
#include <linux/module.h>
#include <linux/soundwire/sdw.h>
#include <linux/soundwire/sdw_type.h>

#define SPX_WSA_DEVICE			"sdw:0:0:0217:2010:00:1"
#define WSA881X_CLOCK_CONFIG		0x3009
#define WSA881X_SAMPLE_EDGE_SEL		0x3044
#define WSA881X_SPKR_DRV_GAIN		0x311b
#define WSA881X_BOOST_PRESET_OUT1	0x312d

/* SoundWire slave registers used by the DAC/COMP transport. */
#define SPX_SCP_HOST_CLK_DIV2_B0		0x00e0
#define SPX_SCP_HOST_CLK_DIV2_B1		0x00f0
#define SPX_DP1_PORTCTRL			0x0102
#define SPX_DP1_BANK_FIRST		0x0122
#define SPX_DP1_BANK_LAST		0x0137
#define SPX_DP2_PORTCTRL			0x0202
#define SPX_DP2_BANK_FIRST		0x0222
#define SPX_DP2_BANK_LAST		0x0237

static uint wsa_reg;
module_param(wsa_reg, uint, 0400);
MODULE_PARM_DESC(wsa_reg, "Whitelisted WSA881x register address");

static uint wsa_val;
module_param(wsa_val, uint, 0400);
MODULE_PARM_DESC(wsa_val, "8-bit WSA881x register value");

static bool spx_wsa_reg_allowed(uint reg)
{
	return reg == WSA881X_CLOCK_CONFIG ||
	       reg == WSA881X_SAMPLE_EDGE_SEL ||
	       reg == WSA881X_SPKR_DRV_GAIN ||
	       reg == WSA881X_BOOST_PRESET_OUT1 ||
	       reg == SPX_SCP_HOST_CLK_DIV2_B0 ||
	       reg == SPX_SCP_HOST_CLK_DIV2_B1 ||
	       (reg >= 0x0100 && reg <= 0x013f) ||
	       (reg >= 0x0200 && reg <= 0x023f) ||
	       (reg >= 0x0300 && reg <= 0x033f);
}

static int __init spx_wsa_write_init(void)
{
	struct sdw_slave *slave;
	struct device *dev;
	int pass, ret;

	if (!spx_wsa_reg_allowed(wsa_reg) || wsa_val > 0xff)
		return -EINVAL;

	dev = bus_find_device_by_name(&sdw_bus_type, NULL, SPX_WSA_DEVICE);
	if (!dev)
		return -ENODEV;

	slave = dev_to_sdw_dev(dev);
	if (slave->status != SDW_SLAVE_ATTACHED || !slave->dev_num) {
		ret = -ENODEV;
		goto out_put;
	}

	/* Both physical amplifiers answer as device 1. Repeat a broadcast-style
	 * write so shared-address bus noise cannot turn a successful module load
	 * into a false timing result.
	 */
	for (pass = 0; pass < 3; pass++) {
		ret = sdw_write_no_pm(slave, wsa_reg, wsa_val);
		if (ret)
			break;
	}
	if (!ret)
		dev_info(dev, "SPX: WSA dev%u reg 0x%04x <- 0x%02x\n",
			 slave->dev_num, wsa_reg, wsa_val);

out_put:
	put_device(dev);
	return ret;
}

static void __exit spx_wsa_write_exit(void)
{
}

module_init(spx_wsa_write_init);
module_exit(spx_wsa_write_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX one-shot whitelisted WSA881x register writer");
