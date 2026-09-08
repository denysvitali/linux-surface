// SPDX-License-Identifier: GPL-2.0
/*
 * Surface Pro X rear/IR camera identity probe.
 *
 * This deliberately does less than a sensor driver: it applies the exact
 * Windows ACPI PEP power sequence, reads one documented chip-ID register pair
 * on ac4a000 CCI master 0, and restores every resource before returning.
 *
 * Rear / CAMS (OV13858):
 *   reset GPIO22 low; LDO14_A, LDO17_A, LDO1_A; MCLK0 @ 19.2 MHz;
 *   reset high; 2 ms; CCI0 addr 0x10, ID d855 at 0x300b.
 *
 * IR / CAMI (OV7251):
 *   reset GPIO23 low; LDO14_A; MCLK3 @ 19.2 MHz;
 *   reset high; 1 ms; CCI0 addr 0x60, ID 7750 at 0x300a.
 *
 * The rail writes use SPMI directly.  Never replace them with regulator_enable:
 * RPMh votes for these PEP-owned rails time out and can wedge the RSC.
 *
 * The module returns -EAGAIN after cleanup so it never remains loaded.  A
 * temporary emergency-restart watchdog protects against a stuck CCI transfer;
 * it is cancelled synchronously before init returns.
 */

#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/gpio.h>
#include <linux/gpio/consumer.h>
#include <linux/gpio/driver.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/pinctrl/consumer.h>
#include <linux/pinctrl/machine.h>
#include <linux/pinctrl/pinconf-generic.h>
#include <linux/pm_runtime.h>
#include <linux/reboot.h>
#include <linux/spmi.h>
#include <linux/workqueue.h>

#include <dt-bindings/clock/qcom,sc8180x-camcc.h>

#define SPX_CAMCC_COMPATIBLE     "qcom,sc8180x-camcc"
#define SPX_CCI0_BUS_PATH        "/soc@0/cci@ac4a000/i2c-bus@0"
#define SPX_TLMM_LABEL           "3100000.pinctrl"
#define SPX_PINCTRL_DEVICE       "3100000.pinctrl"
#define SPX_PROBE_DEVICE         "spx-camera-id-probe"
#define SPX_MCLK_HZ              19200000

#define SPX_PMIC_SID             1
#define SPX_PERPH_TYPE_OFF       0x04
#define SPX_PERPH_SUBTYPE_OFF    0x05
#define SPX_EN_CTL_OFF           0x46
#define SPX_EN_CTL_ENABLE        BIT(7)
#define SPX_PERPH_TYPE_LDO       0x04

static char *target = "rear";
module_param(target, charp, 0444);
MODULE_PARM_DESC(target, "sensor to probe: rear or ir");

static int watchdog_seconds = 30;
module_param(watchdog_seconds, int, 0444);
MODULE_PARM_DESC(watchdog_seconds,
			 "emergency reboot if the probe does not finish (0 disables)");

static bool dry_run;
module_param(dry_run, bool, 0444);
MODULE_PARM_DESC(dry_run, "validate reset/pinctrl setup and cleanup without power or I2C");

struct spx_camera_target {
	const char *name;
	u8 addr;
	u16 id_reg;
	u16 expected_id;
	u32 mclk_id;
	unsigned int mclk_pin;
	unsigned int reset_pin;
	unsigned int post_reset_ms;
	unsigned int rails[3];
	unsigned int num_rails;
};

static const struct spx_camera_target spx_rear = {
	.name = "rear OV13858",
	.addr = 0x10,
	.id_reg = 0x300b,
	.expected_id = 0xd855,
	.mclk_id = CAM_CC_MCLK0_CLK,
	.mclk_pin = 13,
	.reset_pin = 22,
	.post_reset_ms = 2,
	.rails = { 14, 17, 1 },
	.num_rails = 3,
};

static const struct spx_camera_target spx_ir = {
	.name = "IR OV7251",
	.addr = 0x60,
	.id_reg = 0x300a,
	.expected_id = 0x7750,
	.mclk_id = CAM_CC_MCLK3_CLK,
	.mclk_pin = 16,
	.reset_pin = 23,
	.post_reset_ms = 1,
	.rails = { 14 },
	.num_rails = 1,
};

struct spx_rail_state {
	unsigned int ldo;
	u8 original_en;
	bool valid;
	bool changed;
};

static void spx_probe_watchdog(struct work_struct *work)
{
	pr_emerg("spxcamid: probe exceeded %d seconds; emergency reboot to avoid a physical power-cycle\n",
		 watchdog_seconds);
	emergency_restart();
}

static DECLARE_DELAYED_WORK(spx_watchdog_work, spx_probe_watchdog);

static struct spmi_device *spx_get_pmic(void)
{
	struct device_node *np;
	struct spmi_device *sdev;

	np = of_find_node_by_path("/soc@0/spmi@c440000/pmic@1");
	if (!np)
		return NULL;
	sdev = spmi_find_device_by_of_node(np);
	of_node_put(np);
	return sdev;
}

static unsigned int spx_ldo_base(unsigned int ldo)
{
	return 0x4000 + (ldo - 1) * 0x100;
}

static int spx_rail_enable(struct spmi_device *sdev,
			   struct spx_rail_state *state, unsigned int ldo)
{
	unsigned int base = spx_ldo_base(ldo);
	u8 type = 0, subtype = 0, en = 0;
	int ret;

	state->ldo = ldo;
	ret = spmi_ext_register_readl(sdev, base + SPX_PERPH_TYPE_OFF,
				      &type, 1);
	if (ret)
		return ret;
	ret = spmi_ext_register_readl(sdev, base + SPX_PERPH_SUBTYPE_OFF,
				      &subtype, 1);
	if (ret)
		return ret;
	ret = spmi_ext_register_readl(sdev, base + SPX_EN_CTL_OFF, &en, 1);
	if (ret)
		return ret;

	pr_info("spxcamid: LDO%u_A base 0x%04x type=0x%02x subtype=0x%02x EN_CTL=0x%02x\n",
		ldo, base, type, subtype, en);
	if (type != SPX_PERPH_TYPE_LDO) {
		pr_err("spxcamid: LDO%u_A type mismatch; refusing to write\n", ldo);
		return -ENODEV;
	}

	state->original_en = en;
	state->valid = true;
	if (en & SPX_EN_CTL_ENABLE)
		return 0;

	en |= SPX_EN_CTL_ENABLE;
	ret = spmi_ext_register_writel(sdev, base + SPX_EN_CTL_OFF, &en, 1);
	if (ret)
		return ret;
	state->changed = true;
	usleep_range(1000, 2000);
	ret = spmi_ext_register_readl(sdev, base + SPX_EN_CTL_OFF, &en, 1);
	if (ret)
		return ret;
	if (!(en & SPX_EN_CTL_ENABLE))
		return -EIO;

	pr_info("spxcamid: LDO%u_A enabled over SPMI\n", ldo);
	return 0;
}

static void spx_rail_restore(struct spmi_device *sdev,
			     struct spx_rail_state *state)
{
	unsigned int base;
	u8 en;
	int ret;

	if (!state->valid || !state->changed)
		return;
	base = spx_ldo_base(state->ldo);
	en = state->original_en;
	ret = spmi_ext_register_writel(sdev, base + SPX_EN_CTL_OFF, &en, 1);
	if (ret) {
		pr_err("spxcamid: failed to restore LDO%u_A EN_CTL (%d)\n",
		       state->ldo, ret);
		return;
	}
	usleep_range(1000, 2000);
	spmi_ext_register_readl(sdev, base + SPX_EN_CTL_OFF, &en, 1);
	pr_info("spxcamid: LDO%u_A restored to 0x%02x (%s)\n",
		state->ldo, en,
		(en & SPX_EN_CTL_ENABLE) ? "ON as found" : "OFF");
}

static struct clk *spx_get_mclk(u32 id)
{
	struct device_node *camcc;
	struct of_phandle_args spec = { };
	struct clk *clk;

	camcc = of_find_compatible_node(NULL, NULL, SPX_CAMCC_COMPATIBLE);
	if (!camcc)
		return ERR_PTR(-ENODEV);
	spec.np = camcc;
	spec.args_count = 1;
	spec.args[0] = id;
	clk = of_clk_get_from_provider(&spec);
	of_node_put(camcc);
	return clk;
}

static int spx_read8(struct i2c_adapter *adap, u8 addr, u16 reg, u8 *value)
{
	u8 regbuf[2] = { reg >> 8, reg & 0xff };
	struct i2c_msg msgs[2] = {
		{ .addr = addr, .len = sizeof(regbuf), .buf = regbuf },
		{ .addr = addr, .flags = I2C_M_RD, .len = 1, .buf = value },
	};
	int ret;

	ret = i2c_transfer(adap, msgs, ARRAY_SIZE(msgs));
	return ret == ARRAY_SIZE(msgs) ? 0 : (ret < 0 ? ret : -EIO);
}

static void spx_init_map(struct pinctrl_map *map, const char *state,
			 enum pinctrl_map_type type, const char *group,
			 const char *function, unsigned long *configs,
			 unsigned int num_configs)
{
	map->dev_name = SPX_PROBE_DEVICE;
	map->name = state;
	map->type = type;
	map->ctrl_dev_name = SPX_PINCTRL_DEVICE;
	if (type == PIN_MAP_TYPE_MUX_GROUP) {
		map->data.mux.group = group;
		map->data.mux.function = function;
	} else {
		map->data.configs.group_or_pin = group;
		map->data.configs.configs = configs;
		map->data.configs.num_configs = num_configs;
	}
}

static int __init spx_camera_id_init(void)
{
	const struct spx_camera_target *sensor;
	struct spx_rail_state rail_state[3] = { };
	struct pinctrl_map maps[4] = { };
	unsigned long active_configs[2], idle_configs[2];
	char mclk_group[16];
	struct device *probe_dev = NULL;
	struct pinctrl *pctl = NULL;
	struct pinctrl_state *active_state, *idle_state;
	struct gpio_device *gdev = NULL;
	struct gpio_desc *reset = NULL;
	struct spmi_device *pmic = NULL;
	struct device_node *bus_np = NULL;
	struct i2c_adapter *adap = NULL;
	struct clk *mclk = NULL;
	int reset_gpio = -1;
	bool maps_registered = false;
	bool cci_awake = false;
	bool mclk_on = false;
	u8 id_hi = 0, id_lo = 0;
	u16 id;
	int ret = 0;
	int i;

	if (!strcmp(target, "rear"))
		sensor = &spx_rear;
	else if (!strcmp(target, "ir"))
		sensor = &spx_ir;
	else {
		pr_err("spxcamid: invalid target '%s' (use rear or ir)\n", target);
		return -EINVAL;
	}

	pr_info("spxcamid: begin %s probe; exact bus=%s addr=0x%02x\n",
		sensor->name, SPX_CCI0_BUS_PATH, sensor->addr);
	if (watchdog_seconds > 0) {
		schedule_delayed_work(&spx_watchdog_work,
				      watchdog_seconds * HZ);
		pr_info("spxcamid: emergency-reboot watchdog armed for %d seconds\n",
			watchdog_seconds);
	}

	/* Hold reset low before any sensor rail is raised. */
	gdev = gpio_device_find_by_label(SPX_TLMM_LABEL);
	if (!gdev) {
		ret = -ENODEV;
		pr_err("spxcamid: TLMM gpiochip not found\n");
		goto out;
	}
	reset_gpio = gpio_device_get_base(gdev) + sensor->reset_pin;
	ret = gpio_request_one(reset_gpio, GPIOF_OUT_INIT_LOW, SPX_PROBE_DEVICE);
	if (ret) {
		pr_err("spxcamid: failed to request reset GPIO%u (%d)\n",
		       sensor->reset_pin, ret);
		goto out;
	}
	reset = gpio_to_desc(reset_gpio);
	gpiod_set_config(reset,
		pinconf_to_config_packed(PIN_CONFIG_BIAS_DISABLE, 0));
	gpiod_set_config(reset,
		pinconf_to_config_packed(PIN_CONFIG_DRIVE_STRENGTH, 2));
	gpiod_set_raw_value_cansleep(reset, 0);
	pr_info("spxcamid: GPIO%u LOW (reset asserted)\n", sensor->reset_pin);

	/* Register a temporary pinctrl consumer; no DT change or reboot needed. */
	snprintf(mclk_group, sizeof(mclk_group), "gpio%u", sensor->mclk_pin);
	active_configs[0] = pinconf_to_config_packed(PIN_CONFIG_BIAS_DISABLE, 0);
	active_configs[1] = pinconf_to_config_packed(PIN_CONFIG_DRIVE_STRENGTH, 4);
	idle_configs[0] = pinconf_to_config_packed(PIN_CONFIG_BIAS_PULL_DOWN, 1);
	idle_configs[1] = pinconf_to_config_packed(PIN_CONFIG_DRIVE_STRENGTH, 2);
	spx_init_map(&maps[0], PINCTRL_STATE_DEFAULT, PIN_MAP_TYPE_MUX_GROUP,
		     mclk_group, "cam_mclk", NULL, 0);
	spx_init_map(&maps[1], PINCTRL_STATE_DEFAULT, PIN_MAP_TYPE_CONFIGS_GROUP,
		     mclk_group, NULL, active_configs, ARRAY_SIZE(active_configs));
	spx_init_map(&maps[2], PINCTRL_STATE_IDLE, PIN_MAP_TYPE_MUX_GROUP,
		     mclk_group, "gpio", NULL, 0);
	spx_init_map(&maps[3], PINCTRL_STATE_IDLE, PIN_MAP_TYPE_CONFIGS_GROUP,
		     mclk_group, NULL, idle_configs, ARRAY_SIZE(idle_configs));
	ret = pinctrl_register_mappings(maps, ARRAY_SIZE(maps));
	if (ret) {
		pr_err("spxcamid: pinctrl mapping registration failed (%d)\n", ret);
		goto out;
	}
	maps_registered = true;
	probe_dev = root_device_register(SPX_PROBE_DEVICE);
	if (IS_ERR(probe_dev)) {
		ret = PTR_ERR(probe_dev);
		probe_dev = NULL;
		pr_err("spxcamid: temporary device registration failed (%d)\n", ret);
		goto out;
	}
	pctl = pinctrl_get(probe_dev);
	if (IS_ERR(pctl)) {
		ret = PTR_ERR(pctl);
		pctl = NULL;
		pr_err("spxcamid: pinctrl get failed (%d)\n", ret);
		goto out;
	}
	active_state = pinctrl_lookup_state(pctl, PINCTRL_STATE_DEFAULT);
	if (IS_ERR(active_state)) {
		ret = PTR_ERR(active_state);
		pr_err("spxcamid: active pinctrl state lookup failed (%d)\n", ret);
		goto out;
	}
	ret = pinctrl_select_state(pctl, active_state);
	if (ret) {
		pr_err("spxcamid: failed to mux %s as cam_mclk (%d)\n",
		       mclk_group, ret);
		goto out;
	}
	pr_info("spxcamid: %s muxed as cam_mclk, 4 mA, no pull\n",
		mclk_group);
	if (dry_run) {
		pr_info("spxcamid: dry run complete; no CCI, clock, or rail was enabled\n");
		goto out;
	}

	/* Keep only ac4a000 CCI master 0 awake for the duration of the probe. */
	bus_np = of_find_node_by_path(SPX_CCI0_BUS_PATH);
	if (!bus_np) {
		ret = -ENODEV;
		pr_err("spxcamid: exact CCI bus node not found\n");
		goto out;
	}
	adap = of_find_i2c_adapter_by_node(bus_np);
	if (!adap) {
		ret = -EPROBE_DEFER;
		pr_err("spxcamid: exact CCI adapter is unavailable\n");
		goto out;
	}
	ret = pm_runtime_resume_and_get(adap->dev.parent);
	if (ret < 0) {
		pr_err("spxcamid: CCI runtime resume failed (%d)\n", ret);
		goto out;
	}
	cci_awake = true;
	pr_info("spxcamid: CCI controller %s held runtime-active\n",
		dev_name(adap->dev.parent));

	pmic = spx_get_pmic();
	if (!pmic) {
		ret = -ENODEV;
		pr_err("spxcamid: PMIC SID%d not found\n", SPX_PMIC_SID);
		goto out;
	}
	for (i = 0; i < sensor->num_rails; i++) {
		ret = spx_rail_enable(pmic, &rail_state[i], sensor->rails[i]);
		if (ret) {
			pr_err("spxcamid: failed to enable LDO%u_A (%d)\n",
			       sensor->rails[i], ret);
			goto out;
		}
	}

	mclk = spx_get_mclk(sensor->mclk_id);
	if (IS_ERR(mclk)) {
		ret = PTR_ERR(mclk);
		mclk = NULL;
		pr_err("spxcamid: MCLK%u get failed (%d)\n",
		       sensor->mclk_pin - 13, ret);
		goto out;
	}
	ret = clk_set_rate(mclk, SPX_MCLK_HZ);
	if (ret) {
		pr_err("spxcamid: MCLK set-rate failed (%d)\n", ret);
		goto out;
	}
	ret = clk_prepare_enable(mclk);
	if (ret) {
		pr_err("spxcamid: MCLK enable failed (%d)\n", ret);
		goto out;
	}
	mclk_on = true;
	pr_info("spxcamid: MCLK id %u running at %lu Hz on GPIO%u\n",
		sensor->mclk_id, clk_get_rate(mclk), sensor->mclk_pin);

	gpiod_set_raw_value_cansleep(reset, 1);
	pr_info("spxcamid: GPIO%u HIGH (reset released)\n", sensor->reset_pin);
	msleep(sensor->post_reset_ms);

	ret = spx_read8(adap, sensor->addr, sensor->id_reg, &id_hi);
	if (ret) {
		pr_err("spxcamid: %s no response at 0x%02x reg 0x%04x (%d)\n",
		       sensor->name, sensor->addr, sensor->id_reg, ret);
		goto out;
	}
	ret = spx_read8(adap, sensor->addr, sensor->id_reg + 1, &id_lo);
	if (ret) {
		pr_err("spxcamid: %s low ID byte read failed (%d)\n",
		       sensor->name, ret);
		goto out;
	}
	id = (id_hi << 8) | id_lo;
	if (id == sensor->expected_id)
		pr_info("spxcamid: MATCH %s ID=0x%04x at 0x%02x ***\n",
			sensor->name, id, sensor->addr);
	else {
		pr_err("spxcamid: %s ID mismatch: got 0x%04x expected 0x%04x\n",
		       sensor->name, id, sensor->expected_id);
		ret = -ENODEV;
	}

out:
	/* Restore the PEP D3 ordering: reset, clock, rails, then controller. */
	if (reset) {
		gpiod_set_raw_value_cansleep(reset, 0);
		pr_info("spxcamid: GPIO%u LOW (reset asserted for cleanup)\n",
			sensor->reset_pin);
	}
	if (mclk_on)
		clk_disable_unprepare(mclk);
	if (mclk)
		clk_put(mclk);
	for (i = sensor->num_rails - 1; i >= 0; i--)
		spx_rail_restore(pmic, &rail_state[i]);
	if (cci_awake) {
		pm_runtime_mark_last_busy(adap->dev.parent);
		pm_runtime_put_autosuspend(adap->dev.parent);
	}
	if (adap)
		i2c_put_adapter(adap);
	if (bus_np)
		of_node_put(bus_np);
	if (pctl) {
		idle_state = pinctrl_lookup_state(pctl, PINCTRL_STATE_IDLE);
		if (!IS_ERR(idle_state)) {
			int idle_ret = pinctrl_select_state(pctl, idle_state);

			pr_info("spxcamid: restored %s to GPIO/pull-down (%d)\n",
				mclk_group, idle_ret);
		}
		pinctrl_put(pctl);
	}
	if (probe_dev)
		root_device_unregister(probe_dev);
	if (maps_registered)
		pinctrl_unregister_mappings(maps);
	if (reset) {
		gpiod_direction_input(reset);
		gpiod_set_config(reset,
			pinconf_to_config_packed(PIN_CONFIG_BIAS_PULL_DOWN, 1));
		gpio_free(reset_gpio);
	}
	if (gdev)
		gpio_device_put(gdev);

	if (watchdog_seconds > 0)
		cancel_delayed_work_sync(&spx_watchdog_work);
	pr_info("spxcamid: watchdog disarmed; cleanup complete; result=%d\n", ret);

	/* Never remain loaded, so repeated probes require no module removal. */
	return -EAGAIN;
}

static void __exit spx_camera_id_exit(void) { }

module_init(spx_camera_id_init);
module_exit(spx_camera_id_exit);
MODULE_DESCRIPTION("Surface Pro X exact rear/IR camera chip-ID probe");
MODULE_LICENSE("GPL");
