#!/bin/bash
# SPX built-in mic capture probe: make the machine its own listener.
#
# Routes one codec input (DMICn via ADC MUX0=DMIC, or ADCn via ADC MUX0=AMIC)
# through DEC0 -> SLIM TX0 -> AIF1_CAP -> SLIMBUS_0_TX -> MultiMedia2 and
# records SECS seconds, then prints RMS/peak/nonzero stats (stdlib python).
#
# WHY MultiMedia2 and not MultiMedia1: the FE that has a capture BE routed is
# plughw:0,1 (MM2). The earlier y-internal-capture-probe.py used hw:0,0 (MM1)
# with no ALSA mixer routing, so dpcm_fe_dai_open() found no DAPM path to any
# backend DAI and returned -EINVAL ("no backend DAIs enabled for MultiMedia1").
# The routing below is what creates that path; it is required, not cosmetic.
#
# REQUIRES a q6asm-dai with capture parking (2026-08-24 fix: parked[2][16]);
# on older modules one capture close wedges the ADSP ASM service and kills the
# boot's playback. Check for "parking ASM capture session" / "reusing parked
# ASM capture session" in dmesg after the first run. A "Failed to close copp
# -110" on close is EXPECTED and harmless here: the session is parked, not
# freed, and the next run reuses it.
#
# Usage: spx-mic-capture.sh [DMIC0|DMIC1..5|ADC1..4|sweep] [secs]
set -u
SRC=${1:-DMIC0}
SECS=${2:-4}
C=${SPX_CARD:-0}

s() { amixer -c "$C" cset name="$1" "$2" >/dev/null || echo "FAILED ctl: $1=$2" >&2; }

one() {
	local src=$1 tag=$1
	s 'MultiMedia2 Mixer SLIMBUS_0_TX' 1
	s 'AIF1_CAP Mixer SLIM TX0' 1
	s 'CDC_IF TX0 MUX' DEC0
	s 'DEC0 Volume' 84
	if [[ $src == DMIC* ]]; then
		s 'ADC MUX0' DMIC
		s 'DMIC MUX0' "$src"
	else
		s 'ADC MUX0' AMIC
		s 'AMIC MUX0' "$src"
	fi
	printf '<6>SPX_CAP_%s\n' "$tag" | sudo tee /dev/kmsg >/dev/null
	local out="/tmp/cap-$tag.wav"
	rm -f "$out"
	timeout -k 2 $((SECS + 15)) arecord -q -D "plughw:$C,1" -f S16_LE -r 48000 \
		-c 1 -d "$SECS" "$out"
	echo "rc=$?"
	python3 - "$out" "$tag" <<'PY'
import sys, wave, struct, math
try:
    w = wave.open(sys.argv[1]); d = w.readframes(w.getnframes())
except Exception as e:
    print(sys.argv[2], "open fail", e); sys.exit()
v = list(struct.unpack("<%dh" % (len(d) // 2), d))
if not v:
    print(sys.argv[2], "empty"); sys.exit()
rms = math.sqrt(sum(x * x for x in v) / len(v))
pk = max(abs(x) for x in v)
nz = sum(1 for x in v if x)
print(f"{sys.argv[2]}: frames={len(v)} rms={rms:.2f} "
      f"({20 * math.log10(max(rms, 1e-9) / 32768):.1f} dBFS) "
      f"peak={pk} nonzero={100.0 * nz / len(v):.1f}%")
PY
	sudo dmesg | sed -n "/SPX_CAP_$tag/,\$p" |
		grep -E "SPX ASM|parking ASM|reusing parked|timeout|failed|Port Closed" |
		head -6
}

if [[ $SRC == sweep ]]; then
	for x in DMIC0 DMIC1 DMIC2 DMIC3 DMIC4 DMIC5 ADC1 ADC2 ADC3 ADC4; do
		echo "##### $x"
		one "$x"
	done
else
	one "$SRC"
fi
