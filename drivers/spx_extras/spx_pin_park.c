// SPDX-License-Identifier: GPL-2.0
/*
 * spx_pin_park - claim TLMM pins as plain GPIO inputs and HOLD them.
 *
 * Purpose: a live control for "are these pins electrically loaded?", with no
 * reboot and no DTB change.
 *
 * Claiming a pin through gpiod_request() runs pinmux_gpio_request(), which
 * re-muxes it from its current function (here cci_i2c) to GPIO. Freeing it on
 * rmmod restores the previous mux. So:
 *
 *   insmod spx_pin_park.ko pins=31,32,33,34   # CCI2's pins -> GPIO
 *   insmod spx_cam_go.ko                      # scan again
 *   rmmod  spx_pin_park                       # give them back to cci_i2c
 *
 * If CCI2 times out with the pins muxed and NAKs cleanly once they are parked,
 * then something on those pins is loading the bus - i.e. a device is present.
 * If it times out either way, the pins are irrelevant and the fault is inside
 * the controller.
 *
 * Unlike spx_gpio_read.ko this STAYS LOADED (returns 0), because the mux change
 * only lasts as long as the descriptors are held. spx_gpio_read used
 * gpio_device_get_desc() + gpiod_direction_input() WITHOUT a request, so it
 * never re-muxed anything and its result was meaningless.
 *
 * Input only - nothing is ever driven.
 */

#include <linux/gpio.h>
#include <linux/gpio/consumer.h>
#include <linux/gpio/machine.h>
#include <dt-bindings/gpio/gpio.h>
#include <linux/gpio/driver.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/slab.h>

#define SPX_MAX_PINS 16

static char *pins = "31,32,33,34";
module_param(pins, charp, 0444);
MODULE_PARM_DESC(pins, "comma-separated TLMM pins to park as GPIO inputs");

static struct gpio_desc *held[SPX_MAX_PINS];
static int nheld;

static void spx_release(void)
{
	while (nheld--)
		gpiod_put(held[nheld]);
	nheld = 0;
}

static int __init spx_pin_park_init(void)
{
	struct device_node *np;
	struct gpio_device *gdev;
	struct gpio_chip *gc;
	char *s, *tok, *buf;

	np = of_find_node_by_path("/soc@0/pinctrl@3100000");
	if (!np) {
		pr_info("spxpark: no TLMM node\n");
		return -ENODEV;
	}
	gdev = gpio_device_find_by_fwnode(of_fwnode_handle(np));
	of_node_put(np);
	if (!gdev) {
		pr_info("spxpark: no gpio_device for TLMM\n");
		return -ENODEV;
	}
	gc = gpio_device_get_chip(gdev);
	if (!gc) {
		gpio_device_put(gdev);
		return -ENODEV;
	}

	buf = kstrdup(pins, GFP_KERNEL);
	if (!buf) {
		gpio_device_put(gdev);
		return -ENOMEM;
	}
	s = buf;

	while ((tok = strsep(&s, ",")) != NULL && nheld < SPX_MAX_PINS) {
		struct gpio_desc *d;
		unsigned int n;

		if (!*tok || kstrtouint(tok, 10, &n))
			continue;

		/*
		 * gpiochip_request_own_desc() takes the same path as a normal
		 * consumer request, so it triggers the pinmux switch to GPIO.
		 */
		{
			int gnum = gc->base + n;
			int rc = gpio_request_one(gnum, GPIOF_IN, "spx-park");

			if (rc) {
				pr_info("spxpark: gpio%u (global %d): request failed (%d)\n",
					n, gnum, rc);
				continue;
			}
			d = gpio_to_desc(gnum);
			held[nheld++] = d;
			pr_info("spxpark: gpio%-3u parked as input, level=%d\n",
				n, gpio_get_value(gnum));
		}
	}
	kfree(buf);
	gpio_device_put(gdev);

	if (!nheld) {
		pr_info("spxpark: nothing parked\n");
		return -ENODEV;
	}
	pr_info("spxpark: holding %d pin(s) - rmmod to hand them back to pinctrl\n",
		nheld);
	return 0;
}

static void __exit spx_pin_park_exit(void)
{
	spx_release();
	pr_info("spxpark: released\n");
}

module_init(spx_pin_park_init);
module_exit(spx_pin_park_exit);
MODULE_DESCRIPTION("SPX: park TLMM pins as GPIO to test bus loading");
MODULE_LICENSE("GPL");
