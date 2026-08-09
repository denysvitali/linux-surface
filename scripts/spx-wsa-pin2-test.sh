#!/bin/bash
# SPDX-License-Identifier: GPL-2.0

echo "FATAL: the legacy pin2 test is disabled." >&2
echo "Its old GRUB entry powers both amplifiers at device 0 and causes a bus clash." >&2
echo "Use the guarded spx-speaker-dev0-v3-audited entry and scripts/spx-speakers-up.sh." >&2
exit 1
