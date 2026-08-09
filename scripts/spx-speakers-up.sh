#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Guarded Surface Pro X single-amplifier playback test.
#
# Run this as the logged-in desktop user, never through sudo. The script uses
# sudo only for the hardware operations that require it, so it can reliably
# stop and restore that user's PipeWire services.

set -euo pipefail

if (( EUID == 0 )); then
	echo "FATAL: run $0 as the desktop user, without sudo" >&2
	exit 1
fi

cd "$(dirname "$0")/.."

fatal()
{
	echo "FATAL: $*" >&2
	exit 1
}

sudo -v || fatal "sudo authentication failed"
systemctl --user show-environment >/dev/null 2>&1 ||
	fatal "the desktop user's systemd service manager is unavailable"

LOG_DIR="/var/tmp/spx-speaker-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/run.log") 2>&1
cp /proc/cmdline "$LOG_DIR/cmdline"
echo "SPX: persistent diagnostics: $LOG_DIR"

PW_RESTORE_UNITS=()
TONE_PID=
DMESG_PID=
SYNC_PID=
SPX_CARD=
HARDWARE_TOUCHED=0
TEST_SUCCEEDED=0
KERNEL_FAULT=0
KERNEL_FAULT_RE='soft lockup|hard LOCKUP|rcu.*stall|kernel panic|Oops:'
KERNEL_FAULT_RE+='|Internal error:|SError|hung task|synchronous external abort'
KERNEL_FAULT_RE+='|watchdog: BUG'
stop_tone()
{
	local i

	[[ -n ${TONE_PID:-} ]] || return 0
	# speaker-test and timeout run in a private session. Stop and reap that
	# whole group before touching PA/GPIO state on any active-stream failure.
	kill -TERM -- "-$TONE_PID" 2>/dev/null ||
		kill -TERM "$TONE_PID" 2>/dev/null || true
	for ((i = 0; i < 20; i++)); do
		kill -0 "$TONE_PID" 2>/dev/null || break
		sleep 0.1
	done
	if kill -0 "$TONE_PID" 2>/dev/null; then
		kill -KILL -- "-$TONE_PID" 2>/dev/null ||
			kill -KILL "$TONE_PID" 2>/dev/null || true
	fi
	wait "$TONE_PID" 2>/dev/null || true
	TONE_PID=
}
cleanup()
{
	set +e
	stop_tone
	if [[ -n ${DMESG_PID:-} ]]; then
		kill "$DMESG_PID" 2>/dev/null || true
	fi
	if [[ -n ${SYNC_PID:-} ]]; then
		kill "$SYNC_PID" 2>/dev/null || true
	fi
	if (( HARDWARE_TOUCHED && !KERNEL_FAULT )); then
		if [[ -n ${SPX_CARD:-} ]]; then
			timeout 2 amixer -q -c "$SPX_CARD" cset \
				name='SpkrLeft PA Volume' 0 >/dev/null 2>&1 || true
		fi
		if set_amp_gpio 0x00; then
			echo "SPX: amplifier parking was verified after the controlled test"
		else
			echo "SPX WARNING: amplifier parking could not be verified" >&2
		fi
	fi
	if (( KERNEL_FAULT )); then
		echo "SPX: kernel fault detected; leaving user audio services stopped"
	elif (( HARDWARE_TOUCHED )); then
		echo "SPX: leaving user audio services stopped pending listening confirmation"
	elif (( ${#PW_RESTORE_UNITS[@]} )); then
		systemctl --user start "${PW_RESTORE_UNITS[@]}" \
			>/dev/null 2>&1 || true
	fi
	sync
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

require_param()
{
	local path=$1 expected=$2 actual

	[[ -r $path ]] || fatal "missing module parameter $path"
	actual=$(<"$path")
	[[ $actual == "$expected" ]] ||
		fatal "$(basename "$path") is '$actual', expected '$expected'"
}

kmsg_marker()
{
	SPX_KMSG_MARKER="SPX_SCRIPT_${1}_${BASHPID}_${RANDOM}_$(date +%s%N)"
	printf '<6>%s\n' "$SPX_KMSG_MARKER" | sudo tee /dev/kmsg >/dev/null
}

logs_since_marker()
{
	sudo dmesg | sed -n "/$1/,\$p"
}

fresh_regs()
{
	local tag=$1 marker block line

	kmsg_marker regs
	marker=$SPX_KMSG_MARKER
	echo 1 | sudo tee \
		/sys/module/soundwire_qcom/parameters/spx_snapshot >/dev/null ||
		fatal "controller-serialized register snapshot failed"
	block=$(logs_since_marker "$marker")
	line=$(grep 'SPX SNAPSHOT:' <<<"$block" | tail -1)
	[[ -n $line ]] || fatal "fresh controller snapshot was not logged"
	SPX_COMP_PARAMS=$(sed -n 's/.*COMP_PARAMS=\(0x[0-9a-fA-F]\+\).*/\1/p' <<<"$line")
	SPX_SLV_STATUS=$(sed -n 's/.*MCP_SLV_STATUS=\(0x[0-9a-fA-F]\+\).*/\1/p' <<<"$line")
	SPX_MCP_STATUS=$(sed -n 's/.*MCP_STATUS=\(0x[0-9a-fA-F]\+\).*/\1/p' <<<"$line")
	SPX_DP1_B0=$(sed -n 's/.*DP1_B0=\(0x[0-9a-fA-F]\+\).*/\1/p' <<<"$line")
	SPX_DP1_B1=$(sed -n 's/.*DP1_B1=\(0x[0-9a-fA-F]\+\).*/\1/p' <<<"$line")
	[[ -n $SPX_COMP_PARAMS && -n $SPX_SLV_STATUS && -n $SPX_MCP_STATUS ]] ||
		fatal "could not parse the fresh register dump"
	printf '  %s: COMP_PARAMS=%s MCP_SLV_STATUS=%s\n' \
		"$tag" "$SPX_COMP_PARAMS" "$SPX_SLV_STATUS"
	[[ $SPX_COMP_PARAMS == 0x016840c6 ]] ||
		fatal "AHB bridge canary is invalid ($SPX_COMP_PARAMS)"
	if [[ $tag == pre-stream ]]; then
		[[ $SPX_SLV_STATUS == 0x00000001 ]] ||
			fatal "single amp is not stably attached at physical device 0 ($SPX_SLV_STATUS)"
	else
		# In no-assign mode the amp cannot acquire any address except device 0,
		# but this master's status latch commonly clears on the first frame-bank
		# switch.  A zero after a proven pre-stream 0x1 is therefore ambiguous:
		# it can mean absent or merely stale.  Keep the bounded listening test
		# running and decide from the active-bank transport plus acoustic result;
		# still reject any indication that the slave moved to another address.
		case $SPX_SLV_STATUS in
		0x00000000)
			echo "  WARNING: slave-status latch cleared after the proven device-0 attach"
			;;
		0x00000001)
			;;
		*)
			fatal "single amp left physical device 0 ($SPX_SLV_STATUS)"
			;;
		esac
	fi
	if [[ $tag == active-stream ]]; then
		printf '  MCP_STATUS=%s DP1 banks: B0=%s B1=%s\n' \
			"$SPX_MCP_STATUS" "$SPX_DP1_B0" "$SPX_DP1_B1"
		if (( SPX_MCP_STATUS & 1 )); then
			[[ $SPX_DP1_B1 == 0x01000107 ]] ||
				fatal "active bank 1 does not contain the enabled DAC transport"
		else
			[[ $SPX_DP1_B0 == 0x01000107 ]] ||
				fatal "active bank 0 does not contain the enabled DAC transport"
		fi
	fi
}

set_amp_gpio()
{
	local value=$1 marker block

	kmsg_marker gpio
	marker=$SPX_KMSG_MARKER
	# This one-shot helper intentionally returns EAGAIN so it never remains
	# loaded. Validate its fresh log instead of treating insmod's status as the
	# hardware result.
	sudo insmod drivers/spx_extras/spx_wcd_gpio.ko dir=0x06 val="$value" || true
	block=$(logs_since_marker "$marker")
	grep -q "SPX GPIO managed: dir=0x06 val=$value" <<<"$block"
}

echo "=== [0] guarded boot invariants ==="
grep -qw 'wcd934x.spx_wsa_gpio_val=0x00' /proc/cmdline ||
	fatal "not booted with both amplifiers parked off"
grep -qw 'wcd934x.spx_wsa_gpio_dir=0x06' /proc/cmdline ||
	fatal "not booted with the managed WSA GPIO direction mask"
grep -qw 'wcd934x.spx_wsa_en_pin=-1' /proc/cmdline ||
	fatal "legacy single-pin WSA override is not disabled"
for REQUIRED_BOOT_ARG in panic=10 softlockup_panic=1 hung_task_panic=1 \
		oops=panic ramoops.console_size=0x20000; do
	grep -qw "$REQUIRED_BOOT_ARG" /proc/cmdline ||
		fatal "missing hard-lock recovery argument $REQUIRED_BOOT_ARG"
done
[[ -c /dev/watchdog0 ]] || fatal "Qualcomm hardware watchdog is unavailable"
command -v setsid >/dev/null || fatal "setsid is required for safe tone cleanup"
[[ $(systemctl show --property=RuntimeWatchdogUSec --value) == 30s ]] ||
	fatal "PID 1 is not configured for the 30-second hardware watchdog"
sudo fuser /dev/watchdog0 2>/dev/null | grep -qw 1 ||
	fatal "PID 1 does not own /dev/watchdog0"

require_param /sys/module/soundwire_qcom/parameters/spx_exact_windows_init N
require_param /sys/module/soundwire_qcom/parameters/spx_core_enum 1
require_param /sys/module/soundwire_qcom/parameters/spx_no_assign 1
require_param /sys/module/soundwire_qcom/parameters/spx_blind_attach 0
require_param /sys/module/soundwire_qcom/parameters/spx_write_dev0 1
require_param /sys/module/soundwire_qcom/parameters/spx_mirror_banks 0
require_param /sys/module/soundwire_qcom/parameters/spx_write_twice 0
require_param /sys/module/soundwire_qcom/parameters/spx_bank_switch_repeats 1
require_param /sys/module/soundwire_qcom/parameters/spx_watchdog 0
require_param /sys/module/soundwire_qcom/parameters/spx_quiet_bus 0
require_param /sys/module/soundwire_qcom/parameters/spx_win_transport 1
require_param /sys/module/soundwire_qcom/parameters/spx_runtime_ssp_period 1
require_param /sys/module/soundwire_qcom/parameters/spx_verify_bank 0
require_param /sys/module/soundwire_qcom/parameters/spx_dr_freq 0
require_param /sys/module/soundwire_qcom/parameters/spx_port_si -1
require_param /sys/module/soundwire_qcom/parameters/spx_port_off1 -1
require_param /sys/module/soundwire_qcom/parameters/spx_port_off2 -1
require_param /sys/module/soundwire_qcom/parameters/spx_port_bp -1
require_param /sys/module/soundwire_qcom/parameters/spx_frame_phase 1
require_param /sys/module/soundwire_qcom/parameters/spx_actual_phase 0
require_param /sys/module/soundwire_qcom/parameters/spx_clk_div 0
require_param /sys/module/snd_soc_wsa881x/parameters/spx_write_only Y
require_param /sys/module/snd_soc_wsa881x/parameters/spx_blind_rmw N
require_param /sys/module/snd_soc_wsa881x/parameters/spx_stream_port_mask 1
require_param /sys/module/snd_soc_wsa881x/parameters/spx_replay_supplies Y
require_param /sys/module/snd_soc_wsa881x/parameters/spx_init_on_pmu 0
require_param /sys/module/snd_soc_wsa881x/parameters/spx_win_pa_seq 1
require_param /sys/module/snd_soc_wsa881x/parameters/spx_sample_edge -1
require_param /sys/module/snd_soc_wsa881x/parameters/spx_powerdown_gpio 1
require_param /sys/module/snd_soc_wsa881x/parameters/spx_port_map 0,0,0,0
grep -qw 'snd_soc_wsa881x.spx_port_map=0,0,0,0' /proc/cmdline ||
	fatal "the boot entry did not pin the all-zero WSA port-map override"
require_param /sys/module/wcd934x/parameters/spx_wsa_en_pin -1
require_param /sys/module/wcd934x/parameters/spx_wsa_gpio_dir 6
require_param /sys/module/wcd934x/parameters/spx_wsa_gpio_val 0
grep -qw 'snd_soc_wcd934x.spx_persist_stream=1' /proc/cmdline ||
	fatal "the boot entry did not arm persistent WCD SLIMbus teardown protection"
grep -qw 'q6afe_dai.spx_no_port_stop=0' /proc/cmdline ||
	fatal "the boot entry did not pin the scoped AFE teardown policy"
if [[ -e /sys/module/snd_soc_wcd934x/parameters/spx_persist_stream ]]; then
	require_param /sys/module/snd_soc_wcd934x/parameters/spx_persist_stream Y
fi
if [[ -e /sys/module/q6afe_dai/parameters/spx_no_port_stop ]]; then
	require_param /sys/module/q6afe_dai/parameters/spx_no_port_stop N
fi

DT=/sys/firmware/devicetree/base
DAI_PROP="$DT/sound/slim-playback-dai-link/codec/sound-dai"
[[ $(stat -c %s "$DAI_PROP") == 20 ]] ||
	fatal "live playback DAI link is not the proven WCD + one WSA + SWM topology"
mapfile -t WCD_PHANDLE < <(find "$DT" -path '*/slim@1/codec@1,0/phandle')
mapfile -t LEFT_PHANDLE < <(find "$DT" -path '*/soundwire@c85/speaker@0,1/phandle')
mapfile -t SWM_PHANDLE < <(find "$DT" -path '*/soundwire@c85/phandle')
(( ${#WCD_PHANDLE[@]} == 1 && ${#LEFT_PHANDLE[@]} == 1 &&
   ${#SWM_PHANDLE[@]} == 1 )) || fatal "could not resolve exact live DAI phandles"
hex_file()
{
	od -An -v -tx1 "$1" | tr -d ' \n'
}
EXPECTED_DAI=$(hex_file "${WCD_PHANDLE[0]}")
EXPECTED_DAI+="00000000$(hex_file "${LEFT_PHANDLE[0]}")"
EXPECTED_DAI+="$(hex_file "${SWM_PHANDLE[0]}")00000000"
[[ $(hex_file "$DAI_PROP") == "$EXPECTED_DAI" ]] ||
	fatal "live DAI cells do not reference exactly WCD + left WSA + SWM"
mapfile -t LEFT_PORT_MAP < <(find "$DT" \
	-path '*/soundwire@c85/speaker@0,1/qcom,port-mapping')
(( ${#LEFT_PORT_MAP[@]} == 1 )) ||
	fatal "could not resolve the live left-WSA port mapping"
[[ $(hex_file "${LEFT_PORT_MAP[0]}") == 00000001000000020000000300000007 ]] ||
	fatal "live left-WSA port mapping is not the proven 1,2,3,7 topology"
RIGHT_STATUS=$(find "$DT" -path '*/soundwire@c85/speaker@0,2/status' -print -quit)
[[ -n $RIGHT_STATUS && $(tr -d '\0' <"$RIGHT_STATUS") == disabled ]] ||
	fatal "right WSA codec is not disabled in the live DT"
ROUTING=$(tr '\0' '\n' <"$DT/sound/audio-routing")
grep -qx 'Left Spk' <<<"$ROUTING" || fatal "left speaker route is absent"
if grep -qE 'Right Spk|SpkrRight' <<<"$ROUTING"; then
	fatal "right speaker route is still present"
fi
BOOT_LOG=$(sudo dmesg)
if grep -qE 'SPX: hw_params active_ports=|SPX: PA DAPM event' <<<"$BOOT_LOG"; then
	fatal "speaker transport was already opened this boot; use a fresh guarded boot"
fi

for PW_UNIT in wireplumber.service pipewire.service pipewire-pulse.service \
		pipewire.socket pipewire-pulse.socket; do
	if systemctl --user is-active -q "$PW_UNIT" 2>/dev/null; then
		PW_RESTORE_UNITS+=("$PW_UNIT")
	fi
done
if (( ${#PW_RESTORE_UNITS[@]} )); then
	echo "SPX: stopping this user's PipeWire session for the controlled test"
	systemctl --user stop "${PW_RESTORE_UNITS[@]}"
fi
for PW_UNIT in wireplumber.service pipewire.service pipewire-pulse.service \
		pipewire.socket pipewire-pulse.socket; do
	systemctl --user is-active -q "$PW_UNIT" 2>/dev/null &&
		fatal "$PW_UNIT is still active"
done
BOOT_LOG=$(sudo dmesg)
if grep -qE 'SPX: hw_params active_ports=|SPX: PA DAPM event' <<<"$BOOT_LOG"; then
	fatal "speaker transport opened during PipeWire shutdown; use a fresh guarded boot"
fi

sudo dmesg -w >"$LOG_DIR/dmesg-follow.log" &
DMESG_PID=$!
( while sleep 1; do sync; done ) &
SYNC_PID=$!

echo "=== [1] codec / SLIMbus card bring-up ==="
if ! grep -qE 'sdm845|Surface Pro X' /proc/asound/cards 2>/dev/null; then
	./scripts/spx-run2-pio-full.sh > /tmp/spx-speaker-bringup.log 2>&1 ||
		fatal "SLIMbus bring-up failed (see /tmp/spx-speaker-bringup.log)"
	sleep 2
fi
mapfile -t SPX_CARDS < <(awk '/sdm845|Surface Pro X/{print $1}' /proc/asound/cards)
(( ${#SPX_CARDS[@]} == 1 )) || fatal "expected exactly one Surface Pro X ALSA card"
SPX_CARD=${SPX_CARDS[0]}
[[ $SPX_CARD =~ ^[0-9]+$ ]] || fatal "no Surface Pro X ALSA card"
echo "  ALSA card $SPX_CARD"
require_param /sys/module/snd_soc_wcd934x/parameters/spx_persist_stream Y
require_param /sys/module/q6afe_dai/parameters/spx_no_port_stop N
for PARAM_MODULE in soundwire_qcom snd_soc_wsa881x snd_soc_wcd934x q6afe_dai; do
	mkdir -p "$LOG_DIR/$PARAM_MODULE-parameters"
	for PARAM_FILE in /sys/module/"$PARAM_MODULE"/parameters/*; do
		[[ -r $PARAM_FILE ]] || continue
		cp "$PARAM_FILE" "$LOG_DIR/$PARAM_MODULE-parameters/"
	done
done
for STATUS_FILE in /proc/asound/card"$SPX_CARD"/pcm*/sub*/status; do
	[[ -e $STATUS_FILE ]] || continue
	grep -qx closed "$STATUS_FILE" ||
		fatal "an ALSA stream is still open ($STATUS_FILE); refusing controller reset"
done
PCM_NODE=/dev/snd/pcmC${SPX_CARD}D0p
if command -v fuser >/dev/null && fuser -s "$PCM_NODE"; then
	fatal "$PCM_NODE is still held by another process"
fi

echo "=== [2] power and attach exactly one amplifier ==="
set_amp_gpio 0x00 || fatal "failed to park both WSA GPIOs off"
sleep 10
HARDWARE_TOUCHED=1
set_amp_gpio 0x02 || fatal "failed to power the single guarded WSA GPIO"
sleep 1
kmsg_marker enum
ENUM_MARKER=$SPX_KMSG_MARKER
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_force_attach >/dev/null
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_reenum >/dev/null
sleep 25

ENUM_LOG=$(logs_since_marker "$ENUM_MARKER")
grep -q 'soundwire_qcom: spx_reenum: schedule work (force=1' <<<"$ENUM_LOG" ||
	fatal "fresh re-enumeration request was not observed"
grep -q 'SPX FORCE-ATTACH: stable attachment' <<<"$ENUM_LOG" ||
	fatal "force-attach did not reach its stable state"
grep -q 'SPX: initializing amplifier at SoundWire device 1' <<<"$ENUM_LOG" ||
	fatal "fresh attach did not replay the amplifier cold-init table"
fresh_regs pre-stream

echo "=== [3] safe cold-init replay while the stream is idle ==="
echo 1 | sudo tee /sys/module/snd_soc_wsa881x/parameters/spx_rearm_init >/dev/null
sleep 1

echo "=== [4] required single-speaker mixer path ==="
set_ctl()
{
	amixer -c "$SPX_CARD" cset name="$1" "$2" \
		>>"$LOG_DIR/mixer.log" 2>&1 ||
		fatal "failed to set ALSA control '$1'"
	amixer -c "$SPX_CARD" cget name="$1" \
		>>"$LOG_DIR/mixer.log" 2>&1 ||
		fatal "failed to read back ALSA control '$1'"
}
set_ctl 'SLIMBUS_2_RX Audio Mixer MultiMedia1' 1
set_ctl 'SLIM RX0 MUX' AIF1_PB
set_ctl 'SLIM RX1 MUX' AIF1_PB
set_ctl 'RX INT7_1 MIX1 INP0' RX0
set_ctl 'COMP7 Switch' 1
set_ctl 'RX7 Digital Volume' 84
set_ctl 'RX8 Digital Volume' 84
set_ctl 'SpkrLeft COMP Switch' 0
set_ctl 'SpkrLeft VISENSE Switch' 0
set_ctl 'SpkrLeft BOOST Switch' 1
set_ctl 'SpkrLeft DAC Switch' 1
# Force a real control transition after the cold-init replay. Code 8 is 6 dB
# below the historically audible code 12 and is a safer first listening level.
set_ctl 'SpkrLeft PA Volume' 0
set_ctl 'SpkrLeft PA Volume' 8
set_ctl 'SpkrLeft Smart Boost Level' 0

echo "=== [5] short 48 kHz S16_LE stereo tone ==="
TONE_LOG=/tmp/spx-speaker-test.log
kmsg_marker tone
TONE_MARKER=$SPX_KMSG_MARKER
set +e
setsid timeout -k 2 5 speaker-test -D "plughw:${SPX_CARD},0" -c 2 -r 48000 \
	-F S16_LE -t sine -f 440 >"$TONE_LOG" 2>&1 &
TONE_PID=$!
set -e
sleep 1
fresh_regs active-stream
set +e
wait "$TONE_PID"
TONE_RC=$?
TONE_PID=
set -e
if (( TONE_RC != 0 && TONE_RC != 124 && TONE_RC != 137 )); then
	sed -n '1,120p' "$TONE_LOG" >&2
	fatal "speaker-test failed with exit code $TONE_RC"
fi
# With the deliberately persistent WCD/AFE teardown policy, speaker-test can
# remain in PCM close after timeout sends SIGTERM and then be reaped by the
# two-second SIGKILL deadline (137).  ALSA DAPM also applies its normal delayed
# power-down several seconds after the process is gone.  Both are bounded here;
# do not misreport that expected protected teardown as a playback failure.
for ((i = 0; i < 80; i++)); do
	TONE_KERNEL_LOG=$(logs_since_marker "$TONE_MARKER")
	grep -q 'SPX: PA DAPM event 0x8' <<<"$TONE_KERNEL_LOG" && break
	sleep 0.1
done
grep -q '0 - Front Left' "$TONE_LOG" ||
	fatal "speaker-test never reported submitting the left channel"
TONE_KERNEL_LOG=$(logs_since_marker "$TONE_MARKER")
if grep -qiE "$KERNEL_FAULT_RE" <<<"$TONE_KERNEL_LOG"; then
	KERNEL_FAULT=1
	fatal "kernel fault signature appeared during the controlled test"
fi
grep -q 'SPX: hw_params active_ports=1' <<<"$TONE_KERNEL_LOG" ||
	fatal "WSA DAC-only stream setup was not observed"
grep -q 'SPX: PA DAPM event 0x1' <<<"$TONE_KERNEL_LOG" ||
	fatal "speaker PA PRE_PMU event was not observed"
grep -q 'SPX: PA DAPM event 0x8' <<<"$TONE_KERNEL_LOG" ||
	fatal "speaker PA POST_PMD teardown event was not observed"

sleep 2
fresh_regs post-stream
POST_LOG=$(logs_since_marker "$ENUM_MARKER")
if grep -qiE "$KERNEL_FAULT_RE" <<<"$POST_LOG"; then
	KERNEL_FAULT=1
	fatal "kernel fault signature appeared during the controlled test"
fi
TEST_SUCCEEDED=1
cp "$TONE_LOG" "$LOG_DIR/speaker-test.log"
sync

echo
echo "ALSA submitted the guarded 5-second tone; the amp remained at device 0."
echo "Did you hear a 440 Hz tone from the physical right speaker?"
echo "The amplifier will be parked off and PipeWire left stopped on exit."
