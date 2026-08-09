#!/bin/bash
# SPX WSA per-amp powerdown-pin test.
#
# Background: both DT speaker nodes used to name the SAME wcd934x GPIO (pin 1),
# so both WSA881x amps powered up together. They share a SoundWire address, so
# both sat unenumerated at device 0 and both answered PING at once -> bus clash
# -> MCP_SLV_STATUS=0x0 and every DevID read returned 0xaa.
#
# This boot: left_spkr=pin1, right_spkr=pin2 (right disabled), and BOTH pins are
# parked output-HIGH (shutdown) by the MFD before the SoundWire master probes.
# wsa881x then powers only its own pin, so exactly one amp is ever on the bus.
#
# Success = DevID reads settle to mfg=0217 part=2010 and the slave ATTACHes.
set -u
cd "$(dirname "$0")/.."

echo "=== [0] boot sanity ==="
if ! grep -q "spx_wsa_gpio_val=0x06" /proc/cmdline; then
	echo "FATAL: not the spx-wsa-pin2-test entry (missing spx_wsa_gpio_val=0x06)"
	echo "  cmdline: $(cat /proc/cmdline)"
	exit 1
fi
echo "  cmdline: OK (both amps parked in shutdown at bring-up)"
sudo dmesg | grep -E "SPX: wcd-gpio forced|SPX: SD_N on wcd-gpio pin" || \
	echo "  WARN: expected MFD/wsa881x pin messages not found"

echo
echo "=== [1] live GPIO state (expect dir=0x06, pin1 LOW, pin2 HIGH => val bit2 set, bit1 clear) ==="
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko 2>/dev/null
sudo dmesg | grep "SPX GPIO" | tail -1

echo
echo "=== [2] card bring-up ==="
if ! grep -q sdm845 /proc/asound/cards 2>/dev/null; then
	./scripts/spx-run2-pio-full.sh >/tmp/spx-bringup.log 2>&1 || true
	sleep 2
fi
grep -q sdm845 /proc/asound/cards 2>/dev/null \
	&& echo "  card: OK" || { echo "FATAL: no card (see /tmp/spx-bringup.log)"; exit 1; }

echo
echo "=== [3] boot-time enumeration diag ==="
sudo dmesg | grep -E "SPX DIAG: |SPX DIAG dev0 FINAL|SPX enum poll" | tail -6
echo "  --- last 6 DevID attempts ---"
sudo dmesg | grep -E "SPX DIAG dev0 try" | tail -6
echo "  --- clashes since boot: $(sudo dmesg | grep -c 'clsh detected') ---"

echo
echo "=== [4] slave status ==="
for d in /sys/bus/soundwire/devices/sdw:0:0:0217:2010:*; do
	[ -e "$d" ] || continue
	echo "  $(basename "$d"): $(cat "$d"/status 2>/dev/null)"
done

if grep -qi '^attached$' /sys/bus/soundwire/devices/sdw:0:0:0217:2010:00:1/status 2>/dev/null; then
	echo
	echo "=== [5] *** LEFT AMP ATTACHED *** playing 5s tone -- LISTEN ==="
	sc(){ amixer -q -c0 cset name="$1" "$2" 2>/dev/null || true; }
	sc "SLIMBUS_2_RX Audio Mixer MultiMedia1" 1
	sc "SLIM RX0 MUX" AIF1_PB; sc "SLIM RX1 MUX" AIF1_PB
	sc "RX INT7_1 MIX1 INP0" RX0; sc "COMP7 Switch" 1
	sc "RX7 Digital Volume" 84
	# Windows allocates all four SoundWire transport ports, but leaves the
	# compander and VI-sense analog paths off for ordinary playback.
	sc "SpkrLeft COMP Switch" 0; sc "SpkrLeft BOOST Switch" 1
	sc "SpkrLeft VISENSE Switch" 0; sc "SpkrLeft DAC Switch" 1
	sc "SpkrLeft WSA PA Volume" 12
	systemctl --user stop wireplumber pipewire pipewire-pulse 2>/dev/null || true
	timeout -k 2 7 speaker-test -D plughw:0,0 -c 2 -t sine -f 440 -l 1 >/dev/null 2>&1
	echo "  rc=$? -- did you HEAR it?"
else
	echo
	echo "RESULT: amp still not attached. Retry enumeration live with:"
	echo "  echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_reenum"
fi
