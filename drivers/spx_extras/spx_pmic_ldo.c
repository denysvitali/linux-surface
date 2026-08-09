// SPDX-License-Identifier: GPL-2.0
/*
 * spx_pmic_ldo - identify (and optionally enable) a PMIC LDO over SPMI,
 * bypassing RPMh entirely.
 *
 * Why this exists
 * ---------------
 * The Surface Pro X camera rails (LDO14_A 1.8 V for all three sensors, plus
 * LDO17_A/LDO1_A for the rear module) are listed in the vendor's ACPI PEP
 * resource table \_SB.PEP0.CPXC. On Windows they are voted by PEP firmware,
 * which runs on a different RSC DRV than the applications processor.
 *
 * Measured 2026-08-06: every RPMh command to cmd-db resource "ldoa14" from the
 * APPS RSC times out (-ETIMEDOUT), even though apps_rsc's ACK interrupt is
 * demonstrably healthy (IRQ 13, 506+ counts). Qualcomm RSCs silently drop
 * writes to resources the requesting DRV does not own, which presents exactly
 * as a timeout. Worse, the dropped request keeps its active TCS slot forever,
 * so a SECOND rpmh_write() hangs uninterruptibly in rpmh_rsc_send_data().
 *
 * SPMI is a completely independent path to the same PMIC, so it sidesteps the
 * ownership question. This module reads the peripheral ID registers first so
 * the address can be verified before anything is written.
 *
 * PMIC5 (pm8150 family, here "pmc8180") peripheral layout:
 *   LDOn base   = 0x4000 + (n - 1) * 0x100      -> LDO14 = 0x4D00
 *   base + 0x04 = PERPH_TYPE     (0x1C = regulator)
 *   base + 0x05 = PERPH_SUBTYPE
 *   base + 0x46 = EN_CTL         (bit 7 = enable)
 *
 * Default is READ-ONLY. Set enable=1 only after the type/subtype readback has
 * confirmed the address really is an LDO.
 *
 * Loads with -EAGAIN by design so it can be re-run without rmmod.
 */

#include <linux/module.h>
#include <linux/of.h>
#include <linux/spmi.h>
#include <linux/device.h>
#include <linux/delay.h>

static int ldo = 14;
module_param(ldo, int, 0644);
MODULE_PARM_DESC(ldo, "LDO number on PMIC A (camera rail is 14)");

static int sid;
module_param(sid, int, 0644);
MODULE_PARM_DESC(sid, "SPMI slave id (PMIC A = 0)");

static int sweep;
module_param(sweep, int, 0644);
MODULE_PARM_DESC(sweep, "1 = dump every present peripheral on this sid (read-only)");

static int dump;
module_param(dump, int, 0644);
MODULE_PARM_DESC(dump, "1 = hexdump this LDO's registers (read-only)");

static int enable;
module_param(enable, int, 0644);
MODULE_PARM_DESC(enable, "1 = actually set EN_CTL bit 7 (default 0 = read-only)");

#define PERPH_TYPE_OFF		0x04
#define PERPH_SUBTYPE_OFF	0x05
#define EN_CTL_OFF		0x46
#define EN_CTL_ENABLE		BIT(7)
#define PERPH_TYPE_BUCK		0x03
#define PERPH_TYPE_LDO		0x04
#define PERPH_TYPE_VS		0x05
#define PERPH_TYPE_FTS		0x1c

/* PMIC A is pmic@0 under the SPMI bus in the booted DT. */
static struct spmi_device *spx_get_pmic(int usid)
{
	struct device_node *np;
	struct spmi_device *sdev = NULL;
	char path[64];

	/*
	 * of_get_child_by_name() compares only the node name and strips the
	 * "@unit" suffix, so it can never match "pmic@0". Use the full path.
	 */
	snprintf(path, sizeof(path), "/soc@0/spmi@c440000/pmic@%x", usid);
	np = of_find_node_by_path(path);
	if (!np) {
		pr_info("spxldo: no DT node %s\n", path);
		return NULL;
	}
	sdev = spmi_find_device_by_of_node(np);
	of_node_put(np);
	return sdev;
}

static int __init spx_pmic_ldo_init(void)
{
	struct spmi_device *sdev;
	unsigned int base;
	u8 type = 0, subtype = 0, en = 0;
	int ret;

	if (ldo < 1 || ldo > 32) {
		pr_info("spxldo: ldo=%d out of range\n", ldo);
		return -EAGAIN;
	}
	base = 0x4000 + (ldo - 1) * 0x100;

	sdev = spx_get_pmic(sid);
	if (!sdev) {
		pr_info("spxldo: no SPMI device for pmic@%x\n", sid);
		return -EAGAIN;
	}

	/*
	 * The "LDOn = 0x4000 + (n-1)*0x100" formula does not hold on this PMIC
	 * (LDO14 -> 0x4d00 reads -ENODEV). Sweep instead: every peripheral
	 * occupies one 0x100 page and reports PERPH_TYPE/SUBTYPE at +0x04/+0x05,
	 * with absent pages returning -ENODEV. This builds the real map.
	 */
	if (sweep) {
		unsigned int p;
		int n = 0;

		pr_info("spxldo: sweeping sid %d\n", sid);
		for (p = 0; p <= 0xff; p++) {
			u8 t = 0, st = 0, e = 0;

			if (spmi_ext_register_readl(sdev, (p << 8) + PERPH_TYPE_OFF, &t, 1))
				continue;
			spmi_ext_register_readl(sdev, (p << 8) + PERPH_SUBTYPE_OFF, &st, 1);
			spmi_ext_register_readl(sdev, (p << 8) + EN_CTL_OFF, &e, 1);
			pr_info("spxldo:   0x%04x TYPE=0x%02x SUBTYPE=0x%02x EN_CTL=0x%02x%s\n",
				p << 8, t, st, e,
				(t == PERPH_TYPE_LDO || t == PERPH_TYPE_BUCK ||
			 t == PERPH_TYPE_VS || t == PERPH_TYPE_FTS) ?
				"  <-- REGULATOR" : "");
			n++;
		}
		pr_info("spxldo: sid %d has %d peripheral(s)\n", sid, n);
		return -EAGAIN;
	}

	ret = spmi_ext_register_readl(sdev, base + PERPH_TYPE_OFF, &type, 1);
	if (ret) {
		pr_info("spxldo: read TYPE @0x%04x failed (%d)\n",
			base + PERPH_TYPE_OFF, ret);
		return -EAGAIN;
	}
	spmi_ext_register_readl(sdev, base + PERPH_SUBTYPE_OFF, &subtype, 1);
	spmi_ext_register_readl(sdev, base + EN_CTL_OFF, &en, 1);

	pr_info("spxldo: LDO%d_A sid%d base 0x%04x: TYPE=0x%02x SUBTYPE=0x%02x EN_CTL=0x%02x -> rail is %s\n",
		ldo, sid, base, type, subtype, en,
		(en & EN_CTL_ENABLE) ? "ON" : "OFF");

	if (type != PERPH_TYPE_LDO) {
		pr_info("spxldo: TYPE 0x%02x is not an LDO (0x%02x) - address is WRONG, refusing to write\n",
			type, PERPH_TYPE_LDO);
		return -EAGAIN;
	}

	if (dump) {
		unsigned int o;

		for (o = 0x00; o < 0x60; o += 8) {
			u8 b[8] = {0};
			int k;

			for (k = 0; k < 8; k++)
				spmi_ext_register_readl(sdev, base + o + k, &b[k], 1);
			pr_info("spxldo:   +0x%02x: %02x %02x %02x %02x %02x %02x %02x %02x\n",
				o, b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]);
		}
		return -EAGAIN;
	}

	if (!enable) {
		pr_info("spxldo: read-only (pass enable=1 to set, enable=-1 to clear, EN_CTL bit 7)\n");
		return -EAGAIN;
	}

	/*
	 * enable=-1 clears the bit. Needed so a camera test boot can put the
	 * sensor rails back down before a reboot instead of handing the next
	 * boot a still-powered sensor.
	 */
	if (enable < 0)
		en &= ~EN_CTL_ENABLE;
	else
		en |= EN_CTL_ENABLE;
	ret = spmi_ext_register_writel(sdev, base + EN_CTL_OFF, &en, 1);
	if (ret) {
		pr_info("spxldo: EN_CTL write failed (%d)\n", ret);
		return -EAGAIN;
	}
	usleep_range(1000, 2000);
	spmi_ext_register_readl(sdev, base + EN_CTL_OFF, &en, 1);
	pr_info("spxldo: EN_CTL now 0x%02x -> rail is %s\n",
		en, (en & EN_CTL_ENABLE) ? "ON" : "OFF");

	return -EAGAIN;
}

static void __exit spx_pmic_ldo_exit(void) { }

module_init(spx_pmic_ldo_init);
module_exit(spx_pmic_ldo_exit);
MODULE_DESCRIPTION("SPX PMIC LDO identify/enable over SPMI (RPMh bypass)");
MODULE_LICENSE("GPL");
