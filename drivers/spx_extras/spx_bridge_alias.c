// Test if 0xc95 mirror to 0xc91 (write 0xc85 separately)
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slab.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/slimbus.h>

static struct regmap *find_wcd934x_regmap(void)
{
    struct device *dev;
    struct wcd934x_ddata *ddata;
    dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
    if (!dev) return ERR_PTR(-ENODEV);
    ddata = dev_get_drvdata(dev);
    put_device(dev);
    if (!ddata || !ddata->regmap) return ERR_PTR(-ENODEV);
    return ddata->regmap;
}

static int __init spx_ba_init(void)
{
    struct regmap *map;
    unsigned int v;

    map = find_wcd934x_regmap();
    if (IS_ERR(map)) return -ENODEV;

    /* First read - what's currently in each bridge reg */
    regmap_read(map, 0xc85, &v); pr_info("spx_ba: 0xc85 = 0x%02x\n", v);
    regmap_read(map, 0xc89, &v); pr_info("spx_ba: 0xc89 = 0x%02x\n", v);
    regmap_read(map, 0xc8d, &v); pr_info("spx_ba: 0xc8d = 0x%02x\n", v);
    regmap_read(map, 0xc91, &v); pr_info("spx_ba: 0xc91 = 0x%02x\n", v);
    regmap_read(map, 0xc95, &v); pr_info("spx_ba: 0xc95 = 0x%02x\n", v);

    /* Write 0xc85=0x42, then read 0xc91 */
    pr_info("spx_ba: TEST 1: write 0xc85=0x42\n");
    regmap_write(map, 0xc85, 0x42);
    regmap_read(map, 0xc91, &v); pr_info("spx_ba: 0xc91 = 0x%02x (expect 0x42 if mirror)\n", v);
    regmap_read(map, 0xc85, &v); pr_info("spx_ba: 0xc85 = 0x%02x\n", v);

    /* Write 0xc89=0xAA, then read 0xc8d */
    pr_info("spx_ba: TEST 2: write 0xc89=0xAA\n");
    regmap_write(map, 0xc89, 0xAA);
    regmap_read(map, 0xc8d, &v); pr_info("spx_ba: 0xc8d = 0x%02x (expect 0xAA if mirror)\n", v);

    /* Write 0xc8d=0x33, then read 0xc91 */
    pr_info("spx_ba: TEST 3: write 0xc8d=0x33\n");
    regmap_write(map, 0xc8d, 0x33);
    regmap_read(map, 0xc91, &v); pr_info("spx_ba: 0xc91 = 0x%02x (expect 0x33 if read-trigger)\n", v);

    /* Bypass cache and try again */
    pr_info("spx_ba: TEST 4: cache_bypass reads\n");
    regmap_write(map, 0xc85, 0x77);
    regmap_read(map, 0xc91, &v); pr_info("spx_ba: (cache) 0xc91 = 0x%02x\n", v);
    /* bypass */
    {
        unsigned int val = 0xff;
        int ret = regmap_bulk_read(map, 0xc91, &val, 4);
        pr_info("spx_ba: (bypass) 0xc91 bulk_read rc=%d val=0x%x\n", ret, val);
    }

    /* Try slimbus direct */
    {
        struct device *dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
        struct slim_device *sdev = to_slim_device(dev);
        u8 buf[4] = {0};
        int ret;

        /* Read 0xc95 directly via slim_read */
        ret = slim_read(sdev, 0xc95, 4, buf);
        pr_info("spx_ba: slim_read 0xc95 rc=%d val=%02x %02x %02x %02x\n", ret, buf[0], buf[1], buf[2], buf[3]);

        ret = slim_read(sdev, 0xc91, 4, buf);
        pr_info("spx_ba: slim_read 0xc91 rc=%d val=%02x %02x %02x %02x\n", ret, buf[0], buf[1], buf[2], buf[3]);

        /* Read 0x0000 - chip ID */
        ret = slim_read(sdev, 0x0000, 4, buf);
        pr_info("spx_ba: slim_read 0x0000 rc=%d val=%02x %02x %02x %02x\n", ret, buf[0], buf[1], buf[2], buf[3]);

        put_device(dev);
    }

    return 0;
}

module_init(spx_ba_init);
MODULE_LICENSE("GPL");
