#!/bin/bash
# SPX sample-edge sweep: play ONE short tone with a specific PDM sample edge.
#
# Usage: spx-edge-sweep.sh <edge>   (edge = 0x00,0x04,0x08,0x0c,0x10,...)
#
# Static is audible during the digital-zero preroll, which points at PDM
# clock/data desync. WSA881X_SAMPLE_EDGE_SEL (0x3044) is the PDM edge select and
# has never been swept on an AUDIBLE baseline (the 07-21 sweep was in the silent
# era). Each invocation plays one stream at one edge; the user listens.

set -euo pipefail
if (( EUID == 0 )); then echo "FATAL: run as desktop user, not sudo" >&2; exit 1; fi
cd "$(dirname "$0")/.."
sudo -v || exit 1

EDGE=${1:-0x0c}
[[ $EDGE =~ ^0x[0-9a-fA-F]{2}$ ]] || { echo "usage: $0 <0xNN>" >&2; exit 1; }

LOG=/tmp/spx-edge-$EDGE.log
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

CARD=$(awk '/Surface Pro X/{print $1}' /proc/asound/cards | head -1)
[[ $CARD =~ ^[0-9]+$ ]] || { echo "no Surface Pro X card" >&2; exit 1; }
for n in /dev/snd/controlC* /dev/snd/pcmC*; do [ -c "$n" ] && sudo setfacl -m u:"$USER":rw- "$n"; done
set_ctl() { amixer -c "$CARD" cset name="$1" "$2" >> /tmp/spx-edge-mixer.log 2>&1 || { echo "FAILED ctl $1=$2" >&2; exit 1; }; }

echo "=== edge=$EDGE: park amp off 10s, power pin2 ==="
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x00 || true
sleep 10
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x04 || true
sleep 0.2

echo "=== force-attach + reenum ==="
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_force_attach >/dev/null
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_reenum >/dev/null
sleep 1

echo "=== set PDM sample edge to $EDGE ==="
echo "$((EDGE))" | sudo tee /sys/module/snd_soc_wsa881x/parameters/spx_sample_edge >/dev/null

echo "=== mixer path (endpoint B / pin2 / S16) ==="
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

echo "=== play 5s 440Hz tone (C1/front-right) ==="
TONE_WAV=/tmp/spx-edge-tone.wav
ffmpeg -nostdin -v error \
	-f lavfi -i anullsrc=r=48000:cl=stereo:d=1 \
	-f lavfi -i sine=frequency=440:sample_rate=48000:duration=5 \
	-filter_complex "[1:a]volume=6.4,pan=stereo|c0=0*c0|c1=c0[tone];[0:a][tone]concat=n=2:v=0:a=1[out]" \
	-map '[out]' -c:a pcm_s16le -y "$TONE_WAV"
printf '<6>SPX_EDGE_%s_%s\n' "$EDGE" "$RANDOM" | sudo tee /dev/kmsg >/dev/null
timeout -k 2 10 aplay -D "plughw:${CARD},0" --period-size=12000 --buffer-size=48000 "$TONE_WAV" > /tmp/spx-edge-aplay.log 2>&1 &
PID=$!
wait "$PID" || true
sleep 3

echo "=== park amp off ==="
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x00 || true

echo "=== Q6 summary ==="
sudo dmesg | grep -E 'SPX ASM stream' | tail -1
echo "=== done edge=$EDGE ==="
