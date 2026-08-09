#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# Run on the "EXPERIMENTAL: WSA speaker fix" GRUB entry. Verifies the WSA881x
# amps now ATTACH (PART A: soundwire-qcom enumeration kick) and aren't held in
# shutdown (PART B: powerdown-gpios ACTIVE_LOW), then plays an audible tone.
set -u
CARD=0

echo "=== boot sanity: WSA-fix DTB (powerdown-gpios ACTIVE_LOW)? ==="
sudo grep -aqo "qcom,q6asm-dais" /sys/firmware/fdt 2>/dev/null && echo "  APR DTB: yes" || { echo "  FATAL: not the APR/WSA DTB"; exit 1; }

echo "=== boot sanity: core-enumeration fix active (spx_core_enum=1)? ==="
# the real WSA fix: HW auto-enum disabled, SoundWire core enumerates device 0.
# PART B (GPIO ACTIVE_LOW) was a no-op (driver cancels the flag) -- ignore it.
if grep -q spx_core_enum=1 /proc/cmdline 2>/dev/null; then
	echo "  spx_core_enum: ON (cmdline) -- correct GRUB entry"
else
	echo "  WARN: spx_core_enum NOT in cmdline -- boot the 'WSA speaker fix' entry"
fi

echo "=== bring up the card (loads new soundwire-qcom w/ enum kick) ==="
if ! grep -q sdm845 /proc/asound/cards 2>/dev/null; then
	"$(dirname "$0")/spx-run2-pio-full.sh" >/tmp/spx-bringup.log 2>&1 || true
	grep -q sdm845 /proc/asound/cards 2>/dev/null || sudo modprobe q6asm_dai 2>/dev/null
	sleep 2
fi
grep -q sdm845 /proc/asound/cards 2>/dev/null || { echo "FATAL: no card (see /tmp/spx-bringup.log)"; exit 1; }

echo "=== PART A check: WSA881x SoundWire attach state ==="
for d in /sys/bus/soundwire/devices/sdw:*; do echo "  $(basename $d): $(cat $d/status 2>/dev/null)"; done
echo "  (want: attached, NOT UNATTACHED)"
echo "--- DECISIVE: raw DevID probe (does the WSA return ANY bytes?) ---"
sudo dmesg | grep -E "SPX DIAG" || echo "  (no SPX DIAG lines — diagnostic did not run; check spx_core_enum + presence)"
echo "--- soundwire enumeration trace ---"
sudo dmesg | grep -iE "soundwire|wsa881|enumerat|attach|SPX enum|slave|dev_num|program" | tail -12

echo "=== set pool=4 + full speaker path, play 5s tone (LISTEN) ==="
echo 4 | sudo tee /sys/module/q6asm/parameters/mem_pool >/dev/null
sc(){ amixer -q -c$CARD cset name="$1" "$2" 2>/dev/null || true; }
sc "SLIMBUS_2_RX Audio Mixer MultiMedia1" 1
sc "SLIM RX0 MUX" AIF1_PB; sc "SLIM RX1 MUX" AIF1_PB
sc "RX INT7_1 MIX1 INP0" RX0; sc "RX INT8_1 MIX1 INP0" RX1
sc "COMP7 Switch" 1; sc "COMP8 Switch" 1
sc "RX7 Digital Volume" 84; sc "RX8 Digital Volume" 84
# WSA amp gain/boost if the wsa881x controls now exist (post-attach)
sc "SpkrLeft WSA PA Volume" 12; sc "SpkrRight WSA PA Volume" 12
sc "SpkrLeft COMP Switch" 0; sc "SpkrRight COMP Switch" 0
sc "SpkrLeft BOOST Switch" 1; sc "SpkrRight BOOST Switch" 1
sc "SpkrLeft VISENSE Switch" 0; sc "SpkrRight VISENSE Switch" 0
sc "SpkrLeft DAC Switch" 1; sc "SpkrRight DAC Switch" 1
systemctl --user stop wireplumber pipewire pipewire-pulse 2>/dev/null || true; pkill -9 -x wireplumber 2>/dev/null || true
rm -f /tmp/spx-adsp-abort
sudo sh -c "timeout 20 dmesg -w | while IFS= read -r l; do case \"\$l\" in *qcom_q6v5_pas*watchdog*|*\"crash detected in adsp\"*) printf %s\\\\n \"\$l\">/tmp/spx-adsp-abort; break;; esac; done" &
echo ">>> PLAYING 5s 440Hz tone — LISTEN TO THE SPEAKERS <<<"
timeout -k 2 7 speaker-test -D plughw:$CARD,0 -c 2 -t sine -f 440 -l 1 >/dev/null 2>&1; echo "rc=$?"
sleep 1
[ -f /tmp/spx-adsp-abort ] && echo "CRASH: $(cat /tmp/spx-adsp-abort)" || echo "clean; adsp=$(cat /sys/class/remoteproc/remoteproc2/state)"
echo "=== WSA amp controls present? (post-attach) ==="
amixer -c$CARD controls 2>/dev/null | grep -iE "Spkr|WSA" | head
