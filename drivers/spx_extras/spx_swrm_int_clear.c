// SPDX-License-Identifier: GPL-2.0
/*
 * SPX: clear the SWR master's latched interrupt status via the paged WCD934X
 * bridge, so that INT_STATUS read after a stream reflects only that stream.
 *
 * SWRM_INTERRUPT_STATUS is sticky: reading 0x18a after a run proves nothing
 * unless the bits were cleared beforehand. Load this before playback, then dump
 * with spx_swrm_regs.ko afterwards.
 *
 * Uses the same bridge discipline as spx_swrm_regs.ko (500us settle, level-high
 * status bit 0, throwaway first read) rather than the qcom AHB path, which stops
 * completing partway through a session.
 *
 * Fails to load with -EAGAIN by design so it can be re-run without rmmod.
 */
#include <linux/delay.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>

#define BR_WR_DATA		0x0c85
#define BR_RD_ADDR		0x0c8d
#define BR_RD_DATA		0x0c91
#define BR_STATUS		0x0c96

#define SWRM_INTERRUPT_STATUS	0x0200
#define SWRM_INTERRUPT_CLEAR	0x0208

static struct regmap *map;

static int br_read(u32 reg, u32 *val)
{
	u32 addr = reg, first = 0, v = 0;
	int i, ret;

	ret = regmap_bulk_write(map, BR_RD_ADDR, (u8 *)&addr, 4);
	if (ret)
		return ret;
	usleep_range(500, 550);
	for (i = 0; i < 200; i++) {
		u32 st;

		if (!regmap_read(map, BR_STATUS, &st) && (st & 1))
			break;
		udelay(5);
	}
	ret = regmap_bulk_read(map, BR_RD_DATA, &first, 4);
	if (ret)
		return ret;
	usleep_range(500, 550);
	ret = regmap_bulk_read(map, BR_RD_DATA, &v, 4);
	if (ret)
		return ret;
	*val = v;
	return 0;
}

static int br_write(u32 reg, u32 val)
{
	u32 request[2] = { val, reg };
	int ret;

	ret = regmap_bulk_write(map, BR_WR_DATA, (u8 *)request,
				sizeof(request));
	usleep_range(500, 550);
	return ret;
}

static int __init spx_int_clear_init(void)
{
	struct wcd934x_ddata *dd;
	struct device *dev;
	u32 before = 0, after = 0;

	dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
	if (!dev)
		return -ENODEV;
	dd = dev_get_drvdata(dev);
	put_device(dev);
	if (!dd || !dd->regmap)
		return -ENODEV;
	map = dd->regmap;

	br_read(SWRM_INTERRUPT_STATUS, &before);
	br_write(SWRM_INTERRUPT_CLEAR, ~0U);
	br_read(SWRM_INTERRUPT_STATUS, &after);

	pr_info("spx_int_clear: INT_STATUS 0x%08x -> 0x%08x\n", before, after);

	return -EAGAIN;
}

static void __exit spx_int_clear_exit(void)
{
}

module_init(spx_int_clear_init);
module_exit(spx_int_clear_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX: clear latched SWR master interrupt status");
