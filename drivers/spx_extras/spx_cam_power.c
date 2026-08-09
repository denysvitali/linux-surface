// SPDX-License-Identifier: GPL-2.0
/*
 * spx_cam_power - run the Windows-exact camera power-on sequence and probe I2C.
 *
 * Every parameter here is taken from the vendor's own PEP resource table,
 * ACPI \_SB.PEP0.CPXC (Name(CPXC) at dsdt.dsl:58526), device entry
 * "\_SB.CAMF" at dsdt.dsl:63708 -- not inferred:
 *
 *   GPIO12 -> low  (reset assert)
 *   PPP_RESOURCE_ID_LDO14_A @ 1.8 V   (vreg_l14a; enabled by this module, NOT always-on)
 *   delay
 *   cam_cc_mclk2_clk @ 19 200 000 Hz  (NOT 24 MHz - the Chromatix-derived
 *                                      24 MHz used in earlier boots was wrong)
 *   GPIO12 -> high (reset deassert)
 *   delay 2 ms
 *   then read OV5693 chip id: reg 0x300A/0x300B, expect 0x5690.
 *
 * The rear (OV13858) and aux (OV7251) also get probed opportunistically, but
 * per ACPI CAMP.PCFG they live on CCI0, whose pins are in gpio-reserved-ranges
 * and therefore unreachable - do not read anything into their result.
 *
 * Read-only on the I2C side. Loads with -EAGAIN by design so it can be re-run
 * without rmmod.
 */

#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>
#include <linux/regulator/consumer.h>

static int mclk_hz = 19200000;
module_param(mclk_hz, int, 0644);
MODULE_PARM_DESC(mclk_hz, "MCLK rate (PEP table says 19200000)");

static int post_reset_ms = 2;
module_param(post_reset_ms, int, 0644);
MODULE_PARM_DESC(post_reset_ms, "delay after reset deassert, ms");

struct spx_sensor {
	const char *name;
	u8 addr;
	u16 id_reg;
	u16 id_val;
};

static const struct spx_sensor sensors[] = {
	{ "ov5693 (front, CCI1)", 0x36, 0x300a, 0x5690 },
	{ "ov13858 (rear)",       0x10, 0x300b, 0xd855 },
	{ "ov7251 (aux/IR)",      0x60, 0x300a, 0x7750 },
};

static int spx_ov_read8(struct i2c_adapter *adap, u8 addr, u16 reg, u8 *val)
{
	u8 wbuf[2] = { reg >> 8, reg & 0xff };
	struct i2c_msg msgs[2] = {
		{ .addr = addr, .flags = 0,        .len = 2, .buf = wbuf },
		{ .addr = addr, .flags = I2C_M_RD, .len = 1, .buf = val  },
	};
	int ret = i2c_transfer(adap, msgs, 2);

	return ret == 2 ? 0 : (ret < 0 ? ret : -EIO);
}

/*
 * Runtime-resume the CCI controller by issuing one throwaway transfer. That is
 * what powers the TITAN_TOP GDSC, without which every camcc branch refuses to
 * come out of reset ("status stuck at 'off'", clk-branch.c:87 -> -EBUSY).
 *
 * The spx-cam-test node has no power-domains property of its own, so a
 * clk_prepare_enable() on cam_cc_mclk2 from here fails unless CCI is awake.
 * CCI autosuspend is 1 s, so the caller must enable MCLK promptly after this.
 */
static void spx_cci_wakeup(void)
{
	struct device_node *np;

	for_each_compatible_node(np, NULL, "qcom,msm8996-cci") {
		struct device_node *bus;

		for_each_child_of_node(np, bus) {
			struct i2c_adapter *adap = of_find_i2c_adapter_by_node(bus);
			u8 dummy;

			if (!adap)
				continue;
			spx_ov_read8(adap, sensors[0].addr, sensors[0].id_reg, &dummy);
			i2c_put_adapter(adap);
		}
	}
	pr_info("spxcam: CCI warmed up (TITAN_TOP should now be powered)\n");
}

static void spx_scan(void)
{
	struct device_node *np;

	for_each_compatible_node(np, NULL, "qcom,msm8996-cci") {
		struct device_node *bus;

		for_each_child_of_node(np, bus) {
			struct i2c_adapter *adap = of_find_i2c_adapter_by_node(bus);
			int i;

			if (!adap)
				continue;
			pr_info("spxcam: scanning %pOF\n", bus);
			for (i = 0; i < ARRAY_SIZE(sensors); i++) {
				const struct spx_sensor *s = &sensors[i];
				u8 hi = 0, lo = 0;
				u16 id;

				if (spx_ov_read8(adap, s->addr, s->id_reg, &hi)) {
					pr_info("spxcam:   %-22s @0x%02x : no response\n",
						s->name, s->addr);
					continue;
				}
				spx_ov_read8(adap, s->addr, s->id_reg + 1, &lo);
				id = (hi << 8) | lo;
				pr_info("spxcam:   %-22s @0x%02x : ID 0x%04x (expect 0x%04x) %s\n",
					s->name, s->addr, id, s->id_val,
					id == s->id_val ? "*** MATCH ***" : "mismatch");
			}
			i2c_put_adapter(adap);
		}
	}
}

static int __init spx_cam_power_init(void)
{
	struct device_node *np;
	struct platform_device *pdev;
	struct gpio_desc *reset;
	struct regulator *vdd;
	struct clk *mclk;
	bool rail_on;
	int mclk_on = -1;
	int ret;

	np = of_find_compatible_node(NULL, NULL, "spx,cam-test");
	if (!np) {
		pr_info("spxcam: no spx,cam-test node - wrong DTB?\n");
		return -EAGAIN;
	}
	pdev = of_find_device_by_node(np);
	of_node_put(np);
	if (!pdev) {
		pr_info("spxcam: no platform device for spx,cam-test\n");
		return -EAGAIN;
	}

	/*
	 * The DTB deliberately declares ldo14 with min==max ONLY - no
	 * always-on, no initial-mode. v5 used regulator-initial-mode and the
	 * RPMh mode command timed out, which failed devm_regulator_register()
	 * and aborted the ENTIRE pmc8180-a provider (killing smps5/ldo7/ldo9/
	 * ldo12 and with them Wi-Fi). Enabling here instead keeps any failure
	 * contained to this module.
	 */
	/*
	 * DISABLED 2026-08-06. Enabling this rail over RPMh is a trap, and it
	 * cost a forcibly-reset boot:
	 *
	 *   - The APPS RSC does not own cmd-db resource "ldoa14", so the write
	 *     is never ACKed (-ETIMEDOUT) and its active TCS slot is never
	 *     released. A second rpmh_write() then blocks forever in
	 *     rpmh_rsc_send_data(), in uninterruptible D state.
	 *   - That wedged task holds the regulator core's ww_mutex chain, so at
	 *     SHUTDOWN wpa_supplicant blocks in regulator_bulk_disable() via
	 *     ath10k_hif_power_down(). systemd waits 122 s per task and the
	 *     reboot never completes -- it needs Ctrl-Alt-Del x7 to force.
	 *
	 * The correct way to raise this rail is SPMI, which bypasses RPMh
	 * entirely: spx_pmic_ldo.ko sid=1 ldo=14 enable=1. Use spx_cam_go.ko
	 * for the probe. This module is kept only for its documentation.
	 */
	pr_info("spxcam: REFUSING to vote LDO14_A over RPMh - it wedges the RSC and hangs shutdown.\n");
	pr_info("spxcam: use: insmod spx_pmic_ldo.ko sid=1 ldo=14 enable=1 ; insmod spx_cam_go.ko\n");
	put_device(&pdev->dev);
	return -EAGAIN;

	vdd = regulator_get(&pdev->dev, "vdd");
	if (IS_ERR(vdd)) {
		pr_info("spxcam: vdd get failed (%ld) - aborting\n", PTR_ERR(vdd));
		put_device(&pdev->dev);
		return -EAGAIN;
	}
	/*
	 * -ETIMEDOUT here means RPMh never ACKed the VRM *enable* command for
	 * ldoa14, exactly as it never ACKed the *mode* command in v5. The
	 * voltage vote for the same resource does succeed (boot logs
	 * "ldo14: Setting 1800000-1800000uV" with no error), so the resource
	 * address is right and only some command types are serviced. Treat a
	 * failure as non-fatal and keep going: if the rail is board-always-on
	 * (or already voted by firmware) the scan below is still meaningful.
	 */
	rail_on = !regulator_enable(vdd);
	pr_info("spxcam: LDO14_A enable=%s, %d uV\n",
		rail_on ? "ok" : "FAILED", regulator_get_voltage(vdd));
	if (!rail_on)
		pr_info("spxcam: NOTE APPS could not vote the rail on; a 'no response' below is NOT proof the sensor is dead\n");

	reset = gpiod_get(&pdev->dev, "reset", GPIOD_OUT_LOW);
	if (IS_ERR(reset)) {
		pr_info("spxcam: reset gpio (TLMM 12) get failed (%ld)\n",
			PTR_ERR(reset));
		reset = NULL;
	} else {
		gpiod_set_value_cansleep(reset, 0);	/* assert reset */
		pr_info("spxcam: TLMM 12 driven LOW (reset asserted)\n");
	}

	usleep_range(1000, 2000);			/* PEP DELAY 1 */

	spx_cci_wakeup();

	mclk = clk_get(&pdev->dev, "mclk");
	if (IS_ERR(mclk)) {
		pr_info("spxcam: mclk2 get failed (%ld)\n", PTR_ERR(mclk));
		mclk = NULL;
	} else {
		ret = clk_set_rate(mclk, mclk_hz);
		if (ret)
			pr_info("spxcam: mclk2 set_rate %d failed (%d)\n", mclk_hz, ret);
		ret = clk_prepare_enable(mclk);
		mclk_on = ret;	/* 0 = enabled; nonzero = never came up */
		pr_info("spxcam: mclk2 enable=%d, rate now %lu Hz\n",
			ret, clk_get_rate(mclk));
		if (ret)
			pr_info("spxcam: NOTE MCLK is NOT running - scan below is not a sensor verdict\n");
	}

	if (reset) {
		gpiod_set_value_cansleep(reset, 1);	/* deassert reset */
		pr_info("spxcam: TLMM 12 driven HIGH (reset released)\n");
	}
	msleep(post_reset_ms);				/* PEP DELAY 2 */

	spx_scan();

	if (mclk) {
		if (!mclk_on)
			clk_disable_unprepare(mclk);
		clk_put(mclk);
	}
	if (rail_on)
		regulator_disable(vdd);
	if (reset)
		gpiod_put(reset);
	regulator_put(vdd);
	put_device(&pdev->dev);

	pr_info("spxcam: done\n");
	return -EAGAIN;
}

static void __exit spx_cam_power_exit(void) { }

module_init(spx_cam_power_init);
module_exit(spx_cam_power_exit);
MODULE_DESCRIPTION("SPX Windows-exact camera power-on + I2C probe");
MODULE_LICENSE("GPL");
