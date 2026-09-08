// Probe 0xc95 (unknown bridge register) and try enabling the master
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

static int __init spx_bridge_enable_init(void)
{
    struct regmap *map;
    unsigned int v;
    int i;
    u16 probes[] = {0xc80, 0xc90, 0xc95, 0xc97, 0xc98, 0x0090, 0x0094, 0x0098};

    map = find_wcd934x_regmap();
    if (IS_ERR(map)) return -ENODEV;

    pr_info("spx_be: === PROBE BRIDGE REGION 0xc80-0xc98 ===\n");
    for (i = 0; i < ARRAY_SIZE(probes); i++) {
        regmap_read(map, probes[i], &v);
        pr_info("spx_be: read 0x%04x = 0x%02x\n", probes[i], v);
    }

    // Dump 0xc80-0xc9f in detail
    for (i = 0xc80; i <= 0xc9f; i++) {
        regmap_read(map, i, &v);
        if (v != 0)
            pr_info("spx_be: 0x%04x = 0x%02x\n", i, v);
    }

    // Try writing 0xc95 with various values to see if anything responds
    pr_info("spx_be: trying 0xc95 writes\n");
    for (i = 0; i <= 0xff; i += 0x11) {
        regmap_write(map, 0xc95, i);
        msleep(10);
        regmap_read(map, 0xc91, &v);
        regmap_read(map, 0xc95, &v);
        pr_info("spx_be: wrote 0xc95=0x%02x, read 0xc95=0x%02x, 0xc91=0x%02x\n", i, v, v);
    }

    // Try the dead-codec approach: trigger a fresh SWR master reset via 0xc95 bit
    regmap_write(map, 0xc95, 0x0f);
    msleep(50);
    regmap_read(map, 0xc91, &v);
    regmap_read(map, 0x101c, &v);
    pr_info("spx_be: after 0xc95=0x0f, MCP_FRAME_CTRL=0x%x\n", v);

    return 0;
}

module_init(spx_bridge_enable_init);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX bridge enable probe");
