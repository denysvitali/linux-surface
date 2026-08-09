#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# Run the Surface Pro X SLIMbus stage-7 step-4 DMA diagnostic while
# bypassing QMI service lookup. Defaults to the safe BAM stop=2 path,
# which queues RX descriptors but skips the final EVNT_REG write.

set -eu

SPX_QMI_NODE="${SPX_QMI_NODE:-5}"
SPX_QMI_PORT="${SPX_QMI_PORT:-11}"
SPX_DMA_BITS="${SPX_DMA_BITS:-31}"
SPX_BAM_START_STOP="${SPX_BAM_START_STOP:-2}"

if lsmod | grep -q '^slim_qcom_ngd_ctrl '; then
	echo "slim_qcom_ngd_ctrl is already loaded; reboot before this test" >&2
	exit 1
fi

if [ ! -e /sys/module/bam_dma/parameters/spx_bam_dma_mask_bits ]; then
	echo "missing bam_dma.spx_bam_dma_mask_bits; boot the diagnostic kernel first" >&2
	exit 1
fi

echo "$SPX_DMA_BITS" | sudo tee /sys/module/bam_dma/parameters/spx_bam_dma_mask_bits >/dev/null
echo "$SPX_BAM_START_STOP" | sudo tee /sys/module/bam_dma/parameters/spx_bam_start_stop >/dev/null

echo "SPX: running bypass stage7 step4 with node=$SPX_QMI_NODE port=$SPX_QMI_PORT DMA bits=$SPX_DMA_BITS BAM start_stop=$SPX_BAM_START_STOP"

exec sudo modprobe -v slim_qcom_ngd_ctrl \
	spx_qmi_bypass_lookup=1 \
	spx_qmi_node="$SPX_QMI_NODE" \
	spx_qmi_port="$SPX_QMI_PORT" \
	spx_dma_mask_bits="$SPX_DMA_BITS" \
	spx_probe_stage=7 \
	spx_allow_dma=1 \
	spx_stage7_step=4
