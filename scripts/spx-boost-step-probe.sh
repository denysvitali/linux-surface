#!/bin/bash
# Boost load-step probe (delta-sweep report 2026-08-23): poll BAT1 V/I fast
# while a play attempt happens ON BATTERY. A conducting WSA881x output stage
# produces a visible boost-current step at PA enable; a non-conducting stage
# shows none. Silent-with-step => data/carrier path alive; silent-without-step
# => output stage open. Meaningless on AC/pending-charge (rate telemetry reads
# zero there) -- unplug first, and record SOC in the run log.
#
# Usage: scripts/spx-boost-step-probe.sh [duration_s]   (default 300)
# Output: /tmp/spx-boost-step-<ts>.csv   epoch,V_uV,I_uA,status,cap

DUR=${1:-300}
OUT=/tmp/spx-boost-step-$(date +%Y%m%d-%H%M%S).csv
echo "epoch,V_uV,I_uA,status,cap" > "$OUT"
echo "logging $OUT for ${DUR}s"
end=$(( $(date +%s) + DUR ))
while (( $(date +%s) < end )); do
	printf '%s,%s,%s,%s,%s\n' \
		"$(date +%s.%N)" \
		"$(cat /sys/class/power_supply/BAT1/voltage_now 2>/dev/null || echo '?')" \
		"$(cat /sys/class/power_supply/BAT1/current_now 2>/dev/null || echo '?')" \
		"$(cat /sys/class/power_supply/BAT1/status 2>/dev/null || echo '?')" \
		"$(cat /sys/class/power_supply/BAT1/capacity 2>/dev/null || echo '?')" >> "$OUT"
	sleep 0.05
done
echo "done: $OUT"
