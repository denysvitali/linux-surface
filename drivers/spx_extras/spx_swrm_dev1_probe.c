// SPDX-License-Identifier: GPL-2.0
/*
 * One-shot, reversible probe of the SoundWire device-1 command slot.
 *
 * This deliberately leaves enumeration and GPIO state alone.  It uses the
 * running qcom master's locked AHB helpers, serializes against normal SoundWire
 * transfers with bus_lock, and restores MCP_CFG and the WCD AHB access mode.
 */
#include <linux/device.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/soundwire/sdw.h>
#include <linux/soundwire/sdw_registers.h>

#define WCD_AHB_ACCESS_CFG		0x0c95
#define WCD_AHB_WRITE_MODE		0x03
#define WCD_AHB_READ_MODE		0x0c

#define SWRM_COMP_STATUS		0x0014
#define SWRM_FIFO_RD_CMD		0x0304
#define SWRM_FIFO_STATUS		0x030c
#define SWRM_FIFO_RD_DATA		0x0318
#define SWRM_ENUMERATOR_ID1(dev)	(0x0530 + 8 * (dev))
#define SWRM_ENUMERATOR_ID2(dev)	(0x0534 + 8 * (dev))
#define SWRM_MCP_CFG			0x1048
#define SWRM_MCP_SLV_STATUS		0x1090

#define SWRM_MCP_CFG_SYNC		BIT(1)
#define SWRM_COMP_SYNC_MASK		GENMASK(5, 4)
#define SWRM_COMP_SYNC_READY		(2U << 4)
#define SWRM_RD_COUNT_MASK		GENMASK(20, 16)
#define SPX_MAX_READ_LEN		6

typedef int (*spx_ahb_read_fn)(void *ctrl, int reg, u32 *val);
typedef int (*spx_ahb_write_fn)(void *ctrl, int reg, int val);

struct spx_read_result {
	u32 cmd;
	u32 fifo_before;
	u32 fifo_ready;
	u32 fifo_after;
	u32 pre_comp;
	u32 post_comp;
	u32 data[SPX_MAX_READ_LEN];
	u8 count;
	u8 words;
	u8 polls;
};

static struct device *swrm_dev;
static void *swrm_ctrl;
static struct regmap *wcd_regmap;
static spx_ahb_read_fn swrm_read;
static spx_ahb_write_fn swrm_write;

static int rounds = 8;
module_param(rounds, int, 0444);
MODULE_PARM_DESC(rounds, "Probe rounds (1..32)");

static int slot_samples = 300;
module_param(slot_samples, int, 0444);
MODULE_PARM_DESC(slot_samples,
		 "Immediate slot-1 samples before each command round (1..2000)");

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

static int windows_pre_command(u32 *last_comp)
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

static int windows_post_command(u32 *last_comp)
{
	u32 fifo;
	u32 cfg;
	u32 comp = 0;
	int outer;
	int inner;
	int ret;

	ret = master_read(SWRM_FIFO_STATUS, &fifo);
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

static int dev1_read(u8 cmd_id, u16 reg, u8 len,
		     struct spx_read_result *result)
{
	u32 status = 0;
	unsigned int count;
	int poll;
	int ret;
	int post_ret;
	int word;

	memset(result, 0, sizeof(*result));
	ret = master_read(SWRM_FIFO_STATUS, &result->fifo_before);
	if (ret)
		return ret;
	ret = windows_pre_command(&result->pre_comp);
	if (ret)
		return ret;

	result->cmd = ((u32)len << 24) | BIT(20) |
		      ((u32)(cmd_id & 7) << 16) | reg;
	ret = master_write(SWRM_FIFO_RD_CMD, result->cmd);
	if (ret)
		goto post;

	for (poll = 0; poll < 11; poll++) {
		ret = master_read(SWRM_FIFO_STATUS, &status);
		if (ret)
			goto post;
		result->polls = poll + 1;
		if (FIELD_GET(SWRM_RD_COUNT_MASK, status))
			break;
	}
	result->fifo_ready = status;
	count = FIELD_GET(SWRM_RD_COUNT_MASK, status);
	result->count = min_t(unsigned int, count, U8_MAX);
	if (!count) {
		ret = -ETIMEDOUT;
		goto post;
	}

	for (word = 0; word < len && word < count; word++) {
		ret = master_read(SWRM_FIFO_RD_DATA, &result->data[word]);
		if (ret)
			goto post;
		result->words++;
	}
	if (result->words < len)
		ret = -ENODATA;
	for (word = 0; word < result->words; word++) {
		if (((result->data[word] >> 8) & 7) != (cmd_id & 7)) {
			ret = -EBADMSG;
			break;
		}
	}

post:
	post_ret = windows_post_command(&result->post_comp);
	if (!ret && post_ret)
		ret = post_ret;
	if (master_read(SWRM_FIFO_STATUS, &result->fifo_after) && !ret)
		ret = -EIO;
	return ret;
}

static void log_result(int round, const char *kind, u8 cmd_id, u16 reg,
		       u8 len, int ret, const struct spx_read_result *result)
{
	int word;

	pr_info("spxdev1 round=%d kind=%s id=%u reg=%#x len=%u ret=%d cmd=%#010x fifo=%#x/%#x/%#x count=%u words=%u polls=%u comp=%#x/%#x\n",
		round, kind, cmd_id, reg, len, ret, result->cmd,
		result->fifo_before, result->fifo_ready, result->fifo_after,
		result->count, result->words, result->polls,
		result->pre_comp, result->post_comp);
	for (word = 0; word < result->words; word++)
		pr_info("spxdev1data round=%d kind=%s id=%u word=%d raw=%#010x byte=%#x response_id=%u\n",
			round, kind, cmd_id, word, result->data[word],
			result->data[word] & 0xff,
			(result->data[word] >> 8) & 7);
}

static int __init spx_swrm_dev1_probe_init(void)
{
	struct spx_read_result result;
	struct sdw_bus *bus;
	unsigned int saved_access;
	u32 saved_mcp = 0;
	u32 slave;
	u32 id1;
	u32 id2;
	u8 cmd_id = 0;
	bool have_mcp = false;
	int round;
	int sample;
	int byte;
	int ret;

	if (rounds < 1 || rounds > 32 ||
	    slot_samples < 1 || slot_samples > 2000)
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

	ret = regmap_read(wcd_regmap, WCD_AHB_ACCESS_CFG, &saved_access);
	if (ret)
		goto err_put;
	mutex_lock(&bus->bus_lock);
	ret = master_read(SWRM_MCP_CFG, &saved_mcp);
	if (ret)
		goto out_unlock;
	have_mcp = true;

	for (round = 1; round <= rounds; round++) {
		for (sample = 1; sample <= slot_samples; sample++) {
			id1 = 0;
			id2 = 0;
			ret = master_read(SWRM_ENUMERATOR_ID1(1), &id1);
			if (ret)
				break;
			ret = master_read(SWRM_ENUMERATOR_ID2(1), &id2);
			if (ret || id1 || id2)
				break;
		}
		slave = 0;
		master_read(SWRM_MCP_SLV_STATUS, &slave);
		pr_info("spxdev1slot round=%d sample=%d/%d ret=%d slave=%#x id1=%#x id2=%#x\n",
			round, min(sample, slot_samples), slot_samples, ret,
			slave, id1, id2);
		if (ret || (!id1 && !id2))
			break;

		cmd_id = (cmd_id + 1) & 7;
		ret = dev1_read(cmd_id, SDW_SCP_DEVID_0, 1, &result);
		log_result(round, "single0", cmd_id, SDW_SCP_DEVID_0, 1,
			   ret, &result);

		cmd_id = (cmd_id + 1) & 7;
		ret = dev1_read(cmd_id, SDW_SCP_DEVID_0,
				SDW_NUM_DEV_ID_REGISTERS, &result);
		log_result(round, "burst6", cmd_id, SDW_SCP_DEVID_0,
			   SDW_NUM_DEV_ID_REGISTERS, ret, &result);

		for (byte = 0; byte < SDW_NUM_DEV_ID_REGISTERS; byte++) {
			cmd_id = (cmd_id + 1) & 7;
			ret = dev1_read(cmd_id, SDW_SCP_DEVID_0 + byte, 1,
					&result);
			log_result(round, "split", cmd_id,
				   SDW_SCP_DEVID_0 + byte, 1, ret, &result);
		}
	}
	ret = 0;

	if (have_mcp)
		master_write(SWRM_MCP_CFG, saved_mcp);
out_unlock:
	mutex_unlock(&bus->bus_lock);
	regmap_write(wcd_regmap, WCD_AHB_ACCESS_CFG, saved_access);
	if (ret)
		goto err_put;
	pr_info("spx_swrm_dev1_probe: complete; rounds=%d restored_mcp=%#x access=%#x\n",
		rounds, saved_mcp, saved_access);
	return 0;

err_put:
	put_device(swrm_dev);
	swrm_dev = NULL;
	return ret;
}

static void __exit spx_swrm_dev1_probe_exit(void)
{
	if (swrm_dev)
		put_device(swrm_dev);
	pr_info("spx_swrm_dev1_probe: unloaded\n");
}

module_init(spx_swrm_dev1_probe_init);
module_exit(spx_swrm_dev1_probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX reversible Windows-style SoundWire dev1 command probe");
