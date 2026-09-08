// SPDX-License-Identifier: GPL-2.0
/*
 * SPX: scripted WSA881x register-sequence player, for replaying the exact
 * bring-up sequences extracted from the Windows qcauddev8180.sys driver.
 *
 * insmod spx_wsa_seq.ko seq=0x3121:0x02:0,0x3122:0xc0:1,...
 *   each entry is reg:val:delay_ms (delay after the write).
 * Registers restricted to the WSA881x slave range 0x3000-0x36ff.
 * Always "fails" load with -EAGAIN after running so it can be re-run
 * without rmmod (same trick as spx_wcd_gpio).
 */
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/module.h>
#include <linux/soundwire/sdw.h>
#include <linux/soundwire/sdw_type.h>

/*
 * Default targets: the two statically declared speaker slaves, which the
 * resident enumeration module remaps onto the real hardware device numbers.
 * Both are driven so a sequence can be replayed to both amplifiers in one go.
 */
#define SPX_WSA_DEVICES	"sdw:0:0:0217:2010:00:1,sdw:0:0:0217:2010:00:2"

/* Exported from drivers/soundwire/bus.c but missing from the public header
 * in this tree; declare it here so bcast mode can use it.
 */
int sdw_bwrite_no_pm_unlocked(struct sdw_bus *bus, u16 dev_num, u32 addr,
			      u8 value);
int sdw_bread_no_pm_unlocked(struct sdw_bus *bus, u16 dev_num, u32 addr);

static char *seq = "";
module_param(seq, charp, 0400);
MODULE_PARM_DESC(seq, "comma list of reg:val:delay_ms entries (hex ok)");

static char *devices = SPX_WSA_DEVICES;
module_param(devices, charp, 0400);
MODULE_PARM_DESC(devices, "comma list of SoundWire device names to replay to");

/*
 * bcast=1 sends every entry as a SoundWire BROADCAST write (dev_num 15)
 * instead of a unicast to the found slave. Every amp on the bus receives it
 * regardless of which logical address it actually sits at -- unicast writes
 * on this master "always report success even when dropped", so broadcast is
 * the only write class with observable effect (the mid-stream bank-switch
 * recovery). Use only while the stream is parked and only pin2 is powered.
 */
static int address = -1;
module_param(address, int, 0400);
MODULE_PARM_DESC(address, "Override physical write address (-1 uses codec, 0..14 explicit)");

static int bcast;
module_param(bcast, int, 0400);
MODULE_PARM_DESC(bcast, "1 = broadcast every write to dev_num 15");

/*
 * allow_scp=1 permits SoundWire SCP registers (< 0x1000, e.g. DevNumber
 * 0x0046) alongside the WSA881x file. Only for deliberate addressing
 * experiments: writing random low registers disturbs the slave's protocol
 * state.
 */
static int allow_scp;
module_param(allow_scp, int, 0400);
MODULE_PARM_DESC(allow_scp, "1 = also accept registers below 0x3000");

/*
 * reads=0x3011,0x3012,... performs READ-ONLY register forensics: each listed
 * register is read twice per device (stability check) and logged. Nothing is
 * ever written in this mode; seq/bcast are ignored. This is the objective
 * counterpart to the listening runs -- OTP identity (0x3080+), temperature
 * (TEMP_MSB/LSB 0x3011/12 after the TEMP_OP recipe), status latches
 * (INTR_STATUS 0x3022) and the analog state registers, read back from the
 * physical amplifier.
 */
static char *reads;
module_param(reads, charp, 0400);
MODULE_PARM_DESC(reads,
		 "comma list of WSA881x registers to read and log (hex ok)");

static int spx_wsa_seq_read_one(const char *name)
{
	struct sdw_slave *slave;
	struct device *dev;
	char *s, *cursor, *tok;
	int ret = 0;

	dev = bus_find_device_by_name(&sdw_bus_type, NULL, name);
	if (!dev) {
		pr_warn("spx_wsa_seq: device %s not found\n", name);
		return -ENODEV;
	}
	slave = dev_to_sdw_dev(dev);

	s = kstrdup(reads, GFP_KERNEL);
	if (!s) {
		ret = -ENOMEM;
		goto out_put;
	}

	cursor = s;
	while ((tok = strsep(&cursor, ",")) != NULL) {
		unsigned int reg;
		u8 val[2];
		int pass;

		if (!*tok)
			continue;
		if (kstrtouint(tok, 0, &reg))
			continue;
		if ((reg < 0x3000 && !allow_scp) || reg > 0x36ff) {
			dev_warn(dev, "SPX seq-read: skip bad reg 0x%x\n", reg);
			continue;
		}
		for (pass = 0; pass < 2; pass++) {
			if (address >= 0) {
				mutex_lock(&slave->bus->bus_lock);
				ret = sdw_bread_no_pm_unlocked(slave->bus,
							      address, reg);
				mutex_unlock(&slave->bus->bus_lock);
			} else {
				ret = sdw_read_no_pm(slave, reg);
			}
			val[pass] = ret < 0 ? 0 : (u8)ret;
			dev_info(dev,
				 "SPX seq-read %s address=%u pass%d: 0x%04x => rc=%d val=0x%02x\n",
				 name, address >= 0 ? address : slave->dev_num,
				 pass, reg, ret, val[pass]);
			if (ret < 0)
				break;
		}
		if (ret >= 0 && val[0] != val[1])
			dev_info(dev,
				 "SPX seq-read UNSTABLE 0x%04x: 0x%02x vs 0x%02x\n",
				 reg, val[0], val[1]);
	}
	kfree(s);
out_put:
	put_device(dev);
	return ret < 0 ? ret : 0;
}

static int spx_wsa_seq_play(const char *name)
{
	struct sdw_slave *slave;
	struct device *dev;
	char *s, *cursor, *entry, *tok;
	int ret = 0, n = 0;

	dev = bus_find_device_by_name(&sdw_bus_type, NULL, name);
	if (!dev) {
		pr_warn("spx_wsa_seq: device %s not found\n", name);
		return -ENODEV;
	}
	slave = dev_to_sdw_dev(dev);

	s = kstrdup(seq, GFP_KERNEL);
	if (!s) {
		ret = -ENOMEM;
		goto out_put;
	}

	cursor = s;
	while ((entry = strsep(&cursor, ",")) != NULL) {
		unsigned int reg, val, ms = 0;

		if (!*entry)
			continue;
		tok = strsep(&entry, ":");
		if (!tok || kstrtouint(tok, 0, &reg))
			continue;
		tok = strsep(&entry, ":");
		if (!tok || kstrtouint(tok, 0, &val))
			continue;
		tok = strsep(&entry, ":");
		if (tok && kstrtouint(tok, 0, &ms))
			continue;

		if ((reg < 0x3000 && !allow_scp) || reg > 0x36ff ||
		    val > 0xff) {
			dev_warn(dev, "SPX seq: skip bad entry 0x%x:0x%x\n",
				 reg, val);
			continue;
		}
		if (bcast || address >= 0) {
			/* sdw_bwrite_no_pm() is static in this tree; the
			 * exported _unlocked variant plus the bus lock is the
			 * same operation.
			 */
			mutex_lock(&slave->bus->bus_lock);
			ret = sdw_bwrite_no_pm_unlocked(slave->bus,
							bcast ? SDW_BROADCAST_DEV_NUM : address,
							reg, val);
			mutex_unlock(&slave->bus->bus_lock);
			/* The qcom master pushes the broadcast into the FIFO
			 * BEFORE waiting on its completion interrupt, so
			 * -ENODATA here only means "sent, unconfirmed" -- the
			 * same fire-and-forget property as every other write
			 * on this master. Do not abort the sequence on it.
			 */
			if (bcast && ret == -ENODATA)
				ret = 0;
		} else {
			ret = sdw_write_no_pm(slave, reg, val);
		}
		dev_info(dev, "SPX seq %s %3d: 0x%04x <- 0x%02x rc=%d%s\n",
			 bcast ? "bcast" : "ucast",
			 ++n, reg, val, ret, ms ? " +delay" : "");
		if (ret)
			break;
		if (ms)
			fsleep(ms * 1000);
	}
	kfree(s);
out_put:
	put_device(dev);
	return ret;
}

static int __init spx_wsa_seq_init(void)
{
	char *list, *cursor, *name;
	int ret = 0;

	if (address < -1 || address > 14 ||
	    (address >= 0 && bcast))
		return -EINVAL;

	if (reads && *reads) {
		list = kstrdup(devices, GFP_KERNEL);
		if (!list)
			return -ENOMEM;
		cursor = list;
		while ((name = strsep(&cursor, ",")) != NULL) {
			if (!*name)
				continue;
			ret = spx_wsa_seq_read_one(name);
			if (ret)
				break;
		}
		kfree(list);
		return ret ? ret : -EAGAIN;
	}

	list = kstrdup(devices, GFP_KERNEL);
	if (!list)
		return -ENOMEM;

	cursor = list;
	while ((name = strsep(&cursor, ",")) != NULL) {
		if (!*name)
			continue;
		ret = spx_wsa_seq_play(name);
		/* In bcast mode the first bus pointer is all we need; a second
		 * pass would replay the sequence to the same broadcast address.
		 */
		if (ret || bcast || address >= 0)
			break;
	}
	kfree(list);

	/* Always fail the load so the module can be re-run without rmmod. */
	return ret ? ret : -EAGAIN;
}

static void __exit spx_wsa_seq_exit(void)
{
}

module_init(spx_wsa_seq_init);
module_exit(spx_wsa_seq_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX scripted WSA881x register sequence player");
