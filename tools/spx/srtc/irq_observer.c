// SPDX-License-Identifier: GPL-2.0
/* Bounded awake-only observation of SPX's already registered wake GPIO IRQ.
 * Never sets IRQ wake permission or changes the firmware event policy.
 * Load/unload under the coordinator's device lock; system sleep stays masked.
 */
#include <linux/interrupt.h>
#include <linux/irq.h>
#include <linux/module.h>
#include <linux/of.h>

static unsigned int irq;
module_param(irq, uint, 0444);
MODULE_PARM_DESC(irq, "Existing ssam_wakeup Linux IRQ for GPIO180");

static int __init spx_irq_observer_init(void)
{
	struct irq_data *data;
	struct irq_chip *chip;

	if (!of_machine_is_compatible("microsoft,surface-pro-x"))
		return -ENODEV;
	data = irq_get_irq_data(irq);
	if (!data || data->hwirq != 180 || !irqd_irq_disabled(data) ||
	    irqd_is_wakeup_set(data) ||
	    irqd_get_trigger_type(data) != IRQ_TYPE_EDGE_RISING)
		return -EINVAL;
	chip = irq_data_get_irq_chip(data);
	if (!chip || !chip->name || strcmp(chip->name, "msmgpio"))
		return -EINVAL;
	enable_irq(irq);
	pr_info("spx_srtc: enabled existing IRQ%u/GPIO180 for awake observation only\n", irq);
	return 0;
}

static void __exit spx_irq_observer_exit(void)
{
	disable_irq(irq);
	pr_info("spx_srtc: disabled observed IRQ%u; balanced awake observation\n", irq);
}

module_init(spx_irq_observer_init);
module_exit(spx_irq_observer_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SPX bounded awake SSAM GPIO IRQ observer");
