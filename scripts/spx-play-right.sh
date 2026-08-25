#!/bin/bash
# SPX play (right speaker): bring up the right amp (endpoint B / pin2 / S16) and
# play a file. Current validated path (2026-08-20, spx_keep_asm fix).
#
# Usage: spx-play-right.sh [file]   (default: ~/Downloads/tune.wav)
# Run as the desktop user. The amp is parked off at exit.
#
# Grants the ALSA ACL (like the autotest does) so a plain user can open the PCM
# nodes; devtmpfs drops the ACL at the next reboot.

set -euo pipefail
if (( EUID == 0 )); then echo "FATAL: run as desktop user, not sudo" >&2; exit 1; fi
cd "$(dirname "$0")/.."
sudo -v || exit 1

FILE=${1:-$HOME/Downloads/tune.wav}
[[ -f $FILE ]] || { echo "no such file: $FILE" >&2; exit 1; }

LOG=/tmp/spx-play-right.log
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

CARD=$(awk '/Surface Pro X/{print $1}' /proc/asound/cards | head -1)
[[ $CARD =~ ^[0-9]+$ ]] || { echo "no Surface Pro X card" >&2; exit 1; }

for n in /dev/snd/controlC* /dev/snd/pcmC*; do
	[ -c "$n" ] && sudo setfacl -m u:"$USER":rw- "$n"
done

set_ctl() { amixer -c "$CARD" cset name="$1" "$2" >> /tmp/spx-play-right-mixer.log 2>&1 || { echo "FAILED ctl $1=$2" >&2; exit 1; }; }

echo "=== park amp off 10s, then power pin2 (0x04) ==="
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x00 || true
sleep 10
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x04 || true
sleep 0.2

echo "=== force-attach + reenum ==="
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_force_attach >/dev/null
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_reenum >/dev/null
sleep 1

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
set_ctl 'SpkrRight PA Volume' "${SPX_PA_VOLUME:-12}"
set_ctl 'SpkrRight Smart Boost Level' 0

echo "=== playing $FILE ==="
printf '<6>SPX_PLAY_RIGHT_%s\n' "$RANDOM" | sudo tee /dev/kmsg >/dev/null
timeout -k 2 300 aplay -D "plughw:${CARD},0" --period-size=12000 --buffer-size=48000 "$FILE" > /tmp/spx-play-right-aplay.log 2>&1 &
PID=$!
wait "$PID" || true
sleep 3

echo "=== park amp off ==="
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x00 || true

echo "=== Q6 stream summary ==="
sudo dmesg | grep -E 'SPX ASM stream|SPX: parking ASM|SPX: reusing parked ASM' | tail -6
