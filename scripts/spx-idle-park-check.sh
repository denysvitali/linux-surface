#!/bin/bash
# SPX idle-park validator: watch the SoundWire controller's runtime-PM state
# around manual streams. READ-ONLY except one explicitly opted-in knob.
#
# PROGRESS §48 #4 / §48.6 #3: Windows broadcasts CLK_STP_NOW (dev15, SCP_CTRL
# 0x44 <- 2) whenever its idle refcount hits zero, quiescing the WSA881x bus
# between streams; verified live 2026-08-24 our controller sits
# runtime-'active' forever. NOTE: missing autosuspend is NOT the gate on this
# tree -- committed HEAD already arms autosuspend at 3000 ms in probe and
# qcom_swrm_shutdown does mark_last_busy+put_autosuspend, so
# swrm_runtime_suspend() (the full MIPI prep/clk-stop handshake) is reachable.
# What actually pins the controller 'active' on the standard guarded boot is
# the spx_force_attach hold: force-attach takes ONE permanent runtime-PM
# reference (spx_pm_held, dropped only in remove()), so runtime_status can
# never leave 'active' BY DESIGN while spx_force_attach=1 -- even with the
# counterpart knob `soundwire_qcom.spx_idle_clk_stop_ms` (>0 re-arms
# autosuspend with that delay) correctly armed. Park validation therefore
# needs a boot WITHOUT spx_force_attach=1 on the command line.
#
# This script validates that WITHOUT any listening: it samples the
# controller's sysfs runtime state every few seconds for N minutes while the
# operator plays audio manually whenever they like. Each sample is annotated
# with the ALSA playback-PCM state read from /proc/asound, so park/resume can
# be correlated with stream windows afterwards from the log alone.
#
# Expected signatures:
#   knob off (legacy)   : runtime_status=active for every sample, no matter
#                         what -- today's baseline ("active" forever), with
#                         runtime_usage dropping to 0 in closed windows.
#   knob armed, healthy : active while a PCM is OPEN/RUNNING (streams hold
#                         pm_runtime_get_sync); transitions to suspended
#                         ~<knob> ms after the last close; back to active on
#                         the next open. runtime_suspended_time grows.
#   knob armed + force-attach hold: runtime_status=active for every sample AND
#                         runtime_usage stays >0 across pcm-closed windows.
#                         The park is impossible BY DESIGN on that boot; the
#                         run says NOTHING about whether the knob works.
#
# Usage: spx-idle-park-check.sh            (no arguments)
#
# Env knobs:
#   SPX_IDLE_MINUTES=10    how long to sample (minutes)
#   SPX_IDLE_INTERVAL_S=5  seconds between samples
#   SPX_IDLE_SNAPSHOT=0    1 ALSO fires the serialized spx_snapshot register
#                          dump ONCE per observed entry into 'suspended'
#                          (max SPX_IDLE_SNAP_MAX times, only while the PCM
#                          is closed). This is the script's ONLY write: it
#                          pokes soundwire_qcom/spx_snapshot exactly like
#                          scripts/spx-portmask-snapshot discipline -- never
#                          while samples are flowing. NOTE: the current
#                          snapshot line carries COMP_PARAMS/MCP_STATUS/
#                          MCP_SLV_STATUS/DP1+DP4 banks, not SWRM_COMP_STATUS
#                          (0x014); if that register is added to the dump
#                          later, the recorded "SPX SNAPSHOT:" lines pick it
#                          up unchanged.
#   SPX_IDLE_SNAP_MAX=10   hard cap on snapshots per run
#
# Exit codes:
#   0   sampling completed (summary printed)
#   1   preflight failure (controller device missing, card missing, bad knob)
#
# HARD RULES encoded (CLAUDE.md): no reboot, no module load/unload, no
# reads of spx_reenum (write-only, blocks forever) or pinctrl debugfs
# (oopses) or MMIO near 171c0000 (+0x2000 wedges the CPU), no rpmsg/GLINK
# probes, and -- unlike its sibling runners -- it never opens an ALSA device
# and never touches amp GPIO state. Pure observation.
#
# Run as the desktop user, never through sudo.

set -euo pipefail
if (( EUID == 0 )); then echo "FATAL: run as desktop user, not sudo" >&2; exit 1; fi
cd "$(dirname "$0")/.."
sudo -v || exit 1

(( $# == 0 )) || { echo "usage: $0 (no arguments)" >&2; exit 1; }

MINUTES=${SPX_IDLE_MINUTES:-10}
INTERVAL_S=${SPX_IDLE_INTERVAL_S:-5}
SNAPSHOT=${SPX_IDLE_SNAPSHOT:-0}
SNAP_MAX=${SPX_IDLE_SNAP_MAX:-10}

[[ $MINUTES =~ ^[0-9]+$ ]] && (( MINUTES >= 1 )) ||
	{ echo "FATAL: SPX_IDLE_MINUTES must be >= 1" >&2; exit 1; }
[[ $INTERVAL_S =~ ^[0-9]+$ ]] && (( INTERVAL_S >= 1 )) ||
	{ echo "FATAL: SPX_IDLE_INTERVAL_S must be >= 1" >&2; exit 1; }
[[ $SNAPSHOT =~ ^[01]$ ]] ||
	{ echo "FATAL: SPX_IDLE_SNAPSHOT must be 0 or 1" >&2; exit 1; }
[[ $SNAP_MAX =~ ^[0-9]+$ ]] ||
	{ echo "FATAL: SPX_IDLE_SNAP_MAX must be numeric" >&2; exit 1; }

LOG="/tmp/spx-idle-park-check-$(date +%Y%m%d-%H%M%S).log"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
echo "logfile: $LOG"
echo "knobs: MINUTES=$MINUTES INTERVAL_S=$INTERVAL_S SNAPSHOT=$SNAPSHOT SNAP_MAX=$SNAP_MAX"

# --- locate the controller ---------------------------------------------------
SWR_DEV=
for d in /sys/bus/platform/drivers/qcom-soundwire/*/; do
	[[ -e $d/power/runtime_status ]] || continue
	SWR_DEV=${d%/}
	break
done
[[ -n $SWR_DEV ]] ||
	{ echo "FATAL: no bound qcom-soundwire controller with a power/runtime_status" >&2
	  echo "       found under /sys/bus/platform/drivers/qcom-soundwire/" >&2; exit 1; }
echo "controller: $SWR_DEV"
FORCE_ATTACH=$(cat /sys/module/soundwire_qcom/parameters/spx_force_attach 2>/dev/null || echo '?')
echo "force_attach param: $FORCE_ATTACH"
[[ $FORCE_ATTACH != 1 ]] || echo "WARNING: spx_force_attach=1 holds a permanent runtime-PM reference; runtime_status can NEVER leave 'active' on this boot, regardless of the idle_clk_stop knob."
echo "idle_clk_stop knob: $(cat /sys/module/soundwire_qcom/parameters/spx_idle_clk_stop_ms 2>/dev/null || echo '<param absent: pre-group-3 kernel>')"

CARD=$(awk '/Surface Pro X/{print $1}' /proc/asound/cards | head -1)
[[ $CARD =~ ^[0-9]+$ ]] || { echo "FATAL: no Surface Pro X card" >&2; exit 1; }
PCM_STATUS=/proc/asound/card${CARD}/pcm0p/sub0/status
[[ -e $PCM_STATUS ]] ||
	{ echo "FATAL: $PCM_STATUS missing" >&2; exit 1; }

read1() { cat "$1" 2>/dev/null || echo '?'; }

# One AC/battery/rail line at start and end: the §46 soak model correlates
# decay with supply state, so every park log should be datable against SOC.
power_note() {
	local adp bst bcap iio vph line
	adp=$(read1 /sys/class/power_supply/ADP1/online)
	bst=$(read1 /sys/class/power_supply/BAT1/status)
	bcap=$(read1 /sys/class/power_supply/BAT1/capacity)
	vph='?'
	for iio in /sys/bus/iio/devices/iio:device*; do
		[[ -e $iio/in_voltage_vph_pwr_input ]] || continue
		vph=$(read1 "$iio/in_voltage_vph_pwr_input")
		break
	done
	line="tag=$1 adp=$adp bat=$bst/$bcap% vph=${vph}uV up=$(cut -d ' ' -f1 /proc/uptime)"
	logger -t spx-power "$line" 2>/dev/null || true
	echo "[power] $line"
}

snapshot_once() {
	# Serialized controller dump, idle-only by construction (caller gates on
	# pcm=closed + suspended). Same mechanism as scripts/spx-portmask-sweep.sh.
	local marker line
	marker="SPX_IDLEPARK_SNAP_${RANDOM}_$(date +%s%N)"
	printf '<6>%s\n' "$marker" | sudo tee /dev/kmsg >/dev/null
	echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_snapshot \
		>/dev/null 2>&1 || { echo "  [snapshot] FAILED"; return 0; }
	line=$(sudo dmesg | sed -n "/$marker/,\$p" | grep 'SPX SNAPSHOT:' | tail -1)
	echo "  [snapshot] ${line:-none logged}"
}

echo
echo "Play/pause audio manually whenever you like; every sample below records"
echo "the playback-PCM state so park windows can be matched to stream windows."
echo "Ctrl-C stops early (partial log remains valid). Sampling for $MINUTES min."
power_note start

DEADLINE=$(( $(date +%s) + MINUTES * 60 ))
PREV_STATUS='run-start'
N_ACTIVE=0 N_SUSPENDED=0 N_SAMPLES=0
N_HOLD_CLOSED=0 N_CLOSED=0
SUSP_EPISODES=0 SNAPS_DONE=0
ACT0='' SUS0=''

while :; do
	NOW=$(date +%s)
	(( NOW < DEADLINE )) || break

	TS=$(date +%T)
	ST=$(cat "$SWR_DEV/power/runtime_status" 2>/dev/null || echo '?')
	CTL=$(cat "$SWR_DEV/power/control" 2>/dev/null || echo '?')
	DLY=$(cat "$SWR_DEV/power/autosuspend_delay_ms" 2>/dev/null || echo '?')
	ACT=$(cat "$SWR_DEV/power/runtime_active_time" 2>/dev/null || echo '?')
	SUS=$(cat "$SWR_DEV/power/runtime_suspended_time" 2>/dev/null || echo '?')
	USAGE=$(cat "$SWR_DEV/power/runtime_usage" 2>/dev/null || echo '?')
	PCM=$(cat "$PCM_STATUS" 2>/dev/null | tr -d '\n' || echo '?')
	[[ -z $ACT0 ]] && ACT0=$ACT SUS0=$SUS
	N_SAMPLES=$((N_SAMPLES + 1))
	if [[ $PCM == closed ]]; then
		N_CLOSED=$((N_CLOSED + 1))
		if [[ $USAGE =~ ^[0-9]+$ ]] && (( USAGE > 0 )); then
			N_HOLD_CLOSED=$((N_HOLD_CLOSED + 1))
		fi
	fi
	case $ST in
	active) N_ACTIVE=$((N_ACTIVE + 1)) ;;
	suspended) N_SUSPENDED=$((N_SUSPENDED + 1)) ;;
	esac

	if [[ $ST != $PREV_STATUS ]]; then
		echo "*** TRANSITION $PREV_STATUS -> $ST at $TS (pcm=$PCM)"
		logger -t spx-idle-park "$TS runtime_status $PREV_STATUS -> $ST (pcm=$PCM)" 2>/dev/null || true
		PREV_STATUS=$ST
		if [[ $ST == suspended ]]; then
			SUSP_EPISODES=$((SUSP_EPISODES + 1))
			if (( SNAPSHOT == 1 )) && (( SNAPS_DONE < SNAP_MAX )) && [[ $PCM == closed ]]; then
				snapshot_once
				SNAPS_DONE=$((SNAPS_DONE + 1))
			fi
		fi
	fi
	echo "$TS status=$ST pcm=$PCM ctl=$CTL delay=$DLY usage=$USAGE act_ms=$ACT susp_ms=$SUS"

	sleep "$INTERVAL_S"
done

power_note end
echo
echo "======================= PARK SUMMARY ======================="
echo "samples          : $N_SAMPLES (every ${INTERVAL_S}s for ~${MINUTES}min)"
echo "active samples   : $N_ACTIVE"
echo "suspended samples: $N_SUSPENDED"
echo "suspend episodes : $SUSP_EPISODES (active->suspended transitions)"
echo "closed windows   : $N_CLOSED (pcm closed at sample time)"
echo "hold in closed   : $N_HOLD_CLOSED samples with runtime_usage > 0 while pcm=closed (force-attach hold signature)"
echo "force_attach     : $FORCE_ATTACH"
if [[ $ACT0 =~ ^[0-9]+$ && $ACT =~ ^[0-9]+$ ]]; then
	echo "runtime_active_time delta   : $((ACT - ACT0)) ms over this run"
fi
if [[ $SUS0 =~ ^[0-9]+$ && $SUS =~ ^[0-9]+$ ]]; then
	echo "runtime_suspended_time delta: $((SUS - SUS0)) ms over this run"
fi
if (( N_HOLD_CLOSED > 0 )); then
	echo
	echo "NOTE: runtime_usage stayed >0 in $N_HOLD_CLOSED pcm-closed sample(s):"
	echo "the spx_force_attach hold pins this controller active BY DESIGN."
	echo "This run cannot validate spx_idle_clk_stop_ms -- re-run on a boot"
	echo "whose command line does not contain spx_force_attach=1."
fi
cat <<'VERDICT'

Verdict guide (§48 #4):
  episodes >= 1, only while pcm=closed . WORKING park: matches the Windows
        CLK_STP_NOW-between-streams semantic. Correlate episode count and
        parked-milliseconds-per-hour against the §46 decay model across days.
  0 episodes + runtime_usage was 0 in closed windows ... the bus NEVER parked:
        legacy behavior, or the knob is 0/not applied on this boot. Check the
        knob line above; check /sys/.../power/control is 'auto' and delay
        equals the knob.
  0 episodes + runtime_usage > 0 in closed windows .... FORCE-ATTACH HOLD:
        spx_force_attach=1 takes one permanent runtime-PM reference, so no
        park can happen regardless of the knob. This is NOT evidence that
        spx_idle_clk_stop_ms failed -- validate it on a boot without
        spx_force_attach=1 instead (a silent run here would be a void
        measurement).
  episodes while pcm OPEN/RUNNING ... UNEXPECTED (streams hold a runtime PM
        reference); capture dmesg and investigate before any listening A/B.
VERDICT
echo "full log: $LOG"
exit 0
