#!/bin/bash
# SPX §48.6 delta A/B runner: two guarded streams in one boot with the
# Windows-parity register deltas applied live between bring-ups.
#
# PROGRESS §48 ranked ten real Windows-vs-Linux deltas; §48.6 is the cheapest
# objective ladder out of them. This runner hosts one boot's worth of that
# ladder: it brings the pin2 amp up TWICE with the full guarded recipe
# (park -> >= 10 s off -> pin2 -> physical device-0 announce -> force-attach
# stable attachment + cold-init replay), plays ONE guarded tone per
# bring-up, and can apply a Windows register delta after every cold-init
# replay so both streams run under it. Every stream window carries a
# power-state line (PROGRESS §39 rule: a listening run without a power
# record is void) and its own kmsg-sliced evidence block.
#
# The objective metric is the codec SLIMbus PGD interrupt line
#   "overflow error on RX port 0, value .."
# (sound/soc/codecs/wcd934x.c dev_err_ratelimited) counted PER STREAM from
# dmesg -- the §48 #1 defect signature (fires once per stream today).
# dev_err_ratelimited means counts are lower bounds; compare directionally,
# never absolutely.
#
# Usage: spx-delta-ab.sh            (no arguments)
#
# Env knobs (defaults mirror scripts/spx-portmask-sweep.sh exactly):
#   SPX_WSA_SEQ=""        optional spx_wsa_seq.ko seq string, replayed to the
#                         pin2 amp unit after EVERY cold-init replay (a cold
#                         init overwrites these registers) and before every
#                         stream. The spec's §48 #2 boost-octet delta:
#                           0x3133:0x8f,0x3135:0xa3,0x3135:0xa0,0x3131:0x75,
#                           0x3131:0x74,0x312c:0x80,0x3134:0x14,0x312b:0x78,
#                           0x312a:0x98
#   SPX_SEQ_STREAM2_ONLY=0 1 applies SPX_WSA_SEQ to stream 2 only (stream 1 =
#                         legacy control) for a true same-boot A/B
#   SPX_TEARDOWN_RESET=0  1 replays Windows' teardown soft-reset after each
#                         stream close (SWR_RESET_EN 0x300b=0x07 THEN
#                         CDC_RST_CTL 0x3005=0x00 -- §48 #5): the WSA digital
#                         core resets between streams and the next bring-up's
#                         cold-init replay is the required re-arm.
#   SPX_GREP_RX0=0        1 prints the per-stream RX0 overflow diff table
#                         (the §48.6 #1 objective metric).
#   SPX_PA_VOLUME=12      PA gain force-written after cold init (12 = +18 dB)
#   SPX_BOOST_SWITCH=1    analog boost switch state during the stream
#   SPX_ZERO_ONLY=0       1 replaces the 5 s tone with silence (11 s of zero)
#   SPX_PORT_MASK=1       SoundWire descriptor mask (1 = DAC-only v28
#                         baseline; 5 = DAC+BOOST v31)
#   SPX_COUNTDOWN_S=3     countdown seconds before each stream
#   SPX_SEQ_DEVICES=sdw:0:0:0217:2010:00:2    seq target: the pin2 amp unit
#
# Exit codes:
#   0   both streams completed, evidence printed
#   1   usage or preflight failure (module/card/tool missing, bad knob,
#       booted-entry coherence check failed)
#   10  stream-1 phase: park/pin2 unverified, bridge canary invalid, no
#       device-0 announce, no stable attachment + cold-init replay, seq
#       replay incomplete, or a mixer write failed
#   20  stream-2 phase: any phase-1-type failure during the teardown reset
#       or the second bring-up
#   30  final park could not be verified
#   50  kernel-fault indicator (Oops/BUG:) observed since the phase marker
#
# HARD RULES encoded (CLAUDE.md). This script never:
#   - reboots or powers off the machine;
#   - rmmods soundwire_qcom (re-probe oopses; reboot-only recovery);
#   - READS /sys/module/soundwire_qcom/parameters/spx_reenum (write-only, a
#     read blocks forever) -- it is only ever written via `sudo tee`;
#   - reads pinctrl debugfs pinmux-pins/pins (oops, mutex held until reboot);
#   - reads MMIO around 171c0000 (+0x2000 wedges the CPU);
#   - probes rpmsg/GLINK channels (ADSP crash);
#   - calls a mid-tone serialized controller read (the shared WCD/SLIMbus
#     bridge transaction costs ~165 ms and audibly cuts the stream;
#     snapshots happen only before the countdown or after close).
#
# Run as the desktop user, never through sudo. The amp is parked off at
# exit and the descriptor mask is restored.

set -euo pipefail
if (( EUID == 0 )); then echo "FATAL: run as desktop user, not sudo" >&2; exit 1; fi
cd "$(dirname "$0")/.."
sudo -v || exit 1

(( $# == 0 )) || { echo "usage: $0 (no arguments)" >&2; exit 1; }

WSA_SEQ=${SPX_WSA_SEQ:-}
SEQ_STREAM2_ONLY=${SPX_SEQ_STREAM2_ONLY:-0}
TEARDOWN_RESET=${SPX_TEARDOWN_RESET:-0}
GREP_RX0=${SPX_GREP_RX0:-0}
PA_VOLUME=${SPX_PA_VOLUME:-12}
BOOST_SWITCH=${SPX_BOOST_SWITCH:-1}
ZERO_ONLY=${SPX_ZERO_ONLY:-0}
PORT_MASK=${SPX_PORT_MASK:-1}
COUNTDOWN_S=${SPX_COUNTDOWN_S:-3}
SEQ_DEVICES=${SPX_SEQ_DEVICES:-sdw:0:0:0217:2010:00:2}

[[ $TEARDOWN_RESET =~ ^[01]$ ]] ||
	{ echo "FATAL: SPX_TEARDOWN_RESET must be 0 or 1" >&2; exit 1; }
[[ $GREP_RX0 =~ ^[01]$ ]] ||
	{ echo "FATAL: SPX_GREP_RX0 must be 0 or 1" >&2; exit 1; }
[[ $PA_VOLUME =~ ^[0-9]+$ ]] ||
	{ echo "FATAL: SPX_PA_VOLUME must be numeric" >&2; exit 1; }
[[ $BOOST_SWITCH =~ ^[01]$ ]] ||
	{ echo "FATAL: SPX_BOOST_SWITCH must be 0 or 1" >&2; exit 1; }
[[ $ZERO_ONLY =~ ^[01]$ ]] ||
	{ echo "FATAL: SPX_ZERO_ONLY must be 0 or 1" >&2; exit 1; }
[[ $PORT_MASK =~ ^[0-9]+$ ]] ||
	{ echo "FATAL: SPX_PORT_MASK must be numeric" >&2; exit 1; }
[[ $COUNTDOWN_S =~ ^[0-9]+$ ]] && (( COUNTDOWN_S >= 1 )) ||
	{ echo "FATAL: SPX_COUNTDOWN_S must be >= 1" >&2; exit 1; }
[[ $SEQ_DEVICES =~ ^sdw:[0-9]+:[0-9]+:[0-9a-fA-F]+:[0-9a-fA-F]+:[0-9]{2}:[0-9]{1,2}$ ]] ||
	{ echo "FATAL: SPX_SEQ_DEVICES is not a SoundWire device name" >&2; exit 1; }

# Validate the seq string BEFORE touching hardware: spx_wsa_seq.ko silently
# skips entries outside 0x3000-0x36ff (or val > 0xff), and a half-applied
# delta would corrupt the A/B. Entry form: reg:val[:delay_ms], hex ok.
SEQ_NENTRIES=0
if [[ -n $WSA_SEQ ]]; then
	IFS=',' read -r -a _SEQ_ENTRIES <<<"$WSA_SEQ"
	for entry in "${_SEQ_ENTRIES[@]}"; do
		[[ $entry =~ ^(0x[0-9a-fA-F]{1,4}|[0-9]+):(0x[0-9a-fA-F]{1,2}|[0-9]+)(:[0-9]+)?$ ]] ||
			{ echo "FATAL: SPX_WSA_SEQ entry '$entry' is not reg:val[:delay_ms]" >&2; exit 1; }
		REG=${entry%%:*}
		REG=$((REG))
		(( REG >= 0x3000 && REG <= 0x36ff )) ||
			{ echo "FATAL: SPX_WSA_SEQ reg $(printf 0x%04x "$REG") outside 0x3000-0x36ff" >&2; exit 1; }
		SEQ_NENTRIES=$((SEQ_NENTRIES + 1))
	done
fi

LOG="/tmp/spx-delta-ab-$(date +%Y%m%d-%H%M%S).log"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
echo "logfile: $LOG"
echo "knobs: TEARDOWN_RESET=$TEARDOWN_RESET GREP_RX0=$GREP_RX0" \
	"PA_VOLUME=$PA_VOLUME BOOST_SWITCH=$BOOST_SWITCH ZERO_ONLY=$ZERO_ONLY" \
	"PORT_MASK=$PORT_MASK SEQ_ENTRIES=$SEQ_NENTRIES SEQ_DEVICES=$SEQ_DEVICES"

MASK_PARAM=/sys/module/snd_soc_wsa881x/parameters/spx_stream_port_mask
[[ -w $MASK_PARAM || -e $MASK_PARAM ]] ||
	{ echo "FATAL: snd_soc_wsa881x is not loaded" >&2; exit 1; }
# Existence checks only: stat never reads spx_reenum (write-only, blocking).
for p in spx_snapshot spx_force_attach spx_reenum; do
	[[ -e /sys/module/soundwire_qcom/parameters/$p ]] ||
		{ echo "FATAL: soundwire_qcom parameter $p missing" >&2; exit 1; }
done
[[ -e drivers/spx_extras/spx_wcd_gpio.ko ]] ||
	{ echo "FATAL: drivers/spx_extras/spx_wcd_gpio.ko is not built" >&2; exit 1; }
if [[ -n $WSA_SEQ || $TEARDOWN_RESET == 1 ]]; then
	[[ -e drivers/spx_extras/spx_wsa_seq.ko ]] ||
		{ echo "FATAL: drivers/spx_extras/spx_wsa_seq.ko is not built" >&2; exit 1; }
fi
for t in ffmpeg aplay amixer timeout; do
	command -v "$t" >/dev/null ||
		{ echo "FATAL: $t not installed" >&2; exit 1; }
done

CARD=$(awk '/Surface Pro X/{print $1}' /proc/asound/cards | head -1)
[[ $CARD =~ ^[0-9]+$ ]] || { echo "FATAL: no Surface Pro X card" >&2; exit 1; }

for n in /dev/snd/controlC* /dev/snd/pcmC*; do
	[ -c "$n" ] && sudo setfacl -m u:"$USER":rw- "$n"
done

echo
echo "=== [0] booted-entry coherence (CLAUDE.md step-[0] stale-expectation rule) ==="
cat <<'ENVBLOCK'
The module-param env block the booted GRUB entry must carry for this A/B to
be interpretable (guarded audio family, verbatim from spx-speaker-v28/v29):

  panic=10 softlockup_panic=1 hung_task_panic=1 oops=panic
  ramoops.console_size=0x20000 printk.always_kmsg_dump=1
  slim_qcom_ngd_ctrl.spx_probe_stage=8 slim_qcom_ngd_ctrl.spx_pio_mode=1
  slim_qcom_ngd_ctrl.spx_allow_full=1 slim_qcom_ngd_ctrl.spx_pin_after_qmi=1
  wcd934x.spx_wsa_en_pin=-1 wcd934x.spx_wsa_gpio_dir=0x06 wcd934x.spx_wsa_gpio_val=0x00
  soundwire_qcom.spx_exact_windows_init=0 soundwire_qcom.spx_core_enum=1
  soundwire_qcom.spx_force_attach=1 soundwire_qcom.spx_no_assign=1
  soundwire_qcom.spx_blind_attach=0 soundwire_qcom.spx_write_dev0=1
  soundwire_qcom.spx_mirror_banks=0 soundwire_qcom.spx_write_twice=0
  soundwire_qcom.spx_bank_switch_repeats=1 soundwire_qcom.spx_watchdog=0
  soundwire_qcom.spx_quiet_bus=0 soundwire_qcom.spx_win_transport=1
  soundwire_qcom.spx_runtime_ssp_period=1 soundwire_qcom.spx_verify_bank=0
  soundwire_qcom.spx_dr_freq=0 soundwire_qcom.spx_port_si=-1
  soundwire_qcom.spx_port_off1=-1 soundwire_qcom.spx_port_off2=-1
  soundwire_qcom.spx_port_bp=-1 soundwire_qcom.spx_frame_phase=1
  soundwire_qcom.spx_actual_phase=0 soundwire_qcom.spx_clk_div=0
  soundwire_qcom.spx_shadow_dp1_enable=1
  snd_soc_wsa881x.spx_write_only=1 snd_soc_wsa881x.spx_powerdown_gpio=1
  snd_soc_wsa881x.spx_blind_rmw=0 snd_soc_wsa881x.spx_stream_port_mask=<mask>
  snd_soc_wsa881x.spx_port_map=0,0,0,0 snd_soc_wsa881x.spx_replay_supplies=1
  snd_soc_wsa881x.spx_init_on_pmu=0 snd_soc_wsa881x.spx_win_pa_seq=1
  snd_soc_wsa881x.spx_sample_edge=-1
  snd_soc_wcd934x.spx_persist_stream=1 q6afe_dai.spx_no_port_stop=0
  q6asm_dai.spx_force_timer_pacing=0 q6asm_dai.spx_keep_asm=1

Ladder #1 (RX0 vs the ADSP SLIM channel-management delta) additionally boots
the v29 argument: q6afe.spx_auto_speaker_cal=1
ENVBLOCK
KEEP_ASM=$(cat /sys/module/q6asm_dai/parameters/spx_keep_asm 2>/dev/null || echo '?')
WRITE_ONLY=$(cat /sys/module/snd_soc_wsa881x/parameters/spx_write_only 2>/dev/null || echo '?')
NO_ASSIGN=$(cat /sys/module/soundwire_qcom/parameters/spx_no_assign 2>/dev/null || echo '?')
[[ $KEEP_ASM == Y || $KEEP_ASM == 1 ]] ||
	{ echo "FATAL: q6asm_dai.spx_keep_asm=$KEEP_ASM -- without keep_asm every" >&2;
	  echo "       stream after the first reports write_done=0 and the second" >&2;
	  echo "       stream of this A/B would be a void measurement." >&2; exit 1; }
[[ $WRITE_ONLY == Y || $WRITE_ONLY == 1 ]] ||
	{ echo "FATAL: snd_soc_wsa881x.spx_write_only=$WRITE_ONLY -- the guarded" >&2;
	  echo "       cold-init replay (and its stable-attachment proof line)" >&2;
	  echo "       only exists in write-only mode." >&2; exit 1; }
grep -qw 'wcd934x.spx_wsa_gpio_dir=0x06' /proc/cmdline &&
grep -qw 'wcd934x.spx_wsa_gpio_val=0x00' /proc/cmdline ||
	echo "WARNING: booted cmdline lacks the guarded wcd934x GPIO args" \
		"(dir=0x06 val=0x00); this runner drives GPIO itself via" \
		"spx_wcd_gpio.ko, but comparisons against guarded-boot runs" \
		"are weakened." >&2
[[ $NO_ASSIGN == 1 ]] ||
	echo "WARNING: soundwire_qcom.spx_no_assign=$NO_ASSIGN (guarded entries" \
		"boot 1)" >&2
echo "keep_asm=$KEEP_ASM write_only=$WRITE_ONLY no_assign=$NO_ASSIGN"

die() { echo "FATAL($1): $2" >&2; exit "$1"; }

MIXER_LOG=/tmp/spx-delta-ab-mixer.log
PHASE_CODE=1
KMSG_MARKER=

kmsg_marker() {
	KMSG_MARKER="SPX_DELTAAB_${1}_${RANDOM}_$(date +%s%N)"
	printf '<6>%s\n' "$KMSG_MARKER" | sudo tee /dev/kmsg >/dev/null
}
begin_phase() {
	PHASE_CODE=$1
	kmsg_marker "$2"
	power_note "phase_$2"
}

# PROGRESS §39: a listening run without a power record is void. Inlined from
# scripts/spx-power-snapshot.sh (same reads, same journal tag) so this runner
# has no sibling-file dependency; every phase marker carries one line.
power_note() {
	read1() { cat "$1" 2>/dev/null || echo '?'; }
	local adp bst bcap line iio vph
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
	echo "  [power] $line"
}

# Serialized controller snapshot, idle only -- verbatim discipline from
# scripts/spx-portmask-sweep.sh. Never call while tone samples flow.
SPX_SNAP_COMP=
SPX_SNAP_SLV=
snapshot() {
	local tag=$1 quiet=${2:-0} marker line
	SPX_SNAP_COMP=; SPX_SNAP_SLV=
	marker="SPX_SWEEP_SNAP_${RANDOM}_$(date +%s%N)"
	printf '<6>%s\n' "$marker" | sudo tee /dev/kmsg >/dev/null
	echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_snapshot \
		>/dev/null 2>&1 || { echo "  $tag: SNAPSHOT FAILED"; return 0; }
	line=$(sudo dmesg | sed -n "/$marker/,\$p" | grep 'SPX SNAPSHOT:' | tail -1)
	if [[ -z $line ]]; then
		echo "  $tag: no snapshot logged"
		return 0
	fi
	local dp4b0 dp4b1
	SPX_SNAP_COMP=$(sed -n 's/.*COMP_PARAMS=\(0x[0-9a-fA-F]\+\).*/\1/p' <<<"$line")
	SPX_SNAP_SLV=$(sed -n 's/.*MCP_SLV_STATUS=\(0x[0-9a-fA-F]\+\).*/\1/p' <<<"$line")
	dp4b0=$(sed -n 's/.*DP4_B0=\(0x[0-9a-fA-F]\+\).*/\1/p' <<<"$line")
	dp4b1=$(sed -n 's/.*DP4_B1=\(0x[0-9a-fA-F]\+\).*/\1/p' <<<"$line")
	(( quiet )) && return 0
	printf '  %s: COMP_PARAMS=%s MCP_SLV_STATUS=%s DP4 B0=%s B1=%s' \
		"$tag" "$SPX_SNAP_COMP" "$SPX_SNAP_SLV" "$dp4b0" "$dp4b1"
	# 0x016840c6 is the AHB bridge canary; anything else means the read path
	# is returning fabricated data and no register value in this run is real.
	[[ $SPX_SNAP_COMP == 0x016840c6 ]] &&
		printf ' [bridge OK]' || printf ' [BRIDGE CANARY BAD]'
	printf '\n'
}

# --- amp power sequencing (guarded recipe, verbatim discipline) -------------
AMP_OFF_SINCE=
gpio() {
	local value=$1 marker block
	kmsg_marker "gpio$value"
	marker=$KMSG_MARKER
	sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val="$value" || true
	block=$(sudo dmesg | sed -n "/$marker/,\$p")
	grep -q "SPX GPIO managed: dir=0x06 val=$value" <<<"$block"
}
park_amp() {
	gpio 0x00 || return 1
	AMP_OFF_SINCE=$(date +%s)
}
power_pin2() {
	# Documented requirement: a power-cycle needs >= 10 s off before
	# power-on. Enforce the floor measured from the last VERIFIED park.
	[[ -n ${AMP_OFF_SINCE:-} ]] || return 1
	local now
	now=$(date +%s)
	while (( now - AMP_OFF_SINCE < 10 )); do
		sleep 1
		now=$(date +%s)
	done
	gpio 0x04
}

# Gate 1: wait for a REAL physical announce (MCP_SLV_STATUS=0x1) before
# touching force-attach. The latch flickers 0x1/0x0 even with the amp
# present, so sample fast and keep the first 0x1 as proof.
wait_device0_announce() {
	local s
	for ((s = 0; s < 40; s++)); do
		snapshot "attach-window" 1
		if [[ $SPX_SNAP_COMP != 0x016840c6 ]]; then
			echo "FATAL: AHB bridge canary invalid ($SPX_SNAP_COMP); reads are fake" >&2
			return 2
		fi
		if [[ $SPX_SNAP_SLV == 0x00000001 ]]; then
			echo "  physical device-0 presence observed after $((s + 1)) sample(s)"
			return 0
		fi
		sleep 0.05
	done
	echo "FATAL: the amp never announced at physical device 0 after GPIO-high." >&2
	echo "       Refusing to play: any later result would be a void measurement," >&2
	echo "       not a result about the delta under test." >&2
	return 1
}

# Gate 2: force-attach + re-enumerate, then require BOTH the driver's
# stable-attachment line AND the wsa881x cold-init replay line. spx_reenum is
# WRITE-ONLY here by policy; never read it.
bring_up_amp() {
	kmsg_marker enum
	local marker=$KMSG_MARKER i enum_log
	echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_force_attach >/dev/null
	echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_reenum >/dev/null
	for ((i = 0; i < 300; i++)); do
		enum_log=$(sudo dmesg | sed -n "/$marker/,\$p")
		if grep -q 'SPX FORCE-ATTACH: stable attachment' <<<"$enum_log" &&
		   grep -q 'SPX: initializing amplifier at SoundWire device 1' <<<"$enum_log"
		then
			echo "  stable attachment + cold-init replay confirmed"
			return 0
		fi
		sleep 0.1
	done
	echo "FATAL: force-attach never reached stable attachment with a cold-init replay." >&2
	return 1
}

# Replay a seq string through spx_wsa_seq.ko and require every entry to have
# landed. The module deliberately fails insmod with -EAGAIN so it can be
# re-run without rmmod; validate the FRESH dmesg output instead of insmod's
# status. One "SPX seq" log line per accepted entry, rc<0 on write failure.
seq_replay() {
	local what=$1 want=$2 marker block n_ok n_bad n_want
	[[ -n $want ]] || return 0
	IFS=',' read -r -a _WANT_ENTRIES <<<"$want"
	n_want=${#_WANT_ENTRIES[@]}
	kmsg_marker "seq_$what"
	marker=$KMSG_MARKER
	sudo insmod drivers/spx_extras/spx_wsa_seq.ko \
		devices="$SEQ_DEVICES" seq="$want" || true
	block=$(sudo dmesg | sed -n "/$marker/,\$p")
	n_ok=$(grep -c 'SPX seq ' <<<"$block" || true)
	n_bad=$(grep -Ec 'rc=-|skip bad' <<<"$block" || true)
	if (( n_ok != n_want )) || (( n_bad != 0 )); then
		echo "FATAL: $what seq replay incomplete ($n_ok/$n_want writes ok, $n_bad bad)" >&2
		grep 'SPX seq\|not found\|skip bad' <<<"$block" | tail -8 >&2 || true
		return 1
	fi
	echo "  $what seq applied ($n_ok/$n_want writes ok)"
}

# --- mixer path (endpoint B / pin2 / S16), verbatim from the sweep's [D] ----
set_ctl() {
	amixer -c "$CARD" cset name="$1" "$2" >> "$MIXER_LOG" 2>&1 ||
		die "$PHASE_CODE" "mixer ctl $1=$2 failed (see $MIXER_LOG)"
}
mixer_path() {
	set_ctl 'SLIMBUS_2_RX Audio Mixer MultiMedia1' 1
	set_ctl 'SLIM RX0 MUX' AIF1_PB
	set_ctl 'SLIM RX1 MUX' AIF1_PB
	set_ctl 'RX INT8_1 MIX1 INP0' RX1
	set_ctl 'COMP8 Switch' 1
	set_ctl 'RX8 Digital Volume' 84
	set_ctl 'SpkrRight COMP Switch' 0
	set_ctl 'SpkrRight VISENSE Switch' 0
	set_ctl 'SpkrRight BOOST Switch' "$BOOST_SWITCH"
	set_ctl 'SpkrRight DAC Switch' 1
	# Force-write the gain: a plain re-set is an ALSA no-op while the hardware
	# register has been reseeded to the 0 dB floor by the power cycle.
	set_ctl 'SpkrRight PA Volume' 0
	if (( PA_VOLUME != 0 )); then
		set_ctl 'SpkrRight PA Volume' "$PA_VOLUME"
	fi
	echo "  PA Volume force-written 0 -> $PA_VOLUME"
	set_ctl 'SpkrRight Smart Boost Level' 0
}

# --- per-stream evidence ------------------------------------------------------
kernel_evidence() {
	sudo dmesg | sed -n "/$1/,\$p" |
		grep -E 'active_ports=|SPX ASM stream|PA DAPM event|shadow (slave|master) DP|overflow|XRUN|Oops|BUG:' |
		head -40 || true
}
check_faults() {
	local block
	block=$(sudo dmesg | sed -n "/$1/,\$p")
	if grep -Eq 'Oops|BUG:' <<<"$block"; then
		echo "FATAL: kernel-fault indicator (Oops/BUG:) since $1" >&2
		grep -E 'Oops|BUG:' <<<"$block" | head -5 >&2
		exit 50
	fi
}

# Count RX0 overflow lines strictly inside one kmsg window [start,end).
# Markers are alnum+underscore only, so plain substring matching is exact.
rx0_count() {
	sudo dmesg | awk -v s="$1" -v e="$2" '$0 ~ e { exit } index($0, s) { f = 1 } f' |
		grep -c 'overflow error on RX port 0' || true
}

ORIGINAL_MASK=
cleanup() {
	sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x00 2>/dev/null || true
	if [[ -n ${ORIGINAL_MASK:-} ]]; then
		echo "$ORIGINAL_MASK" | sudo tee "$MASK_PARAM" >/dev/null 2>&1 || true
	fi
}
trap cleanup EXIT

# --- preflight: descriptor mask + test waveform -----------------------------
ORIGINAL_MASK=$(cat "$MASK_PARAM")
if (( ORIGINAL_MASK != PORT_MASK )); then
	echo "$PORT_MASK" | sudo tee "$MASK_PARAM" >/dev/null
fi
READBACK=$(cat "$MASK_PARAM")
[[ $READBACK == "$PORT_MASK" ]] ||
	{ echo "FATAL: port mask readback $READBACK != $PORT_MASK" >&2; exit 1; }
echo "descriptor mask = $READBACK"
power_note preflight

WAV=/tmp/spx-delta-ab.wav
if (( ZERO_ONLY == 1 )); then
	echo "=== building waveform: 11 s PURE digital zero (SPX_ZERO_ONLY=1) ==="
	ffmpeg -nostdin -v error \
		-f lavfi -i anullsrc=r=48000:cl=stereo:d=11 \
		-c:a pcm_s16le -y "$WAV"
else
	echo "=== building waveform: 3 s zero -> 5 s 440 Hz (C1/right) -> 3 s zero ==="
	ffmpeg -nostdin -v error \
		-f lavfi -i anullsrc=r=48000:cl=stereo:d=3 \
		-f lavfi -i sine=frequency=440:sample_rate=48000:duration=5 \
		-f lavfi -i anullsrc=r=48000:cl=stereo:d=3 \
		-filter_complex "[1:a]volume=0.8,pan=stereo|c0=0*c0|c1=c0[tone];[0:a][tone][2:a]concat=n=3:v=0:a=1[out]" \
		-map '[out]' -c:a pcm_s16le -y "$WAV"
fi
echo "waveform sha256: $(sha256sum "$WAV" | cut -d' ' -f1)"

# One guarded bring-up -> optional delta -> ONE stream, per phase.
run_stream() {
	local sid=$1 wav_label
	begin_phase "$PHASE_CODE" "$sid"

	park_amp ||
		die "$PHASE_CODE" "could not verify both amps parked (GPIO managed val=0x00)"
	echo "  powering pin2 (enforces the >= 10 s park floor)..."
	power_pin2 ||
		die "$PHASE_CODE" "could not verify pin2 powered (GPIO managed val=0x04)"
	sleep 0.2
	local rc=0
	wait_device0_announce || rc=$?
	(( rc == 0 )) ||
		die "$PHASE_CODE" "device-0 announce gate failed (rc=$rc: 1=no announce, 2=canary bad)"
	bring_up_amp ||
		die "$PHASE_CODE" "cold-init replay gate failed"

	if [[ -n $WSA_SEQ && $SEQ_STREAM2_ONLY == 1 && $sid == stream1 ]]; then
		echo "  (SPX_SEQ_STREAM2_ONLY=1: stream1 is the legacy control, no seq)"
	elif [[ -n $WSA_SEQ ]]; then
		seq_replay "delta-$sid" "$WSA_SEQ" ||
			die "$PHASE_CODE" "delta seq replay failed before stream $sid"
	elif (( TEARDOWN_RESET == 1 )); then
		echo "  (no SPX_WSA_SEQ; teardown reset was the only extra write)"
	fi

	snapshot "$sid-post-attach"
	mixer_path

	if (( ZERO_ONLY == 1 )); then
		wav_label="all 11 s digital zero (no tone)"
	else
		wav_label="0-3 s zeros | 3-8 s 440 Hz (right) | 8-11 s zeros"
	fi
	local c
	for ((c = COUNTDOWN_S; c >= 1; c--)); do
		echo ">>> stream $sid in $c..."
		sleep 1
	done
	kmsg_marker "${sid}_START"
	local start=$KMSG_MARKER
	echo ">>> STREAM $sid PLAYING (11 s) FROM $(date +%T): $wav_label"
	timeout -k 2 20 aplay -D "plughw:${CARD},0" \
		--period-size=12000 --buffer-size=48000 "$WAV" \
		> "/tmp/spx-delta-ab-aplay-$sid.log" 2>&1 &
	local apid=$!
	# Serialized snapshot INSIDE the leading digital-zero prefix only (~165 ms
	# shared-bridge transaction; PROGRESS.md §28).
	sleep 0.9
	snapshot "$sid-leading-zeros"
	local aprc=0
	wait "$apid" || aprc=$?
	(( aprc == 0 )) ||
		echo "WARNING: aplay exited rc=$aprc (log: /tmp/spx-delta-ab-aplay-$sid.log)" >&2
	# Give the delayed PCM close time to emit the SPX ASM stream summary
	# before closing the evidence window.
	sleep 3
	kmsg_marker "${sid}_END"
	check_faults "$start"

	local asm_line sub wd fb rx0
	asm_line=$(sudo dmesg | sed -n "/$start/,\$p" | grep 'SPX ASM stream' | tail -1 || true)
	sub=$(sed -n 's/.*submitted=\([0-9]*\).*/\1/p' <<<"${asm_line:-}")
	wd=$(sed -n 's/.*write_done=\([0-9]*\).*/\1/p' <<<"${asm_line:-}")
	fb=$(sed -n 's/.*fallback=\([0-9]*\).*/\1/p' <<<"${asm_line:-}")
	rx0=$(rx0_count "$start" "$KMSG_MARKER")
	echo "--- stream $sid evidence ---"
	echo "  ASM: ${asm_line:-<no SPX ASM stream line found>}"
	echo "  RX0 overflow lines in this stream window: $rx0"
	if [[ -z $sub || -z $wd ]]; then
		echo "  WARNING: could not parse Q6 counters; stream $sid validity UNPROVEN" >&2
	elif (( wd == 0 )); then
		echo "  WARNING: DSP CONSUMED NOTHING (write_done=0): stream $sid is a" >&2
		echo "           VOID measurement (first-stream-only bug not fixed this boot?)" >&2
	elif (( fb > 0 )); then
		echo "  WARNING: fallback=$fb -- timer pacing intervened; judge with care" >&2
	fi
	kernel_evidence "$start"
	RX0_COUNTS+=("$rx0")
}

RX0_COUNTS=()

echo
echo "############################################################"
echo "### PHASE 1: guarded bring-up + STREAM 1"
echo "############################################################"
PHASE_CODE=10
run_stream stream1

if (( TEARDOWN_RESET == 1 )); then
	echo
	echo "=== Windows teardown soft-reset (§48 #5): 0x300b=0x07 then 0x3005=0x00 ==="
	# Order is load-bearing: SWR_RESET_EN arms the reset sources, CDC_RST_CTL
	# fires them. Both are plain slave writes in range 0x3000-0x36ff.
	seq_replay teardown_reset '0x300b:0x07:0,0x3005:0x00:0' ||
		die 20 "teardown soft-reset replay failed"
fi

echo
echo "############################################################"
echo "### PHASE 2: guarded re-bring-up + STREAM 2"
echo "############################################################"
PHASE_CODE=20
run_stream stream2

echo
echo "############################################################"
echo "### PHASE 3: final park"
echo "############################################################"
PHASE_CODE=30
begin_phase 30 phaseP
park_amp || die 30 "final park could not be verified"
snapshot "post-park"
check_faults "$KMSG_MARKER"

echo
echo "======================= RESULT SUMMARY ======================="
echo "streams played : 2 (both under identical software except the knobs below)"
echo "knobs          : TEARDOWN_RESET=$TEARDOWN_RESET GREP_RX0=$GREP_RX0 PA_VOLUME=$PA_VOLUME"
echo "                 BOOST_SWITCH=$BOOST_SWITCH ZERO_ONLY=$ZERO_ONLY PORT_MASK=$PORT_MASK"
if [[ -n $WSA_SEQ ]]; then
	echo "WSA_SEQ        : $WSA_SEQ"
fi
if (( GREP_RX0 == 1 )) && (( ${#RX0_COUNTS[@]} == 2 )); then
	N1=${RX0_COUNTS[0]} N2=${RX0_COUNTS[1]}
	echo "RX0 overflow   : stream1=$N1 stream2=$N2  (ratelimited: lower bounds)"
	cat <<INTERP
Interpretation (§48.6 #1):
  both > 0 ............ RX0 overflow persists under this delta; delta did not
                        clear the per-stream overflow signature.
  stream1 > 0, N2 == 0  delta CORRELATES with the overflow clearing; repeat
                        once, then flip the delta off (re-run bare) to prove
                        it is the cause and not drift.
  both == 0 ........... overflow not reproduced this boot; the baseline itself
                        moved -- interpret nothing else from this run.
INTERP
elif (( GREP_RX0 == 0 )); then
	echo "RX0 overflow   : re-run with SPX_GREP_RX0=1 for the per-stream diff table"
fi
echo
echo "Record your listening observations next to this run's log: $LOG"
echo "(power-state lines above are part of the record; a silent run without"
echo "them is void per PROGRESS §39.)"
exit 0
