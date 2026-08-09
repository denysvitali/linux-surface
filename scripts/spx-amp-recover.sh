#!/bin/bash
# SPX: restore the WSA881x amp after it desyncs (static-only / silent runs).
# Works every time on a fresh boot; no power-cycle needed while the boot is warm-
# state-clean. Usage: sudo ./scripts/spx-amp-recover.sh [file.wav]
set -u
cd "$(dirname "$0")/.."

echo 1 > /sys/module/soundwire_qcom/parameters/spx_force_attach
echo 1 > /sys/module/soundwire_qcom/parameters/spx_reenum
sleep 3
dmesg | grep "writes go" | tail -1

# Replay the amp init table, then FORCE the PA gain write: the replay reseeds
# the gain register to the 0 dB floor while ALSA still believes it is 12, so a
# plain re-set is a silent no-op -- toggle through 0 to make the write happen.
echo 1 > /sys/module/snd_soc_wsa881x/parameters/spx_rearm_init
amixer -q -c0 cset name="SpkrLeft COMP Switch" 0
amixer -q -c0 cset name="SpkrLeft VISENSE Switch" 0
amixer -q -c0 cset name="SpkrLeft DAC Switch" 1
amixer -q -c0 cset name="SpkrLeft BOOST Switch" 1
amixer -q -c0 cset name="SpkrLeft PA Volume" 0
amixer -q -c0 cset name="SpkrLeft PA Volume" 12

if [ $# -ge 1 ]; then
	aplay -q -D plughw:0,0 "$1"
fi
