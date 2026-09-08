// Slim device state probe
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/delay.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/slimbus.h>

static int spx_state_probe(void)
{
    struct device *dev;
    struct slim_device *sdev;

    dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
    if (!dev) { pr_err("spx: wcd934x slim not found\n"); return -ENODEV; }
    sdev = to_slim_device(dev);

    pr_info("spx: === SLIM DEVICE STATE ===\n");
    pr_info("spx:   dev name: %s\n", dev_name(dev));
    pr_info("spx:   dev init_name: %s\n", dev->init_name ? dev->init_name : "(null)");
    pr_info("spx:   slim_device laddr=0x%x\n", sdev->laddr);
    pr_info("spx:   slim_device eaddr: %02x:%02x:%02x:%02x\n",
            sdev->e_addr.manf_id, sdev->e_addr.prod_code,
            sdev->e_addr.dev_index, sdev->e_addr.instance);
    pr_info("spx:   slim_device->ctrl: %p\n", sdev->ctrl);

    put_device(dev);

    /* Now try via regmap - should work */
    {
        struct wcd934x_ddata *ddata = dev_get_drvdata(dev);
        unsigned int v;
        int ret;
        if (ddata && ddata->regmap) {
            regmap_read(ddata->regmap, 0x0009, &v);
            pr_info("spx:   regmap_read 0x0009 = 0x%x (sanity)\n", v);
            regmap_read(ddata->regmap, 0x0c91, &v);
            pr_info("spx:   regmap_read 0x0c91 = 0x%x\n", v);

            /* Try writing to high addresses directly */
            ret = regmap_write(ddata->regmap, 0x0c85, 0x02);
            pr_info("spx:   regmap_write 0x0c85=0x02 rc=%d\n", ret);
            ret = regmap_write(ddata->regmap, 0x0c89, 0x44);
            pr_info("spx:   regmap_write 0x0c89=0x44 rc=%d\n", ret);
            ret = regmap_write(ddata->regmap, 0x0c8a, 0x10);
            pr_info("spx:   regmap_write 0x0c8a=0x10 rc=%d\n", ret);
            msleep(50);
            ret = regmap_read(ddata->regmap, 0x0c91, &v);
            pr_info("spx:   regmap_read 0x0c91 rc=%d v=0x%x\n", ret, v);
        }
    }

    /* Direct slim_read test */
    {
        u8 buf[4] = {0};
        int ret;
        ret = slim_read(sdev, 0x0c91, 4, buf);
        pr_info("spx:   slim_read 0x0c91 rc=%d bytes=%02x %02x %02x %02x\n",
                ret, buf[0], buf[1], buf[2], buf[3]);
    }

    /* Try well below 0xC00 limit */
    {
        u8 buf[4] = {0};
        int ret;
        ret = slim_read(sdev, 0x0bfc, 4, buf);
        pr_info("spx:   slim_read 0x0bfc rc=%d bytes=%02x %02x %02x %02x\n",
                ret, buf[0], buf[1], buf[2], buf[3]);
    }
    /* And a known-good CDC reg 0x0009 */
    {
        u8 buf[2] = {0};
        int ret;
        ret = slim_read(sdev, 0x0009, 2, buf);
        pr_info("spx:   slim_read 0x0009 rc=%d bytes=%02x %02x\n",
                ret, buf[0], buf[1]);
    }
    /* Read the chip ID */
    {
        u8 buf[2] = {0};
        int ret;
        ret = slim_read(sdev, 0x0000, 2, buf);
        pr_info("spx:   slim_read 0x0000 rc=%d bytes=%02x %02x (CHIP_ID)\n",
                ret, buf[0], buf[1]);
    }

    return 0;
}

static int __init spx_mod_init(void) { return spx_state_probe(); }
static void __exit spx_mod_exit(void) {}
module_init(spx_mod_init);
module_exit(spx_mod_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX slim device state probe");
