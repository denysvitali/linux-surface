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
PHYSICAL_DEV0_SEEN=0
# Amplifier power state. V15/V16 proved that WCD GPIO pin2 is the audible amp;
# boot with both amps parked off, then raise pin2 only. Set SPX_EXPECT_GPIO_VAL
# and SPX_AMP_GPIO_ON to 0x06 only to reproduce the old two-amp state.
SPX_EXPECT_GPIO_VAL=${SPX_EXPECT_GPIO_VAL:-0x00}
SPX_AMP_GPIO_ON=${SPX_AMP_GPIO_ON:-0x04}
SPX_EXPECT_GPIO_VAL_DEC=$((SPX_EXPECT_GPIO_VAL))
# Addressing model under test. The audible 07-25/28 era let the amp enumerate
# naturally (device 1, MCP_SLV_STATUS=0x4) with spx_no_assign=0 spx_write_dev0=0;
# every silent v3-v9 boot pinned it unenumerated at device 0. The defaults
# reproduce the pinned guarded runs. Set SPX_EXPECT_NO_ASSIGN=0,
# SPX_EXPECT_WRITE_DEV0=0 and SPX_EXPECT_DEV_STATUS=0x00000004 to test the
# era's enumerated addressing.
SPX_EXPECT_NO_ASSIGN=${SPX_EXPECT_NO_ASSIGN:-1}
SPX_EXPECT_WRITE_DEV0=${SPX_EXPECT_WRITE_DEV0:-1}
SPX_EXPECT_DEV_STATUS=${SPX_EXPECT_DEV_STATUS:-0x00000001}
SPX_EXPECT_FORCE_TIMER_PACING=${SPX_EXPECT_FORCE_TIMER_PACING:-1}
# Persistent-WCD-SLIMbus-teardown policy armed on the command line. Default 1
# (the audited v28 baseline); a persist_stream=0 A/B boot sets SPX_EXPECT_
# PERSIST_STREAM=0 in the test env so both cmdline and sysfs checks follow it.
SPX_EXPECT_PERSIST_STREAM=${SPX_EXPECT_PERSIST_STREAM:-1}
case $SPX_EXPECT_PERSIST_STREAM in
0) SPX_EXPECT_PERSIST_STREAM_YN=N ;;
1) SPX_EXPECT_PERSIST_STREAM_YN=Y ;;
*) fatal "SPX_EXPECT_PERSIST_STREAM must be 0 or 1, got '$SPX_EXPECT_PERSIST_STREAM'" ;;
esac
SPX_EXPECT_WIN_PA_PROFILE=${SPX_EXPECT_WIN_PA_PROFILE:-0}
SPX_EXPECT_WIN_BIAS_PSRR=${SPX_EXPECT_WIN_BIAS_PSRR:--1}
SPX_EXPECT_WIN_TEMP_OP=${SPX_EXPECT_WIN_TEMP_OP:--1}
SPX_READBACK_ONLY=${SPX_READBACK_ONLY:-0}
# The guarded baseline transports only the WSA DAC descriptor (slave port 1).
# Windows and mainline db845c both open all four (mask 15). Naming the mask up
# front keeps the guard able to reject a boot that disagrees with what was armed.
SPX_EXPECT_PORT_MASK=${SPX_EXPECT_PORT_MASK:-1}
[[ $SPX_EXPECT_PORT_MASK =~ ^[0-9]+$ ]] &&
	(( SPX_EXPECT_PORT_MASK >= 1 && SPX_EXPECT_PORT_MASK <= 15 )) ||
	fatal "guarded WSA port mask must be 1..15, got '$SPX_EXPECT_PORT_MASK'"
# The DAC descriptor (bit 0) carries the audio; a mask without it is never a
# speaker configuration.
(( SPX_EXPECT_PORT_MASK & 1 )) ||
	fatal "guarded WSA port mask must include the DAC descriptor (bit 0)"
SPX_EXPECT_ACTIVE_PORTS=0
for ((SPX_PM_BIT = 0; SPX_PM_BIT < 4; SPX_PM_BIT++)); do
	if (( SPX_EXPECT_PORT_MASK & (1 << SPX_PM_BIT) )); then
		SPX_EXPECT_ACTIVE_PORTS=$((SPX_EXPECT_ACTIVE_PORTS + 1))
	fi
done
SPX_TONE_FORMAT=${SPX_TONE_FORMAT:-S16_LE}
SPX_EXPECT_SPK_PATH=${SPX_EXPECT_SPK_PATH:-left}
SPX_ALLOW_CROSS_GPIO=${SPX_ALLOW_CROSS_GPIO:-0}
case $SPX_EXPECT_FORCE_TIMER_PACING in
0) SPX_EXPECT_FORCE_TIMER_PACING=N ;;
1) SPX_EXPECT_FORCE_TIMER_PACING=Y ;;
esac
case $SPX_TONE_FORMAT in
S16_LE|S24_LE) ;;
*) fatal "unsupported guarded tone format '$SPX_TONE_FORMAT'" ;;
esac
case $SPX_EXPECT_SPK_PATH in
left)
	SPX_NATIVE_GPIO_PIN=1
	SPX_SPK_UNIT=1
	SPX_OTHER_SPK_UNIT=2
	SPX_SPK_PREFIX=SpkrLeft
	SPX_MACHINE_WIDGET='Left Spk'
	SPX_FORBIDDEN_ROUTE_RE='Right Spk|SpkrRight'
	SPX_PORT_MAP_HEX=00000001000000020000000300000007
	SPX_MASTER_PORT=1
	SPX_MASTER_CTRL=0x01000107
	SPX_TONE_PAN='pan=stereo|c0=c0|c1=0*c0'
	SPX_WCD_INTERP='RX INT7_1 MIX1 INP0'
	SPX_WCD_SOURCE=RX0
	SPX_WCD_COMP='COMP7 Switch'
	SPX_WCD_VOLUME='RX7 Digital Volume'
	SPX_ROUTE_PAIR_1='Left Spk|SpkrLeft SPKR|'
	SPX_ROUTE_PAIR_2='SpkrLeft IN|SPK1 OUT|'
	;;
right)
	SPX_NATIVE_GPIO_PIN=2
	SPX_SPK_UNIT=2
	SPX_OTHER_SPK_UNIT=1
	SPX_SPK_PREFIX=SpkrRight
	SPX_MACHINE_WIDGET='Right Spk'
	SPX_FORBIDDEN_ROUTE_RE='Left Spk|SpkrLeft'
	SPX_PORT_MAP_HEX=00000004000000050000000600000008
	SPX_MASTER_PORT=4
	SPX_MASTER_CTRL=0x01000607
	SPX_TONE_PAN='pan=stereo|c0=0*c0|c1=c0'
	SPX_WCD_INTERP='RX INT8_1 MIX1 INP0'
	SPX_WCD_SOURCE=RX1
	SPX_WCD_COMP='COMP8 Switch'
	SPX_WCD_VOLUME='RX8 Digital Volume'
	SPX_ROUTE_PAIR_1='Right Spk|SpkrRight SPKR|'
	SPX_ROUTE_PAIR_2='SpkrRight IN|SPK2 OUT|'
	;;
*) fatal "unsupported guarded speaker path '$SPX_EXPECT_SPK_PATH'" ;;
esac
SPX_EXPECT_GPIO_PIN=${SPX_EXPECT_GPIO_PIN:-$SPX_NATIVE_GPIO_PIN}
case $SPX_EXPECT_GPIO_PIN in
1)
	SPX_PATH_GPIO_MASK=0x02
	SPX_GPIO_PIN_HEX=00000001
	;;
2)
	SPX_PATH_GPIO_MASK=0x04
	SPX_GPIO_PIN_HEX=00000002
	;;
*) fatal "unsupported guarded WSA GPIO pin '$SPX_EXPECT_GPIO_PIN'" ;;
esac
if [[ $SPX_EXPECT_GPIO_PIN != "$SPX_NATIVE_GPIO_PIN" ]]; then
	[[ $SPX_ALLOW_CROSS_GPIO == 1 && $SPX_EXPECT_SPK_PATH == right &&
	   $SPX_EXPECT_GPIO_PIN == 1 ]] ||
		fatal "non-native path/GPIO pairing requires the audited right-on-pin1 cross mode"
fi
[[ $SPX_AMP_GPIO_ON == "$SPX_PATH_GPIO_MASK" ]] ||
	fatal "GPIO pin $SPX_EXPECT_GPIO_PIN requires isolated mask $SPX_PATH_GPIO_MASK, got $SPX_AMP_GPIO_ON"
case $SPX_TONE_FORMAT in
S16_LE) SPX_EXPECT_BITS=16 ;;
S24_LE) SPX_EXPECT_BITS=24 ;;
esac
KERNEL_FAULT_RE='soft lockup|hard LOCKUP|rcu.*stall|kernel panic|Oops:'
KERNEL_FAULT_RE+='|Internal error:|SError|hung task|synchronous external abort'
KERNEL_FAULT_RE+='|watchdog: BUG'
stop_tone()
{
	local i

	[[ -n ${TONE_PID:-} ]] || return 0
	# The guarded player and timeout run in a private session. Stop and reap that
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
				name="$SPX_SPK_PREFIX PA Volume" 0 >/dev/null 2>&1 || true
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
	SPX_DP4_B0=$(sed -n 's/.*DP4_B0=\(0x[0-9a-fA-F]\+\).*/\1/p' <<<"$line")
	SPX_DP4_B1=$(sed -n 's/.*DP4_B1=\(0x[0-9a-fA-F]\+\).*/\1/p' <<<"$line")
	[[ -n $SPX_COMP_PARAMS && -n $SPX_SLV_STATUS && -n $SPX_MCP_STATUS &&
	   -n $SPX_DP1_B0 && -n $SPX_DP1_B1 &&
	   -n $SPX_DP4_B0 && -n $SPX_DP4_B1 ]] ||
		fatal "could not parse the fresh register dump"
	printf '  %s: COMP_PARAMS=%s MCP_SLV_STATUS=%s\n' \
		"$tag" "$SPX_COMP_PARAMS" "$SPX_SLV_STATUS"
	[[ $SPX_COMP_PARAMS == 0x016840c6 ]] ||
		fatal "AHB bridge canary is invalid ($SPX_COMP_PARAMS)"
	# In no-assign mode the amp cannot acquire any address except device 0,
	# but this master's status latch flickers between 0x1 and 0x0 even while
	# the powered amp remains present.  Require a real 0x1 in the immediate
	# GPIO-high window, remember that physical proof, and reject every other
	# nonzero address.  Later zero samples are ambiguous/stale, not proof that
	# the already-observed device vanished.
	case $SPX_SLV_STATUS in
	0x00000001)
		PHYSICAL_DEV0_SEEN=1
		;;
	"$SPX_EXPECT_DEV_STATUS")
		# Only reachable when the expected status is not 0x1: the
		# enumerated-addressing experiment, where the amp legitimately
		# answers at its assigned address after force-attach.
		PHYSICAL_DEV0_SEEN=1
		echo "  NOTE: amp answering at the expected enumerated address $SPX_SLV_STATUS"
		;;
	0x00000000)
		if [[ $tag != attach-window ]]; then
			(( PHYSICAL_DEV0_SEEN )) ||
				fatal "device 0 was never physically observed before $tag"
			echo "  WARNING: slave-status latch cleared after the proven device-0 attach"
		fi
		;;
	*)
		# With both amplifiers powered, two slaves answer at once and the
		# latch legitimately reports something other than 0x1 (0x4, 0x40,
		# a garbled DevID). That is the configuration under test, not a
		# fault, so accept any nonzero address as proof that an amp
		# announced. The single-amp default still rejects it.
		if [[ $SPX_AMP_GPIO_ON == 0x06 ]]; then
			PHYSICAL_DEV0_SEEN=1
			echo "  NOTE: multi-amp mode, slave status $SPX_SLV_STATUS accepted as presence"
		else
			fatal "single amp left physical device 0 ($SPX_SLV_STATUS)"
		fi
		;;
	esac
	if [[ $tag == active-stream ]]; then
		if [[ $SPX_MASTER_PORT == 1 ]]; then
			SPX_MASTER_B0=$SPX_DP1_B0
			SPX_MASTER_B1=$SPX_DP1_B1
		else
			SPX_MASTER_B0=$SPX_DP4_B0
			SPX_MASTER_B1=$SPX_DP4_B1
		fi
		printf '  MCP_STATUS=%s DP%s banks: B0=%s B1=%s\n' \
			"$SPX_MCP_STATUS" "$SPX_MASTER_PORT" \
			"$SPX_MASTER_B0" "$SPX_MASTER_B1"
		[[ $SPX_MASTER_B0 == "$SPX_MASTER_CTRL" ]] ||
			fatal "master bank 0 does not contain the enabled DAC transport"
		[[ $SPX_MASTER_B1 == "$SPX_MASTER_CTRL" ]] ||
			fatal "master bank 1 does not contain the shadowed DAC transport"
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
# The boot-time GPIO value is the variable under test: the audible 07-26/07-28
# runs booted 0x06 (both amps powered), every silent boot since booted 0x00.
# Declare which one this run expects so the gate still verifies the boot.
grep -qw "wcd934x.spx_wsa_gpio_val=$SPX_EXPECT_GPIO_VAL" /proc/cmdline ||
	fatal "not booted with spx_wsa_gpio_val=$SPX_EXPECT_GPIO_VAL"
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
require_param /sys/module/soundwire_qcom/parameters/spx_no_assign \
	"$SPX_EXPECT_NO_ASSIGN"
require_param /sys/module/soundwire_qcom/parameters/spx_blind_attach 0
require_param /sys/module/soundwire_qcom/parameters/spx_write_dev0 \
	"$SPX_EXPECT_WRITE_DEV0"
require_param /sys/module/soundwire_qcom/parameters/spx_mirror_banks 0
require_param /sys/module/soundwire_qcom/parameters/spx_shadow_dp1_enable 1
require_param /sys/module/soundwire_qcom/parameters/spx_write_twice 0
require_param /sys/module/soundwire_qcom/parameters/spx_bank_switch_repeats 1
require_param /sys/module/soundwire_qcom/parameters/spx_watchdog 0
require_param /sys/module/soundwire_qcom/parameters/spx_quiet_bus 0
# The two reverse-engineered knobs are the only invariants a baseline probe is
# allowed to relax, and only by naming the value it expects up front, so the
# guard still catches a boot that disagrees with the entry that was armed.
require_param /sys/module/soundwire_qcom/parameters/spx_win_transport \
	"${SPX_EXPECT_WIN_TRANSPORT:-1}"
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
require_param /sys/module/snd_soc_wsa881x/parameters/spx_stream_port_mask \
	"$SPX_EXPECT_PORT_MASK"
if [[ $SPX_EXPECT_PORT_MASK != 1 ]]; then
	grep -qw "snd_soc_wsa881x.spx_stream_port_mask=$SPX_EXPECT_PORT_MASK" \
		/proc/cmdline ||
		fatal "the boot entry did not select the guarded WSA port mask"
fi
require_param /sys/module/snd_soc_wsa881x/parameters/spx_replay_supplies Y
require_param /sys/module/snd_soc_wsa881x/parameters/spx_init_on_pmu 0
require_param /sys/module/snd_soc_wsa881x/parameters/spx_win_pa_seq \
	"${SPX_EXPECT_WIN_PA_SEQ:-1}"
require_param /sys/module/snd_soc_wsa881x/parameters/spx_win_pa_profile \
	"$SPX_EXPECT_WIN_PA_PROFILE"
require_param /sys/module/snd_soc_wsa881x/parameters/spx_win_bias_psrr \
	"$SPX_EXPECT_WIN_BIAS_PSRR"
[[ $SPX_EXPECT_WIN_BIAS_PSRR == -1 || $SPX_EXPECT_WIN_BIAS_PSRR == 69 ]] ||
	fatal "guarded BIAS_PSRR expectation must be -1 or decimal 69 (0x45)"
require_param /sys/module/snd_soc_wsa881x/parameters/spx_win_temp_op \
	"$SPX_EXPECT_WIN_TEMP_OP"
[[ $SPX_EXPECT_WIN_TEMP_OP == -1 || $SPX_EXPECT_WIN_TEMP_OP == 12 ]] ||
	fatal "guarded TEMP_OP expectation must be -1 or decimal 12 (0x0c)"
if [[ $SPX_EXPECT_WIN_PA_PROFILE != 0 ]]; then
	grep -qw "snd_soc_wsa881x.spx_win_pa_profile=$SPX_EXPECT_WIN_PA_PROFILE" \
		/proc/cmdline || fatal "the boot entry did not select the guarded PA profile"
fi
if [[ $SPX_EXPECT_WIN_BIAS_PSRR != -1 ]]; then
	grep -qw "snd_soc_wsa881x.spx_win_bias_psrr=0x45" /proc/cmdline ||
		fatal "the boot entry did not select the guarded BIAS_PSRR override"
fi
if [[ $SPX_EXPECT_WIN_TEMP_OP != -1 ]]; then
	grep -qw "snd_soc_wsa881x.spx_win_temp_op=0x0c" /proc/cmdline ||
		fatal "the boot entry did not select the guarded TEMP_OP override"
fi
require_param /sys/module/snd_soc_wsa881x/parameters/spx_sample_edge -1
require_param /sys/module/snd_soc_wsa881x/parameters/spx_powerdown_gpio 1
require_param /sys/module/snd_soc_wsa881x/parameters/spx_port_map 0,0,0,0
require_param /sys/module/q6asm_dai/parameters/spx_force_timer_pacing \
	"$SPX_EXPECT_FORCE_TIMER_PACING"
[[ -e /sys/module/soundwire_qcom/parameters/spx_slave_readback ]] ||
	fatal "the physical-device readback trigger is unavailable"
grep -qw 'snd_soc_wsa881x.spx_port_map=0,0,0,0' /proc/cmdline ||
	fatal "the boot entry did not pin the all-zero WSA port-map override"
require_param /sys/module/wcd934x/parameters/spx_wsa_en_pin -1
require_param /sys/module/wcd934x/parameters/spx_wsa_gpio_dir 6
require_param /sys/module/wcd934x/parameters/spx_wsa_gpio_val \
	"$SPX_EXPECT_GPIO_VAL_DEC"
grep -qw "snd_soc_wcd934x.spx_persist_stream=$SPX_EXPECT_PERSIST_STREAM" /proc/cmdline ||
	fatal "the boot entry did not arm persistent WCD SLIMbus teardown protection (expected =$SPX_EXPECT_PERSIST_STREAM)"
grep -qw 'q6afe_dai.spx_no_port_stop=0' /proc/cmdline ||
	fatal "the boot entry did not pin the scoped AFE teardown policy"
if [[ -e /sys/module/snd_soc_wcd934x/parameters/spx_persist_stream ]]; then
	require_param /sys/module/snd_soc_wcd934x/parameters/spx_persist_stream \
		"$SPX_EXPECT_PERSIST_STREAM_YN"
fi
if [[ -e /sys/module/q6afe_dai/parameters/spx_no_port_stop ]]; then
	require_param /sys/module/q6afe_dai/parameters/spx_no_port_stop N
fi

DT=/sys/firmware/devicetree/base
DAI_PROP="$DT/sound/slim-playback-dai-link/codec/sound-dai"
[[ $(stat -c %s "$DAI_PROP") == 20 ]] ||
	fatal "live playback DAI link is not the proven WCD + one WSA + SWM topology"
mapfile -t WCD_PHANDLE < <(find "$DT" -path '*/slim@1/codec@1,0/phandle')
mapfile -t SPK_PHANDLE < <(find "$DT" \
	-path "*/soundwire@c85/speaker@0,$SPX_SPK_UNIT/phandle")
mapfile -t SWM_PHANDLE < <(find "$DT" -path '*/soundwire@c85/phandle')
(( ${#WCD_PHANDLE[@]} == 1 && ${#SPK_PHANDLE[@]} == 1 &&
   ${#SWM_PHANDLE[@]} == 1 )) || fatal "could not resolve exact live DAI phandles"
hex_file()
{
	od -An -v -tx1 "$1" | tr -d ' \n'
}
EXPECTED_DAI=$(hex_file "${WCD_PHANDLE[0]}")
EXPECTED_DAI+="00000000$(hex_file "${SPK_PHANDLE[0]}")"
EXPECTED_DAI+="$(hex_file "${SWM_PHANDLE[0]}")00000000"
[[ $(hex_file "$DAI_PROP") == "$EXPECTED_DAI" ]] ||
	fatal "live DAI cells do not reference exactly WCD + $SPX_EXPECT_SPK_PATH WSA + SWM"
mapfile -t SPK_PORT_MAP < <(find "$DT" \
	-path "*/soundwire@c85/speaker@0,$SPX_SPK_UNIT/qcom,port-mapping")
(( ${#SPK_PORT_MAP[@]} == 1 )) ||
	fatal "could not resolve the live $SPX_EXPECT_SPK_PATH-WSA port mapping"
[[ $(hex_file "${SPK_PORT_MAP[0]}") == "$SPX_PORT_MAP_HEX" ]] ||
	fatal "live $SPX_EXPECT_SPK_PATH-WSA port mapping disagrees with Windows endpoint data"
mapfile -t SPK_POWERDOWN_GPIO < <(find "$DT" \
	-path "*/soundwire@c85/speaker@0,$SPX_SPK_UNIT/powerdown-gpios")
(( ${#SPK_POWERDOWN_GPIO[@]} == 1 )) ||
	fatal "could not resolve the selected WSA powerdown GPIO"
SPK_POWERDOWN_HEX=$(hex_file "${SPK_POWERDOWN_GPIO[0]}")
[[ ${SPK_POWERDOWN_HEX: -16} == "${SPX_GPIO_PIN_HEX}00000001" ]] ||
	fatal "selected WSA does not use the expected active-low GPIO pin"
SPK_STATUS=$(find "$DT" \
	-path "*/soundwire@c85/speaker@0,$SPX_SPK_UNIT/status" -print -quit)
[[ -z $SPK_STATUS || $(tr -d '\0' <"$SPK_STATUS") == okay ]] ||
	fatal "selected WSA codec is disabled in the live DT"
OTHER_STATUS=$(find "$DT" \
	-path "*/soundwire@c85/speaker@0,$SPX_OTHER_SPK_UNIT/status" -print -quit)
[[ -n $OTHER_STATUS && $(tr -d '\0' <"$OTHER_STATUS") == disabled ]] ||
	fatal "non-test WSA codec is not disabled in the live DT"
ROUTING=$(tr '\0' '\n' <"$DT/sound/audio-routing")
ROUTING_PAIRS=$(tr '\0' '|' <"$DT/sound/audio-routing")
grep -qx "$SPX_MACHINE_WIDGET" <<<"$ROUTING" ||
	fatal "$SPX_EXPECT_SPK_PATH speaker route is absent"
grep -Fq "$SPX_ROUTE_PAIR_1" <<<"$ROUTING_PAIRS" ||
	fatal "selected machine-to-WSA route pair is absent"
grep -Fq "$SPX_ROUTE_PAIR_2" <<<"$ROUTING_PAIRS" ||
	fatal "selected WCD-to-WSA route pair is absent"
if grep -qE "$SPX_FORBIDDEN_ROUTE_RE" <<<"$ROUTING"; then
	fatal "non-test speaker route is still present"
fi
BOOT_LOG=$(sudo dmesg)
grep -qE "wsa881x-codec sdw:.*:00:$SPX_SPK_UNIT: SPX: SD_N on wcd-gpio pin $SPX_EXPECT_GPIO_PIN" \
	<<<"$BOOT_LOG" || fatal "boot did not bind the selected WSA codec/GPIO pair"
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
require_param /sys/module/snd_soc_wcd934x/parameters/spx_persist_stream \
	"$SPX_EXPECT_PERSIST_STREAM_YN"
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
set_amp_gpio "$SPX_AMP_GPIO_ON" ||
	fatal "failed to power the guarded WSA GPIO(s) ($SPX_AMP_GPIO_ON)"
for ((ATTACH_SAMPLE = 0; ATTACH_SAMPLE < 40; ATTACH_SAMPLE++)); do
	fresh_regs attach-window
	(( PHYSICAL_DEV0_SEEN )) && break
	sleep 0.05
done
(( PHYSICAL_DEV0_SEEN )) ||
	fatal "single amp never announced at physical device 0 after GPIO-high"
echo "  physical device-0 presence observed after $((ATTACH_SAMPLE + 1)) sample(s)"
kmsg_marker enum
ENUM_MARKER=$SPX_KMSG_MARKER
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_force_attach >/dev/null
echo 1 | sudo tee /sys/module/soundwire_qcom/parameters/spx_reenum >/dev/null

# Re-enumeration itself initializes the newly attached logical device. Do not
# leave the write-only amplifier idle for an arbitrary 25 seconds afterward:
# unicast writes have no acknowledgement, and the physical-presence latch can
# disappear during that gap. Follow the actual completion messages instead.
for ((i = 0; i < 300; i++)); do
	ENUM_LOG=$(logs_since_marker "$ENUM_MARKER")
	if grep -q 'SPX FORCE-ATTACH: stable attachment' <<<"$ENUM_LOG" &&
	   grep -q 'SPX: initializing amplifier at SoundWire device 1' <<<"$ENUM_LOG" &&
	   { [[ $SPX_EXPECT_WIN_BIAS_PSRR == -1 ]] ||
	     grep -q 'SPX: Windows BIAS_PSRR override 0x45' <<<"$ENUM_LOG"; } &&
	   { [[ $SPX_EXPECT_WIN_TEMP_OP == -1 ]] ||
	     grep -q 'SPX: Windows TEMP_OP override 0x0c' <<<"$ENUM_LOG"; }
	then
		break
	fi
	sleep 0.1
done

ENUM_LOG=$(logs_since_marker "$ENUM_MARKER")
grep -q 'soundwire_qcom: spx_reenum: schedule work (force=1' <<<"$ENUM_LOG" ||
	fatal "fresh re-enumeration request was not observed"
grep -q 'SPX FORCE-ATTACH: stable attachment' <<<"$ENUM_LOG" ||
	fatal "force-attach did not reach its stable state"
grep -q 'SPX: initializing amplifier at SoundWire device 1' <<<"$ENUM_LOG" ||
	fatal "fresh attach did not replay the amplifier cold-init table"
if [[ $SPX_EXPECT_WIN_TEMP_OP != -1 ]]; then
	grep -q 'SPX: Windows TEMP_OP override 0x0c' <<<"$ENUM_LOG" ||
		fatal "controlled cold init did not issue the TEMP_OP override"
fi

echo "=== [3] use the presence-bound automatic cold init ==="
# Do not issue the old explicit replay here. In v24 it ran 25 seconds after
# presence, when MCP_SLV_STATUS had already vanished. The force-attach path has
# just initialized logical device 1 while the physical amplifier was present.

if [[ $SPX_READBACK_ONLY == 1 ]]; then
	echo "=== [4] bounded physical-device-0 register readback (no PCM/PA) ==="
	kmsg_marker slave-readback
	READBACK_MARKER=$SPX_KMSG_MARKER
	set +e
	echo 1 | sudo tee \
		/sys/module/soundwire_qcom/parameters/spx_slave_readback >/dev/null
	READBACK_RC=$?
	set -e
	READBACK_LOG=$(logs_since_marker "$READBACK_MARKER")
	grep -q 'SPX SLAVE READBACK begin dev=0' <<<"$READBACK_LOG" ||
		fatal "physical-device readback did not start"
	if (( READBACK_RC == 0 )); then
		grep -q 'SPX SLAVE READBACK dev=0' <<<"$READBACK_LOG" ||
			fatal "physical-device readback returned without a result"
	else
		grep -q 'SPX SLAVE READBACK .*UNOBSERVABLE' <<<"$READBACK_LOG" ||
			fatal "physical-device readback failed without diagnostic evidence"
	fi
	printf '%s\n' "$READBACK_LOG" >"$LOG_DIR/slave-readback.log"

	# Optional wider WSA881x register forensics (still no PCM/PA): dump the
	# listed registers from the attached logical device via spx_wsa_seq's
	# reads mode. SPX_REG_READS is a comma list of register addresses.
	if [[ -n ${SPX_REG_READS:-} ]]; then
		echo "=== [4b] WSA881x register forensics (reads only) ==="
		kmsg_marker wsa-reg-reads
		REG_MARKER=$SPX_KMSG_MARKER
		set +e
		sudo insmod drivers/spx_extras/spx_wsa_seq.ko \
			"reads=$SPX_REG_READS" 2>/dev/null
		REG_RC=$?
		set -e
		# The module always fails its load with -EAGAIN by design.
		REG_LOG=$(logs_since_marker "$REG_MARKER")
		grep -q 'SPX seq-read' <<<"$REG_LOG" ||
			fatal "register-forensics module produced no reads"
		printf '%s\n' "$REG_LOG" >"$LOG_DIR/wsa-reg-reads.log"
		echo "register forensics captured (rc=$REG_RC; -EAGAIN expected)"
	fi

	TEST_SUCCEEDED=1
	sync
	echo "SPX: diagnostic-only readback complete; PCM and PA were never opened"
	exit 0
fi

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
set_ctl "$SPX_WCD_INTERP" "$SPX_WCD_SOURCE"
set_ctl "$SPX_WCD_COMP" 1
set_ctl "$SPX_WCD_VOLUME" 84
set_ctl "$SPX_SPK_PREFIX COMP Switch" 0
set_ctl "$SPX_SPK_PREFIX VISENSE Switch" 0
set_ctl "$SPX_SPK_PREFIX BOOST Switch" 1
set_ctl "$SPX_SPK_PREFIX DAC Switch" 1
# Force a real control transition after the cold-init replay.  Code 12 is the
# exact +18 dB setting used by the historically audible recovery runs; the
# guarded v3-v5 tests at code 8 were all silent despite correct transport.
# SPX_PA_VOLUME: PA gain force-written after cold init (12 = +18 dB, the
# historical guarded value; lower it for late-night runs).
set_ctl "$SPX_SPK_PREFIX PA Volume" 0
set_ctl "$SPX_SPK_PREFIX PA Volume" "${SPX_PA_VOLUME:-12}"
set_ctl "$SPX_SPK_PREFIX Smart Boost Level" 0

echo "=== [5] short 48 kHz $SPX_TONE_FORMAT stereo tone ==="
TONE_LOG=/tmp/spx-aplay.log
TONE_WAV="$LOG_DIR/preroll-tone.wav"
[[ $SPX_TONE_FORMAT == S16_LE ]] ||
	fatal "the silent-pre-roll proof is defined only for the S16_LE baseline"
# Keep one PCM handle open for three seconds of exact digital zero followed by
# five seconds of 440 Hz on only the selected logical channel.  The active
# controller snapshot runs entirely within the zero prefix, so its shared-bus
# traffic cannot cut the audible tone and no live mixer write is required.
ffmpeg -nostdin -v error \
	-f lavfi -i anullsrc=r=48000:cl=stereo:d=3 \
	-f lavfi -i sine=frequency=440:sample_rate=48000:duration=5 \
	-filter_complex "[1:a]volume=${SPX_TONE_GAIN:-6.4},$SPX_TONE_PAN[tone];[0:a][tone]concat=n=2:v=0:a=1[out]" \
	-map '[out]' -c:a pcm_s16le -y "$TONE_WAV" \
	2>"$LOG_DIR/ffmpeg.log" || fatal "failed to build the guarded pre-roll waveform"
# Optional objective listener (SPX_MIC_CAPTURE=1): record the built-in DMIC1
# through DEC0 -> SLIM TX0 -> SLIMBUS_0_TX -> MultiMedia2 for the whole tone
# window and score 440 Hz against neighbouring bins afterwards.  Needs the
# capture-parking q6asm-dai (2026-08-24) and the wcd934x micbias parse (1.8 V).
# Never fatal: it only adds evidence to the run directory.
MIC_PID=
MIC_WAV="$LOG_DIR/mic-DMIC1.wav"
if [[ ${SPX_MIC_CAPTURE:-0} == 1 ]]; then
	for c in 'MultiMedia2 Mixer SLIMBUS_0_TX:1' 'AIF1_CAP Mixer SLIM TX0:1' \
		'CDC_IF TX0 MUX:DEC0' 'ADC MUX0:DMIC' 'DMIC MUX0:DMIC1' 'DEC0 Volume:84'; do
		amixer -c "$SPX_CARD" cset name="${c%%:*}" "${c##*:}" >/dev/null 2>&1 ||
			echo "  mic: mixer write failed: $c"
	done
	setsid timeout -k 2 14 arecord -q -D "plughw:${SPX_CARD},1" -f S16_LE -r 48000 -c 1 \
		-d 9 "$MIC_WAV" >"$LOG_DIR/arecord.log" 2>&1 &
	MIC_PID=$!
	sleep 0.3
fi
kmsg_marker tone
TONE_MARKER=$SPX_KMSG_MARKER
set +e
setsid timeout -k 2 10 aplay -D "plughw:${SPX_CARD},0" \
	--period-size=12000 --buffer-size=48000 "$TONE_WAV" \
	>"$TONE_LOG" 2>&1 &
TONE_PID=$!
set -e
sleep 1
PCM_HW_PARAMS=/proc/asound/card${SPX_CARD}/pcm0p/sub0/hw_params
[[ -r $PCM_HW_PARAMS ]] || fatal "active PCM hw_params are unavailable"
cp "$PCM_HW_PARAMS" "$LOG_DIR/hw_params-active"
grep -qx "format: $SPX_TONE_FORMAT" "$PCM_HW_PARAMS" ||
	fatal "active PCM format disagrees with the requested guarded format"
grep -qx 'channels: 2' "$PCM_HW_PARAMS" ||
	fatal "active PCM is not stereo"
grep -qE '^rate: 48000( \(48000/1\))?$' "$PCM_HW_PARAMS" ||
	fatal "active PCM is not 48 kHz"
grep -qx 'period_size: 12000' "$PCM_HW_PARAMS" ||
	fatal "active PCM does not use the proven 12000-frame period"
grep -qx 'buffer_size: 48000' "$PCM_HW_PARAMS" ||
	fatal "active PCM does not use the proven 48000-frame buffer"
# The seven-register controller read takes roughly 140-165 ms through the
# shared WCD/SLIMbus bridge.  It is now safely inside the waveform's three
# seconds of digital zero, with ample settling time before the first sine
# sample reaches the already-open PCM stream.
fresh_regs active-stream
set +e
wait "$TONE_PID"
TONE_RC=$?
TONE_PID=
set -e
if (( TONE_RC != 0 && TONE_RC != 124 && TONE_RC != 137 )); then
	sed -n '1,120p' "$TONE_LOG" >&2
	fatal "aplay failed with exit code $TONE_RC"
fi
if [[ -n $MIC_PID ]]; then
	wait "$MIC_PID" 2>/dev/null || true
	MIC_PID=
	if [[ -s $MIC_WAV ]]; then
		python3 - "$MIC_WAV" <<'PY' | tee "$LOG_DIR/mic-goertzel.txt" || true
import sys, wave, struct, math
w = wave.open(sys.argv[1]); fs = w.getframerate()
v = struct.unpack('<%dh' % w.getnframes(), w.readframes(w.getnframes()))
def g(f, x):
    k = 2*math.cos(2*math.pi*f/fs); s1 = s2 = 0.0
    for s in x:
        s0 = s + k*s1 - s2; s2 = s1; s1 = s0
    return math.sqrt(max(s1*s1 + s2*s2 - k*s1*s2, 0)) / len(x) * math.sqrt(2)
# tone occupies 3..8 s of the aplay window; capture started ~0.3 s earlier
x = v[int(3.5*fs):int(7.5*fs)] if len(v) > 8*fs else v
rms = math.sqrt(sum(a*a for a in x)/len(x)) if x else 0
t = g(440, x) if x else 0
nb = max(g(f, x) for f in (330, 400, 480, 560)) if x else 0
print(f"SPX MIC: frames={len(v)} tone-window rms={rms:.1f} 440Hz={t:.2f} neighbours={nb:.2f} ratio={t/max(nb,1e-9):.1f}  ({'TONE DETECTED' if t > 5*nb and t > 1 else 'no tone'})")
PY
		python3 "$(dirname "$0")/spx-mic-analyze.py" "$MIC_WAV" 2>/dev/null |
			tee "$LOG_DIR/mic-analyze.txt" || true
	else
		echo "  mic: no capture file (arecord failed, see arecord.log)"
	fi
fi
# With the deliberately persistent WCD/AFE teardown policy, aplay can
# remain in PCM close after timeout sends SIGTERM and then be reaped by the
# two-second SIGKILL deadline (137).  ALSA DAPM also applies its normal delayed
# power-down several seconds after the process is gone.  Both are bounded here;
# do not misreport that expected protected teardown as a playback failure.
for ((i = 0; i < 80; i++)); do
	TONE_KERNEL_LOG=$(logs_since_marker "$TONE_MARKER")
	grep -q 'SPX: PA DAPM event 0x8' <<<"$TONE_KERNEL_LOG" && break
	sleep 0.1
done
grep -Fq "Playing WAVE '$TONE_WAV' : Signed 16 bit Little Endian, Rate 48000 Hz, Stereo" \
	"$TONE_LOG" || fatal "aplay never reported the guarded stereo waveform"
TONE_KERNEL_LOG=$(logs_since_marker "$TONE_MARKER")
if grep -qiE "$KERNEL_FAULT_RE" <<<"$TONE_KERNEL_LOG"; then
	KERNEL_FAULT=1
	fatal "kernel fault signature appeared during the controlled test"
fi
grep -q "SPX: hw_params active_ports=$SPX_EXPECT_ACTIVE_PORTS" \
	<<<"$TONE_KERNEL_LOG" ||
	fatal "WSA stream setup did not open $SPX_EXPECT_ACTIVE_PORTS descriptor(s)"
grep -q 'SPX: PA DAPM event 0x1' <<<"$TONE_KERNEL_LOG" ||
	fatal "speaker PA PRE_PMU event was not observed"
grep -q "SPX: Windows PA profile $SPX_EXPECT_WIN_PA_PROFILE" \
	<<<"$TONE_KERNEL_LOG" || fatal "the selected Windows PA branch was not observed"
if [[ $SPX_EXPECT_WIN_BIAS_PSRR != -1 ]]; then
	# The override is part of Windows' cold configuration and therefore
	# precedes the tone marker; it is intentionally not a PRE_PMU write.
	grep -q 'SPX: Windows BIAS_PSRR override 0x45' <<<"$(sudo dmesg)" ||
		fatal "the selected Windows BIAS_PSRR write was not observed"
fi
if [[ $SPX_EXPECT_WIN_TEMP_OP != -1 ]]; then
	grep -q 'SPX: Windows TEMP_OP override 0x0c' <<<"$(sudo dmesg)" ||
		fatal "the selected Windows TEMP_OP cold write was not observed"
fi
grep -q 'SPX: shadow slave DP1 ChannelEn value=0x01' <<<"$TONE_KERNEL_LOG" ||
	fatal "slave DP1 enable was not shadowed into both banks"
grep -q "SPX: shadow master DP$SPX_MASTER_PORT ChannelEn value=0x01" \
	<<<"$TONE_KERNEL_LOG" ||
	fatal "master DP$SPX_MASTER_PORT enable was not shadowed into both banks"
grep -q 'SPX: PA DAPM event 0x8' <<<"$TONE_KERNEL_LOG" ||
	fatal "speaker PA POST_PMD teardown event was not observed"
grep -q 'SPX: shadow slave DP1 ChannelEn value=0x00' <<<"$TONE_KERNEL_LOG" ||
	fatal "slave DP1 disable was not shadowed into both banks"
grep -q "SPX: shadow master DP$SPX_MASTER_PORT ChannelEn value=0x00" \
	<<<"$TONE_KERNEL_LOG" ||
	fatal "master DP$SPX_MASTER_PORT disable was not shadowed into both banks"
# The capture-parking q6asm-dai also logs the mic session's close (submitted=0,
# write_done=N); keep only playback lines (submitted>0) for the gate.
Q6_SUMMARY=$(grep 'SPX ASM stream .*bits=.*submitted=[1-9][0-9]*.*write_done=.*fallback=' \
	<<<"$TONE_KERNEL_LOG" | tail -1)
[[ -n $Q6_SUMMARY ]] || fatal "Q6ASM did not log a completed stream summary"
Q6_BITS=$(sed -n 's/.*bits=\([0-9]\+\).*/\1/p' <<<"$Q6_SUMMARY")
Q6_SUBMITTED=$(sed -n 's/.*submitted=\([0-9]\+\).*/\1/p' <<<"$Q6_SUMMARY")
Q6_WRITE_DONE=$(sed -n 's/.*write_done=\([0-9]\+\).*/\1/p' <<<"$Q6_SUMMARY")
Q6_FALLBACK=$(sed -n 's/.*fallback=\([0-9]\+\).*/\1/p' <<<"$Q6_SUMMARY")
[[ $Q6_BITS == "$SPX_EXPECT_BITS" ]] ||
	fatal "Q6ASM used $Q6_BITS significant bits, expected $SPX_EXPECT_BITS"
(( Q6_WRITE_DONE > 0 )) || fatal "DSP did not consume any submitted buffer"
[[ $Q6_FALLBACK == 0 ]] ||
	fatal "Q6ASM watchdog fallback ran; completion-pacing result is inconclusive"
[[ $Q6_SUBMITTED == "$Q6_WRITE_DONE" ]] ||
	fatal "Q6ASM submitted/completed counts disagree ($Q6_SUBMITTED/$Q6_WRITE_DONE)"

sleep 2
fresh_regs post-stream
POST_LOG=$(logs_since_marker "$ENUM_MARKER")
if grep -qiE "$KERNEL_FAULT_RE" <<<"$POST_LOG"; then
	KERNEL_FAULT=1
	fatal "kernel fault signature appeared during the controlled test"
fi
TEST_SUCCEEDED=1
cp "$TONE_LOG" "$LOG_DIR/aplay.log"
sync

echo
echo "ALSA submitted the guarded 5-second tone; the amp remained at device 0."
echo "Which physical speaker produced the 440 Hz tone, and was it clean?"
echo "The amplifier will be parked off and PipeWire left stopped on exit."
