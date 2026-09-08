// SPX: read-only dump of the codec-internal SWR master registers via the
// WCD934X regmap AHB bridge (paged: regmap 0xc8d/0xc91 -> VE 0x88d/0x891).
// Reads are confirmed working (COMP_PARAMS returns 0x16840c6). One-shot;
// run only when soundwire_qcom's enum poll is idle.
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/delay.h>
#include <linux/slimbus.h>
#include <linux/mfd/wcd934x/wcd934x.h>

#define BR_RD_ADDR  0xc8d
#define BR_RD_DATA  0xc91
#define BR_STATUS   0xc96

struct r { u32 a; const char *n; };

static int __init spx_init(void)
{
	struct device *dev;
	struct wcd934x_ddata *dd;
	struct regmap *map;
	int i;
	static const struct r regs[] = {
		{0x100, "COMP_PARAMS"}, {0x014, "COMP_STATUS(frmgen b0)"},
		{0x018, "LINK_MANAGER_EE"},
		{0x200, "INT_STATUS"},  {0x204, "INT_MASK"},
		{0x500, "ENUM_CFG"},    {0x101c,"MCP_FRAME_CTRL_B0"},
		{0x105c,"MCP_FRAME_CTRL_B1"},
		{0x1044,"MCP_BUS_CTRL"},{0x1048,"MCP_CFG"},
		{0x104c,"MCP_STATUS"},  {0x1090,"MCP_SLV_STATUS"},
		{0x1054,"DIN_DP1_PCM_CTRL"},
		{0x1124,"DP1_PORT_CTRL_B0"}, {0x1164,"DP1_PORT_CTRL_B1"},
		{0x1128,"DP1_PORT_CTRL2_B0"},{0x1168,"DP1_PORT_CTRL2_B1"},
		{0x112c,"DP1_BLOCK_CTRL1"},
		{0x1130,"DP1_BLOCK_CTRL2_B0"},{0x1170,"DP1_BLOCK_CTRL2_B1"},
		{0x1134,"DP1_HCTRL_B0"},     {0x1174,"DP1_HCTRL_B1"},
		{0x1138,"DP1_BLOCK_CTRL3_B0"},{0x1178,"DP1_BLOCK_CTRL3_B1"},
		{0x113c,"DP1_SAMPLECTRL2_B0"},{0x117c,"DP1_SAMPLECTRL2_B1"},
		{0x1154,"DIN_DP2_PCM_CTRL"},
		{0x1224,"DP2_PORT_CTRL_B0"}, {0x1264,"DP2_PORT_CTRL_B1"},
		{0x122c,"DP2_BLOCK_CTRL1"},
		{0x1254,"DIN_DP3_PCM_CTRL"},
		{0x1324,"DP3_PORT_CTRL_B0"}, {0x1364,"DP3_PORT_CTRL_B1"},
		{0x132c,"DP3_BLOCK_CTRL1"},
	};

	dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
	if (!dev) { pr_err("spx_swrm_regs: no codec\n"); return -ENODEV; }
	dd = dev_get_drvdata(dev);
	put_device(dev);
	if (!dd || !dd->regmap) { pr_err("spx_swrm_regs: no regmap\n"); return -ENODEV; }
	map = dd->regmap;

	pr_info("spx_swrm_regs: === SWR master registers via bridge ===\n");
	for (i = 0; i < ARRAY_SIZE(regs); i++) {
		u32 first = 0xdeadbeef, v = 0xdeadbeef, a = regs[i].a, st = 0;
		int j, rc1, rc2;

		rc1 = regmap_bulk_write(map, BR_RD_ADDR, (u8 *)&a, 4);
		/* ACCESS_STATUS is level-high on SPX, not a completion edge. */
		usleep_range(500, 550);
		for (j = 0; !rc1 && j < 200; j++) {
			if (!regmap_read(map, BR_STATUS, &st) && (st & 1))
				break;
			udelay(5);
		}
		rc2 = regmap_bulk_read(map, BR_RD_DATA, &first, 4);
		usleep_range(500, 550);
		if (!rc2)
			rc2 = regmap_bulk_read(map, BR_RD_DATA, &v, 4);
		pr_info("spx_swrm_regs: %-22s (0x%04x) = 0x%08x first=0x%08x (wr=%d rd=%d)\n",
			regs[i].n, regs[i].a, v, first, rc1, rc2);
		usleep_range(500, 600);
	}
	pr_info("spx_swrm_regs: === done ===\n");
	return 0;
}
static void __exit spx_exit(void) {}
module_init(spx_init);
module_exit(spx_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX: dump SWR master registers via bridge");
