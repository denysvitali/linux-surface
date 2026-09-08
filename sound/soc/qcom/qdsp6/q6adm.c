// SPDX-License-Identifier: GPL-2.0
// Copyright (c) 2011-2017, The Linux Foundation. All rights reserved.
// Copyright (c) 2018, Linaro Limited

#include <linux/device.h>
#include <linux/debugfs.h>
#include <linux/jiffies.h>
#include <linux/kernel.h>
#include <linux/kref.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>
#include <linux/sched.h>
#include <linux/slab.h>
#include <linux/soc/qcom/apr.h>
#include <linux/wait.h>
#include <sound/asound.h>
#include "q6adm.h"
#include "q6afe.h"
#include "q6core.h"
#include "q6dsp-common.h"
#include "q6dsp-errno.h"

#define ADM_CMD_DEVICE_OPEN_V5		0x00010326
#define ADM_CMDRSP_DEVICE_OPEN_V5	0x00010329
#define ADM_CMD_DEVICE_OPEN_V7		0x0001035b
#define ADM_CMDRSP_DEVICE_OPEN_V7	0x0001035c
#define ADM_CMD_DEVICE_OPEN_V8		0x0001036a	/* SPX: AR speaker topology */
#define ADM_CMD_DEVICE_CLOSE_V5		0x00010327
#define ADM_CMD_MATRIX_MAP_ROUTINGS_V5	0x00010325
/* SPX: per-COPP post-proc param set/get (the path the Windows driver uses to
 * apply the dev-0x45 speaker subgraph cal, opcode 0x1035d = SET_PP_PARAMS_V6). */
#define ADM_CMD_SET_PP_PARAMS_V6	0x0001035d
#define ADM_CMD_GET_PP_PARAMS_V5	0x0001032a
#define ADM_CMDRSP_GET_PP_PARAMS_V5	0x0001032b
#define ADM_GET_PARAM_MAX		256
#define SPX_V7_SPEAKER_TOPOLOGY		0x10000008

#define TIMEOUT_MS 1000
#define RESET_COPP_ID 99
#define INVALID_COPP_ID 0xFF
/* Definition for a legacy device session. */
#define ADM_LEGACY_DEVICE_SESSION	0
#define ADM_MATRIX_ID_AUDIO_RX		0
#define ADM_MATRIX_ID_AUDIO_TX		1

/* qcadcm maps its stream flags to the V7 wire flags (0x2000/0x4000/0x6000).
 * Keep this runtime-selectable while matching the Windows request exactly. */
static uint spx_v7_flags;
module_param(spx_v7_flags, uint, 0644);
MODULE_PARM_DESC(spx_v7_flags, "SPX: ADM_DEVICE_OPEN_V7 flags override");

/* qcadcm resolves this from the selected AFE port before building V7. */
static int spx_v7_endpoint = -1;
module_param(spx_v7_endpoint, int, 0644);
MODULE_PARM_DESC(spx_v7_endpoint,
		 "SPX: ADM_DEVICE_OPEN_V7 endpoint 1 override (-1: AFE port map)");

/* Keep the Windows-style matrix route fields live-tunable.  The Windows
 * driver derives these values from its stream/COPP objects, so exposing them
 * lets us validate that translation without another kernel rebuild/reboot. */
static int spx_v7_matrix_id = -1;
module_param(spx_v7_matrix_id, int, 0644);
MODULE_PARM_DESC(spx_v7_matrix_id, "SPX: V7 matrix id override (-1: normal)");

static int spx_v7_session_id = -1;
module_param(spx_v7_session_id, int, 0644);
MODULE_PARM_DESC(spx_v7_session_id, "SPX: V7 matrix session id override (-1: normal)");

static int spx_v7_copp_id = -1;
module_param(spx_v7_copp_id, int, 0644);
MODULE_PARM_DESC(spx_v7_copp_id, "SPX: V7 matrix COPP id override (-1: open response)");

static int spx_v7_matrix_token = -1;
module_param(spx_v7_matrix_token, int, 0644);
MODULE_PARM_DESC(spx_v7_matrix_token, "SPX: V7 matrix APR token override (-1: zero)");

static int spx_v7_matrix_src_svc = -1;
module_param(spx_v7_matrix_src_svc, int, 0644);
MODULE_PARM_DESC(spx_v7_matrix_src_svc, "SPX: V7 matrix APR source service override");

static int spx_v7_matrix_src_port = -1;
module_param(spx_v7_matrix_src_port, int, 0644);
MODULE_PARM_DESC(spx_v7_matrix_src_port, "SPX: V7 matrix APR source port override");

static int spx_v7_matrix_dest_port = -1;
module_param(spx_v7_matrix_dest_port, int, 0644);
MODULE_PARM_DESC(spx_v7_matrix_dest_port, "SPX: V7 matrix APR destination port override");

struct q6copp {
	int afe_port;
	int copp_idx;
	int id;
	int topology;
	int mode;
	int rate;
	int bit_width;
	int channels;
	int app_type;
	int acdb_id;

	struct aprv2_ibasic_rsp_result_t result;
	struct kref refcount;
	wait_queue_head_t wait;
	struct list_head node;
	struct q6adm *adm;
	/* SPX GET_PP_PARAMS read-back staging */
	u32 get_param_status;
	int get_param_len;
	u32 get_param[ADM_GET_PARAM_MAX / 4];
};

struct q6adm {
	struct apr_device *apr;
	struct device *dev;
	struct q6core_svc_api_info ainfo;
	unsigned long copp_bitmap[AFE_MAX_PORTS];
	struct list_head copps_list;
	spinlock_t copps_list_lock;
	struct aprv2_ibasic_rsp_result_t result;
	struct mutex lock;
	wait_queue_head_t matrix_map_wait;
#ifdef CONFIG_DEBUG_FS
	/* SPX speaker ADM SET/GET_PP_PARAMS probe */
	struct dentry *dbg_dir;
	struct mutex dbg_lock;
	void *dbg_payload;
	size_t dbg_payload_len;
	u32 dbg_module_id;
	u32 dbg_param_id;
	u32 dbg_port_index;
	u32 dbg_copp_index;
	u32 dbg_phdr_ver;	/* 5 or 6: param-header layout to send */
	u32 dbg_v8_topology;	/* 0x10000001 = dev-0x45 AR spkr COPP topology */
	u32 dbg_v8_channels;	/* 2 for 2ch speaker */
	u32 dbg_v8_bit_width;	/* 24 for 24-bit */
	u32 dbg_v8_sample_rate;	/* 48000 */
#endif
};

struct adm_cmd_set_pp_params {
	u32 payload_addr_lsw;
	u32 payload_addr_msw;
	u32 mem_map_handle;
	u32 payload_size;
} __packed;

struct adm_param_data_v5 {
	u32 module_id;
	u32 param_id;
	u16 param_size;
	u16 reserved;
} __packed;

/* SET_PP_PARAMS_V6 (0x1035d) uses the larger instance-based param header. */
struct adm_param_data_v6 {
	u32 module_id;
	u16 instance_id;
	u16 reserved;
	u32 param_id;
	u32 param_size;
} __packed;

struct adm_cmd_get_pp_params {
	u32 data_payload_addr_lsw;
	u32 data_payload_addr_msw;
	u32 mem_map_handle;
	u32 module_id;
	u32 param_id;
	u16 param_max_size;
	u16 reserved;
} __packed;

struct q6adm_cmd_device_open_v5 {
	u16 flags;
	u16 mode_of_operation;
	u16 endpoint_id_1;
	u16 endpoint_id_2;
	u32 topology_id;
	u16 dev_num_channel;
	u16 bit_width;
	u32 sample_rate;
	u8 dev_channel_mapping[8];
} __packed;

struct q6adm_cmd_device_open_v7 {
	u16 flags;
	u16 mode_of_operation;
	u16 endpoint_id_1;
	u16 endpoint_id_2;
	u32 topology_id;
	u16 dev_num_channel;
	u16 bit_width;
	u32 sample_rate;
	u8 dev_channel_mapping[44];
} __packed;

/* SPX: ADM_DEVICE_OPEN_V8 (0x1036a) - V5 with the dev_num_channel/bit_width/
 * sample_rate/dev_channel_mapping moved to a TRAILING per-endpoint payload, and
 * the topology_id moved to offset 0x04 (before endpoint ids). The fixed body is
 * 16 bytes; each active endpoint appends an adm_endpoint_payload{16B hdr + map}.
 * For 2ch/48k/24bit the trailing ep payload is 8 + roundup(2,4)=12B, so the
 * total packet is 20B (apr_hdr) + 16B (v8 body) + 12B (ep1) = 48 bytes.
 * V8 is required for the dev-0x45 AudioReach speaker topology 0x10000001,
 * which V5 rejects with ADSP_EUNSUPPORTED(3).
 */
struct q6adm_cmd_device_open_v8 {
	u16 flags;
	u16 mode_of_operation;
	u32 topology_id;
	u16 endpoint_id_1;
	u16 endpoint_id_2;
	u16 endpoint_id_3;
	u16 compressed_data_type;
} __packed;

struct q6adm_endpoint_payload {
	u16 dev_num_channel;
	u16 bit_width;
	u32 sample_rate;
	/* dev_channel_mapping[roundup(dev_num_channel, 4)]; 4 bytes for 2ch */
} __packed;

struct q6adm_cmd_matrix_map_routings_v5 {
	u32 matrix_id;
	u32 num_sessions;
} __packed;

struct q6adm_session_map_node_v5 {
	u16 session_id;
	u16 num_copps;
} __packed;

static struct q6copp *q6adm_find_copp(struct q6adm *adm, int port_idx,
				  int copp_idx)
{
	struct q6copp *c;
	struct q6copp *ret = NULL;
	unsigned long flags;

	spin_lock_irqsave(&adm->copps_list_lock, flags);
	list_for_each_entry(c, &adm->copps_list, node) {
		if ((port_idx == c->afe_port) && (copp_idx == c->copp_idx)) {
			ret = c;
			kref_get(&c->refcount);
			break;
		}
	}

	spin_unlock_irqrestore(&adm->copps_list_lock, flags);

	return ret;

}

static int q6adm_apr_send_copp_pkt(struct q6adm *adm, struct q6copp *copp,
				   struct apr_pkt *pkt, uint32_t rsp_opcode)
{
	struct device *dev = adm->dev;
	uint32_t opcode = pkt->hdr.opcode;
	int ret;

	mutex_lock(&adm->lock);
	copp->result.opcode = 0;
	copp->result.status = 0;
	ret = apr_send_pkt(adm->apr, pkt);
	if (ret < 0) {
		dev_err(dev, "Failed to send APR packet\n");
		ret = -EINVAL;
		goto err;
	}

	/* Wait for the callback with copp id */
	if (rsp_opcode)
		ret = wait_event_timeout(copp->wait,
					 (copp->result.opcode == opcode) ||
					 (copp->result.opcode == rsp_opcode),
					 msecs_to_jiffies(TIMEOUT_MS));
	else
		ret = wait_event_timeout(copp->wait,
					 (copp->result.opcode == opcode),
					 msecs_to_jiffies(TIMEOUT_MS));

	if (!ret) {
		dev_err(dev, "ADM copp cmd timedout\n");
		ret = -ETIMEDOUT;
	} else if (copp->result.status > 0) {
		dev_err(dev, "DSP returned error[%d]\n",
			copp->result.status);
		ret = -EINVAL;
	}

err:
	mutex_unlock(&adm->lock);
	return ret;
}

static int q6adm_device_close(struct q6adm *adm, struct q6copp *copp,
			      int port_id, int copp_idx)
{
	struct apr_pkt close;

	close.hdr.hdr_field = APR_HDR_FIELD(APR_MSG_TYPE_SEQ_CMD,
					APR_HDR_LEN(APR_HDR_SIZE),
					APR_PKT_VER);
	close.hdr.pkt_size = sizeof(close);
	close.hdr.src_port = port_id;
	close.hdr.dest_port = copp->id;
	close.hdr.token = port_id << 16 | copp_idx;
	close.hdr.opcode = ADM_CMD_DEVICE_CLOSE_V5;

	return q6adm_apr_send_copp_pkt(adm, copp, &close, 0);
}

static void q6adm_free_copp(struct kref *ref)
{
	struct q6copp *c = container_of(ref, struct q6copp, refcount);
	struct q6adm *adm = c->adm;
	unsigned long flags;
	int ret;

	ret = q6adm_device_close(adm, c, c->afe_port, c->copp_idx);
	if (ret < 0)
		dev_err(adm->dev, "Failed to close copp %d\n", ret);

	spin_lock_irqsave(&adm->copps_list_lock, flags);
	clear_bit(c->copp_idx, &adm->copp_bitmap[c->afe_port]);
	list_del(&c->node);
	spin_unlock_irqrestore(&adm->copps_list_lock, flags);
	kfree(c);
}

static int q6adm_callback(struct apr_device *adev, const struct apr_resp_pkt *data)
{
	const struct aprv2_ibasic_rsp_result_t *result = data->payload;
	int port_idx, copp_idx;
	const struct apr_hdr *hdr = &data->hdr;
	struct q6copp *copp;
	struct q6adm *adm = dev_get_drvdata(&adev->dev);

	if (!data->payload_size)
		return 0;

	copp_idx = (hdr->token) & 0XFF;
	port_idx = ((hdr->token) >> 16) & 0xFF;
	if (port_idx < 0 || port_idx >= AFE_MAX_PORTS) {
		dev_err(&adev->dev, "Invalid port idx %d token %d\n",
		       port_idx, hdr->token);
		return 0;
	}
	if (copp_idx < 0 || copp_idx >= MAX_COPPS_PER_PORT) {
		dev_err(&adev->dev, "Invalid copp idx %d token %d\n",
			copp_idx, hdr->token);
		return 0;
	}

	switch (hdr->opcode) {
	case APR_BASIC_RSP_RESULT: {
		if (result->status != 0) {
			dev_err(&adev->dev, "cmd = 0x%x return error = 0x%x\n",
				result->opcode, result->status);
		}
		switch (result->opcode) {
		case ADM_CMD_DEVICE_OPEN_V5:
		case ADM_CMD_DEVICE_OPEN_V7:
		case ADM_CMD_DEVICE_CLOSE_V5:
		case ADM_CMD_SET_PP_PARAMS_V6:
		case ADM_CMD_GET_PP_PARAMS_V5:
			list_for_each_entry(copp, &adm->copps_list, node) {
				if ((port_idx == copp->afe_port) && (copp_idx == copp->copp_idx)) {
					copp->result = *result;
					wake_up(&copp->wait);
					break;
				}
			}
			break;
		case ADM_CMD_MATRIX_MAP_ROUTINGS_V5:
			adm->result = *result;
			wake_up(&adm->matrix_map_wait);
			break;

		default:
			dev_err(&adev->dev, "Unknown Cmd: 0x%x\n",
				result->opcode);
			break;
		}
		return 0;
	}
	case ADM_CMDRSP_DEVICE_OPEN_V5:
	case ADM_CMDRSP_DEVICE_OPEN_V7: {
		struct adm_cmd_rsp_device_open_v5 {
			u32 status;
			u16 copp_id;
			u16 reserved;
		} __packed *open = data->payload;

		copp = q6adm_find_copp(adm, port_idx, copp_idx);
		if (!copp)
			return 0;

		if (open->copp_id == INVALID_COPP_ID) {
			dev_err(&adev->dev, "Invalid coppid rxed %d\n",
				open->copp_id);
			copp->result.status = ADSP_EBADPARAM;
			wake_up(&copp->wait);
			kref_put(&copp->refcount, q6adm_free_copp);
			break;
		}
		copp->result.opcode = hdr->opcode;
		copp->id = open->copp_id;
		if (hdr->opcode == ADM_CMDRSP_DEVICE_OPEN_V7)
			dev_info(&adev->dev,
				 "SPX V7 open response: status=0x%x copp_id=0x%x\n",
				 open->status, open->copp_id);
		wake_up(&copp->wait);
		kref_put(&copp->refcount, q6adm_free_copp);
	}
	break;
	case 0x1036D:		/* SPX: ADM_CMDRSP_DEVICE_OPEN_V8 */
	{
		/* V8 response payload mirrors V5: u32 status; u16 copp_id; u16 reserved */
		struct adm_cmd_rsp_device_open_v5 {
			u32 status;
			u16 copp_id;
			u16 reserved;
		} __packed *open = data->payload;

		copp = q6adm_find_copp(adm, port_idx, copp_idx);
		if (!copp)
			return 0;
		dev_info(&adev->dev, "ADM V8 open resp: copp_id=%d status=0x%x\n",
			 open->copp_id, open->status);
		if (open->copp_id == INVALID_COPP_ID) {
			copp->result.status = ADSP_EBADPARAM;
			wake_up(&copp->wait);
			kref_put(&copp->refcount, q6adm_free_copp);
			break;
		}
		copp->result.opcode = hdr->opcode;
		copp->id = open->copp_id;
		wake_up(&copp->wait);
		kref_put(&copp->refcount, q6adm_free_copp);
	}
	break;
	case ADM_CMDRSP_GET_PP_PARAMS_V5: {
		struct adm_cmd_rsp_get_pp_params {
			u32 status;
			struct adm_param_data_v5 pdata;
		} __packed *g = data->payload;
		int avail = (int)data->payload_size - (int)sizeof(*g);

		copp = q6adm_find_copp(adm, port_idx, copp_idx);
		if (!copp)
			return 0;

		copp->get_param_status = g->status;
		copp->get_param_len = min_t(int, g->pdata.param_size,
					    ADM_GET_PARAM_MAX);
		if (copp->get_param_len > avail)
			copp->get_param_len = avail;
		if (copp->get_param_len < 0)
			copp->get_param_len = 0;
		memcpy(copp->get_param, (u8 *)data->payload + sizeof(*g),
		       copp->get_param_len);
		copp->result.opcode = hdr->opcode;
		wake_up(&copp->wait);
		kref_put(&copp->refcount, q6adm_free_copp);
	}
	break;
	default:
		dev_err(&adev->dev, "Unknown cmd:0x%x\n",
		       hdr->opcode);
		break;
	}

	return 0;
}

static struct q6copp *q6adm_alloc_copp(struct q6adm *adm, int port_idx)
{
	struct q6copp *c;
	int idx;

	idx = find_first_zero_bit(&adm->copp_bitmap[port_idx],
				  MAX_COPPS_PER_PORT);

	if (idx >= MAX_COPPS_PER_PORT)
		return ERR_PTR(-EBUSY);

	c = kzalloc_obj(*c, GFP_ATOMIC);
	if (!c)
		return ERR_PTR(-ENOMEM);

	set_bit(idx, &adm->copp_bitmap[port_idx]);
	c->copp_idx = idx;
	c->afe_port = port_idx;
	c->adm = adm;

	init_waitqueue_head(&c->wait);

	return c;
}

static struct q6copp *q6adm_find_matching_copp(struct q6adm *adm,
					       int port_id, int topology,
					       int mode, int rate,
					       int channel_mode, int bit_width,
					       int app_type)
{
	struct q6copp *c;
	struct q6copp *ret = NULL;
	unsigned long flags;

	spin_lock_irqsave(&adm->copps_list_lock, flags);

	list_for_each_entry(c, &adm->copps_list, node) {
		if ((port_id == c->afe_port) && (topology == c->topology) &&
		    (mode == c->mode) && (rate == c->rate) &&
		    (bit_width == c->bit_width) && (app_type == c->app_type)) {
			ret = c;
			kref_get(&c->refcount);
		}
	}
	spin_unlock_irqrestore(&adm->copps_list_lock, flags);

	return ret;
}

static int q6adm_device_open(struct q6adm *adm, struct q6copp *copp,
			     int port_id, int path, int topology,
			     int channel_mode, int bit_width, int rate)
{
	struct q6adm_cmd_device_open_v5 *open;
	int afe_port = q6afe_get_port_id(port_id);
	struct apr_pkt *pkt;
	int ret, pkt_size = APR_HDR_SIZE + sizeof(*open);

	void *p __free(kfree) = kzalloc(pkt_size, GFP_KERNEL);
	if (!p)
		return -ENOMEM;

	pkt = p;
	open = p + APR_HDR_SIZE;
	pkt->hdr.hdr_field = APR_HDR_FIELD(APR_MSG_TYPE_SEQ_CMD,
					   APR_HDR_LEN(APR_HDR_SIZE),
					   APR_PKT_VER);
	pkt->hdr.pkt_size = pkt_size;
	pkt->hdr.src_port = afe_port;
	pkt->hdr.dest_port = afe_port;
	pkt->hdr.token = port_id << 16 | copp->copp_idx;
	pkt->hdr.opcode = ADM_CMD_DEVICE_OPEN_V5;
	open->flags = ADM_LEGACY_DEVICE_SESSION;
	open->mode_of_operation = path;
	open->endpoint_id_1 = afe_port;
	open->topology_id = topology;
	open->dev_num_channel = channel_mode & 0x00FF;
	open->bit_width = bit_width;
	open->sample_rate = rate;

	ret = q6dsp_map_channels(&open->dev_channel_mapping[0],
				 channel_mode);
	if (ret)
		return ret;

	return q6adm_apr_send_copp_pkt(adm, copp, pkt, ADM_CMDRSP_DEVICE_OPEN_V5);
}

static int q6adm_device_open_v7(struct q6adm *adm, struct q6copp *copp,
				int port_id, int path, int topology,
				int channel_mode, int bit_width, int rate)
{
	struct q6adm_cmd_device_open_v7 *open;
	struct apr_pkt *pkt;
	int endpoint, ret, pkt_size = APR_HDR_SIZE + sizeof(*open);

	pkt = kzalloc(pkt_size, GFP_KERNEL);
	if (!pkt)
		return -ENOMEM;
	open = (void *)pkt + APR_HDR_SIZE;

	pkt->hdr.hdr_field = APR_HDR_FIELD(APR_MSG_TYPE_SEQ_CMD,
					   APR_HDR_LEN(APR_HDR_SIZE), APR_PKT_VER);
	pkt->hdr.pkt_size = pkt_size;
	pkt->hdr.src_svc = 5; /* Windows qcadcm client identity */
	/* qcadcm uses its client port (1); the AFE port is in endpoint_id_1. */
	pkt->hdr.src_port = 1;
	pkt->hdr.dest_port = 1;
	pkt->hdr.token = port_id << 16 | copp->copp_idx;
	pkt->hdr.opcode = ADM_CMD_DEVICE_OPEN_V7;

	open->flags = spx_v7_flags;
	open->mode_of_operation = path;
	endpoint = spx_v7_endpoint >= 0 ? spx_v7_endpoint :
		q6afe_get_port_id(port_id);
	if (endpoint < 0) {
		dev_err(adm->dev, "SPX V7: invalid endpoint for AFE port %d: %d\n",
			port_id, endpoint);
		ret = endpoint;
		goto out;
	}
	/* qcadcm resolves endpoint 1 from its AFE port map (0x4004 here). */
	open->endpoint_id_1 = endpoint;
	open->endpoint_id_2 = 0xffff;
	open->topology_id = topology;
	open->dev_num_channel = channel_mode & 0xff;
	open->bit_width = bit_width;
	open->sample_rate = rate;

	ret = q6dsp_map_channels(open->dev_channel_mapping, channel_mode);
	if (ret < 0)
		goto out;

	dev_info(adm->dev,
		 "SPX V7 open: flags=0x%x mode=%u ep1=0x%x ep2=0x%x topo=0x%x ch=%u bits=%u rate=%u\n",
		 open->flags, open->mode_of_operation, open->endpoint_id_1,
		 open->endpoint_id_2, open->topology_id, open->dev_num_channel,
		 open->bit_width, open->sample_rate);

	ret = q6adm_apr_send_copp_pkt(adm, copp, pkt,
					  ADM_CMDRSP_DEVICE_OPEN_V7);
out:
	kfree(pkt);
	return ret;
}

/* SPX: V8 device-open. The fixed body is 16B; the trailing per-endpoint
 * payload adds dev_num_channel/bit_width/sample_rate/dev_channel_mapping
 * (4-byte-padded). For 2ch/48k/24bit the total packet is 48B. The response
 * opcode on this fw is the V8 open response; we wait for the V5 response
 * token and the DSP will error if the V8 is rejected.
 */
static int q6adm_device_open_v8(struct q6adm *adm, struct q6copp *copp,
				int port_id, int path, int topology,
				int channel_mode, int bit_width, int rate)
{
	struct q6adm_cmd_device_open_v8 *open;
	struct q6adm_endpoint_payload *ep;
	int afe_port = q6afe_get_port_id(port_id);
	u8 map[8] = {0};
	int ret, pkt_size, ep_size, map_size;
	struct apr_pkt *pkt;
	void *p;

	ret = q6dsp_map_channels(map, channel_mode);
	if (ret < 0)
		return ret;

	map_size = roundup(ret, 4);	/* ret = number of channels */
	ep_size  = sizeof(*ep) + map_size;
	pkt_size = APR_HDR_SIZE + sizeof(*open) + ep_size;
	p = kzalloc(pkt_size, GFP_KERNEL);
	if (!p)
		return -ENOMEM;

	pkt = p;
	open = p + APR_HDR_SIZE;
	ep   = p + APR_HDR_SIZE + sizeof(*open);

	pkt->hdr.hdr_field = APR_HDR_FIELD(APR_MSG_TYPE_SEQ_CMD,
					   APR_HDR_LEN(APR_HDR_SIZE), APR_PKT_VER);
	pkt->hdr.pkt_size = pkt_size;
	pkt->hdr.src_port = afe_port;
	pkt->hdr.dest_port = afe_port;
	pkt->hdr.token = port_id << 16 | copp->copp_idx;
	pkt->hdr.opcode = ADM_CMD_DEVICE_OPEN_V8;
	open->flags = ADM_LEGACY_DEVICE_SESSION;
	open->mode_of_operation = path;
	open->topology_id = topology;
	open->endpoint_id_1 = afe_port;
	open->endpoint_id_2 = 0xFFFF;
	open->endpoint_id_3 = 0xFFFF;
	open->compressed_data_type = 0;

	ep->dev_num_channel = channel_mode & 0x00FF;
	ep->bit_width = bit_width;
	ep->sample_rate = rate;
	memcpy(p + APR_HDR_SIZE + sizeof(*open) + sizeof(*ep), map, map_size);

	ret = q6adm_apr_send_copp_pkt(adm, copp, pkt,
				      ADM_CMDRSP_DEVICE_OPEN_V5);
	kfree(pkt);
	return ret;
}

/**
 * q6adm_open() - open adm and grab a free copp
 *
 * @dev: Pointer to adm child device.
 * @port_id: port id
 * @path: playback or capture path.
 * @rate: rate at which copp is required.
 * @channel_mode: channel mode
 * @topology: adm topology id
 * @perf_mode: performace mode.
 * @bit_width: audio sample bit width
 * @app_type: Application type.
 * @acdb_id: ACDB id
 *
 * Return: Will be an negative on error or a valid copp pointer on success.
 */
struct q6copp *q6adm_open(struct device *dev, int port_id, int path, int rate,
	       int channel_mode, int topology, int perf_mode,
	       uint16_t bit_width, int app_type, int acdb_id)
{
	struct q6adm *adm = dev_get_drvdata(dev->parent);
	struct q6copp *copp;
	unsigned long flags;
	int ret = 0;

	if (port_id < 0) {
		dev_err(dev, "Invalid port_id %d\n", port_id);
		return ERR_PTR(-EINVAL);
	}

	copp = q6adm_find_matching_copp(adm, port_id, topology, perf_mode,
				      rate, channel_mode, bit_width, app_type);
	if (copp) {
		dev_err(dev, "Found Matching Copp 0x%x\n", copp->copp_idx);
		return copp;
	}

	spin_lock_irqsave(&adm->copps_list_lock, flags);
	copp = q6adm_alloc_copp(adm, port_id);
	if (IS_ERR(copp)) {
		spin_unlock_irqrestore(&adm->copps_list_lock, flags);
		return ERR_CAST(copp);
	}

	list_add_tail(&copp->node, &adm->copps_list);
	spin_unlock_irqrestore(&adm->copps_list_lock, flags);

	kref_init(&copp->refcount);
	copp->topology = topology;
	copp->mode = perf_mode;
	copp->rate = rate;
	copp->channels = channel_mode;
	copp->bit_width = bit_width;
	copp->app_type = app_type;

	if (topology == SPX_V7_SPEAKER_TOPOLOGY) {
		/* qcadcm initializes AVCS before opening the Surface speaker COPP. */
		ret = q6core_spx_audio_init();
		if (ret < 0)
			goto err;
		ret = q6adm_device_open_v7(adm, copp, port_id, path, topology,
					    channel_mode, bit_width, rate);
	} else {
		ret = q6adm_device_open(adm, copp, port_id, path, topology,
				channel_mode, bit_width, rate);
	}
	if (ret < 0) {
	err:
		kref_put(&copp->refcount, q6adm_free_copp);
		return ERR_PTR(ret);
	}

	return copp;
}
EXPORT_SYMBOL_GPL(q6adm_open);

/**
 * q6adm_get_copp_id() - get copp index
 *
 * @copp: Pointer to valid copp
 *
 * Return: Will be an negative on error or a valid copp index on success.
 **/
int q6adm_get_copp_id(struct q6copp *copp)
{
	if (!copp)
		return -EINVAL;

	return copp->copp_idx;
}
EXPORT_SYMBOL_GPL(q6adm_get_copp_id);

/**
 * q6adm_matrix_map() - Map asm streams and afe ports using payload
 *
 * @dev: Pointer to adm child device.
 * @path: playback or capture path.
 * @payload_map: map between session id and afe ports.
 * @perf_mode: Performace mode.
 *
 * Return: Will be an negative on error or a zero on success.
 */
int q6adm_matrix_map(struct device *dev, int path,
		     struct route_payload payload_map, int perf_mode)
{
	struct q6adm *adm = dev_get_drvdata(dev->parent);
	struct q6adm_cmd_matrix_map_routings_v5 *route;
	struct q6adm_session_map_node_v5 *node;
	struct apr_pkt *pkt;
	uint16_t *copps_list;
	int ret, i, copp_idx;
	bool spx_v7 = false;

	/* Assumes port_ids have already been validated during adm_open */
	struct q6copp *copp;
	int pkt_size = (APR_HDR_SIZE + sizeof(*route) +  sizeof(*node) +
		    (sizeof(uint32_t) * payload_map.num_copps));

	void *matrix_map __free(kfree) = kzalloc(pkt_size, GFP_KERNEL);
	if (!matrix_map)
		return -ENOMEM;

	pkt = matrix_map;
	route = matrix_map + APR_HDR_SIZE;
	node = matrix_map + APR_HDR_SIZE + sizeof(*route);
	copps_list = matrix_map + APR_HDR_SIZE + sizeof(*route) + sizeof(*node);

	pkt->hdr.hdr_field = APR_HDR_FIELD(APR_MSG_TYPE_SEQ_CMD,
					   APR_HDR_LEN(APR_HDR_SIZE),
					   APR_PKT_VER);
	pkt->hdr.pkt_size = pkt_size;
	pkt->hdr.token = 0;
	pkt->hdr.opcode = ADM_CMD_MATRIX_MAP_ROUTINGS_V5;
	route->num_sessions = 1;

	switch (path) {
	case ADM_PATH_PLAYBACK:
		route->matrix_id = ADM_MATRIX_ID_AUDIO_RX;
		break;
	case ADM_PATH_LIVE_REC:
		route->matrix_id = ADM_MATRIX_ID_AUDIO_TX;
		break;
	default:
		dev_err(dev, "Wrong path set[%d]\n", path);
		break;
	}

	node->session_id = payload_map.session_id;
	node->num_copps = payload_map.num_copps;

	for (i = 0; i < payload_map.num_copps; i++) {
		int port_idx = payload_map.port_id[i];

		if (port_idx < 0) {
			dev_err(dev, "Invalid port_id %d\n",
				payload_map.port_id[i]);
			return -EINVAL;
		}
		copp_idx = payload_map.copp_idx[i];

		copp = q6adm_find_copp(adm, port_idx, copp_idx);
		if (!copp)
			return -EINVAL;

		if (copp->topology == SPX_V7_SPEAKER_TOPOLOGY)
			spx_v7 = true;
		copps_list[i] = copp->id;
		kref_put(&copp->refcount, q6adm_free_copp);
	}

	/* Keep the matrix command on the APR identity registered by q6adm.  Unlike
	 * DEVICE_OPEN_V7, rewriting this packet to the Windows client service (5)
	 * makes the firmware reject an otherwise valid V5 matrix payload with
	 * ADSP_EBADPARAM. */
	if (spx_v7) {
		if (spx_v7_matrix_src_svc >= 0)
			pkt->hdr.src_svc = spx_v7_matrix_src_svc;
		if (spx_v7_matrix_src_port >= 0)
			pkt->hdr.src_port = spx_v7_matrix_src_port;
		if (spx_v7_matrix_dest_port >= 0)
			pkt->hdr.dest_port = spx_v7_matrix_dest_port;
		if (spx_v7_matrix_id >= 0)
			route->matrix_id = spx_v7_matrix_id;
		if (spx_v7_session_id >= 0)
			node->session_id = spx_v7_session_id;
		if (spx_v7_copp_id >= 0)
			copps_list[0] = spx_v7_copp_id;
		if (spx_v7_matrix_token >= 0)
			pkt->hdr.token = spx_v7_matrix_token;
		dev_info(dev,
			 "SPX V7 matrix map: hdr=%#x size=%u src=%u/%u:%u dst=%u/%u:%u token=%#x matrix=%u sessions=%u session=%u copps=%u first_copp=%#x\n",
			 pkt->hdr.hdr_field, pkt->hdr.pkt_size,
			 pkt->hdr.src_svc, APR_DOMAIN_APPS, pkt->hdr.src_port,
			 adm->apr->svc.id, adm->apr->domain_id, pkt->hdr.dest_port,
			 pkt->hdr.token, route->matrix_id, route->num_sessions,
			 node->session_id, node->num_copps, copps_list[0]);
	}

	mutex_lock(&adm->lock);
	adm->result.status = 0;
	adm->result.opcode = 0;

	ret = apr_send_pkt(adm->apr, pkt);
	if (ret < 0) {
		dev_err(dev, "routing for stream %d failed ret %d\n",
		       payload_map.session_id, ret);
		goto fail_cmd;
	}
	ret = wait_event_timeout(adm->matrix_map_wait,
				 adm->result.opcode == pkt->hdr.opcode,
				 msecs_to_jiffies(TIMEOUT_MS));
	if (!ret) {
		dev_err(dev, "routing for stream %d failed\n",
		       payload_map.session_id);
		ret = -ETIMEDOUT;
		goto fail_cmd;
	} else if (adm->result.status > 0) {
		dev_err(dev, "DSP returned error[%d]\n",
			adm->result.status);
		ret = -EINVAL;
		goto fail_cmd;
	}

fail_cmd:
	mutex_unlock(&adm->lock);
	return ret;
}
EXPORT_SYMBOL_GPL(q6adm_matrix_map);

/**
 * q6adm_close() - Close adm copp
 *
 * @dev: Pointer to adm child device.
 * @copp: pointer to previously opened copp
 *
 * Return: Will be an negative on error or a zero on success.
 */
int q6adm_close(struct device *dev, struct q6copp *copp)
{
	kref_put(&copp->refcount, q6adm_free_copp);

	return 0;
}
EXPORT_SYMBOL_GPL(q6adm_close);

/*
 * SPX: send ADM_CMD_SET_PP_PARAMS_V6 (0x1035d) to a live COPP - the path the
 * Windows driver uses to apply the dev-0x45 speaker subgraph cal/modules. In-band
 * payload (no shared mem). Returns 0 on a completed round-trip.
 */
static int q6adm_set_pp_params(struct q6adm *adm, struct q6copp *copp,
			       u32 module_id, u32 param_id,
			       const void *data, u16 psize, int ver)
{
	struct adm_cmd_set_pp_params *param;
	struct apr_pkt *pkt;
	int ret, pkt_size, phdr_size;
	void *p, *pl, *pd;

	phdr_size = (ver >= 6) ? sizeof(struct adm_param_data_v6)
			       : sizeof(struct adm_param_data_v5);
	pkt_size = APR_HDR_SIZE + sizeof(*param) + phdr_size + psize;
	p = kzalloc(pkt_size, GFP_KERNEL);
	if (!p)
		return -ENOMEM;

	pkt = p;
	param = p + APR_HDR_SIZE;
	pd = p + APR_HDR_SIZE + sizeof(*param);
	pl = pd + phdr_size;
	memcpy(pl, data, psize);

	pkt->hdr.hdr_field = APR_HDR_FIELD(APR_MSG_TYPE_SEQ_CMD,
					   APR_HDR_LEN(APR_HDR_SIZE), APR_PKT_VER);
	pkt->hdr.pkt_size = pkt_size;
	pkt->hdr.src_port = copp->afe_port;
	pkt->hdr.dest_port = copp->id;
	pkt->hdr.token = copp->afe_port << 16 | copp->copp_idx;
	pkt->hdr.opcode = ADM_CMD_SET_PP_PARAMS_V6;

	param->payload_size = phdr_size + psize;
	if (ver >= 6) {
		struct adm_param_data_v6 *d = pd;

		d->module_id = module_id;
		d->instance_id = 0;
		d->param_id = param_id;
		d->param_size = psize;
	} else {
		struct adm_param_data_v5 *d = pd;

		d->module_id = module_id;
		d->param_id = param_id;
		d->param_size = psize;
	}

	ret = q6adm_apr_send_copp_pkt(adm, copp, pkt, 0);
	kfree(pkt);
	return ret;
}

static int q6adm_get_pp_params(struct q6adm *adm, struct q6copp *copp,
			       u32 module_id, u32 param_id, u16 max_size)
{
	struct adm_cmd_get_pp_params *get;
	struct apr_pkt *pkt;
	int ret, pkt_size;
	void *p;

	if (max_size > ADM_GET_PARAM_MAX)
		max_size = ADM_GET_PARAM_MAX;

	pkt_size = APR_HDR_SIZE + sizeof(*get);
	p = kzalloc(pkt_size, GFP_KERNEL);
	if (!p)
		return -ENOMEM;

	pkt = p;
	get = p + APR_HDR_SIZE;

	pkt->hdr.hdr_field = APR_HDR_FIELD(APR_MSG_TYPE_SEQ_CMD,
					   APR_HDR_LEN(APR_HDR_SIZE), APR_PKT_VER);
	pkt->hdr.pkt_size = pkt_size;
	pkt->hdr.src_port = copp->afe_port;
	pkt->hdr.dest_port = copp->id;
	pkt->hdr.token = copp->afe_port << 16 | copp->copp_idx;
	pkt->hdr.opcode = ADM_CMD_GET_PP_PARAMS_V5;

	get->module_id = module_id;
	get->param_id = param_id;
	get->param_max_size = max_size;

	ret = q6adm_apr_send_copp_pkt(adm, copp, pkt, ADM_CMDRSP_GET_PP_PARAMS_V5);
	kfree(pkt);
	return ret;
}

#ifdef CONFIG_DEBUG_FS
/*
 * SPX ADM PP-param probe: fire SET/GET_PP_PARAMS at the live speaker COPP so we
 * can replay dev-0x45 subgraph module params and confirm (via GET) they stuck.
 * /sys/kernel/debug/q6adm/spx_copp/{module_id,param_id,port_index,copp_index,
 *  payload,fire,get}. port_index = AFE enum index of the live COPP (SLIMBUS_2_RX
 * = 6); copp_index normally 0. The COPP must be live (playback stream open).
 * SET/GET only - never emits an ADM device-close.
 */
#define Q6ADM_SPX_MAX_PAYLOAD	1024

static ssize_t q6adm_spx_payload_write(struct file *file, const char __user *ubuf,
				       size_t count, loff_t *ppos)
{
	struct q6adm *adm = file->private_data;
	void *buf;

	if (count == 0 || count > Q6ADM_SPX_MAX_PAYLOAD)
		return -EINVAL;
	buf = memdup_user(ubuf, count);
	if (IS_ERR(buf))
		return PTR_ERR(buf);

	mutex_lock(&adm->dbg_lock);
	kfree(adm->dbg_payload);
	adm->dbg_payload = buf;
	adm->dbg_payload_len = count;
	mutex_unlock(&adm->dbg_lock);
	return count;
}

static const struct file_operations q6adm_spx_payload_fops = {
	.open = simple_open, .write = q6adm_spx_payload_write,
	.llseek = default_llseek,
};

static ssize_t q6adm_spx_fire_write(struct file *file, const char __user *ubuf,
				    size_t count, loff_t *ppos)
{
	struct q6adm *adm = file->private_data;
	struct q6copp *copp;
	int ret;

	mutex_lock(&adm->dbg_lock);
	if (!adm->dbg_payload || !adm->dbg_payload_len) {
		mutex_unlock(&adm->dbg_lock);
		dev_err(adm->dev, "spx_copp: no payload set\n");
		return -EINVAL;
	}
	copp = q6adm_find_copp(adm, adm->dbg_port_index, adm->dbg_copp_index);
	if (!copp) {
		mutex_unlock(&adm->dbg_lock);
		dev_err(adm->dev,
			"spx_copp: no live COPP at port_idx=%u copp_idx=%u (open a stream first)\n",
			adm->dbg_port_index, adm->dbg_copp_index);
		return -ENODEV;
	}
	ret = q6adm_set_pp_params(adm, copp, adm->dbg_module_id, adm->dbg_param_id,
				  adm->dbg_payload, adm->dbg_payload_len,
				  adm->dbg_phdr_ver);
	kref_put(&copp->refcount, q6adm_free_copp);
	mutex_unlock(&adm->dbg_lock);

	dev_info(adm->dev,
		 "spx_copp SET mod=0x%x param=0x%x port_idx=%u copp=%u len=%zu -> rc=%d\n",
		 adm->dbg_module_id, adm->dbg_param_id, adm->dbg_port_index,
		 adm->dbg_copp_index, adm->dbg_payload_len, ret);
	return ret ? ret : count;
}

static const struct file_operations q6adm_spx_fire_fops = {
	.open = simple_open, .write = q6adm_spx_fire_write,
	.llseek = default_llseek,
};

static ssize_t q6adm_spx_get_write(struct file *file, const char __user *ubuf,
				   size_t count, loff_t *ppos)
{
	struct q6adm *adm = file->private_data;
	struct q6copp *copp;
	int ret;

	mutex_lock(&adm->dbg_lock);
	copp = q6adm_find_copp(adm, adm->dbg_port_index, adm->dbg_copp_index);
	if (!copp) {
		mutex_unlock(&adm->dbg_lock);
		dev_err(adm->dev, "spx_copp: no live COPP (open a stream first)\n");
		return -ENODEV;
	}
	ret = q6adm_get_pp_params(adm, copp, adm->dbg_module_id,
				  adm->dbg_param_id, ADM_GET_PARAM_MAX);
	dev_info(adm->dev,
		 "spx_copp GET mod=0x%x param=0x%x -> rc=%d status=0x%x len=%d\n",
		 adm->dbg_module_id, adm->dbg_param_id, ret,
		 copp->get_param_status, copp->get_param_len);
	if (!ret && copp->get_param_len > 0)
		print_hex_dump(KERN_INFO, "spx_copp get: ", DUMP_PREFIX_OFFSET,
			       16, 1, copp->get_param, copp->get_param_len, false);
	kref_put(&copp->refcount, q6adm_free_copp);
	mutex_unlock(&adm->dbg_lock);
	return ret ? ret : count;
}

/* SPX: open a fresh COPP with ADM_DEVICE_OPEN_V8 + the dev-0x45 AudioReach
 * speaker topology. On success the returned DSP-side copp_id is stored on the
 * q6copp; subsequent SET_PP_PARAMS / GET_PP_PARAMS hits the right COPP.
 * The COPP stays open until /sys/kernel/debug/q6adm/spx_copp/v8_close fires
 * (TODO: not yet exposed - the COPP is torn down with the rest of q6adm on
 * module unload; for a one-shot by-ear test that's fine).
 */
static ssize_t q6adm_spx_v8_open_write(struct file *f, const char __user *buf,
				      size_t count, loff_t *ppos)
{
	struct q6adm *adm = f->f_inode->i_private;
	struct q6copp *copp;
	int ret, port_idx, copp_idx;
	u32 topology = adm->dbg_v8_topology;

	mutex_lock(&adm->dbg_lock);
	port_idx = adm->dbg_port_index;
	copp_idx = adm->dbg_copp_index;

	/* Force a specific copp_idx for deterministic targeting. */
	if (copp_idx >= MAX_COPPS_PER_PORT) {
		dev_err(adm->dev, "v8_open: copp_idx %d OOB\n", copp_idx);
		ret = -EINVAL;
		goto out;
	}
	/* If the requested copp already exists, reuse it. */
	copp = q6adm_find_copp(adm, port_idx, copp_idx);
	if (!copp) {
		copp = q6adm_alloc_copp(adm, port_idx);
		if (IS_ERR(copp)) {
			ret = PTR_ERR(copp);
			dev_err(adm->dev, "v8_open: alloc_copp failed: %d\n", ret);
			goto out;
		}
		kref_init(&copp->refcount);
	}

	dev_info(adm->dev,
		 "spx_copp V8 open: port=%d copp_idx=%d topology=0x%x ch=%d bw=%d rate=%d\n",
		 port_idx, copp_idx, topology,
		 adm->dbg_v8_channels, adm->dbg_v8_bit_width,
		 adm->dbg_v8_sample_rate);

	ret = q6adm_device_open_v8(adm, copp, port_idx, ADM_PATH_PLAYBACK,
				   topology, adm->dbg_v8_channels,
				   adm->dbg_v8_bit_width, adm->dbg_v8_sample_rate);
	dev_info(adm->dev, "spx_copp V8 open: rc=%d dsp_copp_id=0x%x\n",
		 ret, copp->id);
	if (ret < 0) {
		kref_put(&copp->refcount, q6adm_free_copp);
	} else {
		/* Drop the caller's ref; the COPP is now in the copps list via
		 * the standard path - keep one ref so SET/GET find it.
		 */
		kref_get(&copp->refcount);
	}

out:
	mutex_unlock(&adm->dbg_lock);
	return ret ? ret : count;
}

static const struct file_operations q6adm_spx_v8_open_fops = {
	.open = simple_open,
	.write = q6adm_spx_v8_open_write,
};

static const struct file_operations q6adm_spx_get_fops = {
	.open = simple_open, .write = q6adm_spx_get_write,
	.llseek = default_llseek,
};

static void q6adm_spx_debugfs_remove(void *data)
{
	struct q6adm *adm = data;

	debugfs_remove_recursive(adm->dbg_dir);
	kfree(adm->dbg_payload);
}

static void q6adm_spx_debugfs_init(struct q6adm *adm)
{
	struct dentry *d;

	mutex_init(&adm->dbg_lock);
	adm->dbg_port_index = 6;	/* SLIMBUS_2_RX - the speaker RX AFE port */
	adm->dbg_phdr_ver = 6;		/* SET_PP_PARAMS_V6 instance-based param hdr */
	adm->dbg_v8_topology = 0x10000001;	/* dev-0x45 AudioReach COPP */
	adm->dbg_v8_channels = 2;
	adm->dbg_v8_bit_width = 24;
	adm->dbg_v8_sample_rate = 48000;

	adm->dbg_dir = debugfs_create_dir("q6adm", NULL);
	if (IS_ERR(adm->dbg_dir))
		return;
	d = debugfs_create_dir("spx_copp", adm->dbg_dir);

	debugfs_create_x32("module_id", 0644, d, &adm->dbg_module_id);
	debugfs_create_x32("param_id", 0644, d, &adm->dbg_param_id);
	debugfs_create_u32("port_index", 0644, d, &adm->dbg_port_index);
	debugfs_create_u32("copp_index", 0644, d, &adm->dbg_copp_index);
	debugfs_create_u32("phdr_ver", 0644, d, &adm->dbg_phdr_ver);
	debugfs_create_file("payload", 0200, d, adm, &q6adm_spx_payload_fops);
	debugfs_create_file("fire", 0200, d, adm, &q6adm_spx_fire_fops);
	debugfs_create_file("get", 0200, d, adm, &q6adm_spx_get_fops);
	debugfs_create_u32("v8_topology", 0644, d, &adm->dbg_v8_topology);
	debugfs_create_u32("v8_channels", 0644, d, &adm->dbg_v8_channels);
	debugfs_create_u32("v8_bit_width", 0644, d, &adm->dbg_v8_bit_width);
	debugfs_create_u32("v8_sample_rate", 0644, d, &adm->dbg_v8_sample_rate);
	debugfs_create_file("v8_open", 0200, d, adm, &q6adm_spx_v8_open_fops);

	devm_add_action_or_reset(adm->dev, q6adm_spx_debugfs_remove, adm);
}
#else
static inline void q6adm_spx_debugfs_init(struct q6adm *adm) { }
#endif

static int q6adm_probe(struct apr_device *adev)
{
	struct device *dev = &adev->dev;
	struct q6adm *adm;

	adm = devm_kzalloc(dev, sizeof(*adm), GFP_KERNEL);
	if (!adm)
		return -ENOMEM;

	adm->apr = adev;
	dev_set_drvdata(dev, adm);
	adm->dev = dev;
	q6core_get_svc_api_info(adev->svc_id, &adm->ainfo);
	mutex_init(&adm->lock);
	init_waitqueue_head(&adm->matrix_map_wait);

	INIT_LIST_HEAD(&adm->copps_list);
	spin_lock_init(&adm->copps_list_lock);

	q6adm_spx_debugfs_init(adm);

	return devm_of_platform_populate(dev);
}

#ifdef CONFIG_OF
static const struct of_device_id q6adm_device_id[]  = {
	{ .compatible = "qcom,q6adm" },
	{},
};
MODULE_DEVICE_TABLE(of, q6adm_device_id);
#endif

static struct apr_driver qcom_q6adm_driver = {
	.probe = q6adm_probe,
	.callback = q6adm_callback,
	.driver = {
		.name = "qcom-q6adm",
		.of_match_table = of_match_ptr(q6adm_device_id),
	},
};

module_apr_driver(qcom_q6adm_driver);
MODULE_DESCRIPTION("Q6 Audio Device Manager");
MODULE_LICENSE("GPL v2");
