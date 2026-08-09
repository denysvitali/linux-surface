#!/bin/bash
# SPX SINGLE-AMP decisive test. Boot the "EXPERIMENTAL: WSA SINGLE-AMP test"
# GRUB entry (slimfix kernel, dtb.wsairq-1amp: right_spkr disabled), then run
# this. It brings the card up, RETRIES the flaky frame-gen lock via spx_reenum
# (the 2026-07-01 soundwire-qcom.ko re-runs SW_RESET+init+frame_phase sweep on
# every trigger while frame-gen is down), and once locked lets the diag/enum
# run. Success = left amp enumerates as 0217:2010 + ATTACHED -> plays a tone.
set -u
cd "$(dirname "$0")/.."
DBG=/sys/kernel/debug/soundwire/master-0-0/qualcomm-sdw/qualcomm-registers

echo "=== [0] boot sanity ==="
grep -q "BOOT_IMAGE=[^ ]*slimfix" /proc/cmdline || { echo "FATAL: not the slimfix kernel entry"; exit 1; }
S=$(cat /proc/device-tree/soc@0/slim-ngd@171c0000/slim@1/codec@1,0/soundwire@c85/speaker@0,2/status 2>/dev/null | tr -d '\0')
[ "$S" = "disabled" ] || { echo "FATAL: right_spkr not disabled -> not the 1-amp DTB (status='$S')"; exit 1; }
echo "  slimfix kernel + 1-amp DTB: OK"

echo "=== [1] preload module chain (order matters: avoids probe-defer mid-sweep) ==="
sudo modprobe slimbus soundwire_qcom gpio_wcd934x snd_soc_wcd934x snd_soc_wsa881x wcd934x 2>/dev/null || true

echo "=== [2] card bring-up ==="
if ! grep -q sdm845 /proc/asound/cards 2>/dev/null; then
	./scripts/spx-run2-pio-full.sh >/tmp/spx-bringup.log 2>&1 || true
	sleep 2
fi
grep -q sdm845 /proc/asound/cards 2>/dev/null || { echo "FATAL: no card (see /tmp/spx-bringup.log)"; exit 1; }
echo "  card: OK"

echo "=== [3] frame-gen lock (retry up to 20x via spx_reenum) ==="
locked=0
for i in $(seq 1 20); do
	COMP=$(sudo cat "$DBG" 2>/dev/null | awk -F: '{gsub(/ /,"",$1);a=strtonum($1)} a==0x14 {gsub(/ /,"",$2); print $2}')
	[ -n "$COMP" ] || COMP=0
	if [ $(( COMP & 1 )) -eq 1 ]; then locked=1; echo "  LOCKED (COMP_STATUS=$COMP) after $((i-1)) retries"; break; fi
	echo "  try $i: COMP_STATUS=$COMP -> re-sweep"
	echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_reenum >/dev/null
	sleep 10
done
[ "$locked" = 1 ] || { echo "RESULT: frame-gen NEVER locked after 20 sweeps -- capture dmesg + stop"; sudo dmesg | grep -iE "SPX" | tail -20; exit 2; }

echo "=== [4] FORCE-ATTACH: blind-assign dev#1 + attach the WSA slave ==="
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_force_attach >/dev/null
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_reenum >/dev/null
sleep 12
sudo dmesg | grep -E "SPX FORCE-ATTACH|SPX DIAG dev0 FINAL|wsa881x" | tail -8
for d in /sys/bus/soundwire/devices/sdw:0:0:0217:2010:*; do echo "  $(basename $d): $(cat $d/status 2>/dev/null)"; done

if grep -qi '^attached$' /sys/bus/soundwire/devices/sdw:0:0:0217:2010:00:1/status 2>/dev/null; then
	echo "=== [5] *** LEFT AMP ATTACHED *** playing 5s tone -- LISTEN ==="
	sc(){ amixer -q -c0 cset name="$1" "$2" 2>/dev/null || true; }
	sc "SLIMBUS_2_RX Audio Mixer MultiMedia1" 1
	sc "SLIM RX0 MUX" AIF1_PB; sc "SLIM RX1 MUX" AIF1_PB
	sc "RX INT7_1 MIX1 INP0" RX0; sc "COMP7 Switch" 1
	sc "RX7 Digital Volume" 84
	sc "SpkrLeft COMP Switch" 1; sc "SpkrLeft BOOST Switch" 1
	sc "SpkrLeft VISENSE Switch" 1; sc "SpkrLeft WSA PA Volume" 12
	systemctl --user stop wireplumber pipewire pipewire-pulse 2>/dev/null || true
	timeout -k 2 7 speaker-test -D plughw:0,0 -c 2 -t sine -f 440 -l 1 >/dev/null 2>&1
	echo "rc=$? -- did you HEAR it?"
else
	echo "RESULT: amp still UNATTACHED after lock -- paste this whole output"
fi
