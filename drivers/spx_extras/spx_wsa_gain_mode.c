// SPDX-License-Identifier: GPL-2.0
/* One-shot SPX WSA881x PA gain-mode writer. */
#include <linux/device.h>
#include <linux/module.h>
#include <linux/soundwire/sdw.h>
#include <linux/soundwire/sdw_type.h>

#define SPX_WSA_DEVICE		"sdw:0:0:0217:2010:00:1"
#define WSA881X_SPKR_DRV_GAIN	0x311b
#define WSA881X_GAIN_MODE_DRE	0x41
#define WSA881X_GAIN_MODE_REG	0x49
#define WSA881X_PWM_MASK		0x06

static uint gain_mode = WSA881X_GAIN_MODE_DRE;
module_param(gain_mode, uint, 0400);
MODULE_PARM_DESC(gain_mode,
		 "WSA881x DRV_GAIN value (0x41/43/45/47 DRE or 0x49 register mode)");

static int __init spx_wsa_gain_mode_init(void)
{
	struct sdw_slave *slave;
	struct device *dev;
	int ret;

	if ((gain_mode & ~WSA881X_PWM_MASK) != WSA881X_GAIN_MODE_DRE &&
	    gain_mode != WSA881X_GAIN_MODE_REG)
		return -EINVAL;

	dev = bus_find_device_by_name(&sdw_bus_type, NULL, SPX_WSA_DEVICE);
	if (!dev)
		return -ENODEV;

	slave = dev_to_sdw_dev(dev);
	if (slave->status != SDW_SLAVE_ATTACHED || !slave->dev_num) {
		ret = -ENODEV;
		goto out_put;
	}

	ret = sdw_write_no_pm(slave, WSA881X_SPKR_DRV_GAIN, gain_mode);
	if (!ret)
		dev_info(dev, "SPX: WSA dev%u DRV_GAIN <- 0x%02x\n",
			 slave->dev_num, gain_mode);

out_put:
	put_device(dev);
	return ret;
}

static void __exit spx_wsa_gain_mode_exit(void)
{
}

module_init(spx_wsa_gain_mode_init);
module_exit(spx_wsa_gain_mode_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX one-shot WSA881x PA gain-mode writer");
