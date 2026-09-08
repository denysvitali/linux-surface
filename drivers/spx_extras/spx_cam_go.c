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
#include <linux/pinctrl/consumer.h>
#include <linux/platform_device.h>
#include <linux/regulator/consumer.h>

static int mclk_hz = 19200000;
module_param(mclk_hz, int, 0644);
MODULE_PARM_DESC(mclk_hz, "MCLK rate (PEP table says 19200000)");

/*
 * HAZARD, measured 2026-08-06: regulator_enable() on vreg_l14a returns
 * -ETIMEDOUT (RPMh never ACKs the VRM enable for ldoa14) AND leaves the active
 * TCS slot occupied. A SECOND attempt then hangs forever in
 * rpmh_rsc_send_data() waiting for a free slot -- uninterruptible D state,
 * only a reboot clears it. Windows votes this rail from PEP firmware, not from
 * a driver, so it is very likely not APPS-owned. Default to NOT touching it.
 */
static int use_regulator;
module_param(use_regulator, int, 0644);
MODULE_PARM_DESC(use_regulator, "vote LDO14_A on (DANGEROUS: wedges the RSC, see comment)");

static int do_sweep;
module_param(do_sweep, int, 0644);
MODULE_PARM_DESC(do_sweep, "1 = full 7-bit sweep (slow: ~11.6 s per bus when transfers time out)");

static int use_mclk = 1;
module_param(use_mclk, int, 0644);
MODULE_PARM_DESC(use_mclk, "0 = do NOT enable MCLK (an OV sensor with no MCLK can hold SCL)");

static int reset_release = 1;
module_param(reset_release, int, 0644);
MODULE_PARM_DESC(reset_release, "0 = leave reset asserted during the scan");

/*
 * Nothing sets the camcc RCG rates, so cam_cc_camnoc_axi_clk_src and
 * cam_cc_cci_N_clk_src both idle at XO 19.2 MHz. Their freq tables
 * (camcc-sc8180x.c) offer camnoc up to 480 MHz and CCI 37.5 MHz off PLL0.
 * A starved CAMNOC/AHB path is a candidate for "master N queue 0 timeout".
 * 0 = leave the rate alone.
 */
static int camnoc_hz = 400000000;
module_param(camnoc_hz, int, 0644);
MODULE_PARM_DESC(camnoc_hz, "cam_cc_camnoc_axi_clk_src rate (0 = leave)");

static int cci_hz = 37500000;
module_param(cci_hz, int, 0644);
MODULE_PARM_DESC(cci_hz, "cam_cc_cci_{1,2}_clk_src rate (0 = leave)");

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

/* camcc clock ids from dt-bindings/clock/qcom,sc8180x-camcc.h */
#define SPX_CAMNOC_AXI_CLK_SRC	6
#define SPX_CCI_1_CLK_SRC	11
#define SPX_CCI_2_CLK_SRC	13

static void spx_set_camcc_rate(u32 id, const char *name, int hz)
{
	struct device_node *camcc;
	struct of_phandle_args spec;
	struct clk *c;
	int ret;

	if (!hz)
		return;
	camcc = of_find_compatible_node(NULL, NULL, "qcom,sc8180x-camcc");
	if (!camcc)
		return;
	spec.np = camcc;
	spec.args_count = 1;
	spec.args[0] = id;
	c = of_clk_get_from_provider(&spec);
	of_node_put(camcc);
	if (IS_ERR(c))
		return;
	ret = clk_set_rate(c, hz);
	pr_info("spxcam: %s -> %d Hz: ret=%d, now %lu Hz\n",
		name, hz, ret, clk_get_rate(c));
	clk_put(c);
}

static void spx_scan(void)
{
	struct device_node *np;

	for_each_compatible_node(np, NULL, "qcom,msm8996-cci") {
		struct device_node *bus;

		for_each_child_of_node(np, bus) {
			struct i2c_adapter *adap = of_find_i2c_adapter_by_node(bus);
			int i, a, ret, seen = 0;

			if (!adap)
				continue;
			pr_info("spxcam: scanning %pOF\n", bus);

			/* Full 7-bit sweep: does ANYTHING live on this bus? */
			for (a = 0x08; do_sweep && a < 0x78; a++) {
				u8 v;

				if (!spx_ov_read8(adap, a, 0x300a, &v))
					pr_info("spxcam:   sweep: ACK at 0x%02x\n", a), seen++;
			}
			if (do_sweep)
				pr_info("spxcam:   sweep found %d device(s)\n", seen);
			for (i = 0; i < ARRAY_SIZE(sensors); i++) {
				const struct spx_sensor *s = &sensors[i];
				u8 hi = 0, lo = 0;
				u16 id;

				ret = spx_ov_read8(adap, s->addr, s->id_reg, &hi);
				if (ret) {
					/*
					 * -ENXIO/-EREMOTEIO = the sensor NAKed its
					 * address: the bus and controller are fine
					 * and nothing is answering (rail down, or
					 * wrong bus). -ETIMEDOUT = the transfer
					 * never completed: controller/pinmux
					 * problem, a different bug entirely.
					 */
					pr_info("spxcam:   %-22s @0x%02x : no response (%d %s)\n",
						s->name, s->addr, ret,
						ret == -ETIMEDOUT ? "TIMEOUT - bus/controller" : "NAK - bus ok, nobody home");
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

static int __init spx_cam_go_init(void)
{
	struct device_node *np;
	struct platform_device *pdev;
	struct gpio_desc *reset;
	struct regulator *vdd;
	struct clk *mclk;
	struct pinctrl *pctl;
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
	vdd = NULL;
	if (use_regulator) {
		vdd = regulator_get(&pdev->dev, "vdd");
		if (IS_ERR(vdd)) {
			pr_info("spxcam: vdd get failed (%ld) - aborting\n", PTR_ERR(vdd));
			put_device(&pdev->dev);
			return -EAGAIN;
		}
	} else {
		pr_info("spxcam: NOT voting LDO14_A (APPS enable wedges the RSC); assuming board/firmware keeps it up\n");
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
	rail_on = vdd && !regulator_enable(vdd);
	if (vdd)
		pr_info("spxcam: LDO14_A enable=%s, %d uV\n",
			rail_on ? "ok" : "FAILED", regulator_get_voltage(vdd));
	if (vdd && !rail_on)
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

	/*
	 * Nothing binds a driver to spx-cam-test, and the driver core only
	 * applies a device's default pinctrl state at bind time. So pinctrl-0
	 * (cam_mclk on TLMM 15 + reset on TLMM 12) was silently never applied:
	 * MCLK2 ran inside the SoC but never reached the sensor pin. Select it
	 * by hand here. (gpiod_get() muxes TLMM 12 to the gpio function on its
	 * own, so only the MCLK pin actually depended on this.)
	 */
	pctl = pinctrl_get_select_default(&pdev->dev);
	pr_info("spxcam: pinctrl default state: %s\n",
		IS_ERR(pctl) ? "FAILED" : "applied (TLMM15 -> cam_mclk)");

	usleep_range(1000, 2000);			/* PEP DELAY 1 */

	spx_cci_wakeup();

	/* Rates only stick once TITAN_TOP is powered, i.e. after the warm-up. */
	spx_set_camcc_rate(SPX_CAMNOC_AXI_CLK_SRC, "camnoc_axi_src", camnoc_hz);
	spx_set_camcc_rate(SPX_CCI_1_CLK_SRC, "cci_1_src", cci_hz);
	spx_set_camcc_rate(SPX_CCI_2_CLK_SRC, "cci_2_src", cci_hz);

	mclk = use_mclk ? clk_get(&pdev->dev, "mclk") : ERR_PTR(-ENODEV);
	if (!use_mclk)
		pr_info("spxcam: MCLK deliberately NOT enabled (use_mclk=0)\n");
	if (IS_ERR(mclk)) {
		if (use_mclk)
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

	if (reset && reset_release) {
		gpiod_set_value_cansleep(reset, 1);	/* deassert reset */
		pr_info("spxcam: TLMM 12 driven HIGH (reset released)\n");
	} else if (reset) {
		pr_info("spxcam: TLMM 12 left LOW (reset still asserted)\n");
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
	if (vdd)
		regulator_put(vdd);
	put_device(&pdev->dev);

	if (!IS_ERR(pctl))
		pinctrl_put(pctl);

	pr_info("spxcam: done\n");
	return -EAGAIN;
}

static void __exit spx_cam_go_exit(void) { }

module_init(spx_cam_go_init);
module_exit(spx_cam_go_exit);
MODULE_DESCRIPTION("SPX camera MCLK + I2C probe (no RPMh rail vote)");
MODULE_LICENSE("GPL");
