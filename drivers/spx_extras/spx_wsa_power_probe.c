// SPDX-License-Identifier: GPL-2.0
/*
 * SPX: settle the WSA SD_N polarity question empirically.
 *
 * The two reference documents disagree (CLAUDE.md: LOW = on; PROGRESS.md: HIGH =
 * on), the DT binding says powerdown-gpios/GPIO_ACTIVE_LOW (=> physical HIGH is
 * "amp on"), and wsa881x.c's helper comment says the reverse. Every attempt to
 * decide it via FORCE-ATTACH returned "id=aa aa aa aa aa aa", which is the qcom
 * read path failing (rc=4), not a power measurement.
 *
 * This probe avoids all of that. A powered amp announces itself on the bus, which
 * latches NEW_SLAVE_ATTACHED / SLAVE_PEND_IRQ in the master's INTERRUPT_STATUS.
 * So: park both amps, clear the latch, apply one polarity, wait, read the latch.
 * Whichever polarity produces an announcement is the one that powers the amp.
 *
 * Deliberately does NOT reset the master: COMP_SW_RESET is what makes the bridge
 * return one constant for every address. COMP_PARAMS is checked as a canary before
 * and after, and the result is discarded if the bridge is lying.
 *
 *   insmod spx_wsa_power_probe.ko            # tests both polarities
 *   insmod spx_wsa_power_probe.ko val=0x02   # test one specific GPIO value
 *
 * Fails with -EAGAIN by design so it can be re-run without rmmod.
 */
#include <linux/delay.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>

#define BR_WR_DATA		0x0c85
#define BR_RD_ADDR		0x0c8d
#define BR_RD_DATA		0x0c91
#define BR_STATUS		0x0c96

#define SWRM_COMP_PARAMS	0x0100
#define SWRM_COMP_PARAMS_EXPECTED	0x016840c6
#define SWRM_INTERRUPT_STATUS	0x0200
#define SWRM_INTERRUPT_CLEAR	0x0208
#define SWRM_MCP_SLV_STATUS	0x1090

#define INT_SLAVE_PEND_IRQ	BIT(0)
#define INT_NEW_SLAVE_ATTACHED	BIT(1)
#define INT_CHANGE_ENUM_STATUS	BIT(2)

#define WCD_GPIO_DIR		0x0042
#define WCD_GPIO_VAL		0x0043
#define WSA_GPIO_MASK		(BIT(1) | BIT(2))

static int val = -1;
module_param(val, int, 0400);
MODULE_PARM_DESC(val, "GPIO value to test (-1 = try 0x02 then 0x04)");

static int settle_ms = 1500;
module_param(settle_ms, int, 0400);
MODULE_PARM_DESC(settle_ms, "time to wait for the amp to announce itself");

static struct regmap *map;

static int br_read(u32 reg, u32 *out)
{
	u32 addr = reg, first = 0, v = 0;
	int i, ret;

	ret = regmap_bulk_write(map, BR_RD_ADDR, (u8 *)&addr, 4);
	if (ret)
		return ret;
	usleep_range(500, 550);
	for (i = 0; i < 200; i++) {
		u32 st;

		if (!regmap_read(map, BR_STATUS, &st) && (st & 1))
			break;
		udelay(5);
	}
	ret = regmap_bulk_read(map, BR_RD_DATA, &first, 4);
	if (ret)
		return ret;
	usleep_range(500, 550);
	ret = regmap_bulk_read(map, BR_RD_DATA, &v, 4);
	if (ret)
		return ret;
	*out = v;
	return 0;
}

static int br_write(u32 reg, u32 value)
{
	u32 request[2] = { value, reg };
	int ret;

	ret = regmap_bulk_write(map, BR_WR_DATA, (u8 *)request, sizeof(request));
	usleep_range(500, 550);
	return ret;
}

static bool bridge_sane(const char *when)
{
	u32 params = 0;

	if (br_read(SWRM_COMP_PARAMS, &params) ||
	    params != SWRM_COMP_PARAMS_EXPECTED) {
		pr_err("spx_pwrprobe: bridge insane %s: COMP_PARAMS=%#x (want %#x) -- result discarded\n",
		       when, params, SWRM_COMP_PARAMS_EXPECTED);
		return false;
	}
	return true;
}

/*
 * Detect a *change*, never a level. NEW_SLAVE_ATTACHED was observed staying set
 * through INTERRUPT_CLEAR, so testing "is the bit set" reports an announcement for
 * every polarity, including before any pin is touched. Only the transition from
 * the parked baseline to the applied value carries information.
 */
static void probe_one(unsigned int park, unsigned int gpio_val,
		      struct regmap *wcd)
{
	u32 base_irq = 0, base_slv = 0, irq = 0, slv = 0;
	bool changed;

	regmap_update_bits(wcd, WCD_GPIO_DIR, WSA_GPIO_MASK, WSA_GPIO_MASK);
	regmap_update_bits(wcd, WCD_GPIO_VAL, WSA_GPIO_MASK,
			   park & WSA_GPIO_MASK);
	msleep(2500);

	if (!bridge_sane("before"))
		return;
	br_write(SWRM_INTERRUPT_CLEAR, ~0U);
	msleep(50);
	br_read(SWRM_INTERRUPT_STATUS, &base_irq);
	br_read(SWRM_MCP_SLV_STATUS, &base_slv);

	regmap_update_bits(wcd, WCD_GPIO_VAL, WSA_GPIO_MASK,
			   gpio_val & WSA_GPIO_MASK);
	msleep(settle_ms);

	br_read(SWRM_INTERRUPT_STATUS, &irq);
	br_read(SWRM_MCP_SLV_STATUS, &slv);

	if (!bridge_sane("after"))
		return;

	changed = (irq != base_irq) || (slv != base_slv);

	pr_info("spx_pwrprobe: park=%#04x -> VAL=%#04x : INT %#010x->%#010x SLV %#010x->%#010x : %s\n",
		park, gpio_val, base_irq, irq, base_slv, slv,
		changed ? "CHANGED (this transition powers an amp)" :
			  "no change");
}

static int __init spx_pwrprobe_init(void)
{
	struct wcd934x_ddata *dd;
	struct device *dev;

	dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
	if (!dev)
		return -ENODEV;
	dd = dev_get_drvdata(dev);
	put_device(dev);
	if (!dd || !dd->regmap)
		return -ENODEV;
	map = dd->regmap;

	pr_info("spx_pwrprobe: === SD_N polarity probe ===\n");
	if (val >= 0) {
		probe_one(0x00, val, dd->regmap);
	} else {
		/*
		 * Both park states are tried, because which one is "both off"
		 * is precisely what is in dispute. The park that yields a
		 * quiet baseline and then reacts to raising/lowering one pin
		 * is the correct off state.
		 */
		pr_info("spx_pwrprobe: --- park LOW (0x00), raise pin1 ---\n");
		probe_one(0x00, 0x02, dd->regmap);
		pr_info("spx_pwrprobe: --- park LOW (0x00), raise pin2 ---\n");
		probe_one(0x00, 0x04, dd->regmap);
		pr_info("spx_pwrprobe: --- park HIGH (0x06), drop pin1 ---\n");
		probe_one(0x06, 0x04, dd->regmap);
		pr_info("spx_pwrprobe: --- park HIGH (0x06), drop pin2 ---\n");
		probe_one(0x06, 0x02, dd->regmap);
	}
	pr_info("spx_pwrprobe: === done ===\n");

	return -EAGAIN;
}

static void __exit spx_pwrprobe_exit(void)
{
}

module_init(spx_pwrprobe_init);
module_exit(spx_pwrprobe_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX: determine WSA SD_N polarity from bus announcements");
