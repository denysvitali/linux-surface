#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# Drive the q6afe SPX speaker bring-up probe (needs CONFIG_DEBUG_FS + the
# q6afe.ko debugfs hook). Fires one AFE SET_PARAM at a live AFE port and logs
# the DSP's response, to empirically determine what the SPX ADSP accepts for
# speaker bring-up (the bring-up protocol — legacy ELITE AFE vs GSL graph — is
# undetermined, so we probe rather than assume).
#
# The target port (default SLIMBUS_2_RX = index 6) MUST be live: open a playback
# stream first so the port is in afe->port_list and the response gate passes.
# Easiest: run `./scripts/spx-run2-pio-full.sh` (no SPX_TEST) in another shell,
# or `aplay -D plughw:0,0 <48k stereo wav>` while probing.
#
# Usage:
#   spx-spkr-probe.sh -m <module_id> -p <param_id> [-i port_index] [-s] [-2|-3] \
#                     (-x <hexbytes> | -f <binfile>)
#     -m/-p  AFE module/param ids (hex ok, e.g. 0x00010236)
#     -i     AFE port enum index (default 6 = SLIMBUS_2_RX)
#     -s     use service-level SET_PARAM instead of port-level SET_PARAM
#     -3     use SPX V3 header/opcodes (default; the stub ADSP parses these)
#     -2     force legacy V2 header/opcodes for comparison probes
#     -x     payload as a hex string ("0102.." or with spaces)
#     -f     payload from a binary file (e.g. a blob dumped from the ACDB)
#
# rc=0 => DSP accepted the param. -ETIMEDOUT => no live port at that index (open
# a stream) or no response. -EINVAL => DSP rejected (wrong module/param/size).
#
# SAFETY: SET_PARAM only — never sends an AFE port STOP (which wedges the SPX
# ADSP). Never read 171c0000+0x2000 or pinmux-pins on sc8180x (wedge/oops).

set -u
DBG=/sys/kernel/debug/q6afe/spx_probe
MOD=""; PARAM=""; IDX=6; SVC=0; HDR_V3=1; HEX=""; FILE=""

while getopts "m:p:i:s23x:f:" o; do
	case "$o" in
	m) MOD=$OPTARG ;;
	p) PARAM=$OPTARG ;;
	i) IDX=$OPTARG ;;
	s) SVC=1 ;;
	2) HDR_V3=0 ;;
	3) HDR_V3=1 ;;
	x) HEX=$OPTARG ;;
	f) FILE=$OPTARG ;;
	*) exit 2 ;;
	esac
done

# debugfs is root-only (0700), so stat the dir via sudo, not as the calling user.
sudo test -d "$DBG" || { echo "no $DBG - is the patched q6afe.ko loaded (CONFIG_DEBUG_FS)?" >&2; exit 1; }
[ -n "$MOD" ] && [ -n "$PARAM" ] || { echo "need -m <module_id> and -p <param_id>" >&2; exit 2; }

echo "$MOD"   | sudo tee "$DBG/module_id"  >/dev/null
echo "$PARAM" | sudo tee "$DBG/param_id"   >/dev/null
echo "$IDX"   | sudo tee "$DBG/port_index" >/dev/null
echo "$SVC"   | sudo tee "$DBG/use_svc"    >/dev/null
if sudo test -e "$DBG/hdr_v3"; then
	echo "$HDR_V3" | sudo tee "$DBG/hdr_v3" >/dev/null
elif [ "$HDR_V3" != 0 ]; then
	echo "no $DBG/hdr_v3 - loaded q6afe.ko lacks the SPX V3 probe path" >&2
	exit 1
fi

if [ -n "$HEX" ]; then
	printf '%s' "$HEX" | tr -d ' \n' | xxd -r -p | sudo tee "$DBG/payload" >/dev/null
elif [ -n "$FILE" ]; then
	cat "$FILE" | sudo tee "$DBG/payload" >/dev/null
else
	echo "need -x <hex> or -f <binfile>" >&2; exit 2
fi

echo "SPX probe: mod=$MOD param=$PARAM port_idx=$IDX use_svc=$SVC hdr_v3=$HDR_V3 -> firing"
if echo 1 | sudo tee "$DBG/fire" >/dev/null 2>&1; then
	echo "  fired: rc=0 (DSP accepted the param)"
else
	echo "  fire returned error (see dmesg below)"
fi
sudo dmesg | grep -iE 'spx_probe|DSP returned error' | tail -4 || true
