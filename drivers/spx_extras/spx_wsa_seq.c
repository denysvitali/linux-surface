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

static char *seq = "";
module_param(seq, charp, 0400);
MODULE_PARM_DESC(seq, "comma list of reg:val:delay_ms entries (hex ok)");

static char *devices = SPX_WSA_DEVICES;
module_param(devices, charp, 0400);
MODULE_PARM_DESC(devices, "comma list of SoundWire device names to replay to");

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
		if (tok)
			kstrtouint(tok, 0, &ms);

		if (reg < 0x3000 || reg > 0x36ff || val > 0xff) {
			dev_warn(dev, "SPX seq: skip bad entry 0x%x:0x%x\n",
				 reg, val);
			continue;
		}
		ret = sdw_write_no_pm(slave, reg, val);
		dev_info(dev, "SPX seq %3d: 0x%04x <- 0x%02x rc=%d%s\n",
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

	list = kstrdup(devices, GFP_KERNEL);
	if (!list)
		return -ENOMEM;

	cursor = list;
	while ((name = strsep(&cursor, ",")) != NULL) {
		if (!*name)
			continue;
		ret = spx_wsa_seq_play(name);
		if (ret)
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
