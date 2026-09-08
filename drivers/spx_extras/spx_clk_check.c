// SPDX-License-Identifier: GPL-2.0
#include <linux/device.h>
#include <linux/mfd/wcd934x/registers.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>

static int spx_read_fresh(struct regmap *map, unsigned int reg,
			  unsigned int *value)
{
	int ret;

	/* Bypassed reads change the paged selector without updating its cache.
	 * Evict only the requested value, retaining normal selector bookkeeping.
	 * Offset zero aliases the page selector; retain its cached value.
	 */
	if (reg == 0)
		return regmap_read(map, reg, value);
	ret = regcache_drop_region(map, reg, reg);
	if (ret)
		return ret;
	return regmap_read(map, reg, value);
}

static int __init spx_init(void)
{
	struct wcd934x_ddata *dd;
	struct device *dev;
	unsigned int val, raw;
	int i;
	static const unsigned int regs[] = {
		0x0000, 0x0001, 0x0002, 0x0003, /* page-zero controls */
		WCD934X_CLK_SYS_MCLK_PRG,
		WCD934X_CDC_CLK_RST_CTRL_MCLK_CONTROL,
		WCD934X_CDC_CLK_RST_CTRL_FS_CNT_CONTROL,
		WCD934X_CDC_CLK_RST_CTRL_SWR_CONTROL,
		0x8005, 0x8006,                 /* SWR DATA/CLK pad config */
		0x803b, 0x803e,                 /* pad drive / NPL delay */
		0x0bcd, 0x0bce, 0x0bcf, 0x0bd1, 0x0bdf,
		0x0be1, 0x0be2, 0x0be3, 0x0be5, 0x0bf3,
		0x0c19, 0x0c1a, 0x0c1b, 0x0c1c,
		0x0c21, 0x0c22, 0x0c23, 0x0c24,
		0x0b39, 0x0b3c, 0x0b40,
		0x0d0f, 0x0d10, 0x0d11, 0x0d12,
		0x0051, 0x0052,
		0x0042, 0x0043,
	};
	static const char *names[] = {
		"PAGE_SELECTOR", "RPM_CTL1", "RPM_CLK_GATE", "RPM_MCLK_CFG",
		"SYS_MCLK_PRG", "MCLK_CTL", "FS_CNT_CTL", "SWR_CTL",
		"SWR_DATA_PINCFG", "SWR_CLK_PINCFG", "PAD_DRVCTL_0",
		"NPL_DLY",
		"RX7_CTL", "RX7_CFG0", "RX7_CFG1", "RX7_VOL", "RX7_DSMDEM",
		"RX8_CTL", "RX8_CFG0", "RX8_CFG1", "RX8_VOL", "RX8_DSMDEM",
		"BOOST0_PATH", "BOOST0_CTL", "BOOST0_CFG1", "BOOST0_CFG2",
		"BOOST1_PATH", "BOOST1_CTL", "BOOST1_CFG1", "BOOST1_CFG2",
		"COMP8_CTL0", "COMP8_CTL3", "COMP8_CTL7",
		"RX7_INP_MUX0", "RX7_INP_MUX1", "RX8_INP_MUX0", "RX8_INP_MUX1",
		"DATA_HUB_RX0_CFG", "DATA_HUB_RX1_CFG",
		"GPIO_DIRECTION", "GPIO_DATA",
	};

	dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
	if (!dev) return -ENODEV;
	dd = dev_get_drvdata(dev);
	if (!dd || !dd->regmap) { put_device(dev); return -ENODEV; }

	for (i = 0; i < ARRAY_SIZE(regs); i++) {
		int cached_ret, raw_ret;

		val = 0xdead;
		raw = 0xdead;
		cached_ret = regmap_read(dd->regmap, regs[i], &val);
		raw_ret = spx_read_fresh(dd->regmap, regs[i], &raw);
		pr_info("spx_clk: %s (0x%04x) cached=0x%04x raw=0x%04x rc=%d/%d\n",
			names[i], regs[i], val, raw, cached_ret, raw_ret);
	}
	for (i = 0; i <= 18; i++) {
		unsigned int left = 0xdead, right = 0xdead;
		int left_ret, right_ret;

		if (i == 12) /* No RX_PATH_SEC4 register. */
			continue;
		left_ret = spx_read_fresh(dd->regmap, 0x0bcd + i, &left);
		right_ret = spx_read_fresh(dd->regmap, 0x0be1 + i, &right);
		pr_info("spx_clk: RX pair +%#x left=%#x right=%#x rc=%d/%d\n",
			i, left, right, left_ret, right_ret);
	}
	for (i = 0; i < 8; i++) {
		unsigned int left = 0xdead, right = 0xdead;
		int lr = spx_read_fresh(dd->regmap, 0x0b31 + i, &left);
		int rr = spx_read_fresh(dd->regmap, 0x0b39 + i, &right);
		pr_info("spx_clk: COMP pair +%#x left=%#x right=%#x rc=%d/%d\n",
			i, left, right, lr, rr);
	}
	put_device(dev);
	return 0;
}
static void __exit spx_exit(void) {}
module_init(spx_init);
module_exit(spx_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX read-only codec clock and speaker-path snapshot");
