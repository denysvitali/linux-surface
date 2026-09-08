// SPDX-License-Identifier: GPL-2.0
/*
 * SPX: direct WCD934x GPIO control via the codec regmap.
 *
 * The two WSA881x amplifiers are gated by WCD934x GPIOs. Both DT speaker
 * nodes currently name the SAME pin (wcdgpio 1), so both amps power up
 * together, both sit unenumerated at device 0, and both answer PING at once
 * -> bus clash -> MCP_SLV_STATUS reads 0.
 *
 * This module lets us drive the pins independently at runtime (bypassing
 * gpiolib, which has wedged on this machine) so we can bring the amps up one
 * at a time and watch MCP_SLV_STATUS.
 *
 * Pin polarity measured on Surface Pro X: HIGH = amp powered, LOW = off.
 *
 * Usage (dir/val supply managed bits 1-2; all other GPIO bits are preserved):
 *   insmod spx_wcd_gpio.ko dir=0x06 val=0x02   # pin1 HIGH (on), pin2 LOW (off)
 *   insmod spx_wcd_gpio.ko                     # read-only dump
 */
#include <linux/device.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>

/* The SWR master platform device; its parent is the SLIMbus codec device that
 * carries the WCD934x regmap. Using the platform bus avoids a link-time
 * dependency on the slimbus module's exported bus symbol. */
static const char * const spx_swr_devices[] = {
	"wcd934x-soundwire.6.auto",
	"wcd934x-soundwire.5.auto",
};
#define WCD_REG_DIR_CTL		0x42
#define WCD_REG_VAL_CTL		0x43

static int dir = -1;
module_param(dir, int, 0400);
MODULE_PARM_DESC(dir, "Raw value for GPIO direction reg 0x42 (-1 = don't touch)");

static int val = -1;
module_param(val, int, 0400);
MODULE_PARM_DESC(val, "Raw value for GPIO value reg 0x43 (-1 = don't touch)");

static int __init spx_wcd_gpio_init(void)
{
	struct regmap *map = NULL;
	struct device *dev, *anc;
	unsigned int d0, v0, d1, v1;
	int ret;

	dev = NULL;
	for (ret = 0; ret < ARRAY_SIZE(spx_swr_devices) && !dev; ret++)
		dev = bus_find_device_by_name(&platform_bus_type, NULL,
					      spx_swr_devices[ret]);
	if (!dev)
		return -ENODEV;

	for (anc = dev->parent; anc; anc = anc->parent) {
		map = dev_get_regmap(anc, NULL);
		if (map)
			break;
	}
	if (!map) {
		dev_err(dev, "SPX GPIO: no WCD regmap in parent chain\n");
		ret = -ENODEV;
		goto out_put;
	}

	ret = regmap_read(map, WCD_REG_DIR_CTL, &d0);
	if (ret)
		goto out_put;
	ret = regmap_read(map, WCD_REG_VAL_CTL, &v0);
	if (ret)
		goto out_put;

	dev_info(dev, "SPX GPIO before: dir(0x42)=0x%02x val(0x43)=0x%02x\n",
		 d0, v0);

	if (dir >= 0) {
		ret = regmap_update_bits(map, WCD_REG_DIR_CTL, 0x06, dir & 0x06);
		if (ret)
			goto out_put;
	}
	if (val >= 0) {
		ret = regmap_update_bits(map, WCD_REG_VAL_CTL, 0x06, val & 0x06);
		if (ret)
			goto out_put;
	}

	ret = regmap_read(map, WCD_REG_DIR_CTL, &d1);
	if (ret)
		goto out_put;
	ret = regmap_read(map, WCD_REG_VAL_CTL, &v1);
	if (ret)
		goto out_put;

	dev_info(dev, "SPX GPIO after:  dir(0x42)=0x%02x val(0x43)=0x%02x\n",
		 d1, v1);
	dev_info(dev, "SPX GPIO managed: dir=0x%02x val=0x%02x\n",
		 d1 & 0x06, v1 & 0x06);
	ret = 0;

out_put:
	put_device(dev);
	/* Always fail the load so the module never stays resident; the work is
	 * done in init and this keeps insmod re-runnable without rmmod. */
	return ret ? ret : -EAGAIN;
}

static void __exit spx_wcd_gpio_exit(void)
{
}

module_init(spx_wcd_gpio_init);
module_exit(spx_wcd_gpio_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX direct WCD934x GPIO control for WSA amp sequencing");
