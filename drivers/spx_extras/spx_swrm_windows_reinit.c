// SPDX-License-Identifier: GPL-2.0
/*
 * Exact, locked qcauddev8180 controller-init parity test.
 *
 * This module does not unload or replace soundwire_qcom.  It locks the live
 * controller, reproduces Windows' directional WCD AHB bridge accesses and
 * controller sequence, samples the physical enumeration result, then restores
 * the original WCD bridge access mode.
 */
#include <linux/clk.h>
#include <linux/completion.h>
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/reset.h>
#include <linux/soundwire/sdw.h>

struct dentry;

#define WCD_AHB_WR_DATA		0x0c85
#define WCD_AHB_RD_ADDR		0x0c8d
#define WCD_AHB_RD_DATA		0x0c91
#define WCD_AHB_ACCESS_CFG	0x0c95
#define WCD_AHB_ACCESS_STATUS	0x0c96
#define WCD_AHB_WRITE_MODE	0x03
#define WCD_AHB_READ_MODE	0x0c
#define WCD_GPIO_DIR		0x0042
#define WCD_GPIO_VAL		0x0043
#define WSA_GPIO_MASK		(BIT(1) | BIT(2))
#define WSA_LEFT_HIGH		BIT(1)

#define SWRM_HW_VERSION		0x0000
#define SWRM_COMP_CFG		0x0004
#define SWRM_COMP_SW_RESET	0x0008
#define SWRM_COMP_STATUS	0x0014
#define SWRM_COMP_PARAMS	0x0100
#define SWRM_INTERRUPT_STATUS	0x0200
#define SWRM_INTERRUPT_MASK	0x0204
#define SWRM_CMD_FIFO_CFG	0x0314
#define SWRM_ENUM_CFG		0x0500
#define SWRM_ENUM_ID1		0x0530
#define SWRM_ENUM_ID2		0x0534
#define SWRM_FRAME_CTRL_B0	0x101c
#define SWRM_MCP_BUS_CTRL	0x1044
#define SWRM_MCP_CFG		0x1048
#define SWRM_MCP_SLV_STATUS	0x1090
#define SWRM_NO_PINGS_MASK	GENMASK(21, 17)

/*
 * Prefix of the private live qcom_swrm_ctrl.  It is copied verbatim from this
 * tree only far enough to reach the two locks used here.
 */
struct spx_qcom_swrm_prefix {
	struct sdw_bus bus;
	struct device *dev;
	struct regmap *regmap;
	u32 max_reg;
	const unsigned int *reg_layout;
	void __iomem *mmio;
	struct reset_control *audio_cgcr;
#ifdef CONFIG_DEBUG_FS
	struct dentry *debugfs;
#endif
	struct completion broadcast;
	struct completion enumeration;
	struct mutex ahb_lock;
	struct mutex controller_lock;
};

static struct device *swrm_dev;

static bool do_frame_sweep;
module_param(do_frame_sweep, bool, 0444);
MODULE_PARM_DESC(do_frame_sweep,
		 "Run reversible PHASE and SSP_PERIOD searches after staging");

static int wcd_read_byte(struct regmap *map, unsigned int reg, u8 *value)
{
	int attempt;
	int ret = -EIO;

	for (attempt = 0; attempt < 4; attempt++) {
		ret = regmap_bulk_read(map, reg, value, 1);
		if (!ret)
			return 0;
	}
	return ret;
}

static int wait_access(struct regmap *map, u8 *status)
{
	int poll;
	int ret;

	for (poll = 0; poll < 6; poll++) {
		ret = wcd_read_byte(map, WCD_AHB_ACCESS_STATUS, status);
		if (ret)
			return ret;
		if (*status)
			return 0;
	}
	return -ETIMEDOUT;
}

static int master_write(struct regmap *map, u32 reg, u32 value)
{
	u32 request[2] = { value, reg };
	u8 status = 0;
	int ret;

	ret = regmap_write(map, WCD_AHB_ACCESS_CFG, WCD_AHB_WRITE_MODE);
	if (ret)
		return ret;
	ret = regmap_bulk_write(map, WCD_AHB_WR_DATA,
				request, sizeof(request));
	if (ret)
		return ret;
	return wait_access(map, &status);
}

static int master_read(struct regmap *map, u32 reg, u32 *value)
{
	u8 *bytes = (u8 *)value;
	u8 status = 0;
	int byte;
	int ret;

	*value = 0;
	ret = regmap_write(map, WCD_AHB_ACCESS_CFG, WCD_AHB_READ_MODE);
	if (ret)
		return ret;
	ret = regmap_bulk_write(map, WCD_AHB_RD_ADDR, &reg, sizeof(reg));
	if (ret)
		return ret;
	ret = wait_access(map, &status);
	if (ret)
		return ret;
	for (byte = 0; byte < sizeof(*value); byte++) {
		ret = wcd_read_byte(map, WCD_AHB_RD_DATA + byte,
				    &bytes[byte]);
		if (ret)
			return ret;
	}
	return 0;
}

static int checked_write(struct regmap *map, u32 reg, u32 value)
{
	int ret = master_write(map, reg, value);

	if (ret)
		pr_err("spxwininit: write reg=%#x val=%#x ret=%d\n",
		       reg, value, ret);
	return ret;
}

static bool scan_enum_table(struct regmap *map, const char *kind, int setting,
			    u32 *last_slv)
{
	static unsigned int anomalies;
	u8 *buf1;
	u8 *buf2;
	u64 addr;
	u32 id1;
	u32 id2;
	int dev;

	master_read(map, SWRM_MCP_SLV_STATUS, last_slv);
	for (dev = 1; dev <= SDW_MAX_DEVICES; dev++) {
		id1 = 0;
		id2 = 0;
		master_read(map, SWRM_ENUM_ID1 + 8 * (dev - 1), &id1);
		master_read(map, SWRM_ENUM_ID2 + 8 * (dev - 1), &id2);
		if (id1 || id2) {
			buf1 = (u8 *)&id1;
			buf2 = (u8 *)&id2;
			addr = buf2[1] | ((u64)buf2[0] << 8) |
			       ((u64)buf1[3] << 16) |
			       ((u64)buf1[2] << 24) |
			       ((u64)buf1[1] << 32) |
			       ((u64)buf1[0] << 40);
			if (FIELD_GET(SDW_MFG_ID_MASK, addr) == 0x0217 &&
			    FIELD_GET(SDW_PART_ID_MASK, addr) == 0x2010) {
				pr_info("spxwinsweep: VALID %s=%d dev=%d slv=%#x addr=%#llx id1=%#x id2=%#x\n",
					kind, setting, dev, *last_slv,
					addr, id1, id2);
				return true;
			}
			if (anomalies++ < 40)
				pr_info("spxwinsweep: fragment %s=%d dev=%d slv=%#x addr=%#llx id1=%#x id2=%#x\n",
					kind, setting, dev, *last_slv,
					addr, id1, id2);
		}
	}
	return false;
}

static int __init spx_swrm_windows_reinit_init(void)
{
	struct spx_qcom_swrm_prefix *ctrl;
	struct regmap *map;
	unsigned int saved_access_cfg;
	unsigned int saved_gpio_dir = 0;
	unsigned int saved_gpio_val = 0;
	u32 version = 0;
	u32 cfg = 0;
	u32 comp = 0;
	u32 params = 0;
	u32 irq = 0;
	u32 slv = 0;
	u32 id1 = 0;
	u32 id2 = 0;
	u32 original_frame = 0;
	u32 sweep_slv = 0;
	bool found = false;
	int setting;
	int sample;
	int poll;
	int ret;

	swrm_dev = bus_find_device_by_name(&platform_bus_type, NULL,
					   "wcd934x-soundwire.5.auto");
	if (!swrm_dev)
		return -ENODEV;
	ctrl = dev_get_drvdata(swrm_dev);
	map = dev_get_regmap(swrm_dev->parent, NULL);
	if (!ctrl || !map) {
		ret = -ENODEV;
		goto err_put;
	}
	ret = regmap_read(map, WCD_AHB_ACCESS_CFG, &saved_access_cfg);
	if (ret)
		goto err_put;
	ret = regmap_read(map, WCD_GPIO_DIR, &saved_gpio_dir);
	if (ret)
		goto err_put;
	ret = regmap_read(map, WCD_GPIO_VAL, &saved_gpio_val);
	if (ret)
		goto err_put;

	mutex_lock(&ctrl->bus.bus_lock);
	mutex_lock(&ctrl->controller_lock);
	mutex_lock(&ctrl->ahb_lock);

	/* Start the controller on a physically quiet WSA bus. */
	regmap_update_bits(map, WCD_GPIO_VAL, WSA_GPIO_MASK, 0);
	regmap_update_bits(map, WCD_GPIO_DIR,
			   WSA_GPIO_MASK, WSA_GPIO_MASK);
	msleep(20);

	/* Windows' first controller read, then its observed reset/config order. */
	ret = master_read(map, SWRM_HW_VERSION, &version);
	if (ret)
		goto out_unlock;
	ret = checked_write(map, SWRM_COMP_SW_RESET, 1);
	if (ret)
		goto out_unlock;
	ret = checked_write(map, SWRM_COMP_SW_RESET, 1);
	if (ret)
		goto out_unlock;
	ret = checked_write(map, SWRM_CMD_FIFO_CFG, 3);
	if (ret)
		goto out_unlock;
	ret = master_read(map, SWRM_MCP_CFG, &cfg);
	if (ret)
		goto out_unlock;
	cfg &= ~SWRM_NO_PINGS_MASK;
	ret = checked_write(map, SWRM_MCP_CFG, cfg);
	if (ret)
		goto out_unlock;
	ret = checked_write(map, SWRM_INTERRUPT_MASK, 0);
	if (ret)
		goto out_unlock;
	ret = checked_write(map, SWRM_INTERRUPT_MASK, 0x1c3fd);
	if (ret)
		goto out_unlock;
	ret = checked_write(map, SWRM_ENUM_CFG, 1);
	if (ret)
		goto out_unlock;
	ret = checked_write(map, SWRM_FRAME_CTRL_B0, 0x10000);
	if (ret)
		goto out_unlock;
	ret = checked_write(map, SWRM_MCP_BUS_CTRL, 2);
	if (ret)
		goto out_unlock;
	ret = checked_write(map, SWRM_COMP_CFG, 1);
	if (ret)
		goto out_unlock;
	for (poll = 0; poll < 11; poll++) {
		ret = master_read(map, SWRM_COMP_STATUS, &comp);
		if (ret || (comp & 1))
			break;
	}
	if (ret)
		goto out_unlock;
	ret = master_read(map, SWRM_COMP_PARAMS, &params);
	if (ret)
		goto out_unlock;

	/* Wake only the left WSA, then give hardware auto-enum a fresh edge. */
	regmap_update_bits(map, WCD_GPIO_VAL,
			   WSA_GPIO_MASK, WSA_LEFT_HIGH);
	msleep(20);
	ret = checked_write(map, SWRM_ENUM_CFG, 0);
	if (ret)
		goto out_unlock;
	ret = checked_write(map, SWRM_ENUM_CFG, 1);
	if (ret)
		goto out_unlock;

	for (sample = 0; sample < 200; sample++) {
		master_read(map, SWRM_COMP_STATUS, &comp);
		master_read(map, SWRM_INTERRUPT_STATUS, &irq);
		master_read(map, SWRM_MCP_SLV_STATUS, &slv);
		master_read(map, SWRM_ENUM_ID1, &id1);
		master_read(map, SWRM_ENUM_ID2, &id2);
		if (slv || id1 || id2)
			pr_info("spxwininit %d/200 comp=%#x irq=%#x slv=%#x id1=%#x id2=%#x\n",
				sample + 1, comp, irq, slv, id1, id2);
		msleep(5);
	}
	pr_info("spxwininit: complete version=%#x params=%#x comp=%#x irq=%#x slv=%#x id1=%#x id2=%#x\n",
		version, params, comp, irq, slv, id1, id2);

	/*
	 * Reversible response-window search.  First vary only documented
	 * FRAME_CTRL PHASE[15:11] while retaining Windows' SSP_PERIOD=1.
	 * Then exercise the historical SPX SSP_PERIOD search.  Every setting
	 * gets a fresh hardware auto-enumeration and a full 12-slot table scan.
	 */
	ret = master_read(map, SWRM_FRAME_CTRL_B0, &original_frame);
	if (ret)
		goto out_unlock;
	for (setting = 0;
	     do_frame_sweep && setting < 32 && !found;
	     setting++) {
		checked_write(map, SWRM_ENUM_CFG, 0);
		checked_write(map, SWRM_FRAME_CTRL_B0,
			      0x10000 | (setting << 11));
		checked_write(map, SWRM_ENUM_CFG, 1);
		msleep(10);
		found = scan_enum_table(map, "phase", setting, &sweep_slv);
	}
	for (setting = 0;
	     do_frame_sweep && setting < 128 && !found;
	     setting++) {
		checked_write(map, SWRM_ENUM_CFG, 0);
		checked_write(map, SWRM_FRAME_CTRL_B0, setting << 16);
		checked_write(map, SWRM_ENUM_CFG, 1);
		msleep(10);
		found = scan_enum_table(map, "ssp", setting, &sweep_slv);
	}
	if (do_frame_sweep) {
		checked_write(map, SWRM_ENUM_CFG, 0);
		checked_write(map, SWRM_FRAME_CTRL_B0, original_frame);
		checked_write(map, SWRM_ENUM_CFG, 1);
		pr_info("spxwinsweep: complete found=%d restored_frame=%#x last_slv=%#x\n",
			found, original_frame, sweep_slv);
	}

out_unlock:
	regmap_write(map, WCD_AHB_ACCESS_CFG, saved_access_cfg);
	regmap_update_bits(map, WCD_GPIO_VAL, WSA_GPIO_MASK,
			   saved_gpio_val & WSA_GPIO_MASK);
	regmap_update_bits(map, WCD_GPIO_DIR, WSA_GPIO_MASK,
			   saved_gpio_dir & WSA_GPIO_MASK);
	mutex_unlock(&ctrl->ahb_lock);
	mutex_unlock(&ctrl->controller_lock);
	mutex_unlock(&ctrl->bus.bus_lock);
	if (ret)
		goto err_put;
	return 0;

err_put:
	put_device(swrm_dev);
	swrm_dev = NULL;
	return ret;
}

static void __exit spx_swrm_windows_reinit_exit(void)
{
	if (swrm_dev)
		put_device(swrm_dev);
	pr_info("spx_swrm_windows_reinit: unloaded\n");
}

module_init(spx_swrm_windows_reinit_init);
module_exit(spx_swrm_windows_reinit_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX exact locked Windows SoundWire controller reinit");
