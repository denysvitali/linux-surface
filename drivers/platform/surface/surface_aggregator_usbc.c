// SPDX-License-Identifier: GPL-2.0-only
/*
 * Experimental Surface Pro X USC-to-DP0 hotplug forwarding.
 * Load after the desktop starts, then replug the dock. No initial-state query,
 * PHY orientation switching or second-port routing is implemented yet.
 * Never unbind/reload live MSM components when testing this driver.
 */
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/unaligned.h>
#include <linux/workqueue.h>
#include <linux/surface_aggregator/controller.h>

#include <drm/drm_bridge.h>
#include <drm/drm_connector.h>
#include <drm/drm_device.h>

#define SPX_DP0_PATH "/soc@0/display-subsystem@ae00000/displayport-controller@ae90000"

struct spx_usbc {
	struct device *dev;
	struct ssam_controller *ctrl;
	struct drm_bridge *bridge;
	struct ssam_event_notifier notifier;
	struct workqueue_struct *wq;
	bool connected;
};

struct spx_usbc_ack {
	__le32 sequence;
	__le32 port;
	__le32 handled;
} __packed;

struct spx_usbc_event {
	struct work_struct work;
	struct spx_usbc *usbc;
	struct spx_usbc_ack ack;
	u8 orientation;
	u8 type;
	u8 link;
	u8 connected;
};

static bool spx_usbc_hpd(struct spx_usbc *usbc, bool connected)
{
	struct drm_bridge *bridge = usbc->bridge;
	bool ready;
	int idx;

	if (!drm_bridge_enter(bridge, &idx))
		return false;

	/* Keep HPD enabled between checking the callback and notifying it. */
	mutex_lock(&bridge->hpd_state_mutex);
	mutex_lock(&bridge->hpd_mutex);
	ready = bridge->hpd_cb;
	mutex_unlock(&bridge->hpd_mutex);
	if (ready)
		drm_bridge_hpd_notify(bridge, connected ? connector_status_connected :
				      connector_status_disconnected);
	mutex_unlock(&bridge->hpd_state_mutex);
	drm_bridge_exit(idx);

	return ready;
}

static void spx_usbc_event_work(struct work_struct *work)
{
	struct spx_usbc_event *event = container_of(work, struct spx_usbc_event, work);
	struct spx_usbc *usbc = event->usbc;
	struct ssam_request request = {
		.target_category = SSAM_SSH_TC_USC,
		.target_id = 0x01,
		.command_id = 0x03,
		.instance_id = 0x01,
		.length = sizeof(event->ack),
		.payload = (u8 *)&event->ack,
	};
	bool notify = false;
	bool connected = false;
	int ret;

	/* Only USC port zero is known to route to the primary DP controller. */
	if (le32_to_cpu(event->ack.port) == 0) {
		if (event->type == 3) {
			notify = true;
			connected = event->connected == 1;
		} else if (event->type == 0 && event->orientation == 2 && usbc->connected) {
			notify = true;
		}
	}

	if (notify) {
		usbc->connected = connected;
		if (spx_usbc_hpd(usbc, connected)) {
			event->ack.handled = cpu_to_le32(1);
			dev_info(usbc->dev, "USC DP port 0 %s (orientation=%u, link=%u)\n",
				 connected ? "connected" : "disconnected",
				 event->orientation, event->link);
		} else {
			dev_warn_ratelimited(usbc->dev, "DP HPD unavailable; replug after display startup\n");
		}
	}

	/* Sequenced ACK without a response, including unhandled port events. */
	ret = ssam_request_do_sync(usbc->ctrl, &request, NULL);
	if (ret)
		dev_warn_ratelimited(usbc->dev, "USC ACK %u failed: %d\n",
				     le32_to_cpu(event->ack.sequence), ret);
	kfree(event);
}

static u32 spx_usbc_notify(struct ssam_event_notifier *nf,
			   const struct ssam_event *event)
{
	struct spx_usbc *usbc = container_of(nf, struct spx_usbc, notifier);
	struct spx_usbc_event *work;

	if (event->command_id != 0x02 || event->length < 11)
		return 0;

	work = kzalloc_obj(*work);
	if (!work)
		return ssam_notifier_from_errno(-ENOMEM);

	INIT_WORK(&work->work, spx_usbc_event_work);
	work->usbc = usbc;
	work->ack.sequence = cpu_to_le32(get_unaligned_le32(event->data));
	work->ack.port = cpu_to_le32(event->data[4]);
	work->orientation = event->data[5];
	work->type = event->data[6];
	work->link = event->data[8];
	work->connected = event->data[9];
	queue_work(usbc->wq, &work->work);

	return SSAM_NOTIF_HANDLED;
}

static int spx_usbc_link(struct device *consumer, struct device *supplier)
{
	struct device_link *link;
	int ret = -ENODEV;

	device_lock(supplier);
	if (device_is_bound(supplier)) {
		link = device_link_add(consumer, supplier, DL_FLAG_AUTOREMOVE_CONSUMER);
		ret = link ? 0 : -ENOMEM;
	}
	device_unlock(supplier);

	return ret;
}

static int spx_usbc_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct platform_device *dpdev;
	struct device_node *node;
	struct drm_bridge *bridge;
	struct spx_usbc *usbc;
	bool ready;
	int ret;

	usbc = devm_kzalloc(dev, sizeof(*usbc), GFP_KERNEL);
	if (!usbc)
		return -ENOMEM;
	usbc->dev = dev;
	usbc->ctrl = ssam_client_bind(dev);
	if (IS_ERR(usbc->ctrl))
		return dev_err_probe(dev, PTR_ERR(usbc->ctrl), "SSAM is not ready\n");

	node = of_find_node_by_path(SPX_DP0_PATH);
	if (!node)
		return -ENODEV;
	dpdev = of_find_device_by_node(node);
	bridge = of_drm_find_and_get_bridge(node);
	of_node_put(node);
	if (!dpdev || !bridge) {
		ret = -ENODEV;
		goto err_provider;
	}

	ret = spx_usbc_link(dev, &dpdev->dev);
	if (ret)
		goto err_provider;

	/* A registered bridge need not yet have an encoder or HPD callback. */
	if (!bridge->dev || !bridge->encoder || bridge->type != DRM_MODE_CONNECTOR_DisplayPort) {
		ret = -ENODEV;
		goto err_provider;
	}
	ret = spx_usbc_link(dev, bridge->dev->dev);
	if (ret)
		goto err_provider;
	mutex_lock(&bridge->hpd_mutex);
	ready = bridge->hpd_cb;
	mutex_unlock(&bridge->hpd_mutex);
	if (!ready) {
		ret = -ENODEV;
		goto err_provider;
	}
	put_device(&dpdev->dev);
	usbc->bridge = bridge;

	usbc->wq = alloc_ordered_workqueue("spx_usbc", WQ_MEM_RECLAIM | WQ_FREEZABLE);
	if (!usbc->wq) {
		ret = -ENOMEM;
		goto err_bridge;
	}
	usbc->notifier = (struct ssam_event_notifier) {
		.base = { .priority = 1, .fn = spx_usbc_notify },
		.event = {
			.reg = SSAM_EVENT_REGISTRY_SAM,
			.id = { .target_category = SSAM_SSH_TC_USC, .instance = 0 },
			.mask = SSAM_EVENT_MASK_STRICT,
			.flags = SSAM_EVENT_SEQUENCED,
		},
	};
	ret = ssam_notifier_register(usbc->ctrl, &usbc->notifier);
	if (ret)
		goto err_wq;

	platform_set_drvdata(pdev, usbc);
	dev_info(dev, "experimental DP0 forwarding ready; replug dock (orientation switching unimplemented)\n");
	return 0;

err_wq:
	destroy_workqueue(usbc->wq);
err_bridge:
	drm_bridge_put(bridge);
	return ret;
err_provider:
	if (dpdev)
		put_device(&dpdev->dev);
	drm_bridge_put(bridge);
	return dev_err_probe(dev, ret, "DP0 bridge unavailable; reload after desktop startup\n");
}

static void spx_usbc_remove(struct platform_device *pdev)
{
	struct spx_usbc *usbc = platform_get_drvdata(pdev);

	if (!usbc->wq)
		return;
	ssam_notifier_unregister(usbc->ctrl, &usbc->notifier);
	destroy_workqueue(usbc->wq);
	usbc->wq = NULL;
	drm_bridge_put(usbc->bridge);
}

static struct platform_driver spx_usbc_driver = {
	.remove = spx_usbc_remove,
	.shutdown = spx_usbc_remove,
	.driver.name = "surface_aggregator_usbc",
};

static struct platform_device *spx_usbc_device;

static int __init spx_usbc_init(void)
{
	if (!of_machine_is_compatible("microsoft,surface-pro-x"))
		return -ENODEV;

	/* Manual, one-shot probe: load only once MSM and SSAM are ready. */
	spx_usbc_device = platform_create_bundle(&spx_usbc_driver, spx_usbc_probe,
						 NULL, 0, NULL, 0);
	return PTR_ERR_OR_ZERO(spx_usbc_device);
}
module_init(spx_usbc_init);

static void __exit spx_usbc_exit(void)
{
	platform_device_unregister(spx_usbc_device);
	platform_driver_unregister(&spx_usbc_driver);
}
module_exit(spx_usbc_exit);

MODULE_DESCRIPTION("Experimental Surface Pro X USC-to-DP0 hotplug forwarding");
MODULE_LICENSE("GPL");
MODULE_SOFTDEP("pre: msm surface_aggregator");
