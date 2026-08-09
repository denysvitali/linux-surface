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
# Preferred use is the `spx-speaker-dev0-v7-prere` GRUB entry, which boots with
# both knobs already 0 so the very first stream of the boot is the measurement.
# Both parameters are also 0644, so this script can flip them on a live boot —
# but that is only an AUDIBILITY test, because only the first stream after a
# cold boot is a valid quality measurement.
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
	[[ -e $p ]] || { echo "FATAL: $p is missing" >&2; exit 1; }
done

echo "SPX: pre-RE baseline probe"
echo "  booted: spx_win_pa_seq=$(cat "$PA_SEQ") spx_win_transport=$(cat "$TRANSPORT")"

# If the boot already carries the pre-RE values, change nothing: the first
# stream of this boot is then a real quality measurement, not just audibility.
if [[ $(cat "$PA_SEQ") == 0 && $(cat "$TRANSPORT") == 0 ]]; then
	echo "  both knobs already 0 from the command line — no live write needed"
else
	echo "  WARNING: flipping knobs live; this is an audibility test only,"
	echo "           because the boot did not start with the pre-RE values"
	restore()
	{
		echo 1 | sudo tee "$PA_SEQ" >/dev/null || true
		echo 1 | sudo tee "$TRANSPORT" >/dev/null || true
		echo "SPX: restored the reverse-engineered knobs to 1"
	}
	trap restore EXIT
	echo 0 | sudo tee "$PA_SEQ" >/dev/null
	echo 0 | sudo tee "$TRANSPORT" >/dev/null
fi

# Tell the guarded bring-up which values to demand, so step [0] still verifies
# the boot matches this experiment instead of being bypassed.
export SPX_EXPECT_WIN_PA_SEQ=0
export SPX_EXPECT_WIN_TRANSPORT=0

# The bring-up script owns all the guarded checks, the tone and the amp
# parking; this wrapper only settles the two knobs around it.
exec ./scripts/spx-speakers-up.sh
