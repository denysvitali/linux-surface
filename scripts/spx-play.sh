#!/bin/bash
# SPX: reliable speaker playback workaround.
#
# RCA 2026-07-25: stream start programs the channel-enable only into the bank
# being switched to (bank 0); bank 1 keeps enable=0. When the final bank-switch
# command is dropped on the wire (writes always report OK), the bus stays on
# bank 1 -> PA clicks on but no data -> "random" silent runs. Mirroring the
# port config + enable into bank 1 on BOTH master and slave right after the
# stream starts makes playback audible regardless of which bank is active.
#
# Usage: spx-play.sh [seconds] [freq]
set -u
SECS=${1:-8}
FREQ=${2:-440}
cd "$(dirname "$0")/../drivers/spx_extras"

sc(){ amixer -q -c0 cset name="$1" "$2" 2>/dev/null || true; }
# COMP/DRE port OFF: with it on, the DRE gain-word stream drives the PA gain
# down and mutes the real audio (verified A/B 2026-07-25). REG-mode analog
# gain: PA Volume 12 = +18 dB (kcontrol handles the inverted field).
sc "SpkrLeft COMP Switch" 0
sc "SpkrLeft PA Volume" 12

timeout -k 2 "$SECS" speaker-test -D plughw:0,0 -c 2 -t sine -f "$FREQ" >/dev/null 2>&1 &
sleep 1

# Master bank 1: DP1_PORT_CTRL_B1 = enable ch1, offset1=1, SI-1=7 (2.4 MHz PDM)
sudo insmod ./spx_swrm_tune.ko swrm_reg=0x1164 swrm_val=0x01000107 2>/dev/null
sudo rmmod spx_swrm_tune 2>/dev/null
# Slave bank 1: DP1 sample interval, offsets, channel enable
w() { sudo insmod ./spx_wsa_write.ko wsa_reg=$1 wsa_val=$2 2>/dev/null; sudo rmmod spx_wsa_write 2>/dev/null; }
w 0x0132 0x07
w 0x0134 0x01
w 0x0135 0x00
w 0x0130 0x01
wait
echo "played ${SECS}s ${FREQ}Hz (bank-1 mirrored at T+1s)"
