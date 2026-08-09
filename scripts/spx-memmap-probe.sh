#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# Address-SAFE falsification probes for the ADSP mem-map ACK (run on APR boot).
# These NEVER change the buffer address (stays in the [4GB,8GB) ADSP window), so
# they cannot crash the ADSP out-of-window; worst case is a graceful -110/-22.
# Re-runnable WITHOUT reboot (the card stays up; force-unmap recovers each try).
#
# Usage (set any combination, then re-run):
#   SPX_PFLAG=1 ./scripts/spx-memmap-probe.sh         # H2: property_flag=0x01
#   SPX_POOL=4  ./scripts/spx-memmap-probe.sh         # H3: mem_pool_id sweep
#   SPX_PROT=3  ./scripts/spx-memmap-probe.sh         # H4: alias prot (3=R|W, no CACHE)
# Result: ACK (mem_map_handle set, rc=0) = BREAKTHROUGH; -110 timeout / -22 EFAIL = no.
set -u
PREP=/tmp/spx-pcm-prepare
SRC="$(dirname "$0")/spx-pcm-prepare.c"
[ -x "$PREP" ] || gcc -O2 -o "$PREP" "$SRC" -lasound 2>/dev/null
[ -x "$PREP" ] || { echo "FATAL: prepare tool missing (gcc $SRC failed)"; exit 1; }
sudo grep -aqo "qcom,q6asm-dais" /sys/firmware/fdt 2>/dev/null || { echo "FATAL: not APR boot"; exit 1; }

# Verify the NEW param-carrying modules are loaded (need a fresh boot, not a
# mid-session reload). If the params are absent, the modules are stale.
if [ ! -e /sys/module/q6asm/parameters/property_flag ]; then
	echo "FATAL: q6asm has no property_flag param -> stale module. Reboot to APR"
	echo "       (fresh boot auto-loads the new q6asm/q6asm-dai), then re-run."
	exit 1
fi

if ! grep -q sdm845 /proc/asound/cards 2>/dev/null; then
	echo "=== bringing up APR card (once) ==="
	"$(dirname "$0")/spx-run2-pio-full.sh" >/tmp/spx-bringup.log 2>&1 || true
	grep -q sdm845 /proc/asound/cards 2>/dev/null || sudo modprobe q6asm_dai 2>/dev/null
	sleep 2
fi
grep -q sdm845 /proc/asound/cards 2>/dev/null || { echo "FATAL: no card; see /tmp/spx-bringup.log"; exit 1; }
CARD=$(awk '/sdm845/{print $1; exit}' /proc/asound/cards); CARD=${CARD:-0}

# apply probe params
echo "${SPX_PFLAG:-0}" | sudo tee /sys/module/q6asm/parameters/property_flag >/dev/null
echo "${SPX_POOL:--1}"  | sudo tee /sys/module/q6asm/parameters/mem_pool >/dev/null
echo "${SPX_PROT:-7}"   | sudo tee /sys/module/q6asm_dai/parameters/alias_prot >/dev/null
echo 1 | sudo tee /sys/module/q6asm_dai/parameters/alias_debug >/dev/null
echo 1 | sudo tee /sys/module/q6asm/parameters/memmap_debug >/dev/null
echo "PROBE: property_flag=$(cat /sys/module/q6asm/parameters/property_flag) mem_pool=$(cat /sys/module/q6asm/parameters/mem_pool) alias_prot=$(cat /sys/module/q6asm_dai/parameters/alias_prot)"

systemctl --user stop wireplumber pipewire pipewire-pulse 2>/dev/null || true
pkill -9 -x wireplumber 2>/dev/null || true

ABORT=/tmp/spx-adsp-abort; rm -f "$ABORT"
sudo sh -c 'dmesg -w | while IFS= read -r l; do case "$l" in *"qcom_q6v5_pas"*"watchdog"*|*"crash detected in adsp"*) printf "%s\n" "$l">/tmp/spx-adsp-abort; break;; esac; done' &
WPID=$!
MARK="SPXPROBE-$(cut -d. -f1 /proc/uptime)"
echo "$MARK" | sudo tee /dev/kmsg >/dev/null 2>&1 || true
timeout -k 2 12 "$PREP" plughw:${CARD},0; echo "prepare rc=$?"
sleep 2
sudo kill "$WPID" 2>/dev/null

echo "=== dmesg since mark ==="
sudo dmesg | sed -n "/$MARK/,\$p" | grep -iE "SPX alias|mem_map req|CMDRSP|DSP returned error|Memory_map_regions|qcom_q6v5_pas.*watchdog" | head -12
echo "=== VERDICT ==="
if [ -f "$ABORT" ]; then echo "CRASH (REAL): $(cat $ABORT) — reboot before next probe";
elif sudo dmesg | sed -n "/$MARK/,\$p" | grep -qiE "PREPARE OK|CMDRSP"; then echo "ACK!!! mem-map accepted — BREAKTHROUGH with these params";
elif sudo dmesg | sed -n "/$MARK/,\$p" | grep -qiE "Memory_map_regions failed rc=-110"; then echo "-110 timeout (no ack, no crash) — try next probe";
elif sudo dmesg | sed -n "/$MARK/,\$p" | grep -qiE "Memory_map_regions failed rc=-22|DSP returned error.*10d92"; then echo "-22 EFAILED (reject) — this param made the ADSP reject again";
else echo "INCONCLUSIVE"; fi
