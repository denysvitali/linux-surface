// SPDX-License-Identifier: GPL-2.0
/*
 * Reversible reproduction of qcauddev8180's command-serialization handshake.
 * The running qcom driver's locked AHB helpers remain in charge of all access.
 */
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/platform_device.h>

#define SWRM_COMP_STATUS	0x0014
#define SWRM_ENUM_CFG		0x0500
#define SWRM_MCP_CFG		0x1048
#define SWRM_MCP_CFG_SYNC	BIT(1)
#define SWRM_COMP_SYNC_MASK	GENMASK(5, 4)
#define SWRM_COMP_SYNC_READY	(2U << 4)

typedef int (*spx_ahb_read_fn)(void *ctrl, int reg, u32 *val);
typedef int (*spx_ahb_write_fn)(void *ctrl, int reg, int val);

static struct device *swrm_dev;
static void *swrm_ctrl;
static spx_ahb_read_fn swrm_read;
static spx_ahb_write_fn swrm_write;
static u32 saved_mcp_cfg;
static bool changed;

static void *resolve_symbol(const char *name)
{
	struct kprobe resolver = {
		.symbol_name = name,
	};
	void *addr;
	int ret;

	ret = register_kprobe(&resolver);
	if (ret)
		return NULL;
	addr = resolver.addr;
	unregister_kprobe(&resolver);
	return addr;
}

static int windows_sync(const char *stage)
{
	u32 comp = 0;
	u32 cfg = 0;
	int outer;
	int inner;
	int ret;

	/*
	 * qcauddev8180 uses nested five-attempt loops.  There is no delay in
	 * the observed loop; retain that behavior rather than inventing one.
	 */
	for (outer = 0; outer < 5; outer++) {
		ret = swrm_read(swrm_ctrl, SWRM_MCP_CFG, &cfg);
		if (ret)
			return ret;
		ret = swrm_write(swrm_ctrl, SWRM_MCP_CFG,
				 cfg | SWRM_MCP_CFG_SYNC);
		if (ret)
			return ret;
		for (inner = 0; inner < 5; inner++) {
			ret = swrm_read(swrm_ctrl, SWRM_COMP_STATUS, &comp);
			if (ret)
				return ret;
			if ((comp & SWRM_COMP_SYNC_MASK) ==
			    SWRM_COMP_SYNC_READY) {
				pr_info("spx_swrm_windows_handshake: %s ready cfg=%#x comp=%#x attempts=%d/%d\n",
					stage, (u32)(cfg | SWRM_MCP_CFG_SYNC), comp,
					outer + 1, inner + 1);
				return 0;
			}
		}
	}

	pr_info("spx_swrm_windows_handshake: %s NOT ready cfg=%#x comp=%#x\n",
		stage, (u32)(cfg | SWRM_MCP_CFG_SYNC), comp);
	return -ETIMEDOUT;
}

static int __init spx_swrm_windows_handshake_init(void)
{
	int ret;
	int ret0;
	int ret1;

	swrm_dev = bus_find_device_by_name(&platform_bus_type, NULL,
					   "wcd934x-soundwire.5.auto");
	if (!swrm_dev)
		return -ENODEV;
	swrm_ctrl = dev_get_drvdata(swrm_dev);
	swrm_read = resolve_symbol("qcom_swrm_ahb_reg_read");
	swrm_write = resolve_symbol("qcom_swrm_ahb_reg_write");
	if (!swrm_ctrl || !swrm_read || !swrm_write) {
		ret = -ENOENT;
		goto err_put;
	}

	ret = swrm_read(swrm_ctrl, SWRM_MCP_CFG, &saved_mcp_cfg);
	if (ret)
		goto err_put;
	ret = windows_sync("pre-enum");
	changed = true;
	if (ret)
		goto err_restore;

	ret0 = swrm_write(swrm_ctrl, SWRM_ENUM_CFG, 0);
	ret1 = swrm_write(swrm_ctrl, SWRM_ENUM_CFG, 1);
	pr_info("spx_swrm_windows_handshake: enum rearm results=%d,%d saved_cfg=%#x\n",
		ret0, ret1, saved_mcp_cfg);
	if (ret0 || ret1) {
		ret = ret0 ? ret0 : ret1;
		goto err_restore;
	}
	return 0;

err_restore:
	swrm_write(swrm_ctrl, SWRM_MCP_CFG, saved_mcp_cfg);
	changed = false;
err_put:
	put_device(swrm_dev);
	swrm_dev = NULL;
	return ret;
}

static void __exit spx_swrm_windows_handshake_exit(void)
{
	if (changed)
		swrm_write(swrm_ctrl, SWRM_MCP_CFG, saved_mcp_cfg);
	if (swrm_dev)
		put_device(swrm_dev);
	pr_info("spx_swrm_windows_handshake: restored cfg=%#x and unloaded\n",
		saved_mcp_cfg);
}

module_init(spx_swrm_windows_handshake_init);
module_exit(spx_swrm_windows_handshake_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX reversible Windows SoundWire command handshake");
