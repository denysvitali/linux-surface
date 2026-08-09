// SPDX-License-Identifier: GPL-2.0
/*
 * One-shot exact qcauddev8180-style device-0 DevID read diagnostic.
 * Uses the running driver's locked AHB bridge helpers and restores MCP_CFG.
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
#define WCD_GPIO_DIR		0x0042
#define WCD_GPIO_VAL		0x0043
#define WSA_GPIO_MASK		(BIT(1) | BIT(2))
#define SWRM_COMP_STATUS	0x0014
#define SWRM_INTERRUPT_CPU_EN	0x0210
#define SWRM_FIFO_WR_CMD	0x0300
#define SWRM_FIFO_RD_CMD	0x0304
#define SWRM_FIFO_STATUS	0x030c
#define SWRM_FIFO_RD_DATA	0x0318
#define SWRM_ENUM_CFG		0x0500
#define SWRM_FRAME_CTRL_B0	0x101c
#define SWRM_MCP_CFG		0x1048
#define SWRM_MCP_SLV_STATUS	0x1090
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
static u32 saved_mcp_cfg;
static unsigned int saved_access_cfg;
static bool have_saved_cfg;
static bool have_saved_access_cfg;
static unsigned int sample_counts[256];
static unsigned int devid_counts[SDW_NUM_DEV_ID_REGISTERS][256];

static int samples_per_byte = 50;
module_param(samples_per_byte, int, 0444);
MODULE_PARM_DESC(samples_per_byte,
		 "Exact Windows-style attempts for each DevID byte");

static int samples_per_phase = 8;
module_param(samples_per_phase, int, 0444);
MODULE_PARM_DESC(samples_per_phase,
		 "Device-0 DEVID_0 response attempts per PHASE setting");

static int samples_per_gpio = 32;
module_param(samples_per_gpio, int, 0444);
MODULE_PARM_DESC(samples_per_gpio,
		 "Device-0 DEVID_0 attempts per physical GPIO combination");

static bool do_gpio_sweep;
module_param(do_gpio_sweep, bool, 0444);
MODULE_PARM_DESC(do_gpio_sweep, "Exercise all four pin1/pin2 levels");

static bool do_phase_sweep;
module_param(do_phase_sweep, bool, 0444);
MODULE_PARM_DESC(do_phase_sweep, "Exercise all 32 FRAME_CTRL PHASE values");

static int assign_attempts;
module_param(assign_attempts, int, 0444);
MODULE_PARM_DESC(assign_attempts,
		 "Exact Windows-style SCP_DEVNUMBER writes before reads");

static int only_byte = -1;
module_param(only_byte, int, 0444);
MODULE_PARM_DESC(only_byte,
		 "Read only this Device-ID byte first (-1 reads 0..5)");

static void *resolve_symbol(const char *name)
{
	struct kprobe resolver = {
		.symbol_name = name,
	};
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
	u32 ignored;
	u32 cfg;
	u32 comp = 0;
	int outer;
	int inner;
	int ret;

	/* qcauddev8180 samples FIFO_STATUS before entering the set loop. */
	ret = master_read(SWRM_FIFO_STATUS, &ignored);
	if (ret)
		return ret;

	for (outer = 0; outer < 5; outer++) {
		ret = master_read(SWRM_MCP_CFG, &cfg);
		if (ret)
			return ret;
		ret = master_write(SWRM_MCP_CFG,
				   cfg | SWRM_MCP_CFG_SYNC);
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

static int windows_write_byte(u8 cmd_id, u8 dev, u16 reg, u8 value,
			      u32 *packed_cmd, u32 *pre_comp,
			      u32 *post_comp)
{
	u32 cmd;
	int ret;

	ret = windows_pre_command(pre_comp);
	if (ret)
		return ret;
	cmd = ((u32)value << 24) | ((u32)(dev & 0xf) << 20) |
	      ((u32)(cmd_id & 7) << 16) | reg;
	*packed_cmd = cmd;
	ret = master_write(SWRM_FIFO_WR_CMD, cmd);
	if (windows_post_command(post_comp) && !ret)
		ret = -EIO;
	return ret;
}

static int windows_read_byte(u8 cmd_id, u8 dev, u16 reg, u8 *value,
			     u32 *packed_cmd, u32 *fifo_status,
			     u32 *fifo_data, u32 *pre_comp, u32 *post_comp)
{
	u32 cmd;
	u32 status = 0;
	u32 data = 0;
	int poll;
	int ret;

	ret = windows_pre_command(pre_comp);
	if (ret)
		return ret;

	cmd = BIT(24) | ((u32)(dev & 0xf) << 20) |
	      ((u32)(cmd_id & 7) << 16) | reg;
	*packed_cmd = cmd;
	ret = master_write(SWRM_FIFO_RD_CMD, cmd);
	if (ret)
		goto post;

	for (poll = 0; poll < 11; poll++) {
		ret = master_read(SWRM_FIFO_STATUS, &status);
		if (ret)
			goto post;
		if (FIELD_GET(SWRM_RD_COUNT_MASK, status))
			break;
	}
	*fifo_status = status;
	if (!FIELD_GET(SWRM_RD_COUNT_MASK, status)) {
		ret = -ETIMEDOUT;
		goto post;
	}

	ret = master_read(SWRM_FIFO_RD_DATA, &data);
	*fifo_data = data;
	if (ret)
		goto post;
	*value = data & 0xff;
	if (((data >> 8) & 7) != (cmd_id & 7))
		ret = -EBADMSG;
post:
	if (windows_post_command(post_comp) && !ret)
		ret = -EIO;
	return ret;
}

static int __init spx_swrm_windows_read_init(void)
{
	struct sdw_bus *bus;
	struct spx_qcom_swrm_prefix *ctrl;
	u8 id[SDW_NUM_DEV_ID_REGISTERS] = { 0 };
	int results[SDW_NUM_DEV_ID_REGISTERS] = { 0 };
	u8 cmd_id = 0;
	u8 read_dev = 0;
	u32 assign_cmd = 0;
	u32 assign_pre = 0;
	u32 assign_post = 0;
	u32 slv = 0;
	u32 saved_cpu_en = 0;
	u32 saved_frame = 0;
	u32 saved_enum = 0;
	unsigned int best_phase_hits = 0;
	unsigned int best_phase_exact = 0;
	unsigned int saved_gpio_dir = 0;
	unsigned int saved_gpio_val = 0;
	int best_phase = 0;
	int gpio_state;
	int phase;
	int assign_ret;
	int assign_try;
	int poll;
	int byte;
	int sample;
	int ret;

	if (samples_per_byte < 1 || samples_per_byte > 500 ||
	    samples_per_phase < 1 || samples_per_phase > 50 ||
	    samples_per_gpio < 1 || samples_per_gpio > 100 ||
	    assign_attempts < 0 || assign_attempts > 256 ||
	    only_byte < -1 || only_byte >= SDW_NUM_DEV_ID_REGISTERS)
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
	bus = (struct sdw_bus *)swrm_ctrl;
	ctrl = swrm_ctrl;

	ret = regmap_read(wcd_regmap, WCD_AHB_ACCESS_CFG,
			  &saved_access_cfg);
	if (ret)
		goto err_put;
	have_saved_access_cfg = true;
	ret = master_read(SWRM_MCP_CFG, &saved_mcp_cfg);
	if (ret)
		goto err_put;
	have_saved_cfg = true;

	mutex_lock(&bus->bus_lock);
	mutex_lock(&ctrl->controller_lock);
	master_read(SWRM_INTERRUPT_CPU_EN, &saved_cpu_en);
	master_write(SWRM_INTERRUPT_CPU_EN, 0);
	master_read(SWRM_FRAME_CTRL_B0, &saved_frame);
	master_read(SWRM_ENUM_CFG, &saved_enum);
	master_write(SWRM_ENUM_CFG, 0);
	regmap_read(wcd_regmap, WCD_GPIO_DIR, &saved_gpio_dir);
	regmap_read(wcd_regmap, WCD_GPIO_VAL, &saved_gpio_val);
	for (gpio_state = 0; do_gpio_sweep && gpio_state < 4; gpio_state++) {
		unsigned int successes = 0;
		unsigned int best_count = 0;
		unsigned int best_value = 0;
		unsigned int physical = (u32)gpio_state << 1;
		int value;

		regmap_update_bits(wcd_regmap, WCD_GPIO_VAL,
				   WSA_GPIO_MASK, physical);
		regmap_update_bits(wcd_regmap, WCD_GPIO_DIR,
				   WSA_GPIO_MASK, WSA_GPIO_MASK);
		msleep(20);
		memset(sample_counts, 0, sizeof(sample_counts));
		for (sample = 0; sample < samples_per_gpio; sample++) {
			u32 cmd = 0;
			u32 status = 0;
			u32 data = 0;
			u32 pre_comp = 0;
			u32 post_comp = 0;
			u8 sample_value = 0;

			cmd_id = (cmd_id + 1) & 7;
			if (!windows_read_byte(
				    cmd_id, 0, SDW_SCP_DEVID_0,
				    &sample_value, &cmd, &status, &data,
				    &pre_comp, &post_comp)) {
				sample_counts[sample_value]++;
				successes++;
			}
		}
		for (value = 0; value < ARRAY_SIZE(sample_counts); value++) {
			if (sample_counts[value] > best_count) {
				best_count = sample_counts[value];
				best_value = value;
			}
		}
		pr_info("spxwingpio physical=%#x success=%u/%d mode=%#x count=%u\n",
			physical, successes, samples_per_gpio,
			best_value, best_count);
	}
	regmap_update_bits(wcd_regmap, WCD_GPIO_VAL,
			   WSA_GPIO_MASK, saved_gpio_val & WSA_GPIO_MASK);
	regmap_update_bits(wcd_regmap, WCD_GPIO_DIR,
			   WSA_GPIO_MASK, saved_gpio_dir & WSA_GPIO_MASK);
	pr_info("spxwingpio restored dir=%#x val=%#x\n",
		saved_gpio_dir, saved_gpio_val);

	for (phase = 0; do_phase_sweep && phase < 32; phase++) {
		unsigned int phase_hits = 0;
		unsigned int phase_exact = 0;

		master_write(SWRM_FRAME_CTRL_B0,
			     0x10000 | ((u32)phase << 11));
		for (sample = 0; sample < samples_per_phase; sample++) {
			u32 cmd = 0;
			u32 status = 0;
			u32 data = 0;
			u32 pre_comp = 0;
			u32 post_comp = 0;
			u8 sample_value = 0;

			cmd_id = (cmd_id + 1) & 7;
			if (!windows_read_byte(
				    cmd_id, 0, SDW_SCP_DEVID_0,
				    &sample_value, &cmd, &status, &data,
				    &pre_comp, &post_comp)) {
				phase_hits++;
				if (sample_value == 0x11)
					phase_exact++;
			}
		}
		pr_info("spxwinphase phase=%d hits=%u/%d exact11=%u\n",
			phase, phase_hits, samples_per_phase, phase_exact);
		if (phase_exact > best_phase_exact ||
		    (phase_exact == best_phase_exact &&
		     phase_hits > best_phase_hits)) {
			best_phase_exact = phase_exact;
			best_phase_hits = phase_hits;
			best_phase = phase;
		}
	}
	if (do_phase_sweep) {
		master_write(SWRM_FRAME_CTRL_B0,
			     0x10000 | ((u32)best_phase << 11));
		pr_info("spxwinphase best=%d hits=%u/%d exact11=%u\n",
			best_phase, best_phase_hits, samples_per_phase,
			best_phase_exact);
	}

	assign_ret = 0;
	for (assign_try = 0; assign_try < assign_attempts; assign_try++) {
		cmd_id = (cmd_id + 1) & 7;
		assign_ret = windows_write_byte(
			cmd_id, 0, SDW_SCP_DEVNUMBER, 1,
			&assign_cmd, &assign_pre, &assign_post);
		master_read(SWRM_MCP_SLV_STATUS, &slv);
		if (((slv >> 2) & 3) != 0) {
			read_dev = 1;
			break;
		}
	}
	for (poll = 0; poll < 100; poll++) {
		master_read(SWRM_MCP_SLV_STATUS, &slv);
		if (((slv >> 2) & 3) != 0) {
			read_dev = 1;
			break;
		}
		usleep_range(500, 510);
	}
	pr_info("spxwinwr assign attempts=%d/%d cmd=%#010x pre=%#x post=%#x ret=%d slv=%#x read_dev=%u\n",
		assign_try < assign_attempts ? assign_try + 1 :
					      assign_attempts,
		assign_attempts,
		assign_cmd, assign_pre, assign_post,
		assign_ret, slv, read_dev);
	memset(devid_counts, 0, sizeof(devid_counts));
	for (sample = 0; sample < samples_per_byte; sample++) {
		for (byte = 0; byte < SDW_NUM_DEV_ID_REGISTERS; byte++) {
			u32 cmd = 0;
			u32 status = 0;
			u32 data = 0;
			u32 pre_comp = 0;
			u32 post_comp = 0;
			u8 sample_value = 0;
			int sample_ret;

			if (only_byte >= 0 && byte != only_byte)
				continue;
			cmd_id = (cmd_id + 1) & 7;
			sample_ret = windows_read_byte(
				cmd_id, read_dev, SDW_SCP_DEVID_0 + byte,
				&sample_value, &cmd, &status, &data,
				&pre_comp, &post_comp);
			if (!sample_ret) {
				devid_counts[byte][sample_value]++;
				results[byte]++;
				if (results[byte] <= 20)
					pr_info("spxwinrd hit try=%d byte=%d val=%#x cmd=%#x status=%#x data=%#x\n",
						sample + 1, byte,
						sample_value, cmd, status,
						data);
			}
		}
	}
	for (byte = 0; byte < SDW_NUM_DEV_ID_REGISTERS; byte++) {
		unsigned int best_count = 0;
		unsigned int best_value = 0;
		int value;

		for (value = 0; value < 256; value++) {
			if (devid_counts[byte][value] > best_count) {
				best_count = devid_counts[byte][value];
				best_value = value;
			}
		}
		id[byte] = best_value;
		pr_info("spxwinrd summary byte=%d reg=%#x success=%d/%d mode=%#x count=%u\n",
			byte, SDW_SCP_DEVID_0 + byte, results[byte],
			samples_per_byte, best_value, best_count);
	}
	master_write(SWRM_ENUM_CFG, 0);
	master_write(SWRM_FRAME_CTRL_B0, saved_frame);
	master_write(SWRM_ENUM_CFG, saved_enum);
	mutex_unlock(&bus->bus_lock);

	master_write(SWRM_MCP_CFG, saved_mcp_cfg);
	have_saved_cfg = false;
	master_write(SWRM_INTERRUPT_CPU_EN, saved_cpu_en);
	mutex_unlock(&ctrl->controller_lock);
	regmap_write(wcd_regmap, WCD_AHB_ACCESS_CFG, saved_access_cfg);
	have_saved_access_cfg = false;
	pr_info("spxwinrd modal_id=%02x:%02x:%02x:%02x:%02x:%02x successes=%d,%d,%d,%d,%d,%d restored_cfg=%#x c95=%#x\n",
		id[0], id[1], id[2], id[3], id[4], id[5],
		results[0], results[1], results[2], results[3],
		results[4], results[5], saved_mcp_cfg, saved_access_cfg);
	return 0;

err_put:
	put_device(swrm_dev);
	swrm_dev = NULL;
	return ret;
}

static void __exit spx_swrm_windows_read_exit(void)
{
	if (have_saved_cfg)
		master_write(SWRM_MCP_CFG, saved_mcp_cfg);
	if (have_saved_access_cfg)
		regmap_write(wcd_regmap, WCD_AHB_ACCESS_CFG,
			     saved_access_cfg);
	if (swrm_dev)
		put_device(swrm_dev);
	pr_info("spx_swrm_windows_read: unloaded\n");
}

module_init(spx_swrm_windows_read_init);
module_exit(spx_swrm_windows_read_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX exact Windows-style one-shot SoundWire DevID read");
