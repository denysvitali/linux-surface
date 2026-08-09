#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Recovery uses the same guarded, stream-idle power-cycle and validation path as
# the initial test. The former direct re-enum/PA-enable recipe could reset an
# active controller and unmute before SoundWire ports were prepared.

set -euo pipefail

if (( $# )); then
	echo "FATAL: file playback is no longer accepted by the recovery wrapper" >&2
	exit 1
fi

exec "$(dirname "$0")/spx-speakers-up.sh"
