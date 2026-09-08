// SPDX-License-Identifier: GPL-2.0
// Copyright (c) 2011-2017, The Linux Foundation. All rights reserved.
// Copyright (c) 2018, Linaro Limited

#include <linux/irq.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/slab.h>
#include <linux/interrupt.h>
#include <linux/platform_device.h>
#include <linux/dma-mapping.h>
#include <linux/dmaengine.h>
#include <linux/slimbus.h>
#include <linux/delay.h>
#include <linux/pm_runtime.h>
#include <linux/mutex.h>
#include <linux/kthread.h>
#include <linux/notifier.h>
#include <linux/remoteproc/qcom_rproc.h>
#include <linux/of.h>
#include <linux/io.h>
#include <linux/soc/qcom/qmi.h>
#include <linux/soc/qcom/pdr.h>
#include <net/sock.h>
#include "slimbus.h"

/* NGD (Non-ported Generic Device) registers */
#define	NGD_CFG			0x0
#define	NGD_CFG_ENABLE		BIT(0)
#define	NGD_CFG_RX_MSGQ_EN	BIT(1)
#define	NGD_CFG_TX_MSGQ_EN	BIT(2)
#define	NGD_STATUS		0x4
#define NGD_LADDR		BIT(1)
#define	NGD_RX_MSGQ_CFG		0x8
#define	NGD_INT_EN		0x10
#define	NGD_INT_RECFG_DONE	BIT(24)
#define	NGD_INT_TX_NACKED_2	BIT(25)
#define	NGD_INT_MSG_BUF_CONTE	BIT(26)
#define	NGD_INT_MSG_TX_INVAL	BIT(27)
#define	NGD_INT_IE_VE_CHG	BIT(28)
#define	NGD_INT_DEV_ERR		BIT(29)
#define	NGD_INT_RX_MSG_RCVD	BIT(30)
#define	NGD_INT_TX_MSG_SENT	BIT(31)
#define	NGD_INT_STAT		0x14
#define	NGD_INT_CLR		0x18
/*
 * SPX PIO mode: message FIFO offsets in the NGD child window, taken from
 * downstream slim-msm-ngd.c (non-msgq mode). TX FIFO is write-only; the
 * RX FIFO pops on read, so it must only be read with NGD_INT_RX_MSG_RCVD
 * latched. IE/VE_STAT are unverified on this firmware - guarded debug
 * reads only.
 */
#define	NGD_TX_MSG		0x30
#define	NGD_RX_MSG		0x70
#define	NGD_IE_STAT		0xf0
#define	NGD_VE_STAT		0x100
#define SPX_PIO_TX_TOUT_US	50000
#define DEF_NGD_INT_MASK (NGD_INT_TX_NACKED_2 | NGD_INT_MSG_BUF_CONTE | \
				NGD_INT_MSG_TX_INVAL | NGD_INT_IE_VE_CHG | \
				NGD_INT_DEV_ERR | NGD_INT_TX_MSG_SENT | \
				NGD_INT_RX_MSG_RCVD)

/* Slimbus QMI service */
#define SLIMBUS_QMI_SVC_ID	0x0301
#define SLIMBUS_QMI_SVC_V1	1
#define SLIMBUS_QMI_INS_ID	0
#define SLIMBUS_QMI_SELECT_INSTANCE_REQ_V01	0x0020
#define SLIMBUS_QMI_SELECT_INSTANCE_RESP_V01	0x0020
#define SLIMBUS_QMI_POWER_REQ_V01		0x0021
#define SLIMBUS_QMI_POWER_RESP_V01		0x0021
#define SLIMBUS_QMI_CHECK_FRAMER_STATUS_REQ	0x0022
#define SLIMBUS_QMI_CHECK_FRAMER_STATUS_RESP	0x0022
#define SLIMBUS_QMI_POWER_REQ_MAX_MSG_LEN	14
#define SLIMBUS_QMI_POWER_RESP_MAX_MSG_LEN	7
#define SLIMBUS_QMI_SELECT_INSTANCE_REQ_MAX_MSG_LEN	14
#define SLIMBUS_QMI_SELECT_INSTANCE_RESP_MAX_MSG_LEN	7
#define SLIMBUS_QMI_CHECK_FRAMER_STAT_RESP_MAX_MSG_LEN	7
/* SPX ADSP QMI can stall briefly while audio_pd is recovering. */
#define SLIMBUS_QMI_RESP_TOUT	(5 * HZ)
#define SLIMBUS_QMI_SELECT_RETRIES	3

/* User defined commands */
#define SLIM_USR_MC_GENERIC_ACK	0x25
#define SLIM_USR_MC_MASTER_CAPABILITY	0x0
#define SLIM_USR_MC_REPORT_SATELLITE	0x1
#define SLIM_USR_MC_ADDR_QUERY		0xD
#define SLIM_USR_MC_ADDR_REPLY		0xE
#define SLIM_USR_MC_DEFINE_CHAN		0x20
#define SLIM_USR_MC_DEF_ACT_CHAN	0x21
#define SLIM_USR_MC_CHAN_CTRL		0x23
#define SLIM_USR_MC_RECONFIG_NOW	0x24
#define SLIM_USR_MC_REQ_BW		0x28
#define SLIM_USR_MC_CONNECT_SRC		0x2C
#define SLIM_USR_MC_CONNECT_SINK	0x2D
#define SLIM_USR_MC_DISCONNECT_PORT	0x2E
#define SLIM_USR_MC_REPEAT_CHANGE_VALUE	0x0

#define SLIM_RX_MSGQ_TIMEOUT_VAL	0x10000

#define SLIM_LA_MGR	0xFF
#define SLIM_ROOT_FREQ	24576000
#define LADDR_RETRY	5

/* Per spec.max 40 bytes per received message */
#define SLIM_MSGQ_BUF_LEN	40
#define QCOM_SLIM_NGD_DESC_NUM	32

#define SLIM_MSG_ASM_FIRST_WORD(l, mt, mc, dt, ad) \
		((l) | ((mt) << 5) | ((mc) << 8) | ((dt) << 15) | ((ad) << 16))

#define INIT_MX_RETRIES 10
#define DEF_RETRY_MS	10
#define SAT_MAGIC_LSB	0xD9
#define SAT_MAGIC_MSB	0xC5
#define SAT_MSG_VER	0x1
#define SAT_MSG_PROT	0x1
#define to_ngd(d)	container_of(d, struct qcom_slim_ngd, dev)

/*
 * SPX bring-up guard:
 *   0 = register/teardown plumbing only, no SLIMbus QMI mutation
 *   1 = QMI select_instance only
 *   2 = QMI select_instance + power request only
 *   3 = QMI power + read top-level NGD version register
 *   4 = stage 3 + read child NGD status/config registers
 *   5 = stage 4 + optional child NGD write sub-step (spx_stage5_step)
 *   6 = stage 5 + initialize BAM DMA channels/descriptors
 *   7 = full NGD/BAM/MMIO power-up, stop before SLIM registration
 *   8 = full NGD/BAM/MMIO bring-up and SLIM registration
 *
 * Keep the default conservative while this platform is under diagnosis.
 */
static int spx_probe_stage;
module_param(spx_probe_stage, int, 0644);
MODULE_PARM_DESC(spx_probe_stage,
		 "Surface Pro X probe stage: 0=no QMI mutation, 1=qmi-select, 2=qmi-power, 3=read-ver, 4=read-ngd, 5=controlled-write, 6=dma-init, 7=power-up-no-register, 8=full");

static int spx_stage5_step;
module_param(spx_stage5_step, int, 0644);
MODULE_PARM_DESC(spx_stage5_step,
		 "Surface Pro X stage 5 sub-step: 0=no writes, 1=RX timeout write, 2=INT_CLR write, 3=INT_EN write then disable");

static bool spx_allow_int_en;
module_param(spx_allow_int_en, bool, 0644);
MODULE_PARM_DESC(spx_allow_int_en,
		 "Surface Pro X: allow diagnostic writes to NGD_INT_EN; unsafe, can reset the device");

static bool spx_allow_dma;
module_param(spx_allow_dma, bool, 0644);
MODULE_PARM_DESC(spx_allow_dma,
		 "Surface Pro X: allow staged BAM DMA init; unsafe until NGD reset cause is understood");

static bool spx_allow_full;
module_param(spx_allow_full, bool, 0644);
MODULE_PARM_DESC(spx_allow_full,
		 "Surface Pro X: allow full SLIMbus controller registration; unsafe until stage 7 works");

static bool spx_pin_after_qmi = true;
module_param(spx_pin_after_qmi, bool, 0644);
MODULE_PARM_DESC(spx_pin_after_qmi,
		 "Surface Pro X: pin this module after SELECT_INSTANCE so rmmod cannot trigger QMI teardown/reset");

static bool spx_poll_rx = true;
module_param(spx_poll_rx, bool, 0644);
MODULE_PARM_DESC(spx_poll_rx,
		 "Surface Pro X: poll RX message buffers while NGD_INT_EN is disabled");

static int spx_stage6_step;
module_param(spx_stage6_step, int, 0644);
MODULE_PARM_DESC(spx_stage6_step,
		 "Surface Pro X stage 6 sub-step: 0=no DMA, 1=RX chan request, 2=RX alloc, 3=RX descriptors, 4=RX+TX full DMA init");

static int spx_stage7_step;
module_param(spx_stage7_step, int, 0644);
MODULE_PARM_DESC(spx_stage7_step,
		 "Surface Pro X stage 7 sub-step: 0=QMI power+reads, 1=RX chan, 2=RX buffer, 3=RX desc submit only, 4=RX desc issue, 5=RX+TX DMA, 6=NGD_CFG enable, 7=capability polling");

static int spx_select_mode;
module_param(spx_select_mode, int, 0644);
MODULE_PARM_DESC(spx_select_mode,
		 "Surface Pro X select_instance mode TLV: 0=omit, 1=satellite, 2=master");

static int spx_select_instance = -1;
module_param(spx_select_instance, int, 0644);
MODULE_PARM_DESC(spx_select_instance,
		 "Surface Pro X select_instance override: -1=use DT-derived default");

static int spx_power_resp_type = -1;
module_param(spx_power_resp_type, int, 0644);
MODULE_PARM_DESC(spx_power_resp_type,
		 "Surface Pro X power_req resp_type TLV: -1=omit, 1=synchronous");

static int spx_dma_mask_bits;
module_param(spx_dma_mask_bits, int, 0644);
MODULE_PARM_DESC(spx_dma_mask_bits,
		 "Surface Pro X SLIM coherent DMA mask bits applied before RX/TX buffer allocation, 0=unchanged");

static bool spx_qmi_bypass_lookup;
module_param(spx_qmi_bypass_lookup, bool, 0644);
MODULE_PARM_DESC(spx_qmi_bypass_lookup,
		 "Surface Pro X: skip QMI service lookup and use spx_qmi_node/spx_qmi_port");

static int spx_qmi_node = -1;
module_param(spx_qmi_node, int, 0644);
MODULE_PARM_DESC(spx_qmi_node,
		 "Surface Pro X: QRTR node for spx_qmi_bypass_lookup");

static int spx_qmi_port = -1;
module_param(spx_qmi_port, int, 0644);
MODULE_PARM_DESC(spx_qmi_port,
		 "Surface Pro X: QRTR port for spx_qmi_bypass_lookup");

static bool spx_pdr_auto_enable;
module_param(spx_pdr_auto_enable, bool, 0644);
MODULE_PARM_DESC(spx_pdr_auto_enable,
		 "Surface Pro X: allow PDR/SSR UP events to auto-enable NGD");

static bool spx_dump_windows;
module_param(spx_dump_windows, bool, 0644);
MODULE_PARM_DESC(spx_dump_windows,
		 "Surface Pro X: dump known-safe NGD register windows after QMI power");

static int spx_ngd_base_offset = -1;
module_param(spx_ngd_base_offset, int, 0644);
MODULE_PARM_DESC(spx_ngd_base_offset,
		 "Surface Pro X NGD child base offset override in bytes, -1=DT id-derived");

static bool spx_pio_mode;
module_param(spx_pio_mode, bool, 0644);
MODULE_PARM_DESC(spx_pio_mode,
		 "Surface Pro X: PIO/FIFO NGD messaging: no BAM DMA at all, NGD_INT_EN stays 0, poll INT_STAT");

static bool spx_pio_tx_nowait;
module_param(spx_pio_tx_nowait, bool, 0644);
MODULE_PARM_DESC(spx_pio_tx_nowait,
		 "Surface Pro X: skip the TX_MSG_SENT poll after a PIO TX, use a fixed 2ms delay instead");

static int spx_pio_cap_retries = 3;
module_param(spx_pio_cap_retries, int, 0644);
MODULE_PARM_DESC(spx_pio_cap_retries,
		 "Surface Pro X: proactive REPORT_SATELLITE sends while waiting for capability exchange, 0=observe only");

static bool spx_pio_debug_reads;
module_param(spx_pio_debug_reads, bool, 0644);
MODULE_PARM_DESC(spx_pio_debug_reads,
		 "Surface Pro X: on capability timeout, read NGD_IE_STAT/NGD_VE_STAT once (unverified offsets)");

static bool spx_pio_verbose;
module_param(spx_pio_verbose, bool, 0644);
MODULE_PARM_DESC(spx_pio_verbose,
		 "Surface Pro X: log every PIO RX frame and parsed message; floods printk under regmap traffic");

struct ngd_reg_offset_data {
	u32 offset, size;
};

static const struct ngd_reg_offset_data ngd_v1_5_offset_info = {
	.offset = 0x1000,
	.size = 0x1000,
};

enum qcom_slim_ngd_state {
	QCOM_SLIM_NGD_CTRL_AWAKE,
	QCOM_SLIM_NGD_CTRL_IDLE,
	QCOM_SLIM_NGD_CTRL_ASLEEP,
	QCOM_SLIM_NGD_CTRL_DOWN,
};

struct qcom_slim_ngd_qmi {
	struct qmi_handle qmi;
	struct sockaddr_qrtr svc_info;
	struct qmi_handle svc_event_hdl;
	struct qmi_response_type_v01 resp;
	struct qmi_handle *handle;
	struct completion qmi_comp;
	bool powered;
};

struct qcom_slim_ngd_ctrl;
struct qcom_slim_ngd;

struct qcom_slim_ngd_dma_desc {
	struct dma_async_tx_descriptor *desc;
	struct qcom_slim_ngd_ctrl *ctrl;
	struct completion *comp;
	dma_cookie_t cookie;
	dma_addr_t phys;
	void *base;
};

struct qcom_slim_ngd {
	struct platform_device *pdev;
	void __iomem *base;
	int id;
};

struct qcom_slim_ngd_ctrl {
	struct slim_framer framer;
	struct slim_controller ctrl;
	struct qcom_slim_ngd_qmi qmi;
	struct qcom_slim_ngd *ngd;
	struct device *dev;
	void __iomem *base;
	struct dma_chan *dma_rx_channel;
	struct dma_chan	*dma_tx_channel;
	struct qcom_slim_ngd_dma_desc rx_desc[QCOM_SLIM_NGD_DESC_NUM];
	struct qcom_slim_ngd_dma_desc txdesc[QCOM_SLIM_NGD_DESC_NUM];
	struct completion reconf;
	struct work_struct m_work;
	struct work_struct ngd_up_work;
	atomic_t ngd_up_work_pending;
	struct workqueue_struct *mwq;
	struct completion qmi_up;
	spinlock_t tx_buf_lock;
	struct mutex tx_lock;
	struct mutex ssr_lock;
	bool ctrl_registered;
	bool qmi_svc_event_active;
	bool qmi_module_pinned;
	bool removing;
	/*
	 * True only between a QMI power-on ack and the next power-off/QMI
	 * teardown/SSR-down. Any NGD MMIO access while the block is gated
	 * stalls the bus and wedges the CPU, so the IRQ handler must fail
	 * closed on this flag.
	 */
	bool mmio_alive;
	unsigned int irq_count;
	unsigned long rx_poll_seen;
	struct task_struct *pio_task;
	bool pio_tx_fifo_logged;
	bool pio_rx_dead;
	int pio_rx_anomalies;
	u8 pio_last_rx[SLIM_MSGQ_BUF_LEN];
	int pio_last_rx_len;
	struct notifier_block nb;
	void *notifier;
	struct pdr_handle *pdr;
	enum qcom_slim_ngd_state state;
	dma_addr_t rx_phys_base;
	dma_addr_t tx_phys_base;
	void *rx_base;
	void *tx_base;
	int tx_tail;
	int tx_head;
	u32 ver;
};

enum slimbus_mode_enum_type_v01 {
	/* To force a 32 bit signed enum. Do not change or use*/
	SLIMBUS_MODE_ENUM_TYPE_MIN_ENUM_VAL_V01 = INT_MIN,
	SLIMBUS_MODE_SATELLITE_V01 = 1,
	SLIMBUS_MODE_MASTER_V01 = 2,
	SLIMBUS_MODE_ENUM_TYPE_MAX_ENUM_VAL_V01 = INT_MAX,
};

enum slimbus_pm_enum_type_v01 {
	/* To force a 32 bit signed enum. Do not change or use*/
	SLIMBUS_PM_ENUM_TYPE_MIN_ENUM_VAL_V01 = INT_MIN,
	SLIMBUS_PM_INACTIVE_V01 = 1,
	SLIMBUS_PM_ACTIVE_V01 = 2,
	SLIMBUS_PM_ENUM_TYPE_MAX_ENUM_VAL_V01 = INT_MAX,
};

enum slimbus_resp_enum_type_v01 {
	SLIMBUS_RESP_ENUM_TYPE_MIN_VAL_V01 = INT_MIN,
	SLIMBUS_RESP_SYNCHRONOUS_V01 = 1,
	SLIMBUS_RESP_ENUM_TYPE_MAX_VAL_V01 = INT_MAX,
};

struct slimbus_select_inst_req_msg_v01 {
	uint32_t instance;
	uint8_t mode_valid;
	enum slimbus_mode_enum_type_v01 mode;
};

struct slimbus_select_inst_resp_msg_v01 {
	struct qmi_response_type_v01 resp;
};

struct slimbus_power_req_msg_v01 {
	enum slimbus_pm_enum_type_v01 pm_req;
	uint8_t resp_type_valid;
	enum slimbus_resp_enum_type_v01 resp_type;
};

struct slimbus_power_resp_msg_v01 {
	struct qmi_response_type_v01 resp;
};

static const struct qmi_elem_info slimbus_select_inst_req_msg_v01_ei[] = {
	{
		.data_type  = QMI_UNSIGNED_4_BYTE,
		.elem_len   = 1,
		.elem_size  = sizeof(uint32_t),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x01,
		.offset     = offsetof(struct slimbus_select_inst_req_msg_v01,
				       instance),
		.ei_array   = NULL,
	},
	{
		.data_type  = QMI_OPT_FLAG,
		.elem_len   = 1,
		.elem_size  = sizeof(uint8_t),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x10,
		.offset     = offsetof(struct slimbus_select_inst_req_msg_v01,
				       mode_valid),
		.ei_array   = NULL,
	},
	{
		.data_type  = QMI_UNSIGNED_4_BYTE,
		.elem_len   = 1,
		.elem_size  = sizeof(enum slimbus_mode_enum_type_v01),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x10,
		.offset     = offsetof(struct slimbus_select_inst_req_msg_v01,
				       mode),
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

static const struct qmi_elem_info slimbus_select_inst_resp_msg_v01_ei[] = {
	{
		.data_type  = QMI_STRUCT,
		.elem_len   = 1,
		.elem_size  = sizeof(struct qmi_response_type_v01),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x02,
		.offset     = offsetof(struct slimbus_select_inst_resp_msg_v01,
				       resp),
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

static const struct qmi_elem_info slimbus_power_req_msg_v01_ei[] = {
	{
		.data_type  = QMI_UNSIGNED_4_BYTE,
		.elem_len   = 1,
		.elem_size  = sizeof(enum slimbus_pm_enum_type_v01),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x01,
		.offset     = offsetof(struct slimbus_power_req_msg_v01,
				       pm_req),
		.ei_array   = NULL,
	},
	{
		.data_type  = QMI_OPT_FLAG,
		.elem_len   = 1,
		.elem_size  = sizeof(uint8_t),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x10,
		.offset     = offsetof(struct slimbus_power_req_msg_v01,
				       resp_type_valid),
	},
	{
		.data_type  = QMI_SIGNED_4_BYTE_ENUM,
		.elem_len   = 1,
		.elem_size  = sizeof(enum slimbus_resp_enum_type_v01),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x10,
		.offset     = offsetof(struct slimbus_power_req_msg_v01,
				       resp_type),
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

static const struct qmi_elem_info slimbus_power_resp_msg_v01_ei[] = {
	{
		.data_type  = QMI_STRUCT,
		.elem_len   = 1,
		.elem_size  = sizeof(struct qmi_response_type_v01),
		.array_type = NO_ARRAY,
		.tlv_type   = 0x02,
		.offset     = offsetof(struct slimbus_power_resp_msg_v01, resp),
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

static int qcom_slim_qmi_send_select_inst_req(struct qcom_slim_ngd_ctrl *ctrl,
				struct slimbus_select_inst_req_msg_v01 *req)
{
	struct slimbus_select_inst_resp_msg_v01 resp = { { 0, 0 } };
	struct qmi_txn txn;
	int rc;

	rc = qmi_txn_init(ctrl->qmi.handle, &txn,
				slimbus_select_inst_resp_msg_v01_ei, &resp);
	if (rc < 0) {
		dev_err(ctrl->dev, "QMI TXN init fail: %d\n", rc);
		return rc;
	}

	rc = qmi_send_request(ctrl->qmi.handle, NULL, &txn,
				SLIMBUS_QMI_SELECT_INSTANCE_REQ_V01,
				SLIMBUS_QMI_SELECT_INSTANCE_REQ_MAX_MSG_LEN,
				slimbus_select_inst_req_msg_v01_ei, req);
	if (rc < 0) {
		dev_err(ctrl->dev, "QMI send req fail %d\n", rc);
		qmi_txn_cancel(&txn);
		return rc;
	}

	rc = qmi_txn_wait(&txn, SLIMBUS_QMI_RESP_TOUT);
	if (rc < 0) {
		dev_err(ctrl->dev, "QMI TXN wait fail: %d\n", rc);
		return rc;
	}
	/* Check the response */
	if (resp.resp.result != QMI_RESULT_SUCCESS_V01) {
		dev_err(ctrl->dev, "QMI select_instance failed result=0x%x error=0x%x\n",
			resp.resp.result, resp.resp.error);
		return -EREMOTEIO;
	}

	return 0;
}

static void qcom_slim_qmi_power_resp_cb(struct qmi_handle *handle,
					struct sockaddr_qrtr *sq,
					struct qmi_txn *txn, const void *data)
{
	struct slimbus_power_resp_msg_v01 *resp;

	resp = (struct slimbus_power_resp_msg_v01 *)data;
	if (resp->resp.result != QMI_RESULT_SUCCESS_V01)
		pr_err("QMI power request failed 0x%x\n",
				resp->resp.result);

	complete(&txn->completion);
}

static int qcom_slim_qmi_send_power_request(struct qcom_slim_ngd_ctrl *ctrl,
					struct slimbus_power_req_msg_v01 *req)
{
	struct slimbus_power_resp_msg_v01 resp = { { 0, 0 } };
	struct qmi_txn txn;
	int rc;

	rc = qmi_txn_init(ctrl->qmi.handle, &txn,
				slimbus_power_resp_msg_v01_ei, &resp);
	if (rc < 0) {
		dev_err(ctrl->dev, "QMI TXN init fail: %d\n", rc);
		return rc;
	}
	dev_info(ctrl->dev,
		 "SPX: QMI power txn init done pm_req=%u resp_type_valid=%u resp_type=%d txn_id=%d\n",
		 req->pm_req, req->resp_type_valid, req->resp_type, txn.id);

	dev_info(ctrl->dev,
		 "SPX: QMI power send begin pm_req=%u resp_type_valid=%u resp_type=%d\n",
		 req->pm_req, req->resp_type_valid, req->resp_type);
	rc = qmi_send_request(ctrl->qmi.handle, NULL, &txn,
				SLIMBUS_QMI_POWER_REQ_V01,
				SLIMBUS_QMI_POWER_REQ_MAX_MSG_LEN,
				slimbus_power_req_msg_v01_ei, req);
	if (rc < 0) {
		dev_err(ctrl->dev, "QMI send req fail %d\n", rc);
		qmi_txn_cancel(&txn);
		return rc;
	}
	dev_info(ctrl->dev, "SPX: QMI power send done pm_req=%u ret=%d\n",
		 req->pm_req, rc);

	dev_info(ctrl->dev, "SPX: QMI power wait begin pm_req=%u timeout=%u ms\n",
		 req->pm_req, jiffies_to_msecs(SLIMBUS_QMI_RESP_TOUT));
	rc = qmi_txn_wait(&txn, SLIMBUS_QMI_RESP_TOUT);
	if (rc < 0) {
		dev_err(ctrl->dev, "QMI TXN wait fail: %d\n", rc);
		return rc;
	}
	dev_info(ctrl->dev,
		 "SPX: QMI power wait done pm_req=%u result=0x%x error=0x%x\n",
		 req->pm_req, resp.resp.result, resp.resp.error);

	/* Check the response */
	if (resp.resp.result != QMI_RESULT_SUCCESS_V01) {
		dev_err(ctrl->dev, "QMI request failed 0x%x\n",
			resp.resp.result);
		return -EREMOTEIO;
	}

	return 0;
}

static const struct qmi_msg_handler qcom_slim_qmi_msg_handlers[] = {
	{
		.type = QMI_RESPONSE,
		.msg_id = SLIMBUS_QMI_POWER_RESP_V01,
		.ei = slimbus_power_resp_msg_v01_ei,
		.decoded_size = sizeof(struct slimbus_power_resp_msg_v01),
		.fn = qcom_slim_qmi_power_resp_cb,
	},
	{}
};

static void qcom_slim_ngd_pin_after_qmi(struct qcom_slim_ngd_ctrl *ctrl)
{
	if (!spx_pin_after_qmi || ctrl->qmi_module_pinned)
		return;

	if (try_module_get(THIS_MODULE)) {
		ctrl->qmi_module_pinned = true;
		dev_warn(ctrl->dev,
			 "SPX: module pinned after SLIMbus QMI mutation; reboot required before unloading\n");
	} else {
		dev_warn(ctrl->dev,
			 "SPX: failed to pin module after SLIMbus QMI mutation\n");
	}
}

static int qcom_slim_qmi_init(struct qcom_slim_ngd_ctrl *ctrl,
			      bool apps_is_master)
{
	struct slimbus_select_inst_req_msg_v01 req;
	struct qmi_handle *handle;
	int attempt, rc;

	handle = devm_kzalloc(ctrl->dev, sizeof(*handle), GFP_KERNEL);
	if (!handle)
		return -ENOMEM;

	dev_info(ctrl->dev,
		 "SPX: direct QMI handle init begin max_len=%u svc_node=%u svc_port=%u\n",
		 SLIMBUS_QMI_POWER_REQ_MAX_MSG_LEN,
		 ctrl->qmi.svc_info.sq_node, ctrl->qmi.svc_info.sq_port);
	rc = qmi_handle_init(handle, SLIMBUS_QMI_POWER_REQ_MAX_MSG_LEN,
				NULL, qcom_slim_qmi_msg_handlers);
	if (rc < 0) {
		dev_err(ctrl->dev, "QMI client init failed: %d\n", rc);
		goto qmi_handle_init_failed;
	}
	dev_info(ctrl->dev, "SPX: direct QMI handle init done\n");

	dev_info(ctrl->dev, "SPX: direct QMI connect begin node=%u port=%u\n",
		 ctrl->qmi.svc_info.sq_node, ctrl->qmi.svc_info.sq_port);
	rc = kernel_connect(handle->sock,
				(struct sockaddr_unsized *)&ctrl->qmi.svc_info,
				sizeof(ctrl->qmi.svc_info), 0);
	if (rc < 0) {
		dev_err(ctrl->dev, "Remote Service connect failed: %d\n", rc);
		goto qmi_connect_to_service_failed;
	}
	dev_info(ctrl->dev, "SPX: direct QMI connect done\n");

	/* SPX ADSP firmware accepts hardware instances 0 and 1. The DT-derived
	 * default matches upstream's id >> 1 mapping for slim@1; keep an
	 * override while we determine which instance actually produces SLIMbus
	 * capability traffic on this firmware.
	 */
	if (spx_select_instance >= 0)
		req.instance = spx_select_instance;
	else
		req.instance = ctrl->ngd->id >> 1;
	if (spx_select_mode == SLIMBUS_MODE_SATELLITE_V01 ||
	    spx_select_mode == SLIMBUS_MODE_MASTER_V01) {
		req.mode_valid = 1;
		req.mode = spx_select_mode;
	} else {
		/* Leave the optional field absent and let the ADSP keep its
		 * configured role. With the element order above, setting this
		 * parameter emits the mode TLV before the instance TLV, matching
		 * the userspace QRTR probe shape accepted by the SPX firmware.
		 */
		req.mode_valid = 0;
		if (apps_is_master)
			req.mode = SLIMBUS_MODE_SATELLITE_V01;
		else
			req.mode = SLIMBUS_MODE_MASTER_V01;
	}

	ctrl->qmi.handle = handle;

	for (attempt = 1; attempt <= SLIMBUS_QMI_SELECT_RETRIES; attempt++) {
		rc = qcom_slim_qmi_send_select_inst_req(ctrl, &req);
		if (!rc)
			break;

		dev_err(ctrl->dev,
			"failed to select h/w instance attempt %d/%d ret=%d\n",
			attempt, SLIMBUS_QMI_SELECT_RETRIES, rc);
		if (attempt < SLIMBUS_QMI_SELECT_RETRIES)
			msleep(200);
	}
	if (rc)
		goto qmi_select_instance_failed;

	qcom_slim_ngd_pin_after_qmi(ctrl);

	return 0;

qmi_select_instance_failed:
	ctrl->qmi.handle = NULL;
qmi_connect_to_service_failed:
	qmi_handle_release(handle);
qmi_handle_init_failed:
	devm_kfree(ctrl->dev, handle);
	return rc;
}

static int qcom_slim_qmi_power_request(struct qcom_slim_ngd_ctrl *ctrl,
				       bool active);

static void qcom_slim_qmi_exit(struct qcom_slim_ngd_ctrl *ctrl)
{
	/*
	 * Releasing the QMI client makes the ADSP drop our power vote and
	 * gate the NGD, so no MMIO may happen past this point.
	 */
	WRITE_ONCE(ctrl->mmio_alive, false);

	if (!ctrl->qmi.handle)
		return;

	if (ctrl->qmi.powered) {
		int ret;

		ret = qcom_slim_qmi_power_request(ctrl, false);
		if (ret)
			dev_err(ctrl->dev,
				"SPX: QMI power-off during exit failed:%d\n",
				ret);
	}

	qmi_handle_release(ctrl->qmi.handle);
	devm_kfree(ctrl->dev, ctrl->qmi.handle);
	ctrl->qmi.handle = NULL;
	ctrl->qmi.powered = false;
}

static int qcom_slim_qmi_power_request(struct qcom_slim_ngd_ctrl *ctrl,
				       bool active)
{
	struct slimbus_power_req_msg_v01 req;
	int ret;

	if (active)
		req.pm_req = SLIMBUS_PM_ACTIVE_V01;
	else
		req.pm_req = SLIMBUS_PM_INACTIVE_V01;

	if (spx_power_resp_type >= 0) {
		req.resp_type_valid = 1;
		req.resp_type = spx_power_resp_type;
	} else {
		req.resp_type_valid = 0;
		req.resp_type = SLIMBUS_RESP_SYNCHRONOUS_V01;
	}

	/* Gate the ISR before a power-off can take effect */
	if (!active)
		WRITE_ONCE(ctrl->mmio_alive, false);

	ret = qcom_slim_qmi_send_power_request(ctrl, &req);
	if (!ret) {
		ctrl->qmi.powered = active;
		if (active)
			WRITE_ONCE(ctrl->mmio_alive, true);
	}

	return ret;
}

static u32 *qcom_slim_ngd_tx_msg_get(struct qcom_slim_ngd_ctrl *ctrl, int len,
				     struct completion *comp)
{
	struct qcom_slim_ngd_dma_desc *desc;
	unsigned long flags;

	spin_lock_irqsave(&ctrl->tx_buf_lock, flags);

	if ((ctrl->tx_tail + 1) % QCOM_SLIM_NGD_DESC_NUM == ctrl->tx_head) {
		spin_unlock_irqrestore(&ctrl->tx_buf_lock, flags);
		return NULL;
	}
	desc  = &ctrl->txdesc[ctrl->tx_tail];
	desc->base = ctrl->tx_base + ctrl->tx_tail * SLIM_MSGQ_BUF_LEN;
	desc->comp = comp;
	ctrl->tx_tail = (ctrl->tx_tail + 1) % QCOM_SLIM_NGD_DESC_NUM;

	spin_unlock_irqrestore(&ctrl->tx_buf_lock, flags);

	return desc->base;
}

static void qcom_slim_ngd_tx_msg_dma_cb(void *args)
{
	struct qcom_slim_ngd_dma_desc *desc = args;
	struct qcom_slim_ngd_ctrl *ctrl = desc->ctrl;
	unsigned long flags;

	spin_lock_irqsave(&ctrl->tx_buf_lock, flags);

	if (desc->comp) {
		complete(desc->comp);
		desc->comp = NULL;
	}

	ctrl->tx_head = (ctrl->tx_head + 1) % QCOM_SLIM_NGD_DESC_NUM;
	dev_info(ctrl->dev, "SPX: TX DMA callback phys=%pad head=%u tail=%u\n",
		 &desc->phys, ctrl->tx_head, ctrl->tx_tail);
	spin_unlock_irqrestore(&ctrl->tx_buf_lock, flags);
}

static int qcom_slim_ngd_tx_msg_post(struct qcom_slim_ngd_ctrl *ctrl,
				     void *buf, int len)
{
	struct qcom_slim_ngd_dma_desc *desc;
	unsigned long flags;
	int index, offset;

	spin_lock_irqsave(&ctrl->tx_buf_lock, flags);
	offset = buf - ctrl->tx_base;
	index = offset/SLIM_MSGQ_BUF_LEN;

	desc = &ctrl->txdesc[index];
	desc->phys = ctrl->tx_phys_base + offset;
	desc->base = ctrl->tx_base + offset;
	desc->ctrl = ctrl;
	len = (len + 3) & 0xfc;

	dev_info(ctrl->dev,
		 "SPX: TX desc[%d] prep phys=%pad base=%p len=%d head=%u tail=%u chan_id=%d\n",
		 index, &desc->phys, desc->base, len, ctrl->tx_head,
		 ctrl->tx_tail, ctrl->dma_tx_channel->chan_id);

	desc->desc = dmaengine_prep_slave_single(ctrl->dma_tx_channel,
						desc->phys, len,
						DMA_MEM_TO_DEV,
						DMA_PREP_INTERRUPT);
	if (!desc->desc) {
		dev_err(ctrl->dev, "unable to prepare channel\n");
		spin_unlock_irqrestore(&ctrl->tx_buf_lock, flags);
		return -EINVAL;
	}

	desc->desc->callback = qcom_slim_ngd_tx_msg_dma_cb;
	desc->desc->callback_param = desc;
	desc->desc->cookie = dmaengine_submit(desc->desc);
	dev_info(ctrl->dev, "SPX: TX desc[%d] submitted cookie=%d\n",
		 index, desc->desc->cookie);
	dma_async_issue_pending(ctrl->dma_tx_channel);
	dev_info(ctrl->dev, "SPX: TX desc[%d] issued\n", index);
	spin_unlock_irqrestore(&ctrl->tx_buf_lock, flags);

	return 0;
}

static void qcom_slim_ngd_rx(struct qcom_slim_ngd_ctrl *ctrl, u8 *buf)
{
	u8 mc, mt, len;

	mt = SLIM_HEADER_GET_MT(buf[0]);
	len = SLIM_HEADER_GET_RL(buf[0]);
	mc = SLIM_HEADER_GET_MC(buf[1]);

	if (spx_pio_verbose)
		dev_info(ctrl->dev, "SPX: rx msg mt=0x%x mc=0x%x len=%d\n",
			 mt, mc, len);

	if (mc == SLIM_USR_MC_MASTER_CAPABILITY &&
		mt == SLIM_MSG_MT_SRC_REFERRED_USER)
		queue_work(ctrl->mwq, &ctrl->m_work);

	if (mc == SLIM_MSG_MC_REPLY_INFORMATION ||
	    mc == SLIM_MSG_MC_REPLY_VALUE || (mc == SLIM_USR_MC_ADDR_REPLY &&
	    mt == SLIM_MSG_MT_SRC_REFERRED_USER) ||
		(mc == SLIM_USR_MC_GENERIC_ACK &&
		 mt == SLIM_MSG_MT_SRC_REFERRED_USER)) {
		slim_msg_response(&ctrl->ctrl, &buf[4], buf[3], len - 4);
		pm_runtime_mark_last_busy(ctrl->ctrl.dev);
	}
}

static void qcom_slim_ngd_rx_msgq_cb(void *args)
{
	struct qcom_slim_ngd_dma_desc *desc = args;
	struct qcom_slim_ngd_ctrl *ctrl = desc->ctrl;

	dev_info(ctrl->dev, "SPX: RX DMA callback phys=%pad base=%p\n",
		 &desc->phys, desc->base);

	qcom_slim_ngd_rx(ctrl, (u8 *)desc->base);
	/* Add descriptor back to the queue */
	dev_info(ctrl->dev, "SPX: RX DMA callback requeue phys=%pad\n",
		 &desc->phys);
	desc->desc = dmaengine_prep_slave_single(ctrl->dma_rx_channel,
					desc->phys, SLIM_MSGQ_BUF_LEN,
					DMA_DEV_TO_MEM,
					DMA_PREP_INTERRUPT);
	if (!desc->desc) {
		dev_err(ctrl->dev, "Unable to prepare rx channel\n");
		return;
	}

	desc->desc->callback = qcom_slim_ngd_rx_msgq_cb;
	desc->desc->callback_param = desc;
	desc->desc->cookie = dmaengine_submit(desc->desc);
	dev_info(ctrl->dev, "SPX: RX DMA callback submitted cookie=%d\n",
		 desc->desc->cookie);
	dma_async_issue_pending(ctrl->dma_rx_channel);
	dev_info(ctrl->dev, "SPX: RX DMA callback issued\n");
}

static bool qcom_slim_ngd_poll_rx_msgq(struct qcom_slim_ngd_ctrl *ctrl)
{
	u8 *buf;
	u8 mc, mt, len;
	int i;

	if (!ctrl->rx_base)
		return false;

	for (i = 0; i < QCOM_SLIM_NGD_DESC_NUM; i++) {
		if (ctrl->rx_poll_seen & BIT(i))
			continue;

		buf = ctrl->rx_base + i * SLIM_MSGQ_BUF_LEN;
		mt = SLIM_HEADER_GET_MT(buf[0]);
		len = SLIM_HEADER_GET_RL(buf[0]);
		mc = SLIM_HEADER_GET_MC(buf[1]);

		if (!buf[0] && !buf[1])
			continue;

		ctrl->rx_poll_seen |= BIT(i);
		dev_info(ctrl->dev,
			 "SPX: polled RX desc[%d] mt=0x%x mc=0x%x len=%u first=%*ph\n",
			 i, mt, mc, len, min_t(u8, len + 1, 8), buf);

		qcom_slim_ngd_rx(ctrl, buf);
		return true;
	}

	return false;
}

/*
 * SPX PIO mode: send one fully assembled SLIMbus message by writing it
 * word-by-word into the NGD TX FIFO. Caller holds ctrl->tx_lock. The TX
 * path owns the W1C clears of the TX status bits; the RX poll thread
 * owns NGD_INT_RX_MSG_RCVD, so the two never race on INT_CLR.
 */
static int qcom_slim_ngd_pio_tx(struct qcom_slim_ngd_ctrl *ctrl, u32 *buf,
				int len)
{
	void __iomem *ngd = ctrl->ngd->base;
	int words = DIV_ROUND_UP(len, 4);
	unsigned long timeout;
	u32 stat;
	int i;

	if (!READ_ONCE(ctrl->mmio_alive)) {
		dev_err(ctrl->dev, "SPX: PIO TX refused, NGD MMIO gated\n");
		return -ENODEV;
	}

	stat = readl_relaxed(ngd + NGD_INT_STAT);
	if (stat & (NGD_INT_TX_MSG_SENT | NGD_INT_TX_NACKED_2 |
		    NGD_INT_MSG_TX_INVAL)) {
		dev_info(ctrl->dev, "SPX: PIO TX clearing stale stat=0x%x\n",
			 stat);
		writel_relaxed(stat & (NGD_INT_TX_MSG_SENT |
				       NGD_INT_TX_NACKED_2 |
				       NGD_INT_MSG_TX_INVAL),
			       ngd + NGD_INT_CLR);
	}

	if (!ctrl->pio_tx_fifo_logged) {
		ctrl->pio_tx_fifo_logged = true;
		dev_info(ctrl->dev,
			 "SPX: PIO TX first-ever FIFO write: words=%d w0=0x%08x to child+0x%x\n",
			 words, buf[0], NGD_TX_MSG);
	}

	for (i = 0; i < words; i++)
		writel_relaxed(buf[i], ngd + NGD_TX_MSG + i * 4);
	/* All FIFO words must land before the device acts on the message */
	mb();

	if (spx_pio_tx_nowait) {
		usleep_range(2000, 2500);
		return 0;
	}

	timeout = jiffies + usecs_to_jiffies(SPX_PIO_TX_TOUT_US);
	for (;;) {
		stat = readl_relaxed(ngd + NGD_INT_STAT);
		if (stat & NGD_INT_TX_MSG_SENT) {
			writel_relaxed(NGD_INT_TX_MSG_SENT,
				       ngd + NGD_INT_CLR);
			return 0;
		}
		if (stat & NGD_INT_TX_NACKED_2) {
			writel_relaxed(NGD_INT_TX_NACKED_2,
				       ngd + NGD_INT_CLR);
			dev_err(ctrl->dev, "SPX: PIO TX NACKed stat=0x%x\n",
				stat);
			return -EIO;
		}
		if (stat & (NGD_INT_MSG_TX_INVAL | NGD_INT_DEV_ERR |
			    NGD_INT_MSG_BUF_CONTE)) {
			writel_relaxed(stat & (NGD_INT_MSG_TX_INVAL |
					       NGD_INT_DEV_ERR |
					       NGD_INT_MSG_BUF_CONTE),
				       ngd + NGD_INT_CLR);
			dev_err(ctrl->dev, "SPX: PIO TX error stat=0x%x\n",
				stat);
			return -EINVAL;
		}
		if (time_after(jiffies, timeout)) {
			dev_err(ctrl->dev,
				"SPX: PIO TX_MSG_SENT poll timed out stat=0x%x (try spx_pio_tx_nowait=1)\n",
				stat);
			return -ETIMEDOUT;
		}
		usleep_range(100, 200);
	}
}

/*
 * SPX PIO mode: drain one message from the NGD RX FIFO if RX_MSG_RCVD is
 * latched. Returns true if a message was consumed and another attempt is
 * worthwhile.
 */
static bool qcom_slim_ngd_pio_rx_once(struct qcom_slim_ngd_ctrl *ctrl)
{
	void __iomem *ngd = ctrl->ngd->base;
	u32 w[SLIM_MSGQ_BUF_LEN / 4];
	u32 stat;
	u8 rl;
	int words, i;

	if (!READ_ONCE(ctrl->mmio_alive))
		return false;

	stat = readl_relaxed(ngd + NGD_INT_STAT);
	if (!(stat & NGD_INT_RX_MSG_RCVD))
		return false;

	memset(w, 0, sizeof(w));
	w[0] = readl_relaxed(ngd + NGD_RX_MSG);
	rl = SLIM_HEADER_GET_RL((u8)(w[0] & 0xff));
	/*
	 * The SLIMbus RL field excludes the first header byte. Read the
	 * complete frame from the FIFO, otherwise 4-byte-boundary replies can
	 * leave the TID/reply byte unread and the framework times out.
	 */
	words = clamp(DIV_ROUND_UP((int)rl + 1, 4), 1, 8);
	for (i = 1; i < words; i++)
		w[i] = readl_relaxed(ngd + NGD_RX_MSG + i * 4);
	memcpy(ctrl->pio_last_rx, w, min_t(size_t, sizeof(ctrl->pio_last_rx),
					   words * sizeof(u32)));
	ctrl->pio_last_rx_len = words * sizeof(u32);
	writel_relaxed(NGD_INT_RX_MSG_RCVD, ngd + NGD_INT_CLR);
	/* Settle the FIFO pops and the W1C before the next INT_STAT read */
	mb();

	if (spx_pio_verbose)
		dev_info(ctrl->dev,
			 "SPX: PIO RX stat=0x%x rl=%u words=%d data=%*ph\n",
			 stat, rl, words, words * 4, w);

	if (!rl) {
		ctrl->pio_rx_anomalies++;
		if (ctrl->pio_rx_anomalies >= 3) {
			ctrl->pio_rx_dead = true;
			dev_err(ctrl->dev,
				"SPX: PIO RX disabled after %d zero-length frames\n",
				ctrl->pio_rx_anomalies);
			return false;
		}
		return true;
	}

	ctrl->pio_rx_anomalies = 0;
	qcom_slim_ngd_rx(ctrl, (u8 *)w);
	return true;
}

static int qcom_slim_ngd_pio_thread(void *data)
{
	struct qcom_slim_ngd_ctrl *ctrl = data;
	unsigned long hb_until = jiffies + 30 * HZ;
	unsigned long hb_next = jiffies;
	int n;

	dev_info(ctrl->dev, "SPX: PIO poll thread started\n");

	while (!kthread_should_stop()) {
		if (!READ_ONCE(ctrl->mmio_alive)) {
			msleep(50);
			continue;
		}

		if (!ctrl->pio_rx_dead) {
			for (n = 0; n < 8; n++)
				if (!qcom_slim_ngd_pio_rx_once(ctrl))
					break;
		}

		if (time_before(jiffies, hb_until) &&
		    time_after_eq(jiffies, hb_next)) {
			dev_info(ctrl->dev,
				 "SPX: PIO heartbeat int_stat=0x%x status=0x%x cfg=0x%x\n",
				 readl_relaxed(ctrl->ngd->base + NGD_INT_STAT),
				 readl_relaxed(ctrl->ngd->base + NGD_STATUS),
				 readl_relaxed(ctrl->ngd->base + NGD_CFG));
			hb_next = jiffies + 2 * HZ;
		}

		usleep_range(500, 1500);
	}

	dev_info(ctrl->dev, "SPX: PIO poll thread stopped\n");
	return 0;
}

static int qcom_slim_ngd_pio_wait_for_completion(struct qcom_slim_ngd_ctrl *ctrl,
						 struct completion *comp,
						 struct slim_msg_txn *txn,
						 unsigned long timeout)
{
	unsigned long end = jiffies + timeout;
	u32 stat, status;

	do {
		if (completion_done(comp))
			return 0;

		if (!ctrl->pio_rx_dead)
			qcom_slim_ngd_pio_rx_once(ctrl);

		if (completion_done(comp))
			return 0;

		usleep_range(500, 1000);
	} while (time_before(jiffies, end));

	stat = readl_relaxed(ctrl->ngd->base + NGD_INT_STAT);
	status = readl_relaxed(ctrl->ngd->base + NGD_STATUS);
	dev_err(ctrl->dev,
		"SPX: PIO wait timed out mt=0x%x mc=0x%x la=0x%x tid=%u rl=%u int_stat=0x%x status=0x%x cfg=0x%x rx_dead=%d anomalies=%d last_rx_len=%d last_rx=%*ph\n",
		txn->mt, txn->mc, txn->la, txn->tid, txn->rl, stat, status,
		readl_relaxed(ctrl->ngd->base + NGD_CFG), ctrl->pio_rx_dead,
		ctrl->pio_rx_anomalies, ctrl->pio_last_rx_len,
		min(ctrl->pio_last_rx_len, 16), ctrl->pio_last_rx);

	return -ETIMEDOUT;
}

static void qcom_slim_ngd_pio_start(struct qcom_slim_ngd_ctrl *ctrl)
{
	struct task_struct *t;

	if (ctrl->pio_task)
		return;

	t = kthread_run(qcom_slim_ngd_pio_thread, ctrl, "spx_slim_pio");
	if (IS_ERR(t)) {
		dev_err(ctrl->dev, "SPX: PIO thread start failed:%ld\n",
			PTR_ERR(t));
		return;
	}
	ctrl->pio_task = t;
}

/*
 * SPX PIO mode: wait for the capability exchange (ctrl->reconf) while the
 * poll thread feeds RX. If the master stays quiet, proactively send
 * REPORT_SATELLITE via the existing master worker - downstream has the
 * same capability-retry concept.
 */
static int qcom_slim_ngd_pio_wait_capability(struct qcom_slim_ngd_ctrl *ctrl)
{
	void __iomem *ngd = ctrl->ngd->base;
	unsigned long deadline = jiffies + 5 * HZ;
	unsigned long next_kick = jiffies + msecs_to_jiffies(300);
	unsigned long time_left;
	int kicks = 0;

	while (time_before(jiffies, deadline)) {
		time_left = wait_for_completion_timeout(&ctrl->reconf,
							msecs_to_jiffies(20));
		if (time_left || completion_done(&ctrl->reconf)) {
			dev_info(ctrl->dev,
				 "SPX: PIO capability exchange done status=0x%x int_stat=0x%x\n",
				 readl_relaxed(ngd + NGD_STATUS),
				 readl_relaxed(ngd + NGD_INT_STAT));
			return 0;
		}

		if (kicks < spx_pio_cap_retries &&
		    time_after_eq(jiffies, next_kick)) {
			kicks++;
			dev_info(ctrl->dev,
				 "SPX: PIO proactive REPORT_SATELLITE attempt %d\n",
				 kicks);
			queue_work(ctrl->mwq, &ctrl->m_work);
			next_kick = jiffies + HZ;
		}
	}

	dev_err(ctrl->dev,
		"SPX: PIO capability exchange timed out int_stat=0x%x status=0x%x cfg=0x%x\n",
		readl_relaxed(ngd + NGD_INT_STAT),
		readl_relaxed(ngd + NGD_STATUS),
		readl_relaxed(ngd + NGD_CFG));

	if (spx_pio_debug_reads) {
		dev_info(ctrl->dev,
			 "SPX: reading unverified NGD_IE_STAT child+0x%x / NGD_VE_STAT child+0x%x now\n",
			 NGD_IE_STAT, NGD_VE_STAT);
		dev_info(ctrl->dev, "SPX: IE_STAT=0x%x VE_STAT=0x%x\n",
			 readl_relaxed(ngd + NGD_IE_STAT),
			 readl_relaxed(ngd + NGD_VE_STAT));
	}

	return -ETIMEDOUT;
}

static int qcom_slim_ngd_post_rx_msgq(struct qcom_slim_ngd_ctrl *ctrl,
				      bool issue_pending)
{
	struct qcom_slim_ngd_dma_desc *desc;
	int i;

	dev_info(ctrl->dev, "SPX: posting %u RX DMA descriptors\n",
		 QCOM_SLIM_NGD_DESC_NUM);
	ctrl->rx_poll_seen = 0;
	memset(ctrl->rx_base, 0, QCOM_SLIM_NGD_DESC_NUM * SLIM_MSGQ_BUF_LEN);

	for (i = 0; i < QCOM_SLIM_NGD_DESC_NUM; i++) {
		desc = &ctrl->rx_desc[i];
		desc->phys = ctrl->rx_phys_base + i * SLIM_MSGQ_BUF_LEN;
		desc->ctrl = ctrl;
		desc->base = ctrl->rx_base + i * SLIM_MSGQ_BUF_LEN;
		dev_info(ctrl->dev,
			 "SPX: RX desc[%d] prep phys=%pad base=%p len=%u chan_id=%d\n",
			 i, &desc->phys, desc->base, SLIM_MSGQ_BUF_LEN,
			 ctrl->dma_rx_channel->chan_id);
		desc->desc = dmaengine_prep_slave_single(ctrl->dma_rx_channel,
						desc->phys, SLIM_MSGQ_BUF_LEN,
						DMA_DEV_TO_MEM,
						DMA_PREP_INTERRUPT);
		if (!desc->desc) {
			dev_err(ctrl->dev, "Unable to prepare rx channel\n");
			return -EINVAL;
		}

		desc->desc->callback = qcom_slim_ngd_rx_msgq_cb;
		desc->desc->callback_param = desc;
		desc->desc->cookie = dmaengine_submit(desc->desc);
		dev_info(ctrl->dev, "SPX: RX desc[%d] submitted cookie=%d\n",
			 i, desc->desc->cookie);
	}
	if (!issue_pending) {
		dev_info(ctrl->dev,
			 "SPX: RX DMA descriptors submitted; issue_pending skipped\n");
		return 0;
	}

	dev_info(ctrl->dev, "SPX: issuing pending RX DMA descriptors\n");
	dma_async_issue_pending(ctrl->dma_rx_channel);
	dev_info(ctrl->dev, "SPX: RX DMA descriptors issued\n");

	return 0;
}

static int qcom_slim_ngd_spx_apply_dma_mask(struct qcom_slim_ngd_ctrl *ctrl)
{
	u64 old_mask;
	u64 old_coherent;
	phys_addr_t old_bus_limit;
	u64 mask;
	int ret;

	if (spx_dma_mask_bits <= 0)
		return 0;

	old_mask = dma_get_mask(ctrl->dev);
	old_coherent = ctrl->dev->coherent_dma_mask;
	old_bus_limit = ctrl->dev->bus_dma_limit;
	mask = DMA_BIT_MASK(spx_dma_mask_bits);

	ret = dma_set_mask_and_coherent(ctrl->dev, mask);
	if (ret) {
		dev_err(ctrl->dev,
			"SPX: failed to set SLIM DMA mask bits=%d ret=%d\n",
			spx_dma_mask_bits, ret);
		return ret;
	}

	ctrl->dev->bus_dma_limit = mask;
	dev_info(ctrl->dev,
		 "SPX: SLIM DMA limits bits=%d mask 0x%llx->0x%llx coherent 0x%llx->0x%llx bus 0x%llx->0x%llx before coherent allocation\n",
		 spx_dma_mask_bits,
		 (unsigned long long)old_mask,
		 (unsigned long long)dma_get_mask(ctrl->dev),
		 (unsigned long long)old_coherent,
		 (unsigned long long)ctrl->dev->coherent_dma_mask,
		 (unsigned long long)old_bus_limit,
		 (unsigned long long)ctrl->dev->bus_dma_limit);

	return 0;
}

static int qcom_slim_ngd_init_rx_msgq(struct qcom_slim_ngd_ctrl *ctrl,
				      bool issue_pending)
{
	struct device *dev = ctrl->dev;
	int ret, size;

	dev_info(dev, "SPX: requesting RX DMA channel\n");
	ctrl->dma_rx_channel = dma_request_chan(dev, "rx");
	if (IS_ERR(ctrl->dma_rx_channel)) {
		dev_err(dev, "Failed to request RX dma channel");
		ret = PTR_ERR(ctrl->dma_rx_channel);
		ctrl->dma_rx_channel = NULL;
		return ret;
	}
	dev_info(dev, "SPX: RX DMA channel requested chan=%p chan_id=%d\n",
		 ctrl->dma_rx_channel, ctrl->dma_rx_channel->chan_id);

	size = QCOM_SLIM_NGD_DESC_NUM * SLIM_MSGQ_BUF_LEN;
	dev_info(dev, "SPX: allocating RX DMA buffer size=%d\n", size);
	ret = qcom_slim_ngd_spx_apply_dma_mask(ctrl);
	if (ret)
		goto rel_rx;
	ctrl->rx_base = dma_alloc_coherent(dev, size, &ctrl->rx_phys_base,
					   GFP_KERNEL);
	if (!ctrl->rx_base) {
		ret = -ENOMEM;
		goto rel_rx;
	}
	dev_info(dev, "SPX: RX DMA buffer allocated phys=%pad size=%d\n",
		 &ctrl->rx_phys_base, size);

	ret = qcom_slim_ngd_post_rx_msgq(ctrl, issue_pending);
	if (ret) {
		dev_err(dev, "post_rx_msgq() failed 0x%x\n", ret);
		goto rx_post_err;
	}

	return 0;

rx_post_err:
	dma_free_coherent(dev, size, ctrl->rx_base, ctrl->rx_phys_base);
	ctrl->rx_base = NULL;
	ctrl->rx_phys_base = 0;
rel_rx:
	dma_release_channel(ctrl->dma_rx_channel);
	ctrl->dma_rx_channel = NULL;
	return ret;
}

static int qcom_slim_ngd_init_tx_msgq(struct qcom_slim_ngd_ctrl *ctrl)
{
	struct device *dev = ctrl->dev;
	unsigned long flags;
	int ret = 0;
	int size;

	dev_info(dev, "SPX: requesting TX DMA channel\n");
	ctrl->dma_tx_channel = dma_request_chan(dev, "tx");
	if (IS_ERR(ctrl->dma_tx_channel)) {
		dev_err(dev, "Failed to request TX dma channel");
		ret = PTR_ERR(ctrl->dma_tx_channel);
		ctrl->dma_tx_channel = NULL;
		return ret;
	}
	dev_info(dev, "SPX: TX DMA channel requested chan=%p chan_id=%d\n",
		 ctrl->dma_tx_channel, ctrl->dma_tx_channel->chan_id);

	size = ((QCOM_SLIM_NGD_DESC_NUM + 1) * SLIM_MSGQ_BUF_LEN);
	dev_info(dev, "SPX: allocating TX DMA buffer size=%d\n", size);
	ret = qcom_slim_ngd_spx_apply_dma_mask(ctrl);
	if (ret)
		goto rel_tx;
	ctrl->tx_base = dma_alloc_coherent(dev, size, &ctrl->tx_phys_base,
					   GFP_KERNEL);
	if (!ctrl->tx_base) {
		ret = -EINVAL;
		goto rel_tx;
	}
	dev_info(dev, "SPX: TX DMA buffer allocated phys=%pad size=%d\n",
		 &ctrl->tx_phys_base, size);

	spin_lock_irqsave(&ctrl->tx_buf_lock, flags);
	ctrl->tx_tail = 0;
	ctrl->tx_head = 0;
	dev_info(dev, "SPX: TX ring reset head=%u tail=%u\n",
		 ctrl->tx_head, ctrl->tx_tail);
	spin_unlock_irqrestore(&ctrl->tx_buf_lock, flags);

	return 0;
rel_tx:
	dma_release_channel(ctrl->dma_tx_channel);
	ctrl->dma_tx_channel = NULL;
	return ret;
}

static int qcom_slim_ngd_exit_dma(struct qcom_slim_ngd_ctrl *ctrl);

static int qcom_slim_ngd_init_dma(struct qcom_slim_ngd_ctrl *ctrl)
{
	int ret = 0;

	dev_info(ctrl->dev, "SPX: DMA init start\n");

	dev_info(ctrl->dev, "SPX: DMA init RX phase\n");
	ret = qcom_slim_ngd_init_rx_msgq(ctrl, true);
	if (ret) {
		dev_err(ctrl->dev, "rx dma init failed\n");
		return ret;
	}

	dev_info(ctrl->dev, "SPX: DMA init TX phase\n");
	ret = qcom_slim_ngd_init_tx_msgq(ctrl);
	if (ret) {
		dev_err(ctrl->dev, "tx dma init failed\n");
		qcom_slim_ngd_exit_dma(ctrl);
		return ret;
	}

	dev_info(ctrl->dev, "SPX: DMA init done\n");

	return 0;
}

static int qcom_slim_ngd_spx_dma_probe(struct qcom_slim_ngd_ctrl *ctrl,
				       int step, const char *stage)
{
	struct device *dev = ctrl->dev;
	int ret, size;

	dev_info(dev, "SPX: %s controlled DMA step=%d\n", stage, step);

	switch (step) {
	case 0:
		dev_info(dev, "SPX: %s step 0: no DMA operations\n", stage);
		return 0;
	case 1:
		dev_info(dev, "SPX: %s step 1: requesting RX DMA channel\n",
			 stage);
		ctrl->dma_rx_channel = dma_request_chan(dev, "rx");
		if (IS_ERR(ctrl->dma_rx_channel)) {
			ret = PTR_ERR(ctrl->dma_rx_channel);
			ctrl->dma_rx_channel = NULL;
			dev_err(dev,
				"SPX: %s step 1: RX channel failed:%d\n",
				stage, ret);
			return ret;
		}
		dev_info(dev, "SPX: %s step 1: RX channel=%p chan_id=%d\n",
			 stage, ctrl->dma_rx_channel,
			 ctrl->dma_rx_channel->chan_id);
		dma_release_channel(ctrl->dma_rx_channel);
		ctrl->dma_rx_channel = NULL;
		dev_info(dev, "SPX: %s step 1: RX channel released\n", stage);
		return 0;
	case 2:
		dev_info(dev, "SPX: %s step 2: RX channel + coherent buffer\n",
			 stage);
		ctrl->dma_rx_channel = dma_request_chan(dev, "rx");
		if (IS_ERR(ctrl->dma_rx_channel)) {
			ret = PTR_ERR(ctrl->dma_rx_channel);
			ctrl->dma_rx_channel = NULL;
			dev_err(dev,
				"SPX: %s step 2: RX channel failed:%d\n",
				stage, ret);
			return ret;
		}
		size = QCOM_SLIM_NGD_DESC_NUM * SLIM_MSGQ_BUF_LEN;
		ctrl->rx_base = dma_alloc_coherent(dev, size,
						   &ctrl->rx_phys_base,
						   GFP_KERNEL);
		if (!ctrl->rx_base) {
			dma_release_channel(ctrl->dma_rx_channel);
			ctrl->dma_rx_channel = NULL;
			return -ENOMEM;
		}
		memset(ctrl->rx_base, 0, size);
		dev_info(dev,
			 "SPX: %s step 2: RX buffer phys=%pad size=%d\n",
			 stage, &ctrl->rx_phys_base, size);
		dma_free_coherent(dev, size, ctrl->rx_base,
				  ctrl->rx_phys_base);
		ctrl->rx_base = NULL;
		ctrl->rx_phys_base = 0;
		dma_release_channel(ctrl->dma_rx_channel);
		ctrl->dma_rx_channel = NULL;
		dev_info(dev, "SPX: %s step 2: RX resources released\n",
			 stage);
		return 0;
	case 3:
		dev_info(dev, "SPX: %s step 3: RX descriptor submit without issue_pending\n",
			 stage);
		ret = qcom_slim_ngd_init_rx_msgq(ctrl, false);
		if (ret)
			return ret;
		dev_info(dev, "SPX: %s step 3: RX descriptors submitted without hardware issue\n",
			 stage);
		qcom_slim_ngd_exit_dma(ctrl);
		dev_info(dev, "SPX: %s step 3: RX DMA cleanup done\n",
			 stage);
		return 0;
	case 4:
		dev_info(dev, "SPX: %s step 4: RX descriptor issue_pending\n",
			 stage);
		ret = qcom_slim_ngd_init_rx_msgq(ctrl, true);
		if (ret)
			return ret;
		dev_info(dev, "SPX: %s step 4: RX descriptors issued\n",
			 stage);
		qcom_slim_ngd_exit_dma(ctrl);
		dev_info(dev, "SPX: %s step 4: RX DMA cleanup done\n",
			 stage);
		return 0;
	case 5:
		dev_info(dev, "SPX: %s step 5: full RX+TX DMA init\n", stage);
		ret = qcom_slim_ngd_init_dma(ctrl);
		if (ret)
			return ret;
		dev_info(dev, "SPX: %s step 5: full DMA init done\n", stage);
		qcom_slim_ngd_exit_dma(ctrl);
		dev_info(dev, "SPX: %s step 5: full DMA cleanup done\n",
			 stage);
		return 0;
	default:
		dev_err(dev, "SPX: refusing unknown %s DMA step=%d\n",
			stage, step);
		return -EINVAL;
	}
}

static int qcom_slim_ngd_spx_stage6_probe(struct qcom_slim_ngd_ctrl *ctrl)
{
	return qcom_slim_ngd_spx_dma_probe(ctrl, spx_stage6_step, "stage 6");
}

static irqreturn_t qcom_slim_ngd_interrupt(int irq, void *d)
{
	struct qcom_slim_ngd_ctrl *ctrl = d;
	void __iomem *base = ctrl->ngd->base;
	u32 stat;

	if (!READ_ONCE(ctrl->mmio_alive)) {
		dev_warn_once(ctrl->dev, "Interrupt received while NGD is gated\n");
		return IRQ_NONE;
	}

	if (pm_runtime_suspended(ctrl->ctrl.dev)) {
		dev_warn_once(ctrl->dev, "Interrupt received while suspended\n");
		return IRQ_NONE;
	}

	/*
	 * PIO mode never arms NGD_INT_EN; the poll paths own the W1C status
	 * bits. A spurious IRQ must not clear them or it eats RX/TX events
	 * the pollers are waiting for.
	 */
	if (spx_pio_mode) {
		dev_warn_ratelimited(ctrl->dev,
				     "SPX: unexpected IRQ in PIO mode stat=0x%x (not clearing)\n",
				     readl(base + NGD_INT_STAT));
		return IRQ_NONE;
	}

	stat = readl(base + NGD_INT_STAT);

	if (ctrl->irq_count < 5) {
		ctrl->irq_count++;
		dev_info(ctrl->dev, "SPX: IRQ stat=0x%x (hit %u)\n",
			 stat, ctrl->irq_count);
	}

	/*
	 * Empty status with the line asserted means the interrupt is not
	 * ours (or is stuck). Returning IRQ_NONE lets the spurious-IRQ
	 * detector disable the line instead of storming the CPU to death.
	 */
	if (!stat)
		return IRQ_NONE;

	if ((stat & NGD_INT_MSG_BUF_CONTE) ||
		(stat & NGD_INT_MSG_TX_INVAL) || (stat & NGD_INT_DEV_ERR) ||
		(stat & NGD_INT_TX_NACKED_2)) {
		dev_err(ctrl->dev, "Error Interrupt received 0x%x\n", stat);
	}

	writel(stat, base + NGD_INT_CLR);

	return IRQ_HANDLED;
}

static int qcom_slim_ngd_xfer_msg(struct slim_controller *sctrl,
				  struct slim_msg_txn *txn)
{
	struct qcom_slim_ngd_ctrl *ctrl = dev_get_drvdata(sctrl->dev);
	DECLARE_COMPLETION_ONSTACK(tx_sent);
	DECLARE_COMPLETION_ONSTACK(done);
	int ret, i;
	unsigned long time_left;
	u8 wbuf[SLIM_MSGQ_BUF_LEN];
	u8 rbuf[SLIM_MSGQ_BUF_LEN];
	u32 pio_buf[SLIM_MSGQ_BUF_LEN / 4];
	u32 *pbuf;
	u8 *puc;
	u8 la = txn->la;
	bool usr_msg = false;
	bool tid_msg;

	if (txn->mt == SLIM_MSG_MT_CORE &&
		(txn->mc >= SLIM_MSG_MC_BEGIN_RECONFIGURATION &&
		 txn->mc <= SLIM_MSG_MC_RECONFIGURE_NOW))
		return 0;

	if (txn->dt == SLIM_MSG_DEST_ENUMADDR)
		return -EPROTONOSUPPORT;

	if (txn->msg->num_bytes > SLIM_MSGQ_BUF_LEN ||
			txn->rl > SLIM_MSGQ_BUF_LEN) {
		dev_err(ctrl->dev, "msg exceeds HW limit\n");
		return -EINVAL;
	}

	if (spx_pio_mode) {
		/*
		 * No DMA ring in PIO mode: tx_msg_get would hand out garbage
		 * pointers with tx_base unset, so it must be bypassed.
		 */
		memset(pio_buf, 0, sizeof(pio_buf));
		pbuf = pio_buf;
	} else {
		pbuf = qcom_slim_ngd_tx_msg_get(ctrl, txn->rl, &tx_sent);
		if (!pbuf) {
			dev_err(ctrl->dev, "Message buffer unavailable\n");
			return -ENOMEM;
		}
	}

	if (txn->mt == SLIM_MSG_MT_CORE &&
		(txn->mc == SLIM_MSG_MC_CONNECT_SOURCE ||
		txn->mc == SLIM_MSG_MC_CONNECT_SINK ||
		txn->mc == SLIM_MSG_MC_DISCONNECT_PORT)) {
		txn->mt = SLIM_MSG_MT_DEST_REFERRED_USER;
		switch (txn->mc) {
		case SLIM_MSG_MC_CONNECT_SOURCE:
			txn->mc = SLIM_USR_MC_CONNECT_SRC;
			break;
		case SLIM_MSG_MC_CONNECT_SINK:
			txn->mc = SLIM_USR_MC_CONNECT_SINK;
			break;
		case SLIM_MSG_MC_DISCONNECT_PORT:
			txn->mc = SLIM_USR_MC_DISCONNECT_PORT;
			break;
		default:
			return -EINVAL;
		}

		usr_msg = true;
		i = 0;
		wbuf[i++] = txn->la;
		la = SLIM_LA_MGR;
		wbuf[i++] = txn->msg->wbuf[0];
		if (txn->mc != SLIM_USR_MC_DISCONNECT_PORT)
			wbuf[i++] = txn->msg->wbuf[1];

		txn->comp = &done;
		ret = slim_alloc_txn_tid(sctrl, txn);
		if (ret) {
			dev_err(ctrl->dev, "Unable to allocate TID\n");
			return ret;
		}

		wbuf[i++] = txn->tid;

		txn->msg->num_bytes = i;
		txn->msg->wbuf = wbuf;
		txn->msg->rbuf = rbuf;
		txn->rl = txn->msg->num_bytes + 4;
	}

	/* HW expects length field to be excluded */
	txn->rl--;
	puc = (u8 *)pbuf;
	*pbuf = 0;
	if (txn->dt == SLIM_MSG_DEST_LOGICALADDR) {
		*pbuf = SLIM_MSG_ASM_FIRST_WORD(txn->rl, txn->mt, txn->mc, 0,
				la);
		puc += 3;
	} else {
		*pbuf = SLIM_MSG_ASM_FIRST_WORD(txn->rl, txn->mt, txn->mc, 1,
				la);
		puc += 2;
	}

	if (slim_tid_txn(txn->mt, txn->mc))
		*(puc++) = txn->tid;

	if (slim_ec_txn(txn->mt, txn->mc)) {
		*(puc++) = (txn->ec & 0xFF);
		*(puc++) = (txn->ec >> 8) & 0xFF;
	}

	if (txn->msg && txn->msg->wbuf)
		memcpy(puc, txn->msg->wbuf, txn->msg->num_bytes);

	tid_msg = slim_tid_txn(txn->mt, txn->mc);

	mutex_lock(&ctrl->tx_lock);
	if (spx_pio_mode) {
		ret = qcom_slim_ngd_pio_tx(ctrl, pbuf, txn->rl);
		/*
		 * The PIO FIFO has no DMA ring/backpressure. Keep one
		 * outstanding TID transaction at a time; otherwise concurrent
		 * codec/SoundWire regmap reads overrun the tiny command/reply
		 * path and show up as MC:0x60 timeouts plus SWR FIFO errors.
		 */
		if (ret) {
			mutex_unlock(&ctrl->tx_lock);
			return ret;
		}

		if (usr_msg || tid_msg) {
			struct completion *comp = usr_msg ? &done : txn->comp;

			if (!comp) {
				mutex_unlock(&ctrl->tx_lock);
				return -EINVAL;
			}

			ret = qcom_slim_ngd_pio_wait_for_completion(ctrl, comp,
								    txn, 2 * HZ);
			if (ret) {
				mutex_unlock(&ctrl->tx_lock);
				return ret;
			}

		}

		mutex_unlock(&ctrl->tx_lock);
		return 0;
	} else {
		ret = qcom_slim_ngd_tx_msg_post(ctrl, pbuf, txn->rl);
		if (ret) {
			mutex_unlock(&ctrl->tx_lock);
			return ret;
		}

		time_left = wait_for_completion_timeout(&tx_sent, HZ);
		if (!time_left) {
			dev_err(sctrl->dev, "TX timed out:MC:0x%x,mt:0x%x",
				txn->mc, txn->mt);
			mutex_unlock(&ctrl->tx_lock);
			return -ETIMEDOUT;
		}
	}

	if (usr_msg) {
		time_left = wait_for_completion_timeout(&done, HZ);
		if (!time_left) {
			dev_err(sctrl->dev, "TX timed out:MC:0x%x,mt:0x%x",
				txn->mc, txn->mt);
			mutex_unlock(&ctrl->tx_lock);
			return -ETIMEDOUT;
		}
	}

	mutex_unlock(&ctrl->tx_lock);
	return 0;
}

static int qcom_slim_ngd_xfer_msg_sync(struct slim_controller *ctrl,
				       struct slim_msg_txn *txn)
{
	DECLARE_COMPLETION_ONSTACK(done);
	int ret;
	unsigned long time_left;

	ret = pm_runtime_get_sync(ctrl->dev);
	if (ret < 0)
		goto pm_put;

	txn->comp = &done;

	ret = qcom_slim_ngd_xfer_msg(ctrl, txn);
	if (ret)
		goto pm_put;

	if (txn->comp && completion_done(txn->comp))
		return 0;

	time_left = wait_for_completion_timeout(&done, HZ);
	if (!time_left) {
		dev_err(ctrl->dev, "TX timed out:MC:0x%x,mt:0x%x", txn->mc,
				txn->mt);
		ret = -ETIMEDOUT;
		goto pm_put;
	}
	return 0;

pm_put:
	/*
	 * For TID transactions the runtime-PM put belongs to whoever removes
	 * the tid from the table: a reply racing with this timeout does the
	 * put in slim_msg_response(). Claim the tid here so a late reply
	 * cannot complete() our dead stack frame or double-put.
	 */
	if (txn->tid == 0 || slim_free_txn_tid(ctrl, txn))
		pm_runtime_put(ctrl->dev);

	return ret;
}

static int qcom_slim_calc_coef(struct slim_stream_runtime *rt, int *exp)
{
	struct slim_controller *ctrl = rt->dev->ctrl;
	int coef;

	if (rt->ratem * ctrl->a_framer->superfreq < rt->rate)
		rt->ratem++;

	coef = rt->ratem;
	*exp = 0;

	/*
	 * CRM = Cx(2^E) is the formula we are using.
	 * Here C is the coffecient and E is the exponent.
	 * CRM is the Channel Rate Multiplier.
	 * Coefficeint should be either 1 or 3 and exponenet
	 * should be an integer between 0 to 9, inclusive.
	 */
	while (1) {
		while ((coef & 0x1) != 0x1) {
			coef >>= 1;
			*exp = *exp + 1;
		}

		if (coef <= 3)
			break;

		coef++;
	}

	/*
	 * we rely on the coef value (1 or 3) to set a bit
	 * in the slimbus message packet. This bit is
	 * BIT(5) which is the segment rate coefficient.
	 */
	if (coef == 1) {
		if (*exp > 9)
			return -EIO;
		coef = 0;
	} else {
		if (*exp > 8)
			return -EIO;
		coef = 1;
	}

	return coef;
}

static int qcom_slim_ngd_enable_stream(struct slim_stream_runtime *rt)
{
	struct slim_device *sdev = rt->dev;
	struct slim_controller *ctrl = sdev->ctrl;
	struct slim_val_inf msg =  {0};
	u8 wbuf[SLIM_MSGQ_BUF_LEN];
	u8 rbuf[SLIM_MSGQ_BUF_LEN];
	struct slim_msg_txn txn = {0,};
	int i, ret;

	txn.mt = SLIM_MSG_MT_DEST_REFERRED_USER;
	txn.dt = SLIM_MSG_DEST_LOGICALADDR;
	txn.la = SLIM_LA_MGR;
	txn.ec = 0;
	txn.msg = &msg;
	txn.msg->num_bytes = 0;
	txn.msg->wbuf = wbuf;
	txn.msg->rbuf = rbuf;

	for (i = 0; i < rt->num_ports; i++) {
		struct slim_port *port = &rt->ports[i];

		if (txn.msg->num_bytes == 0) {
			int exp = 0, coef = 0;

			wbuf[txn.msg->num_bytes++] = sdev->laddr;
			wbuf[txn.msg->num_bytes] = rt->bps >> 2 |
						   (port->ch.aux_fmt << 6);

			/* calculate coef dynamically */
			coef = qcom_slim_calc_coef(rt, &exp);
			if (coef < 0) {
				dev_err(&sdev->dev,
				"%s: error calculating coef %d\n", __func__,
									coef);
				return -EIO;
			}

			if (coef)
				wbuf[txn.msg->num_bytes] |= BIT(5);

			txn.msg->num_bytes++;
			wbuf[txn.msg->num_bytes++] = exp << 4 | rt->prot;

			if (rt->prot == SLIM_PROTO_ISO)
				wbuf[txn.msg->num_bytes++] =
						port->ch.prrate |
						SLIM_CHANNEL_CONTENT_FL;
			else
				wbuf[txn.msg->num_bytes++] =  port->ch.prrate;

			ret = slim_alloc_txn_tid(ctrl, &txn);
			if (ret) {
				dev_err(&sdev->dev, "Fail to allocate TID\n");
				return -ENXIO;
			}
			wbuf[txn.msg->num_bytes++] = txn.tid;
		}
		wbuf[txn.msg->num_bytes++] = port->ch.id;
	}

	txn.mc = SLIM_USR_MC_DEF_ACT_CHAN;
	txn.rl = txn.msg->num_bytes + 4;
	ret = qcom_slim_ngd_xfer_msg_sync(ctrl, &txn);
	if (ret) {
		slim_free_txn_tid(ctrl, &txn);
		dev_err(&sdev->dev, "TX timed out:MC:0x%x,mt:0x%x", txn.mc,
				txn.mt);
		return ret;
	}

	txn.mc = SLIM_USR_MC_RECONFIG_NOW;
	txn.msg->num_bytes = 2;
	wbuf[1] = sdev->laddr;
	txn.rl = txn.msg->num_bytes + 4;

	ret = slim_alloc_txn_tid(ctrl, &txn);
	if (ret) {
		dev_err(ctrl->dev, "Fail to allocate TID\n");
		return ret;
	}

	wbuf[0] = txn.tid;
	ret = qcom_slim_ngd_xfer_msg_sync(ctrl, &txn);
	if (ret) {
		slim_free_txn_tid(ctrl, &txn);
		dev_err(&sdev->dev, "TX timed out:MC:0x%x,mt:0x%x", txn.mc,
				txn.mt);
	}

	return ret;
}

static int qcom_slim_ngd_get_laddr(struct slim_controller *ctrl,
				   struct slim_eaddr *ea, u8 *laddr)
{
	struct slim_val_inf msg =  {0};
	u8 failed_ea[6] = {0, 0, 0, 0, 0, 0};
	struct slim_msg_txn txn;
	u8 wbuf[10] = {0};
	u8 rbuf[10] = {0};
	int ret;

	txn.mt = SLIM_MSG_MT_DEST_REFERRED_USER;
	txn.dt = SLIM_MSG_DEST_LOGICALADDR;
	txn.la = SLIM_LA_MGR;
	txn.ec = 0;

	txn.mc = SLIM_USR_MC_ADDR_QUERY;
	txn.rl = 11;
	txn.msg = &msg;
	txn.msg->num_bytes = 7;
	txn.msg->wbuf = wbuf;
	txn.msg->rbuf = rbuf;

	ret = slim_alloc_txn_tid(ctrl, &txn);
	if (ret < 0)
		return ret;

	wbuf[0] = (u8)txn.tid;
	memcpy(&wbuf[1], ea, sizeof(*ea));

	ret = qcom_slim_ngd_xfer_msg_sync(ctrl, &txn);
	if (ret) {
		slim_free_txn_tid(ctrl, &txn);
		return ret;
	}

	if (!memcmp(rbuf, failed_ea, 6))
		return -ENXIO;

	*laddr = rbuf[6];

	return ret;
}

static int qcom_slim_ngd_exit_dma(struct qcom_slim_ngd_ctrl *ctrl)
{
	int rx_size = QCOM_SLIM_NGD_DESC_NUM * SLIM_MSGQ_BUF_LEN;
	int tx_size = (QCOM_SLIM_NGD_DESC_NUM + 1) * SLIM_MSGQ_BUF_LEN;

	if (ctrl->dma_rx_channel) {
		dev_info(ctrl->dev, "SPX: terminating RX DMA channel chan_id=%d\n",
			 ctrl->dma_rx_channel->chan_id);
		dmaengine_terminate_sync(ctrl->dma_rx_channel);
		dev_info(ctrl->dev, "SPX: releasing RX DMA channel chan_id=%d\n",
			 ctrl->dma_rx_channel->chan_id);
		dma_release_channel(ctrl->dma_rx_channel);
		dev_info(ctrl->dev, "SPX: RX DMA channel released\n");
	}

	if (ctrl->dma_tx_channel) {
		dev_info(ctrl->dev, "SPX: terminating TX DMA channel chan_id=%d\n",
			 ctrl->dma_tx_channel->chan_id);
		dmaengine_terminate_sync(ctrl->dma_tx_channel);
		dev_info(ctrl->dev, "SPX: releasing TX DMA channel chan_id=%d\n",
			 ctrl->dma_tx_channel->chan_id);
		dma_release_channel(ctrl->dma_tx_channel);
		dev_info(ctrl->dev, "SPX: TX DMA channel released\n");
	}

	ctrl->dma_tx_channel = ctrl->dma_rx_channel = NULL;

	if (ctrl->rx_base) {
		dev_info(ctrl->dev, "SPX: freeing RX DMA buffer phys=%pad size=%d\n",
			 &ctrl->rx_phys_base, rx_size);
		dma_free_coherent(ctrl->dev, rx_size, ctrl->rx_base,
				  ctrl->rx_phys_base);
		ctrl->rx_base = NULL;
		ctrl->rx_phys_base = 0;
	}

	if (ctrl->tx_base) {
		dev_info(ctrl->dev, "SPX: freeing TX DMA buffer phys=%pad size=%d\n",
			 &ctrl->tx_phys_base, tx_size);
		dma_free_coherent(ctrl->dev, tx_size, ctrl->tx_base,
				  ctrl->tx_phys_base);
		ctrl->tx_base = NULL;
		ctrl->tx_phys_base = 0;
	}

	return 0;
}

static void qcom_slim_ngd_spx_dump_windows(struct qcom_slim_ngd_ctrl *ctrl,
					   const char *tag)
{
	unsigned long child_off;

	if (!spx_dump_windows)
		return;

	dev_info(ctrl->dev,
		 "SPX: %s top window +0x0 cfg=0x%x status=0x%x rx_msgq=0x%x int_en=0x%x int_stat=0x%x\n",
		 tag, readl_relaxed(ctrl->base + NGD_CFG),
		 readl_relaxed(ctrl->base + NGD_STATUS),
		 readl_relaxed(ctrl->base + NGD_RX_MSGQ_CFG),
		 readl_relaxed(ctrl->base + NGD_INT_EN),
		 readl_relaxed(ctrl->base + NGD_INT_STAT));

	child_off = ctrl->ngd->base - ctrl->base;
	if (child_off != 0x1000) {
		dev_info(ctrl->dev,
			 "SPX: %s skipping child window +0x%lx; only +0x1000 is known safe\n",
			 tag, child_off);
		return;
	}

	dev_info(ctrl->dev,
		 "SPX: %s child window +0x%lx cfg=0x%x status=0x%x rx_msgq=0x%x int_en=0x%x int_stat=0x%x\n",
		 tag, child_off, readl_relaxed(ctrl->ngd->base + NGD_CFG),
		 readl_relaxed(ctrl->ngd->base + NGD_STATUS),
		 readl_relaxed(ctrl->ngd->base + NGD_RX_MSGQ_CFG),
		 readl_relaxed(ctrl->ngd->base + NGD_INT_EN),
		 readl_relaxed(ctrl->ngd->base + NGD_INT_STAT));
}

static int qcom_slim_ngd_setup(struct qcom_slim_ngd_ctrl *ctrl)
{
	u32 cfg = readl_relaxed(ctrl->ngd->base);
	int ret;

	dev_info(ctrl->dev, "SPX: setup begin state=%d cfg=0x%x\n",
		 ctrl->state, cfg);

	if (!spx_pio_mode &&
	    (ctrl->state == QCOM_SLIM_NGD_CTRL_DOWN ||
	     ctrl->state == QCOM_SLIM_NGD_CTRL_ASLEEP)) {
		ret = qcom_slim_ngd_init_dma(ctrl);
		if (ret)
			return ret;
	}

	if (spx_pio_mode) {
		/* PIO mode: FIFO messaging, keep both msgq paths disabled */
		cfg &= ~(NGD_CFG_RX_MSGQ_EN | NGD_CFG_TX_MSGQ_EN);
		dev_info(ctrl->dev, "SPX: PIO mode NGD_CFG msgq bits masked\n");
	} else {
		/* By default enable message queues */
		cfg |= NGD_CFG_RX_MSGQ_EN;
		cfg |= NGD_CFG_TX_MSGQ_EN;
	}

	/* Enable NGD if it's not already enabled*/
	if (!(cfg & NGD_CFG_ENABLE))
		cfg |= NGD_CFG_ENABLE;

	dev_info(ctrl->dev, "SPX: writing NGD_CFG=0x%x\n", cfg);
	writel_relaxed(cfg, ctrl->ngd->base);
	dev_info(ctrl->dev,
		 "SPX: NGD_CFG write complete readback=0x%x int_stat=0x%x\n",
		 readl_relaxed(ctrl->ngd->base + NGD_CFG),
		 readl_relaxed(ctrl->ngd->base + NGD_INT_STAT));

	return 0;
}

static int qcom_slim_ngd_power_up(struct qcom_slim_ngd_ctrl *ctrl)
{
	enum qcom_slim_ngd_state cur_state = ctrl->state;
	struct qcom_slim_ngd *ngd = ctrl->ngd;
	u32 laddr, rx_msgq;
	int ret = 0;
	unsigned long time_left;

	if (ctrl->state == QCOM_SLIM_NGD_CTRL_DOWN) {
		time_left = wait_for_completion_timeout(&ctrl->qmi.qmi_comp, HZ);
		if (!time_left)
			return -EREMOTEIO;
	}

	if (ctrl->state == QCOM_SLIM_NGD_CTRL_ASLEEP ||
		ctrl->state == QCOM_SLIM_NGD_CTRL_DOWN) {
		ret = qcom_slim_qmi_power_request(ctrl, true);
		if (ret) {
			dev_err(ctrl->dev, "SLIM QMI power request failed:%d\n",
					ret);
			return ret;
		}
		dev_info(ctrl->dev, "SPX: QMI power-on acked by ADSP\n");
	}

	/*
	 * Start the PIO poll thread before the LADDR-retained early path so
	 * RX dispatch is alive in every post-power state. It gates itself on
	 * mmio_alive.
	 */
	if (spx_pio_mode)
		qcom_slim_ngd_pio_start(ctrl);

	qcom_slim_ngd_spx_dump_windows(ctrl, "full");

	ctrl->ver = readl_relaxed(ctrl->base);
	/* Version info in 16 MSbits */
	ctrl->ver >>= 16;

	laddr = readl_relaxed(ngd->base + NGD_STATUS);
	if (laddr & NGD_LADDR) {
		/*
		 * external MDM restart case where ADSP itself was active framer
		 * For example, modem restarted when playback was active
		 */
		if (cur_state == QCOM_SLIM_NGD_CTRL_AWAKE) {
			dev_info(ctrl->dev, "Subsys restart: ADSP active framer\n");
			return 0;
		}
		return qcom_slim_ngd_setup(ctrl);
	}

	/*
	 * Reinitialize only when registers are not retained or when enumeration
	 * is lost for ngd.
	 */
	reinit_completion(&ctrl->reconf);

	if (spx_pio_mode) {
		dev_info(ctrl->dev,
			 "SPX: PIO mode skipping RX_MSGQ_CFG timeout write\n");
	} else {
		rx_msgq = readl_relaxed(ngd->base + NGD_RX_MSGQ_CFG);
		writel_relaxed(rx_msgq|SLIM_RX_MSGQ_TIMEOUT_VAL,
					ngd->base + NGD_RX_MSGQ_CFG);
	}
	writel_relaxed(readl_relaxed(ngd->base + NGD_INT_STAT),
		       ngd->base + NGD_INT_CLR);
	if (spx_allow_int_en) {
		dev_warn(ctrl->dev,
			 "SPX: unsafe mode: enabling NGD_INT_EN=0x%x\n",
			 (u32)DEF_NGD_INT_MASK);
		writel_relaxed(DEF_NGD_INT_MASK, ngd->base + NGD_INT_EN);
	} else {
		writel_relaxed(0, ngd->base + NGD_INT_EN);
		dev_info(ctrl->dev,
			 "SPX: keeping NGD_INT_EN disabled during power-up\n");
	}

	ret = qcom_slim_ngd_setup(ctrl);
	if (ret)
		return ret;

	dev_info(ctrl->dev, "SPX: NGD ver=0x%x, waiting for capability exchange\n",
		 ctrl->ver);
	if (spx_pio_mode) {
		ret = qcom_slim_ngd_pio_wait_capability(ctrl);
		if (ret)
			return ret;
	} else if (spx_poll_rx && !spx_allow_int_en) {
		unsigned long deadline = jiffies + 5 * HZ;
		bool done = false;

		while (time_before(jiffies, deadline)) {
			time_left = wait_for_completion_timeout(&ctrl->reconf,
								msecs_to_jiffies(20));
			if (time_left || completion_done(&ctrl->reconf)) {
				done = true;
				break;
			}

			qcom_slim_ngd_poll_rx_msgq(ctrl);
		}

		if (!done) {
			dev_err(ctrl->dev,
				"capability exchange timed-out with RX polling\n");
			return -ETIMEDOUT;
		}
	} else {
		time_left = wait_for_completion_timeout(&ctrl->reconf, 5 * HZ);
		if (!time_left) {
			dev_err(ctrl->dev, "capability exchange timed-out\n");
			return -ETIMEDOUT;
		}
	}
	dev_info(ctrl->dev, "SPX: capability exchange DONE\n");

	return 0;
}

static int qcom_slim_ngd_spx_stage7_probe(struct qcom_slim_ngd_ctrl *ctrl)
{
	struct qcom_slim_ngd *ngd = ctrl->ngd;
	unsigned long time_left, deadline;
	u32 cfg, laddr, rx_msgq;
	bool done = false;
	int ret;

	dev_info(ctrl->dev, "SPX: stage 7 controlled power-up step=%d\n",
		 spx_stage7_step);

	if (ctrl->state == QCOM_SLIM_NGD_CTRL_DOWN) {
		time_left = wait_for_completion_timeout(&ctrl->qmi.qmi_comp, HZ);
		if (!time_left) {
			dev_err(ctrl->dev,
				"SPX: stage 7 qmi_comp wait timed out; keeping module pinned\n");
			return 0;
		}
	}

	ret = qcom_slim_qmi_power_request(ctrl, true);
	if (ret) {
		dev_err(ctrl->dev,
			"SPX: stage 7 QMI power request failed:%d; keeping module pinned\n",
			ret);
		return 0;
	}
	dev_info(ctrl->dev, "SPX: stage 7 QMI power-on acked by ADSP\n");

	qcom_slim_ngd_spx_dump_windows(ctrl, "stage7");
	ctrl->ver = readl_relaxed(ctrl->base) >> 16;
	laddr = readl_relaxed(ngd->base + NGD_STATUS);
	dev_info(ctrl->dev,
		 "SPX: stage 7 reads done ver=0x%x status=0x%x cfg=0x%x rx_msgq=0x%x\n",
		 ctrl->ver, laddr, readl_relaxed(ngd->base + NGD_CFG),
		 readl_relaxed(ngd->base + NGD_RX_MSGQ_CFG));
	if (spx_stage7_step <= 0)
		return 0;

	if (spx_pio_mode) {
		if (spx_stage7_step <= 5) {
			dev_info(ctrl->dev,
				 "SPX: stage 7 step %d is a BAM step; nothing to do in PIO mode\n",
				 spx_stage7_step);
			return 0;
		}

		reinit_completion(&ctrl->reconf);
		writel_relaxed(readl_relaxed(ngd->base + NGD_INT_STAT),
			       ngd->base + NGD_INT_CLR);
		writel_relaxed(0, ngd->base + NGD_INT_EN);
		dev_info(ctrl->dev,
			 "SPX: stage 7 PIO: pending interrupts cleared, INT_EN held disabled\n");

		cfg = readl_relaxed(ngd->base + NGD_CFG);
		cfg &= ~(NGD_CFG_RX_MSGQ_EN | NGD_CFG_TX_MSGQ_EN);
		cfg |= NGD_CFG_ENABLE;
		dev_info(ctrl->dev,
			 "SPX: stage 7 PIO writing NGD_CFG=0x%x (enable, msgqs off)\n",
			 cfg);
		writel_relaxed(cfg, ngd->base + NGD_CFG);
		dev_info(ctrl->dev,
			 "SPX: stage 7 PIO NGD_CFG readback=0x%x int_stat=0x%x\n",
			 readl_relaxed(ngd->base + NGD_CFG),
			 readl_relaxed(ngd->base + NGD_INT_STAT));

		qcom_slim_ngd_pio_start(ctrl);

		if (spx_stage7_step == 6) {
			dev_info(ctrl->dev,
				 "SPX: stage 7 PIO observe-only soak (no TX); heartbeat logs follow\n");
			return 0;
		}

		if (!qcom_slim_ngd_pio_wait_capability(ctrl))
			dev_info(ctrl->dev,
				 "SPX: stage 7 PIO capability exchange DONE\n");

		dev_info(ctrl->dev,
			 "SPX: stage 7 PIO final status=0x%x int_stat=0x%x\n",
			 readl_relaxed(ngd->base + NGD_STATUS),
			 readl_relaxed(ngd->base + NGD_INT_STAT));
		return 0;
	}

	if (spx_stage7_step <= 5) {
		ret = qcom_slim_ngd_spx_dma_probe(ctrl, spx_stage7_step,
						  "stage 7");
		if (ret)
			dev_err(ctrl->dev,
				"SPX: stage 7 controlled DMA step failed:%d; keeping module pinned\n",
				ret);
		return 0;
	}

	ret = qcom_slim_ngd_init_dma(ctrl);
	if (ret) {
		dev_err(ctrl->dev,
			"SPX: stage 7 full DMA init failed:%d; keeping module pinned\n",
			ret);
		return 0;
	}
	dev_info(ctrl->dev, "SPX: stage 7 full RX+TX DMA init done\n");

	reinit_completion(&ctrl->reconf);
	rx_msgq = readl_relaxed(ngd->base + NGD_RX_MSGQ_CFG);
	writel_relaxed(rx_msgq | SLIM_RX_MSGQ_TIMEOUT_VAL,
		       ngd->base + NGD_RX_MSGQ_CFG);
	writel_relaxed(readl_relaxed(ngd->base + NGD_INT_STAT),
		       ngd->base + NGD_INT_CLR);
	writel_relaxed(0, ngd->base + NGD_INT_EN);
	dev_info(ctrl->dev,
		 "SPX: stage 7 RX timeout set, pending interrupts cleared, INT_EN held disabled\n");

	cfg = readl_relaxed(ngd->base + NGD_CFG);
	cfg |= NGD_CFG_RX_MSGQ_EN | NGD_CFG_TX_MSGQ_EN | NGD_CFG_ENABLE;
	dev_info(ctrl->dev, "SPX: stage 7 writing NGD_CFG=0x%x\n", cfg);
	writel_relaxed(cfg, ngd->base + NGD_CFG);
	dev_info(ctrl->dev,
		 "SPX: stage 7 NGD_CFG write complete readback=0x%x\n",
		 readl_relaxed(ngd->base + NGD_CFG));
	if (spx_stage7_step <= 6)
		return 0;

	dev_info(ctrl->dev,
		 "SPX: stage 7 waiting for capability exchange with RX polling\n");
	deadline = jiffies + 5 * HZ;
	while (time_before(jiffies, deadline)) {
		time_left = wait_for_completion_timeout(&ctrl->reconf,
							msecs_to_jiffies(20));
		if (time_left || completion_done(&ctrl->reconf)) {
			done = true;
			break;
		}

		qcom_slim_ngd_poll_rx_msgq(ctrl);
	}

	if (!done) {
		dev_err(ctrl->dev,
			"SPX: stage 7 capability exchange timed out; keeping module pinned\n");
		return 0;
	}

	dev_info(ctrl->dev, "SPX: stage 7 capability exchange DONE\n");
	return 0;
}

static void qcom_slim_ngd_notify_slaves(struct qcom_slim_ngd_ctrl *ctrl)
{
	struct slim_device *sbdev;
	struct device_node *node;

	for_each_child_of_node(ctrl->ngd->pdev->dev.of_node, node) {
		sbdev = of_slim_get_device(&ctrl->ctrl, node);
		if (!sbdev)
			continue;

		if (slim_get_logical_addr(sbdev))
			dev_err(ctrl->dev, "Failed to get logical address\n");
		put_device(&sbdev->dev);
	}
}

static void qcom_slim_ngd_master_worker(struct work_struct *work)
{
	struct qcom_slim_ngd_ctrl *ctrl;
	struct slim_msg_txn txn;
	struct slim_val_inf msg = {0};
	int retries = 0;
	u8 wbuf[8];
	int ret = 0;

	ctrl = container_of(work, struct qcom_slim_ngd_ctrl, m_work);
	txn.dt = SLIM_MSG_DEST_LOGICALADDR;
	txn.ec = 0;
	txn.mc = SLIM_USR_MC_REPORT_SATELLITE;
	txn.mt = SLIM_MSG_MT_SRC_REFERRED_USER;
	txn.la = SLIM_LA_MGR;
	wbuf[0] = SAT_MAGIC_LSB;
	wbuf[1] = SAT_MAGIC_MSB;
	wbuf[2] = SAT_MSG_VER;
	wbuf[3] = SAT_MSG_PROT;
	txn.msg = &msg;
	txn.msg->wbuf = wbuf;
	txn.msg->num_bytes = 4;
	txn.rl = 8;

	dev_info(ctrl->dev, "SLIM SAT: Rcvd master capability\n");

capability_retry:
	ret = qcom_slim_ngd_xfer_msg(&ctrl->ctrl, &txn);
	if (!ret) {
		if (ctrl->state >= QCOM_SLIM_NGD_CTRL_ASLEEP)
			complete(&ctrl->reconf);
		else
			dev_err(ctrl->dev, "unexpected state:%d\n",
						ctrl->state);

		if (ctrl->state == QCOM_SLIM_NGD_CTRL_DOWN)
			qcom_slim_ngd_notify_slaves(ctrl);

	} else if (ret == -EIO) {
		dev_err(ctrl->dev, "capability message NACKed, retrying\n");
		if (retries < INIT_MX_RETRIES) {
			msleep(DEF_RETRY_MS);
			retries++;
			goto capability_retry;
		}
	} else {
		dev_err(ctrl->dev, "SLIM: capability TX failed:%d\n", ret);
	}
}

static int qcom_slim_ngd_update_device_status(struct device *dev, void *null)
{
	slim_report_absent(to_slim_device(dev));

	return 0;
}

static int qcom_slim_ngd_runtime_resume(struct device *dev)
{
	struct qcom_slim_ngd_ctrl *ctrl = dev_get_drvdata(dev);
	int ret = 0;

	if (ctrl->removing)
		return 0;

	if (!ctrl->qmi.handle)
		return 0;

	if (ctrl->state >= QCOM_SLIM_NGD_CTRL_ASLEEP)
		ret = qcom_slim_ngd_power_up(ctrl);
	if (ret) {
		/* Did SSR cause this power up failure */
		if (ctrl->state != QCOM_SLIM_NGD_CTRL_DOWN)
			ctrl->state = QCOM_SLIM_NGD_CTRL_ASLEEP;
		else
			dev_err(ctrl->dev, "HW wakeup attempt during SSR\n");
	} else {
		ctrl->state = QCOM_SLIM_NGD_CTRL_AWAKE;
	}

	return ret;
}

static int qcom_slim_ngd_spx_stage_probe(struct qcom_slim_ngd_ctrl *ctrl)
{
	struct qcom_slim_ngd *ngd = ctrl->ngd;
	u32 cfg, rx_msgq, status, ver;
	int ret;

	ret = qcom_slim_qmi_power_request(ctrl, true);
	if (ret) {
		dev_err(ctrl->dev, "SPX: staged QMI power request failed:%d\n",
			ret);
		return ret;
	}

	dev_info(ctrl->dev, "SPX: staged QMI power request acked\n");
	qcom_slim_ngd_spx_dump_windows(ctrl, "staged");

	ver = readl_relaxed(ctrl->base);
	dev_info(ctrl->dev, "SPX: top-level NGD raw version register=0x%x ver=0x%x\n",
		 ver, ver >> 16);
	if (spx_probe_stage == 3)
		return 0;

	status = readl_relaxed(ngd->base + NGD_STATUS);
	cfg = readl_relaxed(ngd->base + NGD_CFG);
	rx_msgq = readl_relaxed(ngd->base + NGD_RX_MSGQ_CFG);
	dev_info(ctrl->dev,
		 "SPX: child NGD read status=0x%x cfg=0x%x rx_msgq_cfg=0x%x\n",
		 status, cfg, rx_msgq);
	if (spx_probe_stage == 4)
		return 0;

	if (spx_probe_stage == 5) {
		reinit_completion(&ctrl->reconf);
		dev_info(ctrl->dev,
			 "SPX: stage 5 controlled write step=%d int_stat=0x%x int_en=0x%x rx_msgq_cfg=0x%x\n",
			 spx_stage5_step,
			 readl_relaxed(ngd->base + NGD_INT_STAT),
			 readl_relaxed(ngd->base + NGD_INT_EN),
			 rx_msgq);

		switch (spx_stage5_step) {
		case 0:
			dev_info(ctrl->dev, "SPX: stage 5 step 0: no writes\n");
			break;
		case 1:
			dev_info(ctrl->dev,
				 "SPX: stage 5 step 1: writing RX_MSGQ_CFG=0x%x\n",
				 rx_msgq | SLIM_RX_MSGQ_TIMEOUT_VAL);
			writel_relaxed(rx_msgq | SLIM_RX_MSGQ_TIMEOUT_VAL,
				       ngd->base + NGD_RX_MSGQ_CFG);
			dev_info(ctrl->dev,
				 "SPX: stage 5 step 1: RX_MSGQ_CFG readback=0x%x\n",
				 readl_relaxed(ngd->base + NGD_RX_MSGQ_CFG));
			break;
		case 2:
			dev_info(ctrl->dev,
				 "SPX: stage 5 step 2: clearing pending INT_STAT=0x%x\n",
				 readl_relaxed(ngd->base + NGD_INT_STAT));
			writel_relaxed(readl_relaxed(ngd->base + NGD_INT_STAT),
				       ngd->base + NGD_INT_CLR);
			dev_info(ctrl->dev,
				 "SPX: stage 5 step 2: INT_STAT readback=0x%x\n",
				 readl_relaxed(ngd->base + NGD_INT_STAT));
			break;
		case 3:
			if (!spx_allow_int_en) {
				dev_err(ctrl->dev,
					"SPX: refusing unsafe stage 5 step 3 without spx_allow_int_en=1\n");
				return -EPERM;
			}
			dev_info(ctrl->dev,
				 "SPX: stage 5 step 3: writing INT_EN=0x%x\n",
				 (u32)DEF_NGD_INT_MASK);
			writel_relaxed(DEF_NGD_INT_MASK, ngd->base + NGD_INT_EN);
			dev_info(ctrl->dev,
				 "SPX: stage 5 step 3: INT_EN readback=0x%x, disabling now\n",
				 readl_relaxed(ngd->base + NGD_INT_EN));
			writel_relaxed(0, ngd->base + NGD_INT_EN);
			dev_info(ctrl->dev,
				 "SPX: stage 5 step 3: INT_EN disabled readback=0x%x\n",
				 readl_relaxed(ngd->base + NGD_INT_EN));
			break;
		default:
			dev_err(ctrl->dev,
				"SPX: refusing unknown stage 5 step=%d\n",
				spx_stage5_step);
			return -EINVAL;
		}

		return 0;
	}

	reinit_completion(&ctrl->reconf);
	writel_relaxed(rx_msgq | SLIM_RX_MSGQ_TIMEOUT_VAL,
		       ngd->base + NGD_RX_MSGQ_CFG);
	writel_relaxed(readl_relaxed(ngd->base + NGD_INT_STAT),
		       ngd->base + NGD_INT_CLR);
	writel_relaxed(0, ngd->base + NGD_INT_EN);
	dev_info(ctrl->dev,
		 "SPX: stage 6: RX timeout set, pending interrupts cleared, INT_EN held disabled\n");

	ret = qcom_slim_ngd_spx_stage6_probe(ctrl);
	if (ret) {
		dev_err(ctrl->dev, "SPX: staged DMA probe failed:%d\n", ret);
		return ret;
	}

	dev_info(ctrl->dev, "SPX: staged DMA probe done\n");

	return 0;
}

static int qcom_slim_ngd_enable(struct qcom_slim_ngd_ctrl *ctrl, bool enable)
{
	if (enable) {
		int ret;

		if (ctrl->removing)
			return -ESHUTDOWN;

		if (spx_probe_stage <= 0) {
			dev_info(ctrl->dev,
				 "SPX: stopping before SLIMbus QMI mutation (spx_probe_stage=%d)\n",
				 spx_probe_stage);
			return 0;
		}

		ret = qcom_slim_qmi_init(ctrl, false);

		if (ret) {
			dev_err(ctrl->dev, "qmi init fail, ret:%d, state:%d\n",
				ret, ctrl->state);
			return ret;
		}
		/* controller state should be in sync with framework state */
		complete(&ctrl->qmi.qmi_comp);

		if (spx_probe_stage <= 1) {
			dev_info(ctrl->dev,
				 "SPX: stopping after QMI select_instance (spx_probe_stage=%d)\n",
				 spx_probe_stage);
			return 0;
		}

		if (spx_probe_stage == 2) {
			ret = qcom_slim_qmi_power_request(ctrl, true);
			if (ret) {
				dev_err(ctrl->dev,
					"SPX: staged QMI power request failed:%d\n",
					ret);
				return ret;
			}
			dev_info(ctrl->dev,
				 "SPX: stopping after QMI power request (spx_probe_stage=2)\n");
			return 0;
		}

		if (spx_probe_stage >= 3 && spx_probe_stage <= 6) {
			if (spx_probe_stage >= 6 && spx_stage6_step > 0 &&
			    !spx_allow_dma) {
				dev_err(ctrl->dev,
					"SPX: refusing unsafe staged DMA step=%d without spx_allow_dma=1\n",
					spx_stage6_step);
				return -EPERM;
			}
			ret = qcom_slim_ngd_spx_stage_probe(ctrl);
			if (ret)
				return ret;

			dev_info(ctrl->dev,
				 "SPX: stopping after staged hardware probe (spx_probe_stage=%d)\n",
				 spx_probe_stage);
			return 0;
		}

			if (spx_probe_stage == 7) {
				if (!spx_allow_dma && !spx_pio_mode) {
					dev_err(ctrl->dev,
						"SPX: refusing stage 7 power-up without spx_allow_dma=1 or spx_pio_mode=1\n");
					return -EPERM;
				}

				ret = qcom_slim_ngd_spx_stage7_probe(ctrl);
				if (ret)
					return ret;

				dev_info(ctrl->dev,
					 "SPX: stopping after controlled stage 7 before SLIM registration\n");
				return 0;
			}

			if (spx_probe_stage < 8) {
				dev_err(ctrl->dev,
					"SPX: refusing unknown probe stage=%d\n",
					spx_probe_stage);
				return -EINVAL;
			}

			if (!spx_allow_dma && !spx_pio_mode) {
				dev_err(ctrl->dev,
					"SPX: refusing full SLIMbus bring-up without spx_allow_dma=1 or spx_pio_mode=1\n");
				return -EPERM;
			}

			if (!spx_allow_full) {
				dev_err(ctrl->dev,
					"SPX: refusing full SLIMbus bring-up without spx_allow_full=1\n");
				return -EPERM;
		}

		if (!pm_runtime_enabled(ctrl->ctrl.dev) ||
			 !pm_runtime_suspended(ctrl->ctrl.dev))
			ret = qcom_slim_ngd_runtime_resume(ctrl->ctrl.dev);
		else
			ret = pm_runtime_resume(ctrl->ctrl.dev);
		if (ret) {
			dev_err(ctrl->dev, "SPX: runtime resume failed:%d\n", ret);
			return ret;
		}

		pm_runtime_mark_last_busy(ctrl->ctrl.dev);
		pm_runtime_put(ctrl->ctrl.dev);

		ret = slim_register_controller(&ctrl->ctrl);
		if (ret) {
			dev_err(ctrl->dev, "error adding slim controller\n");
			return ret;
		}

		ctrl->ctrl_registered = true;
		dev_info(ctrl->dev, "SLIM controller Registered\n");
	} else {
		qcom_slim_qmi_exit(ctrl);
		if (ctrl->ctrl_registered) {
			slim_unregister_controller(&ctrl->ctrl);
			ctrl->ctrl_registered = false;
		}
	}

	return 0;
}

static int qcom_slim_ngd_qmi_new_server(struct qmi_handle *hdl,
					struct qmi_service *service)
{
	struct qcom_slim_ngd_qmi *qmi =
		container_of(hdl, struct qcom_slim_ngd_qmi, svc_event_hdl);
	struct qcom_slim_ngd_ctrl *ctrl =
		container_of(qmi, struct qcom_slim_ngd_ctrl, qmi);

	qmi->svc_info.sq_family = AF_QIPCRTR;
	qmi->svc_info.sq_node = service->node;
	qmi->svc_info.sq_port = service->port;

	complete(&ctrl->qmi_up);

	return 0;
}

static void qcom_slim_ngd_qmi_del_server(struct qmi_handle *hdl,
					 struct qmi_service *service)
{
	struct qcom_slim_ngd_qmi *qmi =
		container_of(hdl, struct qcom_slim_ngd_qmi, svc_event_hdl);
	struct qcom_slim_ngd_ctrl *ctrl =
		container_of(qmi, struct qcom_slim_ngd_ctrl, qmi);

	reinit_completion(&ctrl->qmi_up);
	qmi->svc_info.sq_node = 0;
	qmi->svc_info.sq_port = 0;
}

static const struct qmi_ops qcom_slim_ngd_qmi_svc_event_ops = {
	.new_server = qcom_slim_ngd_qmi_new_server,
	.del_server = qcom_slim_ngd_qmi_del_server,
};

static int qcom_slim_ngd_qmi_svc_event_init(struct qcom_slim_ngd_ctrl *ctrl)
{
	struct qcom_slim_ngd_qmi *qmi = &ctrl->qmi;
	int ret;

	dev_info(ctrl->dev, "SPX: qmi_svc_event_init: qmi_handle_init begin max_len=%u\n",
		 SLIMBUS_QMI_POWER_REQ_MAX_MSG_LEN);
	ret = qmi_handle_init(&qmi->svc_event_hdl,
				SLIMBUS_QMI_POWER_REQ_MAX_MSG_LEN,
				&qcom_slim_ngd_qmi_svc_event_ops, NULL);
	if (ret < 0) {
		dev_err(ctrl->dev, "qmi_handle_init failed: %d\n", ret);
		return ret;
	}
	dev_info(ctrl->dev, "SPX: qmi_svc_event_init: qmi_handle_init done\n");

	dev_info(ctrl->dev,
		 "SPX: qmi_svc_event_init: qmi_add_lookup begin svc=0x%x v=%u inst=%u\n",
		 SLIMBUS_QMI_SVC_ID, SLIMBUS_QMI_SVC_V1, SLIMBUS_QMI_INS_ID);
	ret = qmi_add_lookup(&qmi->svc_event_hdl, SLIMBUS_QMI_SVC_ID,
			SLIMBUS_QMI_SVC_V1, SLIMBUS_QMI_INS_ID);
	if (ret < 0) {
		dev_err(ctrl->dev, "qmi_add_lookup failed: %d\n", ret);
		qmi_handle_release(&qmi->svc_event_hdl);
		return ret;
	}
	dev_info(ctrl->dev, "SPX: qmi_svc_event_init: qmi_add_lookup done\n");

	ctrl->qmi_svc_event_active = true;
	return 0;
}

static void qcom_slim_ngd_qmi_svc_event_deinit(struct qcom_slim_ngd_ctrl *ctrl)
{
	if (!ctrl->qmi_svc_event_active)
		return;

	qmi_handle_release(&ctrl->qmi.svc_event_hdl);
	ctrl->qmi_svc_event_active = false;
}

static struct platform_driver qcom_slim_ngd_driver;
#define QCOM_SLIM_NGD_DRV_NAME	"qcom,slim-ngd"

static const struct of_device_id qcom_slim_ngd_dt_match[] = {
	{
		.compatible = "qcom,slim-ngd-v1.5.0",
		.data = &ngd_v1_5_offset_info,
	},{
		.compatible = "qcom,slim-ngd-v2.1.0",
		.data = &ngd_v1_5_offset_info,
	},
	{}
};

MODULE_DEVICE_TABLE(of, qcom_slim_ngd_dt_match);

static void qcom_slim_ngd_down(struct qcom_slim_ngd_ctrl *ctrl)
{
	cancel_work_sync(&ctrl->ngd_up_work);
	atomic_set(&ctrl->ngd_up_work_pending, 0);
	mutex_lock(&ctrl->ssr_lock);
	device_for_each_child(ctrl->ctrl.dev, NULL,
			      qcom_slim_ngd_update_device_status);
	qcom_slim_ngd_enable(ctrl, false);
	mutex_unlock(&ctrl->ssr_lock);
}

static void qcom_slim_ngd_up_worker(struct work_struct *work)
{
	struct qcom_slim_ngd_ctrl *ctrl;

	ctrl = container_of(work, struct qcom_slim_ngd_ctrl, ngd_up_work);

	if (ctrl->removing)
		return;

	/* Make sure qmi service is up before continuing */
	if (!wait_for_completion_interruptible_timeout(&ctrl->qmi_up,
						       msecs_to_jiffies(MSEC_PER_SEC))) {
		dev_err(ctrl->dev, "QMI wait timeout\n");
		return;
	}

	mutex_lock(&ctrl->ssr_lock);
	if (!ctrl->removing)
		qcom_slim_ngd_enable(ctrl, true);
	mutex_unlock(&ctrl->ssr_lock);
}

static int qcom_slim_ngd_ssr_pdr_notify(struct qcom_slim_ngd_ctrl *ctrl,
					unsigned long action)
{
	switch (action) {
	case QCOM_SSR_BEFORE_SHUTDOWN:
	case SERVREG_SERVICE_STATE_DOWN:
		if (ctrl->state != QCOM_SLIM_NGD_CTRL_DOWN) {
			pm_runtime_get_noresume(ctrl->ctrl.dev);
			ctrl->state = QCOM_SLIM_NGD_CTRL_DOWN;
			qcom_slim_ngd_down(ctrl);
			qcom_slim_ngd_exit_dma(ctrl);
		}
		break;
	case QCOM_SSR_AFTER_POWERUP:
	case SERVREG_SERVICE_STATE_UP:
		if (!spx_pdr_auto_enable)
			break;
		if (ctrl->removing)
			break;
		if (work_busy(&ctrl->ngd_up_work))
			break;
		if (!atomic_xchg(&ctrl->ngd_up_work_pending, 1))
			schedule_work(&ctrl->ngd_up_work);
		break;
	default:
		break;
	}

	return NOTIFY_OK;
}

static int qcom_slim_ngd_ssr_notify(struct notifier_block *nb,
				    unsigned long action,
				    void *data)
{
	struct qcom_slim_ngd_ctrl *ctrl = container_of(nb,
					       struct qcom_slim_ngd_ctrl, nb);

	return qcom_slim_ngd_ssr_pdr_notify(ctrl, action);
}

static void slim_pd_status(int state, char *svc_path, void *priv)
{
	struct qcom_slim_ngd_ctrl *ctrl = (struct qcom_slim_ngd_ctrl *)priv;

	qcom_slim_ngd_ssr_pdr_notify(ctrl, state);
}
static int of_qcom_slim_ngd_register(struct device *parent,
				     struct qcom_slim_ngd_ctrl *ctrl)
{
	const struct ngd_reg_offset_data *data;
	struct qcom_slim_ngd *ngd;
	const struct of_device_id *match;
	u32 id;
	int ret;

	match = of_match_node(qcom_slim_ngd_dt_match, parent->of_node);
	data = match->data;
	for_each_available_child_of_node_scoped(parent->of_node, node) {
		if (of_property_read_u32(node, "reg", &id))
			continue;

		ngd = kzalloc_obj(*ngd);
		if (!ngd)
			return -ENOMEM;

		ngd->pdev = platform_device_alloc(QCOM_SLIM_NGD_DRV_NAME, id);
		if (!ngd->pdev) {
			kfree(ngd);
			return -ENOMEM;
		}
		ngd->id = id;
		ngd->pdev->dev.parent = parent;

		ret = device_set_driver_override(&ngd->pdev->dev,
						 QCOM_SLIM_NGD_DRV_NAME);
		if (ret) {
			platform_device_put(ngd->pdev);
			kfree(ngd);
			return ret;
		}
		platform_device_set_of_node(ngd->pdev, node);
		ctrl->ngd = ngd;

		ngd->base = ctrl->base + ngd->id * data->offset +
					(ngd->id - 1) * data->size;

		ret = platform_device_add(ngd->pdev);
		if (ret) {
			platform_device_put(ngd->pdev);
			kfree(ngd);
			return ret;
		}

		return 0;
	}

	return -ENODEV;
}

static void qcom_slim_ngd_unregister(struct qcom_slim_ngd_ctrl *ctrl)
{
	struct qcom_slim_ngd *ngd = ctrl->ngd;

	platform_device_del(ngd->pdev);
}

static int qcom_slim_ngd_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct qcom_slim_ngd_ctrl *ctrl = dev_get_drvdata(dev->parent);
	long time_left;
	int ret;

	dev_info(dev,
		 "SPX: child probe entry stage=%d stage7=%d allow_dma=%d bam_stop unavailable-here\n",
		 spx_probe_stage, spx_stage7_step, spx_allow_dma);
	ctrl->ctrl.dev = dev;

	platform_set_drvdata(pdev, ctrl);
	dev_info(dev, "SPX: child probe: runtime PM setup begin\n");
	pm_runtime_use_autosuspend(dev);
	pm_runtime_set_autosuspend_delay(dev, 100);
	pm_runtime_set_suspended(dev);
	pm_runtime_enable(dev);
	pm_runtime_get_noresume(dev);
	dev_info(dev, "SPX: child probe: runtime PM setup done\n");

	if (spx_qmi_bypass_lookup) {
		if (spx_qmi_node < 0 || spx_qmi_port < 0) {
			dev_err(dev,
				"SPX: qmi bypass requires spx_qmi_node/spx_qmi_port, got node=%d port=%d\n",
				spx_qmi_node, spx_qmi_port);
			ret = -EINVAL;
			goto qmi_bypass_err;
		}

		ctrl->qmi.svc_info.sq_family = AF_QIPCRTR;
		ctrl->qmi.svc_info.sq_node = spx_qmi_node;
		ctrl->qmi.svc_info.sq_port = spx_qmi_port;
		dev_warn(dev,
			 "SPX: bypassing QMI service lookup; using node=%u port=%u\n",
			 ctrl->qmi.svc_info.sq_node,
			 ctrl->qmi.svc_info.sq_port);
		complete_all(&ctrl->qmi_up);
	} else {
		dev_info(dev, "SPX: child probe: QMI service-event init begin\n");
		ret = qcom_slim_ngd_qmi_svc_event_init(ctrl);
		if (ret) {
			dev_err(&pdev->dev, "SPX: QMI service registration failed:%d (returning -EPROBE_DEFER)\n", ret);
			/*
			 * SPX: any non-zero return from the QMI service-event init is
			 * a transient condition (QRTR not up, ADSP-side service not yet
			 * published, etc.). Returning -EPROBE_DEFER lets the kernel
			 * re-probe us cleanly instead of leaving SLIMbus silently dead.
			 */
			ret = -EPROBE_DEFER;
			goto qmi_bypass_err;
		}
		dev_info(dev, "SPX: child probe: QMI service-event init done\n");
	}

	if (!spx_pdr_auto_enable) {
		/*
		 * SPX: the wait is 5s (was 1s) so a transient QRTR hiccup has
		 * time to recover, and on timeout the WARN below leaves a
		 * marker pointing at the new_server callback so the next hang
		 * produces a stack trace even if pstore is broken.
		 */
		if (spx_qmi_bypass_lookup) {
			time_left = 5 * MSEC_PER_SEC;
			dev_info(dev,
				 "SPX: child probe: qmi_up wait skipped by bypass\n");
		} else {
			dev_info(dev, "SPX: child probe: waiting for qmi_up completion\n");
			time_left = wait_for_completion_interruptible_timeout(&ctrl->qmi_up,
									      msecs_to_jiffies(5 * MSEC_PER_SEC));
		}
		if (time_left <= 0) {
			ret = time_left ?: -ETIMEDOUT;
			dev_err(&pdev->dev,
				"SPX: QMI wait before staged probe failed:%d; new_server=%ps qmi_up=%ps\n",
				ret,
				qcom_slim_ngd_qmi_new_server,
				&ctrl->qmi_up);
			WARN(1, "SPX: SLIMbus QMI service did not appear in 5s; new_server callback at %ps was never invoked. Check LPASS_AHB_CLOCK vote and QRTR-to-ADSP edge state.\n",
			     qcom_slim_ngd_qmi_new_server);
			goto staged_err;
		}
		dev_info(dev, "SPX: child probe: qmi_up completed time_left=%ld\n",
			 time_left);

		dev_info(dev, "SPX: child probe: enable begin\n");
		mutex_lock(&ctrl->ssr_lock);
		ret = qcom_slim_ngd_enable(ctrl, true);
		mutex_unlock(&ctrl->ssr_lock);
		if (ret)
			goto staged_err;
		dev_info(dev, "SPX: child probe: enable done\n");
	}

	return 0;
qmi_bypass_err:
	pm_runtime_put_noidle(dev);
	pm_runtime_dont_use_autosuspend(dev);
	pm_runtime_disable(dev);
	return ret;
staged_err:
	qcom_slim_ngd_enable(ctrl, false);
	qcom_slim_ngd_exit_dma(ctrl);
	cancel_work_sync(&ctrl->ngd_up_work);
	cancel_work_sync(&ctrl->m_work);
	qcom_slim_ngd_qmi_svc_event_deinit(ctrl);
	goto qmi_bypass_err;
}

static int qcom_slim_ngd_ctrl_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct qcom_slim_ngd_ctrl *ctrl;
	int irq;
	int ret;
	struct pdr_service *pds;

	ctrl = devm_kzalloc(dev, sizeof(*ctrl), GFP_KERNEL);
	if (!ctrl)
		return -ENOMEM;

	dev_set_drvdata(dev, ctrl);

	ctrl->base = devm_platform_get_and_ioremap_resource(pdev, 0, NULL);
	if (IS_ERR(ctrl->base))
		return PTR_ERR(ctrl->base);

	irq = platform_get_irq(pdev, 0);
	if (irq < 0)
		return irq;

	ret = devm_request_irq(dev, irq, qcom_slim_ngd_interrupt,
			       IRQF_TRIGGER_HIGH | IRQF_NO_AUTOEN,
			       "slim-ngd", ctrl);
	if (ret)
		return dev_err_probe(&pdev->dev, ret, "request IRQ failed\n");

	ctrl->dev = dev;
	ctrl->framer.rootfreq = SLIM_ROOT_FREQ >> 3;
	ctrl->framer.superfreq =
		ctrl->framer.rootfreq / SLIM_CL_PER_SUPERFRAME_DIV8;

	ctrl->ctrl.a_framer = &ctrl->framer;
	ctrl->ctrl.clkgear = SLIM_MAX_CLK_GEAR;
	ctrl->ctrl.get_laddr = qcom_slim_ngd_get_laddr;
	ctrl->ctrl.enable_stream = qcom_slim_ngd_enable_stream;
	ctrl->ctrl.xfer_msg = qcom_slim_ngd_xfer_msg;
	ctrl->ctrl.wakeup = NULL;
	ctrl->state = QCOM_SLIM_NGD_CTRL_DOWN;
	ctrl->removing = false;
	ctrl->qmi_svc_event_active = false;

	mutex_init(&ctrl->tx_lock);
	mutex_init(&ctrl->ssr_lock);
	spin_lock_init(&ctrl->tx_buf_lock);
	atomic_set(&ctrl->ngd_up_work_pending, 0);
	init_completion(&ctrl->reconf);
	init_completion(&ctrl->qmi.qmi_comp);
	init_completion(&ctrl->qmi_up);

	INIT_WORK(&ctrl->m_work, qcom_slim_ngd_master_worker);
	INIT_WORK(&ctrl->ngd_up_work, qcom_slim_ngd_up_worker);

	ctrl->mwq = create_singlethread_workqueue("ngd_master");
	if (!ctrl->mwq)
		return dev_err_probe(dev, -ENOMEM, "Failed to start master worker\n");

	ctrl->pdr = pdr_handle_alloc(slim_pd_status, ctrl);
	if (IS_ERR(ctrl->pdr)) {
		ret = dev_err_probe(dev, PTR_ERR(ctrl->pdr), "Failed to init PDR handle\n");
		goto err_destroy_mwq;
	}

	ret = of_qcom_slim_ngd_register(dev, ctrl);
	if (ret)
		goto err_pdr_release;

	pds = pdr_add_lookup(ctrl->pdr, "avs/audio", "msm/adsp/audio_pd");
	if (IS_ERR(pds) && PTR_ERR(pds) != -EALREADY) {
		ret = dev_err_probe(dev, PTR_ERR(pds), "pdr add lookup failed\n");
		goto err_unregister_ngd;
	}

	ctrl->nb.notifier_call = qcom_slim_ngd_ssr_notify;
	ctrl->notifier = qcom_register_ssr_notifier("lpass", &ctrl->nb);
	if (IS_ERR(ctrl->notifier)) {
		ret = PTR_ERR(ctrl->notifier);
		goto err_unregister_ngd;
	}

	enable_irq(irq);

	return 0;

err_unregister_ngd:
	qcom_slim_ngd_unregister(ctrl);
err_pdr_release:
	pdr_handle_release(ctrl->pdr);
err_destroy_mwq:
	destroy_workqueue(ctrl->mwq);

	return ret;
}

static void qcom_slim_ngd_ctrl_remove(struct platform_device *pdev)
{
	struct qcom_slim_ngd_ctrl *ctrl = platform_get_drvdata(pdev);

	ctrl->removing = true;
	pdr_handle_release(ctrl->pdr);
	qcom_unregister_ssr_notifier(ctrl->notifier, &ctrl->nb);
	cancel_work_sync(&ctrl->ngd_up_work);
	cancel_work_sync(&ctrl->m_work);
	if (ctrl->pio_task)
		kthread_stop(ctrl->pio_task);
	qcom_slim_ngd_unregister(ctrl);
	destroy_workqueue(ctrl->mwq);
}

static void qcom_slim_ngd_remove(struct platform_device *pdev)
{
	struct qcom_slim_ngd_ctrl *ctrl = platform_get_drvdata(pdev);

	pm_runtime_dont_use_autosuspend(&pdev->dev);
	pm_runtime_disable(&pdev->dev);
	qcom_slim_ngd_enable(ctrl, false);
	qcom_slim_ngd_exit_dma(ctrl);
	qcom_slim_ngd_qmi_svc_event_deinit(ctrl);

	kfree(ctrl->ngd);
	ctrl->ngd = NULL;
}

static int __maybe_unused qcom_slim_ngd_runtime_idle(struct device *dev)
{
	struct qcom_slim_ngd_ctrl *ctrl = dev_get_drvdata(dev);

	if (ctrl->state == QCOM_SLIM_NGD_CTRL_AWAKE)
		ctrl->state = QCOM_SLIM_NGD_CTRL_IDLE;
	pm_request_autosuspend(dev);
	return -EAGAIN;
}

static int __maybe_unused qcom_slim_ngd_runtime_suspend(struct device *dev)
{
	struct qcom_slim_ngd_ctrl *ctrl = dev_get_drvdata(dev);

	/*
	 * SPX HACK: never power down the SLIMbus core. On the Surface Pro X
	 * the MSFT ADSP firmware collapses the SLIMbus core on the QMI
	 * power-off request, and any in-flight register access then wedges
	 * the CPU on the bus (unrecoverable NoC stall). Keep it powered.
	 */
	dev_info(ctrl->dev, "SPX: runtime suspend skipped (keeping core on)\n");
	return -EBUSY;
}

static const struct dev_pm_ops qcom_slim_ngd_dev_pm_ops = {
	SET_SYSTEM_SLEEP_PM_OPS(pm_runtime_force_suspend,
				pm_runtime_force_resume)
	SET_RUNTIME_PM_OPS(
		qcom_slim_ngd_runtime_suspend,
		qcom_slim_ngd_runtime_resume,
		qcom_slim_ngd_runtime_idle
	)
};

static struct platform_driver qcom_slim_ngd_ctrl_driver = {
	.probe = qcom_slim_ngd_ctrl_probe,
	.remove = qcom_slim_ngd_ctrl_remove,
	.driver	= {
		.name = "qcom,slim-ngd-ctrl",
		.of_match_table = qcom_slim_ngd_dt_match,
	},
};

static struct platform_driver qcom_slim_ngd_driver = {
	.probe = qcom_slim_ngd_probe,
	.remove = qcom_slim_ngd_remove,
	.driver	= {
		.name = QCOM_SLIM_NGD_DRV_NAME,
		.pm = &qcom_slim_ngd_dev_pm_ops,
	},
};

static int qcom_slim_ngd_init(void)
{
	int ret;

	ret = platform_driver_register(&qcom_slim_ngd_driver);
	if (ret)
		return ret;

	ret = platform_driver_register(&qcom_slim_ngd_ctrl_driver);
	if (ret)
		platform_driver_unregister(&qcom_slim_ngd_driver);

	return ret;
}

static void qcom_slim_ngd_exit(void)
{
	platform_driver_unregister(&qcom_slim_ngd_ctrl_driver);
	platform_driver_unregister(&qcom_slim_ngd_driver);
}

module_init(qcom_slim_ngd_init);
module_exit(qcom_slim_ngd_exit);
MODULE_LICENSE("GPL v2");
MODULE_DESCRIPTION("Qualcomm SLIMBus NGD controller");
