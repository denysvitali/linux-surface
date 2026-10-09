// SPDX-License-Identifier: GPL-2.0-only
/* Load/remove only with CAMSS and OV5693 unloaded and no video owners. */
#include <linux/module.h>
#include <linux/of.h>
static const u8 overlay[] = {
#include "front-enable.inc"
};
static int overlay_id = -1;
static int __init front_enable_init(void)
{
	return of_overlay_fdt_apply(overlay, sizeof(overlay), &overlay_id, NULL);
}
static void __exit front_enable_exit(void)
{
	int ret = of_overlay_remove(&overlay_id);
	if (ret)
		pr_err("spx_front_enable: overlay removal failed: %d\n", ret);
}
module_init(front_enable_init);
module_exit(front_enable_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Restore SPX front camera live graph without reboot");
