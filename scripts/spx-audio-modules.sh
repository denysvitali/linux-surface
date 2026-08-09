#!/bin/sh
# SPDX-License-Identifier: GPL-2.0

set -eu

ADSP_STATE=/sys/class/remoteproc/remoteproc1/state

i=0
while [ "$(cat "$ADSP_STATE" 2>/dev/null || true)" != "running" ]; do
	i=$((i + 1))
	if [ "$i" -ge 60 ]; then
		echo "SPX audio: ADSP did not reach running state" >&2
		exit 1
	fi
	sleep 0.5
done

modprobe slim_qcom_ngd_ctrl
modprobe wcd934x
modprobe snd_soc_wcd934x
modprobe snd_soc_sdm845

i=0
while ! grep -q "Surface Pro X" /proc/asound/cards 2>/dev/null; do
	i=$((i + 1))
	if [ "$i" -ge 40 ]; then
		echo "SPX audio: sound card did not register" >&2
		exit 1
	fi
	sleep 0.25
done

echo "SPX audio: sound card registered"
