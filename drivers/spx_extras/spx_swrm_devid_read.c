// SPDX-License-Identifier: GPL-2.0
/*
 * Unloadable one-shot direct DevID reader for an isolated device-0 WSA881x.
 * It calls the running qcom driver's normal FIFO read helper while holding
 * the SoundWire bus lock; it does not reset or replace the controller.
 */
#include <linux/device.h>
#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/soundwire/sdw.h>
#include <linux/soundwire/sdw_registers.h>

typedef int (*spx_fifo_read_fn)(void *ctrl, u8 dev_addr, u16 reg_addr,
				u32 len, u8 *rval);

static int attempts = 10;
module_param(attempts, int, 0444);
MODULE_PARM_DESC(attempts, "Number of complete six-byte DevID attempts");

static struct device *swrm_dev;

static int __init spx_swrm_devid_read_init(void)
{
	struct kprobe resolver = {
		.symbol_name = "qcom_swrm_cmd_fifo_rd_cmd",
	};
	spx_fifo_read_fn fifo_read;
	struct sdw_bus *bus;
	void *swrm_ctrl;
	int try, byte;
	int ret;

	if (attempts < 1 || attempts > 100)
		return -EINVAL;

	swrm_dev = bus_find_device_by_name(&platform_bus_type, NULL,
					   "wcd934x-soundwire.5.auto");
	if (!swrm_dev)
		return -ENODEV;

	swrm_ctrl = dev_get_drvdata(swrm_dev);
	if (!swrm_ctrl) {
		ret = -ENODEV;
		goto err_put_device;
	}
	/* struct sdw_bus is the first member of struct qcom_swrm_ctrl. */
	bus = (struct sdw_bus *)swrm_ctrl;

	ret = register_kprobe(&resolver);
	if (ret)
		goto err_put_device;
	fifo_read = (spx_fifo_read_fn)resolver.addr;
	unregister_kprobe(&resolver);
	if (!fifo_read) {
		ret = -ENOENT;
		goto err_put_device;
	}

	mutex_lock(&bus->bus_lock);
	for (try = 0; try < attempts; try++) {
		u8 id[SDW_NUM_DEV_ID_REGISTERS] = { 0 };
		int results[SDW_NUM_DEV_ID_REGISTERS] = { 0 };

		for (byte = 0; byte < SDW_NUM_DEV_ID_REGISTERS; byte++)
			results[byte] = fifo_read(swrm_ctrl, 0,
						 SDW_SCP_DEVID_0 + byte,
						 1, &id[byte]);

		pr_info("spx_devid %d/%d id=%02x:%02x:%02x:%02x:%02x:%02x ret=%d,%d,%d,%d,%d,%d\n",
			try + 1, attempts, id[0], id[1], id[2], id[3],
			id[4], id[5], results[0], results[1], results[2],
			results[3], results[4], results[5]);
	}
	mutex_unlock(&bus->bus_lock);

	pr_info("spx_swrm_devid_read: complete (device 0, read-only)\n");
	return 0;

err_put_device:
	put_device(swrm_dev);
	swrm_dev = NULL;
	return ret;
}

static void __exit spx_swrm_devid_read_exit(void)
{
	if (swrm_dev)
		put_device(swrm_dev);
	pr_info("spx_swrm_devid_read: unloaded\n");
}

module_init(spx_swrm_devid_read_init);
module_exit(spx_swrm_devid_read_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX unloadable direct device-0 SoundWire DevID reader");
