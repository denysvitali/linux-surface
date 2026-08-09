#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# Run the Surface Pro X SLIMbus stage-7 step-4 DMA-mask diagnostic.
# This must be run from a clean boot before slim_qcom_ngd_ctrl is loaded.

set -eu

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

echo "SPX: running stage7 step4 with DMA bits=$SPX_DMA_BITS BAM start_stop=$SPX_BAM_START_STOP"

exec sudo modprobe -v slim_qcom_ngd_ctrl \
	spx_dma_mask_bits="$SPX_DMA_BITS" \
	spx_probe_stage=7 \
	spx_allow_dma=1 \
	spx_stage7_step=4
