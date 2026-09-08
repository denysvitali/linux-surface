// SPDX-License-Identifier: GPL-2.0
/*
 * slimbus-qmi-probe.c — diagnostic-only QMI / QRTR probe for the
 * Qualcomm SLIMbus QMI service on the ADSP.
 *
 * This module is intentionally NOT a SLIMbus controller. It opens the
 * same QRTR sockets and sends the same QMI messages the real SLIMbus
 * child probe sends, but never touches the SLIMbus / BAM MMIO and
 * never starts a DMA. Its job is to bisect whether an audio bring-up
 * hang lives in the QRTR / QMI / PDR subsystem or in the SLIMbus
 * driver itself.
 *
 * Stages (selected via the probe_stage module param, like the real
 * driver):
 *
 *   0  qmi_handle_init + qmi_add_lookup for service 0x301; wait for
 *      new_server. The callback logs node/port and completes a local
 *      completion. Module stays loaded, no further action.
 *
 *   1  On top of stage 0, also connect to the discovered service with
 *      kernel_connect and send SLIMBUS_QMI_SELECT_INSTANCE_REQ_V01.
 *      This mutates ADSP-side state and is refused unless
 *      allow_qmi_mutation=1.
 *
 *   2  On top of stage 1, also send SLIMBUS_QMI_POWER_REQ_V01 with
 *      pm_req = SLIMBUS_PM_ACTIVE_V01, wait for ack, then send it
 *      again with pm_req = SLIMBUS_PM_INACTIVE_V01 and wait for ack,
 *      so the ADSP is left in the same state it was in before the
 *      probe. This is also refused unless allow_qmi_mutation=1.
 *
 * The module never registers as a SLIMbus controller and never
 * touches 0x171c0000 / 0x17184000.
 */

#define pr_fmt(fmt) "slimbus-qmi-probe: " fmt

#include <linux/completion.h>
#include <linux/delay.h>
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/soc/qcom/qmi.h>
#include <linux/types.h>
#include <linux/uaccess.h>
#include <linux/workqueue.h>
#include <net/sock.h>

#include <uapi/linux/qrtr.h>

/* SLIMbus QMI service. Same IDs as drivers/slimbus/qcom-ngd-ctrl.c. */
#define SLIMBUS_QMI_SVC_ID	0x0301
#define SLIMBUS_QMI_SVC_V1	1
#define SLIMBUS_QMI_INS_ID	0

#define SLIMBUS_QMI_SELECT_INSTANCE_REQ_V01	0x0020
#define SLIMBUS_QMI_SELECT_INSTANCE_REQ_MAX_MSG_LEN	14
#define SLIMBUS_QMI_POWER_REQ_V01		0x0021
#define SLIMBUS_QMI_POWER_REQ_MAX_MSG_LEN	14

#define SLIMBUS_QMI_RESP_TOUT	(5 * HZ)

/* QMI enums (see drivers/slimbus/qcom-ngd-ctrl.c for the wire layout) */
enum slimbus_mode_enum_type_v01 {
	SLIMBUS_MODE_SATELLITE_V01 = 1,
	SLIMBUS_MODE_MASTER_V01 = 2,
};

enum slimbus_pm_enum_type_v01 {
	SLIMBUS_PM_INACTIVE_V01 = 1,
	SLIMBUS_PM_ACTIVE_V01 = 2,
};

struct slimbus_select_inst_req_msg_v01 {
	u32 instance;
	u8  mode_valid;
	u32 mode;
};

struct slimbus_power_req_msg_v01 {
	u32 pm_req;
	u8  resp_type_valid;
	u32 resp_type;
};

struct slimbus_resp_msg_v01 {
	struct qmi_response_type_v01 resp;
};

static const struct qmi_elem_info slimbus_select_inst_req_msg_v01_ei[] = {
	{
		.data_type  = QMI_UNSIGNED_4_BYTE,
		.elem_len   = 1,
		.elem_size  = sizeof(u32),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x01,
		.offset     = offsetof(struct slimbus_select_inst_req_msg_v01, instance),
		.ei_array   = NULL,
	},
	{
		.data_type  = QMI_OPT_FLAG,
		.elem_len   = 1,
		.elem_size  = sizeof(u8),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x10,
		.offset     = offsetof(struct slimbus_select_inst_req_msg_v01, mode_valid),
		.ei_array   = NULL,
	},
	{
		.data_type  = QMI_UNSIGNED_4_BYTE,
		.elem_len   = 1,
		.elem_size  = sizeof(u32),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x10,
		.offset     = offsetof(struct slimbus_select_inst_req_msg_v01, mode),
		.ei_array   = NULL,
	},
	{
		.data_type  = QMI_EOTI,
		.elem_len   = 0,
		.elem_size  = 0,
		.array_type = NO_ARRAY,
		.tlv_type   = 0x00,
		.offset     = 0,
		.ei_array   = NULL,
	},
};

static const struct qmi_elem_info slimbus_power_req_msg_v01_ei[] = {
	{
		.data_type  = QMI_UNSIGNED_4_BYTE,
		.elem_len   = 1,
		.elem_size  = sizeof(u32),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x01,
		.offset     = offsetof(struct slimbus_power_req_msg_v01, pm_req),
		.ei_array   = NULL,
	},
	{
		.data_type  = QMI_OPT_FLAG,
		.elem_len   = 1,
		.elem_size  = sizeof(u8),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x10,
		.offset     = offsetof(struct slimbus_power_req_msg_v01, resp_type_valid),
		.ei_array   = NULL,
	},
	{
		.data_type  = QMI_UNSIGNED_4_BYTE,
		.elem_len   = 1,
		.elem_size  = sizeof(u32),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x10,
		.offset     = offsetof(struct slimbus_power_req_msg_v01, resp_type),
		.ei_array   = NULL,
	},
	{
		.data_type  = QMI_EOTI,
		.elem_len   = 0,
		.elem_size  = 0,
		.array_type = NO_ARRAY,
		.tlv_type   = 0x00,
		.offset     = 0,
		.ei_array   = NULL,
	},
};

static const struct qmi_elem_info slimbus_resp_msg_v01_ei[] = {
	{
		.data_type  = QMI_STRUCT,
		.elem_len   = 1,
		.elem_size  = sizeof(struct qmi_response_type_v01),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x02,
		.offset     = offsetof(struct slimbus_resp_msg_v01, resp),
		.ei_array   = qmi_response_type_v01_ei,
	},
	{
		.data_type  = QMI_EOTI,
		.elem_len   = 0,
		.elem_size  = 0,
		.array_type = NO_ARRAY,
		.tlv_type   = 0x00,
		.offset     = 0,
		.ei_array   = NULL,
	},
};

static int probe_stage = 0;
module_param(probe_stage, int, 0644);
MODULE_PARM_DESC(probe_stage,
		 "0=service lookup only; 1=+SELECT_INSTANCE; 2=+POWER_ACTIVE/INACTIVE");

static bool allow_qmi_mutation;
module_param(allow_qmi_mutation, bool, 0644);
MODULE_PARM_DESC(allow_qmi_mutation,
		 "allow SELECT_INSTANCE/POWER QMI requests; unsafe on Surface Pro X");

static bool pin_after_qmi_mutation = true;
module_param(pin_after_qmi_mutation, bool, 0644);
MODULE_PARM_DESC(pin_after_qmi_mutation,
		 "pin this module after SELECT_INSTANCE so rmmod cannot trigger QMI teardown/reset");

static int select_instance = 0;
module_param(select_instance, int, 0644);
MODULE_PARM_DESC(select_instance,
		 "instance value passed to SLIMBUS_QMI_SELECT_INSTANCE_REQ_V01");

static int power_resp_type = -1;
module_param(power_resp_type, int, 0644);
MODULE_PARM_DESC(power_resp_type,
		 "power_req resp_type TLV: -1=omit, 1=synchronous");

static bool log_echo = true;
module_param(log_echo, bool, 0644);
MODULE_PARM_DESC(log_echo, "log every QRTR packet seen by the new_server callback");

struct probe_state {
	struct qmi_handle svc_hdl;
	struct sockaddr_qrtr svc_info;
	struct completion svc_arrived;
	bool svc_found;

	struct socket *cli_sock;
	struct sockaddr_qrtr cli_sq;
};

static struct probe_state state;
static bool pinned_after_qmi;

static void probe_pin_after_qmi(void)
{
	if (!pin_after_qmi_mutation || pinned_after_qmi)
		return;

	if (try_module_get(THIS_MODULE)) {
		pinned_after_qmi = true;
		pr_warn("SPX: QMI-probe pinned after QMI mutation; reboot required before unloading\n");
	} else {
		pr_warn("SPX: QMI-probe failed to pin after QMI mutation\n");
	}
}

static int probe_qmi_new_server(struct qmi_handle *hdl,
				struct qmi_service *svc)
{
	struct probe_state *p =
		container_of(hdl, struct probe_state, svc_hdl);

	if (svc->service != SLIMBUS_QMI_SVC_ID)
		return 0;

	pr_info("SPX: QMI-probe new_server: node=%u port=%u service=0x%x instance=%u version=%u\n",
		svc->node, svc->port, svc->service, svc->instance, svc->version);

	p->svc_info.sq_family = AF_QIPCRTR;
	p->svc_info.sq_node = svc->node;
	p->svc_info.sq_port = svc->port;

	if (!p->svc_found) {
		p->svc_found = true;
		complete(&p->svc_arrived);
	}
	return 0;
}

static void probe_qmi_del_server(struct qmi_handle *hdl,
				 struct qmi_service *svc)
{
	struct probe_state *p =
		container_of(hdl, struct probe_state, svc_hdl);

	if (svc->service != SLIMBUS_QMI_SVC_ID)
		return;

	pr_info("SPX: QMI-probe del_server: node=%u port=%u service=0x%x\n",
		svc->node, svc->port, svc->service);

	p->svc_found = false;
	reinit_completion(&p->svc_arrived);
}

static void probe_qmi_net_reset(struct qmi_handle *hdl)
{
	pr_info("SPX: QMI-probe net_reset\n");
}

static const struct qmi_ops probe_qmi_ops = {
	.new_server = probe_qmi_new_server,
	.del_server = probe_qmi_del_server,
	.net_reset  = probe_qmi_net_reset,
};

static int probe_run_select_instance(struct probe_state *p)
{
	struct slimbus_select_inst_req_msg_v01 req = { 0 };
	struct slimbus_resp_msg_v01 resp = { { 0, 0 } };
	struct qmi_txn txn;
	int rc;

	req.instance = select_instance;
	/* mode TLV omitted (mode_valid=0), matching the real driver's
	 * "spx_select_mode default 0" behaviour. */

	pr_info("SPX: QMI-probe stage 1: select_instance req begin instance=%u\n",
		req.instance);

	rc = qmi_txn_init(&p->svc_hdl, &txn, slimbus_resp_msg_v01_ei, &resp);
	if (rc < 0) {
		pr_err("SPX: QMI-probe select_instance qmi_txn_init failed:%d\n", rc);
		return rc;
	}

	rc = qmi_send_request(&p->svc_hdl, NULL, &txn,
			      SLIMBUS_QMI_SELECT_INSTANCE_REQ_V01,
			      SLIMBUS_QMI_SELECT_INSTANCE_REQ_MAX_MSG_LEN,
			      slimbus_select_inst_req_msg_v01_ei, &req);
	if (rc < 0) {
		pr_err("SPX: QMI-probe select_instance qmi_send_request failed:%d\n", rc);
		qmi_txn_cancel(&txn);
		return rc;
	}

	rc = qmi_txn_wait(&txn, SLIMBUS_QMI_RESP_TOUT);
	if (rc < 0) {
		pr_err("SPX: QMI-probe select_instance qmi_txn_wait failed:%d\n", rc);
		return rc;
	}

	pr_info("SPX: QMI-probe stage 1: select_instance ack result=0x%x error=0x%x\n",
		resp.resp.result, resp.resp.error);

	if (resp.resp.result != QMI_RESULT_SUCCESS_V01)
		return -EREMOTEIO;
	return 0;
}

static int probe_run_power(struct probe_state *p, u32 pm_req)
{
	struct slimbus_power_req_msg_v01 req = { 0 };
	struct slimbus_resp_msg_v01 resp = { { 0, 0 } };
	struct qmi_txn txn;
	int rc;

	req.pm_req = pm_req;
	if (power_resp_type >= 0) {
		req.resp_type_valid = 1;
		req.resp_type = power_resp_type;
	} else {
		req.resp_type_valid = 0;
		req.resp_type = 1;
	}

	pr_info("SPX: QMI-probe stage 2: power req begin pm_req=%u resp_type_valid=%u resp_type=%u\n",
		pm_req, req.resp_type_valid, req.resp_type);

	rc = qmi_txn_init(&p->svc_hdl, &txn, slimbus_resp_msg_v01_ei, &resp);
	if (rc < 0) {
		pr_err("SPX: QMI-probe power qmi_txn_init failed:%d\n", rc);
		return rc;
	}

	rc = qmi_send_request(&p->svc_hdl, NULL, &txn,
			      SLIMBUS_QMI_POWER_REQ_V01,
			      SLIMBUS_QMI_POWER_REQ_MAX_MSG_LEN,
			      slimbus_power_req_msg_v01_ei, &req);
	if (rc < 0) {
		pr_err("SPX: QMI-probe power qmi_send_request failed:%d\n", rc);
		qmi_txn_cancel(&txn);
		return rc;
	}

	rc = qmi_txn_wait(&txn, SLIMBUS_QMI_RESP_TOUT);
	if (rc < 0) {
		pr_err("SPX: QMI-probe power qmi_txn_wait failed:%d\n", rc);
		return rc;
	}

	pr_info("SPX: QMI-probe stage 2: power ack result=0x%x error=0x%x\n",
		resp.resp.result, resp.resp.error);

	if (resp.resp.result != QMI_RESULT_SUCCESS_V01)
		return -EREMOTEIO;
	return 0;
}

static int __init slimbus_qmi_probe_init(void)
{
	struct probe_state *p = &state;
	long time_left;
	int rc;

	memset(p, 0, sizeof(*p));
	init_completion(&p->svc_arrived);

	pr_info("SPX: QMI-probe init begin stage=%d\n", probe_stage);

	pr_info("SPX: QMI-probe stage 0: handle init begin\n");
	rc = qmi_handle_init(&p->svc_hdl,
			     SLIMBUS_QMI_POWER_REQ_MAX_MSG_LEN,
			     &probe_qmi_ops, NULL);
	if (rc < 0) {
		pr_err("SPX: QMI-probe stage 0: handle init failed:%d\n", rc);
		return rc;
	}
	pr_info("SPX: QMI-probe stage 0: handle init done\n");

	pr_info("SPX: QMI-probe stage 0: add_lookup svc=0x%x v=%u inst=%u\n",
		SLIMBUS_QMI_SVC_ID, SLIMBUS_QMI_SVC_V1, SLIMBUS_QMI_INS_ID);
	rc = qmi_add_lookup(&p->svc_hdl, SLIMBUS_QMI_SVC_ID,
			    SLIMBUS_QMI_SVC_V1, SLIMBUS_QMI_INS_ID);
	if (rc < 0) {
		pr_err("SPX: QMI-probe stage 0: add_lookup failed:%d\n", rc);
		qmi_handle_release(&p->svc_hdl);
		return rc;
	}

	pr_info("SPX: QMI-probe stage 0: waiting for new_server (3s)\n");
	time_left = wait_for_completion_interruptible_timeout(&p->svc_arrived,
							      msecs_to_jiffies(3000));
	if (time_left <= 0) {
		pr_err("SPX: QMI-probe stage 0: new_server did not arrive (%ld)\n",
		       time_left);
		qmi_handle_release(&p->svc_hdl);
		return time_left ?: -ETIMEDOUT;
	}
	pr_info("SPX: QMI-probe stage 0: done node=%u port=%u\n",
		p->svc_info.sq_node, p->svc_info.sq_port);

	if (probe_stage < 1)
		goto stay_loaded;

	if (!allow_qmi_mutation) {
		pr_err("SPX: QMI-probe refusing stage=%d without allow_qmi_mutation=1\n",
		       probe_stage);
		qmi_handle_release(&p->svc_hdl);
		return -EPERM;
	}

	/*
	 * Stages 1 and 2 reuse the service-event QMI handle. The QMI
	 * helpers do NOT auto-connect the socket: qmi_send_request()
	 * ultimately calls kernel_sendmsg() with no msg_name when called
	 * with sq=NULL, and for AF_QIPCRTR SOCK_DGRAM that returns
	 * EOPNOTSUPP (-107) if the socket is unconnected. The real
	 * driver does an explicit kernel_connect() in qcom_slim_qmi_init
	 * (drivers/slimbus/qcom-ngd-ctrl.c:525); we mirror that here.
	 */
	pr_info("SPX: QMI-probe stage 0: connecting to node=%u port=%u\n",
		p->svc_info.sq_node, p->svc_info.sq_port);
	rc = kernel_connect(p->svc_hdl.sock,
			    (struct sockaddr_unsized *)&p->svc_info,
			    sizeof(p->svc_info), 0);
	if (rc < 0) {
		pr_err("SPX: QMI-probe stage 0: kernel_connect failed:%d\n", rc);
		qmi_handle_release(&p->svc_hdl);
		return rc;
	}
	pr_info("SPX: QMI-probe stage 0: connected\n");

	rc = probe_run_select_instance(p);
	if (rc) {
		pr_err("SPX: QMI-probe stage 1: failed:%d\n", rc);
		qmi_handle_release(&p->svc_hdl);
		return rc;
	}
	pr_info("SPX: QMI-probe stage 1: done\n");
	probe_pin_after_qmi();

	if (probe_stage < 2)
		goto stay_loaded;

	rc = probe_run_power(p, SLIMBUS_PM_ACTIVE_V01);
	if (rc) {
		pr_err("SPX: QMI-probe stage 2: power=active failed:%d\n", rc);
		qmi_handle_release(&p->svc_hdl);
		return rc;
	}

	rc = probe_run_power(p, SLIMBUS_PM_INACTIVE_V01);
	if (rc) {
		pr_err("SPX: QMI-probe stage 2: power=inactive failed:%d\n", rc);
		qmi_handle_release(&p->svc_hdl);
		return rc;
	}
	pr_info("SPX: QMI-probe stage 2: done\n");

stay_loaded:
	pr_info("SPX: QMI-probe init done; stage=%d; module stays loaded until rmmod\n",
		probe_stage);
	/* Stay loaded so the QMI handle keeps the SLIMbus service in its
	 * lookup list. The user unloads with `sudo modprobe -r
	 * slimbus_qmi_probe` to release the QRTR socket cleanly. */
	return 0;
}

static void __exit slimbus_qmi_probe_exit(void)
{
	pr_info("SPX: QMI-probe exit: releasing handle\n");
	qmi_handle_release(&state.svc_hdl);
	pr_info("SPX: QMI-probe exit done\n");
}

module_init(slimbus_qmi_probe_init);
module_exit(slimbus_qmi_probe_exit);

MODULE_AUTHOR("Denys Vitali <denys.vitali@…>");
MODULE_DESCRIPTION("Qualcomm SLIMbus QMI / QRTR diagnostic probe");
MODULE_LICENSE("GPL v2");
