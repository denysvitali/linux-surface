// SPDX-License-Identifier: GPL-2.0
#include <linux/device.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>
#include <linux/delay.h>

#define SPX_CODEC_DEVICE "217:250:1:0"
#define WCD934X_SWR_CLK_CTL 0xd43

static int __init spx_init(void)
{
	struct wcd934x_ddata *dd;
	struct device *dev;
	unsigned int val;

	dev = bus_find_device_by_name(&slimbus_bus, NULL, SPX_CODEC_DEVICE);
	if (!dev) return -ENODEV;
	dd = dev_get_drvdata(dev);
	if (!dd || !dd->regmap) { put_device(dev); return -ENODEV; }

	regmap_read(dd->regmap, WCD934X_SWR_CLK_CTL, &val);
	pr_info("spx_swr_clk: before=0x%02x, disabling\n", val);
	regmap_write(dd->regmap, WCD934X_SWR_CLK_CTL, 0x00);
	msleep(100);
	regmap_write(dd->regmap, WCD934X_SWR_CLK_CTL, 0x01);
	msleep(100);
	regmap_read(dd->regmap, WCD934X_SWR_CLK_CTL, &val);
	pr_info("spx_swr_clk: after=0x%02x, clock restarted\n", val);
	put_device(dev);
	return 0;
}
static void __exit spx_exit(void) {}
module_init(spx_init);
module_exit(spx_exit);
MODULE_LICENSE("GPL");
