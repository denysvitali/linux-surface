#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slab.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/slimbus.h>

static int __init spx_reset_init(void)
{
    struct device *dev;
    struct slim_device *sdev;
    int ret;
    u8 buf[4];
    u32 val;

    dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
    if (!dev) return -ENODEV;
    sdev = to_slim_device(dev);

    /* Try the db845c reset/clock sequence step by step */

    /* 1. Ensure codec is reset out of SIDO */
    buf[0] = 0x01; ret = slim_write(sdev, 0x0009, 1, buf);
    pr_info("spx_reset: 0x0009=0x01 rc=%d\n", ret);

    buf[0] = 0x19; ret = slim_write(sdev, 0x071b, 1, buf);
    pr_info("spx_reset: 0x071b=0x19 rc=%d\n", ret);

    buf[0] = 0x15; ret = slim_write(sdev, 0x071c, 1, buf);
    pr_info("spx_reset: 0x071c=0x15 rc=%d\n", ret);

    msleep(20);

    buf[0] = 0x05; ret = slim_write(sdev, 0x0011, 1, buf);
    pr_info("spx_reset: 0x0011=0x05 rc=%d\n", ret);

    buf[0] = 0x07; ret = slim_write(sdev, 0x0011, 1, buf);
    pr_info("spx_reset: 0x0011=0x07 rc=%d\n", ret);

    buf[0] = 0x03; ret = slim_write(sdev, 0x0009, 1, buf);
    pr_info("spx_reset: 0x0009=0x03 rc=%d\n", ret);

    buf[0] = 0x07; ret = slim_write(sdev, 0x0009, 1, buf);
    pr_info("spx_reset: 0x0009=0x07 rc=%d\n", ret);

    buf[0] = 0x03; ret = slim_write(sdev, 0x0011, 1, buf);
    pr_info("spx_reset: 0x0011=0x03 rc=%d\n", ret);

    /* 2. Enable SWR master clock gate (CDC_CLK_RST_CTRL_SWR_CONTROL = 0xd43 bit 0) */
    buf[0] = 0xff; ret = slim_write(sdev, 0x0d43, 1, buf);
    pr_info("spx_reset: 0x0d43=0xff rc=%d\n", ret);

    /* 3. Enable MCLK */
    buf[0] = 0x01; ret = slim_write(sdev, 0x0d41, 1, buf);
    pr_info("spx_reset: 0x0d41=0x01 rc=%d\n", ret);

    msleep(100);

    /* 4. Now try the bridge sequence: write MCP_BUS_CTRL = 0x02 (start clock) */
    val = 0x02;
    ret = slim_write(sdev, 0xc85, 4, (u8 *)&val);
    pr_info("spx_reset: bridge WR_DATA=0x02 rc=%d\n", ret);

    val = 0x1044; /* MCP_BUS_CTRL */
    ret = slim_write(sdev, 0xc89, 4, (u8 *)&val);
    pr_info("spx_reset: bridge WR_ADDR=0x1044 rc=%d\n", ret);

    msleep(50);

    /* Try to read MCP_BUS_CTRL via bridge */
    val = 0x1044;
    ret = slim_write(sdev, 0xc8d, 4, (u8 *)&val);
    pr_info("spx_reset: bridge RD_ADDR=0x1044 rc=%d\n", ret);
    msleep(10);

    ret = slim_read(sdev, 0xc91, 4, buf);
    pr_info("spx_reset: bridge RD_DATA rc=%d val=%02x %02x %02x %02x (expect 02 00 00 00)\n", ret, buf[0], buf[1], buf[2], buf[3]);

    put_device(dev);
    return 0;
}

module_init(spx_reset_init);
MODULE_LICENSE("GPL");
