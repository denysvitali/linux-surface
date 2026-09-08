#include <linux/module.h>
#include <linux/delay.h>
#include <linux/slimbus.h>

static int __init spx_b2_init(void)
{
    struct device *dev;
    struct slim_device *sdev;
    int ret;
    u8 buf[4];

    dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
    if (!dev) return -ENODEV;
    sdev = to_slim_device(dev);

    /* Try writing WR_DATA = 0xCAFEBABE, then WR_ADDR = 0x14 (COMP_STATUS),
     * then reading RD_DATA. Should give 0xCAFEBABE back if echo. */
    buf[0] = 0xBE; buf[1] = 0xBA; buf[2] = 0xFE; buf[3] = 0xCA;
    ret = slim_write(sdev, 0x844, 4, buf);
    pr_info("spx_b2: WR_DATA=0xCAFEBABE rc=%d\n", ret);

    /* WR_ADDR=0x14 (COMP_STATUS) - little endian: 14 00 00 00 */
    buf[0] = 0x14; buf[1] = 0x00; buf[2] = 0x00; buf[3] = 0x00;
    ret = slim_write(sdev, 0x848, 4, buf);
    pr_info("spx_b2: WR_ADDR=0x14 rc=%d\n", ret);

    msleep(100);

    /* Read RD_DATA (0x850) */
    ret = slim_read(sdev, 0x850, 4, buf);
    pr_info("spx_b2: RD_DATA@850 rc=%d val=%02x %02x %02x %02x\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    /* Maybe RD_DATA is at 0x851? Try byte-by-byte */
    ret = slim_read(sdev, 0x851, 1, buf);
    pr_info("spx_b2: RD_DATA@851 rc=%d val=%02x\n", ret, buf[0]);
    ret = slim_read(sdev, 0x852, 1, buf);
    pr_info("spx_b2: RD_DATA@852 rc=%d val=%02x\n", ret, buf[0]);
    ret = slim_read(sdev, 0x853, 1, buf);
    pr_info("spx_b2: RD_DATA@853 rc=%d val=%02x\n", ret, buf[0]);
    ret = slim_read(sdev, 0x854, 1, buf);
    pr_info("spx_b2: RD_DATA@854 rc=%d val=%02x\n", ret, buf[0]);

    /* Write RD_ADDR=0x14 first then read */
    buf[0] = 0x14; buf[1] = 0x00; buf[2] = 0x00; buf[3] = 0x00;
    ret = slim_write(sdev, 0x84c, 4, buf);
    pr_info("spx_b2: RD_ADDR=0x14 rc=%d\n", ret);
    msleep(50);
    ret = slim_read(sdev, 0x850, 4, buf);
    pr_info("spx_b2: RD_DATA@850 (after RD_ADDR) rc=%d val=%02x %02x %02x %02x\n",
            ret, buf[0], buf[1], buf[2], buf[3]);

    /* Try alternate bridge addresses - maybe SPX uses different layout */
    /* These are the addresses from spx_ba test where writes worked */
    const u16 wr_data_addrs[] = {0x844, 0x845, 0x848, 0x884, 0x885, 0x888, 0xc44, 0xc45, 0xc48, 0xc84, 0xc85, 0xc88};
    int i;
    pr_info("spx_b2: === Search for RD_DATA addr ===\n");
    for (i = 0; i < ARRAY_SIZE(wr_data_addrs); i++) {
        ret = slim_read(sdev, wr_data_addrs[i], 4, buf);
        pr_info("spx_b2: rd 0x%04x rc=%d val=%02x %02x %02x %02x\n",
                wr_data_addrs[i], ret, buf[0], buf[1], buf[2], buf[3]);
    }

    put_device(dev);
    return 0;
}

module_init(spx_b2_init);
MODULE_LICENSE("GPL");
