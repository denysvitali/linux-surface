#include <linux/module.h>
#include <linux/delay.h>
#include <linux/slimbus.h>

static int spx_read_bridge(struct slim_device *sdev, u16 reg, u32 *out_val)
{
    int ret;
    u8 buf[4];
    ret = slim_read(sdev, reg, 4, buf);
    if (ret < 0) return ret;
    *out_val = buf[0] | (buf[1] << 8) | (buf[2] << 16) | (buf[3] << 24);
    return 0;
}

static int spx_write_bridge(struct slim_device *sdev, u16 reg, u32 val)
{
    u8 buf[4] = {val & 0xff, (val >> 8) & 0xff, (val >> 16) & 0xff, (val >> 24) & 0xff};
    return slim_write(sdev, reg, 4, buf);
}

static int __init spx_b3_init(void)
{
    struct device *dev;
    struct slim_device *sdev;
    int ret;
    u32 val;

    dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
    if (!dev) return -ENODEV;
    sdev = to_slim_device(dev);

    /* Try RD_ADDR at 0x84c - test by writing and reading */
    ret = spx_write_bridge(sdev, 0x84c, 0xCAFEBABE);
    pr_info("spx_b3: WR RD_ADDR=0xCAFEBABE rc=%d\n", ret);

    ret = spx_read_bridge(sdev, 0x84c, &val);
    pr_info("spx_b3: RD RD_ADDR rc=%d val=0x%08x (expect 0xCAFEBABE)\n", ret, val);

    /* Check RD_DATA at 0x850 - we expect it to be different from WR_DATA */
    ret = spx_read_bridge(sdev, 0x850, &val);
    pr_info("spx_b3: RD_DATA@850 rc=%d val=0x%08x\n", ret, val);

    /* ACCESS_STATUS at 0x854 */
    ret = spx_read_bridge(sdev, 0x854, &val);
    pr_info("spx_b3: ACCESS_STATUS@854 rc=%d val=0x%08x\n", ret, val);

    /* Try the sequence: write WR_ADDR first (to address a reg),
     * then read RD_DATA to get the value */
    /* 1. WR_ADDR = 0x14 (COMP_STATUS) */
    ret = spx_write_bridge(sdev, 0x848, 0x14);
    pr_info("spx_b3: WR_ADDR=0x14 rc=%d\n", ret);
    msleep(50);

    /* 2. Write WR_DATA = anything (this triggers read) */
    ret = spx_write_bridge(sdev, 0x844, 0xDEADBEEF);
    pr_info("spx_b3: WR_DATA=0xDEADBEEF rc=%d\n", ret);
    msleep(50);

    /* 3. Read RD_DATA */
    ret = spx_read_bridge(sdev, 0x850, &val);
    pr_info("spx_b3: RD_DATA@850 (after WR_ADDR=0x14, WR_DATA=0xDEADBEEF) val=0x%08x\n", val);

    /* Read COMP_STATUS again */
    msleep(100);
    ret = spx_read_bridge(sdev, 0x850, &val);
    pr_info("spx_b3: RD_DATA@850 (re-read) val=0x%08x\n", val);

    /* Try with RD_ADDR pre-set */
    ret = spx_write_bridge(sdev, 0x84c, 0x14);
    pr_info("spx_b3: RD_ADDR=0x14 rc=%d\n", ret);
    msleep(50);

    ret = spx_read_bridge(sdev, 0x850, &val);
    pr_info("spx_b3: RD_DATA@850 (after RD_ADDR=0x14) val=0x%08x\n", val);

    /* Check RD_ADDR location alternatives */
    const u16 addrs[] = {0x84c, 0x850, 0x854, 0x858, 0x85c, 0x860, 0x864, 0x868, 0x86c, 0x870, 0x874, 0x878};
    int i;
    pr_info("spx_b3: === Reading bridge region 0x84c-0x878 ===\n");
    for (i = 0; i < ARRAY_SIZE(addrs); i++) {
        ret = spx_read_bridge(sdev, addrs[i], &val);
        if (val != 0)
            pr_info("spx_b3: 0x%04x val=0x%08x\n", addrs[i], val);
    }

    /* Now check the second bridge (0x884-0x8a8) */
    pr_info("spx_b3: === Reading second bridge 0x884-0x8a8 ===\n");
    for (i = 0x884; i < 0x8a8; i += 4) {
        ret = spx_read_bridge(sdev, i, &val);
        if (val != 0)
            pr_info("spx_b3: 0x%04x val=0x%08x\n", i, val);
    }

    put_device(dev);
    return 0;
}

module_init(spx_b3_init);
MODULE_LICENSE("GPL");
