// SPDX-License-Identifier: GPL-2.0
/*
 * Reversible capture of the hardware auto-enumerator path used by Windows.
 * No SoundWire FIFO commands are issued.
 */
#include <linux/completion.h>
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/soundwire/sdw.h>

struct dentry;
struct clk;

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
	struct mutex port_lock;
	struct clk *hclk;
	int irq;
	unsigned int version;
	int wake_irq;
	int num_din_ports;
	int num_dout_ports;
	int cols_index;
	int rows_index;
	unsigned long port_mask;
	u32 intr_mask;
};

#define WCD_AHB_ACCESS_CFG	0x0c95
#define WCD_AHB_WRITE_MODE	0x03
#define WCD_AHB_READ_MODE	0x0c
#define WCD_GPIO_DIR		0x0042
#define WCD_GPIO_VAL		0x0043
#define WSA_GPIO_MASK		(BIT(1) | BIT(2))

#define SWRM_INTERRUPT_STATUS	0x0200
#define SWRM_INTERRUPT_CLEAR	0x0208
#define SWRM_INTERRUPT_CPU_EN	0x0210
#define SWRM_INTERRUPT_STATUS_SPECIAL_CMD_ID_FINISHED	BIT(10)
#define SWRM_COMP_CFG		0x0004
#define SWRM_COMP_SW_RESET	0x0008
#define SWRM_COMP_STATUS	0x0014
#define SWRM_COMP_PARAMS	0x0100
#define SWRM_LINK_MANAGER_EE	0x0018
#define SWRM_ENUM_CFG		0x0500
#define SWRM_INTERRUPT_MASK	0x0204
#define SWRM_CMD_FIFO_CFG	0x0314
#define SWRM_FRAME_CTRL_B0	0x101c
#define SWRM_FRAME_CTRL_B1	0x105c
#define SWRM_ENUM_ID1(dev)	(0x0530 + 8 * (dev))
#define SWRM_ENUM_ID2(dev)	(0x0534 + 8 * (dev))
#define SWRM_MCP_SLV_STATUS	0x1090
#define SWRM_MCP_BUS_CTRL	0x1044
#define SWRM_MCP_CFG		0x1048
#define SWRM_NO_PINGS_MASK	GENMASK(21, 17)

typedef int (*spx_ahb_read_fn)(void *ctrl, int reg, u32 *val);
typedef int (*spx_ahb_write_fn)(void *ctrl, int reg, int val);

static struct device *swrm_dev;
static void *swrm_ctrl;
static struct regmap *wcd_regmap;
static spx_ahb_read_fn swrm_read;
static spx_ahb_write_fn swrm_write;

struct spx_held_state {
	bool active;
	unsigned int access;
	unsigned int dir;
	unsigned int val;
	u32 cpu_en;
	u32 enum_cfg;
	u32 comp_cfg;
	u32 mcp_cfg;
	u32 link_ee;
	u32 irq_mask;
	u32 fifo_cfg;
	u32 frame_b0;
	u32 frame_b1;
	u32 intr_mask_soft;
};

static struct spx_held_state held;
static bool frame_guard_registered;

static int active_pin = 1;
module_param(active_pin, int, 0444);
MODULE_PARM_DESC(active_pin, "One WSA SD_N pin to wake (1 or 2)");

static int snapshots = 300;
module_param(snapshots, int, 0444);
MODULE_PARM_DESC(snapshots, "Tight hardware-table snapshots (1..2000)");

static bool enum_before_wake;
module_param(enum_before_wake, bool, 0444);
MODULE_PARM_DESC(enum_before_wake,
		 "Enable hardware auto-enum before releasing the WSA SD_N pin");

static bool clash_workaround;
module_param(clash_workaround, bool, 0444);
MODULE_PARM_DESC(clash_workaround,
		 "Apply Qualcomm's documented stale-clash COMP_CFG sequence");

static int no_pings = -1;
module_param(no_pings, int, 0444);
MODULE_PARM_DESC(no_pings,
		 "Override MCP_CFG no-pings field (-1 preserves, 0..31 sets)");

static bool claim_cpu_ee;
module_param(claim_cpu_ee, bool, 0444);
MODULE_PARM_DESC(claim_cpu_ee,
		 "Claim link-manager EE1 and start its per-EE bus clock");

static bool full_vendor_reinit;
module_param(full_vendor_reinit, bool, 0444);
MODULE_PARM_DESC(full_vendor_reinit,
		 "Run locked Qualcomm v1.x duplicate-reset recovery/init");

static int clock_div = -1;
module_param(clock_div, int, 0444);
MODULE_PARM_DESC(clock_div,
		 "Override FRAME_CTRL bits 10:8 (-1 preserves, 0..7 sets)");

static bool dual_enum;
module_param(dual_enum, bool, 0444);
MODULE_PARM_DESC(dual_enum,
		 "After dev1 ID capture, wake the other WSA and capture dev2");

static int settle_div = -1;
module_param(settle_div, int, 0444);
MODULE_PARM_DESC(settle_div,
		 "Switch FRAME_CTRL divider after dev1 ID capture (-1 preserves)");

static int dual_settle_div = -1;
module_param(dual_settle_div, int, 0444);
MODULE_PARM_DESC(dual_settle_div,
		 "Switch FRAME_CTRL divider after dev2 ID capture (-1 preserves)");

static bool keep_live;
module_param(keep_live, bool, 0444);
MODULE_PARM_DESC(keep_live,
		 "Keep successful dual enumeration live until module unload");

static bool runtime_handoff;
module_param(runtime_handoff, bool, 0444);
MODULE_PARM_DESC(runtime_handoff,
		 "Stop auto-enum and hold both banks at Windows runtime 0x10100");

static int guard_windows_frame(struct kprobe *probe, struct pt_regs *regs)
{
	u32 reg = (u32)regs->regs[1];

	if (held.active &&
	    (reg == SWRM_FRAME_CTRL_B0 || reg == SWRM_FRAME_CTRL_B1))
		regs->regs[2] = BIT(16) | BIT(8);
	return 0;
}

static struct kprobe frame_guard_probe = {
	.symbol_name = "qcom_swrm_ahb_reg_write",
	.pre_handler = guard_windows_frame,
};

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

/*
 * The qcom driver's own AHB bridge path (qcom_swrm_ahb_reg_read) stops working
 * partway through a session -- it polls ACCESS_STATUS for the RD_DONE edge
 * (bit 1), which on this silicon never arrives once the bus has clashed, so it
 * returns SDW_CMD_FAIL(2) forever and this module used to bail before printing
 * anything. spx_swrm_regs.ko drives the very same bridge registers and keeps
 * working, because it (a) settles 500us after submitting RD_ADDR, (b) polls the
 * level-high bit 0 rather than the RD_DONE edge, and (c) throws the first
 * RD_DATA sample away. Reproduce that discipline here so enumeration survives
 * a degraded bridge.
 */
#define BR_WR_DATA	0x0c85
#define BR_RD_ADDR	0x0c8d
#define BR_RD_DATA	0x0c91
#define BR_STATUS	0x0c96

/*
 * Which SoundWire device number the static DT slave is mapped onto.
 *
 * Mapping to 1 looked right, but MCP_SLV_STATUS reads 0x1 mid-stream -- the amp
 * actually answers at device *0*, its stable unenumerated address. Everything
 * addressed to device 1 is therefore dropped, silently, because unicast writes
 * always report success on this master. soundwire_qcom.spx_write_dev0 only
 * redirects the wsa881x driver's own register writes; the SoundWire core
 * programs the slave's DPn transport registers using slave->dev_num, so the
 * port configuration kept going to device 1 while the analog bring-up was
 * mirrored to device 0. Setting this to 0 puts *everything* on device 0.
 */
static bool handoff_codecs = true;
module_param(handoff_codecs, bool, 0444);
MODULE_PARM_DESC(handoff_codecs, "Hand enumerated addresses to codecs (disable for retained-PCM diagnostics)");

static int map_devnum = 1;
module_param(map_devnum, int, 0444);
MODULE_PARM_DESC(map_devnum,
		 "device number to map the static DT slave onto (0 = the amp's stable address)");

static bool paged_bridge = true;
module_param(paged_bridge, bool, 0444);
MODULE_PARM_DESC(paged_bridge,
		 "use the spx_swrm_regs paged bridge instead of the qcom AHB path");

static int paged_read(int reg, u32 *val)
{
	u32 addr = reg, first = 0, v = 0;
	int i, ret;

	ret = regmap_bulk_write(wcd_regmap, BR_RD_ADDR, (u8 *)&addr, 4);
	if (ret)
		return ret;
	usleep_range(500, 550);
	for (i = 0; i < 200; i++) {
		u32 st;

		if (!regmap_read(wcd_regmap, BR_STATUS, &st) && (st & 1))
			break;
		udelay(5);
	}
	ret = regmap_bulk_read(wcd_regmap, BR_RD_DATA, &first, 4);
	if (ret)
		return ret;
	usleep_range(500, 550);
	ret = regmap_bulk_read(wcd_regmap, BR_RD_DATA, &v, 4);
	if (ret)
		return ret;
	*val = v;
	return 0;
}

static int paged_write(int reg, u32 val)
{
	u32 request[2] = { val, reg };
	int ret;

	/* WR_DATA and WR_ADDR as one contiguous eight-byte transaction. */
	ret = regmap_bulk_write(wcd_regmap, BR_WR_DATA, (u8 *)request,
				sizeof(request));
	usleep_range(500, 550);
	return ret;
}

static int master_read(int reg, u32 *val)
{
	int ret;

	if (paged_bridge)
		return paged_read(reg, val);

	ret = regmap_write(wcd_regmap, WCD_AHB_ACCESS_CFG,
			   WCD_AHB_READ_MODE);
	if (ret)
		return ret;
	return swrm_read(swrm_ctrl, reg, val);
}

static int master_write(int reg, u32 val)
{
	int ret;

	if (paged_bridge)
		return paged_write(reg, val);

	ret = regmap_write(wcd_regmap, WCD_AHB_ACCESS_CFG,
			   WCD_AHB_WRITE_MODE);
	if (ret)
		return ret;
	return swrm_write(swrm_ctrl, reg, val);
}

/*
 * After COMP_SW_RESET the bridge can return one constant for *every* address
 * (observed: 0x36000d0c for INTERRUPT_STATUS, MCP_SLV_STATUS and both ENUM_ID
 * pairs at once). Those values look like plausible register contents and have
 * already been mistaken for a stable enumeration. COMP_PARAMS is a read-only
 * hardware constant on this master, so use it as a canary before trusting
 * anything -- including before accepting keep_live.
 */
#define SWRM_COMP_PARAMS_EXPECTED	0x016840c6

static bool bridge_sane(void)
{
	u32 params = 0;

	if (master_read(SWRM_COMP_PARAMS, &params) || params != SWRM_COMP_PARAMS_EXPECTED) {
		pr_err("spxautocap: bridge insane, COMP_PARAMS=%#x (expected %#x) -- reads untrustworthy\n",
		       params, SWRM_COMP_PARAMS_EXPECTED);
		return false;
	}
	return true;
}


static void map_surface_codecs_live(struct sdw_bus *bus)
{
	enum sdw_slave_status status[SDW_MAX_DEVICES + 1] = { 0 };
	struct sdw_slave *slave;
	unsigned int mapped = 0;
	int ret;

	mutex_lock(&bus->bus_lock);
	list_for_each_entry(slave, &bus->slaves, node) {
		int devnum;

		if (slave->id.mfg_id != 0x0217 ||
		    slave->id.part_id != 0x2010)
			continue;
		if (slave->id.unique_id == 1)
			devnum = 1;
		else if (slave->id.unique_id == 2 && dual_enum)
			devnum = 2;
		else
			continue;
		slave->dev_num = devnum;
		slave->prop.quirks |=
			SDW_SLAVE_QUIRKS_WRITE_ONLY_PORTCTRL;
		set_bit(devnum, bus->assigned);
		mapped++;
		pr_info("spxautocap: live-mapped %s to hardware dev%d\n",
			dev_name(&slave->dev), devnum);
	}
	mutex_unlock(&bus->bus_lock);

	if (mapped != (dual_enum ? 2u : 1u)) {
		pr_err("spxautocap: expected %u Surface DTS codec(s), mapped %u\n",
		       dual_enum ? 2u : 1u, mapped);
		return;
	}
	status[1] = SDW_SLAVE_ATTACHED;
	if (dual_enum)
		status[2] = SDW_SLAVE_ATTACHED;
	ret = sdw_handle_slave_status(bus, status);
	if (ret) {
		pr_err("spxautocap: live codec status handoff failed: %d\n", ret);
		return;
	}
	pr_info("spxautocap: %u Surface codec(s) handed to SoundWire core\n",
		mapped);

	/*
	 * Re-address to the amp's real device number *after* the handoff.
	 * status[0]=ATTACHED cannot be announced directly: the core would call
	 * sdw_program_device_num() and try to enumerate over a read path that
	 * does not work here. So hand off as device 1 (the core marks the slave
	 * attached and probes it), then rewrite dev_num, which is what both the
	 * core's DPn transport programming and the codec driver address.
	 */
	if (map_devnum != 1) {
		mutex_lock(&bus->bus_lock);
		list_for_each_entry(slave, &bus->slaves, node) {
			if (slave->id.mfg_id != 0x0217 ||
			    slave->id.part_id != 0x2010)
				continue;
			if (slave->id.unique_id == 1)
				slave->dev_num = map_devnum;
			else if (slave->id.unique_id == 2 && dual_enum)
				slave->dev_num = map_devnum + 1;
			else
				continue;
			pr_info("spxautocap: re-addressed %s to dev%d\n",
				dev_name(&slave->dev), slave->dev_num);
		}
		mutex_unlock(&bus->bus_lock);
	}
}

static int __init spx_swrm_autoenum_capture_init(void)
{
	struct spx_qcom_swrm_prefix *ctrl;
	struct sdw_bus *bus;
	unsigned int saved_access;
	unsigned int saved_dir;
	unsigned int saved_val;
	u32 saved_cpu_en;
	u32 saved_enum;
	u32 saved_comp_cfg;
	u32 saved_mcp_cfg;
	u32 saved_link_ee;
	u32 saved_bus_ctrl;
	u32 saved_irq_mask;
	u32 saved_fifo_cfg;
	u32 saved_frame;
	u32 saved_frame_b1;
	u32 comp_before = 0;
	u32 comp_after = 0;
	u32 irq = 0;
	u32 slv = 0;
	u32 id11 = 0;
	u32 id12 = 0;
	u32 id21 = 0;
	u32 id22 = 0;
	u32 prev_irq = ~0U;
	u32 prev_slv = ~0U;
	u32 prev_id11 = ~0U;
	u32 prev_id12 = ~0U;
	u32 prev_id21 = ~0U;
	u32 prev_id22 = ~0U;
	unsigned int changes = 0;
	unsigned int dev1_stable = 0;
	bool second_woken = false;
	bool divider_settled = false;
	bool dual_divider_settled = false;
	bool runtime_ready = false;
	unsigned int dual_stable = 0;
	int sample;
	int ret;

	if ((active_pin != 1 && active_pin != 2) ||
	    no_pings < -1 || no_pings > 31 ||
	    clock_div < -1 || clock_div > 7 ||
	    settle_div < -1 || settle_div > 7 ||
	    dual_settle_div < -1 || dual_settle_div > 7 ||
	    snapshots < 1 || snapshots > 2000)
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
	ret = regmap_read(wcd_regmap, WCD_GPIO_DIR, &saved_dir);
	if (ret)
		goto err_put;
	ret = regmap_read(wcd_regmap, WCD_GPIO_VAL, &saved_val);
	if (ret)
		goto err_put;

	mutex_lock(&bus->bus_lock);
	mutex_lock(&ctrl->controller_lock);

	/*
	 * Validate the bridge BEFORE snapshotting the controller state. A
	 * garbage snapshot is worse than no snapshot: the restore path writes it
	 * back on exit, which is how MCP_CFG was once left at 0x00000000. The
	 * bridge needs a moment to settle after the qcom read path has been
	 * hammered (force_attach/reenum), so retry rather than fail outright.
	 */
	for (ret = 0; ret < 10 && !bridge_sane(); ret++)
		msleep(200);
	if (ret == 10) {
		ret = -EIO;
		goto out_unlock;
	}

	ret = master_read(SWRM_INTERRUPT_CPU_EN, &saved_cpu_en);
	if (ret)
		goto out_unlock;
	ret = master_read(SWRM_ENUM_CFG, &saved_enum);
	if (ret)
		goto out_unlock;
	ret = master_read(SWRM_COMP_CFG, &saved_comp_cfg);
	if (ret)
		goto out_unlock;
	ret = master_read(SWRM_MCP_CFG, &saved_mcp_cfg);
	if (ret)
		goto out_unlock;
	ret = master_read(SWRM_LINK_MANAGER_EE, &saved_link_ee);
	if (ret)
		goto out_unlock;
	ret = master_read(SWRM_MCP_BUS_CTRL, &saved_bus_ctrl);
	if (ret)
		goto out_unlock;
	ret = master_read(SWRM_INTERRUPT_MASK, &saved_irq_mask);
	if (ret)
		goto out_unlock;
	ret = master_read(SWRM_CMD_FIFO_CFG, &saved_fifo_cfg);
	if (ret)
		goto out_unlock;
	ret = master_read(SWRM_FRAME_CTRL_B0, &saved_frame);
	if (ret)
		goto out_unlock;
	ret = master_read(SWRM_FRAME_CTRL_B1, &saved_frame_b1);
	if (ret)
		goto out_unlock;
	held = (struct spx_held_state) {
		.access = saved_access,
		.dir = saved_dir,
		.val = saved_val,
		.cpu_en = saved_cpu_en,
		.enum_cfg = saved_enum,
		.comp_cfg = saved_comp_cfg,
		.mcp_cfg = saved_mcp_cfg,
		.link_ee = saved_link_ee,
		.irq_mask = saved_irq_mask,
		.fifo_cfg = saved_fifo_cfg,
		.frame_b0 = saved_frame,
		.frame_b1 = saved_frame_b1,
		.intr_mask_soft = ctrl->intr_mask ?
				  ctrl->intr_mask : saved_irq_mask,
	};
	master_read(SWRM_COMP_STATUS, &comp_before);
	master_write(SWRM_INTERRUPT_CPU_EN, 0);
	master_write(SWRM_ENUM_CFG, 0);

	/* Exact external power-cycle of one slave while the wire is quiet. */
	regmap_update_bits(wcd_regmap, WCD_GPIO_VAL, WSA_GPIO_MASK, 0);
	regmap_update_bits(wcd_regmap, WCD_GPIO_DIR,
			   WSA_GPIO_MASK, WSA_GPIO_MASK);
	msleep(20);
	if (full_vendor_reinit) {
		u32 vendor_cfg =
			(saved_mcp_cfg & ~SWRM_NO_PINGS_MASK) |
			(31U << 17);
		int poll;

		master_write(SWRM_COMP_SW_RESET, 1);
		master_write(SWRM_COMP_SW_RESET, 1);
		master_write(SWRM_CMD_FIFO_CFG, 3);
		master_write(SWRM_MCP_CFG, vendor_cfg);
		master_write(SWRM_INTERRUPT_MASK, 0);
		master_write(SWRM_INTERRUPT_MASK, 0x1fffd);
		master_write(SWRM_FRAME_CTRL_B0, 0x10000 |
			     (clock_div >= 0 ? (u32)clock_div << 8 : 0));
		master_write(SWRM_ENUM_CFG, 1);
		master_write(SWRM_MCP_BUS_CTRL, BIT(1));
		master_write(SWRM_COMP_CFG, 2);
		master_write(SWRM_COMP_CFG, 3);
		master_write(SWRM_INTERRUPT_CLEAR, ~0U);
		for (poll = 0; poll < 100; poll++) {
			master_read(SWRM_COMP_STATUS, &comp_after);
			if (comp_after & 1)
				break;
			usleep_range(500, 510);
		}
	}
	if (!full_vendor_reinit && clock_div >= 0)
		master_write(SWRM_FRAME_CTRL_B0,
			     (saved_frame & ~GENMASK(10, 8)) |
			     ((u32)clock_div << 8));
	if (clash_workaround) {
		master_write(SWRM_COMP_CFG, 1);
		master_write(SWRM_COMP_CFG, 2);
		master_write(SWRM_INTERRUPT_CLEAR, ~0U);
		master_write(SWRM_COMP_CFG, 3);
	}
	if (no_pings >= 0)
		master_write(SWRM_MCP_CFG,
			     (saved_mcp_cfg & ~SWRM_NO_PINGS_MASK) |
			     ((u32)no_pings << 17));
	if (claim_cpu_ee) {
		master_write(SWRM_LINK_MANAGER_EE, 1);
		master_write(SWRM_MCP_BUS_CTRL, BIT(2));
	}
	master_read(SWRM_COMP_STATUS, &comp_after);
	pr_info("spxautocap setup pin=%d comp=%#x->%#x cfg=%#x np=%d div=%d link=%#x bus=%#x claim=%d\n",
		active_pin, comp_before, comp_after, saved_mcp_cfg, no_pings,
		clock_div, saved_link_ee, saved_bus_ctrl, claim_cpu_ee);
	if (enum_before_wake)
		master_write(SWRM_ENUM_CFG, 1);
	regmap_update_bits(wcd_regmap, WCD_GPIO_VAL,
			   WSA_GPIO_MASK, BIT(active_pin));
	if (!enum_before_wake) {
		msleep(20);
		master_write(SWRM_ENUM_CFG, 1);
	}

	for (sample = 0; sample < snapshots; sample++) {
		master_read(SWRM_INTERRUPT_STATUS, &irq);
		master_read(SWRM_MCP_SLV_STATUS, &slv);
		master_read(SWRM_ENUM_ID1(1), &id11);
		master_read(SWRM_ENUM_ID2(1), &id12);
		master_read(SWRM_ENUM_ID1(2), &id21);
		master_read(SWRM_ENUM_ID2(2), &id22);
		if (!divider_settled && settle_div >= 0 && id11 && id12) {
			u32 frame;

			master_read(SWRM_FRAME_CTRL_B0, &frame);
			master_write(SWRM_FRAME_CTRL_B0,
				     (frame & ~GENMASK(10, 8)) |
				     ((u32)settle_div << 8));
			divider_settled = true;
			pr_info("spxautocap pin=%d dev1 complete; switched divider to %d\n",
				active_pin, settle_div);
		}
		if (divider_settled && id11 && id12 &&
		    (slv & GENMASK(3, 2)) == BIT(2))
			dev1_stable++;
		else
			dev1_stable = 0;
		if (dual_enum && !second_woken && dev1_stable >= 4) {
			regmap_update_bits(wcd_regmap, WCD_GPIO_VAL,
					   WSA_GPIO_MASK,
					   WSA_GPIO_MASK);
			second_woken = true;
			pr_info("spxautocap pin=%d dev1 stable; released pin=%d for dev2\n",
				active_pin, active_pin == 1 ? 2 : 1);
		}
		if (second_woken && !dual_divider_settled &&
		    dual_settle_div >= 0 && id21 && id22) {
			u32 frame;

			master_read(SWRM_FRAME_CTRL_B0, &frame);
			master_write(SWRM_FRAME_CTRL_B0,
				     (frame & ~GENMASK(10, 8)) |
				     ((u32)dual_settle_div << 8));
			dual_divider_settled = true;
			pr_info("spxautocap pin=%d dev2 complete; switched divider to %d\n",
				active_pin, dual_settle_div);
		}
		/*
		 * Single-amp hold: dev1 alone must be able to satisfy the
		 * runtime handoff, otherwise runtime_ready never goes true and
		 * keep_live is refused even though slv=0x4 is rock stable.
		 */
		if (!dual_enum) {
			dual_stable = dev1_stable;
		} else if (dual_divider_settled && id11 && id12 && id21 &&
			   id22 &&
			   (slv & GENMASK(5, 2)) == (BIT(4) | BIT(2))) {
			dual_stable++;
		} else {
			dual_stable = 0;
		}
		if (runtime_handoff && !runtime_ready && dual_stable >= 4) {
			master_write(SWRM_ENUM_CFG, 0);
			master_write(SWRM_FRAME_CTRL_B0, BIT(16) | BIT(8));
			master_write(SWRM_FRAME_CTRL_B1, BIT(16) | BIT(8));
			master_write(SWRM_INTERRUPT_CLEAR, ~0U);
			runtime_ready = true;
			pr_info("spxautocap: Windows runtime handoff frame=0x10100 enum=0\n");
		}
		if (irq != prev_irq || slv != prev_slv ||
		    id11 != prev_id11 || id12 != prev_id12 ||
		    id21 != prev_id21 || id22 != prev_id22) {
			if (changes++ < 200)
				pr_info("spxautocap pin=%d sample=%d/%d irq=%#x slv=%#x dev1=%#x/%#x dev2=%#x/%#x\n",
					active_pin, sample + 1, snapshots,
					irq, slv, id11, id12, id21, id22);
			prev_irq = irq;
			prev_slv = slv;
			prev_id11 = id11;
			prev_id12 = id12;
			prev_id21 = id21;
			prev_id22 = id22;
		}
	}
	pr_info("spxautocap summary pin=%d snapshots=%d changes=%u second=%d irq=%#x slv=%#x dev1=%#x/%#x dev2=%#x/%#x\n",
		active_pin, snapshots, changes, second_woken, irq, slv,
		id11, id12, id21, id22);
	ret = 0;

	if (keep_live) {
		u32 live_frame;

		/*
		 * With both amps live the master reports MASTER_CLASH_DET and
		 * DOUT_PORT_COLLISION during playback and the device table is
		 * cleared mid-stream, so a single-amp hold has to be a valid
		 * outcome: require the second amp only when dual_enum asked
		 * for it.
		 */
		bool need_second = dual_enum;

		if (!bridge_sane()) {
			ret = -EIO;
			goto restore;
		}

		if (!id11 || !id12 ||
		    (need_second && (!second_woken || !id21 || !id22)) ||
		    (!runtime_handoff &&
		     (slv & GENMASK(5, 2)) !=
		     (need_second ? (BIT(4) | BIT(2)) : BIT(2))) ||
		    (runtime_handoff && !runtime_ready)) {
			pr_err("spxautocap: refusing keep_live without stable %s attachment\n",
			       need_second ? "dual" : "single");
			ret = -EIO;
			goto restore;
		}
		if (runtime_handoff) {
			ret = register_kprobe(&frame_guard_probe);
			if (ret) {
				pr_err("spxautocap: frame guard unavailable: %d\n", ret);
				goto restore;
			}
			frame_guard_registered = true;
		}
		master_read(SWRM_FRAME_CTRL_B0, &live_frame);
		master_write(SWRM_FRAME_CTRL_B1, live_frame);
		ctrl->intr_mask = SWRM_INTERRUPT_STATUS_SPECIAL_CMD_ID_FINISHED;
		master_write(SWRM_INTERRUPT_MASK,
			     SWRM_INTERRUPT_STATUS_SPECIAL_CMD_ID_FINISHED);
		master_write(SWRM_INTERRUPT_CLEAR, ~0U);
		master_write(SWRM_INTERRUPT_CPU_EN,
			     SWRM_INTERRUPT_STATUS_SPECIAL_CMD_ID_FINISHED);
		held.active = true;
		pr_info("spxautocap: dual bus held live frame=%#x irq_mask=%#x\n",
			live_frame, saved_irq_mask);
		goto out_unlock;
	}

restore:
	master_write(SWRM_ENUM_CFG, 0);
	master_write(SWRM_INTERRUPT_MASK, saved_irq_mask);
	master_write(SWRM_CMD_FIFO_CFG, saved_fifo_cfg);
	master_write(SWRM_FRAME_CTRL_B0, saved_frame);
	master_write(SWRM_FRAME_CTRL_B1, saved_frame_b1);
	master_write(SWRM_MCP_CFG, saved_mcp_cfg);
	master_write(SWRM_LINK_MANAGER_EE, saved_link_ee);
	/* BUS_CTRL is a start command; restore the running Windows path. */
	master_write(SWRM_MCP_BUS_CTRL, BIT(1));
	master_write(SWRM_COMP_CFG, saved_comp_cfg);
	master_write(SWRM_ENUM_CFG, saved_enum);
	master_write(SWRM_INTERRUPT_CPU_EN, saved_cpu_en);
	regmap_update_bits(wcd_regmap, WCD_GPIO_VAL, WSA_GPIO_MASK, 0);
	msleep(20);
	regmap_update_bits(wcd_regmap, WCD_GPIO_DIR,
			   WSA_GPIO_MASK, saved_dir & WSA_GPIO_MASK);
	regmap_update_bits(wcd_regmap, WCD_GPIO_VAL,
			   WSA_GPIO_MASK, saved_val & WSA_GPIO_MASK);
out_unlock:
	mutex_unlock(&ctrl->controller_lock);
	mutex_unlock(&bus->bus_lock);
	regmap_write(wcd_regmap, WCD_AHB_ACCESS_CFG, saved_access);
	if (ret)
		goto err_put;
	if (held.active && handoff_codecs)
		map_surface_codecs_live(bus);
	return 0;

err_put:
	put_device(swrm_dev);
	swrm_dev = NULL;
	return ret;
}

static void __exit spx_swrm_autoenum_capture_exit(void)
{
	struct spx_qcom_swrm_prefix *ctrl = swrm_ctrl;
	struct sdw_bus *bus = swrm_ctrl;

	if (held.active && ctrl && bus && wcd_regmap) {
		held.active = false;
		if (frame_guard_registered) {
			unregister_kprobe(&frame_guard_probe);
			frame_guard_registered = false;
		}
		mutex_lock(&bus->bus_lock);
		mutex_lock(&ctrl->controller_lock);
		master_write(SWRM_INTERRUPT_CPU_EN, 0);
		master_write(SWRM_ENUM_CFG, 0);
		regmap_update_bits(wcd_regmap, WCD_GPIO_VAL,
				   WSA_GPIO_MASK, 0);
		regmap_update_bits(wcd_regmap, WCD_GPIO_DIR,
				   WSA_GPIO_MASK, WSA_GPIO_MASK);
		msleep(20);
		master_write(SWRM_INTERRUPT_MASK, held.irq_mask);
		master_write(SWRM_CMD_FIFO_CFG, held.fifo_cfg);
		master_write(SWRM_FRAME_CTRL_B0, held.frame_b0);
		master_write(SWRM_FRAME_CTRL_B1, held.frame_b1);
		master_write(SWRM_MCP_CFG, held.mcp_cfg);
		master_write(SWRM_LINK_MANAGER_EE, held.link_ee);
		master_write(SWRM_MCP_BUS_CTRL, BIT(1));
		master_write(SWRM_COMP_CFG, held.comp_cfg);
		master_write(SWRM_ENUM_CFG, held.enum_cfg);
		ctrl->intr_mask = held.intr_mask_soft;
		master_write(SWRM_INTERRUPT_CPU_EN, held.cpu_en);
		regmap_update_bits(wcd_regmap, WCD_GPIO_DIR,
				   WSA_GPIO_MASK, held.dir & WSA_GPIO_MASK);
		regmap_update_bits(wcd_regmap, WCD_GPIO_VAL,
				   WSA_GPIO_MASK, held.val & WSA_GPIO_MASK);
		mutex_unlock(&ctrl->controller_lock);
		mutex_unlock(&bus->bus_lock);
		regmap_write(wcd_regmap, WCD_AHB_ACCESS_CFG, held.access);
		pr_info("spxautocap: restored pre-test controller/GPIO state\n");
	}
	if (swrm_dev)
		put_device(swrm_dev);
	pr_info("spx_swrm_autoenum_capture: unloaded\n");
}

module_init(spx_swrm_autoenum_capture_init);
module_exit(spx_swrm_autoenum_capture_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX reversible Windows-path hardware autoenum capture");
