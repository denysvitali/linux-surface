// SPDX-License-Identifier: GPL-2.0
// Copyright (c) 2019, Linaro Limited

#include <linux/clk.h>
#include <linux/completion.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/debugfs.h>
#include <linux/of.h>
#include <linux/of_irq.h>
#include <linux/pm_runtime.h>
#include <linux/regmap.h>
#include <linux/reset.h>
#include <linux/slab.h>
#include <linux/pm_wakeirq.h>
#include <linux/slimbus.h>
#include <linux/soundwire/sdw.h>
#include <linux/soundwire/sdw_registers.h>
#include <sound/pcm_params.h>
#include <sound/soc.h>
#include "bus.h"

/*
 * SPX: on the wcd934x internal SoundWire master (no usable IRQ) the HW
 * auto-enumerator runs at master probe, BEFORE wsa881x powers the WSA881x amps,
 * so it scans an unpowered bus and latches a garbage DevID. When set, the poll
 * worker re-runs the auto-enum on a live (powered) bus via soft-reset + re-init.
 * Gated + default-off so the known-good default boot is unaffected; the
 * experimental GRUB entry passes soundwire_qcom.spx_core_enum=1. IRQ-less only.
 */
static int spx_core_enum;
module_param(spx_core_enum, int, 0644);

/*
 * The byte-for-byte Windows controller init is useful as a diagnostic, but it
 * powers both Surface Pro X amplifiers into the hardware auto-enumerator at
 * once. On the codec-internal, SLIMbus-bridged master that leaves both slaves
 * colliding at device 0. Keep that experiment opt-in; the working path is the
 * single-amp force attach selected by spx_core_enum/spx_force_attach.
 */
static bool spx_exact_windows_init;
module_param(spx_exact_windows_init, bool, 0444);
MODULE_PARM_DESC(spx_exact_windows_init,
		 "SPX: use the experimental two-amp Windows controller init instead of stable single-amp force attach");

/* Diagnostic only: one DAC schedule and analog profile shared by both amps. */
static bool spx_keep_enum_frame;
module_param(spx_keep_enum_frame, bool, 0444);
MODULE_PARM_DESC(spx_keep_enum_frame,
		 "SPX: retain 48x2 divider-3 enumeration frame during playback diagnostic");

static bool spx_broadcast_audio;
module_param(spx_broadcast_audio, bool, 0644);
MODULE_PARM_DESC(spx_broadcast_audio,
		 "SPX: broadcast WSA and data-port writes for a shared mono diagnostic (default off)");
/*
 * SPX: the WCD9340 AHB bridge is slow -- reading RD_DATA before the bridge has
 * fetched the SWR-master register returns stale/partial bytes (observed:
 * intermittent 0xAA/0x00 corruption in DevID reads even though the amp does
 * respond). The Windows-native Surface path reproduces qcauddev8180's exact
 * ACCESS_STATUS completion handshake for every bridge transaction.
 * spx_ahb_dbg logs each bridge read's status so the completion bit can be
 * characterised live; spx_ahb_wait_us caps the completion poll.
 */
static int spx_ahb_dbg;
module_param(spx_ahb_dbg, int, 0644);
static int spx_ahb_wait_us = 500;
module_param(spx_ahb_wait_us, int, 0644);
/*
 * SPX: the two WSA881x share SD_N (wcdgpio pin1) AND a shared enable (pin2), so
 * they can't be electrically isolated -- both always answer device 0, and the
 * unique_id read is too marginal to disambiguate them (bytes drop). But the amp
 * DOES report the correct DevID (0217:2010, confirmed byte-by-byte), and the
 * audio DATA path is master->slave (no response -> no bus clash). So when
 * spx_force_attach is set, blindly assign device number 1 at device 0 (a
 * fire-and-forget write, far more reliable than the reads), mark the DT WSA
 * slave attached, and let wsa881x bind + stream. Both physical amps take dev 1
 * and receive the same stream (mono, both speakers) -- the goal is audible sound.
 */
static int spx_force_attach;
module_param(spx_force_attach, int, 0644);
MODULE_PARM_DESC(spx_force_attach,
		 "SPX: blind-assign dev#1 + force-attach the WSA slave (bypass marginal enum reads)");
/*
 * SPX: skip the DevID read-back verification in force-attach. The two amps
 * clash on reads (both answer dev1 simultaneously), but writes are
 * fire-and-forget and may succeed. With blind attach, assign dev1 and
 * proceed without verifying the identity.
 */
static int spx_blind_attach;
module_param(spx_blind_attach, int, 0644);
MODULE_PARM_DESC(spx_blind_attach,
		 "SPX: skip DevID verification in force-attach (writes are fire-and-forget)");
/* Keep a validated logical slave bound without repeatedly reinitializing it. */
static bool spx_forced_attached;
/*
 * SPX: DEFAULT OFF. This used to redirect every logical device-1 write to
 * enumeration address 0, on the assumption that the amps never really retained
 * the blind device-number assignment. That assumption held only while the
 * "attach" was a fiction (MCP_SLV_STATUS read 0x0).
 *
 * Once the amps are brought up one at a time (see the per-amp powerdown pins in
 * sc8180x-wcd9340.dtsi) the assignment is REAL -- MCP_SLV_STATUS reads 0x4,
 * i.e. device 1 attached -- and a slave that has accepted a device number stops
 * answering address 0. With this enabled every write (wsa881x_init, DAPM, mixer,
 * PA enable/unmute, and the SoundWire core's DPn_ChannelEn/SampleCtrl/OffsetCtrl
 * port setup) was therefore dropped on the floor, while READS -- which are not
 * remapped -- kept working. That mismatch produced months of contradictory
 * register evidence and total silence. Turning it off produced audio.
 */
static int spx_write_dev0 = -1;
module_param(spx_write_dev0, int, 0644);
MODULE_PARM_DESC(spx_write_dev0,
		 "SPX: -1 = auto (follow MCP_SLV_STATUS), 0 = always device 1, 1 = always device 0");

/*
 * SPX: where the amplifier physically answers right now.
 *
 * The blind device-number assignment does not always stick: sometimes the amp
 * accepts device 1 (MCP_SLV_STATUS = 0x4) and sometimes it stays unenumerated
 * at device 0 (0x1). A slave only answers ONE of those addresses, so a fixed
 * routing choice is wrong half the time -- every register write silently
 * vanishes, which is invisible because qcom_swrm_cmd_fifo_wr_cmd() reports
 * SDW_CMD_OK for unicast regardless. Track the real address instead and let the
 * write path follow it.
 */
static bool spx_amp_at_dev0;
/* Set when the last MCP_SLV_STATUS sample showed no device at all; the write
 * path re-samples before routing so a late attach still flips the routing. */
static bool spx_amp_addr_stale = true;
/* Runtime-PM reference held after force-attach (see fast path). */
static bool spx_pm_held;

/*
 * SPX: dropped commands are invisible (unicast always reports SDW_CMD_OK), and
 * a lost bank-switch strands the bus on the bank whose channel-enable was never
 * programmed -- the "random silent run" failure. The old full-bank mirror and
 * write-twice experiments are retained opt-in but were proven to desynchronize
 * this amp. A narrower experiment shadows only DP1 ChannelEn on the master and
 * slave, leaving every other timing/transport register in the normal next-bank
 * sequence.
 */
static int spx_mirror_banks;
module_param(spx_mirror_banks, int, 0644);
MODULE_PARM_DESC(spx_mirror_banks, "SPX: program both register banks with identical port config");
static int spx_shadow_dp1_enable;
module_param(spx_shadow_dp1_enable, int, 0444);
MODULE_PARM_DESC(spx_shadow_dp1_enable,
		 "SPX: shadow only master/slave DP1 ChannelEn into both banks (boot-only dropped-switch workaround)");
static int spx_write_twice;
module_param(spx_write_twice, int, 0644);
MODULE_PARM_DESC(spx_write_twice, "SPX: issue amp-bound unicast writes twice (dropped-write insurance)");

/*
 * The frame-control broadcast has no slave response and cannot be verified on
 * this v1.3 master. If it is dropped, the bus remains on the old bank while
 * the enabled ports are in the new bank: all register traces look correct but
 * no samples flow. Repeat only this critical command; repeating all amplifier
 * writes was proven to destabilize the WSA881x.
 */
static int spx_bank_switch_repeats = 1;
module_param(spx_bank_switch_repeats, int, 0644);
MODULE_PARM_DESC(spx_bank_switch_repeats,
		 "SPX: number of identical SCP_FRAMECTRL broadcasts (1-5)");

/*
 * SPX: set once frame-gen is confirmed up at the end of qcom_swrm_init. The
 * ISR clash-recovery (re-arming the auto-enumerator) must NOT fire while the
 * bus is still being brought up -- toggling ENUMERATOR_CFG mid-init disrupts
 * frame-gen startup. Gate the recovery on this.
 */
static bool spx_bus_up;
/* SPX debug override for MCP_FRAME_CTRL_BANK.SSP_PERIOD[23:16]. */
static int spx_frame_phase = 1;
/* The audible SPX transport uses SSP_PERIOD=1 for streaming banks as well. */
static int spx_runtime_ssp_period = 1;

/* Live transport timing overrides for the WSA playback master port. */
static int spx_port_si = -1;
module_param(spx_port_si, int, 0644);
static int spx_port_off1 = -1;
module_param(spx_port_off1, int, 0644);
static int spx_port_off2 = -1;
module_param(spx_port_off2, int, 0644);
static int spx_port_bp = -1;
module_param(spx_port_bp, int, 0644);
MODULE_PARM_DESC(spx_port_bp,
		 "SPX: master port 1 block-packing mode (-1 leaves DT/default)");

/*
 * SPX: WCD9340 GPIO registers (from gpio-wcd934x.c): 0x42 = direction (bit per
 * pin, 1=output), 0x43 = output value. The WSA881x enable line is active high:
 * physical HIGH powers the amp and physical LOW turns it off. Bring the SWR
 * master up on a QUIET bus: power the selected WSA amps off BEFORE frame-gen
 * so they don't drive the bus and trigger MASTER_CLASH_DET (which makes
 * frame-gen lock nondeterministic), then release them after the lock.
 * spx_quiet_bus selects the pin mask to shut down during init (bitmask of
 * wcdgpio pins; default pin1+pin2 = 0x6). 0 disables the quiet-bus step.
 */
#define WCD934X_GPIO_DIR_CTL	0x42
#define WCD934X_GPIO_VAL_CTL	0x43
static int spx_quiet_bus;	/* default off: disproven as the frame-gen blocker */
module_param(spx_quiet_bus, int, 0644);
MODULE_PARM_DESC(spx_quiet_bus, "SPX: wcdgpio pin bitmask to hold in shutdown during frame-gen bring-up (0=off)");
MODULE_PARM_DESC(spx_core_enum,
		 "SPX: re-run HW auto-enum on a powered bus from the poll (IRQ-less master)");

/*
 * SPX live-iteration harness (debug). With spx_core_enum=1 the diag normally
 * reads the 6-byte SCP DevID with retries. To isolate WHICH read fails, set
 * spx_diag_reg to a single SCP/SWR register: the diag then reads ONLY that
 * register, spx_diag_count times, at device spx_diag_dev, logging each value.
 * Writing anything to spx_reenum re-arms and re-runs the whole diag+enum on the
 * live bus (no reboot) -- so you can toggle the WSA enable GPIOs between runs.
 */
static int spx_diag_reg = -1;
module_param(spx_diag_reg, int, 0644);
MODULE_PARM_DESC(spx_diag_reg, "SPX: if >=0, diag reads ONLY this SCP/SWR reg repeatedly");
static int spx_diag_dev;
module_param(spx_diag_dev, int, 0644);
MODULE_PARM_DESC(spx_diag_dev, "SPX: device address for spx_diag_reg reads (default 0)");
static int spx_diag_count = 24;
module_param(spx_diag_count, int, 0644);
MODULE_PARM_DESC(spx_diag_count, "SPX: how many times the diag reads (default 24)");

#define SWRM_COMP_SW_RESET					0x008
#define SWRM_COMP_STATUS					0x014
#define SWRM_LINK_MANAGER_EE					0x018
#define SWRM_EE_CPU						1
#define SWRM_FRM_GEN_ENABLED					BIT(0)
#define SWRM_VERSION_1_3_0					0x01030000
#define SWRM_VERSION_1_5_1					0x01050001
#define SWRM_VERSION_1_7_0					0x01070000
#define SWRM_VERSION_2_0_0					0x02000000
#define SWRM_VERSION_3_1_0					0x03010000
#define SWRM_COMP_HW_VERSION					0x00
#define SWRM_COMP_CFG_ADDR					0x04
#define SWRM_COMP_CFG_IRQ_LEVEL_OR_PULSE_MSK			BIT(1)
#define SWRM_COMP_CFG_ENABLE_MSK				BIT(0)
#define SWRM_COMP_PARAMS					0x100
#define SWRM_COMP_PARAMS_WR_FIFO_DEPTH				GENMASK(14, 10)
#define SWRM_COMP_PARAMS_RD_FIFO_DEPTH				GENMASK(19, 15)
#define SWRM_COMP_PARAMS_DOUT_PORTS_MASK			GENMASK(4, 0)
#define SWRM_COMP_PARAMS_DIN_PORTS_MASK				GENMASK(9, 5)
#define SWRM_V3_COMP_PARAMS_WR_FIFO_DEPTH			GENMASK(17, 10)
#define SWRM_V3_COMP_PARAMS_RD_FIFO_DEPTH			GENMASK(23, 18)

#define SWRM_COMP_MASTER_ID					0x104
#define SWRM_V1_3_INTERRUPT_STATUS				0x200
#define SWRM_V2_0_INTERRUPT_STATUS				0x5000
#define SWRM_INTERRUPT_STATUS_RMSK				GENMASK(16, 0)
#define SWRM_INTERRUPT_STATUS_SLAVE_PEND_IRQ			BIT(0)
#define SWRM_INTERRUPT_STATUS_NEW_SLAVE_ATTACHED		BIT(1)
#define SWRM_INTERRUPT_STATUS_CHANGE_ENUM_SLAVE_STATUS		BIT(2)
#define SWRM_INTERRUPT_STATUS_MASTER_CLASH_DET			BIT(3)
#define SWRM_INTERRUPT_STATUS_RD_FIFO_OVERFLOW			BIT(4)
#define SWRM_INTERRUPT_STATUS_RD_FIFO_UNDERFLOW			BIT(5)
#define SWRM_INTERRUPT_STATUS_WR_CMD_FIFO_OVERFLOW		BIT(6)
#define SWRM_INTERRUPT_STATUS_CMD_ERROR				BIT(7)
#define SWRM_INTERRUPT_STATUS_DOUT_PORT_COLLISION		BIT(8)
#define SWRM_INTERRUPT_STATUS_READ_EN_RD_VALID_MISMATCH		BIT(9)
#define SWRM_INTERRUPT_STATUS_SPECIAL_CMD_ID_FINISHED		BIT(10)
#define SWRM_INTERRUPT_STATUS_AUTO_ENUM_FAILED			BIT(11)
#define SWRM_INTERRUPT_STATUS_AUTO_ENUM_TABLE_IS_FULL		BIT(12)
#define SWRM_INTERRUPT_STATUS_BUS_RESET_FINISHED_V2		BIT(13)
#define SWRM_INTERRUPT_STATUS_CLK_STOP_FINISHED_V2		BIT(14)
#define SWRM_INTERRUPT_STATUS_EXT_CLK_STOP_WAKEUP		BIT(16)
#define SWRM_INTERRUPT_STATUS_CMD_IGNORED_AND_EXEC_CONTINUED	BIT(19)
#define SWRM_INTERRUPT_MAX					17
#define SWRM_V1_3_INTERRUPT_MASK_ADDR				0x204
#define SWRM_V1_3_INTERRUPT_CLEAR				0x208
#define SWRM_V2_0_INTERRUPT_CLEAR				0x5008
#define SWRM_V1_3_INTERRUPT_CPU_EN				0x210
#define SWRM_V2_0_INTERRUPT_CPU_EN				0x5004
#define SWRM_V1_3_CMD_FIFO_WR_CMD				0x300
#define SWRM_V2_0_CMD_FIFO_WR_CMD				0x5020
#define SWRM_V1_3_CMD_FIFO_RD_CMD				0x304
#define SWRM_V2_0_CMD_FIFO_RD_CMD				0x5024
#define SWRM_CMD_FIFO_CMD					0x308
#define SWRM_CMD_FIFO_FLUSH					0x1
#define SWRM_V1_3_CMD_FIFO_STATUS				0x30C
#define SWRM_V2_0_CMD_FIFO_STATUS				0x5050
#define SWRM_RD_CMD_FIFO_CNT_MASK				GENMASK(20, 16)
#define SWRM_WR_CMD_FIFO_CNT_MASK				GENMASK(12, 8)
#define SWRM_CMD_FIFO_CFG_ADDR					0x314
#define SWRM_CONTINUE_EXEC_ON_CMD_IGNORE			BIT(31)
#define SWRM_RD_WR_CMD_RETRIES					0x7
#define SWRM_V1_3_CMD_FIFO_RD_FIFO_ADDR				0x318
#define SWRM_V2_0_CMD_FIFO_RD_FIFO_ADDR				0x5040
#define SWRM_RD_FIFO_CMD_ID_MASK				GENMASK(11, 8)
#define SWRM_ENUMERATOR_CFG_ADDR				0x500
#define SWRM_ENUMERATOR_SLAVE_DEV_ID_1(m)		(0x530 + 0x8 * (m))
#define SWRM_ENUMERATOR_SLAVE_DEV_ID_2(m)		(0x534 + 0x8 * (m))
#define SWRM_MCP_FRAME_CTRL_BANK_ADDR(m)		(0x101C + 0x40 * (m))
#define SWRM_MCP_FRAME_CTRL_BANK_COL_CTRL_BMSK			GENMASK(2, 0)
#define SWRM_MCP_FRAME_CTRL_BANK_ROW_CTRL_BMSK			GENMASK(7, 3)
#define SWRM_MCP_BUS_CTRL					0x1044
#define SWRM_MCP_BUS_CLK_START					BIT(1)
#define SWRM_MCP_CFG_ADDR					0x1048
#define SWRM_MCP_CFG_MAX_NUM_OF_CMD_NO_PINGS_BMSK		GENMASK(21, 17)
#define SWRM_DEF_CMD_NO_PINGS					0x1f
#define SWRM_MCP_STATUS						0x104C
#define SWRM_MCP_STATUS_BANK_NUM_MASK				BIT(0)
#define SWRM_MCP_SLV_STATUS					0x1090
#define SWRM_MCP_SLV_STATUS_MASK				GENMASK(1, 0)
#define SWRM_MCP_SLV_STATUS_SZ					2

#define SWRM_DPn_PORT_CTRL_BANK(offset, n, m)	(offset + 0x100 * (n - 1) + 0x40 * m)
#define SWRM_DPn_PORT_CTRL_2_BANK(offset, n, m)	(offset + 0x100 * (n - 1) + 0x40 * m)
#define SWRM_DPn_BLOCK_CTRL_1(offset, n)	(offset + 0x100 * (n - 1))
#define SWRM_DPn_BLOCK_CTRL2_BANK(offset, n, m)	(offset + 0x100 * (n - 1) + 0x40 * m)
#define SWRM_DPn_PORT_HCTRL_BANK(offset,  n, m)	(offset + 0x100 * (n - 1) + 0x40 * m)
#define SWRM_DPn_BLOCK_CTRL3_BANK(offset, n, m)	(offset + 0x100 * (n - 1) + 0x40 * m)
#define SWRM_DPn_SAMPLECTRL2_BANK(offset, n, m)	(offset + 0x100 * (n - 1) + 0x40 * m)

#define SWR_V1_3_MSTR_MAX_REG_ADDR				0x1740
#define SWR_V2_0_MSTR_MAX_REG_ADDR				0x50ac

#define SWRM_V2_0_CLK_CTRL					0x5060
#define SWRM_V2_0_CLK_CTRL_CLK_START				BIT(0)
#define SWRM_V2_0_LINK_STATUS					0x5064

#define SWRM_DP_PORT_CTRL_EN_CHAN_SHFT				0x18
#define SWRM_DP_PORT_CTRL_OFFSET2_SHFT				0x10
#define SWRM_DP_PORT_CTRL_OFFSET1_SHFT				0x08
/*
 * Codec-internal SWR-master AHB bridge value-elements. These are WCD934X
 * regmap addresses: the regmap range_cfg (window_start=0x800, window_len=0x100)
 * page-translates 0xc85 -> write page 0x0c to selector VE 0x800, then access
 * data at VE 0x885. Confirmed on SPX (sc8180x): VE 0x885 echoes WR_DATA, VE
 * 0x800 reads back 0x0c. (Do NOT "remap" these to raw VEs like 0x844 — that
 * was a 2026-06-29 misread of a direct, non-paged slim_read probe and it
 * breaks COMP_PARAMS readback, failing the master probe with -EINVAL.)
 */
#define SWRM_AHB_BRIDGE_WR_DATA_0				0xc85
#define SWRM_AHB_BRIDGE_WR_ADDR_0				0xc89
#define SWRM_AHB_BRIDGE_RD_ADDR_0				0xc8d
#define SWRM_AHB_BRIDGE_RD_DATA_0				0xc91
/*
 * Bridge access configuration.  Downstream Qualcomm names WCD register 0xc95
 * WCD934X_SWR_AHB_BRIDGE_ACCESS_CFG and gives it a reset value of 0x0f.
 * qcauddev8180.sys nevertheless explicitly reasserts 0x0f immediately after
 * enabling the WCD SoundWire clock and before its first master access.
 */
#define SWRM_AHB_BRIDGE_ACCESS_CFG				0xc95
/*
 * AHB-bridge transaction-complete status. Windows (qcauddev8180) polls
 * this after every codec-internal SWR register access; mainline never reads it.
 */
#define SWRM_AHB_BRIDGE_ACCESS_STATUS				0xc96

#define SWRM_REG_VAL_PACK(data, dev, id, reg)	\
			((reg) | ((id) << 16) | ((dev) << 20) | ((data) << 24))

#define MAX_FREQ_NUM						1
#define TIMEOUT_MS						100
#define QCOM_SWRM_MAX_RD_LEN					0x1
#define DEFAULT_CLK_FREQ					9600000
#define SWR_INVALID_PARAM					0xFF
#define SWR_HSTOP_MAX_VAL					0xF
#define SWR_HSTART_MIN_VAL					0x0
#define SWR_BROADCAST_CMD_ID					0x0F
#define SWR_MAX_CMD_ID						14
#define MAX_FIFO_RD_RETRY					3
#define SWR_OVERFLOW_RETRY_COUNT				30
#define SWRM_LINK_STATUS_RETRY_CNT				100

enum {
	MASTER_ID_WSA = 1,
	MASTER_ID_RX,
	MASTER_ID_TX
};

struct qcom_swrm_port_config {
	u16 si;
	u8 off1;
	u8 off2;
	u8 bp_mode;
	u8 hstart;
	u8 hstop;
	u8 word_length;
	u8 blk_group_count;
	u8 lane_control;
};

/*
 * Internal IDs for different register layouts.  Only few registers differ per
 * each variant, so the list of IDs below does not include all of registers.
 */
enum {
	SWRM_REG_FRAME_GEN_ENABLED,
	SWRM_REG_INTERRUPT_STATUS,
	SWRM_REG_INTERRUPT_MASK_ADDR,
	SWRM_REG_INTERRUPT_CLEAR,
	SWRM_REG_INTERRUPT_CPU_EN,
	SWRM_REG_CMD_FIFO_WR_CMD,
	SWRM_REG_CMD_FIFO_RD_CMD,
	SWRM_REG_CMD_FIFO_STATUS,
	SWRM_REG_CMD_FIFO_RD_FIFO_ADDR,
	SWRM_OFFSET_DP_PORT_CTRL_BANK,
	SWRM_OFFSET_DP_PORT_CTRL_2_BANK,
	SWRM_OFFSET_DP_BLOCK_CTRL_1,
	SWRM_OFFSET_DP_BLOCK_CTRL2_BANK,
	SWRM_OFFSET_DP_PORT_HCTRL_BANK,
	SWRM_OFFSET_DP_BLOCK_CTRL3_BANK,
	SWRM_OFFSET_DP_SAMPLECTRL2_BANK,
};

struct qcom_swrm_ctrl {
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
	/* Serialize a complete transaction through the WCD9340 AHB bridge. */
	struct mutex ahb_lock;
	/* Keep the threaded IRQ out of a partially completed controller init. */
	struct mutex controller_lock;
	/* Port alloc/free lock */
	struct mutex port_lock;
	struct clk *hclk;
	int irq;
	unsigned int version;
	int wake_irq;
	int num_din_ports;
	int num_dout_ports;
	int nports;
	int cols_index;
	int rows_index;
	unsigned long port_mask;
	u32 intr_mask;
	u8 rcmd_id;
	u8 wcmd_id;
	/* Port numbers are 1 - 14 */
	struct qcom_swrm_port_config *pconfig;
	struct sdw_stream_runtime **sruntime;
	enum sdw_slave_status status[SDW_MAX_DEVICES + 1];
	int (*reg_read)(struct qcom_swrm_ctrl *ctrl, int reg, u32 *val);
	int (*reg_write)(struct qcom_swrm_ctrl *ctrl, int reg, int val);
	u32 slave_status;
	u32 wr_fifo_depth;
	bool clock_stop_not_supported;
	bool spx_windows_init;
	bool spx_runtime_handoff_pending;
	bool spx_runtime_mirror_pending;
	struct delayed_work spx_enum_work;	/* SPX: poll-enumerate, IRQ-less */
	int spx_enum_tries;
	bool spx_diag_done;			/* SPX: one-shot DevID probe ran */
	struct delayed_work spx_wd_work;	/* SPX: amp-presence watchdog */
	int spx_wd_state;
	int spx_wd_fails;
	int spx_wd_misses;
	bool spx_stopping;
};

struct qcom_swrm_data {
	u32 default_cols;
	u32 default_rows;
	bool sw_clk_gate_required;
	u32 max_reg;
	const unsigned int *reg_layout;
};

static const unsigned int swrm_v1_3_reg_layout[] = {
	[SWRM_REG_FRAME_GEN_ENABLED] = SWRM_COMP_STATUS,
	[SWRM_REG_INTERRUPT_STATUS] = SWRM_V1_3_INTERRUPT_STATUS,
	[SWRM_REG_INTERRUPT_MASK_ADDR] = SWRM_V1_3_INTERRUPT_MASK_ADDR,
	[SWRM_REG_INTERRUPT_CLEAR] = SWRM_V1_3_INTERRUPT_CLEAR,
	[SWRM_REG_INTERRUPT_CPU_EN] = SWRM_V1_3_INTERRUPT_CPU_EN,
	[SWRM_REG_CMD_FIFO_WR_CMD] = SWRM_V1_3_CMD_FIFO_WR_CMD,
	[SWRM_REG_CMD_FIFO_RD_CMD] = SWRM_V1_3_CMD_FIFO_RD_CMD,
	[SWRM_REG_CMD_FIFO_STATUS] = SWRM_V1_3_CMD_FIFO_STATUS,
	[SWRM_REG_CMD_FIFO_RD_FIFO_ADDR] = SWRM_V1_3_CMD_FIFO_RD_FIFO_ADDR,
	[SWRM_OFFSET_DP_PORT_CTRL_BANK]		= 0x1124,
	[SWRM_OFFSET_DP_PORT_CTRL_2_BANK]	= 0x1128,
	[SWRM_OFFSET_DP_BLOCK_CTRL_1]		= 0x112c,
	[SWRM_OFFSET_DP_BLOCK_CTRL2_BANK]	= 0x1130,
	[SWRM_OFFSET_DP_PORT_HCTRL_BANK]	= 0x1134,
	[SWRM_OFFSET_DP_BLOCK_CTRL3_BANK]	= 0x1138,
	[SWRM_OFFSET_DP_SAMPLECTRL2_BANK]	= 0x113c,
};

static const struct qcom_swrm_data swrm_v1_3_data = {
	.default_rows = 48,
	.default_cols = 16,
	.max_reg = SWR_V1_3_MSTR_MAX_REG_ADDR,
	.reg_layout = swrm_v1_3_reg_layout,
};

static const struct qcom_swrm_data swrm_v1_5_data = {
	.default_rows = 50,
	.default_cols = 16,
	.max_reg = SWR_V1_3_MSTR_MAX_REG_ADDR,
	.reg_layout = swrm_v1_3_reg_layout,
};

static const struct qcom_swrm_data swrm_v1_6_data = {
	.default_rows = 50,
	.default_cols = 16,
	.sw_clk_gate_required = true,
	.max_reg = SWR_V1_3_MSTR_MAX_REG_ADDR,
	.reg_layout = swrm_v1_3_reg_layout,
};

static const unsigned int swrm_v2_0_reg_layout[] = {
	[SWRM_REG_FRAME_GEN_ENABLED] = SWRM_V2_0_LINK_STATUS,
	[SWRM_REG_INTERRUPT_STATUS] = SWRM_V2_0_INTERRUPT_STATUS,
	[SWRM_REG_INTERRUPT_MASK_ADDR] = 0, /* Not present */
	[SWRM_REG_INTERRUPT_CLEAR] = SWRM_V2_0_INTERRUPT_CLEAR,
	[SWRM_REG_INTERRUPT_CPU_EN] = SWRM_V2_0_INTERRUPT_CPU_EN,
	[SWRM_REG_CMD_FIFO_WR_CMD] = SWRM_V2_0_CMD_FIFO_WR_CMD,
	[SWRM_REG_CMD_FIFO_RD_CMD] = SWRM_V2_0_CMD_FIFO_RD_CMD,
	[SWRM_REG_CMD_FIFO_STATUS] = SWRM_V2_0_CMD_FIFO_STATUS,
	[SWRM_REG_CMD_FIFO_RD_FIFO_ADDR] = SWRM_V2_0_CMD_FIFO_RD_FIFO_ADDR,
	[SWRM_OFFSET_DP_PORT_CTRL_BANK]		= 0x1124,
	[SWRM_OFFSET_DP_PORT_CTRL_2_BANK]	= 0x1128,
	[SWRM_OFFSET_DP_BLOCK_CTRL_1]		= 0x112c,
	[SWRM_OFFSET_DP_BLOCK_CTRL2_BANK]	= 0x1130,
	[SWRM_OFFSET_DP_PORT_HCTRL_BANK]	= 0x1134,
	[SWRM_OFFSET_DP_BLOCK_CTRL3_BANK]	= 0x1138,
	[SWRM_OFFSET_DP_SAMPLECTRL2_BANK]	= 0x113c,
};

static const struct qcom_swrm_data swrm_v2_0_data = {
	.default_rows = 50,
	.default_cols = 16,
	.sw_clk_gate_required = true,
	.max_reg = SWR_V2_0_MSTR_MAX_REG_ADDR,
	.reg_layout = swrm_v2_0_reg_layout,
};

static const unsigned int swrm_v3_0_reg_layout[] = {
	[SWRM_REG_FRAME_GEN_ENABLED] = SWRM_V2_0_LINK_STATUS,
	[SWRM_REG_INTERRUPT_STATUS] = SWRM_V2_0_INTERRUPT_STATUS,
	[SWRM_REG_INTERRUPT_MASK_ADDR] = 0, /* Not present */
	[SWRM_REG_INTERRUPT_CLEAR] = SWRM_V2_0_INTERRUPT_CLEAR,
	[SWRM_REG_INTERRUPT_CPU_EN] = SWRM_V2_0_INTERRUPT_CPU_EN,
	[SWRM_REG_CMD_FIFO_WR_CMD] = SWRM_V2_0_CMD_FIFO_WR_CMD,
	[SWRM_REG_CMD_FIFO_RD_CMD] = SWRM_V2_0_CMD_FIFO_RD_CMD,
	[SWRM_REG_CMD_FIFO_STATUS] = SWRM_V2_0_CMD_FIFO_STATUS,
	[SWRM_REG_CMD_FIFO_RD_FIFO_ADDR] = SWRM_V2_0_CMD_FIFO_RD_FIFO_ADDR,
	[SWRM_OFFSET_DP_PORT_CTRL_BANK]		= 0x1224,
	[SWRM_OFFSET_DP_PORT_CTRL_2_BANK]	= 0x1228,
	[SWRM_OFFSET_DP_BLOCK_CTRL_1]		= 0x122c,
	[SWRM_OFFSET_DP_BLOCK_CTRL2_BANK]	= 0x1230,
	[SWRM_OFFSET_DP_PORT_HCTRL_BANK]	= 0x1234,
	[SWRM_OFFSET_DP_BLOCK_CTRL3_BANK]	= 0x1238,
	[SWRM_OFFSET_DP_SAMPLECTRL2_BANK]	= 0x123c,
};

static const struct qcom_swrm_data swrm_v3_0_data = {
	.default_rows = 50,
	.default_cols = 16,
	.sw_clk_gate_required = true,
	.max_reg = SWR_V2_0_MSTR_MAX_REG_ADDR,
	.reg_layout = swrm_v3_0_reg_layout,
};
#define to_qcom_sdw(b)	container_of(b, struct qcom_swrm_ctrl, bus)

static int spx_regmap_read_byte(struct regmap *regmap, unsigned int reg,
				u8 *val)
{
	int retry;
	int ret = -EIO;

	/*
	 * The Windows WCD byte-read primitive retries a failed underlying
	 * SLIMbus transaction four times.  This is separate from the AHB
	 * completion poll: a transport error must not consume that poll's
	 * status-zero retry budget.
	 */
	for (retry = 0; retry < 4; retry++) {
		ret = regmap_bulk_read(regmap, reg, val, 1);
		if (!ret)
			return 0;
	}

	return ret;
}

static int __qcom_swrm_ahb_reg_read(struct qcom_swrm_ctrl *ctrl, int reg,
				    u32 *val)
{
	struct regmap *wcd_regmap = ctrl->regmap;
	u32 discard;
	int ret;

	/* pg register + offset */
	ret = regmap_bulk_write(wcd_regmap, SWRM_AHB_BRIDGE_RD_ADDR_0,
			  (u8 *)&reg, 4);
	if (ret < 0)
		return SDW_CMD_FAIL;

	/*
	 * The WCD9340 paged bridge completes more slowly under Linux than under
	 * qcauddev's synchronous byte primitive.  Immediate status polling gave
	 * torn enumerator words.  A settle interval plus one discarded RD_DATA
	 * sample produced stable, complete IDs for both Surface amplifiers.
	 */
	if (ctrl->spx_windows_init) {
		usleep_range(500, 550);
		ret = regmap_bulk_read(wcd_regmap, SWRM_AHB_BRIDGE_RD_DATA_0,
				       &discard, sizeof(discard));
		if (ret < 0)
			return SDW_CMD_FAIL;
		usleep_range(500, 550);
		ret = regmap_bulk_read(wcd_regmap, SWRM_AHB_BRIDGE_RD_DATA_0,
				       val, sizeof(*val));
		return ret < 0 ? SDW_CMD_FAIL : SDW_CMD_OK;
	}

	/*
	 * SPX: wait for the (slow) AHB bridge to complete the fetch before
	 * sampling RD_DATA, else we read stale/partial bytes. Poll ACCESS_STATUS
	 * (bit0 = done, best guess -- validated via spx_ahb_dbg) with a bounded
	 * timeout; if the bit never asserts we still fall through and read after
	 * the full wait, so a wrong guess only costs latency, never a hang.
	 */
	if (spx_core_enum) {
		u32 st = 0;
		int i, iters = spx_ahb_wait_us / 5;

		for (i = 0; i < iters; i++) {
			if (regmap_read(wcd_regmap, SWRM_AHB_BRIDGE_ACCESS_STATUS,
					&st) == 0 && (st & 0x1))
				break;
			udelay(5);
		}
		if (spx_ahb_dbg)
			dev_info(ctrl->dev,
				 "SPX AHB rd reg=0x%x access_status=0x%x iters=%d/%d\n",
				 reg, st, i, iters);
	}

	ret = regmap_bulk_read(wcd_regmap, SWRM_AHB_BRIDGE_RD_DATA_0,
			       val, sizeof(*val));
	if (ret < 0)
		return SDW_CMD_FAIL;

	return SDW_CMD_OK;
}

static int qcom_swrm_ahb_reg_read(struct qcom_swrm_ctrl *ctrl, int reg,
				  u32 *val)
{
	int ret;

	mutex_lock(&ctrl->ahb_lock);
	ret = __qcom_swrm_ahb_reg_read(ctrl, reg, val);
	mutex_unlock(&ctrl->ahb_lock);

	return ret;
}

static int __qcom_swrm_ahb_reg_write(struct qcom_swrm_ctrl *ctrl,
				     int reg, int val)
{
	struct regmap *wcd_regmap = ctrl->regmap;
	int ret;
	u32 request[2] = { val, reg };
	u8 status = 0;
	int i;

	/*
	 * qcauddev8180!0x14009a0a8 submits WR_DATA and WR_ADDR as one
	 * contiguous eight-byte SLIMbus transaction. Splitting this into two
	 * regmap writes lets a slow bridge observe an incomplete command.
	 */
	if (ctrl->spx_windows_init) {
		ret = regmap_bulk_write(wcd_regmap,
					SWRM_AHB_BRIDGE_WR_DATA_0,
					request, sizeof(request));
		if (ret < 0)
			return SDW_CMD_FAIL;

		/* Let the bridge consume the complete WR_DATA+WR_ADDR tuple. */
		usleep_range(500, 550);

		/*
		 * Windows performs at most six immediate one-byte status reads
		 * and waits specifically for WR_DONE (bit 0). RD_DONE (bit 1)
		 * can remain set from an earlier bridge read.
		 */
		for (i = 0; i < 6; i++) {
			ret = spx_regmap_read_byte(wcd_regmap,
						  SWRM_AHB_BRIDGE_ACCESS_STATUS,
						  &status);
			if (ret < 0)
				return SDW_CMD_FAIL;
			if (status & BIT(0))
				return SDW_CMD_OK;
		}

		/* Slave writes are intentionally fire-and-forget in the clean path.
		 * Their wire-level FIFO status is stale on this bridge, so successful
		 * submission of CMD_FIFO_WR_CMD is sufficient here as well.
		 */
		if (reg == ctrl->reg_layout[SWRM_REG_CMD_FIFO_WR_CMD])
			return SDW_CMD_OK;

		return SDW_CMD_FAIL;
	}

	/* pg register + offset */
	ret = regmap_bulk_write(wcd_regmap, SWRM_AHB_BRIDGE_WR_DATA_0,
			  (u8 *)&val, 4);
	if (ret)
		return SDW_CMD_FAIL;

	/* write address register */
	ret = regmap_bulk_write(wcd_regmap, SWRM_AHB_BRIDGE_WR_ADDR_0,
			  (u8 *)&reg, 4);
	if (ret)
		return SDW_CMD_FAIL;

	return SDW_CMD_OK;
}

static int qcom_swrm_ahb_reg_write(struct qcom_swrm_ctrl *ctrl,
				   int reg, int val)
{
	int ret;

	mutex_lock(&ctrl->ahb_lock);
	ret = __qcom_swrm_ahb_reg_write(ctrl, reg, val);
	mutex_unlock(&ctrl->ahb_lock);

	return ret;
}

static int qcom_swrm_cpu_reg_read(struct qcom_swrm_ctrl *ctrl, int reg,
				  u32 *val)
{
	*val = readl(ctrl->mmio + reg);
	return SDW_CMD_OK;
}

static int qcom_swrm_cpu_reg_write(struct qcom_swrm_ctrl *ctrl, int reg,
				   int val)
{
	writel(val, ctrl->mmio + reg);
	return SDW_CMD_OK;
}

static u32 swrm_get_packed_reg_val(u8 *cmd_id, u8 cmd_data,
				   u8 dev_addr, u16 reg_addr)
{
	u32 val;
	u8 id = *cmd_id;

	if (id != SWR_BROADCAST_CMD_ID) {
		if (id < SWR_MAX_CMD_ID)
			id += 1;
		else
			id = 0;
		*cmd_id = id;
	}
	val = SWRM_REG_VAL_PACK(cmd_data, dev_addr, id, reg_addr);

	return val;
}

static int swrm_wait_for_rd_fifo_avail(struct qcom_swrm_ctrl *ctrl)
{
	u32 fifo_outstanding_data, value;
	int fifo_retry_count = SWR_OVERFLOW_RETRY_COUNT;

	do {
		/* Check for fifo underflow during read */
		ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_CMD_FIFO_STATUS],
			       &value);
		fifo_outstanding_data = FIELD_GET(SWRM_RD_CMD_FIFO_CNT_MASK, value);

		/* Check if read data is available in read fifo */
		if (fifo_outstanding_data > 0)
			return 0;

		usleep_range(500, 510);
	} while (fifo_retry_count--);

	if (fifo_outstanding_data == 0) {
		dev_err_ratelimited(ctrl->dev, "%s err read underflow\n", __func__);
		return -EIO;
	}

	return 0;
}

static int swrm_wait_for_wr_fifo_avail(struct qcom_swrm_ctrl *ctrl)
{
	u32 fifo_outstanding_cmds, value;
	int fifo_retry_count = SWR_OVERFLOW_RETRY_COUNT;

	do {
		/* Check for fifo overflow during write */
		ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_CMD_FIFO_STATUS],
			       &value);
		fifo_outstanding_cmds = FIELD_GET(SWRM_WR_CMD_FIFO_CNT_MASK, value);

		/* Check for space in write fifo before writing */
		if (fifo_outstanding_cmds < ctrl->wr_fifo_depth)
			return 0;

		usleep_range(500, 510);
	} while (fifo_retry_count--);

	if (fifo_outstanding_cmds == ctrl->wr_fifo_depth) {
		dev_err_ratelimited(ctrl->dev, "%s err write overflow\n", __func__);
		return -EIO;
	}

	return 0;
}

static bool swrm_wait_for_wr_fifo_done(struct qcom_swrm_ctrl *ctrl)
{
	u32 fifo_outstanding_cmds, value;
	int fifo_retry_count = SWR_OVERFLOW_RETRY_COUNT;

	/* Check for fifo overflow during write */
	ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_CMD_FIFO_STATUS], &value);
	fifo_outstanding_cmds = FIELD_GET(SWRM_WR_CMD_FIFO_CNT_MASK, value);

	if (fifo_outstanding_cmds) {
		while (fifo_retry_count) {
			usleep_range(500, 510);
			ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_CMD_FIFO_STATUS], &value);
			fifo_outstanding_cmds = FIELD_GET(SWRM_WR_CMD_FIFO_CNT_MASK, value);
			fifo_retry_count--;
			if (fifo_outstanding_cmds == 0)
				return true;
		}
	} else {
		return true;
	}


	return false;
}

static int qcom_swrm_cmd_fifo_wr_cmd(struct qcom_swrm_ctrl *ctrl, u8 cmd_data,
				     u8 dev_addr, u16 reg_addr)
{

	u32 val;
	int ret = 0;
	u8 cmd_id = 0x0;
	u8 target = dev_addr;

	/* Leave SCP addressing and synchronized frame switches untouched. Ordinary
	 * codec/DP broadcasts retain their ordinary FIFO tag; only the existing
	 * explicit broadcast path requests synchronized-command completion.
	 */
	if ((ctrl->spx_windows_init || spx_forced_attached) &&
	    spx_broadcast_audio && dev_addr <= 2 &&
	    ((reg_addr >= 0x100 && reg_addr < 0xf00) ||
	     (reg_addr >= 0x3000 && reg_addr <= 0x36ff)))
		target = SDW_BROADCAST_DEV_NUM;

	if (dev_addr == SDW_BROADCAST_DEV_NUM) {
		cmd_id = SWR_BROADCAST_CMD_ID;
		val = swrm_get_packed_reg_val(&cmd_id, cmd_data,
					      dev_addr, reg_addr);
	} else {
		val = swrm_get_packed_reg_val(&ctrl->wcmd_id, cmd_data,
					      target, reg_addr);
	}

	/* SPX accesses this master through the WCD9340 SLIMbus bridge.  Its
	 * write-FIFO count is stale/unreliable (often permanently reports full),
	 * although the command register remains usable.  Serialize blind writes
	 * with a flush and enough bridge settle time instead of rejecting DAPM
	 * power writes based on that count.
	 */
	if (ctrl->spx_windows_init || spx_core_enum) {
		ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CMD, SWRM_CMD_FIFO_FLUSH);
		usleep_range(500, 550);
	} else if (swrm_wait_for_wr_fifo_avail(ctrl)) {
		return SDW_CMD_FAIL_OTHER;
	}

	if (cmd_id == SWR_BROADCAST_CMD_ID)
		reinit_completion(&ctrl->broadcast);

	/* Its assumed that write is okay as we do not get any status back */
	ctrl->reg_write(ctrl, ctrl->reg_layout[SWRM_REG_CMD_FIFO_WR_CMD], val);
	if (ctrl->spx_windows_init || spx_core_enum) {
		usleep_range(1200, 1300);
	}

	if (ctrl->version <= SWRM_VERSION_1_3_0)
		usleep_range(150, 155);

	if (cmd_id == SWR_BROADCAST_CMD_ID) {
		swrm_wait_for_wr_fifo_done(ctrl);
		/*
		 * sleep for 10ms for MSM soundwire variant to allow broadcast
		 * command to complete.
		 */
		ret = wait_for_completion_timeout(&ctrl->broadcast,
						  msecs_to_jiffies(TIMEOUT_MS));
		if (!ret)
			ret = SDW_CMD_IGNORED;
		else
			ret = SDW_CMD_OK;

	} else {
		ret = SDW_CMD_OK;
	}
	return ret;
}

static int qcom_swrm_cmd_fifo_rd_cmd(struct qcom_swrm_ctrl *ctrl,
				     u8 dev_addr, u16 reg_addr,
				     u32 len, u8 *rval)
{
	u32 cmd_data, cmd_id, val, retry_attempt = 0;

	val = swrm_get_packed_reg_val(&ctrl->rcmd_id, len, dev_addr, reg_addr);

	/*
	 * Check for outstanding cmd wrt. write fifo depth to avoid
	 * overflow as read will also increase write fifo cnt.
	 */
	swrm_wait_for_wr_fifo_avail(ctrl);

	/*
	 * SPX (no-IRQ, SLIMbus-bridged master): a stale entry left in the read
	 * FIFO from a prior single-byte read corrupts the next read (every other
	 * byte of a multi-byte DevID read drops to 0). Flush for a clean slate
	 * and give the slow AHB-over-SLIMbus path extra settle so the response
	 * is latched before we poll the FIFO count.
	 */
	if (ctrl->spx_windows_init || spx_core_enum) {
		ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CMD, SWRM_CMD_FIFO_FLUSH);
		usleep_range(500, 550);
	}

	/* wait for FIFO RD to complete to avoid overflow */
	usleep_range(100, 105);
	ctrl->reg_write(ctrl, ctrl->reg_layout[SWRM_REG_CMD_FIFO_RD_CMD], val);
	/* wait for FIFO RD CMD complete to avoid overflow */
	usleep_range(250, 255);
	if (ctrl->spx_windows_init || spx_core_enum)
		usleep_range(700, 750);

	if (swrm_wait_for_rd_fifo_avail(ctrl))
		return SDW_CMD_FAIL_OTHER;

	do {
		ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_CMD_FIFO_RD_FIFO_ADDR],
			       &cmd_data);
		rval[0] = cmd_data & 0xFF;
		cmd_id = FIELD_GET(SWRM_RD_FIFO_CMD_ID_MASK, cmd_data);

		if (cmd_id != ctrl->rcmd_id) {
			if (retry_attempt < (MAX_FIFO_RD_RETRY - 1)) {
				/* wait 500 us before retry on fifo read failure */
				usleep_range(500, 505);
				ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CMD,
						SWRM_CMD_FIFO_FLUSH);
				ctrl->reg_write(ctrl,
						ctrl->reg_layout[SWRM_REG_CMD_FIFO_RD_CMD],
						val);
			}
			retry_attempt++;
		} else {
			return SDW_CMD_OK;
		}

	} while (retry_attempt < MAX_FIFO_RD_RETRY);

	dev_err(ctrl->dev, "failed to read fifo: reg: 0x%x, rcmd_id: 0x%x,\
		dev_num: 0x%x, cmd_data: 0x%x\n",
		reg_addr, ctrl->rcmd_id, dev_addr, cmd_data);

	return SDW_CMD_IGNORED;
}

static int qcom_swrm_get_alert_slave_dev_num(struct qcom_swrm_ctrl *ctrl)
{
	u32 val, status;
	int dev_num;

	ctrl->reg_read(ctrl, SWRM_MCP_SLV_STATUS, &val);

	for (dev_num = 1; dev_num <= SDW_MAX_DEVICES; dev_num++) {
		status = (val >> (dev_num * SWRM_MCP_SLV_STATUS_SZ));

		if ((status & SWRM_MCP_SLV_STATUS_MASK) == SDW_SLAVE_ALERT) {
			ctrl->status[dev_num] = status & SWRM_MCP_SLV_STATUS_MASK;
			return dev_num;
		}
	}

	return -EINVAL;
}

static void qcom_swrm_get_device_status(struct qcom_swrm_ctrl *ctrl)
{
	u32 val;
	int i;

	ctrl->reg_read(ctrl, SWRM_MCP_SLV_STATUS, &val);
	ctrl->slave_status = val;

	for (i = 1; i <= SDW_MAX_DEVICES; i++) {
		u32 s;

		s = (val >> (i * 2));
		s &= SWRM_MCP_SLV_STATUS_MASK;
		ctrl->status[i] = s;
	}

	/*
	 * SPX: when force-attaching the WSA881x, the hardware status will read
	 * UNATTACHED because the shared-pin amps clash and the DevNumber write
	 * cannot be verified. Keep device 1 reported as ATTACHED so the core
	 * leaves the slave bound and the write-only stream path can be tested.
	 */
	if (spx_force_attach || spx_forced_attached)
		ctrl->status[1] = SDW_SLAVE_ATTACHED;
}

static void qcom_swrm_set_slave_dev_num(struct sdw_bus *bus,
					struct sdw_slave *slave, int devnum)
{
	struct qcom_swrm_ctrl *ctrl = to_qcom_sdw(bus);
	u32 status;

	/*
	 * qcauddev8180 maps the enumerator table from the single slave-status
	 * snapshot which triggered its worker. Re-reading the physical status
	 * here creates a race: a brief valid assignment can disappear before
	 * Linux records the device number, leaving the DT slave permanently at
	 * enumeration address 0.
	 */
	if (ctrl->spx_windows_init) {
		status = ctrl->status[devnum];
	} else {
		ctrl->reg_read(ctrl, SWRM_MCP_SLV_STATUS, &status);
		status = (status >> (devnum * SWRM_MCP_SLV_STATUS_SZ));
		status &= SWRM_MCP_SLV_STATUS_MASK;
	}

	if (status == SDW_SLAVE_ATTACHED) {
		if (slave)
			slave->dev_num = devnum;
		mutex_lock(&bus->bus_lock);
		set_bit(devnum, bus->assigned);
		mutex_unlock(&bus->bus_lock);
		if (ctrl->spx_windows_init)
			dev_info(ctrl->dev,
				 "SPX: mapped SoundWire slave %d from status snapshot\n",
				 devnum);
	}
}

static int qcom_swrm_enumerate(struct sdw_bus *bus)
{
	struct qcom_swrm_ctrl *ctrl = to_qcom_sdw(bus);
	struct sdw_slave *slave, *_s;
	struct sdw_slave_id id;
	u32 val1, val2;
	bool found;
	u64 addr;
	int i;
	char *buf1 = (char *)&val1, *buf2 = (char *)&val2;

	for (i = 1; i <= SDW_MAX_DEVICES; i++) {
		/* do not continue if the status is Not Present  */
		if (!ctrl->status[i])
			continue;

		/*SCP_Devid5 - Devid 4*/
		ctrl->reg_read(ctrl, SWRM_ENUMERATOR_SLAVE_DEV_ID_1(i), &val1);

		/*SCP_Devid3 - DevId 2 Devid 1 Devid 0*/
		ctrl->reg_read(ctrl, SWRM_ENUMERATOR_SLAVE_DEV_ID_2(i), &val2);

		if (!val1 && !val2) {
			if (ctrl->spx_windows_init)
				continue;
			break;
		}

		addr = buf2[1] | (buf2[0] << 8) | (buf1[3] << 16) |
			((u64)buf1[2] << 24) | ((u64)buf1[1] << 32) |
			((u64)buf1[0] << 40);

		sdw_extract_slave_id(bus, addr, &id);
		found = false;
		ctrl->clock_stop_not_supported = false;
		/* Now compare with entries */
		list_for_each_entry_safe(slave, _s, &bus->slaves, node) {
			if (sdw_compare_devid(slave, id) == 0) {
				qcom_swrm_set_slave_dev_num(bus, slave, i);
				if (slave->prop.clk_stop_mode1)
					ctrl->clock_stop_not_supported = true;

				found = true;
				break;
			}
		}

		if (!found) {
			/* SPX DevID reads are electrically contended and frequently
			 * contain mixed bytes from both amplifiers. Never instantiate
			 * those transient IDs; the two real WSA881x devices are declared
			 * by DT and the validated force-attach path binds them.
			 */
			if (spx_core_enum) {
				dev_dbg(ctrl->dev,
					"SPX: ignoring unknown enumerator ID %04x:%04x\n",
					id.mfg_id, id.part_id);
				continue;
			}
			qcom_swrm_set_slave_dev_num(bus, NULL, i);
			sdw_slave_add(bus, &id, NULL);
		}
	}

	complete(&ctrl->enumeration);
	return 0;
}

static int qcom_swrm_init(struct qcom_swrm_ctrl *ctrl);
static bool swrm_wait_for_frame_gen_enabled(struct qcom_swrm_ctrl *ctrl);

/*
 * Re-read MCP_SLV_STATUS and record which address the amp is answering on.
 * Presence flickers to 0 between samples on this bus, so poll for a nonzero
 * status instead of latching a single flicker sample; if nothing ever shows,
 * mark the answer stale so the write path keeps re-sampling -- silently
 * keeping a guess here reroutes every write into the void for the whole boot.
 */
static int spx_no_assign = 1;
module_param(spx_no_assign, int, 0644);
MODULE_PARM_DESC(spx_no_assign,
		 "SPX: keep the amp unenumerated at device 0 (stable self-healing state)");

static void spx_refresh_amp_addr(struct qcom_swrm_ctrl *ctrl)
{
	u32 slv = 0;
	int try;
	bool dev0, dev1;

	/* No DevNumber write is issued in this mode, so device 0 is invariant. */
	if (spx_no_assign) {
		spx_amp_at_dev0 = true;
		spx_amp_addr_stale = false;
		return;
	}

	for (try = 0; try < 20; try++) {
		if (ctrl->reg_read(ctrl, SWRM_MCP_SLV_STATUS, &slv))
			slv = 0;
		if (slv)
			break;
		usleep_range(10000, 11000);
	}

	/* Accept only an unambiguous single-address sample. */
	dev1 = (slv >> 2) & SWRM_MCP_SLV_STATUS_MASK;
	dev0 = slv & SWRM_MCP_SLV_STATUS_MASK;
	if (dev1 && !dev0) {
		spx_amp_at_dev0 = false;
		spx_amp_addr_stale = false;
	} else if (dev0 && !dev1) {
		spx_amp_at_dev0 = true;
		spx_amp_addr_stale = false;
	} else {
		/* Preserve the last route on empty, contended or garbled reads. */
		spx_amp_addr_stale = true;
		dev_warn(ctrl->dev,
			 "SPX: ambiguous slave status 0x%x after %d polls; preserving device %d route\n",
			 slv, try, spx_amp_at_dev0 ? 0 : 1);
	}

	dev_info(ctrl->dev, "SPX: slv_status=0x%x -> writes go to device %d%s\n",
		 slv, spx_amp_at_dev0 ? 0 : 1,
		 spx_amp_addr_stale ? " (stale)" : "");
}

/*
 * SPX amp-presence watchdog. The WSA amp intermittently drops off the bus
 * (sync loss); once gone it does not return on its own, and every write to it
 * silently vanishes. The one reliable revival is a long SD_N power-cycle.
 * Poll MCP_SLV_STATUS; when the amp disappears, power-cycle it via the WCD
 * GPIO (the bridge regmap IS the codec regmap) and refresh write routing.
 * Never SW_RESET here: resetting a bus with a live amp kicks the amp off.
 */
static int spx_watchdog;
module_param(spx_watchdog, int, 0644);
MODULE_PARM_DESC(spx_watchdog, "SPX: auto power-cycle the amp when it drops off the bus");
static int spx_wd_amp_mask = 0x02;
module_param(spx_wd_amp_mask, int, 0644);
MODULE_PARM_DESC(spx_wd_amp_mask,
		 "SPX: WCD GPIO VAL bits of the active amp's SD_N (physical high=on)");
static int spx_wd_off_ms = 10000;
module_param(spx_wd_off_ms, int, 0644);
MODULE_PARM_DESC(spx_wd_off_ms, "SPX: how long to hold the amp powered off (2s is not enough)");
static int spx_wd_miss_limit = 3;
module_param(spx_wd_miss_limit, int, 0644);
MODULE_PARM_DESC(spx_wd_miss_limit,
		 "SPX: consecutive empty slave-status polls required before an amp power-cycle");
static void spx_latch_from_slv(struct qcom_swrm_ctrl *ctrl, u32 slv)
{
	bool dev0 = slv & SWRM_MCP_SLV_STATUS_MASK;
	bool dev1 = (slv >> 2) & SWRM_MCP_SLV_STATUS_MASK;
	bool at_dev0;

	if (spx_no_assign)
		at_dev0 = true;
	else {
		if (dev0 == dev1) {
			spx_amp_addr_stale = true;
			dev_warn(ctrl->dev,
				 "SPX wd: ambiguous slv_status=0x%x; preserving route\n",
				 slv);
			return;
		}
		at_dev0 = dev0;
	}

	if (spx_amp_addr_stale || at_dev0 != spx_amp_at_dev0)
		dev_info(ctrl->dev,
			 "SPX wd: slv_status=0x%x -> writes go to device %d\n",
			 slv, at_dev0 ? 0 : 1);
	spx_amp_at_dev0 = at_dev0;
	spx_amp_addr_stale = false;
}

static void spx_wd_work_fn(struct work_struct *work)
{
	struct qcom_swrm_ctrl *ctrl = container_of(work, struct qcom_swrm_ctrl,
						   spx_wd_work.work);
	unsigned int delay = 2000;
	u32 slv = 0;

	if (READ_ONCE(ctrl->spx_stopping) || !spx_watchdog)
		return;
	if (!spx_forced_attached) {
		delay = 5000;
		goto rearm;
	}

	switch (ctrl->spx_wd_state) {
	case 0:	/* monitor */
		if (ctrl->reg_read(ctrl, SWRM_MCP_SLV_STATUS, &slv))
			slv = 0;
		if (slv) {
			spx_latch_from_slv(ctrl, slv);
			ctrl->spx_wd_misses = 0;
			ctrl->spx_wd_fails = 0;
			break;
		}
		ctrl->spx_wd_misses++;
		if (ctrl->spx_wd_misses < max(spx_wd_miss_limit, 1)) {
			dev_dbg(ctrl->dev,
				"SPX wd: empty slave status %d/%d; waiting before recovery\n",
				ctrl->spx_wd_misses, max(spx_wd_miss_limit, 1));
			delay = 1000;
			break;
		}
		ctrl->spx_wd_misses = 0;
		if (ctrl->spx_wd_fails >= 3) {
			delay = 30000;	/* keep watching, quietly */
			break;
		}
		dev_warn(ctrl->dev,
			 "SPX wd: amp gone (try %d), power-cycling SD_N for %d ms\n",
			 ctrl->spx_wd_fails + 1, spx_wd_off_ms);
		regmap_update_bits(ctrl->regmap, WCD934X_GPIO_DIR_CTL, 0x06, 0x06);
		regmap_update_bits(ctrl->regmap, WCD934X_GPIO_VAL_CTL,
				   spx_wd_amp_mask, 0);
		ctrl->spx_wd_state = 1;
		delay = spx_wd_off_ms;
		break;
	case 1:	/* power the amp back on, then re-run the attach recipe --
		 * a plain SD_N cycle alone never makes it announce. */
		if (READ_ONCE(ctrl->spx_stopping))
			return;
		regmap_update_bits(ctrl->regmap, WCD934X_GPIO_VAL_CTL,
				   spx_wd_amp_mask, spx_wd_amp_mask);
		spx_force_attach = 1;
		mod_delayed_work(system_wq, &ctrl->spx_enum_work,
				 msecs_to_jiffies(500));
		ctrl->spx_wd_state = 2;
		delay = 4000;
		break;
	case 2:	/* did it come back? */
		if (ctrl->reg_read(ctrl, SWRM_MCP_SLV_STATUS, &slv))
			slv = 0;
		if (slv) {
			dev_info(ctrl->dev, "SPX wd: amp revived (slv=0x%x)\n", slv);
			spx_latch_from_slv(ctrl, slv);
			ctrl->spx_wd_misses = 0;
			ctrl->spx_wd_fails = 0;
		} else {
			ctrl->spx_wd_fails++;
			dev_warn(ctrl->dev,
				 "SPX wd: revival attempt %d failed\n",
				 ctrl->spx_wd_fails);
		}
		ctrl->spx_wd_state = 0;
		break;
	}
rearm:
	if (!READ_ONCE(ctrl->spx_stopping))
		schedule_delayed_work(&ctrl->spx_wd_work,
				      msecs_to_jiffies(delay));
}

/*
 * SPX: the wcd934x internal SoundWire master has no usable IRQ, so the normal
 * IRQ-driven enumeration never runs and the WSA881x amps stay UNATTACHED. Worse,
 * the HW auto-enumerator in qcom_swrm_init() ran at master probe -- BEFORE
 * wsa881x powers the amps (wsa881x probes after this master) -- so it scanned an
 * unpowered bus and latched a garbage DevID, and never rescans.
 *
 * Fix (gated on spx_core_enum): from this workqueue, after the amps are powered,
 * RE-RUN the auto-enum on a live bus: soft-reset the master + re-init (restarts
 * the bus clock so the now-powered slaves re-sync, and re-enables + re-triggers
 * the auto-enum scan), then read status / enumerate / hand to the core. Retry the
 * reset every few passes in case the first rescan still raced the amps, and poll
 * in between, until both expected slaves attach (or give up after ~6s).
 */
static void spx_swrm_enum_work(struct work_struct *work)
{
	struct qcom_swrm_ctrl *ctrl = container_of(work, struct qcom_swrm_ctrl,
						   spx_enum_work.work);

	if (READ_ONCE(ctrl->spx_stopping))
		return;

	dev_info(ctrl->dev,
		 "SPX enum work enter core_enum=%d force=%d diag_done=%d irq=%d\n",
		 spx_core_enum, spx_force_attach, ctrl->spx_diag_done, ctrl->irq);

	/*
	 * FORCE-ATTACH is independent of the DevID diag storm. Always take the
	 * short path first when requested: SW_RESET + init, program DevNumber,
	 * mark ATTACHED. The 40× DevID read path trashes the CMD FIFO.
	 */
	if (spx_force_attach) {
		static const u8 spx_wsa_id[] = {
			0x00, 0x02, 0x10, 0x00, 0x10, 0x00,
		};
		struct sdw_slave *slave;
		int dn = 1, k, i, rchk = 0;
		u8 chk[6];
		u32 comp = 0, ist = 0, rst;
		int attempt = ++ctrl->spx_enum_tries;

		ctrl->spx_diag_done = true;
		/*
		 * SPX: check if the frame-gen is already running BEFORE
		 * resetting. The initial probe state (COMP_STATUS=0x2a01)
		 * may have bus state that the SW_RESET destroys. If the
		 * frame-gen is already locked, skip the reset loop and go
		 * straight to the dev_num assignment.
		 */
		ctrl->reg_read(ctrl,
			ctrl->reg_layout[SWRM_REG_FRAME_GEN_ENABLED],
			&comp);
		if (!(comp & 1)) {
			for (rst = 0; rst < 8; rst++) {
				reinit_completion(&ctrl->enumeration);
				ctrl->reg_write(ctrl, SWRM_COMP_SW_RESET, 0x01);
				usleep_range(100, 105);
				spx_bus_up = false;
				qcom_swrm_init(ctrl);
				swrm_wait_for_frame_gen_enabled(ctrl);
				ctrl->reg_read(ctrl,
					ctrl->reg_layout[SWRM_REG_FRAME_GEN_ENABLED],
					&comp);
				if (comp & 1)
					break;
			}
		} else {
			rst = 0;
		}
		dev_info(ctrl->dev,
			 "SPX FORCE-ATTACH: after %u resets frame-gen=0x%x\n",
			 rst, comp);
		ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 0);
		/*
		 * SPX: mask ALL SWR interrupts during force-attach. The
		 * qcom_swrm_init() above unmasks everything, so with an IRQ
		 * the ISR fires on every bus event and corrupts the CMD FIFO
		 * mid-sequence. Disable until attach completes.
		 */
		if (ctrl->irq > 0) {
			ctrl->reg_write(ctrl,
				ctrl->reg_layout[SWRM_REG_INTERRUPT_CPU_EN], 0);
			ctrl->reg_write(ctrl,
				ctrl->reg_layout[SWRM_REG_INTERRUPT_MASK_ADDR], 0);
		}
		ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_STATUS],
			       &ist);
		if (ist)
			ctrl->reg_write(ctrl,
					ctrl->reg_layout[SWRM_REG_INTERRUPT_CLEAR],
					ist);
		ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CMD, SWRM_CMD_FIFO_FLUSH);
		usleep_range(500, 550);

		/*
		 * Leaving the amp UNENUMERATED at device 0 is the stable,
		 * self-healing configuration: after any bus desync it
		 * re-announces at device 0 where the write rewrite still
		 * reaches it, and playback there produces the real tone. An
		 * enumerated device-1 amp is fragile -- one desync (stream
		 * start is enough) and it is permanently deaf until a full
		 * power-cycle + attach recipe. So skip the DevNumber
		 * assignment by default (spx_no_assign=0 restores it).
		 */
		if (spx_no_assign) {
			dev_info(ctrl->dev,
				 "SPX FORCE-ATTACH: leaving amp unenumerated at device 0\n");
		} else {
			for (k = 0; k < 8; k++) {
				qcom_swrm_cmd_fifo_wr_cmd(ctrl, dn, 0, SDW_SCP_DEVNUMBER);
				usleep_range(1500, 1600);
			}
			for (i = 0; i < ARRAY_SIZE(chk); i++) {
				u8 b = 0xaa;

				rchk |= qcom_swrm_cmd_fifo_rd_cmd(ctrl, dn,
								  SDW_SCP_DEVID_0 + i, 1,
								  &b);
				chk[i] = b;
			}
			dev_info(ctrl->dev,
				 "SPX FORCE-ATTACH verify dev%d rc=%d id=%02x %02x %02x %02x %02x %02x\n",
				 dn, rchk, chk[0], chk[1], chk[2], chk[3], chk[4],
				 chk[5]);
		}

		/* Version and unique-ID bytes collide independently. Require the
		 * stable manufacturer/product core before binding the logical slave.
		 * In blind mode, skip verification entirely -- writes are
		 * fire-and-forget and may succeed even when reads clash.
		 */
		if (!spx_no_assign && !spx_blind_attach &&
		    memcmp(&chk[1], &spx_wsa_id[1], 4)) {
			dev_warn(ctrl->dev,
				 "SPX FORCE-ATTACH: assignment not verified on attempt %d/64\n",
				 attempt);
			ctrl->spx_diag_done = false;
			if (attempt < 64 && !READ_ONCE(ctrl->spx_stopping))
				mod_delayed_work(system_wq, &ctrl->spx_enum_work,
						 msecs_to_jiffies(500));
			else
				dev_err(ctrl->dev,
					"SPX FORCE-ATTACH: assignment failed after 64 attempts\n");
			return;
		}
		ctrl->spx_enum_tries = 0;

		memset(ctrl->status, 0, sizeof(ctrl->status));
		ctrl->status[dn] = SDW_SLAVE_ATTACHED;
		list_for_each_entry(slave, &ctrl->bus.slaves, node) {
			if (slave->id.part_id != 0x2010 ||
			    slave->id.mfg_id != 0x0217)
				continue;
			/* skip OF-disabled nodes */
			if (!slave->dev.of_node ||
			    !of_device_is_available(slave->dev.of_node)) {
				dev_info(ctrl->dev,
					 "SPX FORCE-ATTACH skip disabled %s\n",
					 dev_name(&slave->dev));
				continue;
			}
			slave->dev_num = dn;
			mutex_lock(&ctrl->bus.bus_lock);
			set_bit(dn, ctrl->bus.assigned);
			mutex_unlock(&ctrl->bus.bus_lock);
			dev_info(ctrl->dev,
				 "SPX FORCE-ATTACH: %s -> dev_num %d\n",
				 dev_name(&slave->dev), dn);
		}
		/* Keep the forced logical attachment stable before the status
		 * notification invokes wsa881x_init(). Device routing remains a
		 * runtime option; SPX requires logical device 1 during codec init.
		 */
		spx_forced_attached = true;
		spx_force_attach = 0;
		/*
		 * The shared-address amplifiers continue raising clash and command
		 * errors after their logical address is established.  Unicast codec
		 * writes are fire-and-forget, but the IRQ handler used to flush the
		 * command FIFO for those errors while wsa881x_init() was still
		 * programming the amplifier.  Keep only broadcast completion, which
		 * is the sole interrupt required by the transfer path after attach.
		 */
		ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 0);
		ctrl->intr_mask = SWRM_INTERRUPT_STATUS_SPECIAL_CMD_ID_FINISHED;
		ctrl->reg_write(ctrl,
				ctrl->reg_layout[SWRM_REG_INTERRUPT_CLEAR],
				0xffffffff);
		if (ctrl->irq > 0)
			ctrl->reg_write(ctrl,
					ctrl->reg_layout[SWRM_REG_INTERRUPT_CPU_EN],
					ctrl->intr_mask);
		dev_info(ctrl->dev,
			 "SPX FORCE-ATTACH: stable attachment, write_dev0=%d intr_mask=0x%x\n",
			 spx_write_dev0, ctrl->intr_mask);
		/* Learn the amp's real address before wsa881x_init() writes to it. */
		spx_refresh_amp_addr(ctrl);
		sdw_handle_slave_status(&ctrl->bus, ctrl->status);
		/*
		 * Keep the master clocking: a runtime clock-stop suspend
		 * desyncs the force-attached amp (it never comes back on
		 * resume), and a suspended master makes the watchdog's
		 * presence reads meaningless. One reference, dropped in
		 * remove().
		 */
		if (!spx_pm_held) {
			spx_pm_held = true;
			pm_runtime_get_noresume(ctrl->dev);
		}
		/* From here the watchdog owns amp presence and write routing. */
		ctrl->spx_wd_state = 0;
		ctrl->spx_wd_fails = 0;
		ctrl->spx_wd_misses = 0;
		if (spx_watchdog && !READ_ONCE(ctrl->spx_stopping))
			schedule_delayed_work(&ctrl->spx_wd_work,
					      msecs_to_jiffies(2000));
		return;
	}

	/*
	 * Once terminally force-attached, the poll/diag below must never run:
	 * its SW_RESET + init storm and per-pass wsa881x_init replay wreck a
	 * live bus. Re-triggering recovery requires spx_force_attach=1 first,
	 * which takes the fast path above.
	 */
	if (spx_forced_attached)
		return;

	/*
	 * SPX: frame-gen lock is nondeterministic boot-to-boot, and the diag
	 * below is gated on device-0 presence, which needs the lock -- so a
	 * bad-lock boot used to be a wasted reboot. If frame-gen is down,
	 * re-run the full SW_RESET + init (which re-sweeps frame_phase) right
	 * here, so writing spx_reenum retries the lock without rebooting.
	 */
	if (spx_core_enum) {
		u32 comp = 0;

		ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_FRAME_GEN_ENABLED],
			       &comp);
		if (!(comp & 0x1)) {
			dev_info(ctrl->dev,
				 "SPX: frame-gen down (comp=0x%x), SW_RESET + re-init sweep\n",
				 comp);
			reinit_completion(&ctrl->enumeration);
			ctrl->reg_write(ctrl, SWRM_COMP_SW_RESET, 0x01);
			usleep_range(100, 105);
			qcom_swrm_init(ctrl);
			swrm_wait_for_frame_gen_enabled(ctrl);
		}
	}

	/*
	 * SPX one-shot decisive probe (the HW auto-enum's DevID read underflows
	 * with AUTO_ENUM_FAILED). Read the WSA SCP DevID DIRECTLY at device 0 and
	 * log the raw bytes to settle whether the slave returns ANY data; then
	 * break the enumeration chicken-and-egg by FORCE-writing a device number
	 * (a write needs no slave echo) and re-reading the DevID at that number.
	 */
	if (spx_core_enum && !ctrl->spx_diag_done) {
		{
			u8 id[6];
			u32 ist = 0;
			int i, r0 = 0, tries, mfg = 0, part = 0;
			u32 comp = 0, rst;

			ctrl->spx_diag_done = true;

			/*
			 * The amp asserts device-0 presence only briefly after a bus
			 * reset, and the read needs frame-gen locked -- both hold at
			 * once ONLY right after a reset that happens to lock. Loop
			 * reset+init until frame-gen locks, then read immediately in
			 * that fresh window (do NOT gate on a presence sample, which
			 * flickers to 0 between polls).
			 */
			for (rst = 0; rst < 12; rst++) {
				reinit_completion(&ctrl->enumeration);
				ctrl->reg_write(ctrl, SWRM_COMP_SW_RESET, 0x01);
				usleep_range(100, 105);
				qcom_swrm_init(ctrl);
				swrm_wait_for_frame_gen_enabled(ctrl);
				ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_FRAME_GEN_ENABLED], &comp);
				if (comp & 1)
					break;
			}
			qcom_swrm_get_device_status(ctrl);
			dev_info(ctrl->dev,
				 "SPX DIAG: %u resets, frame-gen comp=0x%x slv=0x%x\n",
				 rst, comp, ctrl->slave_status);
			ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 0);
			ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_STATUS], &ist);
			ctrl->reg_write(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_CLEAR], ist);
			ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CMD, SWRM_CMD_FIFO_FLUSH);
			usleep_range(500, 550);

			if (spx_diag_reg >= 0) {
				/*
				 * Live harness: isolate ONE register. Read
				 * spx_diag_reg at device spx_diag_dev, spx_diag_count
				 * times, logging each value -- to see whether a single
				 * read is reliable on its own (vs inside the 6-byte
				 * sequence). Re-trigger via spx_reenum after toggling pins.
				 */
				int n;

				for (n = 0; n < spx_diag_count; n++) {
					u8 b = 0xAA;
					int rc = qcom_swrm_cmd_fifo_rd_cmd(ctrl,
							spx_diag_dev, spx_diag_reg, 1, &b);

					dev_info(ctrl->dev,
						"SPX DIAG1 dev%d reg=0x%02x n=%d rc=%d val=0x%02x\n",
						spx_diag_dev, spx_diag_reg, n, rc, b);
					usleep_range(3000, 3200);
				}
			} else {
				/*
				 * Read the device-0 DevID, RETRYING the whole 6-byte
				 * read until a valid WSA881x signature (mfg 0217 /
				 * part 2010) appears, logging every attempt.
				 */
				for (tries = 0; tries < 40; tries++) {
					u32 e1 = 0, e2 = 0, slv = 0;

					/* clear latched CMD_ERROR/underflow so a wedged
					 * FIFO doesn't fail every subsequent read */
					ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_STATUS], &ist);
					if (ist)
						ctrl->reg_write(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_CLEAR], ist);
					ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CMD, SWRM_CMD_FIFO_FLUSH);

					r0 = 0;
					for (i = 0; i < 6; i++) {
						u8 b = 0xAA;

						r0 |= qcom_swrm_cmd_fifo_rd_cmd(ctrl, 0,
									SDW_SCP_DEVID_0 + i, 1, &b);
						id[i] = b;
					}
					mfg = (id[1] << 8) | id[2];
					part = (id[3] << 8) | id[4];
					/* snapshot presence + what the HW auto-enum captured */
					ctrl->reg_read(ctrl, SWRM_MCP_SLV_STATUS, &slv);
					ctrl->reg_read(ctrl, SWRM_ENUMERATOR_SLAVE_DEV_ID_1(1), &e1);
					ctrl->reg_read(ctrl, SWRM_ENUMERATOR_SLAVE_DEV_ID_2(1), &e2);
					dev_info(ctrl->dev,
						"SPX DIAG dev0 try %d rc=%d id=%02x %02x %02x %02x %02x %02x mfg=%04x part=%04x slv=0x%x enum1=0x%x enum2=0x%x ist=0x%x\n",
						tries, r0, id[0], id[1], id[2], id[3], id[4], id[5],
						mfg, part, slv, e1, e2, ist);
					if (mfg == 0x0217 && part == 0x2010)
						break;
					usleep_range(2000, 2100);
				}
				dev_info(ctrl->dev,
					"SPX DIAG dev0 FINAL mfg=%04x part=%04x => %s (int_sts=0x%x)\n",
					mfg, part,
					(mfg == 0x0217 && part == 0x2010) ?
						"VALID WSA881x -- read is now reliable" :
						"still garbled", ist);
			}

			/* force_attach already handled in fast path above */

			ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 1);
		}
	}

	qcom_swrm_get_device_status(ctrl);
	spx_refresh_amp_addr(ctrl);
	qcom_swrm_enumerate(&ctrl->bus);
	sdw_handle_slave_status(&ctrl->bus, ctrl->status);
	dev_info(ctrl->dev,
		 "SPX enum poll #%d: slv_status=0x%x st[0]=%d st[1]=%d st[2]=%d\n",
		 ctrl->spx_enum_tries, ctrl->slave_status,
		 ctrl->status[0], ctrl->status[1], ctrl->status[2]);

	if ((ctrl->status[1] && ctrl->status[2]) || ++ctrl->spx_enum_tries > 24)
		return;
	if (!READ_ONCE(ctrl->spx_stopping))
		schedule_delayed_work(&ctrl->spx_enum_work,
				      msecs_to_jiffies(250));
}

/*
 * SPX live re-trigger: writing to soundwire_qcom.spx_reenum re-arms the diag
 * (spx_diag_done=0) and re-runs spx_swrm_enum_work on the live bus -- so the
 * WSA enable GPIOs can be toggled (gpioset) between runs without a reboot.
 */
static struct qcom_swrm_ctrl *spx_dbg_ctrl;
static DEFINE_MUTEX(spx_dbg_lock);

static int spx_frame_field_set(const char *val, const struct kernel_param *kp,
			       u32 mask, unsigned int shift)
{
	int ret;

	ret = param_set_int(val, kp);
	if (ret)
		return ret;
	if (*(int *)kp->arg < 0 || *(int *)kp->arg > (mask >> shift))
		return -EINVAL;

	/* Updating frame timing on a running SPX link poisons frame generation.
	 * Stage the value and apply it only from qcom_swrm_init(), after reset.
	 */
	return 0;
}

static int spx_ssp_period_set(const char *val, const struct kernel_param *kp)
{
	return spx_frame_field_set(val, kp, GENMASK(23, 16), 16);
}

static const struct kernel_param_ops spx_ssp_period_ops = {
	.set = spx_ssp_period_set,
	.get = param_get_int,
};
module_param_cb(spx_frame_phase, &spx_ssp_period_ops,
		&spx_frame_phase, 0444);
MODULE_PARM_DESC(spx_frame_phase,
		 "SPX MCP_FRAME_CTRL SSP_PERIOD[23:16] used to lock frame generation");

static int spx_runtime_ssp_period_set(const char *val,
				      const struct kernel_param *kp)
{
	int ret;

	ret = param_set_int(val, kp);
	if (ret)
		return ret;
	if (spx_runtime_ssp_period < 0 || spx_runtime_ssp_period > 0xff)
		return -EINVAL;

	return 0;
}

static const struct kernel_param_ops spx_runtime_ssp_period_ops = {
	.set = spx_runtime_ssp_period_set,
	.get = param_get_int,
};
module_param_cb(spx_runtime_ssp_period, &spx_runtime_ssp_period_ops,
		&spx_runtime_ssp_period, 0444);
MODULE_PARM_DESC(spx_runtime_ssp_period,
		 "SPX MCP_FRAME_CTRL SSP_PERIOD[23:16] used for audio bank switches");

static int spx_actual_phase;

static int spx_actual_phase_set(const char *val, const struct kernel_param *kp)
{
	return spx_frame_field_set(val, kp, GENMASK(15, 11), 11);
}

static const struct kernel_param_ops spx_actual_phase_ops = {
	.set = spx_actual_phase_set,
	.get = param_get_int,
};
module_param_cb(spx_actual_phase, &spx_actual_phase_ops,
		&spx_actual_phase, 0444);
MODULE_PARM_DESC(spx_actual_phase,
		 "SPX MCP_FRAME_CTRL PHASE[15:11], applied on re-init");

static int spx_clk_div;

static int spx_clk_div_set(const char *val, const struct kernel_param *kp)
{
	return spx_frame_field_set(val, kp, GENMASK(10, 8), 8);
}

static const struct kernel_param_ops spx_clk_div_ops = {
	.set = spx_clk_div_set,
	.get = param_get_int,
};
module_param_cb(spx_clk_div, &spx_clk_div_ops, &spx_clk_div, 0444);
MODULE_PARM_DESC(spx_clk_div,
		 "SPX MCP_FRAME_CTRL CLK_DIV[10:8], applied on re-init");

static int spx_reenum_set(const char *val, const struct kernel_param *kp)
{
	struct qcom_swrm_ctrl *ctrl;

	mutex_lock(&spx_dbg_lock);
	ctrl = spx_dbg_ctrl;
	if (ctrl && !ctrl->spx_stopping) {
		pr_info("soundwire_qcom: spx_reenum: schedule work (force=%d core_enum=%d)\n",
			spx_force_attach, spx_core_enum);
		ctrl->spx_diag_done = false;
		ctrl->spx_enum_tries = 0;
		schedule_delayed_work(&ctrl->spx_enum_work,
				      msecs_to_jiffies(10));
	} else {
		pr_warn("soundwire_qcom: spx_reenum: no ctrl (probe without spx_core_enum=1?)\n");
	}
	mutex_unlock(&spx_dbg_lock);
	return 0;
}

static const struct kernel_param_ops spx_reenum_ops = {
	.set = spx_reenum_set,
};
module_param_cb(spx_reenum, &spx_reenum_ops, NULL, 0200);
MODULE_PARM_DESC(spx_reenum, "SPX: write to re-run the diag/enum on the live bus");

/*
 * Serialize diagnostic register reads through the controller's own access
 * path. The old out-of-tree helper drove the shared WCD AHB bridge directly
 * and could race normal SoundWire traffic during the active-stream proof.
 */
static int spx_snapshot_set(const char *val, const struct kernel_param *kp)
{
	struct qcom_swrm_ctrl *ctrl;
	u32 comp, status, slv, dp1_b0, dp1_b1, dp4_b0, dp4_b1;
	int ret;

	mutex_lock(&spx_dbg_lock);
	ctrl = spx_dbg_ctrl;
	if (!ctrl || ctrl->spx_stopping) {
		ret = -ENODEV;
		goto out;
	}

	ret = ctrl->reg_read(ctrl, SWRM_COMP_PARAMS, &comp);
	if (ret)
		goto read_fail;
	ret = ctrl->reg_read(ctrl, SWRM_MCP_STATUS, &status);
	if (ret)
		goto read_fail;
	ret = ctrl->reg_read(ctrl, SWRM_MCP_SLV_STATUS, &slv);
	if (ret)
		goto read_fail;
	ret = ctrl->reg_read(ctrl, SWRM_DPn_PORT_CTRL_BANK(ctrl->reg_layout[SWRM_OFFSET_DP_PORT_CTRL_BANK], 1, 0), &dp1_b0);
	if (ret)
		goto read_fail;
	ret = ctrl->reg_read(ctrl, SWRM_DPn_PORT_CTRL_BANK(ctrl->reg_layout[SWRM_OFFSET_DP_PORT_CTRL_BANK], 1, 1), &dp1_b1);
	if (ret)
		goto read_fail;
	ret = ctrl->reg_read(ctrl, SWRM_DPn_PORT_CTRL_BANK(ctrl->reg_layout[SWRM_OFFSET_DP_PORT_CTRL_BANK], 4, 0), &dp4_b0);
	if (ret)
		goto read_fail;
	ret = ctrl->reg_read(ctrl, SWRM_DPn_PORT_CTRL_BANK(ctrl->reg_layout[SWRM_OFFSET_DP_PORT_CTRL_BANK], 4, 1), &dp4_b1);
	if (ret)
		goto read_fail;

	dev_info(ctrl->dev,
		 "SPX SNAPSHOT: COMP_PARAMS=0x%08x MCP_STATUS=0x%08x MCP_SLV_STATUS=0x%08x DP1_B0=0x%08x DP1_B1=0x%08x DP4_B0=0x%08x DP4_B1=0x%08x\n",
		 comp, status, slv, dp1_b0, dp1_b1, dp4_b0, dp4_b1);
	ret = 0;
	goto out;

read_fail:
	dev_err(ctrl->dev, "SPX SNAPSHOT: controller read failed: %d\n", ret);
	ret = -EIO;
out:
	mutex_unlock(&spx_dbg_lock);
	return ret;
}

static const struct kernel_param_ops spx_snapshot_ops = {
	.set = spx_snapshot_set,
};
module_param_cb(spx_snapshot, &spx_snapshot_ops, NULL, 0200);
MODULE_PARM_DESC(spx_snapshot,
		 "SPX: write to log a controller-serialized transport snapshot");

/*
 * Diagnostic-only physical-device readback. Force-attach represents the WSA
 * as logical device 1, but spx_write_dev0 deliberately sends its unicast
 * traffic to the still-unassigned physical address 0. Read that same address
 * directly after cold init so submitted writes are not mistaken for retained
 * amplifier state. This trigger never writes a codec register or enables PA.
 */
static int spx_slave_readback_set(const char *val,
				  const struct kernel_param *kp)
{
	struct qcom_swrm_ctrl *ctrl;
	u32 slv = 0, ist = 0;
	u8 temp[2] = { 0 }, psrr[2] = { 0 };
	int i, rc, ret = 0;

	mutex_lock(&spx_dbg_lock);
	ctrl = spx_dbg_ctrl;
	if (!ctrl || ctrl->spx_stopping) {
		ret = -ENODEV;
		goto out;
	}

	ctrl->reg_read(ctrl, SWRM_MCP_SLV_STATUS, &slv);
	if (!(slv & SWRM_MCP_SLV_STATUS_MASK)) {
		dev_warn(ctrl->dev,
			 "SPX SLAVE READBACK physical device 0 absent status=0x%08x\n",
			 slv);
		ret = -ENODEV;
		goto out;
	}
	ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_STATUS], &ist);
	dev_info(ctrl->dev,
		 "SPX SLAVE READBACK begin dev=0 slv_status=0x%08x int_status=0x%08x\n",
		 slv, ist);

	mutex_lock(&ctrl->bus.msg_lock);
	mutex_lock(&ctrl->controller_lock);
	for (i = 0; i < 2; i++) {
		rc = qcom_swrm_cmd_fifo_rd_cmd(ctrl, 0, 0x3103, 1,
					       &temp[i]);
		if (rc) {
			dev_warn(ctrl->dev,
				 "SPX SLAVE READBACK TEMP_OP pass=%d rc=%d UNOBSERVABLE\n",
				 i, rc);
			ret = -EIO;
			break;
		}
		rc = qcom_swrm_cmd_fifo_rd_cmd(ctrl, 0, 0x3127, 1,
					       &psrr[i]);
		if (rc) {
			dev_warn(ctrl->dev,
				 "SPX SLAVE READBACK BIAS_PSRR pass=%d rc=%d UNOBSERVABLE\n",
				 i, rc);
			ret = -EIO;
			break;
		}
	}
	mutex_unlock(&ctrl->controller_lock);
	mutex_unlock(&ctrl->bus.msg_lock);

	if (!ret)
		dev_info(ctrl->dev,
			 "SPX SLAVE READBACK dev=0 status=0x%08x TEMP_OP=0x%02x/0x%02x expected=0x0c BIAS_PSRR=0x%02x/0x%02x expected=0x45\n",
			 slv, temp[0], temp[1], psrr[0], psrr[1]);

	ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_STATUS], &ist);
	dev_info(ctrl->dev, "SPX SLAVE READBACK end int_status=0x%08x\n",
		 ist);
out:
	mutex_unlock(&spx_dbg_lock);
	return ret;
}

static const struct kernel_param_ops spx_slave_readback_ops = {
	.set = spx_slave_readback_set,
};
module_param_cb(spx_slave_readback, &spx_slave_readback_ops, NULL, 0200);
MODULE_PARM_DESC(spx_slave_readback,
		 "SPX: write to read a bounded cold-register signature from physical device 0");

static irqreturn_t qcom_swrm_wake_irq_handler(int irq, void *dev_id)
{
	struct qcom_swrm_ctrl *ctrl = dev_id;
	int ret;

	ret = pm_runtime_get_sync(ctrl->dev);
	if (ret < 0 && ret != -EACCES) {
		dev_err_ratelimited(ctrl->dev,
				    "pm_runtime_get_sync failed in %s, ret %d\n",
				    __func__, ret);
		pm_runtime_put_noidle(ctrl->dev);
		return ret;
	}

	if (ctrl->wake_irq > 0) {
		if (!irqd_irq_disabled(irq_get_irq_data(ctrl->wake_irq)))
			disable_irq_nosync(ctrl->wake_irq);
	}

	pm_runtime_mark_last_busy(ctrl->dev);
	pm_runtime_put_autosuspend(ctrl->dev);

	return IRQ_HANDLED;
}

static irqreturn_t qcom_swrm_irq_handler(int irq, void *dev_id)
{
	struct qcom_swrm_ctrl *ctrl = dev_id;
	u32 value, intr_sts, intr_sts_masked, slave_status;
	u32 i;
	int devnum;
	int ret = IRQ_HANDLED;
	/* Retry budget for the older opt-in SPX diagnostic path. */
	static int spx_clash_recover;
	clk_prepare_enable(ctrl->hclk);
	if (ctrl->spx_windows_init)
		mutex_lock(&ctrl->controller_lock);

	ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_STATUS],
		       &intr_sts);
	intr_sts_masked = intr_sts & ctrl->intr_mask;

	do {
		for (i = 0; i < SWRM_INTERRUPT_MAX; i++) {
			value = intr_sts_masked & BIT(i);
			if (!value)
				continue;

			switch (value) {
			case SWRM_INTERRUPT_STATUS_SLAVE_PEND_IRQ:
				/* Shared-address SPX alerts are collision artifacts.
				 * Once force-attached, consulting slave status here can
				 * notify the core and re-run codec initialization.
				 */
				if (spx_forced_attached)
					break;
				devnum = qcom_swrm_get_alert_slave_dev_num(ctrl);
				if (devnum < 0) {
					dev_err_ratelimited(ctrl->dev,
					    "no slave alert found.spurious interrupt\n");
				} else {
					sdw_handle_slave_status(&ctrl->bus, ctrl->status);
				}

				break;
			case SWRM_INTERRUPT_STATUS_NEW_SLAVE_ATTACHED:
			case SWRM_INTERRUPT_STATUS_CHANGE_ENUM_SLAVE_STATUS:
				/* The shared SPX amps make physical status flicker on
				 * every colliding command. The logical forced attachment
				 * is terminal; notifying the core here re-runs codec init
				 * and destroys the active stream configuration.
				 */
				if (spx_forced_attached)
					break;
				dev_dbg_ratelimited(ctrl->dev, "SWR new slave attached\n");
				ctrl->reg_read(ctrl, SWRM_MCP_SLV_STATUS, &slave_status);
				if (ctrl->slave_status == slave_status) {
					dev_dbg(ctrl->dev, "Slave status not changed %x\n",
						slave_status);
				} else {
					qcom_swrm_get_device_status(ctrl);
					qcom_swrm_enumerate(&ctrl->bus);
					sdw_handle_slave_status(&ctrl->bus, ctrl->status);
				}
				/*
				 * SPX: NO budget refund here. The failed arbitration makes
				 * the device-0 slv-status flicker, which fires this IRQ
				 * repeatedly; refunding on it reset the 64-cap forever and
				 * stormed (57k IRQs). The cap is a hard per-session bound.
				 */
				break;
			case SWRM_INTERRUPT_STATUS_MASTER_CLASH_DET:
				dev_err_ratelimited(ctrl->dev,
						"%s: SWR bus clsh detected\n",
						__func__);
				/*
				 * qcauddev8180 clears and logs MASTER_CLASH_DET. It does
				 * not disable this interrupt and does not toggle the
				 * enumerator. The common tail below clears the status.
				 */
				if (ctrl->spx_windows_init)
					break;

				/* Older opt-in SPX diagnostic recovery path. */
				if (spx_core_enum && spx_bus_up &&
				    spx_clash_recover++ < 64) {
					ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 0);
					ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 1);
					usleep_range(1000, 2000);
					break;
				}
				/* SPX: budget spent -> give up cleanly: STOP the auto-
				 * enumerator so the clash + slv-flicker stop firing. */
				if (spx_core_enum)
					ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 0);
				ctrl->intr_mask &= ~SWRM_INTERRUPT_STATUS_MASTER_CLASH_DET;
				ctrl->reg_write(ctrl,
						ctrl->reg_layout[SWRM_REG_INTERRUPT_CPU_EN],
						ctrl->intr_mask);
				break;
			case SWRM_INTERRUPT_STATUS_AUTO_ENUM_FAILED:
				/*
				 * SPX: Windows' clash recovery fires on this bit too --
				 * toggle ENUMERATOR_CFG to re-arm auto-enumeration.
				 * Mainline has no handler (it shows up as "unknown
				 * interrupt 2048" and storms). Bounded.
				 */
				if (spx_core_enum && spx_bus_up &&
				    spx_clash_recover++ < 64) {
					ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 0);
					ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 1);
					usleep_range(1000, 2000);
				} else if (spx_bus_up) {
					/* budget spent -> stop the auto-enumerator + mask. */
					ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 0);
					ctrl->intr_mask &= ~SWRM_INTERRUPT_STATUS_AUTO_ENUM_FAILED;
					ctrl->reg_write(ctrl,
						ctrl->reg_layout[SWRM_REG_INTERRUPT_CPU_EN],
						ctrl->intr_mask);
				}
				break;
			case SWRM_INTERRUPT_STATUS_RD_FIFO_OVERFLOW:
				ctrl->reg_read(ctrl,
					       ctrl->reg_layout[SWRM_REG_CMD_FIFO_STATUS],
					       &value);
				dev_err_ratelimited(ctrl->dev,
					"%s: SWR read FIFO overflow fifo status 0x%x\n",
					__func__, value);
				break;
			case SWRM_INTERRUPT_STATUS_RD_FIFO_UNDERFLOW:
				ctrl->reg_read(ctrl,
					       ctrl->reg_layout[SWRM_REG_CMD_FIFO_STATUS],
					       &value);
				dev_err_ratelimited(ctrl->dev,
					"%s: SWR read FIFO underflow fifo status 0x%x\n",
					__func__, value);
				break;
			case SWRM_INTERRUPT_STATUS_WR_CMD_FIFO_OVERFLOW:
				ctrl->reg_read(ctrl,
					       ctrl->reg_layout[SWRM_REG_CMD_FIFO_STATUS],
					       &value);
				dev_err(ctrl->dev,
					"%s: SWR write FIFO overflow fifo status %x\n",
					__func__, value);
				ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CMD, 0x1);
				break;
			case SWRM_INTERRUPT_STATUS_CMD_ERROR:
				ctrl->reg_read(ctrl,
					       ctrl->reg_layout[SWRM_REG_CMD_FIFO_STATUS],
					       &value);
				dev_err_ratelimited(ctrl->dev,
					"%s: SWR CMD error, fifo status 0x%x, flushing fifo\n",
					__func__, value);
				ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CMD, 0x1);
				break;
			case SWRM_INTERRUPT_STATUS_DOUT_PORT_COLLISION:
				dev_err_ratelimited(ctrl->dev,
						"%s: SWR Port collision detected\n",
						__func__);
				ctrl->intr_mask &= ~SWRM_INTERRUPT_STATUS_DOUT_PORT_COLLISION;
				ctrl->reg_write(ctrl,
						ctrl->reg_layout[SWRM_REG_INTERRUPT_CPU_EN],
						ctrl->intr_mask);
				break;
			case SWRM_INTERRUPT_STATUS_READ_EN_RD_VALID_MISMATCH:
				dev_err_ratelimited(ctrl->dev,
					"%s: SWR read enable valid mismatch\n",
					__func__);
				ctrl->intr_mask &=
					~SWRM_INTERRUPT_STATUS_READ_EN_RD_VALID_MISMATCH;
				ctrl->reg_write(ctrl,
						ctrl->reg_layout[SWRM_REG_INTERRUPT_CPU_EN],
						ctrl->intr_mask);
				break;
			case SWRM_INTERRUPT_STATUS_SPECIAL_CMD_ID_FINISHED:
				complete(&ctrl->broadcast);
				break;
			case SWRM_INTERRUPT_STATUS_BUS_RESET_FINISHED_V2:
				break;
			case SWRM_INTERRUPT_STATUS_CLK_STOP_FINISHED_V2:
				break;
			case SWRM_INTERRUPT_STATUS_EXT_CLK_STOP_WAKEUP:
				break;
			case SWRM_INTERRUPT_STATUS_CMD_IGNORED_AND_EXEC_CONTINUED:
				ctrl->reg_read(ctrl,
					       ctrl->reg_layout[SWRM_REG_CMD_FIFO_STATUS],
					       &value);
				dev_err(ctrl->dev,
					"%s: SWR CMD ignored, fifo status %x\n",
					__func__, value);

				/* Wait 3.5ms to clear */
				usleep_range(3500, 3505);
				break;
			default:
				dev_err_ratelimited(ctrl->dev,
						"%s: SWR unknown interrupt value: %d\n",
						__func__, value);
				ret = IRQ_NONE;
				break;
			}
		}
		ctrl->reg_write(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_CLEAR],
				intr_sts);
		ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_STATUS],
			       &intr_sts);
		intr_sts_masked = intr_sts & ctrl->intr_mask;
	} while (intr_sts_masked);

	if (ctrl->spx_windows_init)
		mutex_unlock(&ctrl->controller_lock);
	clk_disable_unprepare(ctrl->hclk);
	return ret;
}

static bool swrm_wait_for_frame_gen_enabled(struct qcom_swrm_ctrl *ctrl)
{
	int retry = SWRM_LINK_STATUS_RETRY_CNT;
	int comp_sts;

	do {
		ctrl->reg_read(ctrl, ctrl->reg_layout[SWRM_REG_FRAME_GEN_ENABLED],
			       &comp_sts);
		if (comp_sts & SWRM_FRM_GEN_ENABLED)
			return true;

		usleep_range(500, 510);
	} while (retry--);

	dev_err(ctrl->dev, "%s: link status not %s\n", __func__,
		comp_sts & SWRM_FRM_GEN_ENABLED ? "connected" : "disconnected");

	return false;
}

static int spx_swrm_windows_enumerate_wsas(struct qcom_swrm_ctrl *ctrl)
{
	u32 slv = 0, dev1_id1 = 0, dev1_id2 = 0;
	u32 dev2_id1 = 0, dev2_id2 = 0, frame = 0;
	bool divider_changed = false;
	int poll, stable = 0;

	/* Hold ID4 off, then let the hardware enumerator assign ID3 as dev1. */
	regmap_update_bits(ctrl->regmap, WCD934X_GPIO_DIR_CTL, 0x06, 0x06);
	regmap_update_bits(ctrl->regmap, WCD934X_GPIO_VAL_CTL, 0x06, BIT(1));
	for (poll = 0; poll < 400; poll++) {
		ctrl->reg_read(ctrl, SWRM_MCP_SLV_STATUS, &slv);
		ctrl->reg_read(ctrl, SWRM_ENUMERATOR_SLAVE_DEV_ID_1(1),
			       &dev1_id1);
		ctrl->reg_read(ctrl, SWRM_ENUMERATOR_SLAVE_DEV_ID_2(1),
			       &dev1_id2);

		if (!divider_changed && dev1_id1 == 0x21170213 &&
		    dev1_id2 == 0x10) {
			ctrl->reg_read(ctrl, SWRM_MCP_FRAME_CTRL_BANK_ADDR(0),
				       &frame);
			u32p_replace_bits(&frame, 2, GENMASK(10, 8));
			ctrl->reg_write(ctrl, SWRM_MCP_FRAME_CTRL_BANK_ADDR(0),
					frame);
			divider_changed = true;
		}

		if ((slv & GENMASK(3, 2)) == BIT(2) &&
		    dev1_id1 == 0x21170213 && dev1_id2 == 0x10)
			stable++;
		else
			stable = 0;
		if (stable >= 4)
			break;
		usleep_range(500, 550);
	}
	if (stable < 4) {
		dev_err(ctrl->dev,
			"SPX: dual enumeration failed at left WSA slv=%#x id=%#x/%#x\n",
			slv, dev1_id1, dev1_id2);
		goto fail_closed;
	}

	/* Release ID4 and let the same enumerator assign it as dev2. */
	regmap_update_bits(ctrl->regmap, WCD934X_GPIO_VAL_CTL, 0x06, 0x06);
	divider_changed = false;
	stable = 0;
	for (poll = 0; poll < 400; poll++) {
		ctrl->reg_read(ctrl, SWRM_MCP_SLV_STATUS, &slv);
		ctrl->reg_read(ctrl, SWRM_ENUMERATOR_SLAVE_DEV_ID_1(2),
			       &dev2_id1);
		ctrl->reg_read(ctrl, SWRM_ENUMERATOR_SLAVE_DEV_ID_2(2),
			       &dev2_id2);

		if (!divider_changed && dev2_id1 == 0x21170214 &&
		    dev2_id2 == 0x10) {
			ctrl->reg_read(ctrl, SWRM_MCP_FRAME_CTRL_BANK_ADDR(0),
				       &frame);
			u32p_replace_bits(&frame, 3, GENMASK(10, 8));
			ctrl->reg_write(ctrl, SWRM_MCP_FRAME_CTRL_BANK_ADDR(0),
					frame);
			divider_changed = true;
		}

		if ((slv & GENMASK(5, 2)) == (BIT(4) | BIT(2)) &&
		    dev1_id1 == 0x21170213 && dev1_id2 == 0x10 &&
		    dev2_id1 == 0x21170214 && dev2_id2 == 0x10)
			stable++;
		else
			stable = 0;
		if (stable >= 4)
			break;
		usleep_range(500, 550);
	}
	if (stable < 4) {
		dev_err(ctrl->dev,
			"SPX: dual enumeration failed at right WSA slv=%#x id=%#x/%#x\n",
			slv, dev2_id1, dev2_id2);
		goto fail_closed;
	}

	/* The active bank reached divider 3 incrementally; match the idle bank. */
	ctrl->reg_write(ctrl, SWRM_MCP_FRAME_CTRL_BANK_ADDR(1),
			BIT(16) | (3 << 8));
	ctrl->slave_status = slv;
	memset(ctrl->status, 0, sizeof(ctrl->status));
	ctrl->status[1] = SDW_SLAVE_ATTACHED;
	ctrl->status[2] = SDW_SLAVE_ATTACHED;
	dev_info(ctrl->dev,
		 "SPX: minimal dual WSA enumeration retained slv=%#x dev1=%#x/%#x dev2=%#x/%#x\n",
		 slv, dev1_id1, dev1_id2, dev2_id1, dev2_id2);
	return 0;

fail_closed:
	ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 0);
	regmap_update_bits(ctrl->regmap, WCD934X_GPIO_VAL_CTL, 0x06, 0);
	return -ENODEV;
}

static int qcom_swrm_init(struct qcom_swrm_ctrl *ctrl)
{
	u32 val;
	int retry, ret;

	spx_bus_up = false;
	if (ctrl->spx_windows_init)
		mutex_lock(&ctrl->controller_lock);

	/*
	 * Exact qcauddev8180 sequence for the WCD9340-integrated v1.3 master.
	 * The Windows driver's logical power-control calls around its 2 ms wait
	 * map to empty ACPI component states on Surface Pro X; they do not touch
	 * WCD GPIOs. Keep the actual register writes in their observed order.
	 */
	if (ctrl->spx_windows_init) {
		/*
		 * Windows brackets its empty Surface ACPI component-state
		 * transitions with 2 ms and 1 ms waits before touching the
		 * master. The component calls have no electrical effect on this
		 * machine, but preserve both settling intervals.
		 */
		usleep_range(2000, 2100);
		usleep_range(1000, 1100);

		regmap_update_bits(ctrl->regmap, WCD934X_GPIO_DIR_CTL,
				   0x06, 0x06);
		regmap_update_bits(ctrl->regmap, WCD934X_GPIO_VAL_CTL,
				   0x06, 0);
		msleep(20);

		/* This reset bit is self-clearing on the WCD9340 manager. */
		ctrl->reg_write(ctrl, SWRM_COMP_SW_RESET, 1);
		ctrl->reg_write(ctrl, SWRM_COMP_SW_RESET, 1);

		/*
		 * qcauddev8180!0x14009c6fc writes 0x03: three command
		 * retries, without CONTINUE_EXEC_ON_CMD_IGNORE.
		 */
		ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CFG_ADDR, 0x03);

		ctrl->reg_read(ctrl, SWRM_MCP_CFG_ADDR, &val);
		u32p_replace_bits(&val, SWRM_DEF_CMD_NO_PINGS,
				  SWRM_MCP_CFG_MAX_NUM_OF_CMD_NO_PINGS_BMSK);
		ctrl->reg_write(ctrl, SWRM_MCP_CFG_ADDR, val);

		ctrl->reg_write(ctrl,
				ctrl->reg_layout[SWRM_REG_INTERRUPT_MASK_ADDR], 0);
		ctrl->reg_write(ctrl,
				ctrl->reg_layout[SWRM_REG_INTERRUPT_CPU_EN], 0);
		ctrl->intr_mask = 0x1fffd;
		ctrl->reg_write(ctrl,
				ctrl->reg_layout[SWRM_REG_INTERRUPT_MASK_ADDR],
				ctrl->intr_mask);

		/* Start on 48x2/divider-1; the staged enumerator reaches divider 3. */
		ctrl->reg_write(ctrl, SWRM_MCP_FRAME_CTRL_BANK_ADDR(0),
				BIT(16) | (1 << 8));
		ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 1);
		ctrl->reg_write(ctrl, SWRM_MCP_BUS_CTRL,
				SWRM_MCP_BUS_CLK_START);
		ctrl->reg_write(ctrl, SWRM_COMP_CFG_ADDR,
				SWRM_COMP_CFG_IRQ_LEVEL_OR_PULSE_MSK);
		ctrl->reg_write(ctrl, SWRM_COMP_CFG_ADDR,
				SWRM_COMP_CFG_IRQ_LEVEL_OR_PULSE_MSK |
				SWRM_COMP_CFG_ENABLE_MSK);
		ctrl->reg_write(ctrl,
				ctrl->reg_layout[SWRM_REG_INTERRUPT_CLEAR], ~0U);

		for (retry = 0; retry < 100; retry++) {
			ctrl->reg_read(ctrl, SWRM_COMP_STATUS, &val);
			if (val & SWRM_FRM_GEN_ENABLED)
				break;
			usleep_range(500, 550);
		}
		if (!(val & SWRM_FRM_GEN_ENABLED))
			dev_err(ctrl->dev,
				"SPX: Windows init sequence did not start frame generator (status %#x)\n",
				val);
		else
			dev_info(ctrl->dev,
				 "SPX: exact Windows SoundWire controller init complete\n");

		ret = spx_swrm_windows_enumerate_wsas(ctrl);
		if (ret) {
			mutex_unlock(&ctrl->controller_lock);
			return ret;
		}
		spx_clk_div = 3;
		ctrl->spx_runtime_handoff_pending = false;
		ctrl->reg_read(ctrl, SWRM_COMP_PARAMS, &val);
		ctrl->wr_fifo_depth =
			FIELD_GET(SWRM_COMP_PARAMS_WR_FIFO_DEPTH, val);
		mutex_unlock(&ctrl->controller_lock);
		return 0;
	}

	/*
	 * SPX: quiet the bus before frame-gen. Drive the WSA enable pins LOW
	 * so the amps are not driving the bus while
	 * the frame generator starts — this is what triggers MASTER_CLASH_DET
	 * and leaves frame-gen lock nondeterministic. Released after the lock.
	 */
	if (spx_core_enum && spx_quiet_bus) {
		regmap_update_bits(ctrl->regmap, WCD934X_GPIO_DIR_CTL,
				   spx_quiet_bus, spx_quiet_bus);
		regmap_update_bits(ctrl->regmap, WCD934X_GPIO_VAL_CTL,
				   spx_quiet_bus, 0);
		usleep_range(2000, 2100);
	}

	/* Clear Rows and Cols */
	val = FIELD_PREP(SWRM_MCP_FRAME_CTRL_BANK_ROW_CTRL_BMSK, ctrl->rows_index);
	val |= FIELD_PREP(SWRM_MCP_FRAME_CTRL_BANK_COL_CTRL_BMSK, ctrl->cols_index);
	/*
	 * SPX: set the frame-phase field [22:16]. REQUIRED for frame-gen to lock
	 * on SPX (proven: removing it -> "link status not disconnected"; db845c
	 * doesn't need it). Tunable via spx_frame_phase to hunt a value that also
	 * lets the device-0 arbitration converge.
	 */
	if (ctrl->spx_windows_init)
		val |= BIT(16);
	else if (spx_core_enum)
		val |= (spx_frame_phase & 0xff) << 16 |
		       (spx_actual_phase & 0x1f) << 11 |
		       (spx_clk_div & 0x7) << 8;

	if (ctrl->audio_cgcr)
		reset_control_reset(ctrl->audio_cgcr);

	ctrl->reg_write(ctrl, SWRM_MCP_FRAME_CTRL_BANK_ADDR(0), val);

	/*
	 * Enable Auto enumeration HERE (stock/db845c position). NOTE: deferring
	 * this to post-frame-gen (tried earlier) BREAKS frame-gen lock -- the
	 * frame generator needs the enumerator enabled to lock (frame-gen then
	 * timed out intermittently with "link status not disconnected"). db845c
	 * enables it here and locks fine, so match it.
	 */
	ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 1);

	/*
	 * SPX: Windows writes INTERRUPT_MASK = 0x1c3fd (not the full 0x1ffff) --
	 * it MASKS OFF NEW_SLAVE_ATTACHED(b1), AUTO_ENUM_FAILED(b11) and the other
	 * enum-chatter IRQs (b9,10,12,13) so the driver ISR stays OUT of the HW
	 * auto-enum's multi-pass arbitration (and does not storm). Mainline unmasks
	 * everything, so its ISR reacts to every attach/fail mid-arbitration.
	 */
	/*
	 * SPX: keep ALL interrupts unmasked (like stock/db845c). The earlier
	 * 0x1c3fd masked NEW_SLAVE_ATTACHED(b1) + AUTO_ENUM_FAILED(b11) -- exactly
	 * the bits the device-0 clash RECOVERY needs (the ISR re-arms the HW
	 * auto-enumerator on the clash, Windows-style, and re-enumerates on the
	 * resulting attach). Masking them left the bus stuck after one clash.
	 */
	ctrl->intr_mask = ctrl->spx_windows_init ? 0x1c3fd :
						 SWRM_INTERRUPT_STATUS_RMSK;
	/* Mask soundwire interrupts */
	if (ctrl->version < SWRM_VERSION_2_0_0)
		ctrl->reg_write(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_MASK_ADDR],
				ctrl->intr_mask);

	/*
	 * Configure No pings.
	 * SPX: Windows zeroes the no-pings field on this codec-internal master;
	 * mainline's 0x1f changes the ping cadence during auto-enum arbitration on
	 * the slow SLIMbus-bridged bus. db845c (fast MMIO master) keeps 0x1f.
	 */
	ctrl->reg_read(ctrl, SWRM_MCP_CFG_ADDR, &val);
	u32p_replace_bits(&val,
			  (ctrl->spx_windows_init || spx_core_enum) ? 0 :
			  SWRM_DEF_CMD_NO_PINGS,
			  SWRM_MCP_CFG_MAX_NUM_OF_CMD_NO_PINGS_BMSK);
	ctrl->reg_write(ctrl, SWRM_MCP_CFG_ADDR, val);

	if (ctrl->version == SWRM_VERSION_1_7_0) {
		ctrl->reg_write(ctrl, SWRM_LINK_MANAGER_EE, SWRM_EE_CPU);
		ctrl->reg_write(ctrl, SWRM_MCP_BUS_CTRL,
				SWRM_MCP_BUS_CLK_START << SWRM_EE_CPU);
	} else if (ctrl->version >= SWRM_VERSION_2_0_0) {
		ctrl->reg_write(ctrl, SWRM_LINK_MANAGER_EE, SWRM_EE_CPU);
		ctrl->reg_write(ctrl, SWRM_V2_0_CLK_CTRL,
				SWRM_V2_0_CLK_CTRL_CLK_START);
	} else if (ctrl->spx_windows_init) {
		/* qcauddev8180 writes MCP_BUS_CTRL (0x1044) byte value 2. */
		ctrl->reg_write(ctrl, SWRM_MCP_BUS_CTRL,
				SWRM_MCP_BUS_CLK_START);
		ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CFG_ADDR, 0x03);
	} else if (spx_core_enum) {
		/*
		 * SPX: the WCD9340 codec-internal SWR master is SHARED with the
		 * ADSP execution environment. db845c's v1.3.0 master is single-EE
		 * so mainline just starts the bus clock — but on SPX the APPS EE
		 * must first CLAIM ownership of the link manager (LINK_MANAGER_EE
		 * = CPU), otherwise the BUS_CTRL=CLK_START write does not reliably
		 * start the frame generator (nondeterministic "link status not
		 * disconnected"). Claim EE, then start the clock.
		 */
		ctrl->reg_write(ctrl, SWRM_LINK_MANAGER_EE, SWRM_EE_CPU);
		/*
		 * SPX: the EE-arbitrated master encodes the bus-clock-start bit
		 * at a PER-EE position (see the v1.7.0 path: CLK_START<<EE_CPU).
		 * Writing the bare CLK_START (bit1, the EE0/ADSP slot) reads back
		 * 0 and never starts the frame generator. Shift it to the CPU EE
		 * slot so the APPS-owned clock actually starts.
		 */
		ctrl->reg_write(ctrl, SWRM_MCP_BUS_CTRL,
				SWRM_MCP_BUS_CLK_START << SWRM_EE_CPU);
	} else {
		ctrl->reg_write(ctrl, SWRM_MCP_BUS_CTRL, SWRM_MCP_BUS_CLK_START);
	}

	/* Configure number of retries of a read/write cmd */
	if (ctrl->version >= SWRM_VERSION_1_5_1) {
		ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CFG_ADDR,
				SWRM_RD_WR_CMD_RETRIES |
				SWRM_CONTINUE_EXEC_ON_CMD_IGNORE);
	} else if (ctrl->spx_windows_init) {
		/* Windows uses three retries without continue-on-ignore. */
		ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CFG_ADDR, 0x03);
	} else if (spx_core_enum) {
		/* SPX: Windows writes CMD_FIFO_CFG=0x03 (retries=3, NO bit31
		 * CONTINUE_EXEC_ON_CMD_IGNORE); the continue-on-ignore bit lets
		 * enumeration plow past ignored cmds and aggravates the clash. */
		ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CFG_ADDR, 0x03);
	} else {
		ctrl->reg_write(ctrl, SWRM_CMD_FIFO_CFG_ADDR,
				SWRM_RD_WR_CMD_RETRIES);
	}

	/* COMP Enable */
	ctrl->reg_write(ctrl, SWRM_COMP_CFG_ADDR, SWRM_COMP_CFG_ENABLE_MSK);

	/* Set IRQ to PULSE */
	ctrl->reg_write(ctrl, SWRM_COMP_CFG_ADDR,
			SWRM_COMP_CFG_IRQ_LEVEL_OR_PULSE_MSK);

	ctrl->reg_write(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_CLEAR],
			0xFFFFFFFF);

	/* enable CPU IRQs (SPX: use the Windows-masked set, not all-17) */
	if (ctrl->mmio && ctrl->irq > 0) {
		ctrl->reg_write(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_CPU_EN],
				ctrl->intr_mask);
	}

	/* Set IRQ to PULSE */
	ctrl->reg_write(ctrl, SWRM_COMP_CFG_ADDR,
			SWRM_COMP_CFG_IRQ_LEVEL_OR_PULSE_MSK |
			SWRM_COMP_CFG_ENABLE_MSK);

	/*
	 * SPX: once frame-gen is confirmed up, allow the ISR clash-recovery to
	 * fire (re-arm on clash, bounded). The enumerator is already enabled
	 * above (stock position); we only flip the recovery gate here.
	 */
	if (swrm_wait_for_frame_gen_enabled(ctrl) && spx_core_enum)
		spx_bus_up = true;

	if (spx_core_enum) {
		/*
		 * SPX diag + frame_phase auto-sweep. The codec-internal master
		 * fails frame-gen lock with "bus clsh detected" at the default
		 * phase. Dump the master state, then (if not locked) sweep the
		 * frame-phase field [22:16] re-pulsing the bus clock until
		 * COMP_STATUS bit0 sets. Logs the locking phase if found.
		 */
		static const struct { u16 a; const char *n; } dbg[] = {
			{ SWRM_COMP_STATUS, "COMP_STATUS" },
			{ SWRM_V1_3_INTERRUPT_STATUS, "INT_STATUS" },
			{ SWRM_LINK_MANAGER_EE, "LINK_MANAGER_EE" },
			{ SWRM_MCP_FRAME_CTRL_BANK_ADDR(0), "FRAME_CTRL" },
			{ SWRM_MCP_BUS_CTRL, "MCP_BUS_CTRL" },
			{ SWRM_MCP_STATUS, "MCP_STATUS" },
			{ SWRM_MCP_SLV_STATUS, "MCP_SLV_STATUS" },
		};
		u32 dv;
		int di;

		for (di = 0; di < ARRAY_SIZE(dbg); di++) {
			dv = 0;
			ctrl->reg_read(ctrl, dbg[di].a, &dv);
			dev_info(ctrl->dev, "SPX SWRM %-14s (0x%04x) = 0x%08x\n",
				 dbg[di].n, dbg[di].a, dv);
		}

		if (!spx_bus_up) {
			int phase, base;

			base = FIELD_PREP(SWRM_MCP_FRAME_CTRL_BANK_ROW_CTRL_BMSK,
					  ctrl->rows_index) |
			       FIELD_PREP(SWRM_MCP_FRAME_CTRL_BANK_COL_CTRL_BMSK,
					  ctrl->cols_index);
			dev_info(ctrl->dev, "SPX: frame-gen not locked, sweeping frame_phase 0..127\n");
			for (phase = 0; phase < 128; phase += 2) {
				ctrl->reg_write(ctrl,
					SWRM_MCP_FRAME_CTRL_BANK_ADDR(0),
					base | ((phase & 0x7f) << 16));
				ctrl->reg_write(ctrl, SWRM_LINK_MANAGER_EE,
						SWRM_EE_CPU);
				ctrl->reg_write(ctrl, SWRM_MCP_BUS_CTRL,
						SWRM_MCP_BUS_CLK_START << SWRM_EE_CPU);
				if (swrm_wait_for_frame_gen_enabled(ctrl)) {
					dev_info(ctrl->dev,
						"SPX: *** frame-gen LOCKED at frame_phase=%d ***\n",
						phase);
					spx_frame_phase = phase;
					spx_bus_up = true;
					break;
				}
			}
			if (!spx_bus_up)
				dev_info(ctrl->dev,
					"SPX: frame-gen FAILED all frame_phase values\n");
		}

		/*
		 * Frame-gen settled on a quiet bus; now power the selected WSA amps
		 * on (drive their enable pins HIGH). They attach as NEW_SLAVE and
		 * enumerate against the now-locked frame generator.
		 */
		if (spx_quiet_bus) {
			dev_info(ctrl->dev, "SPX: releasing WSA amps (pins 0x%x) post frame-gen, bus_up=%d\n",
				 spx_quiet_bus, spx_bus_up);
			regmap_update_bits(ctrl->regmap, WCD934X_GPIO_VAL_CTL,
					   spx_quiet_bus, spx_quiet_bus);
			usleep_range(5000, 5100);
		}
	}

	ctrl->slave_status = 0;
	ctrl->reg_read(ctrl, SWRM_COMP_PARAMS, &val);

	if (ctrl->version >= SWRM_VERSION_3_1_0)
		ctrl->wr_fifo_depth = FIELD_GET(SWRM_V3_COMP_PARAMS_WR_FIFO_DEPTH, val);
	else
		ctrl->wr_fifo_depth = FIELD_GET(SWRM_COMP_PARAMS_WR_FIFO_DEPTH, val);

	return 0;
}

static int qcom_swrm_read_prop(struct sdw_bus *bus)
{
	struct qcom_swrm_ctrl *ctrl = to_qcom_sdw(bus);

	if (ctrl->version >= SWRM_VERSION_2_0_0) {
		bus->multi_link = true;
		bus->hw_sync_min_links = 3;
	}

	return 0;
}

static enum sdw_command_response qcom_swrm_xfer_msg(struct sdw_bus *bus,
						    struct sdw_msg *msg)
{
	struct qcom_swrm_ctrl *ctrl = to_qcom_sdw(bus);
	int ret, i, len;

	if (msg->page) {
		ret = qcom_swrm_cmd_fifo_wr_cmd(ctrl, msg->addr_page1,
						msg->dev_num,
						SDW_SCP_ADDRPAGE1);
		if (ret)
			return ret;

		ret = qcom_swrm_cmd_fifo_wr_cmd(ctrl, msg->addr_page2,
						msg->dev_num,
						SDW_SCP_ADDRPAGE2);
		if (ret)
			return ret;
	}

	if (msg->flags == SDW_MSG_FLAG_READ) {
		for (i = 0; i < msg->len;) {
			len = min(msg->len - i, QCOM_SWRM_MAX_RD_LEN);

			ret = qcom_swrm_cmd_fifo_rd_cmd(ctrl, msg->dev_num,
							msg->addr + i, len,
						       &msg->buf[i]);
			if (ret)
				return ret;

			i = i + len;
		}
	} else if (msg->flags == SDW_MSG_FLAG_WRITE) {
		u8 dev_num = msg->dev_num;

		/* Force-attach keeps a logical device 1 in the SoundWire core, but
		 * the shared SPX amplifiers do not retain the blind device-number
		 * assignment.  They remain at enumeration address 0, so send both
		 * codec-register and stream-port writes to that physical address.
		 */
		/*
		 * Route to whichever address the amp actually answers on.
		 * spx_write_dev0 < 0 = auto (track MCP_SLV_STATUS); 0/1 force it.
		 * While the last sample saw no device, re-sample cheaply before
		 * each write so a late attach still flips the routing.
		 */
		if (spx_forced_attached && dev_num == 1) {
			if (spx_no_assign) {
				dev_num = SDW_ENUM_DEV_NUM;
			} else if (spx_write_dev0 < 0 && spx_amp_addr_stale) {
				u32 slv = 0;
				bool dev0, dev1;

				if (!ctrl->reg_read(ctrl, SWRM_MCP_SLV_STATUS, &slv)) {
					dev0 = slv & SWRM_MCP_SLV_STATUS_MASK;
					dev1 = (slv >> 2) & SWRM_MCP_SLV_STATUS_MASK;
					if (dev0 == dev1)
						goto route_write;
					spx_amp_at_dev0 = dev0;
					spx_amp_addr_stale = false;
					dev_info(ctrl->dev,
						 "SPX: late slv_status=0x%x -> writes go to device %d\n",
						 slv, spx_amp_at_dev0 ? 0 : 1);
				}
			}
route_write:
			if (!spx_no_assign &&
			    (spx_write_dev0 < 0 ? spx_amp_at_dev0 :
			     !!spx_write_dev0))
				dev_num = SDW_ENUM_DEV_NUM;
		}

		for (i = 0; i < msg->len; i++) {
			u16 addr = msg->addr + i;
			int rep, reps = 1;
			u16 mirror = 0;

			if ((spx_forced_attached || ctrl->spx_windows_init) &&
			    msg->dev_num == SDW_BROADCAST_DEV_NUM &&
			    (addr == SDW_SCP_FRAMECTRL_B0 ||
			     addr == SDW_SCP_FRAMECTRL_B1)) {
				reps = clamp(spx_bank_switch_repeats, 1, 5);
				if (reps > 1)
					dev_info(ctrl->dev,
						 "SPX: FRAMECTRL bank-switch broadcast addr=%#x value=%#x repeats=%d\n",
						 addr, msg->buf[i], reps);
			}

			if ((spx_forced_attached &&
			     (msg->dev_num == 1 || dev_num == SDW_ENUM_DEV_NUM)) ||
			    (ctrl->spx_windows_init &&
			     (dev_num == 1 || dev_num == 2))) {
				/*
				 * Mirror banked slave DPn registers (offset
				 * 0x20-0x2f = bank 0, 0x30-0x3f = bank 1 within
				 * each 0x100-sized port block) so the stream is
				 * configured no matter which bank the bus is
				 * on; a lost bank switch then cannot mute it.
				 */
				if (spx_mirror_banks &&
				    addr >= 0x100 && addr < 0xf00) {
					if ((addr & 0xf0) == 0x20)
						mirror = addr + 0x10;
					else if ((addr & 0xf0) == 0x30)
						mirror = addr - 0x10;
				}
				if (!mirror && spx_shadow_dp1_enable) {
					unsigned int p;

					/*
					 * Keep both banks complete for every WSA
					 * descriptor in use, not just the DAC one:
					 * Windows programs the destination bank from
					 * per-port records, so a four-port stream must
					 * be enabled in both banks too.
					 */
					for (p = 1; p <= 4; p++) {
						if (addr == SDW_DPN_CHANNELEN_B0(p))
							mirror = SDW_DPN_CHANNELEN_B1(p);
						else if (addr == SDW_DPN_CHANNELEN_B1(p))
							mirror = SDW_DPN_CHANNELEN_B0(p);
						if (mirror)
							break;
					}
					if (mirror)
						dev_info(ctrl->dev,
							 "SPX: shadow slave DP%u ChannelEn value=0x%02x reg 0x%04x->0x%04x\n",
							 p, msg->buf[i], addr, mirror);
				}
				if (spx_write_twice && addr != SDW_SCP_DEVNUMBER)
					reps = 2;
			}

			for (rep = 0; rep < reps; rep++) {
				ret = qcom_swrm_cmd_fifo_wr_cmd(ctrl, msg->buf[i],
								dev_num, addr);
				if (ret)
					return SDW_CMD_IGNORED;
				if (mirror) {
					ret = qcom_swrm_cmd_fifo_wr_cmd(ctrl,
							msg->buf[i], dev_num,
							mirror);
					if (ret)
						return SDW_CMD_IGNORED;
				}
				if (reps > 1 && rep + 1 < reps)
					usleep_range(200, 400);
			}
		}
	}

	return SDW_CMD_OK;
}

static int qcom_swrm_spx_frame_write(struct qcom_swrm_ctrl *ctrl,
				     unsigned int bank, u32 val)
{
	u32 readback;
	int attempt, rd_ret, wr_ret;

	for (attempt = 1; attempt <= 4; attempt++) {
		wr_ret = ctrl->reg_write(ctrl,
			SWRM_MCP_FRAME_CTRL_BANK_ADDR(bank), val);
		readback = 0;
		rd_ret = ctrl->reg_read(ctrl,
			SWRM_MCP_FRAME_CTRL_BANK_ADDR(bank), &readback);
		if (rd_ret == SDW_CMD_OK &&
		    (readback & GENMASK(23, 0)) == (val & GENMASK(23, 0))) {
			dev_info(ctrl->dev,
				 "SPX: manager FRAME_CTRL bank %u verified=%#010x write_response=%d attempt=%d/4\n",
				 bank, (u32)(readback & GENMASK(23, 0)),
				 wr_ret, attempt);
			return 0;
		}
		usleep_range(500, 550);
	}

	dev_err(ctrl->dev,
		"SPX: manager FRAME_CTRL bank %u failed readback=%#010x\n",
		bank, readback);
	return -EIO;
}

static int qcom_swrm_pre_bank_switch(struct sdw_bus *bus)
{
	u32 reg = SWRM_MCP_FRAME_CTRL_BANK_ADDR(bus->params.next_bank);
	struct qcom_swrm_ctrl *ctrl = to_qcom_sdw(bus);
	u32 val = 0;
	int ret;

	/*
	 * Enumerate on the only stable geometry (48x2/divider-3), then coordinate
	 * the first stream's transition to the proven clean-speaker geometry
	 * (48x16/divider-0). Program only the inactive manager bank here. The
	 * core's following FRAMECTRL broadcast changes the slaves and manager at
	 * the same frame boundary; post_bank_switch mirrors the now-inactive bank.
	 * Writing both manager banks before that broadcast changes the live clock
	 * under the assigned slaves and was proven to yield silence/static.
	 */
	if (ctrl->spx_windows_init) {
		if (spx_keep_enum_frame) {
			bus->params.row = 48;
			bus->params.col = 2;
			ctrl->spx_runtime_handoff_pending = false;
		} else if (ctrl->spx_runtime_handoff_pending) {
			spx_clk_div = 0;
			bus->params.row = 48;
			bus->params.col = 16;
			ctrl->rows_index = sdw_find_row_index(48);
			ctrl->cols_index = sdw_find_col_index(16);
			ctrl->spx_runtime_handoff_pending = false;
			ctrl->spx_runtime_mirror_pending = true;
		}
		val = (spx_runtime_ssp_period << 16) |
		      ((spx_actual_phase & 0x1f) << 11) |
		      (spx_clk_div << 8) |
		      FIELD_PREP(SWRM_MCP_FRAME_CTRL_BANK_ROW_CTRL_BMSK,
				 ctrl->rows_index) |
		      FIELD_PREP(SWRM_MCP_FRAME_CTRL_BANK_COL_CTRL_BMSK,
				 ctrl->cols_index);
		ret = qcom_swrm_spx_frame_write(ctrl, bus->params.next_bank, val);
		if (ret)
			return ret;
		if (ctrl->spx_runtime_mirror_pending)
			dev_info(ctrl->dev,
				 "SPX: clean runtime frame handoff armed on inactive bank %u frame=%#010x\n",
				 bus->params.next_bank, val);
		return 0;
	}

	ret = ctrl->reg_read(ctrl, reg, &val);
	if (ret && !spx_core_enum)
		return ret;

	u32p_replace_bits(&val, ctrl->cols_index, SWRM_MCP_FRAME_CTRL_BANK_COL_CTRL_BMSK);
	u32p_replace_bits(&val, ctrl->rows_index, SWRM_MCP_FRAME_CTRL_BANK_ROW_CTRL_BMSK);
	/* Preserve the SPX transport period across inactive-bank switches. */
	if (spx_core_enum) {
		u32p_replace_bits(&val, spx_runtime_ssp_period,
				  GENMASK(23, 16));
		u32p_replace_bits(&val, spx_actual_phase, GENMASK(15, 11));
		u32p_replace_bits(&val, spx_clk_div, GENMASK(10, 8));
		dev_info(ctrl->dev, "SPX: bank %u FRAME_CTRL=0x%08x\n",
			 bus->params.next_bank, val);
	}

	return ctrl->reg_write(ctrl, reg, val);
}

/*
 * SPX: default OFF. The Windows handshake (COMP_STATUS[5:4]==2, 5x5 poll at
 * qcauddev8180.sys 0x14009bb54) does not apply to this codec-internal master:
 * COMP_STATUS reads 0x14201 with bits[5:4]==0 on every switch, even when the
 * bus is demonstrably running. Kept as a knob for further experiments.
 */
/*
 * SPX: stop programming transport registers that the Windows driver
 * (qcauddev8180.sys) leaves at reset, and stop read-modify-writing the port
 * control register through the unreliable AHB bridge. Covers four divergences
 * found by diffing the Windows master against this driver on 2026-07-27:
 * BLOCK_CTRL_1=0xff (bps==0), slave DPn_BlockCtrl3=0xff, HCTRL=0xf0, and the
 * PORT_CTRL RMW. All four are candidates for the signal-proportional static.
 */
static int spx_dr_freq;
module_param(spx_dr_freq, int, 0444);
MODULE_PARM_DESC(spx_dr_freq,
		 "SPX: SoundWire bus data rate in Hz (0 = driver default 9.6 MHz). 19200000 (dual-edge) was TESTED 2026-07-27 and is WRONG: complete silence where 9.6 MHz gives tone+static.");

static int spx_win_transport;
module_param(spx_win_transport, int, 0644);
MODULE_PARM_DESC(spx_win_transport,
		 "SPX: match the Windows master's transport programming (skip bogus BLOCK_CTRL_1/BlockCtrl3/HCTRL writes, no PORT_CTRL read-modify-write)");

static int spx_verify_bank;
module_param(spx_verify_bank, int, 0644);
MODULE_PARM_DESC(spx_verify_bank,
		 "SPX: verify bank switch via COMP_STATUS[5:4]==2 and re-broadcast on failure (Windows qcauddev8180 handshake; field does not match this master)");

/*
 * SPX: Windows broadcasts CLK_STP_NOW (slave dev 0xF reg 0x44 SDW_SCP_CTRL
 * val 2) whenever its idle refcount hits zero, then msleep(1) -- idle park at
 * qcauddev8180.sys 0x14009b28c-b2a4. This driver already implements the
 * equivalent MIPI handshake in swrm_runtime_suspend/swrm_runtime_resume
 * (sdw_bus_prep_clk_stop + sdw_bus_clk_stop incl. the CLK_STP_NOW
 * broadcasts; resume exits clock stop); probe arms autosuspend with a fixed
 * 3000 ms delay. Streams release their runtime reference in
 * qcom_swrm_shutdown(), so the park only fires between streams -- exactly
 * the Windows semantic. No raw register writes are added here. On the
 * force-attach path spx_pm_held keeps the master runtime-active regardless
 * (a clock-stop suspend desyncs the force-attached amp), so this knob only
 * retimes boots without that hold. Validated once at probe; runtime writes
 * take effect after the next boot.
 */
static int spx_idle_clk_stop_ms;
module_param(spx_idle_clk_stop_ms, int, 0644);
MODULE_PARM_DESC(spx_idle_clk_stop_ms,
		 "SPX: idle-autosuspend delay (ms) before swrm_runtime_suspend parks the bus in clock stop between streams (100..600000, else probe fails -EINVAL; 0=legacy fixed 3000 ms)");

static int qcom_swrm_post_bank_switch(struct sdw_bus *bus)
{
	struct qcom_swrm_ctrl *ctrl = to_qcom_sdw(bus);
	int outer, inner;
	u32 val = 0;
	u8 data;
	int ret;

	if (ctrl->spx_windows_init && ctrl->spx_runtime_mirror_pending) {
		val = (spx_runtime_ssp_period << 16) |
		      ((spx_actual_phase & 0x1f) << 11) |
		      (spx_clk_div << 8) |
		      FIELD_PREP(SWRM_MCP_FRAME_CTRL_BANK_ROW_CTRL_BMSK,
				 ctrl->rows_index) |
		      FIELD_PREP(SWRM_MCP_FRAME_CTRL_BANK_COL_CTRL_BMSK,
				 ctrl->cols_index);
		ret = qcom_swrm_spx_frame_write(ctrl, bus->params.next_bank, val);
		if (ret)
			return ret;
		ctrl->spx_runtime_mirror_pending = false;
		dev_info(ctrl->dev,
			 "SPX: clean runtime frame handoff complete; both banks=%#010x\n",
			 val);
	}

	/*
	 * The SPX slave can fall from its fragile assigned address back to
	 * enumeration address 0 while processing FRAMECTRL. Refresh immediately
	 * after every switch so the PA/supply writes which follow are redirected
	 * to the address which is actually listening.
	 */
	if (spx_forced_attached && !spx_no_assign && spx_write_dev0 < 0)
		spx_refresh_amp_addr(ctrl);

	if (!spx_verify_bank)
		return 0;

	/* Windows qcauddev8180 handshake: after the bank-switch broadcast,
	 * COMP_STATUS bits[5:4] must read 2 (5x5 retry loop at 0x14009bb54).
	 * Writes on this bus always report CMD_OK even when dropped, so a
	 * lost bank switch is otherwise invisible and strands the bus on the
	 * unprogrammed bank -> silent/static runs. On failure re-issue the
	 * SCP_FRAMECTRL broadcast; bus->params banks are already flipped
	 * here, so curr_bank is the bank we just switched to.
	 */
	for (outer = 0; outer < 5; outer++) {
		for (inner = 0; inner < 5; inner++) {
			if (!ctrl->reg_read(ctrl, SWRM_COMP_STATUS, &val) &&
			    FIELD_GET(GENMASK(5, 4), val) == 2)
				return 0;
			usleep_range(200, 400);
		}
		data = sdw_find_col_index(bus->params.col) |
		       (sdw_find_row_index(bus->params.row) << 3);
		dev_warn(ctrl->dev,
			 "SPX: bank switch unconfirmed (COMP_STATUS=0x%x), re-broadcasting (try %d)\n",
			 val, outer + 1);
		qcom_swrm_cmd_fifo_wr_cmd(ctrl, data, SDW_BROADCAST_DEV_NUM,
					  bus->params.curr_bank ?
						SDW_SCP_FRAMECTRL_B1 :
						SDW_SCP_FRAMECTRL_B0);
	}
	/* Never fail the stream over this; the log is the diagnostic. */
	return 0;
}

static int qcom_swrm_port_params(struct sdw_bus *bus,
				 struct sdw_port_params *p_params,
				 unsigned int bank)
{
	struct qcom_swrm_ctrl *ctrl = to_qcom_sdw(bus);
	u32 offset = ctrl->reg_layout[SWRM_OFFSET_DP_BLOCK_CTRL_1];

	if (spx_win_transport && !p_params->bps)
		return 0;

	return ctrl->reg_write(ctrl, SWRM_DPn_BLOCK_CTRL_1(offset, p_params->num),
				p_params->bps - 1);
}

static int qcom_swrm_transport_params_bank(struct sdw_bus *bus,
					   struct sdw_transport_params *params,
					   enum sdw_reg_bank bank)
{
	struct qcom_swrm_ctrl *ctrl = to_qcom_sdw(bus);
	struct qcom_swrm_port_config *pcfg;
	u32 value;
	int reg, offset = ctrl->reg_layout[SWRM_OFFSET_DP_PORT_CTRL_BANK];
	int ret;

	reg = SWRM_DPn_PORT_CTRL_BANK(offset, params->port_num, bank);

	pcfg = &ctrl->pconfig[params->port_num];

	value = ((params->port_num == 1 && spx_port_off1 >= 0) ?
		 spx_port_off1 : pcfg->off1) << SWRM_DP_PORT_CTRL_OFFSET1_SHFT;
	value |= ((params->port_num == 1 && spx_port_off2 >= 0) ?
		  spx_port_off2 : pcfg->off2) << SWRM_DP_PORT_CTRL_OFFSET2_SHFT;
	value |= ((params->port_num == 1 && spx_port_si >= 0) ?
		  spx_port_si : pcfg->si) & 0xff;

	ret = ctrl->reg_write(ctrl, reg, value);
	if (ret)
		goto err;

	if (((params->port_num == 1 && spx_port_si >= 0) ?
	     spx_port_si : pcfg->si) > 0xff) {
		value = (((params->port_num == 1 && spx_port_si >= 0) ?
			  spx_port_si : pcfg->si) >> 8) & 0xff;
		offset = ctrl->reg_layout[SWRM_OFFSET_DP_SAMPLECTRL2_BANK];
		reg = SWRM_DPn_SAMPLECTRL2_BANK(offset, params->port_num, bank);
		ret = ctrl->reg_write(ctrl, reg, value);
		if (ret)
			goto err;
	}

	if (pcfg->lane_control != SWR_INVALID_PARAM) {
		offset = ctrl->reg_layout[SWRM_OFFSET_DP_PORT_CTRL_2_BANK];
		reg = SWRM_DPn_PORT_CTRL_2_BANK(offset, params->port_num, bank);

		value = pcfg->lane_control;
		ret = ctrl->reg_write(ctrl, reg, value);
		if (ret)
			goto err;
	}

	if (pcfg->blk_group_count != SWR_INVALID_PARAM) {
		offset = ctrl->reg_layout[SWRM_OFFSET_DP_BLOCK_CTRL2_BANK];

		reg = SWRM_DPn_BLOCK_CTRL2_BANK(offset, params->port_num, bank);

		value = pcfg->blk_group_count;
		ret = ctrl->reg_write(ctrl, reg, value);
		if (ret)
			goto err;
	}

	offset = ctrl->reg_layout[SWRM_OFFSET_DP_PORT_HCTRL_BANK];
	reg = SWRM_DPn_PORT_HCTRL_BANK(offset, params->port_num, bank);

	if (pcfg->hstart != SWR_INVALID_PARAM && pcfg->hstop != SWR_INVALID_PARAM) {
		value = (pcfg->hstop << 4) | pcfg->hstart;
		ret = ctrl->reg_write(ctrl, reg, value);
	} else if (!spx_win_transport) {
		value = (SWR_HSTOP_MAX_VAL << 4) | SWR_HSTART_MIN_VAL;
		ret = ctrl->reg_write(ctrl, reg, value);
	}

	if (ret)
		goto err;

	if ((params->port_num == 1 && spx_port_bp >= 0) ||
	    pcfg->bp_mode != SWR_INVALID_PARAM) {
		offset = ctrl->reg_layout[SWRM_OFFSET_DP_BLOCK_CTRL3_BANK];
		reg = SWRM_DPn_BLOCK_CTRL3_BANK(offset, params->port_num, bank);
		ret = ctrl->reg_write(ctrl, reg,
				      (params->port_num == 1 && spx_port_bp >= 0) ?
				      spx_port_bp : pcfg->bp_mode);
	}

err:
	return ret;
}

/* SPX: program both banks identically so a lost bank switch cannot land the
 * bus on a bank whose ports were never configured (see spx_mirror_banks). */
static int qcom_swrm_transport_params(struct sdw_bus *bus,
				      struct sdw_transport_params *params,
				      enum sdw_reg_bank bank)
{
	int ret;

	ret = qcom_swrm_transport_params_bank(bus, params, bank);
	if (!ret && spx_mirror_banks)
		ret = qcom_swrm_transport_params_bank(bus, params,
				bank == SDW_BANK0 ? SDW_BANK1 : SDW_BANK0);
	return ret;
}

static int qcom_swrm_port_enable_bank(struct sdw_bus *bus,
				      struct sdw_enable_ch *enable_ch,
				      unsigned int bank)
{
	u32 reg;
	struct qcom_swrm_ctrl *ctrl = to_qcom_sdw(bus);
	u32 val;
	u32 offset = ctrl->reg_layout[SWRM_OFFSET_DP_PORT_CTRL_BANK];

	reg = SWRM_DPn_PORT_CTRL_BANK(offset, enable_ch->port_num, bank);

	/*
	 * SPX: never read-modify-write this register. The AHB bridge read path
	 * on this codec-internal master returns stale/zero data, so the RMW can
	 * rewrite si/offset1/offset2 with junk while leaving the channel
	 * enabled -- audio that still plays but is corrupt. Windows composes
	 * the whole word from its port table and writes it in one shot; do the
	 * same from ctrl->pconfig[].
	 */
	if (spx_win_transport) {
		struct qcom_swrm_port_config *pcfg =
			&ctrl->pconfig[enable_ch->port_num];

		val = (pcfg->off1 << SWRM_DP_PORT_CTRL_OFFSET1_SHFT) |
		      (pcfg->off2 << SWRM_DP_PORT_CTRL_OFFSET2_SHFT) |
		      (pcfg->si & 0xff);
		if (enable_ch->enable)
			val |= enable_ch->ch_mask <<
			       SWRM_DP_PORT_CTRL_EN_CHAN_SHFT;

		return ctrl->reg_write(ctrl, reg, val);
	}

	ctrl->reg_read(ctrl, reg, &val);

	if (enable_ch->enable)
		val |= (enable_ch->ch_mask << SWRM_DP_PORT_CTRL_EN_CHAN_SHFT);
	else
		val &= ~(0xff << SWRM_DP_PORT_CTRL_EN_CHAN_SHFT);

	return ctrl->reg_write(ctrl, reg, val);
}

static int qcom_swrm_port_enable(struct sdw_bus *bus,
				 struct sdw_enable_ch *enable_ch,
				 unsigned int bank)
{
	struct qcom_swrm_ctrl *ctrl = to_qcom_sdw(bus);
	int ret;

	ret = qcom_swrm_port_enable_bank(bus, enable_ch, bank);
	if (!ret && spx_mirror_banks)
		ret = qcom_swrm_port_enable_bank(bus, enable_ch, bank ? 0 : 1);
	else if (!ret && spx_shadow_dp1_enable && enable_ch->port_num) {
		dev_info(ctrl->dev,
			 "SPX: shadow master DP%u ChannelEn value=0x%02x bank %u->%u\n",
			 enable_ch->port_num,
			 enable_ch->enable ? enable_ch->ch_mask : 0,
			 bank, bank ? 0 : 1);
		ret = qcom_swrm_port_enable_bank(bus, enable_ch, bank ? 0 : 1);
	}
	return ret;
}

static const struct sdw_master_port_ops qcom_swrm_port_ops = {
	.dpn_set_port_params = qcom_swrm_port_params,
	.dpn_set_port_transport_params = qcom_swrm_transport_params,
	.dpn_port_enable_ch = qcom_swrm_port_enable,
};

static const struct sdw_master_ops qcom_swrm_ops = {
	.read_prop = qcom_swrm_read_prop,
	.xfer_msg = qcom_swrm_xfer_msg,
	.pre_bank_switch = qcom_swrm_pre_bank_switch,
	.post_bank_switch = qcom_swrm_post_bank_switch,
};

static int qcom_swrm_compute_params(struct sdw_bus *bus, struct sdw_stream_runtime *stream)
{
	struct qcom_swrm_ctrl *ctrl = to_qcom_sdw(bus);
	struct sdw_master_runtime *m_rt;
	struct sdw_slave_runtime *s_rt;
	struct sdw_port_runtime *p_rt;
	struct qcom_swrm_port_config *pcfg;
	struct sdw_slave *slave;
	unsigned int m_port;
	int i = 1;

	list_for_each_entry(m_rt, &bus->m_rt_list, bus_node) {
		list_for_each_entry(p_rt, &m_rt->port_list, port_node) {
			pcfg = &ctrl->pconfig[p_rt->num];
			p_rt->transport_params.port_num = p_rt->num;
			if (pcfg->word_length != SWR_INVALID_PARAM) {
				sdw_fill_port_params(&p_rt->port_params,
					     p_rt->num,  pcfg->word_length + 1,
					     SDW_PORT_FLOW_MODE_ISOCH,
					     SDW_PORT_DATA_MODE_NORMAL);
			}

		}

		list_for_each_entry(s_rt, &m_rt->slave_rt_list, m_rt_node) {
			slave = s_rt->slave;
			list_for_each_entry(p_rt, &s_rt->port_list, port_node) {
				m_port = slave->m_port_map[p_rt->num];
				/* port config starts at offset 0 so -1 from actual port number */
				if (m_port)
					pcfg = &ctrl->pconfig[m_port];
				else
					pcfg = &ctrl->pconfig[i];
				p_rt->transport_params.port_num = p_rt->num;
				p_rt->transport_params.sample_interval =
					(((!m_port ? i : m_port) == 1 &&
					   spx_port_si >= 0) ? spx_port_si :
					  pcfg->si) + 1;
				p_rt->transport_params.offset1 =
					((!m_port ? i : m_port) == 1 &&
					 spx_port_off1 >= 0) ? spx_port_off1 :
					 pcfg->off1;
				p_rt->transport_params.offset2 =
					((!m_port ? i : m_port) == 1 &&
					 spx_port_off2 >= 0) ? spx_port_off2 :
					 pcfg->off2;
				p_rt->transport_params.blk_pkg_mode =
					((!m_port ? i : m_port) == 1 &&
					 spx_port_bp >= 0) ? spx_port_bp :
					 pcfg->bp_mode;
				/*
				 * SPX: with no qcom,ports-block-pack-mode in
				 * DT this stays SWR_INVALID_PARAM (0xff), and
				 * the bus layer then writes 0xff into the
				 * slave's DPn_BlockCtrl3 -- bit0 is the real
				 * BlockPackingMode and bits 7:1 are reserved.
				 * Windows never writes the register; 0 is its
				 * reset value.
				 */
				if (spx_win_transport &&
				    p_rt->transport_params.blk_pkg_mode ==
					SWR_INVALID_PARAM)
					p_rt->transport_params.blk_pkg_mode = 0;
				p_rt->transport_params.blk_grp_ctrl = pcfg->blk_group_count;

				p_rt->transport_params.hstart = pcfg->hstart;
				p_rt->transport_params.hstop = pcfg->hstop;
				p_rt->transport_params.lane_ctrl = pcfg->lane_control;
				if (pcfg->word_length != SWR_INVALID_PARAM) {
					sdw_fill_port_params(&p_rt->port_params,
						     p_rt->num,
						     pcfg->word_length + 1,
						     SDW_PORT_FLOW_MODE_ISOCH,
						     SDW_PORT_DATA_MODE_NORMAL);
				}
				i++;
			}
		}
	}

	return 0;
}

static u32 qcom_swrm_freq_tbl[MAX_FREQ_NUM] = {
	DEFAULT_CLK_FREQ,
};

static void qcom_swrm_stream_free_ports(struct qcom_swrm_ctrl *ctrl,
					struct sdw_stream_runtime *stream)
{
	struct sdw_master_runtime *m_rt;
	struct sdw_port_runtime *p_rt;
	unsigned long *port_mask;

	mutex_lock(&ctrl->port_lock);

	list_for_each_entry(m_rt, &stream->master_list, stream_node) {
		port_mask = &ctrl->port_mask;
		list_for_each_entry(p_rt, &m_rt->port_list, port_node)
			clear_bit(p_rt->num, port_mask);
	}

	mutex_unlock(&ctrl->port_lock);
}

static int qcom_swrm_stream_alloc_ports(struct qcom_swrm_ctrl *ctrl,
					struct sdw_stream_runtime *stream,
				       struct snd_pcm_hw_params *params,
				       int direction)
{
	struct sdw_stream_config sconfig;
	struct sdw_master_runtime *m_rt;
	struct sdw_slave_runtime *s_rt;
	struct sdw_port_runtime *p_rt;
	struct sdw_slave *slave;
	unsigned long *port_mask;
	int maxport, pn, nports = 0;
	unsigned int m_port;
	struct sdw_port_config *pconfig __free(kfree) = kzalloc_objs(*pconfig,
								     ctrl->nports);
	if (!pconfig)
		return -ENOMEM;

	if (direction == SNDRV_PCM_STREAM_CAPTURE)
		sconfig.direction = SDW_DATA_DIR_TX;
	else
		sconfig.direction = SDW_DATA_DIR_RX;

	/* hw parameters will be ignored as we only support PDM */
	sconfig.ch_count = 1;
	sconfig.frame_rate = params_rate(params);
	sconfig.type = stream->type;
	sconfig.bps = 1;

	guard(mutex)(&ctrl->port_lock);

	list_for_each_entry(m_rt, &stream->master_list, stream_node) {
		/*
		 * For streams with multiple masters:
		 * Allocate ports only for devices connected to this master.
		 * Such devices will have ports allocated by their own master
		 * and its qcom_swrm_stream_alloc_ports() call.
		 */
		if (ctrl->bus.id != m_rt->bus->id)
			continue;

		port_mask = &ctrl->port_mask;
		maxport = ctrl->nports;

		list_for_each_entry(s_rt, &m_rt->slave_rt_list, m_rt_node) {
			slave = s_rt->slave;
			list_for_each_entry(p_rt, &s_rt->port_list, port_node) {
				m_port = slave->m_port_map[p_rt->num];
				/* Port numbers start from 1 - 14*/
				if (m_port)
					pn = m_port;
				else
					pn = find_first_zero_bit(port_mask, maxport);

				if (pn >= maxport) {
					dev_err(ctrl->dev, "All ports busy\n");
					return -EBUSY;
				}
				set_bit(pn, port_mask);
				pconfig[nports].num = pn;
				pconfig[nports].ch_mask = p_rt->ch_mask;
				nports++;
			}
		}
	}

	sdw_stream_add_master(&ctrl->bus, &sconfig, pconfig,
			      nports, stream);

	return 0;
}

static int qcom_swrm_hw_params(struct snd_pcm_substream *substream,
			       struct snd_pcm_hw_params *params,
			      struct snd_soc_dai *dai)
{
	struct qcom_swrm_ctrl *ctrl = dev_get_drvdata(dai->dev);
	struct sdw_stream_runtime *sruntime = ctrl->sruntime[dai->id];
	int ret;

	ret = qcom_swrm_stream_alloc_ports(ctrl, sruntime, params,
					   substream->stream);
	if (ret)
		qcom_swrm_stream_free_ports(ctrl, sruntime);

	return ret;
}

static int qcom_swrm_hw_free(struct snd_pcm_substream *substream,
			     struct snd_soc_dai *dai)
{
	struct qcom_swrm_ctrl *ctrl = dev_get_drvdata(dai->dev);
	struct sdw_stream_runtime *sruntime = ctrl->sruntime[dai->id];

	qcom_swrm_stream_free_ports(ctrl, sruntime);
	sdw_stream_remove_master(&ctrl->bus, sruntime);

	return 0;
}

static int qcom_swrm_set_sdw_stream(struct snd_soc_dai *dai,
				    void *stream, int direction)
{
	struct qcom_swrm_ctrl *ctrl = dev_get_drvdata(dai->dev);

	ctrl->sruntime[dai->id] = stream;

	return 0;
}

static void *qcom_swrm_get_sdw_stream(struct snd_soc_dai *dai, int direction)
{
	struct qcom_swrm_ctrl *ctrl = dev_get_drvdata(dai->dev);

	return ctrl->sruntime[dai->id];
}

static int qcom_swrm_startup(struct snd_pcm_substream *substream,
			     struct snd_soc_dai *dai)
{
	struct qcom_swrm_ctrl *ctrl = dev_get_drvdata(dai->dev);
	int ret;

	ret = pm_runtime_get_sync(ctrl->dev);
	if (ret < 0 && ret != -EACCES) {
		dev_err_ratelimited(ctrl->dev,
				    "pm_runtime_get_sync failed in %s, ret %d\n",
				    __func__, ret);
		pm_runtime_put_noidle(ctrl->dev);
		return ret;
	}

	return 0;
}

static void qcom_swrm_shutdown(struct snd_pcm_substream *substream,
			       struct snd_soc_dai *dai)
{
	struct qcom_swrm_ctrl *ctrl = dev_get_drvdata(dai->dev);

	swrm_wait_for_wr_fifo_done(ctrl);
	pm_runtime_mark_last_busy(ctrl->dev);
	pm_runtime_put_autosuspend(ctrl->dev);

}

static const struct snd_soc_dai_ops qcom_swrm_pdm_dai_ops = {
	.hw_params = qcom_swrm_hw_params,
	.hw_free = qcom_swrm_hw_free,
	.startup = qcom_swrm_startup,
	.shutdown = qcom_swrm_shutdown,
	.set_stream = qcom_swrm_set_sdw_stream,
	.get_stream = qcom_swrm_get_sdw_stream,
};

static const struct snd_soc_component_driver qcom_swrm_dai_component = {
	.name = "soundwire",
};

static int qcom_swrm_register_dais(struct qcom_swrm_ctrl *ctrl)
{
	int num_dais = ctrl->num_dout_ports + ctrl->num_din_ports;
	struct snd_soc_dai_driver *dais;
	struct snd_soc_pcm_stream *stream;
	struct device *dev = ctrl->dev;
	int i;

	ctrl->sruntime = devm_kcalloc(dev, num_dais, sizeof(*ctrl->sruntime), GFP_KERNEL);
	if (!ctrl->sruntime)
		return -ENOMEM;

	/* PDM dais are only tested for now */
	dais = devm_kcalloc(dev, num_dais, sizeof(*dais), GFP_KERNEL);
	if (!dais)
		return -ENOMEM;

	for (i = 0; i < num_dais; i++) {
		dais[i].name = devm_kasprintf(dev, GFP_KERNEL, "SDW Pin%d", i);
		if (!dais[i].name)
			return -ENOMEM;

		if (i < ctrl->num_dout_ports)
			stream = &dais[i].playback;
		else
			stream = &dais[i].capture;

		stream->channels_min = 1;
		stream->channels_max = 1;
		stream->rates = SNDRV_PCM_RATE_48000;
		stream->formats = SNDRV_PCM_FMTBIT_S16_LE;

		dais[i].ops = &qcom_swrm_pdm_dai_ops;
		dais[i].id = i;
	}

	return devm_snd_soc_register_component(ctrl->dev,
						&qcom_swrm_dai_component,
						dais, num_dais);
}

static int qcom_swrm_get_port_config(struct qcom_swrm_ctrl *ctrl)
{
	struct device_node *np = ctrl->dev->of_node;
	struct qcom_swrm_port_config *pcfg;
	int i, ret, val;

	ctrl->reg_read(ctrl, SWRM_COMP_PARAMS, &val);

	ctrl->num_dout_ports = FIELD_GET(SWRM_COMP_PARAMS_DOUT_PORTS_MASK, val);
	ctrl->num_din_ports = FIELD_GET(SWRM_COMP_PARAMS_DIN_PORTS_MASK, val);

	/*
	 * SPX: the WCD9340 codec-internal SWR master does not service APPS
	 * reads of COMP_PARAMS over SLIMbus (returns 0/garbage), so the
	 * hardware-reported port counts read as 0 and the sanity checks below
	 * wrongly reject the (authoritative) DT port counts. Log the raw value
	 * and, under spx_core_enum, treat the DT as the source of truth.
	 */
	if (spx_core_enum)
		dev_info(ctrl->dev,
			 "SPX: COMP_PARAMS raw=0x%x -> hw dout=%d din=%d (DT will override)\n",
			 val, ctrl->num_dout_ports, ctrl->num_din_ports);

	ret = of_property_read_u32(np, "qcom,din-ports", &val);
	if (!ret) { /* only if present */
		if (val != ctrl->num_din_ports) {
			dev_err(ctrl->dev, "din-ports (%d) mismatch with controller (%d)",
				val, ctrl->num_din_ports);
		}

		ctrl->num_din_ports = val;
	}

	ret = of_property_read_u32(np, "qcom,dout-ports", &val);
	if (!ret) { /* only if present */
		if (val != ctrl->num_dout_ports) {
			dev_err(ctrl->dev, "dout-ports (%d) mismatch with controller (%d)",
				val, ctrl->num_dout_ports);
		}

		ctrl->num_dout_ports = val;
	}

	ctrl->nports = ctrl->num_dout_ports + ctrl->num_din_ports;

	ctrl->pconfig = devm_kcalloc(ctrl->dev, ctrl->nports + 1,
					sizeof(*ctrl->pconfig), GFP_KERNEL);
	if (!ctrl->pconfig)
		return -ENOMEM;

	set_bit(0, &ctrl->port_mask);
	/* Valid port numbers are from 1, so mask out port 0 explicitly */
	for (i = 0; i < ctrl->nports; i++) {
		pcfg = &ctrl->pconfig[i + 1];

		ret = of_property_read_u8_index(np, "qcom,ports-offset1", i, &pcfg->off1);
		if (ret)
			return ret;

		ret = of_property_read_u8_index(np, "qcom,ports-offset2", i, &pcfg->off2);
		if (ret)
			return ret;

		ret = of_property_read_u8_index(np, "qcom,ports-sinterval-low", i, (u8 *)&pcfg->si);
		if (ret) {
			ret = of_property_read_u16_index(np, "qcom,ports-sinterval", i, &pcfg->si);
			if (ret)
				return ret;
		}

		ret = of_property_read_u8_index(np, "qcom,ports-block-pack-mode",
						i, &pcfg->bp_mode);
		if (ret) {
			if (ctrl->version <= SWRM_VERSION_1_3_0)
				pcfg->bp_mode = SWR_INVALID_PARAM;
			else
				return ret;
		}

		/* Optional properties */
		pcfg->hstart = SWR_INVALID_PARAM;
		pcfg->hstop = SWR_INVALID_PARAM;
		pcfg->word_length = SWR_INVALID_PARAM;
		pcfg->blk_group_count = SWR_INVALID_PARAM;
		pcfg->lane_control = SWR_INVALID_PARAM;

		of_property_read_u8_index(np, "qcom,ports-hstart", i, &pcfg->hstart);

		of_property_read_u8_index(np, "qcom,ports-hstop", i, &pcfg->hstop);

		of_property_read_u8_index(np, "qcom,ports-word-length", i, &pcfg->word_length);

		of_property_read_u8_index(np, "qcom,ports-block-group-count",
					i, &pcfg->blk_group_count);

		of_property_read_u8_index(np, "qcom,ports-lane-control", i, &pcfg->lane_control);
	}

	return 0;
}

#ifdef CONFIG_DEBUG_FS
static int swrm_reg_show(struct seq_file *s_file, void *data)
{
	struct qcom_swrm_ctrl *ctrl = s_file->private;
	int reg, reg_val, ret;

	ret = pm_runtime_get_sync(ctrl->dev);
	if (ret < 0 && ret != -EACCES) {
		dev_err_ratelimited(ctrl->dev,
				    "pm_runtime_get_sync failed in %s, ret %d\n",
				    __func__, ret);
		pm_runtime_put_noidle(ctrl->dev);
		return ret;
	}

	for (reg = 0; reg <= ctrl->max_reg; reg += 4) {
		ctrl->reg_read(ctrl, reg, &reg_val);
		seq_printf(s_file, "0x%.3x: 0x%.2x\n", reg, reg_val);
	}
	pm_runtime_mark_last_busy(ctrl->dev);
	pm_runtime_put_autosuspend(ctrl->dev);


	return 0;
}
DEFINE_SHOW_ATTRIBUTE(swrm_reg);
#endif

static int qcom_swrm_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct sdw_master_prop *prop;
	struct sdw_bus_params *params;
	struct qcom_swrm_ctrl *ctrl;
	const struct qcom_swrm_data *data;
	int ret;
	u32 default_cols, default_rows, val;

	ctrl = devm_kzalloc(dev, sizeof(*ctrl), GFP_KERNEL);
	if (!ctrl)
		return -ENOMEM;
	mutex_init(&ctrl->ahb_lock);
	mutex_init(&ctrl->controller_lock);

	/* Fail fast on an out-of-range spx_idle_clk_stop_ms cmdline value
	 * instead of silently ignoring it at activation time.
	 */
	if (spx_idle_clk_stop_ms &&
	    (spx_idle_clk_stop_ms < 100 || spx_idle_clk_stop_ms > 600000)) {
		dev_err(dev,
			"SPX: spx_idle_clk_stop_ms=%d outside 100..600000\n",
			spx_idle_clk_stop_ms);
		return -EINVAL;
	}

	/*
	 * Match the live qcauddev8180.sys path.  It exposes both physical
	 * slaves to one hardware auto-enumeration pass; it never invents an
	 * attachment or mirrors traffic between device addresses.
	 */
	ctrl->spx_windows_init = spx_exact_windows_init &&
		of_machine_is_compatible("microsoft,surface-pro-x");
	if (ctrl->spx_windows_init) {
		spx_core_enum = 0;
		spx_force_attach = 0;
		spx_blind_attach = 0;
		spx_watchdog = 0;
		spx_win_transport = 1;
		spx_clk_div = 3;
		spx_dr_freq = 0;
		spx_mirror_banks = 1;
		spx_write_twice = 0;
		spx_bank_switch_repeats = 3;
		spx_write_dev0 = -1;
		spx_no_assign = 0;
		spx_forced_attached = false;
		dev_info(dev, "SPX: Windows-compatible one-shot SoundWire enumeration\n");
	} else if (of_machine_is_compatible("microsoft,surface-pro-x")) {
		dev_info(dev,
			 "SPX: stable single-amp mode core_enum=%d force_attach=%d no_assign=%d\n",
			 spx_core_enum, spx_force_attach, spx_no_assign);
	}

	data = of_device_get_match_data(dev);
	ctrl->max_reg = data->max_reg;
	ctrl->reg_layout = data->reg_layout;
	default_rows = data->default_rows;
	default_cols = data->default_cols;
	if (ctrl->spx_windows_init) {
		default_rows = 48;
		default_cols = 2;
		dev_info(dev,
			 "SPX: fixed dual SoundWire frame geometry 48x2/divider-3\n");
	}
	ctrl->rows_index = sdw_find_row_index(default_rows);
	ctrl->cols_index = sdw_find_col_index(default_cols);
#if IS_REACHABLE(CONFIG_SLIMBUS)
	if (dev->parent->bus == &slimbus_bus) {
#else
	if (false) {
#endif
		ctrl->reg_read = qcom_swrm_ahb_reg_read;
		ctrl->reg_write = qcom_swrm_ahb_reg_write;
		ctrl->regmap = dev_get_regmap(dev->parent, NULL);
		if (!ctrl->regmap)
			return -EINVAL;
	} else {
		ctrl->reg_read = qcom_swrm_cpu_reg_read;
		ctrl->reg_write = qcom_swrm_cpu_reg_write;
		ctrl->mmio = devm_platform_ioremap_resource(pdev, 0);
		if (IS_ERR(ctrl->mmio))
			return PTR_ERR(ctrl->mmio);
	}

	if (data->sw_clk_gate_required) {
		ctrl->audio_cgcr = devm_reset_control_get_optional_exclusive(dev, "swr_audio_cgcr");
		if (IS_ERR(ctrl->audio_cgcr)) {
			dev_err(dev, "Failed to get cgcr reset ctrl required for SW gating\n");
			ret = PTR_ERR(ctrl->audio_cgcr);
			goto err_init;
		}
	}

	ctrl->irq = of_irq_get(dev->of_node, 0);
	if (ctrl->irq < 0) {
		dev_warn(dev, "No IRQ found, SoundWire interrupts will not be available\n");
		ctrl->irq = 0;
	}

	ctrl->hclk = devm_clk_get(dev, "iface");
	if (IS_ERR(ctrl->hclk)) {
		ret = dev_err_probe(dev, PTR_ERR(ctrl->hclk), "unable to get iface clock\n");
		goto err_init;
	}

	clk_prepare_enable(ctrl->hclk);

	/*
	 * Match qcauddev8180's constructor ordering exactly: clock enable
	 * (WCD 0xd43 = 1), then ACCESS_CFG = 0x0f, then the first AHB bridge
	 * transaction.  Do not leave this to the documented reset default:
	 * Windows deliberately restores it on every controller construction.
	 */
	if (ctrl->spx_windows_init) {
		ret = regmap_write(ctrl->regmap, SWRM_AHB_BRIDGE_ACCESS_CFG,
				   0x0f);
		if (ret) {
			dev_err(dev,
				"SPX: failed to configure SoundWire AHB bridge: %d\n",
				ret);
			goto err_clk;
		}
	}

	ctrl->dev = dev;
	dev_set_drvdata(&pdev->dev, ctrl);
	mutex_init(&ctrl->port_lock);
	init_completion(&ctrl->broadcast);
	init_completion(&ctrl->enumeration);

	ctrl->bus.ops = &qcom_swrm_ops;
	ctrl->bus.port_ops = &qcom_swrm_port_ops;
	ctrl->bus.compute_params = &qcom_swrm_compute_params;
	ctrl->bus.clk_stop_timeout = 300;

	ret = qcom_swrm_get_port_config(ctrl);
	if (ret)
		goto err_clk;

	params = &ctrl->bus.params;
	/*
	 * SPX: SoundWire clocks data on both edges, so the bus DATA RATE is
	 * twice the 9.6 MHz clock. The Windows master computes its frame rate
	 * from 2*9.6 MHz (= 25 kHz at 48x16), and the sample intervals in our
	 * DT were derived from that figure -- but this driver seeds dr_freq
	 * with the clock, halving the rate the core reasons about. A 440 Hz
	 * tone that changes pitch when another port is allocated is the
	 * symptom. spx_dr_freq lets us pin the data rate explicitly.
	 */
	params->max_dr_freq = spx_dr_freq ? spx_dr_freq : DEFAULT_CLK_FREQ;
	params->curr_dr_freq = params->max_dr_freq;
	params->col = default_cols;
	params->row = default_rows;
	ctrl->reg_read(ctrl, SWRM_MCP_STATUS, &val);
	params->curr_bank = val & SWRM_MCP_STATUS_BANK_NUM_MASK;
	params->next_bank = !params->curr_bank;

	prop = &ctrl->bus.prop;
	prop->max_clk_freq = DEFAULT_CLK_FREQ;
	prop->mclk_freq = DEFAULT_CLK_FREQ;
	prop->num_clk_gears = 0;
	prop->num_clk_freq = MAX_FREQ_NUM;
	prop->clk_freq = &qcom_swrm_freq_tbl[0];
	prop->default_col = default_cols;
	prop->default_row = default_rows;

	ctrl->reg_read(ctrl, SWRM_COMP_HW_VERSION, &ctrl->version);

	if (ctrl->irq > 0) {
		ret = devm_request_threaded_irq(dev, ctrl->irq, NULL,
						qcom_swrm_irq_handler,
						IRQF_TRIGGER_RISING |
						IRQF_ONESHOT,
						"soundwire", ctrl);
		if (ret) {
			dev_err(dev, "Failed to request soundwire irq\n");
			goto err_clk;
		}
	}

	ctrl->wake_irq = of_irq_get(dev->of_node, 1);
	if (ctrl->wake_irq > 0) {
		ret = devm_request_threaded_irq(dev, ctrl->wake_irq, NULL,
						qcom_swrm_wake_irq_handler,
						IRQF_TRIGGER_HIGH | IRQF_ONESHOT,
						"swr_wake_irq", ctrl);
		if (ret) {
			dev_err(dev, "Failed to request soundwire wake irq\n");
			goto err_clk;
		}
	}

	ctrl->bus.controller_id = -1;

	if (ctrl->version > SWRM_VERSION_1_3_0) {
		ctrl->reg_read(ctrl, SWRM_COMP_MASTER_ID, &val);
		ctrl->bus.controller_id = val;
	}

	ret = sdw_bus_master_add(&ctrl->bus, dev, dev->fwnode);
	if (ret) {
		dev_err(dev, "Failed to register Soundwire controller (%d)\n",
			ret);
		goto err_clk;
	}

	ret = qcom_swrm_init(ctrl);
	if (ret) {
		dev_err(dev, "SoundWire controller initialization failed (%d)\n",
			ret);
		sdw_bus_master_delete(&ctrl->bus);
		goto err_clk;
	}

	/*
	 * The Linux IRQ path clears status late and suppresses an unchanged
	 * cached status, so the sole CHANGE edge can be consumed while probe is
	 * still finishing. Capture the hardware-auto-enumerator result
	 * synchronously after the complete Windows init sequence. Use the same
	 * single status snapshot for table mapping, as qcauddev8180 does.
	 */
	if (ctrl->spx_windows_init) {
		mutex_lock(&ctrl->controller_lock);
		dev_info(ctrl->dev,
			 "SPX: handing stable dual status snapshot %#x to core\n",
			 ctrl->slave_status);
		ret = qcom_swrm_enumerate(&ctrl->bus);
		if (!ret && test_bit(1, ctrl->bus.assigned) &&
		    test_bit(2, ctrl->bus.assigned))
			ret = sdw_handle_slave_status(&ctrl->bus, ctrl->status);
		else if (!ret)
			ret = -ENODEV;
		if (!ret) {
			spx_clk_div = 3;
			ctrl->spx_runtime_handoff_pending = true;
			ctrl->spx_runtime_mirror_pending = false;
			ctrl->reg_write(ctrl, SWRM_ENUMERATOR_CFG_ADDR, 0);
			ctrl->intr_mask =
				SWRM_INTERRUPT_STATUS_SPECIAL_CMD_ID_FINISHED;
			ctrl->reg_write(ctrl,
				ctrl->reg_layout[SWRM_REG_INTERRUPT_MASK_ADDR],
				ctrl->intr_mask);
			ctrl->reg_write(ctrl,
				ctrl->reg_layout[SWRM_REG_INTERRUPT_CLEAR], ~0U);
			if (ctrl->irq > 0)
				ctrl->reg_write(ctrl,
					ctrl->reg_layout[SWRM_REG_INTERRUPT_CPU_EN],
					ctrl->intr_mask);
			dev_info(ctrl->dev,
				 "SPX: dual enumeration frozen on 48x2/divider-3; coordinated 48x16/divider-0 handoff pending\n");
		}
		mutex_unlock(&ctrl->controller_lock);
		if (ret) {
			dev_err(ctrl->dev,
				"SPX: stable dual-slave core handoff failed (%d)\n",
				ret);
			sdw_bus_master_delete(&ctrl->bus);
			goto err_clk;
		}
	}

	wait_for_completion_timeout(&ctrl->enumeration,
				    msecs_to_jiffies(TIMEOUT_MS));
	/*
	 * SPX: the wcd934x internal SoundWire master has no usable IRQ (the
	 * codec INT is not wired as a Linux irq), so the enumeration completion
	 * above always times out -- the slave-status/enumerate path normally
	 * runs only from qcom_swrm_irq_handler(). Without it the WSA881x amps
	 * stay UNATTACHED forever. Do a one-shot software enumeration kick here
	 * for the IRQ-less case, mirroring the NEW_SLAVE_ATTACHED IRQ path. HW
	 * auto-enum (SWRM_ENUMERATOR_CFG_ADDR=1 in qcom_swrm_init) needs a moment
	 * to assign device numbers after the bus reset.
	 */
	/*
	 * SPX: always init the enum work + the global ctrl so the spx_reenum
	 * live re-trigger works on ANY boot (IRQ or polled). Only auto-SCHEDULE
	 * the boot-time poll when there is no IRQ (the no-IRQ master can't
	 * enumerate otherwise). The HW auto-enumerator in qcom_swrm_init() runs at
	 * master probe -- but the wsa881x slaves are only powered when wsa881x
	 * probes (AFTER us), so the boot-time scan races; spx_swrm_enum_work
	 * re-runs it on a live bus.
	 */
	/*
	 * Always arm the enum work + spx_dbg_ctrl so spx_reenum / force_attach
	 * work even when the boot cmdline omitted spx_core_enum.
	 */
	INIT_DELAYED_WORK(&ctrl->spx_enum_work, spx_swrm_enum_work);
	INIT_DELAYED_WORK(&ctrl->spx_wd_work, spx_wd_work_fn);
	mutex_lock(&spx_dbg_lock);
	spx_dbg_ctrl = ctrl;
	mutex_unlock(&spx_dbg_lock);
	if (spx_core_enum || spx_force_attach) {
		if (ctrl->irq <= 0 || spx_force_attach)
			schedule_delayed_work(&ctrl->spx_enum_work,
					      msecs_to_jiffies(300));
	}
	ret = qcom_swrm_register_dais(ctrl);
	if (ret)
		goto err_master_add;

	dev_dbg(dev, "Qualcomm Soundwire controller v%x.%x.%x registered\n",
		(ctrl->version >> 24) & 0xff, (ctrl->version >> 16) & 0xff,
		ctrl->version & 0xffff);

	pm_runtime_set_autosuspend_delay(dev, 3000);
	pm_runtime_use_autosuspend(dev);
	pm_runtime_mark_last_busy(dev);
	pm_runtime_set_active(dev);
	pm_runtime_enable(dev);
	if (ctrl->spx_windows_init) {
		pm_runtime_forbid(dev);
		dev_info(dev,
			 "SPX: runtime PM forbidden to preserve dual enumeration\n");
	}

	/*
	 * SPX: retime the idle park (Windows CLK_STP_NOW-on-idle parity). The
	 * usage count is 0 here and probe deliberately holds no reference: a
	 * put_autosuspend would drive it to -1, silently consuming the next
	 * stream's get_sync and defeating both later parks and the
	 * force-attach spx_pm_held hold. The existing stream-close
	 * put_autosuspend sites schedule suspend with this delay instead.
	 */
	if (spx_idle_clk_stop_ms) {
		pm_runtime_use_autosuspend(dev);
		pm_runtime_set_autosuspend_delay(dev, spx_idle_clk_stop_ms);
		pm_runtime_mark_last_busy(dev);
		dev_info(dev,
			 "SPX: idle bus clock-stop park armed (%d ms idle -> swrm_runtime_suspend MIPI handshake)\n",
			 spx_idle_clk_stop_ms);
	}

#ifdef CONFIG_DEBUG_FS
	ctrl->debugfs = debugfs_create_dir("qualcomm-sdw", ctrl->bus.debugfs);
	debugfs_create_file("qualcomm-registers", 0400, ctrl->debugfs, ctrl,
			    &swrm_reg_fops);
#endif

	return 0;

err_master_add:
	WRITE_ONCE(ctrl->spx_stopping, true);
	mutex_lock(&spx_dbg_lock);
	if (spx_dbg_ctrl == ctrl)
		spx_dbg_ctrl = NULL;
	mutex_unlock(&spx_dbg_lock);
	cancel_delayed_work_sync(&ctrl->spx_wd_work);
	cancel_delayed_work_sync(&ctrl->spx_enum_work);
	sdw_bus_master_delete(&ctrl->bus);
err_clk:
	clk_disable_unprepare(ctrl->hclk);
err_init:
	return ret;
}

static void qcom_swrm_remove(struct platform_device *pdev)
{
	struct qcom_swrm_ctrl *ctrl = dev_get_drvdata(&pdev->dev);
	int ret;

	/* The SPX work exists even with an IRQ-backed master. Letting it survive
	 * device removal leaves a dangling controller pointer and poisons rebind.
	 */
	WRITE_ONCE(ctrl->spx_stopping, true);
	mutex_lock(&spx_dbg_lock);
	if (spx_dbg_ctrl == ctrl)
		spx_dbg_ctrl = NULL;
	mutex_unlock(&spx_dbg_lock);
	cancel_delayed_work_sync(&ctrl->spx_wd_work);
	cancel_delayed_work_sync(&ctrl->spx_enum_work);
	spx_forced_attached = false;
	spx_bus_up = false;
	spx_amp_at_dev0 = false;
	spx_amp_addr_stale = true;
	if (spx_pm_held) {
		spx_pm_held = false;
		pm_runtime_put_noidle(ctrl->dev);
	}
	if (ctrl->spx_windows_init)
		pm_runtime_allow(&pdev->dev);

	/* Runtime PM remains enabled across a manual unbind unless the driver
	 * disables it. Resume while the bus is intact, then tear it down from a
	 * known active state so a subsequent bind cannot enter runtime-resume in
	 * the middle of sdw_bus_master_add().
	 */
	ret = pm_runtime_resume_and_get(&pdev->dev);
	pm_runtime_disable(&pdev->dev);
	if (ret >= 0)
		pm_runtime_put_noidle(&pdev->dev);
	sdw_bus_master_delete(&ctrl->bus);
	clk_disable_unprepare(ctrl->hclk);
}

static int __maybe_unused swrm_runtime_resume(struct device *dev)
{
	struct qcom_swrm_ctrl *ctrl = dev_get_drvdata(dev);
	int ret;

	if (ctrl->wake_irq > 0) {
		if (!irqd_irq_disabled(irq_get_irq_data(ctrl->wake_irq)))
			disable_irq_nosync(ctrl->wake_irq);
	}

	clk_prepare_enable(ctrl->hclk);

	if (ctrl->clock_stop_not_supported) {
		reinit_completion(&ctrl->enumeration);
		ctrl->reg_write(ctrl, SWRM_COMP_SW_RESET, 0x01);
		usleep_range(100, 105);

		qcom_swrm_init(ctrl);

		usleep_range(100, 105);
		if (!swrm_wait_for_frame_gen_enabled(ctrl))
			dev_err(ctrl->dev, "link failed to connect\n");

		/* wait for hw enumeration to complete */
		wait_for_completion_timeout(&ctrl->enumeration,
					    msecs_to_jiffies(TIMEOUT_MS));
		qcom_swrm_get_device_status(ctrl);
		sdw_handle_slave_status(&ctrl->bus, ctrl->status);
	} else {
		if (ctrl->audio_cgcr)
			reset_control_reset(ctrl->audio_cgcr);

		if (ctrl->version == SWRM_VERSION_1_7_0) {
			ctrl->reg_write(ctrl, SWRM_LINK_MANAGER_EE, SWRM_EE_CPU);
			ctrl->reg_write(ctrl, SWRM_MCP_BUS_CTRL,
					SWRM_MCP_BUS_CLK_START << SWRM_EE_CPU);
		} else if (ctrl->version >= SWRM_VERSION_2_0_0) {
			ctrl->reg_write(ctrl, SWRM_LINK_MANAGER_EE, SWRM_EE_CPU);
			ctrl->reg_write(ctrl, SWRM_V2_0_CLK_CTRL,
					SWRM_V2_0_CLK_CTRL_CLK_START);
		} else {
			ctrl->reg_write(ctrl, SWRM_MCP_BUS_CTRL, SWRM_MCP_BUS_CLK_START);
		}
		ctrl->reg_write(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_CLEAR],
			SWRM_INTERRUPT_STATUS_MASTER_CLASH_DET);

		ctrl->intr_mask |= SWRM_INTERRUPT_STATUS_MASTER_CLASH_DET;
		if (ctrl->version < SWRM_VERSION_2_0_0)
			ctrl->reg_write(ctrl,
					ctrl->reg_layout[SWRM_REG_INTERRUPT_MASK_ADDR],
					ctrl->intr_mask);
		if (ctrl->irq > 0)
			ctrl->reg_write(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_CPU_EN],
					ctrl->intr_mask);

		usleep_range(100, 105);
		if (!swrm_wait_for_frame_gen_enabled(ctrl))
			dev_err(ctrl->dev, "link failed to connect\n");

		ret = sdw_bus_exit_clk_stop(&ctrl->bus);
		if (ret < 0)
			dev_err(ctrl->dev, "bus failed to exit clock stop %d\n", ret);
	}

	return 0;
}

static int __maybe_unused swrm_runtime_suspend(struct device *dev)
{
	struct qcom_swrm_ctrl *ctrl = dev_get_drvdata(dev);
	int ret;

	swrm_wait_for_wr_fifo_done(ctrl);
	if (!ctrl->clock_stop_not_supported) {
		/* Mask bus clash interrupt */
		ctrl->intr_mask &= ~SWRM_INTERRUPT_STATUS_MASTER_CLASH_DET;
		if (ctrl->version < SWRM_VERSION_2_0_0)
			ctrl->reg_write(ctrl,
					ctrl->reg_layout[SWRM_REG_INTERRUPT_MASK_ADDR],
					ctrl->intr_mask);
		if (ctrl->irq > 0)
			ctrl->reg_write(ctrl, ctrl->reg_layout[SWRM_REG_INTERRUPT_CPU_EN],
					ctrl->intr_mask);
		/* Prepare slaves for clock stop */
		ret = sdw_bus_prep_clk_stop(&ctrl->bus);
		if (ret < 0 && ret != -ENODATA) {
			dev_err(dev, "prepare clock stop failed %d", ret);
			return ret;
		}

		ret = sdw_bus_clk_stop(&ctrl->bus);
		if (ret < 0 && ret != -ENODATA) {
			dev_err(dev, "bus clock stop failed %d", ret);
			return ret;
		}
	}

	clk_disable_unprepare(ctrl->hclk);

	usleep_range(300, 305);

	if (ctrl->wake_irq > 0) {
		if (irqd_irq_disabled(irq_get_irq_data(ctrl->wake_irq)))
			enable_irq(ctrl->wake_irq);
	}

	return 0;
}

static const struct dev_pm_ops swrm_dev_pm_ops = {
	SET_RUNTIME_PM_OPS(swrm_runtime_suspend, swrm_runtime_resume, NULL)
};

static const struct of_device_id qcom_swrm_of_match[] = {
	{ .compatible = "qcom,soundwire-v1.3.0", .data = &swrm_v1_3_data },
	{ .compatible = "qcom,soundwire-v1.5.1", .data = &swrm_v1_5_data },
	{ .compatible = "qcom,soundwire-v1.6.0", .data = &swrm_v1_6_data },
	{ .compatible = "qcom,soundwire-v1.7.0", .data = &swrm_v1_5_data },
	{ .compatible = "qcom,soundwire-v2.0.0", .data = &swrm_v2_0_data },
	{ .compatible = "qcom,soundwire-v3.1.0", .data = &swrm_v3_0_data },
	{/* sentinel */},
};

MODULE_DEVICE_TABLE(of, qcom_swrm_of_match);

static struct platform_driver qcom_swrm_driver = {
	.probe	= &qcom_swrm_probe,
	.remove = qcom_swrm_remove,
	.driver = {
		.name	= "qcom-soundwire",
		.of_match_table = qcom_swrm_of_match,
		.pm = &swrm_dev_pm_ops,
	}
};
module_platform_driver(qcom_swrm_driver);

MODULE_DESCRIPTION("Qualcomm soundwire driver");
MODULE_LICENSE("GPL v2");
