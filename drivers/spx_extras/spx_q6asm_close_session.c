// SPDX-License-Identifier: GPL-2.0
/* One-shot recovery helper for a stale SPX Q6ASM stream. */
#include <linux/device.h>
#include <linux/module.h>
#include <linux/platform_device.h>

#include "../../sound/soc/qcom/qdsp6/q6asm.h"

#define SPX_Q6ASM_DAI_NAME \
	"17300000.remoteproc:glink-edge:apr:service@7:dais"

static int session_id = 1;
module_param(session_id, int, 0444);
MODULE_PARM_DESC(session_id, "DSP ASM session to close (1-8)");

static int stream_id = 1;
module_param(stream_id, int, 0444);
MODULE_PARM_DESC(stream_id, "DSP ASM stream to close (normally 1)");

static int __init spx_q6asm_close_session_init(void)
{
	struct audio_client *client;
	struct device *dev;
	int ret;

	if (session_id < 1 || session_id > MAX_SESSIONS || stream_id < 1)
		return -EINVAL;

	dev = bus_find_device_by_name(&platform_bus_type, NULL,
				      SPX_Q6ASM_DAI_NAME);
	if (!dev)
		return -ENODEV;

	client = q6asm_audio_client_alloc(dev, NULL, NULL, session_id - 1,
					  LEGACY_PCM_MODE);
	if (IS_ERR(client)) {
		ret = PTR_ERR(client);
		goto out_put;
	}

	ret = q6asm_cmd(client, stream_id, CMD_CLOSE);
	pr_info("spx_q6asm_close: session=%d stream=%d rc=%d\n",
		session_id, stream_id, ret);
	q6asm_audio_client_free(client);

out_put:
	put_device(dev);
	return ret;
}

static void __exit spx_q6asm_close_session_exit(void)
{
}

module_init(spx_q6asm_close_session_init);
module_exit(spx_q6asm_close_session_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Close a stale Surface Pro X Q6ASM stream");
