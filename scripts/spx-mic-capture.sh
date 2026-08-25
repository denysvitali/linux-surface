#!/bin/bash
# SPX built-in mic capture probe: make the machine its own listener.
#
# Routes one codec input (DMICn via ADC MUX0=DMIC, or ADCn via ADC MUX0=AMIC)
# through DEC0 -> SLIM TX0 -> AIF1_CAP -> SLIMBUS_0_TX -> MultiMedia2 and
# records SECS seconds, then prints RMS/peak/nonzero stats (stdlib python).
#
# REQUIRES a q6asm-dai with capture parking (2026-08-24 fix: parked[2][16]);
# on older modules one capture close wedges the ADSP ASM service and kills the
# boot's playback (CLAUDE.md hard rule). Check:
#   sudo dmesg | grep -q "parking ASM capture session" after the first run.
#
# Usage: spx-mic-capture.sh [DMIC0|DMIC1..5|ADC1..4|sweep] [secs]
set -u
SRC=${1:-DMIC0}; SECS=${2:-4}; C=0
if (( EUID == 0 )); then echo "FATAL: run as desktop user" >&2; exit 1; fi
cd "$(dirname "$0")/.."
sudo -v || exit 1
for n in /dev/snd/controlC* /dev/snd/pcmC*; do [ -c "$n" ] && sudo setfacl -m u:"$USER":rw- "$n"; done
s() { amixer -c $C cset name="$1" "$2" >/dev/null || echo "FAILED ctl: $1=$2"; }
one() {
	local src=$1 tag=$1
	s 'MultiMedia2 Mixer SLIMBUS_0_TX' 1
	s 'AIF1_CAP Mixer SLIM TX0' 1
	s 'CDC_IF TX0 MUX' DEC0
	s 'DEC0 Volume' 84
	if [[ $src == DMIC* ]]; then s 'ADC MUX0' DMIC; s 'DMIC MUX0' "$src"
	else s 'ADC MUX0' AMIC; s 'AMIC MUX0' "$src"; fi
	printf '<6>SPX_CAP_%s\n' "$tag" | sudo tee /dev/kmsg >/dev/null
	timeout -k 2 $((SECS+15)) arecord -q -D plughw:$C,1 -f S16_LE -r 48000 -c 1 -d "$SECS" "/tmp/cap-$tag.wav"
	echo "rc=$?"
	python3 - "/tmp/cap-$tag.wav" "$tag" <<'PY'
import sys, wave, struct, math
try:
    w = wave.open(sys.argv[1]); d = w.readframes(w.getnframes())
except Exception as e:
    print(sys.argv[2], "open fail", e); sys.exit()
v = struct.unpack('<%dh' % (len(d)//2), d)
if not v: print(sys.argv[2], "empty"); sys.exit()
rms = math.sqrt(sum(x*x for x in v)/len(v)); pk = max(abs(x) for x in v)
print(f"{sys.argv[2]}: frames={len(v)} rms={rms:.1f} ({20*math.log10(max(rms,1e-9)/32768):.1f} dBFS) peak={pk} nonzero={sum(1 for x in v if x)}")
PY
	sudo dmesg | sed -n "/SPX_CAP_$tag/,\$p" | grep -E "SPX ASM stream|parking ASM|reusing parked|timeout|failed|Port Closed" | head -6
}
if [[ $SRC == sweep ]]; then for x in DMIC0 DMIC1 DMIC2 DMIC3 DMIC4 DMIC5 ADC1 ADC2 ADC3 ADC4; do echo "##### $x"; one $x; done
else one "$SRC"; fi
