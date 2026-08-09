// SPDX-License-Identifier: GPL-2.0
/*
 * spx_gpio_read - read the logic level of TLMM pins as inputs.
 *
 * Why: CCI1 on gpio17-20 reports "master 1 queue 0 timeout" for every transfer,
 * whereas the (wrong) gpio31-34 config gave instant NAKs. A controller-level
 * timeout is what a bus stuck LOW looks like, but that was an inference. This
 * measures it.
 *
 *   both lines HIGH -> bus is idle; the timeout is inside the CCI block, so
 *                      these pins are probably not CCI1's after all
 *   either line LOW -> something external is holding the bus down (typically a
 *                      device whose I/O rail is still at 0 V, clamping through
 *                      its ESD diodes)
 *
 * Requesting a pin as a GPIO input re-muxes it away from cci_i2c. That is
 * reversible: the CCI pinctrl default state is re-applied on the next CCI
 * runtime resume, and spx_cam_go.ko re-selects it explicitly. Nothing is
 * driven - input only.
 *
 * Do NOT read pinctrl's pinmux-pins/pins debugfs on sc8180x to get this
 * information: that oopses with the pinctrl mutex held and needs a reboot.
 *
 * Loads with -EAGAIN by design so it can be re-run without rmmod.
 */

#include <linux/gpio/consumer.h>
#include <linux/gpio/driver.h>
#include <linux/module.h>
#include <linux/of.h>

static char *pins = "17,18,19,20";
module_param(pins, charp, 0644);
MODULE_PARM_DESC(pins, "comma-separated TLMM pin numbers to read");

static int __init spx_gpio_read_init(void)
{
	struct device_node *np;
	struct gpio_device *gdev;
	char *s, *tok, *buf;

	np = of_find_node_by_path("/soc@0/pinctrl@3100000");
	if (!np) {
		pr_info("spxgpio: no TLMM node\n");
		return -EAGAIN;
	}
	gdev = gpio_device_find_by_fwnode(of_fwnode_handle(np));
	of_node_put(np);
	if (!gdev) {
		pr_info("spxgpio: no gpio_device for TLMM\n");
		return -EAGAIN;
	}

	buf = kstrdup(pins, GFP_KERNEL);
	if (!buf)
		goto out;
	s = buf;

	while ((tok = strsep(&s, ",")) != NULL) {
		struct gpio_desc *d;
		unsigned int n;
		int val;

		if (!*tok || kstrtouint(tok, 10, &n))
			continue;

		d = gpio_device_get_desc(gdev, n);
		if (IS_ERR(d)) {
			pr_info("spxgpio: gpio%u: get_desc failed (%ld)\n",
				n, PTR_ERR(d));
			continue;
		}
		if (gpiod_direction_input(d)) {
			pr_info("spxgpio: gpio%u: cannot set input (claimed by a driver?)\n",
				n);
			continue;
		}
		val = gpiod_get_value(d);
		pr_info("spxgpio: gpio%-3u = %s\n", n,
			val < 0 ? "read error" : (val ? "HIGH (idle)" : "LOW  <-- held down"));
	}
	kfree(buf);
out:
	gpio_device_put(gdev);
	pr_info("spxgpio: done\n");
	return -EAGAIN;
}

static void __exit spx_gpio_read_exit(void) { }

module_init(spx_gpio_read_init);
module_exit(spx_gpio_read_exit);
MODULE_DESCRIPTION("SPX TLMM pin level reader");
MODULE_LICENSE("GPL");
