#include <linux/delay.h>
#include <linux/module.h>
#include <linux/slimbus.h>

static int __init spx_ba_init(void)
{
    struct device *dev;
    struct slim_device *sdev;
    int ret;
    u8 buf[4];

    dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
    if (!dev) return -ENODEV;
    sdev = to_slim_device(dev);

    /* Write to several candidate addresses for bridge WR_DATA */
    const u16 addrs[] = {0x0844, 0x0845, 0x0848, 0x0c44, 0x0c45, 0x0c85, 0x0885, 0x0886, 0x0884};
    int i;

    for (i = 0; i < ARRAY_SIZE(addrs); i++) {
        buf[0] = 0x42; buf[1] = 0x42; buf[2] = 0x42; buf[3] = 0x42;
        ret = slim_write(sdev, addrs[i], 4, buf);
        msleep(5);
        ret = slim_read(sdev, addrs[i], 4, buf);
        pr_info("spx_ba: addr=0x%04x slim_read rc=%d val=%02x %02x %02x %02x\n",
                addrs[i], ret, buf[0], buf[1], buf[2], buf[3]);
    }

    put_device(dev);
    return 0;
}

module_init(spx_ba_init);
MODULE_LICENSE("GPL");
