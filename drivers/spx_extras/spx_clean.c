#include <linux/module.h>
#include <linux/slimbus.h>

static int __init spx_cl_init(void)
{
    struct device *dev;
    struct slim_device *sdev;
    int ret;
    u8 buf[4];

    dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
    if (!dev) return -ENODEV;
    sdev = to_slim_device(dev);

    /* Test: write to SLIMbus VE 0x0844 (the supposed bridge WR_DATA)
     * then read it back */
    buf[0] = 0xAB; buf[1] = 0xCD; buf[2] = 0xEF; buf[3] = 0x12;
    ret = slim_write(sdev, 0x0844, 4, buf);
    pr_info("spx_cl: slim_write 0x0844=0xABCDEF12 rc=%d\n", ret);

    ret = slim_read(sdev, 0x0844, 4, buf);
    pr_info("spx_cl: slim_read 0x0844 rc=%d val=%02x %02x %02x %02x\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    /* Also read 0x0884 in case */
    ret = slim_read(sdev, 0x0884, 4, buf);
    pr_info("spx_cl: slim_read 0x0884 rc=%d val=%02x %02x %02x %02x\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    /* Try 0x0c84 in case */
    ret = slim_read(sdev, 0x0c84, 4, buf);
    pr_info("spx_cl: slim_read 0x0c84 rc=%d val=%02x %02x %02x %02x\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    ret = slim_read(sdev, 0x0c85, 4, buf);
    pr_info("spx_cl: slim_read 0x0c85 rc=%d val=%02x %02x %02x %02x\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    /* And 0x0888 */
    ret = slim_read(sdev, 0x0888, 4, buf);
    pr_info("spx_cl: slim_read 0x0888 rc=%d val=%02x %02x %02x %02x\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    ret = slim_read(sdev, 0x0c89, 4, buf);
    pr_info("spx_cl: slim_read 0x0c89 rc=%d val=%02x %02x %02x %02x\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    put_device(dev);
    return 0;
}

module_init(spx_cl_init);
MODULE_LICENSE("GPL");
