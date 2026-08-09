#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# spx-spkr-replay.sh - replay the Windows dev-0x45 SPX speaker APR enable
# sequence against the live ADSP, using the new q6adm.ko (sha e2d771f7)
# V8 device-open + V6 SET_PP_PARAMS debugfs probes, plus scripts/spx-spkr-probe.sh
# for AFE SET_PARAM. NEVER emits a port/COPP STOP or CLOSE (wedges the ADSP).
#
# Background: prior RE (A, B, C, D) found the dev-0x45 enable order is:
#   1) AFE SVC SET_PARAM 0x100FA - SLIMbus slave-port cfg (param 0x10233) +
#      shared-channel assignment (0xc0/0xc1 = ch 192/193) - via qcauddev
#   2) ADM DEVICE_OPEN_V8 (0x1036A) with topology 0x10000001 (AR speaker)
#   3) ADM MATRIX_MAP_ROUTINGS_V5 (0x10325) - TBD: not yet in q6adm debugfs
#   4) AFE_PORT_CMD_DEVICE_START (0x100E5) - via the regular Q6 path
#   5) per-COPP SET_PP_PARAMS_V6 (0x1035D) - cal blobs from ACDB modules
#      0x10921 (params 0x10922, 0x10923, 0x10924), 0x10943 (iid=1; 0x10944,
#      0x10945, 0x10946), 0x10bfe (param 0x10c29)
#
# USAGE (card must be up: run ./scripts/spx-run2-pio-full.sh once first):
#   sudo ./scripts/spx-spkr-replay.sh
# LISTEN during each "=== LISTEN n ===" pause; report which step (if any) plays.
# Override TOPOLOGY/CH/BW/RATE via env: TOPOLOGY=0x10000001 CH=2 BW=24 RATE=48000
#
# REQUIRES: q6adm.ko sha >= e2d771f7 (V8 + v8_open debugfs), the spx_spkr_probe
# and the bring-up script for the codec SPKR digital path.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PROBE="$HERE/spx-spkr-probe.sh"
CARD=0
IDX=6                                  # SLIMBUS_2_RX = q6afe enum idx 6 (port 0x4004)
QA=/sys/kernel/debug/q6adm/spx_copp
TOPOLOGY=${TOPOLOGY:-0x10000001}       # ACDB DPROP 0x113af dev 0x45
CH=${CH:-2}
BW=${BW:-24}
RATE=${RATE:-48000}

le32() { printf '%08x' "$(($1))" | sed -E 's/(..)(..)(..)(..)/\4\3\2\1/'; }
le16() { printf '%04x' "$(($1))" | sed -E 's/(..)(..)/\2\1/'; }

sudo test -d "$QA" || {
    echo "no $QA - is the V8-capable q6adm.ko loaded?" >&2; exit 1; }
sudo test -e "$QA/v8_open" || {
    echo "no v8_open knob - wrong q6adm.ko (need sha >= e2d771f7)" >&2; exit 1; }

# Park pipewire + set codec SPKR digital path (SLIM RX0/1 -> INT7/8 -> SPK1/2).
systemctl --user stop wireplumber pipewire pipewire-pulse 2>/dev/null || true
sleep 1

sc() { amixer -q -c "$CARD" cset name="$1" "$2" 2>/dev/null || echo "  (miss: $1)"; }
sc 'SLIMBUS_2_RX Audio Mixer MultiMedia1' 1
sc 'SLIM RX0 MUX' AIF1_PB; sc 'SLIM RX1 MUX' AIF1_PB
sc 'RX INT7_1 MIX1 INP0' RX0; sc 'RX INT8_1 MIX1 INP0' RX1
sc 'COMP7 Switch' on; sc 'COMP8 Switch' on
sc 'RX7 Digital Volume' 84; sc 'RX8 Digital Volume' 84

echo "=== SPX dev-0x45 speaker-enable replay: topology=0x$(printf %x $TOPOLOGY) ${CH}ch ${BW}b ${RATE}Hz ==="
echo "(reboot + bring-up required: q6adm.ko sha >= e2d771f7)"
echo

# Persistent stream so a COPP exists for the V8 to allocate against.
echo "=== start persistent 440Hz stream on SLIMBUS_2_RX ==="
( speaker-test -D plughw:$CARD,0 -c 2 -t sine -f 440 >/tmp/spx-replay-play.log 2>&1 ) &
PLAY=$!
trap "kill $PLAY 2>/dev/null; systemctl --user start pipewire pipewire-pulse wireplumber 2>/dev/null || true" EXIT INT TERM
sleep 4
kill -0 $PLAY 2>/dev/null || { echo "playback failed:"; cat /tmp/spx-replay-play.log; exit 1; }
echo "stream running (pid $PLAY)."
echo

# ---- Step 1: V8 device-open with AR speaker topology ----
echo "=== STEP 1: ADM DEVICE_OPEN_V8 (0x1036A) topology=0x$(printf %x $TOPOLOGY) ==="
echo 6 | sudo tee $QA/port_index >/dev/null
echo 0 | sudo tee $QA/copp_index >/dev/null
echo $TOPOLOGY | sudo tee $QA/v8_topology >/dev/null
echo $CH       | sudo tee $QA/v8_channels >/dev/null
echo $BW       | sudo tee $QA/v8_bit_width >/dev/null
echo $RATE     | sudo tee $QA/v8_sample_rate >/dev/null
sudo dmesg -C
echo 1 | sudo tee $QA/v8_open >/dev/null
sleep 2
echo "  V8 open dmesg:"
sudo dmesg | grep -iE 'V8 open|spx_copp|return error' | sed 's/^/    /'
echo
echo "=== LISTEN 1 (V8 open only) - if you hear 440Hz the V8 open + topology"
echo "    instantiated the speaker subgraph and routed the stream. If still"
echo "    silent, continue to step 2 (per-COPP cal apply). ==="
sleep 6
echo

# ---- Step 2: per-COPP SET_PP_PARAMS_V6 cal blobs from ACDB ----
echo "=== STEP 2: SET_PP_PARAMS_V6 per-COPP cal (modules from ACDB dev-0x45) ==="
# The ACDB payloads (little-endian hex) from Speaker_cal.acdb AGII dev0x45
# 0x10921/0x10922 = 12B, 0x10921/0x10923 = 24B, 0x10921/0x10924 = 0x1028B (too big, sub-blob)
# 0x10943(iid=1)/0x10944, 0x10943/0x10945 = 0x474B, 0x10943/0x10946 = 0x34B
# 0x10bfe/0x10c29 = 12B
echo 6 | sudo tee $QA/port_index >/dev/null
echo 0 | sudo tee $QA/copp_index >/dev/null
echo 6 | sudo tee $QA/phdr_ver >/dev/null

spx_set() { # $1 module $2 param $3 hexpayload
  echo "$1" | sudo tee $QA/module_id >/dev/null
  echo "$2" | sudo tee $QA/param_id  >/dev/null
  printf '%s' "$3" | xxd -r -p | sudo tee $QA/payload >/dev/null
  sudo dmesg -C
  echo 1 | sudo tee $QA/fire >/dev/null
  sleep 1
  echo "  SET mod=$1 param=$2 : $(sudo dmesg | grep -iE 'spx_copp SET|return error' | tail -1 | sed 's/^/    /')"
}

# Module 0x10921 (small params - 12B / 24B - first two are very small)
spx_set 0x00010921 0x00010922 "080000000000000001000000"
spx_set 0x00010921 0x00010923 "1400000000000000010000000600000000000000ff010000"
spx_set 0x00010bfe 0x00010c29 "0c000000000000000100000000000000"

echo "=== LISTEN 2 (V8 + cal) - did applying cal make the path audible? ==="
sleep 6
echo

# ---- Step 3: AFE port DEVICE_START (the regular Q6 path already does this
# implicitly when speaker-test opens; included here as a no-op confirm).
echo "=== STEP 3: AFE port start (port $IDX) - already running via speaker-test ==="
echo "    Re-firing the existing AFE port start would emit a redundant command;"
echo "    if you're still silent, the right next test is the AFE SLIMbus slave-cfg"
echo "    SET_PARAMs (qcauddev8180.sys's job) at this port."
echo

# Cleanup
kill $PLAY 2>/dev/null
systemctl --user start pipewire pipewire-pulse wireplumber 2>/dev/null || true
echo "=== done. Re-run with overrides if you learn the right values, e.g.:"
echo "  TOPOLOGY=0x10000018 CH=2 BW=24 RATE=48000 sudo $0"
echo "rc/ack != sound - only audio counts. ==="
sleep 1
