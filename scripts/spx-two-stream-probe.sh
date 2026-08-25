#!/bin/bash
# SPX two-stream probe: bring up the amp and play TWO separate streams.
#
# Validates the spx_keep_asm fix: both the first and second stream on a cold
# boot must report write_done>0 (the DSP actually consumed them). Without the
# fix the second stream reports write_done=0.
#
# Run as the desktop user. Do NOT run through sudo.

set -euo pipefail
if (( EUID == 0 )); then echo "FATAL: run as desktop user, not sudo" >&2; exit 1; fi
cd "$(dirname "$0")/.."
sudo -v || exit 1

LOG=/tmp/spx-two-stream.log
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

CARD=$(awk '/Surface Pro X/{print $1}' /proc/asound/cards | head -1)
[[ $CARD =~ ^[0-9]+$ ]] || { echo "no Surface Pro X card"; exit 1; }
set_ctl() { amixer -c "$CARD" cset name="$1" "$2" >> /tmp/spx-two-mixer.log 2>&1 || { echo "FAILED ctl $1=$2"; exit 1; }; }
play_tone() {
	local tag=$1
	kmsg_marker() { printf '<6>SPX_2STR_%s_%s\n' "$1" "$RANDOM" | sudo tee /dev/kmsg >/dev/null; }
	kmsg_marker "$tag"
	timeout -k 2 10 aplay -D "plughw:${CARD},0" --period-size=12000 --buffer-size=48000 /tmp/spx-two-tone.wav > /tmp/spx-two-aplay-$tag.log 2>&1 &
	local pid=$!
	wait "$pid" || true
	sleep 2
}

echo "=== [A] park amp off 10s, then power pin2 (0x04) ==="
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x00 || true
sleep 10
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x04 || true
sleep 0.2

echo "=== [B] force-attach + reenum ==="
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_force_attach >/dev/null
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_reenum >/dev/null
sleep 1

echo "=== [C] mixer path (endpoint B / pin2 / S16) ==="
set_ctl 'SLIMBUS_2_RX Audio Mixer MultiMedia1' 1
set_ctl 'SLIM RX0 MUX' AIF1_PB
set_ctl 'SLIM RX1 MUX' AIF1_PB
set_ctl 'RX INT8_1 MIX1 INP0' RX1
set_ctl 'COMP8 Switch' 1
set_ctl 'RX8 Digital Volume' 84
set_ctl 'SpkrRight COMP Switch' 0
set_ctl 'SpkrRight VISENSE Switch' 0
set_ctl 'SpkrRight BOOST Switch' 1
set_ctl 'SpkrRight DAC Switch' 1
set_ctl 'SpkrRight PA Volume' 0
set_ctl 'SpkrRight PA Volume' 12
set_ctl 'SpkrRight Smart Boost Level' 0

echo "=== [D] build tone waveform ==="
ffmpeg -nostdin -v error \
	-f lavfi -i anullsrc=r=48000:cl=stereo:d=1 \
	-f lavfi -i sine=frequency=440:sample_rate=48000:duration=5 \
	-filter_complex "[1:a]volume=6.4,pan=stereo|c0=0*c0|c1=c0[tone];[0:a][tone]concat=n=2:v=0:a=1[out]" \
	-map '[out]' -c:a pcm_s16le -y /tmp/spx-two-tone.wav

echo "=== [E] STREAM 1 ==="
play_tone stream1
echo "=== [F] STREAM 2 ==="
play_tone stream2

echo "=== [G] park amp off ==="
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x00 || true

echo "=== [H] Q6 stream summaries (all this boot) ==="
sudo dmesg | grep -E 'SPX ASM stream|SPX: parking ASM|SPX: reusing parked ASM' | tail -8
