#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Manual bring-up for the 2026-07-25/28 era reconstruction (GRUB entry
# spx-speaker-v10-era).
#
# The guarded harness cannot run on this boot: the era command line has none of
# the ~25 knobs its invariants require, and dtb.wsa-pin2 has no watchdog node.
# The kernel still boots with panic=10 / oops=panic so a hang self-recovers.
#
# The essential difference from the silent v3-v9 series is the addressing model.
# v3-v9 force spx_no_assign=1 + spx_write_dev0=1, pinning the amp at device 0.
# The era let the amp enumerate naturally (device 1) with writes following it;
# the 07-25 notes record that spx_write_dev0=1 while the amp held device 1 sent
# every register write into a void, and that setting it to 0 was what produced
# audio.
#
# Run as the desktop user, never through sudo.

set -uo pipefail

if (( EUID == 0 )); then
	echo "FATAL: run $0 as the desktop user, without sudo" >&2
	exit 1
fi

cd "$(dirname "$0")/.."
LOG_DIR="/var/tmp/spx-era-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/run.log") 2>&1
cp /proc/cmdline "$LOG_DIR/cmdline"
echo "SPX era reconstruction; diagnostics: $LOG_DIR"

fatal() { echo "FATAL: $*" >&2; exit 1; }

echo "=== [0] sanity ==="
grep -q 'spx_wsa_gpio_val=0x06' /proc/cmdline || fatal "not the era entry"
grep -q 'spx_no_assign' /proc/cmdline && fatal "spx_no_assign must be absent"
echo "  era command line confirmed"
for m in soundwire_qcom snd_soc_wsa881x; do
	modinfo -F filename "$m" 2>/dev/null || true
done

echo "=== [1] codec / SLIMbus card bring-up ==="
if ! grep -qi 'surface\|sdm845' /proc/asound/cards 2>/dev/null; then
	./scripts/spx-run2-pio-full.sh >"$LOG_DIR/bringup.log" 2>&1 || true
	sleep 2
fi
grep -qi 'surface\|sdm845' /proc/asound/cards ||
	fatal "no sound card (see $LOG_DIR/bringup.log)"
CARD=$(awk '/\[/{print $1; exit}' /proc/asound/cards)
echo "  ALSA card $CARD"

echo "=== [2] power exactly one amplifier, then attach ==="
# 10 s off: shorter power-cycles repeatedly failed to make the amp announce.
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x00 2>/dev/null
sleep 10
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x02 2>/dev/null
sleep 0.5
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_force_attach >/dev/null
# NEVER read spx_reenum: it is write-only and a read blocks forever.
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_reenum >/dev/null
sleep 25

echo "=== [3] verify a real attach (hardware register, not sysfs) ==="
# sysfs 'status' lies when spx_blind_attach=1; only MCP_SLV_STATUS counts.
sudo insmod drivers/spx_extras/spx_swrm_regs.ko 2>/dev/null; sleep 2
sudo rmmod spx_swrm_regs 2>/dev/null
SLV=$(sudo dmesg | grep 'MCP_SLV_STATUS' | tail -1 |
	grep -o '0x[0-9a-f]\{8\}' | head -1)
echo "  MCP_SLV_STATUS = ${SLV:-none}"
case "$SLV" in
0x00000001) echo "  amp at device 0" ;;
0x00000004) echo "  amp at device 1 (the era's normal state)" ;;
*) fatal "no trustworthy amp status ($SLV); refusing playback" ;;
esac

echo "=== [4] write routing ==="
# A slave answers only ONE address, and unicast writes always report success
# even when dropped, so a wrong fixed value silently discards every write.
echo "  spx_write_dev0 = $(cat /sys/module/soundwire_qcom/parameters/spx_write_dev0)"
sudo dmesg | grep 'writes go to device' | tail -1

echo "=== [5] mixer path ==="
sc() { amixer -q -c"$CARD" cset name="$1" "$2" >/dev/null 2>&1 || true; }
sc "SLIMBUS_2_RX Audio Mixer MultiMedia1" 1
sc "SLIM RX0 MUX" AIF1_PB; sc "SLIM RX1 MUX" AIF1_PB
sc "RX INT7_1 MIX1 INP0" RX0
sc "COMP7 Switch" 1
sc "RX7 Digital Volume" 100
sc "RX8 Digital Volume" 100
# COMP/DRE fights register-mode gain and mutes real audio; keep it off.
sc "SpkrLeft COMP Switch" 0
sc "SpkrLeft VISENSE Switch" 0
sc "SpkrLeft BOOST Switch" 1
sc "SpkrLeft DAC Switch" 1
# Force a real control transition: a plain re-set is an ALSA no-op while the
# hardware register has been reseeded to the 0 dB floor.
sc "SpkrLeft PA Volume" 0
sc "SpkrLeft PA Volume" 12
sc "SpkrLeft Smart Boost Level" 8
amixer -c"$CARD" cget name='SpkrLeft PA Volume' >"$LOG_DIR/pa-volume.txt" 2>&1

echo "=== [6] tone ==="
systemctl --user stop wireplumber pipewire pipewire-pulse 2>/dev/null || true
sleep 1
timeout -k 2 8 speaker-test -D "plughw:${CARD},0" -c 2 -r 48000 -F S16_LE \
	-t sine -f 440 >"$LOG_DIR/speaker-test.log" 2>&1
echo "  played 8 s of 440 Hz -- audible?"

echo "=== [7] park the amplifier ==="
sc "SpkrLeft PA Volume" 0
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x00 2>/dev/null
sudo dmesg | tail -200 >"$LOG_DIR/dmesg-tail.log"
echo "SPX: amplifier parked; diagnostics in $LOG_DIR"
