#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Preserve the early host kernel log without waiting for multi-user.target.
set -eu
umask 077
case " $(cat /proc/cmdline) " in *' spx_diag=20260913 '*) ;; *) exit 0 ;; esac

base=${SPX_DIAG_ROOT:-/var/lib/spx-boot-diagnostics}
boot=$(cat /proc/sys/kernel/random/boot_id)
mkdir -p "$base/boots/$boot"
# A service restart must not overwrite the preceding collection.
out=$(mktemp -d "$base/boots/$boot/early.XXXXXX")
cat /proc/cmdline > "$out/cmdline"
uname -a > "$out/uname"

# Bound storage and runtime to the existing three-minute diagnostic window.
# Keep each completed snapshot, including those preceding a failed command.
for sample in $(seq 1 90); do
    cat /proc/uptime > "$out/$sample.uptime"
    dmesg --color=never > "$out/$sample.kernel.tmp"
    mv "$out/$sample.kernel.tmp" "$out/$sample.kernel.log"
    sync -f "$out"
    sleep 2
done
