#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Bound only an explicitly marked diagnostic boot; never re-arm the test entry.
set -eu
umask 077
case " $(cat /proc/cmdline) " in *' spx_diag=20260913 '*) ;; *) exit 0 ;; esac
base=/var/lib/spx-boot-diagnostics
boot=$(cat /proc/sys/kernel/random/boot_id)
out="$base/boots/$boot"
/usr/local/lib/spx-boot-diagnostics/collect.sh
# AGENTS.md: recheck current boot, its age and the requested state before reboot.
uptime -s > "$out/pre-return-boot-start"
current=$(cat /proc/sys/kernel/random/boot_id)
[ "$current" = "$boot" ] || exit 1
read -r age _ < /proc/uptime
[ "${age%.*}" -ge 120 ] || exit 1
case " $(cat /proc/cmdline) " in *' spx_diag=20260913 '*) ;; *) exit 1 ;; esac
# A previous interrupted command may already have executed: never issue twice.
(set -o noclobber; printf '%s\n' "$boot" > "$out/return-requested") || exit 0
grub-editenv /boot/grub/grubenv list > "$out/pre-return-grubenv"
if grep -Eq '^next_entry=.+$' "$out/pre-return-grubenv"; then
    echo 'Refusing automatic return: another boot entry is queued' >&2
    exit 1
fi
sync
systemctl --no-block reboot
