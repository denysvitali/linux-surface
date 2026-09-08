// SPDX-License-Identifier: GPL-2.0
/*
 * Reversible SPX diagnostic: issue one SoundWire Device-ID read containing
 * all six bytes instead of qcom.c's QCOM_SWRM_MAX_RD_LEN == 1 split.
 */
#include <linux/device.h>
#include <linux/completion.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/soundwire/sdw.h>
#include <linux/soundwire/sdw_registers.h>

struct dentry;

/*
 * Prefix copied from this tree's private qcom_swrm_ctrl, only far enough to
 * serialize against its IRQ handler with controller_lock.
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

#define WCD_AHB_ACCESS_CFG	0x0c95
#define WCD_AHB_WRITE_MODE	0x03
#define WCD_AHB_READ_MODE	0x0c

#define SWRM_COMP_STATUS	0x0014
#define SWRM_INTERRUPT_CPU_EN	0x0210
#define SWRM_FIFO_RD_CMD	0x0304
#define SWRM_FIFO_STATUS	0x030c
#define SWRM_FIFO_RD_DATA	0x0318
#define SWRM_ENUM_CFG		0x0500
#define SWRM_MCP_CFG		0x1048
#define SWRM_MCP_CFG_SYNC	BIT(1)
#define SWRM_COMP_SYNC_MASK	GENMASK(5, 4)
#define SWRM_COMP_SYNC_READY	(2U << 4)
#define SWRM_RD_COUNT_MASK	GENMASK(20, 16)

typedef int (*spx_ahb_read_fn)(void *ctrl, int reg, u32 *val);
typedef int (*spx_ahb_write_fn)(void *ctrl, int reg, int val);

static struct device *swrm_dev;
static void *swrm_ctrl;
static struct regmap *wcd_regmap;
static spx_ahb_read_fn swrm_read;
static spx_ahb_write_fn swrm_write;

static int attempts = 64;
module_param(attempts, int, 0444);
MODULE_PARM_DESC(attempts, "Six-byte burst attempts (1..512)");

static void *resolve_symbol(const char *name)
{
	struct kprobe resolver = { .symbol_name = name };
	void *addr;
	int ret;

	ret = register_kprobe(&resolver);
	if (ret)
		return NULL;
	addr = resolver.addr;
	unregister_kprobe(&resolver);
	return addr;
}

static int master_read(int reg, u32 *val)
{
	int ret;

	ret = regmap_write(wcd_regmap, WCD_AHB_ACCESS_CFG,
			   WCD_AHB_READ_MODE);
	if (ret)
		return ret;
	return swrm_read(swrm_ctrl, reg, val);
}

static int master_write(int reg, u32 val)
{
	int ret;

	ret = regmap_write(wcd_regmap, WCD_AHB_ACCESS_CFG,
			   WCD_AHB_WRITE_MODE);
	if (ret)
		return ret;
	return swrm_write(swrm_ctrl, reg, val);
}

static int pre_command(u32 *last_comp)
{
	u32 cfg;
	u32 comp = 0;
	int outer;
	int inner;
	int ret;

	for (outer = 0; outer < 5; outer++) {
		ret = master_read(SWRM_MCP_CFG, &cfg);
		if (ret)
			return ret;
		if (cfg & SWRM_MCP_CFG_SYNC) {
			ret = master_write(SWRM_MCP_CFG,
					   cfg & ~SWRM_MCP_CFG_SYNC);
			if (ret)
				return ret;
		}
		for (inner = 0; inner < 5; inner++) {
			ret = master_read(SWRM_COMP_STATUS, &comp);
			if (ret)
				return ret;
			if (!(comp & SWRM_COMP_SYNC_MASK))
				goto out;
		}
	}
out:
	*last_comp = comp;
	return 0;
}

static int post_command(u32 *last_comp)
{
	u32 ignored;
	u32 cfg;
	u32 comp = 0;
	int outer;
	int inner;
	int ret;

	ret = master_read(SWRM_FIFO_STATUS, &ignored);
	if (ret)
		return ret;
	for (outer = 0; outer < 5; outer++) {
		ret = master_read(SWRM_MCP_CFG, &cfg);
		if (ret)
			return ret;
		ret = master_write(SWRM_MCP_CFG, cfg | SWRM_MCP_CFG_SYNC);
		if (ret)
			return ret;
		for (inner = 0; inner < 5; inner++) {
			ret = master_read(SWRM_COMP_STATUS, &comp);
			if (ret)
				return ret;
			if ((comp & SWRM_COMP_SYNC_MASK) ==
			    SWRM_COMP_SYNC_READY)
				goto out;
		}
	}
out:
	*last_comp = comp;
	return 0;
}

static int burst_read(u8 cmd_id, u8 *buf, u32 *status_out,
		      u32 *pre_comp, u32 *post_comp)
{
	u32 cmd;
	u32 status = 0;
	u32 data;
	unsigned int count;
	int poll;
	int byte;
	int ret;

	memset(buf, 0xaa, SDW_NUM_DEV_ID_REGISTERS);
	ret = pre_command(pre_comp);
	if (ret)
		return ret;

	cmd = ((u32)SDW_NUM_DEV_ID_REGISTERS << 24) |
	      ((u32)(cmd_id & 7) << 16) | SDW_SCP_DEVID_0;
	ret = master_write(SWRM_FIFO_RD_CMD, cmd);
	if (ret)
		goto post;

	/*
	 * Windows breaks on the first response because its generic operation is
	 * one byte.  This diagnostic requested six, so keep sampling until all
	 * six responses have arrived or the same 11-read bound expires.
	 */
	for (poll = 0; poll < 11; poll++) {
		ret = master_read(SWRM_FIFO_STATUS, &status);
		if (ret)
			goto post;
		if (FIELD_GET(SWRM_RD_COUNT_MASK, status) >=
		    SDW_NUM_DEV_ID_REGISTERS)
			break;
	}
	*status_out = status;
	count = FIELD_GET(SWRM_RD_COUNT_MASK, status);
	if (!count) {
		ret = -ETIMEDOUT;
		goto post;
	}

	/*
	 * A response FIFO word carries one byte and its command ID.  Drain up
	 * to the requested six entries so the next attempt starts cleanly.
	 */
	ret = 0;
	for (byte = 0;
	     byte < SDW_NUM_DEV_ID_REGISTERS && byte < count;
	     byte++) {
		ret = master_read(SWRM_FIFO_RD_DATA, &data);
		if (ret)
			break;
		buf[byte] = data & 0xff;
		if (((data >> 8) & 7) != (cmd_id & 7))
			ret = -EBADMSG;
	}
	if (!ret && count < SDW_NUM_DEV_ID_REGISTERS)
		ret = -ENODATA;
post:
	if (post_command(post_comp) && !ret)
		ret = -EIO;
	return ret;
}

static int __init spx_swrm_burst_read_init(void)
{
	struct sdw_bus *bus;
	struct spx_qcom_swrm_prefix *ctrl;
	u32 saved_mcp;
	u32 saved_enum;
	u32 saved_cpu_en;
	u32 status;
	u32 pre_comp;
	u32 post_comp;
	unsigned int saved_access;
	unsigned int counts[7] = { 0 };
	u8 buf[SDW_NUM_DEV_ID_REGISTERS];
	u8 cmd_id = 0;
	int try;
	int ret;

	if (attempts < 1 || attempts > 512)
		return -EINVAL;

	swrm_dev = bus_find_device_by_name(&platform_bus_type, NULL,
					   "wcd934x-soundwire.5.auto");
	if (!swrm_dev)
		return -ENODEV;
	swrm_ctrl = dev_get_drvdata(swrm_dev);
	wcd_regmap = dev_get_regmap(swrm_dev->parent, NULL);
	swrm_read = resolve_symbol("qcom_swrm_ahb_reg_read");
	swrm_write = resolve_symbol("qcom_swrm_ahb_reg_write");
	if (!swrm_ctrl || !wcd_regmap || !swrm_read || !swrm_write) {
		ret = -ENOENT;
		goto err_put;
	}
	bus = swrm_ctrl;
	ctrl = swrm_ctrl;

	ret = regmap_read(wcd_regmap, WCD_AHB_ACCESS_CFG, &saved_access);
	if (ret)
		goto err_put;
	mutex_lock(&bus->bus_lock);
	mutex_lock(&ctrl->controller_lock);
	ret = master_read(SWRM_INTERRUPT_CPU_EN, &saved_cpu_en);
	if (ret)
		goto out_unlock_controller;
	ret = master_write(SWRM_INTERRUPT_CPU_EN, 0);
	if (ret)
		goto out_unlock_controller;
	ret = master_read(SWRM_MCP_CFG, &saved_mcp);
	if (ret)
		goto out_restore_cpu;
	ret = master_read(SWRM_ENUM_CFG, &saved_enum);
	if (ret)
		goto out_restore_cfg;
	ret = master_write(SWRM_ENUM_CFG, 0);
	if (ret)
		goto out_restore_cfg;

	for (try = 0; try < attempts; try++) {
		unsigned int count;

		cmd_id = (cmd_id + 1) & 7;
		status = 0;
		pre_comp = 0;
		post_comp = 0;
		ret = burst_read(cmd_id, buf, &status, &pre_comp,
				 &post_comp);
		count = FIELD_GET(SWRM_RD_COUNT_MASK, status);
		if (count < ARRAY_SIZE(counts))
			counts[count]++;
		if (!ret || count) {
			pr_info("spxburst try=%d/%d ret=%d count=%u status=%#x pre=%#x post=%#x id=%02x:%02x:%02x:%02x:%02x:%02x\n",
				try + 1, attempts, ret, count, status,
				pre_comp, post_comp, buf[0], buf[1], buf[2],
				buf[3], buf[4], buf[5]);
		}
	}
	pr_info("spxburst summary attempts=%d count0=%u count1=%u count2=%u count3=%u count4=%u count5=%u count6=%u\n",
		attempts, counts[0], counts[1], counts[2], counts[3],
		counts[4], counts[5], counts[6]);
	ret = 0;

	master_write(SWRM_ENUM_CFG, saved_enum);
out_restore_cfg:
	master_write(SWRM_MCP_CFG, saved_mcp);
out_restore_cpu:
	master_write(SWRM_INTERRUPT_CPU_EN, saved_cpu_en);
out_unlock_controller:
	mutex_unlock(&ctrl->controller_lock);
	mutex_unlock(&bus->bus_lock);
	regmap_write(wcd_regmap, WCD_AHB_ACCESS_CFG, saved_access);
	if (ret)
		goto err_put;
	return 0;

err_put:
	put_device(swrm_dev);
	swrm_dev = NULL;
	return ret;
}

static void __exit spx_swrm_burst_read_exit(void)
{
	if (swrm_dev)
		put_device(swrm_dev);
	pr_info("spx_swrm_burst_read: unloaded\n");
}

module_init(spx_swrm_burst_read_init);
module_exit(spx_swrm_burst_read_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX reversible six-byte SoundWire Device-ID burst test");
