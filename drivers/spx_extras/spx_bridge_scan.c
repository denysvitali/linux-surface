#include <linux/module.h>
#include <linux/slimbus.h>

static int __init spx_bs_init(void)
{
    struct device *dev;
    struct slim_device *sdev;
    int ret, i;
    u8 buf[4];

    dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
    if (!dev) return -ENODEV;
    sdev = to_slim_device(dev);

    /* Scan 0x0800-0x0FFF with 16-byte stride, then 0x0C00-0x0FFF at 1-byte */
    pr_info("spx_bs: === 0x0800-0x0FFF ===\n");
    for (i = 0x800; i < 0x1000; i += 4) {
        ret = slim_read(sdev, i, 4, buf);
        if (buf[0] || buf[1] || buf[2] || buf[3]) {
            pr_info("spx_bs: 0x%04x val=%02x %02x %02x %02x\n", i, buf[0], buf[1], buf[2], buf[3]);
        }
    }

    /* Critical: scan 0xc80-0xca0 in detail */
    pr_info("spx_bs: === 0x0C80-0x0CA0 ===\n");
    for (i = 0xc80; i < 0xca0; i++) {
        ret = slim_read(sdev, i, 1, buf);
        if (buf[0] || ret < 0) {
            pr_info("spx_bs: 0x%04x rc=%d val=%02x\n", i, ret, buf[0]);
        }
    }

    /* Try address ranges with various bits set */
    pr_info("spx_bs: === 0x10000-0x10080 ===\n");
    for (i = 0x10000; i < 0x10080; i += 4) {
        ret = slim_read(sdev, i, 4, buf);
        if (buf[0] || buf[1] || buf[2] || buf[3]) {
            pr_info("spx_bs: 0x%05x val=%02x %02x %02x %02x\n", i, buf[0], buf[1], buf[2], buf[3]);
        }
    }

    put_device(dev);
    return 0;
}

module_init(spx_bs_init);
MODULE_LICENSE("GPL");
