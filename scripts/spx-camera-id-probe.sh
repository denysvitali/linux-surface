#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Safely identify one non-front Surface Pro X camera without a reboot.

set -eu

D=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TARGET=${1:-}
LOG=/var/log/spx-camera-id-$TARGET.log

case "$TARGET" in
	rear|ir) ;;
	*)
		echo "usage: $0 rear|ir" >&2
		exit 2
		;;
esac

if [ ! -d /proc/device-tree/soc@0/cci@ac4a000/i2c-bus@0 ]; then
	echo "refusing: the booted DT has no ac4a000 CCI bus 0" >&2
	exit 1
fi

if [ ! -e "$D/drivers/spx_extras/spx_camera_id.ko" ]; then
	echo "refusing: build drivers/spx_extras/spx_camera_id.ko first" >&2
	exit 1
fi

echo "Probing $TARGET only; no bus sweep and no normal reboot."
echo "A 30-second in-kernel emergency-reboot watchdog is active only during insmod."

# The probe returns -EAGAIN by design after restoring reset, MCLK and every
# rail, so insmod's nonzero status is expected. Preserve its kernel log.
BEFORE=$(sudo dmesg | wc -l)
sudo insmod "$D/drivers/spx_extras/spx_camera_id.ko" \
	target="$TARGET" watchdog_seconds=30 2>/dev/null || true
sudo dmesg | tail -n "+$((BEFORE + 1))" | grep 'spxcamid:' | sudo tee "$LOG"

# Backstop the module cleanup. This only clears the three already-validated
# camera rails over SPMI; it never unloads a live camera module.
"$D/scripts/spx-camera-down.sh" >/var/log/spx-camera-id-down.log 2>&1 || true

echo "Saved: $LOG"
echo "System remained online; all camera rails were forced off by the backstop."
