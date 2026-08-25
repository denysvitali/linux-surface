#!/bin/bash
# SPX WSA descriptor-count sweep (endpoint B / pin2 / S16).
#
# Windows and mainline db845c both open all four WSA881x SoundWire descriptors
# (DAC, COMP, BOOST, VISENSE); the SPX guarded baseline opens only the DAC one.
# The four-port variant was tested exactly once, during the whole-boot-silence
# era, so it has never been judged on an audible baseline.
#
# `snd_soc_wsa881x.spx_stream_port_mask` is 0644 and is read at hw_params, so a
# fresh stream picks up a new value without a reboot. Combined with the
# spx_keep_asm fix (every stream renders, not just the boot's first), one boot
# can host the whole sweep.
#
# Usage: spx-portmask-sweep.sh [mask ...]      default: 7 15 1
#   1 = DAC only (the v28 baseline)   3 = DAC+COMP
#   5 = DAC+BOOST (the v31 guarded stream)
#   7 = DAC+COMP+BOOST, i.e. every master DOUT descriptor endpoint B owns
#   15 = all four, including VISENSE on master port 8 which is a DIN port —
#        the one direction-inconsistent combination, so test it last
#
# SPX_BOOST_SWITCH=0 additionally disables the analog boost, testing the other
# half of the "boost enabled but its descriptor never streamed" inconsistency.
#
# Run as the desktop user, never through sudo. The amp is parked off at exit.

set -euo pipefail
if (( EUID == 0 )); then echo "FATAL: run as desktop user, not sudo" >&2; exit 1; fi
cd "$(dirname "$0")/.."
sudo -v || exit 1

MASKS=("$@")
(( ${#MASKS[@]} )) || MASKS=(7 15 1)

LOG=/tmp/spx-portmask-sweep.log
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

MASK_PARAM=/sys/module/snd_soc_wsa881x/parameters/spx_stream_port_mask
[[ -w $MASK_PARAM || -e $MASK_PARAM ]] ||
	{ echo "FATAL: snd_soc_wsa881x is not loaded" >&2; exit 1; }

CARD=$(awk '/Surface Pro X/{print $1}' /proc/asound/cards | head -1)
[[ $CARD =~ ^[0-9]+$ ]] || { echo "FATAL: no Surface Pro X card" >&2; exit 1; }

for n in /dev/snd/controlC* /dev/snd/pcmC*; do
	[ -c "$n" ] && sudo setfacl -m u:"$USER":rw- "$n"
done

set_ctl() {
	amixer -c "$CARD" cset name="$1" "$2" >> /tmp/spx-portmask-mixer.log 2>&1 ||
		{ echo "FAILED ctl $1=$2" >&2; exit 1; }
}

# Serialized controller snapshot, idle only. CLAUDE.md's testing etiquette says
# never ask the user about a run whose preconditions were invalid, and a silent
# run with a detached amp is exactly that. Never call this while samples flow:
# the shared WCD/SLIMbus bridge transaction costs ~165 ms and audibly cuts the
# stream (PROGRESS.md §28).
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

cleanup() {
	sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x00 2>/dev/null || true
	echo 1 | sudo tee "$MASK_PARAM" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "=== [A] park both amps off for 10 s, then power pin2 only (0x04) ==="
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x00 || true
sleep 10
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x04 || true
sleep 0.2

# The guarded harness's recipe, which is why its runs are reliably audible and
# ad-hoc replays are a coin flip. Two gates, in this order:
#   1. Wait for a REAL physical announce (MCP_SLV_STATUS=0x1) before touching
#      force-attach. The latch flickers 0x1/0x0 even with the amp present, so
#      sample fast and keep the first 0x1 as proof.
#   2. After re-enumerating, wait for the driver to say the attachment settled
#      AND that it replayed the cold-init table, instead of sleeping a guess.
# Without gate 1 a run can play a full stream, have the DSP consume every
# buffer, and emit nothing, because no amp ever answered.
echo "=== [B] wait for physical device-0 presence ==="
PRESENT=0
for ((s = 0; s < 40; s++)); do
	snapshot "attach-window" 1
	if [[ $SPX_SNAP_COMP != 0x016840c6 ]]; then
		echo "FATAL: AHB bridge canary invalid ($SPX_SNAP_COMP); reads are fake" >&2
		exit 1
	fi
	if [[ $SPX_SNAP_SLV == 0x00000001 ]]; then
		PRESENT=1
		echo "  physical device-0 presence observed after $((s + 1)) sample(s)"
		break
	fi
	sleep 0.05
done
if (( ! PRESENT )); then
	echo "FATAL: the amp never announced at physical device 0 after GPIO-high." >&2
	echo "       Refusing to play: a silent run here would be a void measurement," >&2
	echo "       not a result about the port mask. Re-run to retry the attach." >&2
	exit 1
fi

echo "=== [C] force-attach + re-enumerate ==="
ENUM_MARKER="SPX_SWEEP_ENUM_${RANDOM}_$(date +%s%N)"
printf '<6>%s\n' "$ENUM_MARKER" | sudo tee /dev/kmsg >/dev/null
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_force_attach >/dev/null
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_reenum >/dev/null
ENUM_OK=0
for ((i = 0; i < 300; i++)); do
	ENUM_LOG=$(sudo dmesg | sed -n "/$ENUM_MARKER/,\$p")
	if grep -q 'SPX FORCE-ATTACH: stable attachment' <<<"$ENUM_LOG" &&
	   grep -q 'SPX: initializing amplifier at SoundWire device 1' <<<"$ENUM_LOG"
	then
		ENUM_OK=1
		break
	fi
	sleep 0.1
done
if (( ! ENUM_OK )); then
	echo "FATAL: force-attach never reached stable attachment with a cold-init replay." >&2
	exit 1
fi
echo "  stable attachment + cold-init replay confirmed"
snapshot "post-attach"

echo "=== [D] mixer path (endpoint B / pin2 / S16) ==="
set_ctl 'SLIMBUS_2_RX Audio Mixer MultiMedia1' 1
set_ctl 'SLIM RX0 MUX' AIF1_PB
set_ctl 'SLIM RX1 MUX' AIF1_PB
set_ctl 'RX INT8_1 MIX1 INP0' RX1
set_ctl 'COMP8 Switch' 1
set_ctl 'RX8 Digital Volume' 84
set_ctl 'SpkrRight COMP Switch' 0
set_ctl 'SpkrRight VISENSE Switch' 0
# The analog boost is enabled while its SoundWire descriptor is normally not
# streamed. SPX_BOOST_SWITCH=0 tests the other half of that inconsistency: turn
# the boost off instead of feeding it.
set_ctl 'SpkrRight BOOST Switch' "${SPX_BOOST_SWITCH:-1}"
set_ctl 'SpkrRight DAC Switch' 1
# Force-write the gain: a plain re-set is an ALSA no-op while the hardware
# register has been reseeded to the 0 dB floor by the power cycle.
#
# SPX_PA_VOLUME partitions the remaining search space in one listen. 12 is the
# +18 dB baseline. At 0 (0 dB): if the static falls with the tone, the noise is
# upstream of the PA gain stage (data or DAC); if the static stays put while the
# tone drops away, it is injected after it (boost converter / PA analog).
set_ctl 'SpkrRight PA Volume' 0
if [[ ${SPX_PA_VOLUME:-12} != 0 ]]; then
	set_ctl 'SpkrRight PA Volume' "${SPX_PA_VOLUME:-12}"
fi
echo "  PA Volume = ${SPX_PA_VOLUME:-12}"
set_ctl 'SpkrRight Smart Boost Level' 0

if [[ ${SPX_ZERO_ONLY:-0} == 1 ]]; then
	echo "=== [E] build the test waveform: 10 s of PURE digital zero ==="
	# Control for "is the amp making the noise at all". The PA is enabled for
	# the whole stream but the PCM is exact zero throughout, and the amp is
	# parked off immediately afterwards. Static that starts with the stream and
	# stops at park is generated by the enabled amp; static that is there the
	# whole time is ambient and has never been about the speaker path.
	ffmpeg -nostdin -v error \
		-f lavfi -i anullsrc=r=48000:cl=stereo:d=10 \
		-c:a pcm_s16le -y /tmp/spx-sweep-tone.wav
else
echo "=== [E] build the test waveform: 3 s digital zero, then 5 s 440 Hz on C1 ==="
# The zero prefix is the discriminator: a correctly clocked amp is silent there.
ffmpeg -nostdin -v error \
	-f lavfi -i anullsrc=r=48000:cl=stereo:d=3 \
	-f lavfi -i sine=frequency=440:sample_rate=48000:duration=5 \
	-filter_complex "[1:a]volume=0.8,pan=stereo|c0=0*c0|c1=c0[tone];[0:a][tone]concat=n=2:v=0:a=1[out]" \
	-map '[out]' -c:a pcm_s16le -y /tmp/spx-sweep-tone.wav
fi
echo "waveform sha256: $(sha256sum /tmp/spx-sweep-tone.wav | cut -d' ' -f1)"

TONE_INDEX=1
for MASK in "${MASKS[@]}"; do
	case $MASK in
	1)  DESC="DAC only (v28 baseline)" ;;
	3)  DESC="DAC + COMP" ;;
	5)  DESC="DAC + BOOST (v31 guarded stream)" ;;
	7)  DESC="DAC + COMP + BOOST (every DOUT descriptor)" ;;
	15) DESC="all four, incl. VISENSE on a DIN master port" ;;
	*)  DESC="mask $MASK" ;;
	esac

	echo
	echo "############################################################"
	echo "### port mask $MASK — $DESC (BOOST Switch ${SPX_BOOST_SWITCH:-1})"
	echo "############################################################"
	echo "$MASK" | sudo tee "$MASK_PARAM" >/dev/null
	READBACK=$(cat "$MASK_PARAM")
	[[ $READBACK == "$MASK" ]] ||
		{ echo "FATAL: port mask readback $READBACK != $MASK" >&2; exit 1; }

	MARKER="SPX_SWEEP_${MASK}_${RANDOM}"
	printf '<6>%s\n' "$MARKER" | sudo tee /dev/kmsg >/dev/null
	for c in 3 2 1; do echo ">>> tone $TONE_INDEX ($DESC) in $c..."; sleep 1; done
	echo ">>> TONE $TONE_INDEX PLAYING: 3 s of silence expected, then 440 Hz (right speaker)"
	timeout -k 2 20 aplay -D "plughw:${CARD},0" \
		--period-size=12000 --buffer-size=48000 /tmp/spx-sweep-tone.wav \
		> "/tmp/spx-sweep-aplay-$MASK.log" 2>&1 &
	wait $! || true
	sleep 2
	snapshot "post-tone-$TONE_INDEX"
	TONE_INDEX=$((TONE_INDEX + 1))

	echo "--- kernel evidence for mask $MASK ---"
	sudo dmesg | sed -n "/$MARKER/,\$p" |
		grep -E 'active_ports=|SPX ASM stream|PA DAPM event|shadow (slave|master) DP|overflow|XRUN|Oops|BUG:' |
		head -30
done

echo
echo "=== [F] park amp off, restore DAC-only mask ==="
