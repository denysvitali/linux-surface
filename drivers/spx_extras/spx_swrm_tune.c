// SPDX-License-Identifier: GPL-2.0
/* One-shot SPX SoundWire master data-port register writer. */
#include <linux/delay.h>
#include <linux/completion.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>
#include <linux/soundwire/sdw.h>

struct dentry;
/* Prefix shared with the running qcom_swrm_ctrl and live-health helper. */
struct spx_swrm_lock_prefix {
	struct sdw_bus bus;
	struct device *dev;
	struct regmap *regmap;
	u32 max_reg;
	const unsigned int *reg_layout;
	void __iomem *mmio;
	struct reset_control *audio_cgcr;
#ifdef CONFIG_DEBUG_FS
	struct dentry *debugfs;
#endif
	struct completion broadcast;
	struct completion enumeration;
	struct mutex ahb_lock;
	struct mutex controller_lock;
};

#define SPX_BRIDGE_WR_DATA	0xc85
#define SPX_BRIDGE_WR_ADDR	0xc89
#define SPX_SWRM_DP_FIRST	0x0000
#define SPX_SWRM_DP_LAST		0x173c

static uint swrm_reg;
module_param(swrm_reg, uint, 0400);
MODULE_PARM_DESC(swrm_reg, "SoundWire master data-port register address");

static uint swrm_val;
module_param(swrm_val, uint, 0400);
MODULE_PARM_DESC(swrm_val, "32-bit value to write");

static int __init spx_swrm_tune_init(void)
{
	struct wcd934x_ddata *ddata;
	struct device *dev;
	struct device *master;
	struct spx_swrm_lock_prefix *ctrl;
	u32 request[2] = { swrm_val, swrm_reg };
	int ret;

	if (swrm_reg < SPX_SWRM_DP_FIRST || swrm_reg > SPX_SWRM_DP_LAST)
		return -EINVAL;

	dev = bus_find_device_by_name(&slimbus_bus, NULL, "217:250:1:0");
	if (!dev)
		return -ENODEV;

	ddata = dev_get_drvdata(dev);
	if (!ddata || !ddata->regmap) {
		ret = -ENODEV;
		goto out_put;
	}
	master = bus_find_device_by_name(&platform_bus_type, NULL,
					 "wcd934x-soundwire.5.auto");
	if (!master) {
		ret = -ENODEV;
		goto out_put;
	}
	ctrl = dev_get_drvdata(master);
	if (!ctrl || ctrl->regmap != ddata->regmap) {
		ret = -ENODEV;
		goto out_master;
	}

	/* Match the running driver's contiguous WR_DATA + WR_ADDR transfer.
	 * Separate writes can submit an incomplete bridge command.
	 */
	/* The nested WCD IRQ still runs with master CPU_EN=0. Serialize the
	 * complete command and settle interval with its bridge transactions.
	 */
	mutex_lock(&ctrl->controller_lock);
	mutex_lock(&ctrl->ahb_lock);
	ret = regmap_bulk_write(ddata->regmap, SPX_BRIDGE_WR_DATA,
				request, sizeof(request));
	if (!ret) {
		usleep_range(500, 550);
		dev_info(dev, "SPX: SWRM register 0x%04x <- 0x%08x\n",
			 swrm_reg, swrm_val);
	}
	mutex_unlock(&ctrl->ahb_lock);
	mutex_unlock(&ctrl->controller_lock);

out_master:
	put_device(master);

out_put:
	put_device(dev);
	return ret;
}

static void __exit spx_swrm_tune_exit(void)
{
}

module_init(spx_swrm_tune_init);
module_exit(spx_swrm_tune_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX one-shot SoundWire master data-port tuner");
