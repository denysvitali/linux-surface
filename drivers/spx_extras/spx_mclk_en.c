// SPDX-License-Identifier: GPL-2.0
#include <linux/device.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>
#include <linux/delay.h>

/* Toggle WSA enable pin2: HIGH (disable) -> wait -> LOW (enable) */
static int __init spx_init(void)
{
	struct wcd934x_ddata *dd;
	struct device *dev;
	unsigned int val;

	dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
	if (!dev) return -ENODEV;
	dd = dev_get_drvdata(dev);
	if (!dd || !dd->regmap) { put_device(dev); return -ENODEV; }

	regmap_read(dd->regmap, 0x43, &val);
	pr_info("spx_pin2: GPIO_VAL before=0x%02x\n", val);

	/* Drive pin2 HIGH (disable amps) */
	regmap_update_bits(dd->regmap, 0x43, 0x04, 0x04);
	regmap_read(dd->regmap, 0x43, &val);
	pr_info("spx_pin2: pin2 HIGH (disabled), GPIO_VAL=0x%02x\n", val);
	msleep(2000);

	/* Drive pin2 LOW (enable amps) */
	regmap_update_bits(dd->regmap, 0x43, 0x04, 0x00);
	regmap_read(dd->regmap, 0x43, &val);
	pr_info("spx_pin2: pin2 LOW (enabled), GPIO_VAL=0x%02x\n", val);
	msleep(3000);

	/* Also toggle pin1 (SD_N) for full reset */
	regmap_update_bits(dd->regmap, 0x43, 0x02, 0x02); /* pin1 HIGH = shutdown */
	msleep(1000);
	regmap_update_bits(dd->regmap, 0x43, 0x02, 0x00); /* pin1 LOW = active */
	regmap_read(dd->regmap, 0x43, &val);
	pr_info("spx_pin2: after full toggle, GPIO_VAL=0x%02x\n", val);
	msleep(3000);

	pr_info("spx_pin2: toggle complete, check MCP_SLV_STATUS now\n");
	put_device(dev);
	return 0;
}
static void __exit spx_exit(void) {}
module_init(spx_init);
module_exit(spx_exit);
MODULE_LICENSE("GPL");
