#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slab.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/slimbus.h>

static int __init spx_known_init(void)
{
    struct device *dev;
    struct slim_device *sdev;
    int ret;
    u8 buf[8];

    dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
    if (!dev) return -ENODEV;
    sdev = to_slim_device(dev);

    /* Read known codec registers via slim_read directly */
    struct { u16 reg; const char *name; u8 expect; } probes[] = {
        {0x0002, "RPM_CLK_GATE", 0xff},
        {0x0009, "RPM_RST_CTL", 0x07},
        {0x0021, "CHIP_ID_BYTE0", 0x00},
        {0x0023, "CHIP_ID_BYTE2", 0x00},
        {0x071b, "SIDO_VOUT_A", 0x00},
        {0x0d41, "MCLK_CONTROL", 0x01},
        {0x0d43, "SWR_CONTROL", 0xff},
    };
    int i;
    for (i = 0; i < ARRAY_SIZE(probes); i++) {
        ret = slim_read(sdev, probes[i].reg, 1, buf);
        pr_info("spx_known: slim_read 0x%04x (%s) rc=%d val=%02x (regmap had %02x)\n",
                probes[i].reg, probes[i].name, ret, buf[0], probes[i].expect);
    }

    /* Now try via the BRIDGE addresses - these aren't direct codec VE */
    /* Maybe the bridge uses a SLIMbus device address different from 217:250:1:0 */
    /* The codec may have 2 SLIMbus devices (one for codec regs, one for SWR master) */

    put_device(dev);
    return 0;
}

module_init(spx_known_init);
MODULE_LICENSE("GPL");
