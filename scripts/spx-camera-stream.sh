#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# spx-camera-stream.sh - configure the CAMSS pipeline and attempt a capture.
#
# Why this exists: the measurement that matters is "CSIPHY 3PH HW Version", and
# the driver only prints it on stream START. spx-camera-probe.sh stops at the
# graph dump, so a boot that only probes never produces the number.
#
# Two hard-won rules shape this file:
#
# 1. EVERY line is synced. On 2026-08-07 this script hung at its first step and
#    the boot ended in FailureAction=reboot; the log file did not merely end
#    early, it did not exist at all - ext4 delayed allocation discards an
#    unsynced new file across an unclean reboot. Without per-line sync we cannot
#    tell "produced nothing" from "output lost", which wasted a whole boot.
#
# 2. EVERY hardware call is wrapped in `timeout`. A wedged ioctl otherwise burns
#    the unit's entire TimeoutStartSec with no clue as to which call wedged.
#    (A task stuck in D state is unkillable even so, but then the breadcrumb
#    still names the exact call, which is the point.)
set -u
cd "$(dirname "$0")/.."

say() { echo "$@"; sync; }
# Bounded hardware call: never let one ioctl consume the whole run.
hw()  { timeout 15 "$@"; rc=$?; [ $rc -eq 124 ] && say "  !! TIMED OUT: $*"; return $rc; }

say "=== stream stage start ==="
SOURCE_MODE=${SPX_CAMERA_SOURCE:-csid-testgen}
SENSOR_KIND=${SPX_CAMERA_SENSOR:-front}
case "$SOURCE_MODE" in
	csid-testgen|sensor-bars|sensor-real) ;;
	*)
		say "!! invalid SPX_CAMERA_SOURCE='$SOURCE_MODE'"
		say "   expected csid-testgen, sensor-bars, or sensor-real"
		exit 1
		;;
esac
case "$SENSOR_KIND" in
	front)
		SENSOR_DRIVER=ov5693
		REQUEST_CODE=SBGGR10_1X10
		REQUEST_SIZE=2592x1944
		PIXEL_FORMAT=pBAA
		BARS_PATTERN=2
		;;
	rear)
		SENSOR_DRIVER=ov13858
		REQUEST_CODE=SGRBG10_1X10
		REQUEST_SIZE=2112x1568
		PIXEL_FORMAT=pgAA
		BARS_PATTERN=1
		;;
	ir)
		SENSOR_DRIVER=ov7251
		REQUEST_CODE=Y10_1X10
		REQUEST_SIZE=640x480
		PIXEL_FORMAT=Y10P
		BARS_PATTERN=1
		;;
	*)
		say "!! invalid SPX_CAMERA_SENSOR='$SENSOR_KIND'"
		say "   expected front, rear, or ir"
		exit 1
		;;
esac
if [ -n "${SPX_CAMERA_OUTPUT_PREFIX:-}" ]; then
	OUTPUT_PREFIX=$SPX_CAMERA_OUTPUT_PREFIX
elif [ "$SENSOR_KIND" = "front" ]; then
	# Preserve the historical front-camera paths used by archived tests.
	OUTPUT_PREFIX=/var/log/spx-camera
else
	OUTPUT_PREFIX=/var/log/spx-camera-$SENSOR_KIND
fi
FRAME_FILE=${OUTPUT_PREFIX}-frame.raw
CAPTURE_LOG=${OUTPUT_PREFIX}-capture.log
DMESG_LOG=${OUTPUT_PREFIX}-dmesg-hang.log
say "source mode: $SOURCE_MODE"
say "sensor: $SENSOR_KIND ($SENSOR_DRIVER), request $REQUEST_CODE/$REQUEST_SIZE, output $PIXEL_FORMAT"
LIVE=$(cat /sys/module/qcom_camss/parameters/spx_stop_after 2>/dev/null || echo "?")
WANT=$(cat /var/lib/spx-stop-after-used 2>/dev/null || echo "?")
say "bisect level in force: spx_stop_after=$LIVE (armed: $WANT)"
command -v media-ctl >/dev/null || { say "!! media-ctl missing"; exit 1; }
command -v v4l2-ctl  >/dev/null || { say "!! v4l2-ctl missing";  exit 1; }
[ -x scripts/spx-v4l2-capture ] || { say "!! capture helper missing"; exit 1; }
say "tools present"

# The camss media device, resolved by driver name rather than by scanning every
# /dev/media* - other media drivers (venus, iris) can sit on those nodes and
# there is no reason to poke them.
MDEV=
for m in /dev/media0 /dev/media1 /dev/media2 /dev/media3; do
	[ -e "$m" ] || continue
	say "probing $m"
	if hw media-ctl -d "$m" -p 2>/dev/null | grep -q 'msm_csiphy'; then
		MDEV=$m; break
	fi
done
[ -n "$MDEV" ] || { say "!! no camss media device"; exit 1; }
say "media device: $MDEV"

GRAPH=$(hw media-ctl -d "$MDEV" -p 2>/dev/null)
say "graph captured: $(printf '%s\n' "$GRAPH" | wc -l) lines"

SENSOR=$(printf '%s\n' "$GRAPH" | sed -n "s/^- entity [0-9]*: \($SENSOR_DRIVER [^(]*\) (.*/\\1/p" | sed 's/ *$//' | head -1)
[ -n "$SENSOR" ] || { say "!! $SENSOR_DRIVER not in graph"; exit 1; }
say "sensor entity: '$SENSOR'"

SDEV=$(printf '%s\n' "$GRAPH" | awk -v e="$SENSOR" '
	$0 ~ "^- entity [0-9]+: " e " \\(" {inblk=1; next}
	/^- entity /                         {inblk=0}
	inblk && /\/dev\/v4l-subdev/         {print; exit}
' | grep -o '/dev/v4l-subdev[0-9]*' | head -1)
[ -n "$SDEV" ] || { say "!! sensor has no subdev node"; exit 1; }
say "sensor subdev: $SDEV"

# Follow the sensor's IMMUTABLE link instead of hardcoding the PHY.  The v23
# graph maps front/rear/IR to msm_csiphy0/2/3 respectively.
PHY=$(printf '%s\n' "$GRAPH" | awk -v s="$SENSOR" '
	$0 ~ "^- entity [0-9]+: " s " \\(" {inblk=1; next}
	/^- entity /                       {inblk=0}
	inblk                              {print}
' | grep -o 'msm_csiphy[0-9]*' | head -1)
[ -n "$PHY" ] || { say "!! sensor has no csiphy link"; exit 1; }
say "sensor is on: $PHY"

CSID=msm_csid0
RDI=msm_vfe0_rdi0
VNODE_ENT=msm_vfe0_video0
CSIDDEV=$(printf '%s\n' "$GRAPH" | awk -v e="$CSID" '
	$0 ~ "^- entity [0-9]+: " e " \\(" {inblk=1; next}
	/^- entity /                         {inblk=0}
	inblk && /\/dev\/v4l-subdev/         {print; exit}
' | grep -o '/dev/v4l-subdev[0-9]*' | head -1)
[ -n "$CSIDDEV" ] || { say "!! CSID has no subdev node"; exit 1; }
VDEV=$(printf '%s\n' "$GRAPH" | awk -v e="$VNODE_ENT" '
	$0 ~ "^- entity [0-9]+: " e " " {inblk=1; next}
	/^- entity /                    {inblk=0}
	inblk && /\/dev\/video/         {print; exit}
' | grep -o '/dev/video[0-9]*' | head -1)
[ -n "$VDEV" ] || VDEV=/dev/video0
say "capture node: $VDEV"

if [ "$SOURCE_MODE" = "csid-testgen" ]; then
	say "=== CSID internal test generator ==="
	# Keep CSIPHY disconnected: csid_set_test_pattern() deliberately rejects
	# the generator while a PHY link is active. This is the proven
	# CSID -> VFE -> IOMMU -> RAM diagnostic path.
	hw v4l2-ctl -d "$CSIDDEV" --set-ctrl=test_pattern=1 2>&1 | sed 's/^/  /'
	hw v4l2-ctl -d "$CSIDDEV" --get-ctrl=test_pattern 2>&1 | sed 's/^/  /'
	say "=== linking CSID testgen -> $RDI -> $VNODE_ENT ==="
else
	say "=== $SENSOR_DRIVER through $PHY ==="
	# The CSID generator and a live PHY input are mutually exclusive.
	hw v4l2-ctl -d "$CSIDDEV" --set-ctrl=test_pattern=0 2>&1 | sed 's/^/  /'
	if [ "$SOURCE_MODE" = "sensor-bars" ]; then
		hw v4l2-ctl -d "$SDEV" --set-ctrl=test_pattern="$BARS_PATTERN" 2>&1 | sed 's/^/  /'
	else
		hw v4l2-ctl -d "$SDEV" --set-ctrl=test_pattern=0 2>&1 | sed 's/^/  /'
	fi
	hw v4l2-ctl -d "$SDEV" --get-ctrl=test_pattern 2>&1 | sed 's/^/  /'
	say "=== linking $SENSOR -> $PHY -> $CSID -> $RDI -> $VNODE_ENT ==="
	# A successful earlier capture leaves its mutable PHY->CSID link enabled.
	# CSID0 accepts only one live PHY, so clear every camera candidate first.
	for OLD_PHY in msm_csiphy0 msm_csiphy2 msm_csiphy3; do
		[ "$OLD_PHY" = "$PHY" ] && continue
		hw media-ctl -d "$MDEV" -l "'$OLD_PHY':1 -> '$CSID':0 [0]" >/dev/null 2>&1 || true
	done
	hw media-ctl -d "$MDEV" -l "'$PHY':1 -> '$CSID':0 [1]" || say "  (phy->csid failed)"
	say "  link 1 done"
fi
hw media-ctl -d "$MDEV" -l "'$CSID':1 -> '$RDI':0 [1]"      || say "  (csid->rdi failed)"
say "  link 2 done"
hw media-ctl -d "$MDEV" -l "'$RDI':1 -> '$VNODE_ENT':0 [1]" || say "  (rdi->video failed)"
say "  link 3 done"

say "=== format negotiation ==="
# Set the sensor first, then propagate the value it ACCEPTED. An earlier
# STREAMON returned -EPIPE precisely because the sensor clamped its own pad to a
# real mode while the rest of the chain still held the requested size.
hw media-ctl -d "$MDEV" -V "'$SENSOR':0 [fmt:$REQUEST_CODE/$REQUEST_SIZE]" >/dev/null 2>&1
SFMT=$(hw media-ctl -d "$MDEV" --get-v4l2 "'$SENSOR':0" 2>/dev/null)
say "sensor pad0: $SFMT"
CODE=$(printf '%s' "$SFMT" | sed -n 's/.*fmt:\([A-Z0-9_]*\)\/.*/\1/p')
SIZE=$(printf '%s' "$SFMT" | sed -n 's/.*fmt:[A-Z0-9_]*\/\([0-9]*x[0-9]*\).*/\1/p')
[ -n "$CODE" ] || CODE=$REQUEST_CODE
[ -n "$SIZE" ] || SIZE=$REQUEST_SIZE
say "propagating: $CODE/$SIZE"

FORMAT_ENTITIES="$CSID $RDI"
[ "$SOURCE_MODE" = "csid-testgen" ] || FORMAT_ENTITIES="$PHY $FORMAT_ENTITIES"
for E in $FORMAT_ENTITIES; do
	hw media-ctl -d "$MDEV" -V "'$E':0 [fmt:$CODE/$SIZE]" 2>&1 | sed "s/^/  $E: /"
	say "  set $E"
done

say "=== SMMU mapping state ==="
# v22 attaches CAMSS to the Surface-specific Windows S1_CAMERA_HLOS mapping:
# SID 0x0a00, mask 0x04e0.  The successful CSID test-generator capture used
# IOVAs 0xff800000/0xff000000 and proved real DMA into both queued buffers.
say "  arm_smmu disable_bypass = $(cat /sys/module/arm_smmu/parameters/disable_bypass 2>/dev/null || echo unknown)"
if [ -e /sys/bus/platform/devices/ac65000.camss/iommu_group ]; then
	say "  camss iommu-mapped = yes"
else
	say "  !! camss iommu-mapped = no (v22 camera DTB is not active)"
	[ "$SOURCE_MODE" = "csid-testgen" ] || exit 1
fi

say "=== capture attempt ==="
hw v4l2-ctl -d "$VDEV" --set-fmt-video=width=${SIZE%x*},height=${SIZE#*x},pixelformat=$PIXEL_FORMAT 2>&1 | sed 's/^/  /'
say "  fmt set"
hw v4l2-ctl -d "$VDEV" --get-fmt-video 2>&1 | sed 's/^/  /'
# Arm the hardware watchdog. STREAMON hangs the ENTIRE SoC - systemd dies with
# it, so TimeoutStartSec/FailureAction cannot fire and the machine would sit
# wedged until someone power-cycles it by hand. The APSS watchdog is the only
# thing still running at that point; with nobody petting it, it bites after its
# 30 s default and issues a WARM reset, which both automates recovery AND
# preserves the ramoops DRAM record we came for.
# The node does not exist in sc8180x.dtsi and is not in ACPI either; it was added
# to the CAMERA DTB only, at 0x17c10000 - the gap between apss_shared@17c00000
# and timer@17c20000, matching sm8150's APSS layout.
WD=
if [ -e /dev/watchdog ]; then
	exec 9>/dev/watchdog && WD=1 && say "  watchdog ARMED (bites ~30 s after the last pet)"
else
	say "  !! /dev/watchdog absent - a hang will need a MANUAL power cycle"
	say "     (qcom_wdt may have failed to probe, or TZ owns the block)"
fi

say "  about to STREAMON"
# STREAMON wedges the calling task in UNINTERRUPTIBLE (D) state - measured
# 2026-08-07, `timeout 30` could not kill it and the unit ran to its 180 s
# deadline. But the REST of the system stays alive (systemd still rebooted
# cleanly), so the wedged task can be interrogated in place. That is the only
# way to learn which kernel function blocks; running it in the foreground just
# burns a boot and tells us nothing.
#
# The custom helper allocates exactly two buffers, fills them with 0xa5, queues
# them, syncs the DMA diagnostics, waits five seconds,
# and only then calls STREAMON. Close fd 9 in the child: otherwise a capture
# stuck forever also holds the watchdog device open.
scripts/spx-v4l2-capture "$VDEV" "${SIZE%x*}" "${SIZE#*x}" \
	"$FRAME_FILE" "$PIXEL_FORMAT" > "$CAPTURE_LOG" 2>&1 9>&- &
SPID=$!
say "  STREAMON running as pid $SPID"

# Belt-and-suspenders recovery. The APSS watchdog failed to bite on the last
# wedged run. If enough of the scheduler survives, emergency SysRq reboots at
# 40 seconds without invoking the shutdown paths which later deadlocked in BPF
# text invalidation. GRUB's camera entry is one-shot, so this always returns to
# the saved default entry. All evidence is explicitly synced before STREAMON.
(
	sleep 40
	echo "SPX camera recovery timer: forcing immediate reboot" > /dev/kmsg 2>/dev/null || true
	sync
	echo b > /proc/sysrq-trigger
) 9>&- &
RECOVERY_PID=$!

for i in 1 2 3 4; do
	sleep 5
	if ! kill -0 "$SPID" 2>/dev/null; then
		wait "$SPID"; say "  STREAMON exited rc=$?"; break
	fi
	# ONE-SHOT state capture while the pipeline is OPEN. In sensor modes this is
	# after csiphy_set_power() enabled the CSIPHY clocks; in CSID test-generator
	# mode the PHY correctly remains off. These are read-only debugfs snapshots.
	if [ "$i" = "1" ]; then
		say "  --- power/clock state WITH PIPELINE OPEN ---"
		grep -iE 'titan|ife_0' /sys/kernel/debug/pm_genpd/pm_genpd_summary 2>/dev/null \
			| sed 's/^/    genpd: /' || say "    (genpd unavailable)"
		grep -iE 'cam_cc_(camnoc|cpas|core|gdsc|slow|cphy|csiphy[0-3]|csi[0-3]phytimer)|gcc_camera_(ahb|xo)' /sys/kernel/debug/clk/clk_summary 2>/dev/null \
			| sed 's/^/    clk: /' || say "    (clk_summary unavailable)"
		# Probe the CSIPHY window itself while it is demonstrably powered and
		# clocked. VFE/CSID report real HW versions from their windows but the
		# CSIPHY reads 0x00000000, so either 0xac5a000 is not the CSIPHY on
		# sc8180x or the CMN sub-block is not at the driver's +0x800. A dump
		# says which - and whether ANY word in the window responds.
		# NOTE: spx_csiphy_dump.ko is DISABLED here. Measured 2026-08-07: sweeping
		# the whole 0x2000 window HUNG the SoC. Undecoded offsets in this region
		# do not read back as zero - they wedge the bus. (Only +0x800, where the
		# driver reads, returns 0x0 harmlessly.) That is also why
		# csiphy_lanes_enable hangs: it writes lane registers in that same
		# undecoded space. Never sweep a camera window blind again.
		say "  (window sweep disabled - it hangs; driver prints the HW version)"
		say "  --- DMA/VFE/SMMU diagnostics WITH PIPELINE OPEN ---"
		dmesg | grep -E 'SPX DMA|SPX VFE|arm-smmu|iommu' | tail -120 \
			| sed 's/^/    kmsg: /' || say "    (no matching kernel diagnostics)"
		sync
	fi
	say "  --- t=${i}x5s: still running, state=$(awk '{print $3}' /proc/$SPID/stat 2>/dev/null) wchan=$(cat /proc/$SPID/wchan 2>/dev/null)"
	# The kernel stack of the blocked task names the exact blocking function.
	if [ -r /proc/$SPID/stack ]; then
		say "  kernel stack:"
		sed 's/^/    /' /proc/$SPID/stack 2>/dev/null
	else
		say "  (/proc/$SPID/stack unreadable - needs CONFIG_STACKTRACE)"
	fi
	sync
done
# STOP THE STREAM before anything else. Measured 2026-08-07: the poll loop above
# used to just fall through, leaving v4l2-ctl running with /dev/video0 open and
# the stream still ON. The script then wrote "ALL DONE", SuccessAction=reboot
# fired, and ExecStop ran `rmmod qcom_camss` on a LIVE streaming device - which
# wedged a CPU. Everything else then piled up behind it (a kworker stuck in
# kick_all_cpus_sync waiting for an IPI that CPU could no longer service, five
# CPUs at 100% system, RCU stall at t=270s, soft lockup at t=296s) and the reboot
# never completed. That panic was OUR teardown, not the camera test.
# Done while the watchdog is still armed, so a wedge HERE also auto-recovers.
STUCK=
if kill -0 "$SPID" 2>/dev/null; then
	say "  stopping stream (pid $SPID) before teardown"
	kill -INT "$SPID" 2>/dev/null || true
	for k in 1 2 3 4 5; do
		kill -0 "$SPID" 2>/dev/null || break
		sleep 1
	done
	if kill -0 "$SPID" 2>/dev/null; then
		kill -KILL "$SPID" 2>/dev/null || true
		sleep 1
	fi
	if kill -0 "$SPID" 2>/dev/null; then
		STUCK=1
		say "  !! stream pid $SPID SURVIVED kill -9 (D state) - do NOT rmmod camss"
	else
		say "  stream stopped cleanly"
	fi
fi
# Nothing must hold the capture node when the rails are dropped.
say "  holders of $VDEV: $(fuser -v "$VDEV" 2>&1 | tail -n +2 | tr '\n' ' ' || echo none)"

say "  capture-helper output:"; sed 's/^/    /' "$CAPTURE_LOG" 2>/dev/null
# SysRq-W dumps EVERY task in uninterruptible sleep straight to the kernel log.
# Second, independent source for the blocking function - it also catches a
# workqueue or IRQ thread wedged alongside v4l2-ctl, which /proc/PID/stack of
# the caller alone would miss.
if [ -w /proc/sysrq-trigger ]; then
	echo w > /proc/sysrq-trigger 2>/dev/null || true
	say "  sysrq-w (blocked tasks) issued"
	sleep 1
fi
dmesg > "$DMESG_LOG" 2>&1
sync

# An unkillable capture means STREAMOFF/close cannot be trusted and no driver
# teardown or systemd reboot should be attempted. Leave the watchdog armed and
# stop touching the camera; its bite returns this one-shot boot to the saved
# default even if a CPU is already wedged.
if [ -n "$STUCK" ]; then
	say "  watchdog and 40-second recovery timer remain armed because capture is stuck"
	sync
	while :; do sleep 10; done
fi

# The capture returned or was killed. Cancel the emergency timer before doing
# any clean teardown; wait also prevents a PID-reuse race.
kill "$RECOVERY_PID" 2>/dev/null || true
wait "$RECOVERY_PID" 2>/dev/null || true

# Survived the capture: disarm with the magic 'V' so the watchdog does NOT bite
# 30 s later and reboot us in the middle of writing the results out.
if [ -n "$WD" ]; then
	printf 'V' >&9
	exec 9>&-
	say "  watchdog DISARMED (magic close) - capture survived"
fi

say "=== THE measurement ==="
dmesg | grep -iE 'CSIPHY|csid|vfe|camss' | tail -30
sync
ls -l "$FRAME_FILE" 2>/dev/null
say "=== stream stage end ==="
# Advance only after the selected pipeline level reached STREAMON, remained
# recoverable, and completed teardown.  Advancing in probe.sh used to consume a
# level even when the sensor was absent from the graph and this script exited
# before attempting a stream.
if [ "$LIVE" != "?" ] && [ "$WANT" != "?" ] &&
   [ "$LIVE" = "$WANT" ] && [ "$LIVE" -ge 0 ] && [ "$LIVE" -lt 4 ] 2>/dev/null; then
	echo "$((LIVE + 1))" > /var/lib/spx-stop-after
	sync
	say "bisect advanced: next spx_stop_after=$((LIVE + 1))"
elif [ "$LIVE" = "4" ] 2>/dev/null; then
	say "bisect complete: keeping full-chain spx_stop_after=4"
fi
exit 0
