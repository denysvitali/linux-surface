#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Probe for an audible baseline by disabling the two never-validated
# reverse-engineered knobs, then running the normal guarded bring-up.
#
# Why this exists: v3-v6 each passed every software gate and were all silent,
# so no boot in that series is known to make sound at all and every A/B in it
# is uninterpretable.  spx_win_pa_seq and spx_win_transport are forced on by
# every guarded GRUB entry, ship with cross-platform defaults of 0, and neither
# has ever been shown audible.  This deliberately changes BOTH at once: the
# goal is to recover a baseline, not to isolate a cause.  Bisect afterwards.
#
# Both parameters are 0644, so this needs no reboot and no rebuild.  It is an
# AUDIBILITY test only — only the first stream after a cold boot is a valid
# quality measurement.
#
# Run as the desktop user, never through sudo.

set -euo pipefail

if (( EUID == 0 )); then
	echo "FATAL: run $0 as the desktop user, without sudo" >&2
	exit 1
fi

cd "$(dirname "$0")/.."

PA_SEQ=/sys/module/snd_soc_wsa881x/parameters/spx_win_pa_seq
TRANSPORT=/sys/module/soundwire_qcom/parameters/spx_win_transport

for p in "$PA_SEQ" "$TRANSPORT"; do
	[[ -w $p ]] || { sudo test -w "$p" || { echo "FATAL: $p is not writable" >&2; exit 1; }; }
done

echo "SPX: pre-RE baseline probe"
echo "  before: spx_win_pa_seq=$(cat "$PA_SEQ") spx_win_transport=$(cat "$TRANSPORT")"

# Restore the knobs whatever happens, so a failed run does not leave the module
# state silently different from the booted command line.
restore()
{
	echo 1 | sudo tee "$PA_SEQ" >/dev/null || true
	echo 1 | sudo tee "$TRANSPORT" >/dev/null || true
	echo "SPX: restored spx_win_pa_seq=$(cat "$PA_SEQ") spx_win_transport=$(cat "$TRANSPORT")"
}
trap restore EXIT

echo 0 | sudo tee "$PA_SEQ" >/dev/null
echo 0 | sudo tee "$TRANSPORT" >/dev/null
echo "  after:  spx_win_pa_seq=$(cat "$PA_SEQ") spx_win_transport=$(cat "$TRANSPORT")"

# The bring-up script owns all the guarded checks, the tone and the amp
# parking; this wrapper only changes the two knobs around it.
exec ./scripts/spx-speakers-up.sh
