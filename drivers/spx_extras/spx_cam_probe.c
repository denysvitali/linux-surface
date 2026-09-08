// SPDX-License-Identifier: GPL-2.0
/*
 * spx_cam_probe - Surface Pro X camera sensor discovery over CCI.
 *
 * Answers one question: are the camera sensor supply rails always-on on this
 * board? The Windows drivers never touch the rails (the sequence runs in PEP
 * firmware), and the SPX DSDT exposes no sensor reset/power GPIO at all - the
 * only two camera GPIOs in the whole table are the privacy/IR LEDs. So either
 * the rails are permanently up and the sensors will answer on I2C as soon as
 * MCLK runs, or they are firmware-gated and nothing will answer.
 *
 * What it does: enables the four camera MCLKs at 24 MHz (the rate recovered
 * from the Windows Chromatix sensor blobs), then reads the chip-ID register of
 * each expected sensor on each CCI bus. Register addresses and expected IDs
 * come from the ACPI SCFG methods.
 *
 * Read-only: it issues I2C reads and never writes to a sensor. It only touches
 * addresses that ACPI says are cameras, so it cannot disturb unrelated devices.
 *
 * Loads with -EAGAIN by design, like the other spx_extras tools, so it can be
 * re-run without rmmod.
 */

#include <linux/clk.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/delay.h>

static int mclk_ms = 20;
module_param(mclk_ms, int, 0644);
MODULE_PARM_DESC(mclk_ms, "settle delay after enabling MCLK, in ms");

struct spx_sensor {
	const char *name;
	u8 addr;		/* 7-bit */
	u16 id_reg;
	u16 id_val;
};

/* From ACPI _SB.CAMS/CAMF/CAMI SCFG: (uid<<16)|addr8, (chipid<<16)|idreg. */
static const struct spx_sensor sensors[] = {
	{ "ov13858 (rear)",  0x10, 0x300b, 0xd855 },
	{ "ov5693 (front)",  0x36, 0x300a, 0x5690 },
	{ "ov7251 (aux/IR)", 0x60, 0x300a, 0x7750 },
};

/* OV sensors: 16-bit register address, 8-bit data. */
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

/* MCLK ids from dt-bindings/clock/qcom,sc8180x-camcc.h */
static const u32 mclk_ids[4] = { 99, 101, 103, 105 };

static void spx_set_mclk_rate(void)
{
	struct device_node *camcc;
	int i;

	camcc = of_find_compatible_node(NULL, NULL, "qcom,sc8180x-camcc");
	if (!camcc)
		return;

	for (i = 0; i < 4; i++) {
		struct of_phandle_args spec = {
			.np = camcc, .args_count = 1, .args[0] = mclk_ids[i],
		};
		struct clk *c = of_clk_get_from_provider(&spec);

		if (IS_ERR(c))
			continue;
		if (clk_set_rate(c, 24000000))
			pr_info("spxcam: MCLK%d set_rate 24MHz failed\n", i);
		else
			pr_info("spxcam: MCLK%d now %lu Hz\n", i, clk_get_rate(c));
		clk_put(c);
	}
	of_node_put(camcc);
}

static void spx_scan_adapter(struct i2c_adapter *adap, const char *label)
{
	u8 dummy;
	int i;

	/*
	 * Warm-up: one throwaway transfer runtime-resumes the CCI controller,
	 * which powers TITAN_TOP and enables every clock listed in the node -
	 * including the MCLKs. Autosuspend is 1 s, so MCLK stays up for the
	 * scan below. Enabling the MCLK branches directly from here instead
	 * fails ("status stuck at off") because the camcc block is unpowered.
	 */
	spx_ov_read8(adap, sensors[0].addr, sensors[0].id_reg, &dummy);

	/*
	 * The CCI node lists the MCLKs so they get enabled, but nothing sets
	 * their rate, so they come up at XO (19.2 MHz). The Windows Chromatix
	 * blobs specify 24 MHz for all three sensors. Set it now, while the
	 * branches are enabled and TITAN_TOP is powered - a clk_set_rate before
	 * that point does not stick.
	 */
	spx_set_mclk_rate();
	msleep(mclk_ms);

	for (i = 0; i < ARRAY_SIZE(sensors); i++) {
		const struct spx_sensor *s = &sensors[i];
		u8 hi = 0, lo = 0;
		u16 id;
		int ret;

		ret = spx_ov_read8(adap, s->addr, s->id_reg, &hi);
		if (ret) {
			pr_info("spxcam:   %-16s @0x%02x : no response (%d)\n",
				s->name, s->addr, ret);
			continue;
		}
		ret = spx_ov_read8(adap, s->addr, s->id_reg + 1, &lo);
		if (ret) {
			pr_info("spxcam:   %-16s @0x%02x : partial, hi=0x%02x (%d)\n",
				s->name, s->addr, hi, ret);
			continue;
		}

		id = (hi << 8) | lo;
		pr_info("spxcam:   %-16s @0x%02x : ID 0x%04x (expect 0x%04x) %s\n",
			s->name, s->addr, id, s->id_val,
			id == s->id_val ? "*** MATCH ***" : "mismatch");
	}
}

static int __init spx_cam_probe_init(void)
{
	struct device_node *np;
	int found = 0;

	pr_info("spxcam: MCLKs are enabled by the CCI node clocks list (runtime PM)\n");
	msleep(mclk_ms);

	/* Walk every CCI i2c-bus node and scan it. */
	for_each_compatible_node(np, NULL, "qcom,msm8996-cci") {
		struct device_node *bus;

		for_each_child_of_node(np, bus) {
			struct i2c_adapter *adap = of_find_i2c_adapter_by_node(bus);

			if (!adap)
				continue;
			found++;
			pr_info("spxcam: scanning %pOF (%s)\n", bus, adap->name);
			spx_scan_adapter(adap, adap->name);
			i2c_put_adapter(adap);
		}
	}

	if (!found)
		pr_info("spxcam: no CCI i2c adapters found - is i2c-qcom-cci loaded and probed?\n");

	pr_info("spxcam: done\n");
	return -EAGAIN;	/* by design: reloadable without rmmod */
}

static void __exit spx_cam_probe_exit(void) { }

module_init(spx_cam_probe_init);
module_exit(spx_cam_probe_exit);
MODULE_DESCRIPTION("SPX camera sensor discovery over CCI");
MODULE_LICENSE("GPL");
