#!/bin/bash
# SPX AFE speaker-cal live firer.
#
# Fires individual steps of the six-step Windows speaker calibration
# (q6afe_spx_apply_speaker_cal) at the live SLIMBUS_2_RX AFE port through the
# q6afe spx_probe debugfs interface, without rebooting. Payload bytes are
# parsed straight out of sound/soc/qcom/qdsp6/q6afe.c so they cannot drift
# from what the driver itself sends.
#
# Usage: spx-cal-fire.sh STEP [STEP...]     e.g. cumulative bisect: 1 2 3
# Run as the desktop user (uses sudo internally).
#
# Steps (module_id / param_id / size):
#   1  CDC_SLIMBUS_SLAVE_CFG    0x10234 0x10235  16
#   2  CDC_REG_PAGE_CFG         0x10234 0x10296  12
#   3  SLIMBUS_SLAVE_PORT_CFG   0x10230 0x10233  32
#   4  SLIMBUS_CONFIG@0x15200   0x15200 0x10212  24
#   5  CDC_REG_CFG@0x15200      0x15200 0x10236  120
#   6  CDC_REG_CFG_INIT@0x15200 0x15200 0x10237  1

set -euo pipefail
if (( EUID == 0 )); then echo "FATAL: run $0 as the desktop user, not sudo" >&2; exit 1; fi
cd "$(dirname "$0")/.."
sudo -v || exit 1

(( $# >= 1 )) || { echo "usage: $0 STEP [STEP...]" >&2; exit 1; }

DBG=/sys/kernel/debug/q6afe/spx_probe
[[ -d $DBG ]] || { echo "FATAL: $DBG missing (q6afe loaded without debugfs?)" >&2; exit 1; }

declare -A NAME=( [1]=cdc_slimbus_slave_cfg      [2]=cdc_reg_page_cfg
                  [3]=slimbus_slave_port_cfg     [4]=slimbus_config
                  [5]=codec_cal_15200            [6]=codec_cal_commit )
declare -A MOD=(  [1]=0x10234 [2]=0x10234 [3]=0x10230
                  [4]=0x15200 [5]=0x15200 [6]=0x15200 )
declare -A PARAM=( [1]=0x10235 [2]=0x10296 [3]=0x10233
                   [4]=0x10212 [5]=0x10236 [6]=0x10237 )
declare -A SIZE=(  [1]=16 [2]=12 [3]=32 [4]=24 [5]=120 [6]=1 )

for step in "$@"; do
	[[ -n ${NAME[$step]:-} ]] || { echo "no such step: $step" >&2; exit 1; }
done

for step in "$@"; do
	pay=${NAME[$step]}
	hex=$(python3 - "$pay" "${SIZE[$step]}" <<'PYEOF'
import re, sys
name, want = sys.argv[1], int(sys.argv[2])
src = open('sound/soc/qcom/qdsp6/q6afe.c').read()
m = re.search(r'q6afe_spx_' + name + r'\[\]\s*=\s*\{(.*?)\}', src, re.S)
assert m, f"array {name} not found"
vals = re.findall(r'0x([0-9a-fA-F]{2})', m.group(1))
assert len(vals) == want, f"{name}: {len(vals)} bytes != {want}"
print(''.join(vals))
PYEOF
)

	echo "firing step $step ($pay mod ${MOD[$step]} param ${PARAM[$step]} len ${SIZE[$step]})"
	echo "${MOD[$step]}"   | sudo tee "$DBG/module_id" >/dev/null
	echo "${PARAM[$step]}" | sudo tee "$DBG/param_id" >/dev/null
	echo 0 | sudo tee "$DBG/port_index" >/dev/null
	echo 0 | sudo tee "$DBG/use_svc" >/dev/null
	echo 1 | sudo tee "$DBG/hdr_v3" >/dev/null
	printf '%b' "$(echo "$hex" | sed 's/../\\x&/g')" | sudo tee "$DBG/payload" >/dev/null
	echo f | sudo tee "$DBG/fire" >/dev/null
	sleep 0.3
	# The firer logs one "spx_probe: ... -> rc=N" line per invocation; require the
	# most recent one to carry this step's module+param ids and rc=0.
	last=$(sudo dmesg | grep "spx_probe:" | tail -1)
	echo "$last"
	echo "$last" | grep -qiE "mod=${MOD[$step]} param=${PARAM[$step]} .*rc=0$" \
		|| { echo "FATAL: step $step did not ACK rc=0 (got: $last)" >&2; exit 1; }
done

echo "all requested steps fired with rc=0"
