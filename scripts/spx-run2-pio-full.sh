#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# Surface Pro X SLIMbus audio bring-up over PIO/FIFO messaging.
# No BAM DMA, NGD_INT_EN stays 0. Discovers the SLIMbus QMI endpoint
# (service 0x301) dynamically via qrtr-lookup, loads the NGD driver at
# stage 8, brings up the WCD9340 + sound card, sets the playback path.
#
# Playback tests (each starts ADSP audio-data flow, which has wedged the
# platform before — treat as reset-capable):
#   SPX_TEST=mute ./scripts/spx-run2-pio-full.sh
#       1s playback with codec input muxes at ZERO: AFE port + SLIMbus
#       data channel run, codec analog stays silent. Wedge here =
#       AFE/bus-level data-start fault; survival = analog side suspect.
#   SPX_TEST=slim ./scripts/spx-run2-pio-full.sh
#       1s audible tone over the full path.
# Default (no SPX_TEST) stops after mixer setup.
#
# Re-running on the same boot is OK once the sound card exists; the
# bring-up phase is skipped automatically.

set -eu

SPX_SKIP_BRINGUP=""
if lsmod | grep -q '^slim_qcom_ngd_ctrl '; then
	if grep -q 'sdm845' /proc/asound/cards 2>/dev/null; then
		echo "SPX: bring-up already done this boot; skipping to mixer/test"
		SPX_SKIP_BRINGUP=1
	else
		echo "slim_qcom_ngd_ctrl loaded but no sound card; reboot first" >&2
		exit 1
	fi
fi

if [ -z "$SPX_SKIP_BRINGUP" ]; then
	LOOKUP="$(sudo qrtr-lookup 2>/dev/null | awk '$1 == 769 { print $4, $5; exit }')"
	if [ -z "$LOOKUP" ]; then
		echo "SLIMbus QMI service 0x301 not found via qrtr-lookup" >&2
		echo "check: cat /sys/class/remoteproc/remoteproc2/state" >&2
		exit 1
	fi

	SPX_QMI_NODE="${SPX_QMI_NODE:-${LOOKUP% *}}"
	SPX_QMI_PORT="${SPX_QMI_PORT:-${LOOKUP#* }}"

	echo "SPX: PIO full bring-up (stage 8) node=$SPX_QMI_NODE port=$SPX_QMI_PORT"
	sudo modprobe -v slim_qcom_ngd_ctrl \
		spx_pio_mode=1 \
		spx_qmi_bypass_lookup=1 \
		spx_qmi_node="$SPX_QMI_NODE" \
		spx_qmi_port="$SPX_QMI_PORT" \
		spx_probe_stage=8 \
		spx_allow_full=1 \
		spx_power_resp_type=-1
	sleep 3
	ls /sys/bus/slimbus/devices 2>/dev/null || echo "no slimbus devices yet"

	# wcd934x has no working slim modalias autoload here; load explicitly.
	# Its probe pulses the codec reset (TLMM 143, from the SPX DSDT).
	echo "SPX: loading wcd934x + ASoC codec + machine drivers"
	sudo modprobe wcd934x
	sleep 4
	sudo modprobe gpio_wcd934x
	sudo modprobe soundwire_qcom
	sudo modprobe snd_soc_wsa881x
	sudo modprobe snd_soc_wcd934x spx_persist_stream=1
	sudo modprobe snd_soc_sdm845
	sleep 4
	sudo dmesg | grep -iE 'wcd934x|logical' | tail -6 || true
fi

# Park all teardown paths: stream stop / AFE port stop wedge the MSFT
# ADSP. Set via sysfs too in case the modules were already loaded.
echo 1 | sudo tee /sys/module/snd_soc_wcd934x/parameters/spx_persist_stream >/dev/null 2>&1 || true
echo 1 | sudo tee /sys/module/q6afe_dai/parameters/spx_no_port_stop >/dev/null 2>&1 || true
echo "SPX: teardown parking: wcd=$(cat /sys/module/snd_soc_wcd934x/parameters/spx_persist_stream 2>/dev/null) afe=$(cat /sys/module/q6afe_dai/parameters/spx_no_port_stop 2>/dev/null)"

echo "SPX: sound card state:"
cat /proc/asound/cards 2>/dev/null || true

SPX_CARD="$(awk '/sdm845|Surface Pro X/{print $1; exit}' /proc/asound/cards 2>/dev/null)"
SPX_CARD="${SPX_CARD:-0}"
echo "SPX: using ALSA card $SPX_CARD"

echo "SPX: setting playback path (q6 route + SLIM RX -> AIF1 -> HPH/LINEOUT)"
set_ctl() { amixer -q -c "$SPX_CARD" cset name="$1" "$2" 2>/dev/null \
	|| echo "  (control not set: $1)"; }
# Speaker path: MultiMedia1 FE -> SLIMBUS_2_RX BE (AFE 0x4004, the port the ADSP
# keys the WSA speaker bring-up to). The codec then routes SLIM RX0/1 -> INT7/8
# (SPKR) -> SPK1/2 OUT -> internal SWR -> WSA881x (amps driven by the ADSP).
set_ctl 'SLIMBUS_2_RX Audio Mixer MultiMedia1' 1
set_ctl 'SLIM RX0 MUX' AIF1_PB
set_ctl 'SLIM RX1 MUX' AIF1_PB
set_ctl 'RX INT1_1 MIX1 INP0' RX0
set_ctl 'RX INT2_1 MIX1 INP0' RX1
set_ctl 'RX INT1 DEM MUX' CLSH_DSM_OUT
set_ctl 'RX INT2 DEM MUX' CLSH_DSM_OUT
set_ctl 'RX INT3_1 MIX1 INP0' RX0
set_ctl 'RX INT4_1 MIX1 INP0' RX1
set_ctl 'RX INT7_1 MIX1 INP0' RX0
set_ctl 'RX INT8_1 MIX1 INP0' RX1
set_ctl 'COMP7 Switch' on
set_ctl 'COMP8 Switch' on
set_ctl 'RX7 Digital Volume' 84
set_ctl 'RX8 Digital Volume' 84
# NOTE: the old SpkrLeft/SpkrRight COMP/BOOST/DAC/PA controls were wsa881x
# controls; the wsa881x driver is no longer instantiated (the WSA amps are
# ADSP-owned now), so those controls no longer exist. WSA gain/boost/PA is the
# ADSP's job. Do not set them here.
set_ctl 'RX0 Digital Volume' 84
set_ctl 'RX1 Digital Volume' 84
set_ctl 'HPHL Volume' 75%
set_ctl 'HPHR Volume' 75%
set_ctl 'LINEOUT1 Volume' 75%
set_ctl 'LINEOUT2 Volume' 75%

# Keep the journal tail persisted across a potential platform wedge.
sync_loop() { while :; do sudo journalctl --sync 2>/dev/null; sync; sleep 1; done; }

# WirePlumber/PipeWire race the controlled test (their own snd_pcm_prepare
# storms are what we kept debugging instead of the script's). Park them for
# the test, restore on exit.
PW_STOPPED=""
stop_pipewire() {
	if systemctl --user is-active -q wireplumber 2>/dev/null; then
		echo "SPX: stopping wireplumber/pipewire for the controlled test"
		systemctl --user stop wireplumber pipewire pipewire-pulse 2>/dev/null || true
		PW_STOPPED=1
	fi
}
restore_pipewire() {
	if [ -n "$PW_STOPPED" ]; then
		echo "SPX: restarting pipewire/wireplumber"
		systemctl --user start pipewire pipewire-pulse wireplumber 2>/dev/null || true
	fi
}
trap restore_pipewire EXIT INT TERM

# Stereo 48k S16 — the exact shape the DSP accepted before (mono WAVs get
# rejected, DSP error 9, and leave the AFE port state stuck until reboot).
# The first FE open of each boot fails ASM mem-map with DSP error[1]
# (transient); burn it on a throwaway open before the real test.
# NOTE: timeout exits 124 here; "|| true" keeps set -e from silently
# killing the script (this exact bug ate every prior scripted test run).
warmup() {
	timeout -k 2 2 speaker-test -D plughw:${SPX_CARD},0 -c 2 -t sine -f 440 \
		>/dev/null 2>&1 || true
	sleep 1
}

play_short() {
	sync_loop & SYNCPID=$!
	sudo sh -c 'dmesg -w > /tmp/spx-test-dmesg.log' & DMESGPID=$!
	timeout -k 2 3 speaker-test -D plughw:${SPX_CARD},0 -c 2 -t sine -f 440 >/dev/null 2>&1 \
		|| echo "speaker-test rc=$? (timeout 3s is expected)"
	sleep 5
	sudo kill $DMESGPID 2>/dev/null || true
	kill $SYNCPID 2>/dev/null || true
	echo "--- afe/smmu/fault/dpu lines during test:"
	grep -iE 'smmu|fault|afe|q6|dpu error|TX timed' /tmp/spx-test-dmesg.log | tail -15 || true
	echo "--- regression check (want NO output here):"
	grep -iE 'underflow|flushed SWR|Oops|usage count|deadlock|read underflow' \
		/tmp/spx-test-dmesg.log | tail -10 || true
}

case "${SPX_TEST:-none}" in
mute)
	stop_pipewire
	echo "SPX: BISECTION - 3s stereo data start with codec muxes at ZERO"
	set_ctl 'SLIM RX0 MUX' ZERO
	set_ctl 'SLIM RX1 MUX' ZERO
	play_short
	echo "SPX: mute test survived -> AFE/q6asm/bus data flow is OK muted."
	echo "     Next: SPX_TEST=slim $0"
	;;
slim)
	stop_pipewire
	echo "SPX: 3s stereo 440Hz tone -> SLIMBUS_0_RX -> WCD9340 (listen!)"
	set_ctl 'SLIM RX0 MUX' AIF1_PB
	set_ctl 'SLIM RX1 MUX' AIF1_PB
	set_ctl 'Headphone Jack Switch' on
	echo "SPX: warm-up open (first ASM mem-map of a boot fails; expected)"
	warmup
	play_short
	echo "SPX: first play + close survived. Playing AGAIN (reuse path):"
	play_short
	echo "SPX: play->stop->play cycle works. If you heard two tones:"
	echo "SPX: AUDIO IS WORKING. Try music: aplay/pw-play a 48k stereo wav"
	;;
*)
	echo "SPX: mixer path set; no playback run (SPX_TEST unset)."
	echo "     Next: SPX_TEST=mute $0   then   SPX_TEST=slim $0"
	;;
esac
