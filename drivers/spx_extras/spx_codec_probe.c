// Deep regmap scan — read every SWR master register via the codec AHB bridge
// to find what's actually in there. Also probe some CDC registers to compare.
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slab.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/mfd/wcd934x/registers.h>
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

#define SWRM_AHB_BRIDGE_WR_DATA_0    0xc85
#define SWRM_AHB_BRIDGE_WR_ADDR_0    0xc89
#define SWRM_AHB_BRIDGE_RD_ADDR_0    0xc8d
#define SWRM_AHB_BRIDGE_RD_DATA_0    0xc91

static u32 bridge_read(struct regmap *map, u16 reg)
{
    u32 v = 0;
    regmap_bulk_write(map, SWRM_AHB_BRIDGE_RD_ADDR_0, &reg, 4);
    regmap_bulk_read(map, SWRM_AHB_BRIDGE_RD_DATA_0, &v, 4);
    return v;
}

static int bridge_write(struct regmap *map, u16 reg, u32 val)
{
    int ret;
    ret = regmap_bulk_write(map, SWRM_AHB_BRIDGE_WR_DATA_0, &val, 4);
    if (ret) return ret;
    return regmap_bulk_write(map, SWRM_AHB_BRIDGE_WR_ADDR_0, &reg, 4);
}

static int spx_deep_probe(void)
{
    struct regmap *map;
    int i, ret;

    map = find_wcd934x_regmap();
    if (IS_ERR(map)) { pr_err("spx: regmap not found\n"); return -ENODEV; }

    pr_info("spx: === DEEP SWR MASTER SCAN ===\n");

    /* Write a recognizable value to MCP_BUS_CTRL via bridge */
    {
        u32 pre = bridge_read(map, 0x1044);
        pr_info("spx: pre MCP_BUS_CTRL=0x%x\n", pre);

        /* Try writing then reading */
        ret = bridge_write(map, 0x1044, 0x02);
        pr_info("spx: bridge_write 0x1044=0x02 rc=%d\n", ret);
        msleep(50);
        u32 post = bridge_read(map, 0x1044);
        pr_info("spx: post MCP_BUS_CTRL=0x%x (expected 0x02)\n", post);

        /* Check access status */
        u32 status = bridge_read(map, 0xc96);
        pr_info("spx: ACCESS_STATUS=0x%x\n", status);
    }

    /* Dump all interesting SWR master registers */
    {
        struct { u16 reg; const char *name; } regs[] = {
            {0x000, "COMP_ID"},
            {0x004, "COMP_CFG"},
            {0x008, "COMP_SW_RESET"},
            {0x00C, "COMP_TEST_BUS"},
            {0x010, "COMP_DEBUG_BUS"},
            {0x014, "COMP_STATUS"},
            {0x018, "LINK_MANAGER_EE"},
            {0x200, "INT_STATUS"},
            {0x204, "INT_MASK"},
            {0x208, "INT_CLEAR"},
            {0x20C, "INT_CPU_EN"},
            {0x500, "ENUM_CFG"},
            {0x504, "ENUM_STATUS"},
            {0x101C, "MCP_FRAME_CTRL"},
            {0x1044, "MCP_BUS_CTRL"},
            {0x1048, "MCP_CFG"},
            {0x104C, "MCP_CMD_CTRL"},
            {0x1050, "MCP_CMD_FIFO_CFG"},
            {0x1054, "MCP_CMD_FIFO_STATUS"},
            {0x1058, "MCP_CMD_FIFO_WR_DATA"},
            {0x105C, "MCP_CMD_FIFO_RD_DATA"},
            {0x1060, "MCP_CMD_TX_CTRL"},
            {0x1064, "MCP_CMD_RX_CTRL"},
            {0x1080, "MCP_STATUS"},
            {0x1084, "MCP_SLV_STATUS_SEL"},
            {0x1090, "MCP_SLV_STATUS"},
            {0x10A0, "MCP_FIFO_CFG"},
            {0x10B0, "MCP_PHY_CTRL"},
            {0x1100, "MCP_COMP_CFG"},
            {0x1104, "MCP_COMP_CFG2"},
        };
        pr_info("spx: === SWR MASTER REGISTER DUMP ===\n");
        for (i = 0; i < ARRAY_SIZE(regs); i++) {
            u32 v = bridge_read(map, regs[i].reg);
            pr_info("spx: BR 0x%04x (%s) = 0x%08x\n", regs[i].reg, regs[i].name, v);
        }
    }

    /* Now write the master init sequence and re-dump */
    pr_info("spx: === POST-INIT DUMP ===\n");
    bridge_write(map, 0x008, 0x00);    /* COMP_SW_RESET */
    msleep(10);
    bridge_write(map, 0x018, 0x01);    /* LINK_MANAGER_EE = CPU */
    msleep(10);
    bridge_write(map, 0x004, 0x01);    /* COMP_CFG_ENABLE */
    msleep(10);
    bridge_write(map, 0x101C, 0x10042);/* MCP_FRAME_CTRL */
    msleep(10);
    bridge_write(map, 0x1044, 0x02);   /* MCP_BUS_CTRL = CLK_START */
    msleep(50);
    bridge_write(map, 0x500, 0x01);    /* ENUM_CFG = 1 */
    msleep(200);

    {
        u32 v;
        v = bridge_read(map, 0x1044);
        pr_info("spx: post-init MCP_BUS_CTRL=0x%x\n", v);
        v = bridge_read(map, 0x004);
        pr_info("spx: post-init COMP_CFG=0x%x\n", v);
        v = bridge_read(map, 0x014);
        pr_info("spx: post-init COMP_STATUS=0x%x (bit0=frame_gen)\n", v);
        v = bridge_read(map, 0x018);
        pr_info("spx: post-init LINK_MGR_EE=0x%x\n", v);
        v = bridge_read(map, 0x500);
        pr_info("spx: post-init ENUM_CFG=0x%x\n", v);
        v = bridge_read(map, 0x1054);
        pr_info("spx: post-init MCP_CMD_FIFO_STATUS=0x%x\n", v);
        v = bridge_read(map, 0x1090);
        pr_info("spx: post-init MCP_SLV_STATUS=0x%x\n", v);
    }

    /* Also do per-page-window regmap reads to see if codec has more pages */
    {
        unsigned int v;
        int sel;
        for (sel = 0; sel <= 0xf; sel++) {
            regmap_write(map, 0x800, sel);
            regmap_read(map, 0x000, &v);
            if (v != 0xff)
                pr_info("spx: page 0x%x: 0x000=0x%x\n", sel, v);
        }
    }

    return 0;
}

static int __init spx_mod_init(void) { return spx_deep_probe(); }
static void __exit spx_mod_exit(void) {}
module_init(spx_mod_init);
module_exit(spx_mod_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX deep SWR master probe");
