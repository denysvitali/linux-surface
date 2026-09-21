// SPDX-License-Identifier: GPL-2.0-only
/*
 * Read-only Surface Pro X USB-C observation.
 *
 * Two facts from the SQ2 DSDT, neither of which the DT boot acts on:
 *
 *   Device UCS0 (QCOM04A9) is a 6-byte mailbox at 0x9ff90040
 *   (INFO, UPDT, CCM0, DIS0, CCM1, DIS1), inside the reserved
 *   region that starts at 0x9f800000.
 *
 *   SAM target category USC (0x1b) is the event source the HPD
 *   bridge already enables. This module only observes that
 *   category. It does not enable, disable, or acknowledge events,
 *   and it does not write the mailbox.
 */
#include <linux/io.h>
#include <linux/module.h>
#include <linux/surface_aggregator/controller.h>

static unsigned long mbox_addr = 0x9ff90040;
module_param(mbox_addr, ulong, 0444);
MODULE_PARM_DESC(mbox_addr, "UCS0 mailbox physical address (DSDT default)");

static int mbox_len = 6;
module_param(mbox_len, int, 0444);
MODULE_PARM_DESC(mbox_len, "Bytes to read from the mailbox (1..16)");

static int event_limit = 16;
module_param(event_limit, int, 0444);
MODULE_PARM_DESC(event_limit, "Maximum USC events to print");

static struct ssam_controller *ssam_ctrl;
static int events_seen;
static int events_printed;

static u32 spx_usc_notify(struct ssam_event_notifier *nf,
			  const struct ssam_event *event)
{
	int i, n;

	events_seen++;
	if (events_printed >= event_limit)
		return 0;

	events_printed++;
	n = min_t(int, event->length, 24);
	pr_info("spx_usc_observe: event tc=0x%02x tid=0x%02x cid=0x%02x iid=0x%02x len=%u\n",
		event->target_category, event->target_id, event->command_id,
		event->instance_id, event->length);
	for (i = 0; i < n; i++)
		pr_cont(" %02x", event->data[i]);
	if (n)
		pr_cont("\n");

	/* Leave acknowledgement to the existing HPD bridge. */
	return 0;
}

static struct ssam_event_notifier usc_notifier = {
	.base = {
		.priority = 2,
		.fn = spx_usc_notify,
	},
	.event = {
		.reg = SSAM_EVENT_REGISTRY_SAM,
		.id = {
			.target_category = SSAM_SSH_TC_USC,
			.instance = 0,
		},
		.mask = SSAM_EVENT_MASK_NONE,
		.flags = SSAM_EVENT_SEQUENCED,
	},
	.flags = SSAM_EVENT_NOTIFIER_OBSERVER,
};

static void spx_read_mailbox(void)
{
	void *wb;
	void __iomem *io;
	u8 raw[16];
	int len, i;

	len = clamp(mbox_len, 1, 16);
	wb = memremap(mbox_addr, len, MEMREMAP_WB);
	if (wb) {
		memcpy(raw, wb, len);
		memunmap(wb);
	} else {
		io = ioremap(mbox_addr, len);
		if (!io) {
			pr_info("spx_usc_observe: mailbox %#lx not readable\n",
				mbox_addr);
			return;
		}
		memcpy_fromio(raw, io, len);
		iounmap(io);
	}

	pr_info("spx_usc_observe: UCS0 mailbox %#lx:", mbox_addr);
	for (i = 0; i < len; i++)
		pr_cont(" %02x", raw[i]);
	pr_cont("\n");
}

static int __init spx_usc_observe_init(void)
{
	int ret;

	spx_read_mailbox();

	ssam_ctrl = ssam_get_controller();
	if (!ssam_ctrl)
		return -ENODEV;

	ret = ssam_notifier_register(ssam_ctrl, &usc_notifier);
	if (ret) {
		ssam_controller_put(ssam_ctrl);
		ssam_ctrl = NULL;
		return ret;
	}

	pr_info("spx_usc_observe: observing SAM USC events\n");
	return 0;
}

static void __exit spx_usc_observe_exit(void)
{
	if (ssam_ctrl) {
		ssam_notifier_unregister(ssam_ctrl, &usc_notifier);
		ssam_controller_put(ssam_ctrl);
	}
	pr_info("spx_usc_observe: unloaded after %d USC events\n", events_seen);
}

module_init(spx_usc_observe_init);
module_exit(spx_usc_observe_exit);

MODULE_DESCRIPTION("Read-only Surface Pro X USB-C mailbox and USC observer");
MODULE_LICENSE("GPL");
