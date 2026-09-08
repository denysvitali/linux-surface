#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/delay.h>
#include <linux/slab.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/slimbus.h>

static int __init spx_cb_init(void)
{
    struct device *dev;
    struct slim_device *sdev;
    int ret;
    u8 buf[4];

    dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
    if (!dev) return -ENODEV;
    sdev = to_slim_device(dev);

    /* Correct bridge address is at SLIMbus VE 0x844 (WR_DATA), 0x848 (WR_ADDR),
     * 0x84c (RD_ADDR), 0x850 (RD_DATA), 0x854 (ACCESS_STATUS)
     * because kernel regmap 0x844 maps to SLIMbus VE 0x844 (page 0)
     */

    pr_info("spx_cb: === BRIDGE at SLIMbus 0x844-0x854 ===\n");

    /* Write MCP_BUS_CTRL = 0x02 via bridge */
    /* WR_DATA = 0x02 */
    buf[0] = 0x02; buf[1] = 0x00; buf[2] = 0x00; buf[3] = 0x00;
    ret = slim_write(sdev, 0x844, 4, buf);
    pr_info("spx_cb: WR_DATA=0x02 rc=%d\n", ret);

    /* WR_ADDR = 0x1044 (MCP_BUS_CTRL) */
    buf[0] = 0x44; buf[1] = 0x10; buf[2] = 0x00; buf[3] = 0x00;
    ret = slim_write(sdev, 0x848, 4, buf);
    pr_info("spx_cb: WR_ADDR=0x1044 rc=%d\n", ret);

    msleep(50);

    /* RD_ADDR = 0x1044 */
    buf[0] = 0x44; buf[1] = 0x10; buf[2] = 0x00; buf[3] = 0x00;
    ret = slim_write(sdev, 0x84c, 4, buf);
    pr_info("spx_cb: RD_ADDR=0x1044 rc=%d\n", ret);
    msleep(10);

    /* RD_DATA read */
    ret = slim_read(sdev, 0x850, 4, buf);
    pr_info("spx_cb: RD_DATA rc=%d val=%02x %02x %02x %02x (expect 02 00 00 00)\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    /* ACCESS_STATUS */
    ret = slim_read(sdev, 0x854, 4, buf);
    pr_info("spx_cb: ACCESS_STATUS rc=%d val=%02x %02x %02x %02x\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    /* Read COMP_STATUS (0x14) */
    buf[0] = 0x14; buf[1] = 0x00; buf[2] = 0x00; buf[3] = 0x00;
    ret = slim_write(sdev, 0x84c, 4, buf);
    pr_info("spx_cb: RD_ADDR=0x14 rc=%d\n", ret);
    msleep(10);
    ret = slim_read(sdev, 0x850, 4, buf);
    pr_info("spx_cb: COMP_STATUS rc=%d val=%02x %02x %02x %02x (expect bit0=1)\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    /* Read LINK_MGR_EE (0x18) */
    buf[0] = 0x18; buf[1] = 0x00; buf[2] = 0x00; buf[3] = 0x00;
    ret = slim_write(sdev, 0x84c, 4, buf);
    msleep(10);
    ret = slim_read(sdev, 0x850, 4, buf);
    pr_info("spx_cb: LINK_MGR_EE rc=%d val=%02x %02x %02x %02x (expect 0x01)\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    /* Read INT_STATUS (0x200) */
    buf[0] = 0x00; buf[1] = 0x02; buf[2] = 0x00; buf[3] = 0x00;
    ret = slim_write(sdev, 0x84c, 4, buf);
    msleep(10);
    ret = slim_read(sdev, 0x850, 4, buf);
    pr_info("spx_cb: INT_STATUS rc=%d val=%02x %02x %02x %02x\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    /* Read MCP_FRAME_CTRL (0x101c) */
    buf[0] = 0x1c; buf[1] = 0x10; buf[2] = 0x00; buf[3] = 0x00;
    ret = slim_write(sdev, 0x84c, 4, buf);
    msleep(10);
    ret = slim_read(sdev, 0x850, 4, buf);
    pr_info("spx_cb: MCP_FRAME_CTRL rc=%d val=%02x %02x %02x %02x (expect 42 00 01 00)\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    /* Read MCP_BUS_CTRL (0x1044) - try again */
    buf[0] = 0x44; buf[1] = 0x10; buf[2] = 0x00; buf[3] = 0x00;
    ret = slim_write(sdev, 0x84c, 4, buf);
    msleep(10);
    ret = slim_read(sdev, 0x850, 4, buf);
    pr_info("spx_cb: MCP_BUS_CTRL rc=%d val=%02x %02x %02x %02x (expect 02 00 00 00)\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    put_device(dev);
    return 0;
}

module_init(spx_cb_init);
MODULE_LICENSE("GPL");
