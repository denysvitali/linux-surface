// SPDX-License-Identifier: GPL-2.0
#include <linux/device.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>

static int __init spx_init(void)
{
	struct wcd934x_ddata *dd;
	struct device *dev;
	unsigned int val;
	int i;
	static const unsigned int regs[] = {
		0x0000, 0x0001, 0x0002, 0x0003, /* chip ID */
		0x0d40, 0x0d41, 0x0d42, 0x0d43, /* CLK_RST_CTRL */
		0x8005, 0x8006,                 /* SWR DATA/CLK pad config */
		0x803b, 0x803e,                 /* pad drive / NPL delay */
	};
	static const char *names[] = {
		"CHIP_ID0", "CHIP_ID1", "CHIP_ID2", "CHIP_ID3",
		"MCLK_CTL", "FS_CNT_CTL", "MCLK2_CTL", "SWR_CTL",
		"SWR_DATA_PINCFG", "SWR_CLK_PINCFG", "PAD_DRVCTL_0",
		"NPL_DLY",
	};

	dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
	if (!dev) return -ENODEV;
	dd = dev_get_drvdata(dev);
	if (!dd || !dd->regmap) { put_device(dev); return -ENODEV; }

	for (i = 0; i < ARRAY_SIZE(regs); i++) {
		val = 0xdead;
		regmap_read(dd->regmap, regs[i], &val);
		pr_info("spx_clk: %s (0x%04x) = 0x%04x\n", names[i], regs[i], val);
	}
	put_device(dev);
	return 0;
}
static void __exit spx_exit(void) {}
module_init(spx_init);
module_exit(spx_exit);
MODULE_LICENSE("GPL");
