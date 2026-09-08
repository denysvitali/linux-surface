// SPDX-License-Identifier: GPL-2.0
/* SPX: dump SLIMbus device e_addr + logical address for the WCD9340 ifaces. */
#include <linux/module.h>
#include <linux/delay.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>

static bool rearm_rx;
module_param(rearm_rx, bool, 0400);
MODULE_PARM_DESC(rearm_rx, "Pulse RX0/1 port enable, restoring their current configuration; use with amplifiers muted");

static int rearm_ports(struct regmap *map)
{
	unsigned int saved[2];
	int i, ret, error = 0;

	for (i = 0; i < 2; i++) {
		ret = regmap_read(map, 0x40 + i, &saved[i]);
		if (ret)
			return ret;
	}
	for (i = 0; i < 2; i++) {
		ret = regmap_write(map, 0x40 + i, saved[i] & ~1U);
		if (ret && !error)
			error = ret;
	}
	usleep_range(1000, 1500);
	for (i = 0; i < 2; i++) {
		ret = regmap_write(map, 0x40 + i, saved[i]);
		if (ret && !error)
			error = ret;
		pr_info("spx_slim_info: RX%d port restore=%#x rc=%d\n",
			i, saved[i], ret);
	}
	ret = regmap_write(map, 0x38, 3);
	if (ret && !error)
		error = ret;
	msleep(20);
	return error;
}

static int dump_one(const char *name)
{
	struct device *dev;
	struct slim_device *sdev;

	dev = bus_find_device_by_name(&slimbus_bus, NULL, name);
	if (!dev) {
		pr_info("spx_slim_info: %s: not found\n", name);
		return 0;
	}
	sdev = to_slim_device(dev);
	pr_info("spx_slim_info: %s: e_addr manf=0x%04x prod=0x%04x instance=%u dev_index=%u | laddr=0x%02x valid=%d\n",
		name, sdev->e_addr.manf_id, sdev->e_addr.prod_code,
		sdev->e_addr.instance, sdev->e_addr.dev_index,
		sdev->laddr, sdev->is_laddr_valid);
	pr_info("spx_slim_info: %s: e_addr bytes(wire)=%02x %02x %02x %02x %02x %02x\n",
		name,
		sdev->e_addr.manf_id & 0xff, (sdev->e_addr.manf_id >> 8) & 0xff,
		sdev->e_addr.prod_code & 0xff, (sdev->e_addr.prod_code >> 8) & 0xff,
		sdev->e_addr.dev_index, sdev->e_addr.instance);
	put_device(dev);
	return 0;
}

static int __init spx_init(void)
{
	struct device *dev;
	struct regmap *map;
	unsigned int value;
	static const unsigned int regs[] = {0x34, 0x35, 0x40, 0x41,
		0x60, 0x61, 0x180, 0x184};
	int i, ret;

	dump_one("217:250:1:0");
	dump_one("217:250:0:0");
	dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:0:0");
	if (dev) {
		map = dev_get_regmap(dev, NULL);
		if (!map) {
			put_device(dev);
			return -ENODEV;
		}
		if (rearm_rx) {
			ret = rearm_ports(map);
			if (ret) {
				put_device(dev);
				return ret;
			}
		}
		for (i = 0; i < ARRAY_SIZE(regs); i++) {
			value = 0;
			ret = regmap_read(map, regs[i], &value);
			pr_info("spx_slim_info: paged IFD reg=%#x read=%#x rc=%d\n",
				regs[i], value, ret);
		}
		put_device(dev);
	}
	return 0;
}
static void __exit spx_exit(void) {}
module_init(spx_init);
module_exit(spx_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX: dump WCD9340 SLIMbus e_addr/laddr");
