#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Stage 1 evidence: did the known-good kernel adopt the APSS watchdog?
# Run after booting spx-known-good-wdt. Read-only.
set -u
echo "== boot =="
cat /proc/sys/kernel/random/boot_id
uptime -s
grep -o 'spx_boot=[a-z-]*' /proc/cmdline

echo
echo "== device tree =="
node=/proc/device-tree/soc@0/watchdog@17c10000
if [ -d "$node" ]; then
    echo "node present: $node"
    tr '\0' ' ' < "$node/compatible"; echo
else
    echo "MISSING: $node (booted the wrong DTB?)"
fi

echo
echo "== watchdog class =="
ls /sys/class/watchdog/ 2>/dev/null || echo "  empty"
for attr in identity state status timeout timeleft bootstatus; do
    [ -r "/sys/class/watchdog/watchdog0/$attr" ] &&
        printf '  %-11s %s\n' "$attr" "$(cat "/sys/class/watchdog/watchdog0/$attr")"
done

echo
echo "== pid 1 ownership =="
echo "  RuntimeWatchdogUSec $(systemctl show -p RuntimeWatchdogUSec --value)"
if [ -c /dev/watchdog0 ]; then
    owner=$(sudo fuser /dev/watchdog0 2>/dev/null | tr -s ' ' '\n' | grep -v '^$' | head -1)
    echo "  /dev/watchdog0 held by PID ${owner:-none} (1 = systemd)"
else
    echo "  /dev/watchdog0 absent"
fi

echo
echo "== kernel log =="
dmesg 2>/dev/null | grep -iE 'wdt|watchdog' || echo "  (no watchdog lines)"

echo
echo "== grubenv (next_entry must be consumed) =="
sudo grub-editenv /boot/grub/grubenv list
