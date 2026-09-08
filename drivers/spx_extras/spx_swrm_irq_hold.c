// SPDX-License-Identifier: GPL-2.0
/* Temporarily quiesce the dedicated WCD SoundWire nested IRQ for diagnostics. */
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/platform_device.h>

static int held_irq = -1;

static int __init spx_irq_hold_init(void)
{
	struct device *dev;
	int irq;

	dev = bus_find_device_by_name(&platform_bus_type, NULL,
				      "wcd934x-soundwire.5.auto");
	if (!dev)
		return -ENODEV;
	irq = platform_get_irq(to_platform_device(dev), 0);
	put_device(dev);
	if (irq < 0)
		return irq;
	disable_irq(irq);
	held_irq = irq;
	pr_info("spxirqhold disabled SoundWire IRQ %d\n", irq);
	return 0;
}

static void __exit spx_irq_hold_exit(void)
{
	enable_irq(held_irq);
	pr_info("spxirqhold restored SoundWire IRQ %d\n", held_irq);
}
module_init(spx_irq_hold_init);
module_exit(spx_irq_hold_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX reversible dedicated SoundWire IRQ hold");
