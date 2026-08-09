#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# Run on the DEFAULT (APR) boot — NOT the GPR entry. Sweeps the q6asm ASM
# mem-map address mode to find which address space the sc8180x ADSP accepts:
#   0 = IOVA | (sid<<32)   (current; sdm845 convention -> known EFAILED)
#   1 = IOVA, msw=0        (drop the SID tag)
#   2 = phys(IOVA), msw=0  (real DDR physical addr, like Windows qcadcm8180.sys)
#
# For each mode: set the param, open a short stereo PCM (muxes at ZERO so no
# analog), and capture the address sent (memmap_debug) + the ADSP response.
# PASS for a mode = NO "DSP returned error" for opcode 10d92 AND no
# "Memory_map_regions failed" after that mode's open.
set -u

echo "=== boot sanity: must be APR (q6asm-dais), not GPR ==="
if ! sudo grep -aqo "qcom,q6asm-dais" /sys/firmware/fdt 2>/dev/null; then
	echo "FATAL: not the APR DTB (no q6asm-dais). Reboot to the DEFAULT entry." >&2
	exit 1
fi
echo "OK: APR DTB booted"

# Bring up the card if needed (PIO NGD + wcd934x + machine driver).
if ! grep -q 'sdm845' /proc/asound/cards 2>/dev/null; then
	echo "=== bringing up APR audio card ==="
	"$(dirname "$0")/spx-run2-pio-full.sh" >/tmp/spx-bringup.log 2>&1 || true
fi
grep -q 'sdm845' /proc/asound/cards 2>/dev/null || { echo "FATAL: no sound card after bring-up; see /tmp/spx-bringup.log" >&2; exit 1; }
CARD="$(awk '/sdm845/{print $1; exit}' /proc/asound/cards)"; CARD="${CARD:-0}"
echo "card=$CARD"

echo 1 | sudo tee /sys/module/q6asm/parameters/memmap_debug >/dev/null 2>&1 || true
# park teardown + mute the codec path (data-start without analog)
echo 1 | sudo tee /sys/module/snd_soc_wcd934x/parameters/spx_persist_stream >/dev/null 2>&1 || true
echo 1 | sudo tee /sys/module/q6afe_dai/parameters/spx_no_port_stop >/dev/null 2>&1 || true
amixer -q -c "$CARD" cset name='SLIM RX0 MUX' ZERO 2>/dev/null || true
amixer -q -c "$CARD" cset name='SLIM RX1 MUX' ZERO 2>/dev/null || true
amixer -q -c "$CARD" cset name='SLIMBUS_2_RX Audio Mixer MultiMedia1' 1 2>/dev/null || true

systemctl --user stop wireplumber pipewire pipewire-pulse 2>/dev/null || true

PARAM=/sys/module/q6asm_dai/parameters/memmap_mode
if ! sudo test -e "$PARAM"; then echo "FATAL: param missing at $PARAM" >&2; exit 1; fi
RESULT=""
for MODE in 0 1 2; do
	echo
	echo "============================================================"
	echo "=== MEM-MAP MODE $MODE ==="
	echo "$MODE" | sudo tee "$PARAM" >/dev/null
	echo "param now reads: $(sudo cat "$PARAM")   (expect $MODE)"
	MARK="SPXMODE$MODE-$(cat /proc/uptime | cut -d. -f1)"
	echo "$MARK" | sudo tee /dev/kmsg >/dev/null 2>&1 || true
	# short open; timeout exit is expected
	timeout -k 2 3 speaker-test -D plughw:${CARD},0 -c 2 -t sine -f 440 >/dev/null 2>&1 || true
	sleep 1
	echo "--- address sent + ADSP response for mode $MODE ---"
	sudo dmesg | sed -n "/$MARK/,\$p" | grep -iE "mem_map req|DSP returned error.*10d92|Memory_map_regions|CMDRSP|Buffer Allocation|prepare" | head -12
	if sudo dmesg | sed -n "/$MARK/,\$p" | grep -qiE "DSP returned error.*10d92|Memory_map_regions failed"; then
		echo ">> MODE $MODE: EFAILED (rejected)"
		RESULT="$RESULT mode$MODE=FAIL"
	else
		if sudo dmesg | sed -n "/$MARK/,\$p" | grep -qi "mem_map req"; then
			echo ">> MODE $MODE: NO map-reject seen — POSSIBLE PASS"
			RESULT="$RESULT mode$MODE=PASS?"
		else
			echo ">> MODE $MODE: no mem-map attempted (open may have failed earlier)"
			RESULT="$RESULT mode$MODE=NOMAP"
		fi
	fi
done

systemctl --user start pipewire pipewire-pulse wireplumber 2>/dev/null || true
echo
echo "============================================================"
echo "SUMMARY:$RESULT"
echo "(PASS? = the ADSP did NOT reject that address space — that's the lead.)"
echo "Paste this whole output back."
