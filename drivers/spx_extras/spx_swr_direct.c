// SPX SWR master clock-enable hack. Matches qcom_swrm_ahb_reg_write EXACTLY
// but adds MCP_BUS_CTRL=CLK_START write which the kernel skips for v1.3.0.
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/delay.h>
#include <linux/slab.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/slimbus.h>

#define SWRM_AHB_BRIDGE_WR_DATA_0    0xc85
#define SWRM_AHB_BRIDGE_WR_ADDR_0    0xc89
#define SWRM_AHB_BRIDGE_RD_ADDR_0    0xc8d
#define SWRM_AHB_BRIDGE_RD_DATA_0    0xc91
#define SWRM_MCP_BUS_CTRL            0x1044
#define SWRM_MCP_BUS_CLK_START       BIT(1)
#define SWRM_MCP_BUS_CTRL_START      BIT(0)
#define SWRM_LINK_MANAGER_EE         0x018
#define SWRM_EE_CPU                  0x01
#define SWRM_MCP_CFG                 0x1048
#define SWRM_ENUMERATOR_CFG          0x500
#define SWRM_MCP_SLV_STATUS          0x1090
#define SWRM_COMP_STATUS             0x014

static int swr_bridge_write(struct regmap *map, u16 reg, u32 val)
{
    int ret;
    /* Match qcom.c: regmap_bulk_write of 4 bytes for data, then 4 bytes for addr */
    ret = regmap_bulk_write(map, SWRM_AHB_BRIDGE_WR_DATA_0, &val, 4);
    if (ret) { pr_info("spx: bridge wr_data rc=%d\n", ret); return ret; }
    ret = regmap_bulk_write(map, SWRM_AHB_BRIDGE_WR_ADDR_0, &reg, 4);
    if (ret) { pr_info("spx: bridge wr_addr rc=%d\n", ret); return ret; }
    return 0;
}

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

static int spx_swr_clk_probe(void)
{
    struct regmap *map;
    int ret;

    map = find_wcd934x_regmap();
    if (IS_ERR(map)) { pr_err("spx: wcd934x regmap not found\n"); return -ENODEV; }

    pr_info("spx: forcing MCP_BUS_CTRL=CLK_START (v1.3.0 kernel skips this)\n");

    /* The codec-internal SWR master clock gate is at CODEC register 0x0d43
     * (CDC_CLK_RST_CTRL_SWR_CONTROL). Without this, SWR master writes are
     * silently dropped. Write through the codec regmap first. */
    {
        unsigned int v = 0;
        regmap_read(map, 0x0d43, &v);
        pr_info("spx:   before: codec 0x0d43 = 0x%x\n", v);
        regmap_update_bits(map, 0x0d43, 0xFF, 0xFF);
        regmap_read(map, 0x0d43, &v);
        pr_info("spx:   after : codec 0x0d43 = 0x%x (all bits set)\n", v);
    }

    /* Maybe SWR master needs an explicit "core reset" via CDC register 0x0009 */
    {
        unsigned int v = 0;
        regmap_read(map, 0x0009, &v);
        pr_info("spx:   before: codec 0x0009 = 0x%x\n", v);
        /* Toggle the CDC digital reset (bit 0 = CDC_DIG_RST_N) */
        regmap_write(map, 0x0009, 0x03);  /* assert + deassert */
        msleep(10);
        regmap_write(map, 0x0009, 0x07);  /* also clear software reset */
        regmap_read(map, 0x0009, &v);
        pr_info("spx:   after : codec 0x0009 = 0x%x\n", v);
    }

    /* SIDO regulators startup sequence (matches wcd934x_bring_up) */
    {
        unsigned int v;
        regmap_write(map, 0x071b, 0x19);
        regmap_write(map, 0x071c, 0x15);
        msleep(2);
        regmap_write(map, 0x0011, 0x05);
        regmap_write(map, 0x0011, 0x07);
        regmap_write(map, 0x0009, 0x03);
        regmap_write(map, 0x0009, 0x07);
        regmap_write(map, 0x0011, 0x03);
        msleep(50);
        regmap_read(map, 0x0009, &v);
        pr_info("spx:   bring-up done, codec 0x0009 = 0x%x\n", v);
    }

    /* Step 1: clear any pending bus reset / soft reset (COMP_SW_RESET = 0x008) */
    ret = swr_bridge_write(map, 0x008, 0x00);
    pr_info("spx:   COMP_SW_RESET=0 rc=%d\n", ret);
    msleep(20);

    /* Step 2: set LINK_MANAGER_EE=CPU */
    ret = swr_bridge_write(map, SWRM_LINK_MANAGER_EE, SWRM_EE_CPU);
    pr_info("spx:   LINK_MANAGER_EE=CPU rc=%d\n", ret);
    msleep(20);

    /* Step 3: enable COMP_CFG */
    ret = swr_bridge_write(map, 0x004, 0x01);
    pr_info("spx:   COMP_CFG=ENABLE rc=%d\n", ret);
    msleep(20);

    /* Step 4: set MCP_FRAME_CTRL (rows+cols+frame_phase) */
    ret = swr_bridge_write(map, 0x101c, 0x10042);
    pr_info("spx:   MCP_FRAME_CTRL=0x10042 rc=%d\n", ret);
    msleep(20);

    /* Step 5: start the bus clock (THIS is the key write for v1.3.0) */
    ret = swr_bridge_write(map, SWRM_MCP_BUS_CTRL, SWRM_MCP_BUS_CLK_START);
    pr_info("spx:   MCP_BUS_CTRL=0x02 rc=%d\n", ret);
    msleep(100);

    /* Step 6: enable auto-enum */
    ret = swr_bridge_write(map, SWRM_ENUMERATOR_CFG, 0x01);
    pr_info("spx:   ENUM_CFG=1 rc=%d\n", ret);
    msleep(500);

    /* Verify */
    {
        u32 rb;
        u16 r;
        r = SWRM_MCP_BUS_CTRL;
        regmap_bulk_write(map, SWRM_AHB_BRIDGE_RD_ADDR_0, &r, 4);
        rb = 0;
        regmap_bulk_read(map, SWRM_AHB_BRIDGE_RD_DATA_0, &rb, 4);
        pr_info("spx:   MCP_BUS_CTRL readback=0x%x\n", rb);
        r = SWRM_COMP_STATUS;
        regmap_bulk_write(map, SWRM_AHB_BRIDGE_RD_ADDR_0, &r, 4);
        rb = 0;
        regmap_bulk_read(map, SWRM_AHB_BRIDGE_RD_DATA_0, &rb, 4);
        pr_info("spx:   COMP_STATUS readback=0x%x (bit0=frame_gen)\n", rb);
        r = SWRM_MCP_SLV_STATUS;
        regmap_bulk_write(map, SWRM_AHB_BRIDGE_RD_ADDR_0, &r, 4);
        rb = 0;
        regmap_bulk_read(map, SWRM_AHB_BRIDGE_RD_DATA_0, &rb, 4);
        pr_info("spx:   MCP_SLV_STATUS readback=0x%x\n", rb);
    }

    /* Now re-do the writes WITH readback IMMEDIATELY after each one
     * to see if ANY write sticks */
    pr_info("spx: per-write readback test\n");
    {
        u16 swrm_ee = SWRM_LINK_MANAGER_EE;
        u32 ee_val = SWRM_EE_CPU;
        regmap_bulk_write(map, SWRM_AHB_BRIDGE_WR_DATA_0, &ee_val, 4);
        regmap_bulk_write(map, SWRM_AHB_BRIDGE_WR_ADDR_0, &swrm_ee, 4);
        msleep(50);
        u32 rb = 0;
        u16 r = SWRM_LINK_MANAGER_EE;
        regmap_bulk_write(map, SWRM_AHB_BRIDGE_RD_ADDR_0, &r, 4);
        regmap_bulk_read(map, SWRM_AHB_BRIDGE_RD_DATA_0, &rb, 4);
        pr_info("spx:   EE write CPU, immediate readback=0x%x\n", rb);

        u16 swrm_bus = SWRM_MCP_BUS_CTRL;
        u32 bus_val = SWRM_MCP_BUS_CLK_START;
        regmap_bulk_write(map, SWRM_AHB_BRIDGE_WR_DATA_0, &bus_val, 4);
        regmap_bulk_write(map, SWRM_AHB_BRIDGE_WR_ADDR_0, &swrm_bus, 4);
        msleep(50);
        r = SWRM_MCP_BUS_CTRL;
        rb = 0;
        regmap_bulk_write(map, SWRM_AHB_BRIDGE_RD_ADDR_0, &r, 4);
        regmap_bulk_read(map, SWRM_AHB_BRIDGE_RD_DATA_0, &rb, 4);
        pr_info("spx:   BUS_CTRL write 0x02, immediate readback=0x%x\n", rb);
    }

    /* Now try to READ key SWR registers via bridge */
    {
        u32 val;
        int j;
        u16 regs[] = {0x014, 0x018, 0x200, 0x500, 0x1044, 0x1048, 0x1090, 0x101c};
        const char *names[] = {"COMP_STATUS", "LINK_MGR_EE", "INT_STATUS",
                               "ENUM_CFG", "MCP_BUS_CTRL", "MCP_CFG",
                               "MCP_SLV_STATUS", "MCP_FRAME_CTRL"};
        for (j = 0; j < ARRAY_SIZE(regs); j++) {
            ret = swr_bridge_write(map, 0xDEAD, regs[j]);  /* dummy to keep bus warm */
            val = 0xdeadbeef;
            ret = regmap_bulk_write(map, SWRM_AHB_BRIDGE_RD_ADDR_0, &regs[j], 4);
            if (ret) { pr_info("spx: BR rd_addr %s rc=%d\n", names[j], ret); continue; }
            ret = regmap_bulk_read(map, SWRM_AHB_BRIDGE_RD_DATA_0, &val, 4);
            pr_info("spx: BR %s (0x%x) rc=%d val=0x%x\n",
                    names[j], regs[j], ret, val);
        }
    }

    pr_info("spx: forcing MCP_BUS_CTRL done — wait for spx_reenum to repoll\n");
    return 0;
}

static int __init spx_mod_init(void) { return spx_swr_clk_probe(); }
static void __exit spx_mod_exit(void) {}
module_init(spx_mod_init);
module_exit(spx_mod_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX: force SWR master MCP_BUS_CTRL=CLK_START for v1.3.0");
