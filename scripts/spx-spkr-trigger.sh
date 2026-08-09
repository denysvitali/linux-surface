#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# spx-spkr-trigger.sh - try to make the SPX speakers audible by replaying the
# Windows device-0x45 WSA speaker-enable AFE SET_PARAMs into a LIVE SLIMBUS_2_RX
# stream, via the q6afe debugfs probe (scripts/spx-spkr-probe.sh).
#
# Background: after the contention-removal fix the ADSP solely owns the WCD9340
# internal SWR master; playback is on AFE SLIMBUS_2_RX (idx 6, port 0x4004 - the
# port the ADSP keys the dev-0x45 speaker calibration to). The path runs but is
# SILENT because the ADSP was never told to enable the speaker device. Windows
# sends codec/SLIMbus speaker-config SET_PARAMs on dev 0x45; mainline q6 never
# does. This fires the candidate enable params so you can LISTEN for which works.
#
# Several fields are GUESSES - the SLIMbus logical addresses and the EA packing
# are not exported by Linux, and the DSP acks many params regardless of effect
# (rc=0 != working). YOUR EARS are the only reliable signal. Override the
# guessed values with the flags below and re-run.
#
# SAFETY: SET_PARAM only - never emits an AFE port STOP (sc8180x ADSP wedge);
# never reads 171c0000+0x2000 or pinmux-pins. Exit/Ctrl-C restores pipewire.
#
# USAGE (card must be up: run ./scripts/spx-run2-pio-full.sh once first):
#   ./scripts/spx-spkr-trigger.sh [-i idx] [-e ealsw] [-E eamsw] [-p pgd] [-f ifd]
#     -i idx    AFE port enum index (default 6 = SLIMBUS_2_RX)
#     -e/-E     device_enum_addr lsw/msw (hex)   [default: WCD9340 PGD, dev_index 1]
#     -p/-f     codec PGD / IFD SLIMbus logical address (hex)  [guessed 0x01/0x02]
# LISTEN during each "=== LISTEN n ===" pause; report which step (if any) plays.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PROBE="$HERE/spx-spkr-probe.sh"
CARD=0
IDX=6                       # SLIMBUS_2_RX = q6afe enum idx 6 (AFE port 0x4004)
MOD=0x0001020c              # AFE_MODULE_AUDIO_DEV_INTERFACE
# WCD9340 EA: manf 0x217, prod 0x250, dev_index 1 (PGD = 217:250:1:0), instance 0.
# (hex IDs, NOT decimal). Packing is ambiguous; this is the most likely layout.
EA_LSW=0x02500100
EA_MSW=0x00000217
PGD_LA=0x01                 # GUESS - codec PGD logical addr
IFD_LA=0x02                 # GUESS - codec IFD logical addr
# FIRM: dev-0x45 COPP topology id (ACDB DPROP 0x113af leads with 0x10000001).
# Non-NULL topology is the GATE that makes the ADSP instantiate the speaker
# subgraph instead of the silent NULL_COPP legacy path. Set BEFORE the stream
# opens (q6routing reads it at q6routing_stream_open).
TOPO=0x10000001
ACDB=0x45

while getopts "i:e:E:p:f:t:" o; do
	case "$o" in
	i) IDX=$OPTARG ;; e) EA_LSW=$OPTARG ;; E) EA_MSW=$OPTARG ;;
	p) PGD_LA=$OPTARG ;; f) IFD_LA=$OPTARG ;; t) TOPO=$OPTARG ;; *) exit 2 ;;
	esac
done

[ -x "$PROBE" ] || { echo "missing $PROBE" >&2; exit 1; }
sudo test -d /sys/kernel/debug/q6afe/spx_probe || {
	echo "no q6afe spx_probe debugfs - is the patched q6afe.ko loaded?" >&2; exit 1; }

le32() { printf '%08x' "$(($1))" | sed -E 's/(..)(..)(..)(..)/\4\3\2\1/'; }
le16() { printf '%04x' "$(($1))" | sed -E 's/(..)(..)/\2\1/'; }

echo "=== SPX speaker trigger: idx=$IDX EA=$EA_MSW:$EA_LSW pgd=$PGD_LA ifd=$IFD_LA ==="

# Park pipewire and set the codec SPKR digital path (SLIM RX0/1 -> INT7/8 -> SPK1/2).
systemctl --user stop wireplumber pipewire pipewire-pulse 2>/dev/null || true
sleep 1

# PRIMARY LEVER: set the dev-0x45 COPP topology BEFORE the stream opens, so the
# ADSP instantiates the speaker subgraph (non-NULL topology gate). This alone
# may produce sound; the AFE candidate fires below are the fallback.
QR=/sys/module/q6routing/parameters	# module is "q6routing", not snd_soc_q6routing
if [ -w "$QR/spx_rx_topology" ] || sudo test -e "$QR/spx_rx_topology"; then
	echo "$TOPO" | sudo tee "$QR/spx_rx_topology" >/dev/null
	echo "$ACDB" | sudo tee "$QR/spx_rx_acdb_id" >/dev/null 2>&1 || true
	echo "set spx_rx_topology=$TOPO spx_rx_acdb_id=$ACDB (dev-0x45 COPP subgraph)"
else
	echo "WARNING: $QR/spx_rx_topology missing - q6routing knob not loaded; topology lever inactive"
fi

sc() { amixer -q -c "$CARD" cset name="$1" "$2" 2>/dev/null || echo "  (miss: $1)"; }
sc 'SLIMBUS_2_RX Audio Mixer MultiMedia1' 1
sc 'SLIM RX0 MUX' AIF1_PB; sc 'SLIM RX1 MUX' AIF1_PB
sc 'RX INT7_1 MIX1 INP0' RX0; sc 'RX INT8_1 MIX1 INP0' RX1
sc 'COMP7 Switch' on; sc 'COMP8 Switch' on
sc 'RX7 Digital Volume' 84; sc 'RX8 Digital Volume' 84

# Hold a PERSISTENT stream open so AFE port 6 stays live (the probe borrows its
# token). speaker-test loops until killed.
echo "=== starting persistent 440Hz stream (port $IDX must go live) ==="
( speaker-test -D plughw:$CARD,0 -c 2 -t sine -f 440 >/tmp/spx-trigger-play.log 2>&1 ) &
PLAY=$!
cleanup() { kill $PLAY 2>/dev/null; systemctl --user start pipewire pipewire-pulse wireplumber 2>/dev/null || true; }
trap cleanup EXIT INT TERM
sleep 4
kill -0 $PLAY 2>/dev/null || { echo "playback did not start:"; cat /tmp/spx-trigger-play.log; exit 1; }
echo "stream running (pid $PLAY)."
echo "=== LISTEN 0 (topology subgraph): the COPP opened with topology $TOPO. If you"
echo "    hear 440Hz NOW, the topology lever worked - the speakers are alive. Stop here."
echo "    (The AFE candidate fires below are only needed if this is still silent.)"
sleep 6
echo

fire() { # $1 label  $2 svcflag(-s|"")  $3 param  $4 hex
	echo ">>> $1  (param=$3 ${2:+SVC}${2:-PORT} idx=$IDX)"
	sh "$PROBE" $2 -m "$MOD" -p "$3" -i "$IDX" -x "$4" 2>&1 | sed 's/^/    /'
}

# Candidate 1+2 = the device-enable pair (most likely missing piece): tell the
# ADSP the codec SLIMbus slave + the speaker port channel map (192/193 FIRM from ACDB).
echo "=== Candidate 1: CDC_SLIMBUS_SLAVE_CFG (param 0x10235, EA $EA_MSW:$EA_LSW) ==="
fire "cdc_slimbus_slave_cfg" "-s" 0x00010235 \
	"$(le32 1)$(le32 "$EA_LSW")$(le32 "$EA_MSW")$(le16 0)$(le16 0)"
echo "=== LISTEN 1 ==="; sleep 4

echo "=== Candidate 2: SLIMBUS_SLAVE_PORT_CFG (param 0x10233, ch 192/193) ==="
fire "slimbus_slave_port_cfg 16-bit" "-s" 0x00010233 \
	"$(le32 1)$(le16 0)$(le16 "$PGD_LA")$(le16 "$IFD_LA")$(le16 16)$(le16 0)$(le16 2)c0c1"
echo "=== LISTEN 2 ==="; sleep 5

echo "=== Candidate 2b: SLIMBUS_SLAVE_PORT_CFG 24-bit ==="
fire "slimbus_slave_port_cfg 24-bit" "-s" 0x00010233 \
	"$(le32 1)$(le16 0)$(le16 "$PGD_LA")$(le16 "$IFD_LA")$(le16 24)$(le16 0)$(le16 2)c0c1"
echo "=== LISTEN 2b ==="; sleep 5

# Candidate 3 = AFE SLIMBUS_CONFIG (param 0x216) re-point the running port to ch 192/193.
echo "=== Candidate 3: AFE SLIMBUS_CONFIG shared-ch 192/193 (param 0x216) ==="
fire "slimbus_cfg 0xc0/0xc1" "" 0x00000216 \
	"$(le32 1)$(le16 0)$(le16 16)$(le16 0)$(le16 2)c0c1000000000000"
echo "=== LISTEN 3 ==="; sleep 5

# Candidate 4 = FB speaker-protection enable (after the path is up).
echo "=== Candidate 4: FBSP_MODE_RX_CFG enable (param 0x1021d) ==="
fire "fbsp_mode_rx" "-s" 0x0001021d "$(le32 1)$(le32 0)"
echo "=== LISTEN 4 ==="; sleep 5

echo
echo "=== done. Which step (if any) produced sound? ==="
echo "rc=0 just means the DSP acked (it acks garbage too) - only audio counts."
echo "Re-run with overrides if you learn the real EA/laddr, e.g.:"
echo "  $0 -e 0x02500000 -E 0x00000217   # devidx-0 EA variant"
echo "Exit restores pipewire + stops the stream."
sleep 2
