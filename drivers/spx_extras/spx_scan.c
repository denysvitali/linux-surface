#include <linux/module.h>
#include <linux/slimbus.h>

static int __init spx_scan_init(void)
{
    struct device *dev;
    struct slim_device *sdev;
    int ret, i;
    u8 buf[4];

    dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
    if (!dev) return -ENODEV;
    sdev = to_slim_device(dev);

    /* Scan a wide range of addresses looking for any non-zero response */
    pr_info("spx_scan: === Scanning 0x0000-0x0FFF ===\n");
    for (i = 0; i < 0x1000; i += 0x40) {
        ret = slim_read(sdev, i, 4, buf);
        if (buf[0] || buf[1] || buf[2] || buf[3]) {
            pr_info("spx_scan: 0x%04x rc=%d val=%02x %02x %02x %02x\n",
                    i, ret, buf[0], buf[1], buf[2], buf[3]);
        }
    }

    /* Also try 0x8000-0xBFFF and 0xC00-0xFFF in 4-byte steps */
    pr_info("spx_scan: === Scanning 0x0C00-0x0CFF ===\n");
    for (i = 0xc00; i < 0xd00; i++) {
        ret = slim_read(sdev, i, 1, buf);
        if (buf[0]) {
            pr_info("spx_scan: 0x%04x rc=%d val=%02x\n", i, ret, buf[0]);
        }
    }

    put_device(dev);
    return 0;
}

module_init(spx_scan_init);
MODULE_LICENSE("GPL");
