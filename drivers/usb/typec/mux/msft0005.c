// SPDX-License-Identifier: GPL-2.0
/*
 * Microsoft Display Mux driver for Surface Pro X (ACPI MSFT0005).
 *
 * This is a stub driver for the Microsoft Display Mux device found on
 * Surface Pro X. The Windows driver (DisplayMux.sys) is a KMDF driver
 * matching ACPI\MSFT0005. Reverse-engineering of the binary shows no
 * obvious GPIO, I2C, or ACPI _DSM strings; the driver likely either:
 *   - controls GPIOs via ACPI resource descriptors (to be consumed by
 *     gpio-sbu-mux via fwnode properties), or
 *   - uses an as-yet-undiscovered ACPI _DSM / control method.
 *
 * This driver registers a typec_switch and typec_mux so that the USB-C
 * stack can bind to the device. The set callbacks are no-ops for now,
 * which is sufficient to unblock Type-C/DisplayPort orientation/mux
 * plumbing until the actual control mechanism is determined.
 *
 * Copyright (C) 2026 Denys Vitali <denys@denv.it>
 */

#include <linux/acpi.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/usb/typec_mux.h>

struct msft_display_mux {
	struct typec_switch_dev *sw;
	struct typec_mux_dev *mux;
};

static int msft_display_mux_switch_set(struct typec_switch_dev *sw,
				       enum typec_orientation orientation)
{
	struct device *dev = typec_switch_get_drvdata(sw);

	dev_dbg(dev, "switch orientation: %d\n", orientation);
	/* TODO: implement actual SBU/lane mux switching */
	return 0;
}

static int msft_display_mux_mux_set(struct typec_mux_dev *mux,
				    struct typec_mux_state *state)
{
	struct device *dev = typec_mux_get_drvdata(mux);

	dev_dbg(dev, "mux mode: %lu\n", state->mode);
	/* TODO: implement actual DP/SS lane mux switching */
	return 0;
}

static int msft_display_mux_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct typec_switch_desc sw_desc = { };
	struct typec_mux_desc mux_desc = { };
	struct msft_display_mux *dmux;
	int ret;

	dmux = devm_kzalloc(dev, sizeof(*dmux), GFP_KERNEL);
	if (!dmux)
		return -ENOMEM;

	dev_info(dev, "Microsoft Display Mux (MSFT0005) probed\n");

	sw_desc.drvdata = dev;
	sw_desc.fwnode = dev_fwnode(dev);
	sw_desc.set = msft_display_mux_switch_set;

	dmux->sw = typec_switch_register(dev, &sw_desc);
	if (IS_ERR(dmux->sw))
		return dev_err_probe(dev, PTR_ERR(dmux->sw),
				     "failed to register typec switch\n");

	mux_desc.drvdata = dev;
	mux_desc.fwnode = dev_fwnode(dev);
	mux_desc.set = msft_display_mux_mux_set;

	dmux->mux = typec_mux_register(dev, &mux_desc);
	if (IS_ERR(dmux->mux)) {
		ret = PTR_ERR(dmux->mux);
		typec_switch_unregister(dmux->sw);
		return dev_err_probe(dev, ret,
				     "failed to register typec mux\n");
	}

	platform_set_drvdata(pdev, dmux);
	return 0;
}

static void msft_display_mux_remove(struct platform_device *pdev)
{
	struct msft_display_mux *dmux = platform_get_drvdata(pdev);

	typec_mux_unregister(dmux->mux);
	typec_switch_unregister(dmux->sw);
}

static const struct acpi_device_id msft_display_mux_acpi_match[] = {
	{ "MSFT0005", 0 },
	{ }
};
MODULE_DEVICE_TABLE(acpi, msft_display_mux_acpi_match);

static struct platform_driver msft_display_mux_driver = {
	.probe = msft_display_mux_probe,
	.remove = msft_display_mux_remove,
	.driver = {
		.name = "msft_display_mux",
		.acpi_match_table = ACPI_PTR(msft_display_mux_acpi_match),
		.probe_type = PROBE_PREFER_ASYNCHRONOUS,
	},
};
module_platform_driver(msft_display_mux_driver);

MODULE_AUTHOR("Denys Vitali <denys@denv.it>");
MODULE_DESCRIPTION("Microsoft Display Mux driver (Surface Pro X)");
MODULE_LICENSE("GPL");
