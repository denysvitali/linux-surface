// Test direct slim_write to bridge registers
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slab.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/slimbus.h>

static int __init spx_db_init(void)
{
    struct device *dev;
    struct slim_device *sdev;
    int ret;
    u8 buf[4];

    dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
    if (!dev) return -ENODEV;
    sdev = to_slim_device(dev);

    pr_info("spx_db: === TEST DIRECT slim_write TO BRIDGE ===\n");

    /* Write MCP_BUS_CTRL = 0x02 via direct slim_write */
    buf[0] = 0x02; buf[1] = 0x00; buf[2] = 0x00; buf[3] = 0x00;
    ret = slim_write(sdev, 0xc85, 4, buf);
    pr_info("spx_db: slim_write 0xc85=0x00000002 rc=%d\n", ret);
    usleep_range(1000, 1100);

    /* Write the address (MCP_BUS_CTRL = 0x1044) */
    buf[0] = 0x44; buf[1] = 0x10; buf[2] = 0x00; buf[3] = 0x00;
    ret = slim_write(sdev, 0xc89, 4, buf);
    pr_info("spx_db: slim_write 0xc89=0x00001044 rc=%d\n", ret);
    usleep_range(10000, 10500);

    /* Read back RD_DATA_0 */
    ret = slim_read(sdev, 0xc91, 4, buf);
    pr_info("spx_db: slim_read 0xc91 rc=%d val=%02x %02x %02x %02x\n", ret, buf[0], buf[1], buf[2], buf[3]);

    /* Try RD_ADDR_0 first, then RD_DATA_0 */
    buf[0] = 0x44; buf[1] = 0x10; buf[2] = 0x00; buf[3] = 0x00;
    ret = slim_write(sdev, 0xc8d, 4, buf);
    pr_info("spx_db: slim_write 0xc8d=0x00001044 rc=%d\n", ret);
    usleep_range(10000, 10500);

    ret = slim_read(sdev, 0xc91, 4, buf);
    pr_info("spx_db: slim_read 0xc91 (after RD_ADDR) rc=%d val=%02x %02x %02x %02x\n", ret, buf[0], buf[1], buf[2], buf[3]);

    /* Try reading chip ID via slim_read directly */
    ret = slim_read(sdev, 0x0000, 4, buf);
    pr_info("spx_db: slim_read CHIP_ID (0x0000) rc=%d val=%02x %02x %02x %02x\n", ret, buf[0], buf[1], buf[2], buf[3]);

    /* Read CHIP_ID via regmap (reg_bits=16, val_bits=8) */
    ret = slim_read(sdev, 0x0000, 2, buf);
    pr_info("spx_db: slim_read CHIP_ID 2bytes rc=%d val=%02x %02x\n", ret, buf[0], buf[1]);

    /* Test access_status */
    ret = slim_read(sdev, 0xc96, 4, buf);
    pr_info("spx_db: slim_read ACCESS_STATUS rc=%d val=%02x %02x %02x %02x\n", ret, buf[0], buf[1], buf[2], buf[3]);

    put_device(dev);
    return 0;
}

module_init(spx_db_init);
MODULE_LICENSE("GPL");
