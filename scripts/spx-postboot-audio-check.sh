#!/bin/sh
# SPDX-License-Identifier: GPL-2.0

set -u

REPO=/home/dvitali/Documents/git/linux-surface-kernel
LOG=/var/tmp/spx-audio-postboot-$(date +%Y%m%d-%H%M%S).log

exec >"$LOG" 2>&1

echo "SPX audio postboot check"
date -Is
uname -a
echo

echo "== module metadata =="
modinfo q6afe | grep -E '^(filename|vermagic|parm: *spx_auto_speaker_cal)' || true
modinfo q6afe-dai | grep -E '^(filename|vermagic|parm: *spx_no_port_stop)' || true
sha256sum \
	/lib/modules/$(uname -r)/kernel/sound/soc/qcom/qdsp6/q6afe.ko \
	/lib/modules/$(uname -r)/kernel/sound/soc/qcom/qdsp6/q6afe-dai.ko \
	/lib/modules/$(uname -r)/kernel/sound/soc/qcom/snd-soc-sdm845.ko || true
echo

echo "== loaded module params =="
printf 'q6afe.spx_auto_speaker_cal='
cat /sys/module/q6afe/parameters/spx_auto_speaker_cal 2>/dev/null || echo missing
printf 'q6afe_dai.spx_no_port_stop='
cat /sys/module/q6afe_dai/parameters/spx_no_port_stop 2>/dev/null || echo missing
echo

echo "== remoteproc/cards before =="
cat /sys/class/remoteproc/remoteproc2/state 2>/dev/null || true
cat /proc/asound/cards 2>/dev/null || true
echo

echo "== bring up card =="
if [ -x "$REPO/scripts/spx-run2-pio-full.sh" ]; then
	"$REPO/scripts/spx-run2-pio-full.sh" || true
else
	echo "missing $REPO/scripts/spx-run2-pio-full.sh"
fi
echo

echo "== short speaker-test =="
timeout -k 2 12 speaker-test -D plughw:0,0 -r 48000 -c 2 -t sine -f 660 || true
echo

echo "== remoteproc/cards after =="
cat /sys/class/remoteproc/remoteproc2/state 2>/dev/null || true
cat /proc/asound/cards 2>/dev/null || true
echo

echo "== recent SPX/q6 logs =="
dmesg | grep -Ei 'SPX|q6afe|q6asm|q6adm|APR|remoteproc|100fc|speaker|slim' | tail -n 240 || true

echo
systemctl disable spx-audio-postboot-check.service >/dev/null 2>&1 || true
echo "log saved at $LOG"
