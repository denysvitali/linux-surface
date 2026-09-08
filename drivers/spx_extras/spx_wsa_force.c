// SPDX-License-Identifier: GPL-2.0
/*
 * SPX: forced, WRITE-ONLY bring-up of the WSA881x smart amp on the WCD9340
 * codec-internal SoundWire master.
 *
 * Reads over the SLIMbus->AHB bridge are unreliable on this platform, writes
 * are not.  This module therefore issues a fixed, ordered table of blind
 * sdw_write_no_pm() commands to the attached WSA881x:
 *
 *   stage bit0 (1)  SCP framing + DP1 (DAC) transport config, both banks
 *   stage bit1 (2)  analog chain: reset release, clocks, bandgap, RDAC,
 *                   boost, PA gain in REGISTER mode, PA unmute
 *   stage bit2 (4)  DP2 (COMP) + DP3 (BOOST) transport config, both banks
 *                   (only needed while the COMP/BOOST mixer switches are on)
 *
 * Every value in the tables is the exact byte the in-tree drivers would have
 * produced: the DPn values come from drivers/soundwire/stream.c fed with the
 * SPX port config in sc8180x-wcd9340.dtsi, and the 0x30xx/0x31xx values are the
 * result of replaying wsa881x_init() + the DAPM PRE_PMU/RDAC/boost sequence in
 * sound/soc/codecs/wsa881x.c against the driver's own shadow defaults.
 *
 * PREREQUISITE -- soundwire_qcom.spx_write_dev0 MUST be 0.
 *   qcom_swrm_xfer_msg() rewrites every WRITE addressed to logical device 1
 *   into a write to physical device 0 while spx_forced_attached is set.  The
 *   amp is now genuinely enumerated at device 1 (MCP_SLV_STATUS=0x4), so
 *   nothing answers at address 0 and every write -- including the ones this
 *   module issues -- is silently discarded.  Clear it first:
 *      echo 0 > /sys/module/soundwire_qcom/parameters/spx_write_dev0
 *
 * Usage (module always returns -EAGAIN so it never stays resident and can be
 * re-run without rmmod):
 *
 *   insmod spx_wsa_force.ko stage=3 gain=8         # ports + analog, +6 dB
 *   insmod spx_wsa_force.ko stage=2 gain=4         # analog only, +12 dB
 *   insmod spx_wsa_force.ko seq=311a=fc,311b=89    # arbitrary writes
 *   insmod spx_wsa_force.ko stage=3 dry_run=1      # log the table, write nothing
 */
#include <linux/bits.h>
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/soundwire/sdw.h>
#include <linux/soundwire/sdw_registers.h>
#include <linux/soundwire/sdw_type.h>

#define SPX_WSA_DEVICE_DFL	"sdw:0:0:0217:2010:00:1"

/* WSA881x internal register blocks (see sound/soc/codecs/wsa881x.c). */
#define WSA_CDC_RST_CTL		0x3005
#define WSA_CDC_TOP_CLK_CTL	0x3006
#define WSA_CDC_ANA_CLK_CTL	0x3007
#define WSA_CDC_DIG_CLK_CTL	0x3008
#define WSA_CLOCK_CONFIG	0x3009
#define WSA_SWR_RESET_EN	0x300b
#define WSA_OTP_REG_28		0x309c
#define WSA_TEMP_OP		0x3103
#define WSA_SPKR_DRV_EN		0x311a
#define WSA_SPKR_DRV_GAIN	0x311b
#define WSA_SPKR_DAC_CTL	0x311c
#define WSA_SPKR_OCP_CTL	0x311f
#define WSA_SPKR_MISC_CTL1	0x3122
#define WSA_SPKR_BIAS_INT	0x3124
#define WSA_SPKR_PA_INT		0x3125
#define WSA_BOOST_EN_CTL	0x312a
#define WSA_BOOST_CURR_LIMIT	0x312b
#define WSA_BOOST_PRESET_OUT1	0x312d
#define WSA_BOOST_PRESET_OUT2	0x312e
#define WSA_BOOST_SLOPE_COMP	0x3131
#define WSA_BOOST_LOOP_STAB	0x3133
#define WSA_BOOST_START_CTL	0x3135
#define WSA_BOOST_MISC2_CTL	0x3137
#define WSA_BONGO_RESRV_REG1	0x3142
#define WSA_BONGO_RESRV_REG2	0x3143

#define SPX_SCP_HOST_CLK_DIV2_B0	0x00e0
#define SPX_SCP_HOST_CLK_DIV2_B1	0x00f0

#define SPX_STAGE_PORT		BIT(0)
#define SPX_STAGE_ANALOG	BIT(1)
#define SPX_STAGE_AUXPORTS	BIT(2)

struct spx_wsa_wr {
	u32 reg;
	u8 val;
	u16 delay_us;
	const char *name;
};

static char *slave_name = SPX_WSA_DEVICE_DFL;
module_param(slave_name, charp, 0400);
MODULE_PARM_DESC(slave_name, "SoundWire slave device name to target");

static int stage = SPX_STAGE_PORT | SPX_STAGE_ANALOG;
module_param(stage, int, 0400);
MODULE_PARM_DESC(stage,
		 "bit0=DP1 transport, bit1=analog+PA, bit2=DP2/DP3 transport");

/*
 * PA gain field for SPKR_DRV_GAIN[7:4]: 0 = +18 dB (max) .. 12 = 0 dB, in
 * 1.5 dB steps.  Default 8 = +6 dB: clearly audible but well short of the
 * +18 dB the mixer is currently set to, which is a lot for a tablet driver
 * being fed a blind, unverified signal path.
 */
static int gain = 8;
module_param(gain, int, 0400);
MODULE_PARM_DESC(gain, "PA gain field 0..12 (0=+18dB, 8=+6dB, 12=0dB)");

static int passes = 3;
module_param(passes, int, 0400);
MODULE_PARM_DESC(passes, "How many times to replay each table (bus is lossy)");

static char *seq;
module_param(seq, charp, 0400);
MODULE_PARM_DESC(seq, "Custom hex writes, e.g. \"311a=fc,120=01\"; overrides stage");

static int dry_run;
module_param(dry_run, int, 0400);
MODULE_PARM_DESC(dry_run, "Log the table but issue no bus writes");

/*
 * DP1 = the WSA881x DAC port: the 1-bit 48 kHz PDM speaker stream.
 * (DP2 = COMP, DP3 = BOOST, DP4 = VISENSE -- none of them carry audio.)
 *
 * Values mirror sdw_program_slave_port_params() with the SPX master port-1
 * config from sc8180x-wcd9340.dtsi: sinterval-low 0x07 (=> interval 8,
 * SampleCtrl1 = 8-1 = 7), offset1 0x01, offset2 0x00, no hstart/hstop
 * (=> HStart 0 / HStop 15).  Both banks are written so the config survives
 * whichever bank a running stream switches into.  ChannelEn is written last.
 */
static const struct spx_wsa_wr spx_dp1_table[] = {
	{ SDW_SCP_FRAMECTRL_B0,		0x07, 0, "SCP_FrameCtrl_B0 (48 rows x 16 cols)" },
	{ SDW_SCP_FRAMECTRL_B1,		0x07, 0, "SCP_FrameCtrl_B1" },
	{ SPX_SCP_HOST_CLK_DIV2_B0,	0x01, 0, "SCP_HostClkDiv2_B0" },
	{ SPX_SCP_HOST_CLK_DIV2_B1,	0x01, 0, "SCP_HostClkDiv2_B1" },

	{ SDW_DPN_PORTCTRL(1),		0x00, 0, "DP1_PortCtrl (isoch, normal)" },
	{ SDW_DPN_BLOCKCTRL1(1),	0x00, 0, "DP1_BlockCtrl1 (bps-1 = 0, PDM)" },
	{ SDW_DPN_BLOCKCTRL2_B0(1),	0x00, 0, "DP1_BlockCtrl2_B0" },
	{ SDW_DPN_BLOCKCTRL2_B1(1),	0x00, 0, "DP1_BlockCtrl2_B1" },
	{ SDW_DPN_SAMPLECTRL1_B0(1),	0x07, 0, "DP1_SampleCtrl1_B0" },
	{ SDW_DPN_SAMPLECTRL1_B1(1),	0x07, 0, "DP1_SampleCtrl1_B1" },
	{ SDW_DPN_SAMPLECTRL2_B0(1),	0x00, 0, "DP1_SampleCtrl2_B0" },
	{ SDW_DPN_SAMPLECTRL2_B1(1),	0x00, 0, "DP1_SampleCtrl2_B1" },
	{ SDW_DPN_OFFSETCTRL1_B0(1),	0x01, 0, "DP1_OffsetCtrl1_B0" },
	{ SDW_DPN_OFFSETCTRL1_B1(1),	0x01, 0, "DP1_OffsetCtrl1_B1" },
	{ SDW_DPN_OFFSETCTRL2_B0(1),	0x00, 0, "DP1_OffsetCtrl2_B0" },
	{ SDW_DPN_OFFSETCTRL2_B1(1),	0x00, 0, "DP1_OffsetCtrl2_B1" },
	{ SDW_DPN_HCTRL_B0(1),		0x0f, 0, "DP1_HCtrl_B0 (HStart 0, HStop 15)" },
	{ SDW_DPN_HCTRL_B1(1),		0x0f, 0, "DP1_HCtrl_B1" },
	{ SDW_DPN_BLOCKCTRL3_B0(1),	0x00, 0, "DP1_BlockCtrl3_B0" },
	{ SDW_DPN_BLOCKCTRL3_B1(1),	0x00, 0, "DP1_BlockCtrl3_B1" },

	{ SDW_DPN_CHANNELEN_B0(1),	0x01, 0, "DP1_ChannelEn_B0 (ch1 on)" },
	{ SDW_DPN_CHANNELEN_B1(1),	0x01, 0, "DP1_ChannelEn_B1 (ch1 on)" },
};

/*
 * Optional: DP2 (COMP, master port 2: si 0x1f, off1 0x02) and DP3 (BOOST,
 * master port 3: si 0x3f, off1 0x0c).  Only relevant while the COMP/BOOST
 * mixer switches are enabled and those ports are part of the stream.
 */
static const struct spx_wsa_wr spx_aux_port_table[] = {
	{ SDW_DPN_PORTCTRL(2),		0x00, 0, "DP2_PortCtrl" },
	{ SDW_DPN_SAMPLECTRL1_B0(2),	0x1f, 0, "DP2_SampleCtrl1_B0" },
	{ SDW_DPN_SAMPLECTRL1_B1(2),	0x1f, 0, "DP2_SampleCtrl1_B1" },
	{ SDW_DPN_OFFSETCTRL1_B0(2),	0x02, 0, "DP2_OffsetCtrl1_B0" },
	{ SDW_DPN_OFFSETCTRL1_B1(2),	0x02, 0, "DP2_OffsetCtrl1_B1" },
	{ SDW_DPN_HCTRL_B0(2),		0x0f, 0, "DP2_HCtrl_B0" },
	{ SDW_DPN_HCTRL_B1(2),		0x0f, 0, "DP2_HCtrl_B1" },
	{ SDW_DPN_CHANNELEN_B0(2),	0x0f, 0, "DP2_ChannelEn_B0" },
	{ SDW_DPN_CHANNELEN_B1(2),	0x0f, 0, "DP2_ChannelEn_B1" },

	{ SDW_DPN_PORTCTRL(3),		0x00, 0, "DP3_PortCtrl" },
	{ SDW_DPN_SAMPLECTRL1_B0(3),	0x3f, 0, "DP3_SampleCtrl1_B0" },
	{ SDW_DPN_SAMPLECTRL1_B1(3),	0x3f, 0, "DP3_SampleCtrl1_B1" },
	{ SDW_DPN_OFFSETCTRL1_B0(3),	0x0c, 0, "DP3_OffsetCtrl1_B0" },
	{ SDW_DPN_OFFSETCTRL1_B1(3),	0x0c, 0, "DP3_OffsetCtrl1_B1" },
	{ SDW_DPN_OFFSETCTRL2_B0(3),	0x1f, 0, "DP3_OffsetCtrl2_B0" },
	{ SDW_DPN_OFFSETCTRL2_B1(3),	0x1f, 0, "DP3_OffsetCtrl2_B1" },
	{ SDW_DPN_HCTRL_B0(3),		0x0f, 0, "DP3_HCtrl_B0" },
	{ SDW_DPN_HCTRL_B1(3),		0x0f, 0, "DP3_HCtrl_B1" },
	{ SDW_DPN_CHANNELEN_B0(3),	0x03, 0, "DP3_ChannelEn_B0" },
	{ SDW_DPN_CHANNELEN_B1(3),	0x03, 0, "DP3_ChannelEn_B1" },
};

/*
 * Analog chain.  Each value is the final byte wsa881x.c would have left in the
 * register after wsa881x_init() plus the DAPM enables, computed by replaying
 * its read-modify-write sequence over wsa881x_defaults[] + wsa881x_rev_2_0[].
 * SPKR_DRV_GAIN and SPKR_DRV_EN are filled in at run time from @gain.
 */
static struct spx_wsa_wr spx_analog_table[] = {
	/* --- rev 2.0 reset patch (only the entries init/DAPM depend on) --- */
	{ 0x300c, 0x00, 0, "RESET_CTL" },
	{ 0x300f, 0x01, 0, "TADC_VALUE_CTL" },
	{ 0x3021, 0x1b, 0, "INTR_MASK" },
	{ 0x3045, 0x00, 0, "IOPAD_CTL" },
	{ 0x309d, 0x3f, 0, "OTP_REG_29" },
	{ 0x309e, 0x01, 0, "OTP_REG_30" },
	{ 0x309f, 0x01, 0, "OTP_REG_31" },
	{ 0x3109, 0x03, 0, "TEMP_ADC_CTRL" },
	{ 0x3114, 0x45, 0, "ADC_SEL_IBIAS" },
	{ 0x3121, 0x02, 0, "SPKR_BBM_CTL" },
	{ 0x3123, 0x07, 0, "SPKR_MISC_CTL2" },
	{ 0x3127, 0x44, 0, "SPKR_BIAS_PSRR" },
	{ 0x312c, 0xa0, 0, "BOOST_PS_CTL" },
	{ 0x313f, 0x02, 0, "SPKR_PROT_ATEST2" },

	/* --- release resets, start clocks --- */
	{ WSA_SWR_RESET_EN,	0x07, 0,    "SWR_RESET_EN" },
	{ WSA_CDC_RST_CTL,	0x03, 1000, "CDC_RST_CTL (analog+digital out of reset)" },
	{ WSA_CLOCK_CONFIG,	0x10, 0,    "CLOCK_CONFIG" },
	{ WSA_CDC_TOP_CLK_CTL,	0x03, 0,    "CDC_TOP_CLK_CTL" },

	/* --- wsa881x_init() tuning --- */
	{ WSA_SPKR_MISC_CTL1,	0x86, 0, "SPKR_MISC_CTL1" },
	{ WSA_SPKR_BIAS_INT,	0x00, 0, "SPKR_BIAS_INT" },
	{ WSA_SPKR_PA_INT,	0x4e, 0, "SPKR_PA_INT" },
	{ WSA_BOOST_LOOP_STAB,	0x8f, 0, "BOOST_LOOP_STABILITY" },
	{ WSA_BOOST_MISC2_CTL,	0x14, 0, "BOOST_MISC2_CTL" },
	{ WSA_BOOST_START_CTL,	0xa0, 0, "BOOST_START_CTL" },
	{ WSA_BOOST_SLOPE_COMP,	0x74, 0, "BOOST_SLOPE_COMP_ISENSE_FB" },
	{ WSA_BOOST_PRESET_OUT1, 0x77, 0, "BOOST_PRESET_OUT1" },
	{ WSA_BOOST_PRESET_OUT2, 0x30, 0, "BOOST_PRESET_OUT2" },
	{ WSA_BOOST_CURR_LIMIT,	0x78, 0, "BOOST_CURRENT_LIMIT" },
	{ WSA_OTP_REG_28,	0x3a, 0, "OTP_REG_28" },
	{ WSA_BONGO_RESRV_REG1,	0xb2, 0, "BONGO_RESRV_REG1" },
	{ WSA_BONGO_RESRV_REG2,	0x05, 0, "BONGO_RESRV_REG2" },

	/* --- DAPM supplies: bandgap, analog clock, digital clock --- */
	{ WSA_TEMP_OP,		0x08, 0, "TEMP_OP (bandgap on)" },
	{ WSA_CDC_ANA_CLK_CTL,	0x01, 0, "CDC_ANA_CLK_CTL (ACLK on)" },
	{ WSA_CDC_DIG_CLK_CTL,	0x01, 0, "CDC_DIG_CLK_CTL (DCLK on)" },

	/* --- RDAC on --- */
	{ WSA_SPKR_DAC_CTL,	0xc2, 0, "SPKR_DAC_CTL (RDAC on)" },

	/* --- boost converter on; HW needs 1.5 ms --- */
	{ WSA_BOOST_EN_CTL,	0x98, 1500, "BOOST_EN_CTL (boost on)" },

	/* --- PA: OCP enabled, pre-PMU sequence, gain in REGISTER mode --- */
	{ WSA_SPKR_OCP_CTL,	0xb2, 0, "SPKR_OCP_CTL (OCP_EN)" },
	{ WSA_SPKR_DRV_GAIN,	0x41, 0, "SPKR_DRV_GAIN (pre-PMU step)" },
	{ WSA_SPKR_MISC_CTL1,	0x87, 0, "SPKR_MISC_CTL1 (pre-PMU step)" },
	{ WSA_SPKR_DRV_GAIN,	0x89, 1000, "SPKR_DRV_GAIN (REG mode, patched)" },

	/* --- unmute the output driver --- */
	{ WSA_SPKR_DRV_EN,	0xfc, 0, "SPKR_DRV_EN (PA on + unmute)" },
};

static int spx_wsa_run(struct sdw_slave *slave, struct device *dev,
		       const struct spx_wsa_wr *tbl, int n, const char *what)
{
	int i, p, ret = 0;

	dev_info(dev, "SPX force: applying %s (%d writes x %d passes)%s\n",
		 what, n, passes, dry_run ? " [DRY RUN]" : "");

	for (p = 0; p < passes; p++) {
		for (i = 0; i < n; i++) {
			if (!dry_run) {
				ret = sdw_write_no_pm(slave, tbl[i].reg,
						      tbl[i].val);
				if (ret < 0) {
					dev_err(dev,
						"SPX force: %s 0x%04x <- 0x%02x FAILED %d\n",
						tbl[i].name, tbl[i].reg,
						tbl[i].val, ret);
					return ret;
				}
			}
			if (p == 0)
				dev_info(dev, "SPX force:   0x%04x <- 0x%02x  %s\n",
					 tbl[i].reg, tbl[i].val, tbl[i].name);
			if (tbl[i].delay_us)
				fsleep(tbl[i].delay_us);
		}
	}

	return 0;
}

/* Parse "reg=val,reg=val,..." (hex, no 0x prefix required). */
static int spx_wsa_run_seq(struct sdw_slave *slave, struct device *dev)
{
	char *buf, *cur, *tok;
	int ret = 0;

	buf = kstrdup(seq, GFP_KERNEL);
	if (!buf)
		return -ENOMEM;

	cur = buf;
	while ((tok = strsep(&cur, ",;")) != NULL) {
		unsigned int reg, val;
		char *eq = strchr(tok, '=');

		if (!eq)
			continue;
		*eq = '\0';
		if (kstrtouint(strim(tok), 16, &reg) ||
		    kstrtouint(strim(eq + 1), 16, &val) || val > 0xff) {
			dev_err(dev, "SPX force: bad seq element\n");
			ret = -EINVAL;
			break;
		}

		dev_info(dev, "SPX force: seq 0x%04x <- 0x%02x\n", reg, val);
		if (!dry_run) {
			ret = sdw_write_no_pm(slave, reg, val);
			if (ret < 0) {
				dev_err(dev, "SPX force: seq write failed %d\n",
					ret);
				break;
			}
		}
	}

	kfree(buf);
	return ret < 0 ? ret : 0;
}

static int __init spx_wsa_force_init(void)
{
	struct sdw_slave *slave;
	struct device *dev;
	int ret;

	if (gain < 0 || gain > 12 || passes < 1 || passes > 16)
		return -EINVAL;

	dev = bus_find_device_by_name(&sdw_bus_type, NULL, slave_name);
	if (!dev) {
		pr_err("spx_wsa_force: no SoundWire slave named %s\n",
		       slave_name);
		return -ENODEV;
	}

	slave = dev_to_sdw_dev(dev);
	if (slave->status != SDW_SLAVE_ATTACHED || !slave->dev_num) {
		dev_err(dev, "SPX force: slave not attached (status %d dev_num %d)\n",
			slave->status, slave->dev_num);
		ret = -ENODEV;
		goto out_put;
	}

	dev_info(dev,
		 "SPX force: target dev_num=%d stage=0x%x gain=%d (%d.%d dB)\n",
		 slave->dev_num, stage, gain, (12 - gain) * 15 / 10,
		 ((12 - gain) * 15) % 10);
	dev_warn(dev,
		 "SPX force: writes only reach the amp if soundwire_qcom.spx_write_dev0 == 0\n");

	/* Patch the run-time-dependent analog values. */
	spx_analog_table[ARRAY_SIZE(spx_analog_table) - 2].val =
		((gain & 0xf) << 4) | 0x09;	/* PA_GAIN_SEL_REG | pwm bits */

	if (seq) {
		ret = spx_wsa_run_seq(slave, dev);
		goto out_put;
	}

	if (stage & SPX_STAGE_PORT) {
		ret = spx_wsa_run(slave, dev, spx_dp1_table,
				  ARRAY_SIZE(spx_dp1_table), "DP1 transport");
		if (ret)
			goto out_put;
	}

	if (stage & SPX_STAGE_AUXPORTS) {
		ret = spx_wsa_run(slave, dev, spx_aux_port_table,
				  ARRAY_SIZE(spx_aux_port_table),
				  "DP2/DP3 transport");
		if (ret)
			goto out_put;
	}

	if (stage & SPX_STAGE_ANALOG) {
		ret = spx_wsa_run(slave, dev, spx_analog_table,
				  ARRAY_SIZE(spx_analog_table),
				  "analog chain + PA");
		if (ret)
			goto out_put;
	}

	dev_info(dev, "SPX force: done\n");
	ret = 0;

out_put:
	put_device(dev);
	/*
	 * Always fail the load so the module never stays resident; all the work
	 * happens in init and this keeps insmod re-runnable without rmmod.
	 */
	return ret ? ret : -EAGAIN;
}

static void __exit spx_wsa_force_exit(void)
{
}

module_init(spx_wsa_force_init);
module_exit(spx_wsa_force_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX forced write-only WSA881x port + analog bring-up");
