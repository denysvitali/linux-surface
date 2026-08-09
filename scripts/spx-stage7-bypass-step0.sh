#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# Run the Surface Pro X SLIMbus stage-7 step-0 diagnostic while bypassing
# QMI service lookup. This uses the previously observed SLIMbus QMI endpoint
# and stops before any DMA channel allocation.

set -eu

SPX_QMI_NODE="${SPX_QMI_NODE:-5}"
SPX_QMI_PORT="${SPX_QMI_PORT:-11}"

if lsmod | grep -q '^slim_qcom_ngd_ctrl '; then
	echo "slim_qcom_ngd_ctrl is already loaded; reboot before this test" >&2
	exit 1
fi

echo "SPX: running bypass stage7 step0 with node=$SPX_QMI_NODE port=$SPX_QMI_PORT"

exec sudo modprobe -v slim_qcom_ngd_ctrl \
	spx_qmi_bypass_lookup=1 \
	spx_qmi_node="$SPX_QMI_NODE" \
	spx_qmi_port="$SPX_QMI_PORT" \
	spx_probe_stage=7 \
	spx_allow_dma=1 \
	spx_stage7_step=0
