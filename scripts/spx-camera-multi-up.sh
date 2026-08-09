#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Bind all three verified SPX sensors, then create the CAMSS media graph.
#
# Run only after the one-shot spx-camera-multi-v23 GRUB entry.  This script
# never unloads a module, never starts a stream, and never reboots on success.
# Every risky module probe has both the APSS watchdog and a SysRq fallback so a
# hard CCI/CAMSS stall returns to GRUB's saved safe entry without a person at
# the machine.
set -eu
cd "$(dirname "$0")/.."

if [ "$(id -u)" -ne 0 ]; then
	exec sudo "$0" "$@"
fi

fail()
{
	echo "!! $*"
	exit 1
}

case " $(cat /proc/cmdline) " in
	*" spx_camera_multi_v23=1 "*) ;;
	*) fail "not on the one-shot v23 camera entry; refusing hardware changes" ;;
esac

DT=/proc/device-tree/soc@0/cci@ac4a000/i2c-bus@0
[ -d "$DT/camera@10" ] || fail "rear OV13858 node is absent from the live DT"
[ -d "$DT/camera@60" ] || fail "IR OV7251 node is absent from the live DT"
[ -e /sys/bus/platform/devices/ac65000.camss/iommu_group ] || \
	fail "CAMSS is not attached to an IOMMU group"

for module in ov5693 ov13858 ov7251 qcom_camss; do
	if [ -d "/sys/module/$module" ]; then
		fail "$module loaded before controlled rail bring-up; leaving it untouched"
	fi
done

echo "== v23 DT and unloaded-module preconditions verified =="
scripts/spx-camera-rails-up.sh

risky_run()
{
	label=$1
	shift
	echo "== $label =="
	sync

	# Opening qcom_wdt starts its fixed 30-second countdown.  The child does not
	# inherit fd 9; if modprobe wedges, its close cannot accidentally disarm it.
	wd=
	if [ -e /dev/watchdog ]; then
		exec 9>/dev/watchdog
		wd=1
		echo "  APSS watchdog armed"
	else
		echo "  warning: /dev/watchdog is absent; relying on SysRq recovery"
	fi

	(
		sleep 22
		echo "SPX v23 $label probe recovery: forcing immediate reboot" \
			> /dev/kmsg 2>/dev/null || true
		sync
		echo b > /proc/sysrq-trigger
	) 9>&- &
	recovery_pid=$!

	set +e
	timeout -k 2 15 "$@" 9>&-
	rc=$?
	set -e

	kill "$recovery_pid" 2>/dev/null || true
	wait "$recovery_pid" 2>/dev/null || true
	if [ -n "$wd" ]; then
		printf 'V' >&9
		exec 9>&-
		echo "  watchdog disarmed"
	fi
	[ "$rc" -eq 0 ] || fail "$label failed with rc=$rc"
}

# CCI and every camera GDSC/clock depend on the out-of-tree SC8180X CAMCC
# module.  Once installed it normally autoloads from the ad00000 DT modalias;
# keep an explicit, protected fallback for a minimal initramfs/userspace.
if [ ! -L /sys/bus/platform/devices/ad00000.clock-controller/driver ]; then
	risky_run "loading SC8180X camera clock controller" \
		modprobe camcc-sc8180x
fi

# Sensor modules bind first while the real rails are known to be on.  CAMSS is
# deliberately last so its async graph sees all three registered subdevices.
risky_run "loading front OV5693" modprobe ov5693
risky_run "loading rear OV13858" modprobe ov13858
risky_run "loading IR OV7251" modprobe ov7251
risky_run "loading CAMSS full chain" modprobe qcom-camss spx_stop_after=4

sleep 1
echo "== bound sensors =="
for driver in ov5693 ov13858 ov7251; do
	bound=
	for node in "/sys/bus/i2c/drivers/$driver"/*; do
		[ -e "$node/name" ] || continue
		echo "  $driver: $(basename "$node")"
		bound=1
	done
	[ -n "$bound" ] || fail "$driver has no bound I2C device"
done

echo "== CAMSS graph sensors =="
media-ctl -d /dev/media0 -p 2>/dev/null | \
	grep -E '^- entity [0-9]+: (ov5693|ov13858|ov7251) '

echo "all three sensors are bound; no stream has been started"
