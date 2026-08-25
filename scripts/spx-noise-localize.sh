#!/bin/bash
# SPX broadband-static localization: four-phase listening protocol.
#
# 2026-08-22 established (CLAUDE.md, PROGRESS.md §33) that the residual static
# does NOT scale with SpkrRight PA Volume, so it bypasses the PA gain stage,
# and every digital knob tested so far (framing, packing, sample edge,
# descriptor count, boost, interpolator routing) has come back negative.
# Before spending more listens on hypotheses, this script localizes WHERE the
# noise enters, using the proven endpoint B / sink 8 / C1 / MP4-SPK2 / GPIO
# pin2 / S16 audible baseline and four cheap listening windows:
#
#   A ROOM BASELINE   amp parked off              -> ambient room noise?
#   B AMP IDLE        powered, attached, cold-init replayed, output stage
#                     ENABLED by direct register writes (no PCM: DAPM ties
#                     the PA chain to the AIF stream widgets, so mixer-only
#                     would leave the PA dead and the window meaningless)
#                     -> amp analog idle noise, no data path at all?
#   C STREAM TEST     one PCM: 3 s digital zero -> 5 s 440 Hz -> 3 s zero
#                     -> data-path/modulator noise, and in which interval?
#   D POST PARK       amp parked again             -> residual amp state?
#
# The mid-stream controller snapshot is scheduled ONLY inside the leading
# digital-zero prefix (~165 ms shared-bridge transaction, PROGRESS.md §28; a
# mid-tone bridge read coincided with an audible glitch on 2026-08-22).
#
# Usage: spx-noise-localize.sh            (no arguments)
#
# Env knobs (defaults mirror scripts/spx-portmask-sweep.sh exactly):
#   SPX_PA_VOLUME=12     PA gain force-written after cold init (12 = +18 dB)
#   SPX_BOOST_SWITCH=1   analog boost switch state during the stream
#   SPX_ZERO_ONLY=0      1 replaces the 5 s tone with silence (11 s of zero)
#   SPX_PORT_MASK=1      SoundWire descriptor mask (1 = DAC-only v28 baseline)
#
# Exit codes:
#   0   all four phases completed, matrix printed
#   1   usage or preflight failure (module/card/tool missing, bad knob)
#   10  Phase A: the park (GPIO 0x43 val=0x00) could not be verified
#   20  Phase B: pin2 power-up unverified, no device-0 announce, bridge
#       canary invalid, no stable attachment + cold-init replay, or a mixer /
#       PA force-write failed
#   30  Phase C: any Phase-B-type failure during the second bring-up
#   40  Phase D: the final park could not be verified
#   50  kernel-fault indicator (Oops/BUG:) observed since the phase marker
#
# HARD RULES encoded (CLAUDE.md). This script never:
#   - reboots or powers off the machine;
#   - rmmods soundwire_qcom (re-probe oopses; reboot-only recovery);
#   - READS /sys/module/soundwire_qcom/parameters/spx_reenum (write-only, a
#     read blocks forever) -- it is only ever written via `sudo tee`;
#   - reads pinctrl debugfs pinmux-pins/pins (oops, mutex held until reboot);
#   - reads MMIO around 171c0000 (+0x2000 wedges the CPU);
#   - probes rpmsg/GLINK channels (ADSP crash).
#
# Run as the desktop user, never through sudo. The amp is parked off at exit.

set -euo pipefail
if (( EUID == 0 )); then echo "FATAL: run as desktop user, not sudo" >&2; exit 1; fi
cd "$(dirname "$0")/.."
sudo -v || exit 1

(( $# == 0 )) || { echo "usage: $0 (no arguments)" >&2; exit 1; }

PA_VOLUME=${SPX_PA_VOLUME:-12}
BOOST_SWITCH=${SPX_BOOST_SWITCH:-1}
ZERO_ONLY=${SPX_ZERO_ONLY:-0}
PORT_MASK=${SPX_PORT_MASK:-1}
# Listen-window lengths are timing only -- they change nothing about the
# audio path. Widen them when the listener needs more than 6 s per phase.
LISTEN_S=${SPX_LISTEN_S:-6}
COUNTDOWN_S=${SPX_COUNTDOWN_S:-3}
# Rescue-probe headroom knobs. Defaults are the proven audible baseline
# (RX8 Digital Volume 84, boost rail floor 6.625 V); raise them ONLY for an
# explicit max-headroom audibility probe -- that changes level, not routing.
RX8_VOLUME=${SPX_RX8_VOLUME:-84}
BOOST_LEVEL=${SPX_BOOST_LEVEL:-0}
# R2 probe (watermark-RCA report 2026-08-23): kill the CODEC's own SBOOST1
# switching regulator clock (WCD934X_BOST1_PATH_CTL 0x0c21 bit0) inside the
# leading-zero prefix. The §33 boost A/B toggled the AMP's boost only; this
# converter sits on the codec die beside the DSMDEM/SWR serializer and its
# ripple would be gain-independent -- the one register-reachable, never-tested
# item in the correct zone. Default off = byte-identical behavior.
SBOOST_OFF=${SPX_SBOOST_OFF:-0}
[[ $RX8_VOLUME =~ ^[0-9]+$ ]] && (( RX8_VOLUME >= 0 && RX8_VOLUME <= 124 )) ||
	{ echo "FATAL: SPX_RX8_VOLUME must be 0..124" >&2; exit 1; }
[[ $BOOST_LEVEL =~ ^[0-9]+$ ]] && (( BOOST_LEVEL >= 0 && BOOST_LEVEL <= 15 )) ||
	{ echo "FATAL: SPX_BOOST_LEVEL must be 0..15" >&2; exit 1; }
[[ $LISTEN_S =~ ^[0-9]+$ ]] && (( LISTEN_S >= 1 )) ||
	{ echo "FATAL: SPX_LISTEN_S must be >= 1" >&2; exit 1; }
[[ $COUNTDOWN_S =~ ^[0-9]+$ ]] && (( COUNTDOWN_S >= 1 )) ||
	{ echo "FATAL: SPX_COUNTDOWN_S must be >= 1" >&2; exit 1; }
[[ $PA_VOLUME =~ ^[0-9]+$ ]] ||
	{ echo "FATAL: SPX_PA_VOLUME must be numeric" >&2; exit 1; }
[[ $BOOST_SWITCH =~ ^[01]$ ]] ||
	{ echo "FATAL: SPX_BOOST_SWITCH must be 0 or 1" >&2; exit 1; }
[[ $ZERO_ONLY =~ ^[01]$ ]] ||
	{ echo "FATAL: SPX_ZERO_ONLY must be 0 or 1" >&2; exit 1; }
[[ $PORT_MASK =~ ^[0-9]+$ ]] ||
	{ echo "FATAL: SPX_PORT_MASK must be numeric" >&2; exit 1; }
[[ $SBOOST_OFF =~ ^[01]$ ]] ||
	{ echo "FATAL: SPX_SBOOST_OFF must be 0 or 1" >&2; exit 1; }

LOG="/tmp/spx-noise-localize-$(date +%Y%m%d-%H%M%S).log"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
echo "logfile: $LOG"
echo "knobs: PA_VOLUME=$PA_VOLUME BOOST_SWITCH=$BOOST_SWITCH" \
	"ZERO_ONLY=$ZERO_ONLY PORT_MASK=$PORT_MASK SBOOST_OFF=$SBOOST_OFF"

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
[[ -e drivers/spx_extras/spx_wsa_seq.ko ]] ||
	{ echo "FATAL: drivers/spx_extras/spx_wsa_seq.ko is not built" >&2; exit 1; }
for t in ffmpeg aplay amixer timeout; do
	command -v "$t" >/dev/null ||
		{ echo "FATAL: $t not installed" >&2; exit 1; }
done

CARD=$(awk '/Surface Pro X/{print $1}' /proc/asound/cards | head -1)
[[ $CARD =~ ^[0-9]+$ ]] || { echo "FATAL: no Surface Pro X card" >&2; exit 1; }

for n in /dev/snd/controlC* /dev/snd/pcmC*; do
	[ -c "$n" ] && sudo setfacl -m u:"$USER":rw- "$n"
done

MIXER_LOG=/tmp/spx-noise-localize-mixer.log
PHASE_CODE=1
PHASE_MARKER=
ORIGINAL_MASK=

set_ctl() {
	amixer -c "$CARD" cset name="$1" "$2" >> "$MIXER_LOG" 2>&1 ||
		{ echo "FATAL: mixer ctl $1=$2 (see $MIXER_LOG)" >&2; exit "$PHASE_CODE"; }
}

die() { echo "FATAL($1): $2" >&2; exit "$1"; }

# --- kmsg markers + log slicing (guarded-harness convention) ---------------
KMSG_MARKER=
kmsg_marker() {
	KMSG_MARKER="SPX_LOCALIZE_${1}_${RANDOM}_$(date +%s%N)"
	printf '<6>%s\n' "$KMSG_MARKER" | sudo tee /dev/kmsg >/dev/null
}
begin_phase() {
	PHASE_CODE=$1
	kmsg_marker "$2"
	PHASE_MARKER=$KMSG_MARKER
	power_note "phase_$2"
}

# PROGRESS §39: a listening run without a power record is void. Every phase
# marker carries one journal+log line of AC/battery/rail/thermal context.
power_note() {
	local line
	line=$(scripts/spx-power-snapshot.sh "$1" 2>&1) || true
	echo "  [power] $line"
}

# Serialized controller snapshot, idle only -- verbatim from
# scripts/spx-portmask-sweep.sh. CLAUDE.md testing etiquette: never ask the
# user about a run whose preconditions were invalid, and a detached amp is
# exactly that. Never call this while tone samples flow: the shared
# WCD/SLIMbus bridge transaction costs ~165 ms and audibly cuts the stream.
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

# --- amp power sequencing ---------------------------------------------------
# spx_wcd_gpio.ko does its regmap work in init and deliberately fails the
# load with -EAGAIN so it never stays resident; validate its fresh dmesg
# output instead of insmod's status (guarded-harness set_amp_gpio recipe).
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
	# power-on. Enforce the floor measured from the last VERIFIED park, and
	# refuse to power at all without one.
	[[ -n ${AMP_OFF_SINCE:-} ]] || return 1
	local now
	now=$(date +%s)
	while (( now - AMP_OFF_SINCE < 10 )); do
		sleep 1
		now=$(date +%s)
	done
	gpio 0x04
}

# --- attach proof (both gates of the guarded recipe, as in the sweep) -------
# Gate 1: wait for a REAL physical announce (MCP_SLV_STATUS=0x1) before
# touching force-attach. The latch flickers 0x1/0x0 even with the amp
# present, so sample fast and keep the first 0x1 as proof. Returns
# 0 = announced, 1 = never announced, 2 = bridge canary went bad.
wait_device0_announce() {
	local s expect=${SPX_EXPECT_STATUS:-0x00000001}
	for ((s = 0; s < 40; s++)); do
		snapshot "attach-window" 1
		if [[ $SPX_SNAP_COMP != 0x016840c6 ]]; then
			echo "FATAL: AHB bridge canary invalid ($SPX_SNAP_COMP); reads are fake" >&2
			return 2
		fi
		if [[ $SPX_SNAP_SLV == 0x00000001 || $SPX_SNAP_SLV == "$expect" ]]; then
			if [[ $SPX_SNAP_SLV == 0x00000001 ]]; then
				echo "  physical device-0 presence observed after $((s + 1)) sample(s)"
			else
				echo "  amp answering at expected enumerated address $SPX_SNAP_SLV after $((s + 1)) sample(s)"
			fi
			return 0
		fi
		sleep 0.05
	done
	echo "FATAL: the amp never announced at the expected address ($expect) after GPIO-high." >&2
	echo "       Refusing to continue: any later result would be a void" >&2
	echo "       measurement (Q6 counters cannot see a detached amp)." >&2
	return 1
}

# Gate 2: force-attach + re-enumerate, then require BOTH the driver's
# stable-attachment line AND the wsa881x cold-init replay line, instead of
# sleeping a guess. spx_reenum is WRITE-ONLY here by policy; never read it.
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

# --- mixer path (endpoint B / pin2 / S16), verbatim from the sweep's [D] ----
# The PA gain is FORCE-written (0 then target): after the cold-init replay
# the hardware register sits at the 0 dB floor and a plain re-set is an ALSA
# no-op. SPX_PA_VOLUME partitions the search space (12 = +18 dB baseline).
mixer_path() {
	set_ctl 'SLIMBUS_2_RX Audio Mixer MultiMedia1' 1
	set_ctl 'SLIM RX0 MUX' AIF1_PB
	set_ctl 'SLIM RX1 MUX' AIF1_PB
	set_ctl 'RX INT8_1 MIX1 INP0' RX1
	set_ctl 'COMP8 Switch' 1
	set_ctl 'RX8 Digital Volume' "$RX8_VOLUME"
	set_ctl 'SpkrRight COMP Switch' 0
	set_ctl 'SpkrRight VISENSE Switch' 0
	set_ctl 'SpkrRight BOOST Switch' "$BOOST_SWITCH"
	set_ctl 'SpkrRight DAC Switch' 1
	set_ctl 'SpkrRight PA Volume' 0
	if (( PA_VOLUME != 0 )); then
		set_ctl 'SpkrRight PA Volume' "$PA_VOLUME"
	fi
	echo "  PA Volume force-written 0 -> $PA_VOLUME"
	set_ctl 'SpkrRight Smart Boost Level' "$BOOST_LEVEL"
}

# Phase B only. The ALSA route cannot power the PA without an open PCM: the
# DAC/PA DAPM chain hangs off the AIF stream widgets ("SPX: PA DAPM event"
# fires only at stream start/stop), so with no stream the mixer writes above
# leave the output stage dead and the listen window would prove nothing.
# Stage the profile-3 analog skeleton by DIRECT register write instead --
# exactly the values wsa881x.c's own PA_WRITE path programs (DAC_CTL=c2,
# OCP_CTL=b4, gain ramp c9->09 = +18 dB REG mode, DRV_EN fc -> fd, BIAS_CAL=
# ac), minus the ANA_CTL bit-2 latch pulse, which spx_wsa_seq cannot do as a
# masked update and a full-byte write to 0x300a could clobber unknown
# reset-default bits. Verified through the module's dmesg log (it always
# fails insmod with -EAGAIN by design).
stage_pa_direct() {
	local marker block n_writes n_errs
	kmsg_marker pab
	marker=$KMSG_MARKER
	sudo insmod drivers/spx_extras/spx_wsa_seq.ko \
		devices=sdw:0:0:0217:2010:00:2 \
		seq=0x311c:0xc2:1,0x311f:0xb4:1,0x311b:0xc9:1,0x311b:0xb9:1,0x311b:0xa9:1,0x311b:0x99:1,0x311b:0x89:1,0x311b:0x79:1,0x311b:0x69:1,0x311b:0x59:1,0x311b:0x49:1,0x311b:0x39:1,0x311b:0x29:1,0x311b:0x19:1,0x311b:0x09:1,0x311a:0xfc:2,0x311a:0xfd:1,0x3126:0xac:1 \
		|| true
	block=$(sudo dmesg | sed -n "/$marker/,\$p")
	n_writes=$(grep -c 'SPX seq ' <<<"$block" || true)
	n_errs=$(grep -c 'rc=-' <<<"$block" || true)
	if (( n_writes != 18 )) || (( n_errs != 0 )); then
		echo "FATAL: direct PA staging incomplete ($n_writes/18 writes ok, $n_errs errors)" >&2
		grep 'SPX seq\|not found\|skip bad' <<<"$block" | tail -8 >&2 || true
		return 1
	fi
	echo "  PA staged directly: DAC_CTL=c2 OCP=b4 gain ramp c9->09 DRV_EN=fd BIAS_CAL=ac (no PCM)"
}

# --- evidence + fault scan ---------------------------------------------------
kernel_evidence() {
	sudo dmesg | sed -n "/$1/,\$p" |
		grep -E 'active_ports=|SPX ASM stream|PA DAPM event|shadow (slave|master) DP|overflow|XRUN|Oops|BUG:' |
		head -30 || true
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

WAV=/tmp/spx-noise-localize.wav
if (( ZERO_ONLY == 1 )); then
	echo "=== building waveform: 11 s PURE digital zero (SPX_ZERO_ONLY=1) ==="
	ffmpeg -nostdin -v error \
		-f lavfi -i anullsrc=r=48000:cl=stereo:d=11 \
		-c:a pcm_s16le -y "$WAV"
	LISTEN_C="all 11 s digital zero (control: no tone at all)"
else
	echo "=== building waveform: 3 s zero -> 5 s 440 Hz (C1/right) -> 3 s zero ==="
	ffmpeg -nostdin -v error \
		-f lavfi -i anullsrc=r=48000:cl=stereo:d=3 \
		-f lavfi -i sine=frequency=440:sample_rate=48000:duration=5 \
		-f lavfi -i anullsrc=r=48000:cl=stereo:d=3 \
		-filter_complex "[1:a]volume=0.8,pan=stereo|c0=0*c0|c1=c0[tone];[0:a][tone][2:a]concat=n=3:v=0:a=1[out]" \
		-map '[out]' -c:a pcm_s16le -y "$WAV"
	LISTEN_C="0-3 s zeros | 3-8 s 440 Hz (right) | 8-11 s zeros"
fi
echo "waveform sha256: $(sha256sum "$WAV" | cut -d' ' -f1)"

###############################################################################
echo
echo "############################################################"
echo "### PHASE A: ROOM BASELINE (amp off)"
echo "############################################################"
begin_phase 10 phaseA
park_amp ||
	die 10 "could not verify both amps parked (GPIO 0x43 managed val=0x00)"
echo "  both amps verified parked (GPIO low)"
echo ">>> LISTEN for ${LISTEN_S} s from $(date +%T): any hum / static / buzz with the amplifier OFF?"
echo ">>> Noise heard HERE is ambient room noise, not the speaker path."
sleep "$LISTEN_S"
check_faults "$PHASE_MARKER"

###############################################################################
echo
echo "############################################################"
echo "### PHASE B: AMP IDLE (powered, attached, NO stream)"
echo "############################################################"
begin_phase 20 phaseB
echo "  powering pin2 (waits out the >= 10 s park floor from Phase A)..."
power_pin2 || die 20 "could not verify pin2 powered (GPIO 0x43 managed val=0x04)"
sleep 0.2
RC=0
wait_device0_announce || RC=$?
(( RC == 0 )) || die 20 "device-0 announce gate failed (rc=$RC: 1=no announce, 2=canary bad)"
bring_up_amp || die 20 "cold-init replay gate failed"
snapshot "B-post-attach"
mixer_path
stage_pa_direct || die 20 "direct PA staging failed"
echo "  NO PCM IS OPENED: amp powered + attached, output stage ENABLED, no data."
echo ">>> LISTEN for ${LISTEN_S} s starting $(date +%T):"
echo ">>>   silence -> the amp's analog idle (PA enabled, zero data) is clean;"
echo ">>>   static  -> the amp self-noises with NO data path at all:"
echo ">>>             bias/bandgap/output-stage domain, post-gain confirmed."
sleep "$LISTEN_S"
kernel_evidence "$PHASE_MARKER"
check_faults "$PHASE_MARKER"

###############################################################################
echo
echo "############################################################"
echo "### PHASE C: PARK -> >=10 s OFF -> FULL BRING-UP -> ONE STREAM"
echo "############################################################"
begin_phase 30 phaseC
park_amp || die 30 "could not park the amp before the stream test"
echo "  amp parked; power_pin2 enforces the documented >= 10 s power-off"
power_pin2 || die 30 "could not verify pin2 powered for the stream test"
sleep 0.2
RC=0
wait_device0_announce || RC=$?
(( RC == 0 )) || die 30 "device-0 announce gate failed (rc=$RC: 1=no announce, 2=canary bad)"
bring_up_amp || die 30 "cold-init replay gate failed"
snapshot "C-post-attach"
mixer_path

echo
echo ">>> THE ONLY STREAM OF THIS RUN starts after the countdown."
echo ">>> Timeline: $LISTEN_C"
echo ">>> LISTEN FOR: static during FIRST zeros? during TONE? during TRAILING zeros?"
for ((c = COUNTDOWN_S; c >= 1; c--)); do
	echo ">>> stream in $c..."
	sleep 1
done
echo ">>> STREAM PLAYING (11 s) FROM $(date +%T): $LISTEN_C"
APLAY_LOG=/tmp/spx-noise-localize-aplay-C.log
timeout -k 2 20 aplay -D "plughw:${CARD},0" \
	--period-size=12000 --buffer-size=48000 "$WAV" \
	> "$APLAY_LOG" 2>&1 &
APLAY_PID=$!
# Mid-stream controller snapshot INSIDE the leading digital-zero prefix
# only. The shared-bridge read costs ~165 ms (PROGRESS.md §28) and a
# mid-tone read coincided with an audible glitch (2026-08-22). At ~0.9 s
# after launch the stream is still > 2 s away from the first tone sample.
sleep 0.9
snapshot "C-leading-zeros"
if (( SBOOST_OFF == 1 )); then
	# Still > 2 s from the first tone sample. One write, one variable.
	echo "0x0c21 0x00" | sudo tee /sys/kernel/debug/217:250:1:0/write_reg >/dev/null \
		&& echo "  SBOOST1 clock killed (0x0c21=0x00) during zero prefix" \
		|| echo "  WARNING: SBOOST1 write_reg failed" >&2
	snapshot "C-post-sboost-off"
fi
APLAY_RC=0
wait "$APLAY_PID" || APLAY_RC=$?
(( APLAY_RC == 0 )) ||
	echo "WARNING: aplay exited rc=$APLAY_RC (log: $APLAY_LOG); judge with care" >&2
sleep 2
snapshot "C-post-tone"
echo "--- kernel evidence for the Phase C stream ---"
kernel_evidence "$PHASE_MARKER"
check_faults "$PHASE_MARKER"

###############################################################################
echo
echo "############################################################"
echo "### PHASE D: POST PARK (amp off again)"
echo "############################################################"
begin_phase 40 phaseD
park_amp || die 40 "final park could not be verified"
snapshot "D-post-park"
echo ">>> LISTEN for ${LISTEN_S} s from $(date +%T): any static now that the amp is PARKED OFF again?"
sleep "$LISTEN_S"
check_faults "$PHASE_MARKER"

###############################################################################
echo
cat <<'MATRIX'

======================= INTERPRETATION MATRIX =======================
Intervals: A = room baseline (amp OFF), B = amp idle (powered, NO stream),
Cz1 = stream leading zeros (0-3 s), Ct = stream 440 Hz tone (3-8 s),
Cz2 = stream trailing zeros (8-11 s), D = post park (amp OFF again).

A noisy (whatever the rest) ............ AMBIENT ROOM NOISE. Nothing about
    the speaker path was measured this run; every static observation from
    earlier sessions is PRIOR-MEASUREMENTS-INVALID until a quiet A is on
    record. Next: eliminate the source / change rooms, re-run this script.

A quiet, B noisy ....................... AMP ANALOG SELF-NOISE. The output
    stage was live (direct PA-enable writes) with NO data path at all:
    bias/bandgap/output-stage instability, post-gain confirmed directly.
    Next: BIAS_PSRR 0x44->0x45 + spx_rearm_init, then profile 3, then
    BIAS_INT un-zero -- all live knob/seq changes, one listen each.

A,B quiet, C noisy in ALL THREE Cz1/Ct/Cz2  DATA-PATH OR MODULATOR NOISE.
    Noise rides the enabled stream regardless of sample content: PDM
    clock/carrier desync or the codec SWR data source, upstream of the PA
    gain stage (consistent with the 2026-08-22 gain finding). Next:
    serialized DP1/DP4 snapshot vs the Windows descriptor table; codec
    interpolator -> SWR source routing. Digital transport knobs upstream
    of the PA gain remain dead ends.

A,B quiet, Ct noisy ONLY ............... DATA-DEPENDENT DIGITAL NOISE.
    The samples themselves are corrupted before the modulator: AFE ->
    SLIMbus channel map, format or pacing. Next: q6asm pacing / AFE
    channel-map A/Bs are back on the table; one knob per boot.

A,B quiet, C fully clean ............... PATH CLEAN THIS BOOT; PRIOR
    MEASUREMENTS INVALID for this configuration (state-dependent attach or
    init quality). Next: immediately re-run whichever config previously
    showed static, on this same boot, and diff the kernel evidence.

C noisy in Cz2 only .................... TEARDOWN-ADJACENT DESYNC (variant
    of modulator noise). Repeat once to confirm; check whether PA teardown
    begins under the zero tail.

A quiet, D noisy ....................... RESIDUAL AMP STATE AFTER PARK.
    Parking does not clear bias/bandgap state. Next: leave off >= 10 s
    (this script enforces the floor), prefer a full power cycle before the
    next listening test.

Everything quiet ....................... NOISE NOT REPRODUCED THIS BOOT.
    Prior static results are unconfirmed for this software state. Next:
    re-run the original failing configuration before any new hypothesis.
=====================================================================
MATRIX
echo "record your per-interval observations next to this run's log: $LOG"
echo "run parameters: PA_VOLUME=$PA_VOLUME BOOST_SWITCH=$BOOST_SWITCH ZERO_ONLY=$ZERO_ONLY PORT_MASK=$PORT_MASK waveform=$(sha256sum "$WAV" | cut -d' ' -f1)"
exit 0
