// SPDX-License-Identifier: GPL-2.0
// Copyright (c) 2019, Linaro Limited

#include <linux/clk.h>
#include <linux/debugfs.h>
#include <linux/gpio/consumer.h>
#include <linux/interrupt.h>
#include <linux/kernel.h>
#include <linux/mfd/core.h>
#include <linux/mfd/wcd934x/registers.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_irq.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/regulator/consumer.h>
#include <linux/slimbus.h>
#include <linux/uaccess.h>

#define WCD934X_REGMAP_IRQ_REG(_irq, _off, _mask)		\
	[_irq] = {						\
		.reg_offset = (_off),				\
		.mask = (_mask),				\
		.type = {					\
			.type_reg_offset = (_off),		\
			.types_supported = IRQ_TYPE_EDGE_BOTH,	\
			.type_reg_mask  = (_mask),		\
			.type_level_low_val = (_mask),		\
			.type_level_high_val = (_mask),		\
			.type_falling_val = 0,			\
			.type_rising_val = 0,			\
		},						\
	}

/*
 * SPX: the two internal WSA881x speaker amps share a codec-GPIO enable line
 * that the stock wsa881x driver never drives (it only manages the per-amp
 * "powerdown" GPIO on wcd-gpio pin 1, like db845c). On the Surface Pro X the
 * amps also hang off wcd-gpio pin 2. Direct electrical probing established
 * that physical HIGH powers an amp and LOW turns it off. This legacy one-pin
 * override is boot-only and opt-in; default -1 leaves all boards unchanged.
 *   set: wcd934x.spx_wsa_en_pin=2   (the wcd-gpio pin index to power on)
 */
static int spx_wsa_en_pin = -1;
module_param(spx_wsa_en_pin, int, 0444);
MODULE_PARM_DESC(spx_wsa_en_pin,
	"SPX: force this wcd934x GPIO pin output-high at bring-up to power one WSA amp (-1=off)");

/*
 * SPX: raw boot-time control of the wcd934x GPIO block, applied before the
 * SoundWire master child is added.
 *
 * The two WSA881x amps are gated by pins 1 and 2. Only those managed bits are
 * changed; unrelated WCD GPIO state is preserved.
 *
 *   wcd934x.spx_wsa_gpio_dir=0x06 wcd934x.spx_wsa_gpio_val=0x06
 */
static int spx_wsa_gpio_dir = -1;
module_param(spx_wsa_gpio_dir, int, 0444);
MODULE_PARM_DESC(spx_wsa_gpio_dir,
	"SPX: raw wcd934x GPIO direction reg 0x42 value at bring-up (-1=off)");

static int spx_wsa_gpio_val = -1;
module_param(spx_wsa_gpio_val, int, 0444);
MODULE_PARM_DESC(spx_wsa_gpio_val,
	"SPX: raw wcd934x GPIO value reg 0x43 value at bring-up (-1=off)");

/* wcd934x GPIO block (see drivers/gpio/gpio-wcd934x.c): dir/value at 0x42/0x43 */
#define WCD934X_GPIO_DIR_CTL	0x42
#define WCD934X_GPIO_VAL_CTL	0x43
#define SPX_WSA_GPIO_MASK	0x06

static const struct mfd_cell wcd934x_devices[] = {
	{
		.name = "wcd934x-codec",
	}, {
		.name = "wcd934x-gpio",
		.of_compatible = "qcom,wcd9340-gpio",
	}, {
		.name = "wcd934x-soundwire",
		.of_compatible = "qcom,soundwire-v1.3.0",
	},
};

static const struct regmap_irq wcd934x_irqs[] = {
	WCD934X_REGMAP_IRQ_REG(WCD934X_IRQ_SLIMBUS, 0, BIT(0)),
	WCD934X_REGMAP_IRQ_REG(WCD934X_IRQ_HPH_PA_OCPL_FAULT, 0, BIT(2)),
	WCD934X_REGMAP_IRQ_REG(WCD934X_IRQ_HPH_PA_OCPR_FAULT, 0, BIT(3)),
	WCD934X_REGMAP_IRQ_REG(WCD934X_IRQ_MBHC_SW_DET, 1, BIT(0)),
	WCD934X_REGMAP_IRQ_REG(WCD934X_IRQ_MBHC_ELECT_INS_REM_DET, 1, BIT(1)),
	WCD934X_REGMAP_IRQ_REG(WCD934X_IRQ_MBHC_BUTTON_PRESS_DET, 1, BIT(2)),
	WCD934X_REGMAP_IRQ_REG(WCD934X_IRQ_MBHC_BUTTON_RELEASE_DET, 1, BIT(3)),
	WCD934X_REGMAP_IRQ_REG(WCD934X_IRQ_MBHC_ELECT_INS_REM_LEG_DET, 1, BIT(4)),
	WCD934X_REGMAP_IRQ_REG(WCD934X_IRQ_SOUNDWIRE, 2, BIT(4)),
	WCD934X_REGMAP_IRQ_REG(WCD934X_IRQ_CPE_ERROR, 2, BIT(7)),
	WCD934X_REGMAP_IRQ_REG(WCD934X_IRQ_CPE1_INTR, 3, BIT(5)),
};

static const unsigned int wcd934x_config_regs[] = {
	WCD934X_INTR_LEVEL0,
};

static const struct regmap_irq_chip wcd934x_regmap_irq_chip = {
	.name = "wcd934x_irq",
	.status_base = WCD934X_INTR_PIN1_STATUS0,
	.mask_base = WCD934X_INTR_PIN1_MASK0,
	.ack_base = WCD934X_INTR_PIN1_CLEAR0,
	.num_regs = 4,
	.irqs = wcd934x_irqs,
	.num_irqs = ARRAY_SIZE(wcd934x_irqs),
	.config_base = wcd934x_config_regs,
	.num_config_bases = ARRAY_SIZE(wcd934x_config_regs),
	.num_config_regs = 4,
	.set_type_config = regmap_irq_set_type_config_simple,
};

static bool wcd934x_is_volatile_register(struct device *dev, unsigned int reg)
{
	switch (reg) {
	case WCD934X_INTR_PIN1_STATUS0...WCD934X_INTR_PIN2_CLEAR3:
	case WCD934X_SWR_AHB_BRIDGE_RD_DATA_0:
	case WCD934X_SWR_AHB_BRIDGE_RD_DATA_1:
	case WCD934X_SWR_AHB_BRIDGE_RD_DATA_2:
	case WCD934X_SWR_AHB_BRIDGE_RD_DATA_3:
	case WCD934X_SWR_AHB_BRIDGE_ACCESS_STATUS:
	case WCD934X_ANA_MBHC_RESULT_3:
	case WCD934X_ANA_MBHC_RESULT_2:
	case WCD934X_ANA_MBHC_RESULT_1:
	case WCD934X_ANA_MBHC_MECH:
	case WCD934X_ANA_MBHC_ELECT:
	case WCD934X_ANA_MBHC_ZDET:
	case WCD934X_ANA_MICB2:
	case WCD934X_ANA_RCO:
	case WCD934X_ANA_BIAS:
		return true;
	default:
		return false;
	}
};

static const struct regmap_range_cfg wcd934x_ranges[] = {
	{	.name = "WCD934X",
		.range_min =  0x0,
		.range_max =  WCD934X_MAX_REGISTER,
		.selector_reg = WCD934X_SEL_REGISTER,
		.selector_mask = WCD934X_SEL_MASK,
		.selector_shift = WCD934X_SEL_SHIFT,
		.window_start = WCD934X_WINDOW_START,
		.window_len = WCD934X_WINDOW_LENGTH,
	},
};

static const struct regmap_config wcd934x_regmap_config = {
	.reg_bits = 16,
	.val_bits = 8,
	.cache_type = REGCACHE_MAPLE,
	.max_register = 0xffff,
	.can_multi_write = true,
	.ranges = wcd934x_ranges,
	.num_ranges = ARRAY_SIZE(wcd934x_ranges),
	.volatile_reg = wcd934x_is_volatile_register,
};

static int wcd934x_bring_up(struct wcd934x_ddata *ddata)
{
	struct regmap *regmap = ddata->regmap;
	u16 id_minor, id_major;
	int ret;

	ret = regmap_bulk_read(regmap, WCD934X_CHIP_TIER_CTRL_CHIP_ID_BYTE0,
			       (u8 *)&id_minor, sizeof(u16));
	if (ret)
		return ret;

	ret = regmap_bulk_read(regmap, WCD934X_CHIP_TIER_CTRL_CHIP_ID_BYTE2,
			       (u8 *)&id_major, sizeof(u16));
	if (ret)
		return ret;

	dev_info(ddata->dev, "WCD934x chip id major 0x%x, minor 0x%x\n",
		 id_major, id_minor);

	regmap_write(regmap, WCD934X_CODEC_RPM_RST_CTL, 0x01);
	regmap_write(regmap, WCD934X_SIDO_NEW_VOUT_A_STARTUP, 0x19);
	regmap_write(regmap, WCD934X_SIDO_NEW_VOUT_D_STARTUP, 0x15);
	/* Add 1msec delay for VOUT to settle */
	usleep_range(1000, 1100);
	regmap_write(regmap, WCD934X_CODEC_RPM_PWR_CDC_DIG_HM_CTL, 0x5);
	regmap_write(regmap, WCD934X_CODEC_RPM_PWR_CDC_DIG_HM_CTL, 0x7);
	regmap_write(regmap, WCD934X_CODEC_RPM_RST_CTL, 0x3);
	regmap_write(regmap, WCD934X_CODEC_RPM_RST_CTL, 0x7);
	regmap_write(regmap, WCD934X_CODEC_RPM_PWR_CDC_DIG_HM_CTL, 0x3);

	return 0;
}

/* SPX: userspace regmap write helper. The regmap debugfs `access` file is
 * absent on this build, so expose a minimal write helper for the speaker
 * replay script to drive codec + SWR master + WSA registers from APPS.
 * Usage (root):
 *   echo "0xREG 0xVAL" > /sys/kernel/debug/wcd934x/<addr>/write_reg
 */
static ssize_t spx_write_reg_write(struct file *f, const char __user *buf,
				   size_t count, loff_t *ppos)
{
	struct wcd934x_ddata *ddata = file_inode(f)->i_private;
	unsigned int reg, val, ret;
	char kbuf[32];

	/*
	 * buf is a __user pointer: sscanf()-ing it directly faults on hardened
	 * usercopy (kernel access to user memory) and oopses. Copy into a kernel
	 * buffer first.
	 */
	if (count >= sizeof(kbuf))
		return -EINVAL;
	if (copy_from_user(kbuf, buf, count))
		return -EFAULT;
	kbuf[count] = '\0';

	if (sscanf(kbuf, "%x %x", &reg, &val) != 2)
		return -EINVAL;
	ret = regmap_write(ddata->regmap, reg, val);
	if (ret) {
		dev_err(ddata->dev, "spx write_reg 0x%04x=0x%02x failed: %d\n",
			reg, val, ret);
		return ret;
	}
	dev_dbg(ddata->dev, "spx write_reg 0x%04x=0x%02x ok\n", reg, val);
	return count;
}

static const struct file_operations spx_write_reg_fops = {
	.owner = THIS_MODULE,
	.open = simple_open,
	.write = spx_write_reg_write,
	.llseek = noop_llseek,
};

static int wcd934x_slim_status_up(struct slim_device *sdev)
{
	struct device *dev = &sdev->dev;
	struct wcd934x_ddata *ddata;
	int ret;

	ddata = dev_get_drvdata(dev);

	ddata->regmap = regmap_init_slimbus(sdev, &wcd934x_regmap_config);
	if (IS_ERR(ddata->regmap)) {
		dev_err(dev, "Error allocating slim regmap\n");
		return PTR_ERR(ddata->regmap);
	}

	ret = wcd934x_bring_up(ddata);
	if (ret) {
		dev_err(dev, "Failed to bring up WCD934X: err = %d\n", ret);
		return ret;
	}

	/*
	 * SPX legacy one-pin override: physical HIGH powers the selected amp.
	 */
	if (spx_wsa_en_pin >= 0 && spx_wsa_en_pin < 5) {
		u32 m = BIT(spx_wsa_en_pin);

		regmap_update_bits(ddata->regmap, WCD934X_GPIO_DIR_CTL, m, m);
		regmap_update_bits(ddata->regmap, WCD934X_GPIO_VAL_CTL, m, m);
		dev_info(dev, "SPX: forced wcd-gpio pin %d output-high to power one WSA amp\n",
			 spx_wsa_en_pin);
	}

	/* Managed two-pin override, applied after the single-pin helper above. */
	if (spx_wsa_gpio_dir >= 0)
		regmap_update_bits(ddata->regmap, WCD934X_GPIO_DIR_CTL,
				   SPX_WSA_GPIO_MASK, spx_wsa_gpio_dir);
	if (spx_wsa_gpio_val >= 0)
		regmap_update_bits(ddata->regmap, WCD934X_GPIO_VAL_CTL,
				   SPX_WSA_GPIO_MASK, spx_wsa_gpio_val);
	if (spx_wsa_gpio_dir >= 0 || spx_wsa_gpio_val >= 0)
		dev_info(dev,
			 "SPX: wcd-gpio managed bits 0x06 dir=0x%02x val=0x%02x\n",
			 spx_wsa_gpio_dir & SPX_WSA_GPIO_MASK,
			 spx_wsa_gpio_val & SPX_WSA_GPIO_MASK);

	/* SPX: skip the regmap IRQ chip when no codec IRQ is wired. */
	if (ddata->irq > 0) {
		ret = devm_regmap_add_irq_chip(dev, ddata->regmap, ddata->irq,
					       IRQF_TRIGGER_HIGH, 0,
					       &wcd934x_regmap_irq_chip,
					       &ddata->irq_data);
		if (ret) {
			dev_err(dev, "Failed to add IRQ chip: err = %d\n", ret);
			return ret;
		}
	}

	ret = mfd_add_devices(dev, PLATFORM_DEVID_AUTO, wcd934x_devices,
			      ARRAY_SIZE(wcd934x_devices), NULL, 0, NULL);
	if (ret) {
		dev_err(dev, "Failed to add child devices: err = %d\n",
			ret);
		return ret;
	}

	/* SPX: expose a userspace regmap write helper for the speaker replay. */
	ddata->dbgdir = debugfs_create_dir(dev_name(dev), NULL);
	debugfs_create_file("write_reg", 0200,
			    ddata->dbgdir, ddata,
			    &spx_write_reg_fops);

	return ret;
}

static int wcd934x_slim_status(struct slim_device *sdev,
			       enum slim_device_status status)
{
	switch (status) {
	case SLIM_DEVICE_STATUS_UP:
		return wcd934x_slim_status_up(sdev);
	case SLIM_DEVICE_STATUS_DOWN:
		mfd_remove_devices(&sdev->dev);
		break;
	default:
		return -EINVAL;
	}

	return 0;
}

static int wcd934x_slim_probe(struct slim_device *sdev)
{
	struct device *dev = &sdev->dev;
	struct device_node *np = dev->of_node;
	struct wcd934x_ddata *ddata;
	struct gpio_desc *reset_gpio;
	int ret;

	ddata = devm_kzalloc(dev, sizeof(*ddata), GFP_KERNEL);
	if (!ddata)
		return	-ENOMEM;

	ddata->irq = of_irq_get(np, 0);
	if (ddata->irq < 0) {
		/* SPX: codec IRQ is not wired in the DT (DSDT GIO0 pin 0x100
		 * sits beyond the TLMM pinctrl-msm gpio-ranges, and no
		 * QCOM040D ACPI GPIO driver is upstream). Continue without
		 * the codec IRQ so the sound card can still come up; the
		 * IRQ-gated codec init (MBHC, etc.) is simply skipped. */
		dev_warn(dev, "no codec IRQ (sp): %d\n", ddata->irq);
		ddata->irq = 0;
	}

	ddata->extclk = devm_clk_get(dev, "extclk");
	if (IS_ERR(ddata->extclk))
		return dev_err_probe(dev, PTR_ERR(ddata->extclk),
				     "Failed to get extclk");

	ddata->supplies[0].supply = "vdd-buck";
	ddata->supplies[1].supply = "vdd-buck-sido";
	ddata->supplies[2].supply = "vdd-tx";
	ddata->supplies[3].supply = "vdd-rx";
	ddata->supplies[4].supply = "vdd-io";

	ret = regulator_bulk_get(dev, WCD934X_MAX_SUPPLY, ddata->supplies);
	if (ret)
		return dev_err_probe(dev, ret, "Failed to get supplies\n");

	ret = regulator_bulk_enable(WCD934X_MAX_SUPPLY, ddata->supplies);
	if (ret)
		return dev_err_probe(dev, ret, "Failed to enable supplies\n");

	/*
	 * For WCD934X, it takes about 600us for the Vout_A and
	 * Vout_D to be ready after BUCK_SIDO is powered up.
	 * SYS_RST_N shouldn't be pulled high during this time
	 */
	usleep_range(600, 650);
	reset_gpio = devm_gpiod_get_optional(dev, "reset", GPIOD_OUT_LOW);
	if (IS_ERR(reset_gpio)) {
		ret = dev_err_probe(dev, PTR_ERR(reset_gpio),
				    "Failed to get reset gpio\n");
		goto err_disable_regulators;
	}
	msleep(20);
	gpiod_set_value(reset_gpio, 1);
	msleep(20);

	ddata->dev = dev;
	dev_set_drvdata(dev, ddata);

	return 0;

err_disable_regulators:
	regulator_bulk_disable(WCD934X_MAX_SUPPLY, ddata->supplies);
	return ret;
}

static void wcd934x_slim_remove(struct slim_device *sdev)
{
	struct wcd934x_ddata *ddata = dev_get_drvdata(&sdev->dev);

	regulator_bulk_disable(WCD934X_MAX_SUPPLY, ddata->supplies);
	mfd_remove_devices(&sdev->dev);
}

static const struct slim_device_id wcd934x_slim_id[] = {
	{ SLIM_MANF_ID_QCOM, SLIM_PROD_CODE_WCD9340,
	  SLIM_DEV_IDX_WCD9340, SLIM_DEV_INSTANCE_ID_WCD9340 },
	{}
};
MODULE_DEVICE_TABLE(slim, wcd934x_slim_id);

static struct slim_driver wcd934x_slim_driver = {
	.driver = {
		.name = "wcd934x-slim",
	},
	.probe = wcd934x_slim_probe,
	.remove = wcd934x_slim_remove,
	.device_status = wcd934x_slim_status,
	.id_table = wcd934x_slim_id,
};

module_slim_driver(wcd934x_slim_driver);
MODULE_DESCRIPTION("WCD934X slim driver");
MODULE_LICENSE("GPL v2");
MODULE_AUTHOR("Srinivas Kandagatla <srinivas.kandagatla@linaro.org>");
