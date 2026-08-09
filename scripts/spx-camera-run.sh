#!/bin/sh
# Wrapper run by spx-camera-probe.service. Kept as a script rather than an
# inline ExecStart because systemd pre-expands $VAR and mangles multi-command
# shell lines; a script file has no such quoting hazard.
#
# Everything is line-buffered and dmesg is dumped BETWEEN stages, because a
# camera boot can die hard: on 2026-08-07 two boots wedged mid-probe and left a
# 0-byte stream log, so the run told us nothing about how far it had got.
# Flushing as we go means even a hang leaves a usable trail.
D=/home/dvitali/Documents/git/linux-surface-kernel

run() {
	# stdbuf keeps the redirect line-buffered so a hard hang still leaves
	# everything printed up to that point on disk.
	stdbuf -oL -eL "$1" > "$2" 2>&1
}

# Archive the PREVIOUS run's logs instead of letting them be deleted or clobbered.
# Measured 2026-08-07: a completed level-0 run's results were destroyed by an
# "rm -f /var/log/spx-camera-*.log" issued while arming the next boot, before
# anyone had read them. Each result costs a reboot - never throw one away.
ARCH=/var/log/spx-camera-prev
rm -rf "$ARCH"; mkdir -p "$ARCH"
for f in /var/log/spx-camera-*.log /var/log/spx-camera-frame.raw; do
	[ -e "$f" ] && mv -f "$f" "$ARCH/" 2>/dev/null
done
sync

> /var/log/spx-camera-stage.log
# Breadcrumbs, each flushed to disk. The 2026-08-07 run died within milliseconds
# of the stream stage starting and left NO stream log at all, which made "hung in
# stream.sh" and "power cut at that instant" indistinguishable. These make the
# last completed step unambiguous on the next boot.
mark() { echo "$(date +%T) $*" >> /var/log/spx-camera-stage.log; sync; }

# FIRST: recover the PREVIOUS camera boot's console from ramoops. STREAMON hangs
# the whole SoC, so nothing can be written to disk after it - but whatever the
# kernel printed BEFORE the hang is already in the ramoops console buffer and
# survives the power cycle. Only this GRUB entry can read it back: the camera
# entry sets ramoops.console_size=0x20000 while the DEFAULT entry has
# console_size=0 and cannot expose the record at all.
{
	echo "=== pstore records from the PREVIOUS boot ==="
	ls -l /sys/fs/pstore/ 2>&1
	for f in /sys/fs/pstore/*; do
		[ -f "$f" ] || continue
		echo "--- $f ---"
		cat "$f" 2>&1
	done
} > /var/log/spx-camera-pstore.log 2>&1
sync
# Clear them so the next boot's records are unambiguous.
rm -f /sys/fs/pstore/* 2>/dev/null

mark "probe: start"
run "$D/scripts/spx-camera-probe.sh" /var/log/spx-camera-probe.log
mark "probe: done"
dmesg > /var/log/spx-camera-dmesg-afterprobe.log 2>&1
sync

# This runner is started manually after the camera-entry boot is reachable.
# The unit has no SuccessAction/FailureAction: a successful measurement stays
# online for inspection instead of entering the shutdown path that wedged after
# the 2026-08-09 v22 capture.  The stream-local watchdog/SysRq timer remains the
# emergency recovery for an ioctl that never returns.
mark "stream: start"
if run "$D/scripts/spx-camera-stream.sh" /var/log/spx-camera-stream.log; then
	mark "stream: done"
else
	rc=$?
	mark "stream: FAILED rc=$rc (bisect level NOT advanced)"
fi
dmesg > /var/log/spx-camera-dmesg.log 2>&1
sync
# Tear down HERE, not in ExecStop. Measured 2026-08-07: SuccessAction=reboot
# reboots the machine directly instead of stopping the unit first, so ExecStop
# never ran on a successful boot - no down.log was ever written and LDO14_A was
# still ON in the following boot. Doing it inline makes it deterministic and
# keeps ExecStop only as a backstop for the failure path.
mark "teardown: start"
"$D/scripts/spx-camera-down.sh" > /var/log/spx-camera-down.log 2>&1 || true
sync
mark "teardown: done"

mark "ALL DONE - capture complete; remaining online (no automatic reboot)"
exit 0
