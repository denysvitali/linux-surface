// SPDX-License-Identifier: GPL-2.0
/* SPX: dump SLIMbus device e_addr + logical address for the WCD9340 ifaces. */
#include <linux/module.h>
#include <linux/slimbus.h>

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
	dump_one("217:250:1:0");
	dump_one("217:250:0:0");
	return 0;
}
static void __exit spx_exit(void) {}
module_init(spx_init);
module_exit(spx_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX: dump WCD9340 SLIMbus e_addr/laddr");
