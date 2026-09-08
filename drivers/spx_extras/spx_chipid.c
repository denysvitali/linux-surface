#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slab.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/slimbus.h>

static int __init spx_ci_init(void)
{
    struct device *dev;
    struct slim_device *sdev;
    int ret;
    u8 buf[4];

    dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
    if (!dev) return -ENODEV;
    sdev = to_slim_device(dev);

    /* Read chip id at 0x21 */
    ret = slim_read(sdev, 0x21, 4, buf);
    pr_info("spx_ci: slim_read CHIP_ID(0x21) rc=%d val=%02x %02x %02x %02x (expect 01 08 ...)\n", ret, buf[0], buf[1], buf[2], buf[3]);

    /* Read it 2 bytes at a time */
    ret = slim_read(sdev, 0x21, 2, buf);
    pr_info("spx_ci: slim_read 0x21 2bytes rc=%d val=%02x %02x\n", ret, buf[0], buf[1]);

    ret = slim_read(sdev, 0x22, 2, buf);
    pr_info("spx_ci: slim_read 0x22 2bytes rc=%d val=%02x %02x\n", ret, buf[0], buf[1]);

    /* Read RPM_RST_CTL at 0x09 */
    ret = slim_read(sdev, 0x09, 1, buf);
    pr_info("spx_ci: slim_read 0x09 RPM_RST rc=%d val=%02x (expect 0x07)\n", ret, buf[0]);

    /* Read SWR_CLK_CTL at 0xd43 */
    ret = slim_read(sdev, 0xd43, 1, buf);
    pr_info("spx_ci: slim_read 0xd43 SWR_CLK rc=%d val=%02x (expect 0xff)\n", ret, buf[0]);

    /* Bridge register 0xc95 */
    ret = slim_read(sdev, 0xc95, 1, buf);
    pr_info("spx_ci: slim_read 0xc95 rc=%d val=%02x (regmap saw 0x0f)\n", ret, buf[0]);

    /* Bridge register 0xc91 */
    ret = slim_read(sdev, 0xc91, 1, buf);
    pr_info("spx_ci: slim_read 0xc91 rc=%d val=%02x\n", ret, buf[0]);

    /* Bridge register 0xc85 */
    ret = slim_read(sdev, 0xc85, 1, buf);
    pr_info("spx_ci: slim_read 0xc85 rc=%d val=%02x (regmap saw 0x77)\n", ret, buf[0]);

    /* Bridge register 0xc89 */
    ret = slim_read(sdev, 0xc89, 1, buf);
    pr_info("spx_ci: slim_read 0xc89 rc=%d val=%02x (regmap saw 0xaa)\n", ret, buf[0]);

    /* Try addresses the user might have for bridge: 0x10000+ (16-bit+ bridge) */
    ret = slim_read(sdev, 0x10000 + 0xc85, 4, buf);
    pr_info("spx_ci: slim_read 0x1c85 rc=%d val=%02x %02x %02x %02x\n", ret, buf[0], buf[1], buf[2], buf[3]);

    ret = slim_read(sdev, 0x10000 + 0xc91, 4, buf);
    pr_info("spx_ci: slim_read 0x1c91 rc=%d val=%02x %02x %02x %02x\n", ret, buf[0], buf[1], buf[2], buf[3]);

    put_device(dev);
    return 0;
}

module_init(spx_ci_init);
MODULE_LICENSE("GPL");
