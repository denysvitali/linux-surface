// SPDX-License-Identifier: GPL-2.0
/*
 * SPX: dump the WCD9340 speaker (RX INT7/INT8 -> SoundWire) digital path.
 *
 * Everything from ALSA down to the WSA amp's analog stage has been proven
 * configured, yet playback is silent. The unverified step is whether the codec's
 * interpolator output is actually enabled and unmuted on its way to the SWR
 * master's data port. These reads come from the wcd934x regmap; non-volatile
 * registers are served from the driver's cache, so this reports what the driver
 * believes it programmed without putting traffic on a flaky control bus.
 *
 * Load during playback for a live picture. Fails with -EAGAIN by design so it
 * can be re-run without rmmod.
 */
#include <linux/mfd/wcd934x/registers.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>

struct spx_reg {
	unsigned int addr;
	const char *name;
};

static const struct spx_reg spkr_regs[] = {
	{ WCD934X_CDC_CLK_RST_CTRL_SWR_CONTROL, "CLK_RST_CTRL_SWR_CONTROL" },
	{ WCD934X_CDC_RX_INP_MUX_RX_INT7_CFG0,	"RX_INP_MUX_INT7_CFG0" },
	{ WCD934X_CDC_RX_INP_MUX_RX_INT7_CFG1,	"RX_INP_MUX_INT7_CFG1" },
	{ WCD934X_CDC_RX_INP_MUX_RX_INT8_CFG0,	"RX_INP_MUX_INT8_CFG0" },
	{ WCD934X_CDC_RX_INP_MUX_RX_INT8_CFG1,	"RX_INP_MUX_INT8_CFG1" },
	{ WCD934X_CDC_RX7_RX_PATH_CTL,		"RX7_PATH_CTL" },
	{ WCD934X_CDC_RX7_RX_PATH_CFG0,		"RX7_PATH_CFG0" },
	{ WCD934X_CDC_RX7_RX_PATH_CFG1,		"RX7_PATH_CFG1" },
	{ WCD934X_CDC_RX7_RX_PATH_CFG2,		"RX7_PATH_CFG2" },
	{ WCD934X_CDC_RX7_RX_VOL_CTL,		"RX7_VOL_CTL" },
	{ WCD934X_CDC_RX7_RX_PATH_MIX_CTL,	"RX7_PATH_MIX_CTL" },
	{ WCD934X_CDC_RX7_RX_PATH_SEC1,		"RX7_PATH_SEC1" },
	{ WCD934X_CDC_RX7_RX_PATH_DSMDEM_CTL,	"RX7_PATH_DSMDEM_CTL" },
	{ WCD934X_CDC_RX8_RX_PATH_CTL,		"RX8_PATH_CTL" },
	{ WCD934X_CDC_RX8_RX_PATH_CFG0,		"RX8_PATH_CFG0" },
	{ WCD934X_CDC_RX8_RX_VOL_CTL,		"RX8_VOL_CTL" },
	{ WCD934X_CDC_RX8_RX_PATH_DSMDEM_CTL,	"RX8_PATH_DSMDEM_CTL" },
	{ WCD934X_CDC_COMPANDER7_CTL3,		"COMPANDER7_CTL3" },
	{ WCD934X_CDC_COMPANDER7_CTL7,		"COMPANDER7_CTL7" },
	{ WCD934X_CDC_COMPANDER8_CTL3,		"COMPANDER8_CTL3" },
	{ WCD934X_CDC_COMPANDER8_CTL7,		"COMPANDER8_CTL7" },
	/*
	 * The WSA SD_N lines. Enumeration drives pin1 high to wake the amp, so
	 * high must be "active" -- if anything puts these back low afterwards
	 * the amp sits in reset while every other register still reads
	 * perfectly, which looks exactly like the silence being chased.
	 */
	{ 0x0042,				"WCD_GPIO_DIR (SD_N dir)" },
	{ 0x0043,				"WCD_GPIO_VAL (SD_N val)" },
};

static int __init spx_wcd_spkr_path_init(void)
{
	struct wcd934x_ddata *dd;
	struct device *dev;
	int i;

	dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
	if (!dev) {
		pr_err("spx_spkr_path: codec not found\n");
		return -ENODEV;
	}
	dd = dev_get_drvdata(dev);
	put_device(dev);
	if (!dd || !dd->regmap) {
		pr_err("spx_spkr_path: no codec regmap\n");
		return -ENODEV;
	}

	pr_info("spx_spkr_path: === WCD9340 speaker digital path ===\n");
	for (i = 0; i < ARRAY_SIZE(spkr_regs); i++) {
		unsigned int val = 0;
		int ret;

		ret = regmap_read(dd->regmap, spkr_regs[i].addr, &val);
		pr_info("spx_spkr_path: %-24s (0x%04x) = 0x%02x rc=%d\n",
			spkr_regs[i].name, spkr_regs[i].addr, val, ret);
	}
	pr_info("spx_spkr_path: === done ===\n");

	return -EAGAIN;
}

static void __exit spx_wcd_spkr_path_exit(void)
{
}

module_init(spx_wcd_spkr_path_init);
module_exit(spx_wcd_spkr_path_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX: dump the WCD9340 RX INT7/INT8 speaker path registers");
