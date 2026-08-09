#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# SPX safe single-shot test of the q6asm high-IOVA alias fix.
# Run on the DEFAULT (APR) boot. Does ONE PCM prepare (one mem-map), with a
# watchdog watcher that flags an ADSP crash. NO replay, NO playback data flow,
# so it cannot cascade into a freeze the way the earlier sweep did.
#
# Expected outcomes:
#   PASS   - "PREPARE OK" + dmesg shows mem_map req with msw=0x1 and NO
#            "DSP returned error[..]10d92" / NO watchdog  -> the ADSP accepted
#            the shared-memory map. BREAKTHROUGH.
#   EFAIL  - mem_map req present + "DSP returned error[1] opcode=10d92" but NO
#            watchdog -> graceful reject (alias still not what the DSP wants).
#   CRASH  - "qcom_q6v5_pas ... watchdog" / "crash detected in adsp" -> ADSP
#            faulted (auto-recovers; do NOT re-run, reboot to be safe).
set -u

PREP=/tmp/claude-1000/spx-pcm-prepare
[ -x "$PREP" ] || { echo "FATAL: $PREP missing (compile spx-pcm-prepare.c)"; exit 1; }

sudo grep -aqo "qcom,q6asm-dais" /sys/firmware/fdt 2>/dev/null || {
	echo "FATAL: not the APR DTB. Reboot to the DEFAULT entry."; exit 1; }

# Ensure the NEW alias-fix q6asm_dai is the one that loads: drop it if idle so
# the bring-up pulls the freshly-installed module.
if grep -q '^q6asm_dai' /proc/modules; then
	rc=$(awk '/^q6asm_dai/{print $3}' /proc/modules)
	[ "$rc" = "0" ] && sudo modprobe -r q6asm_dai 2>/dev/null
fi

if ! grep -q sdm845 /proc/asound/cards 2>/dev/null; then
	echo "=== bringing up APR card (once) ==="
	"$(dirname "$0")/spx-run2-pio-full.sh" >/tmp/spx-bringup.log 2>&1 || true
fi
grep -q sdm845 /proc/asound/cards 2>/dev/null || { echo "FATAL: no card; see /tmp/spx-bringup.log"; exit 1; }
CARD=$(awk '/sdm845/{print $1; exit}' /proc/asound/cards); CARD=${CARD:-0}
echo "card=$CARD; q6asm_dai alias-fix loaded:"; lsmod | grep '^q6asm_dai'

# Arm the watchdog watcher (detect ADSP crash; we only do ONE op so no cascade).
ABORT=/tmp/spx-adsp-abort; rm -f "$ABORT"
sudo sh -c 'dmesg -w | while IFS= read -r l; do
	case "$l" in
	  *watchdog*|*"crash detected in adsp"*|*"SFR Init"*)
	    printf "%s\n" "$l" > /tmp/spx-adsp-abort; break;;
	esac; done' &
WPID=$!

echo 1 | sudo tee /sys/module/q6asm/parameters/memmap_debug >/dev/null 2>&1 || true
echo 1 | sudo tee /sys/module/snd_soc_wcd934x/parameters/spx_persist_stream >/dev/null 2>&1 || true
echo 1 | sudo tee /sys/module/q6afe_dai/parameters/spx_no_port_stop >/dev/null 2>&1 || true
amixer -q -c "$CARD" cset name='SLIMBUS_2_RX Audio Mixer MultiMedia1' 1 2>/dev/null || true
systemctl --user stop wireplumber pipewire pipewire-pulse 2>/dev/null || true

MARK="SPXFIX-$(cut -d. -f1 /proc/uptime)"
echo "$MARK" | sudo tee /dev/kmsg >/dev/null 2>&1 || true
echo "=== single-shot prepare-only (one mem-map) ==="
timeout -k 2 12 "$PREP" plughw:${CARD},0; echo "prepare tool rc=$?"
sleep 2

sudo kill "$WPID" 2>/dev/null
systemctl --user start pipewire pipewire-pulse wireplumber 2>/dev/null || true

echo "=== dmesg since $MARK ==="
sudo dmesg | sed -n "/$MARK/,\$p" | grep -iE "mem_map req|CMDRSP|DSP returned error|Memory_map_regions|alias map failed|watchdog|crash detected|SFR" | head -20

echo "=== RESULT ==="
if [ -f "$ABORT" ]; then
	echo "CRASH: ADSP watchdog -> $(cat "$ABORT")"
	echo "Do NOT re-run; reboot before further audio work."
elif sudo dmesg | sed -n "/$MARK/,\$p" | grep -qiE "DSP returned error.*10d92|Memory_map_regions failed"; then
	echo "EFAILED (graceful): the ADSP still rejected the map. No crash. Safe."
elif sudo dmesg | sed -n "/$MARK/,\$p" | grep -qi "mem_map req"; then
	echo "PASS?: mem-map issued and NOT rejected/crashed -> ADSP likely ACCEPTED it. BREAKTHROUGH."
else
	echo "INCONCLUSIVE: no mem_map req seen (open may have failed earlier)."
fi
echo "Paste this whole output back."
