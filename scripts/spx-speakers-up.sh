#!/bin/bash
# SPX: bring the built-in speaker up from a fresh boot.
#
# Boot the single-amp GRUB entry first. It parks both WSA amps LOW (off), disables
# the right WSA codec in DT, and loads the left codec in write-only mode. The
# script then raises only pin 1, so exactly one amp is at enumeration address 0.
# Two amps powered together collide at device 0 and nothing enumerates at all.
#
# Verified working chain (2026-07-25): amp enumerates for real
# (MCP_SLV_STATUS=0x4), writes reach it (spx_write_dev0 MUST be 0), and the
# speaker produces a tone.
set -u
cd "$(dirname "$0")/.."

echo "=== [0] sanity ==="
grep -q "spx_wsa_gpio_val=" /proc/cmdline \
	|| { echo "FATAL: not a guarded single-amp test entry"; exit 1; }
grep -q "spx_wsa_gpio_val=0x00" /proc/cmdline \
	|| { echo "FATAL: both amps were not parked off at boot"; exit 1; }
[ "$(cat /sys/module/soundwire_qcom/parameters/spx_core_enum)" = 1 ] \
	|| { echo "FATAL: spx_core_enum is not enabled"; exit 1; }
[ "$(cat /sys/module/soundwire_qcom/parameters/spx_no_assign)" = 1 ] \
	|| { echo "FATAL: stable device-0 mode is not enabled"; exit 1; }
[ "$(cat /sys/module/snd_soc_wsa881x/parameters/spx_write_only)" = Y ] \
	|| { echo "FATAL: WSA write-only mode is not enabled"; exit 1; }

echo "=== [1] codec / SLIMbus bring-up ==="
if ! grep -q sdm845 /proc/asound/cards 2>/dev/null; then
	./scripts/spx-run2-pio-full.sh >/tmp/spx-bringup.log 2>&1 || true
	sleep 2
fi
grep -q sdm845 /proc/asound/cards 2>/dev/null \
	|| { echo "FATAL: no sound card (see /tmp/spx-bringup.log)"; exit 1; }

echo "=== [2] enumerate the single powered amp ==="
# The amp only announces itself on the bus for a brief window after it powers up,
# so power-cycle it via the WCD GPIO immediately before forcing the attach.
# Without this, force-attach writes the device number into a void and
# MCP_SLV_STATUS stays 0x0. dir=0x06 both pins output; val bit1=pin1, bit2=pin2;
# Physical HIGH = amp on. 0x00 = both off, 0x02 = pin1 on / pin2 off.
# 10 s off: 2 s was repeatedly not enough for the amp to announce afterwards.
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x00 2>/dev/null
sleep 10
sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val=0x02 2>/dev/null
sleep 0.5
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_force_attach >/dev/null
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_reenum >/dev/null
sleep 25

echo "=== [3] verify a REAL attach (hardware register, not sysfs) ==="
# sysfs 'status' lies when spx_blind_attach=1 -- only MCP_SLV_STATUS counts.
# 0x1 = the preferred stable device-0 state. 0x4 = device 1 attached and is
# acceptable because post_bank_switch refreshes routing if it later falls to 0.
# 0x0 means no amp is visible, so do not start a stream in that state.
sudo insmod drivers/spx_extras/spx_swrm_regs.ko 2>/dev/null; sleep 2
sudo rmmod spx_swrm_regs 2>/dev/null
SLV=$(sudo dmesg | grep "MCP_SLV_STATUS" | tail -1 | grep -o '0x[0-9a-f]\{8\}' | head -1)
echo "  MCP_SLV_STATUS = $SLV"
case "$SLV" in
	0x00000001) echo "  stable device-0 state detected" ;;
	0x00000004) echo "  device 1 attached; stream-start refresh will follow any fallback" ;;
	*) echo "FATAL: no trustworthy single-amp status; refusing playback"; exit 1 ;;
esac

echo "=== [4] write routing (auto) ==="
# A slave answers only ONE address. The blind device-number assignment does not
# always stick, so the amp is sometimes at device 1 (MCP_SLV_STATUS=0x4) and
# sometimes still at device 0 (0x1). spx_write_dev0=-1 makes the driver follow
# MCP_SLV_STATUS instead of guessing; a wrong fixed value silently discards every
# register write, because unicast writes always report success.
echo "  spx_write_dev0 = $(cat /sys/module/soundwire_qcom/parameters/spx_write_dev0) (-1 = auto)"
sudo dmesg | grep "writes go to device" | tail -1

echo "=== [5] mixer path ==="
sc(){ amixer -q -c0 cset name="$1" "$2" 2>/dev/null || true; }
sc "SLIMBUS_2_RX Audio Mixer MultiMedia1" 1
sc "SLIM RX0 MUX" AIF1_PB; sc "SLIM RX1 MUX" AIF1_PB
sc "RX INT7_1 MIX1 INP0" RX0
sc "COMP7 Switch" 1
sc "RX7 Digital Volume" 100
sc "RX8 Digital Volume" 100
# The SPX driver now allocates the Windows four-port transport independently
# from these analog controls. Keep COMP and VISENSE processing off while still
# transporting their Windows sideband slots; BOOST remains physically enabled.
sc "SpkrLeft COMP Switch" 0
sc "SpkrLeft VISENSE Switch" 0
sc "SpkrLeft BOOST Switch" 1
sc "SpkrLeft DAC Switch" 1
sc "SpkrLeft PA Volume" 12   # must come AFTER any spx_rearm_init
sc "SpkrLeft Smart Boost Level" 8

echo "=== [6] tone ==="
systemctl --user stop wireplumber pipewire pipewire-pulse 2>/dev/null || true
timeout -k 2 8 speaker-test -D plughw:0,0 -c 2 -t sine -f 440 >/dev/null 2>&1
echo "  played 8s 440Hz -- audible?"
echo
echo "Notes:"
echo " * The stream allocates all four Windows transport descriptors (mask=15)"
echo "   while COMP/VISENSE analog processing remains off."
echo " * qcom,port-mapping = <1 2 3 7> is byte-identical to Windows."
echo " * If it is quiet, check that PA gain is in REGISTER mode (not DRE) and that"
echo "   'writes go to device N' above matches MCP_SLV_STATUS."
echo " * Keep spx_mirror_banks=0 and spx_write_twice=0: both extra-write modes"
echo "   desynchronize this amp. Amp at dev0 (SLV=0x1) is FINE -- write routing"
echo "   follows it."
echo " * NEVER read /sys/module/soundwire_qcom/parameters/spx_reenum (blocks)."
