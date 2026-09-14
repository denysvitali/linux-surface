#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Run on both test and recovery boots; never change boot selection or reboot.
set -eu
umask 077
base=${SPX_DIAG_ROOT:-/var/lib/spx-boot-diagnostics}
boot=$(cat /proc/sys/kernel/random/boot_id)
out="$base/boots/$boot"
mkdir -p "$out"
exec 9>"$out/collect.lock"
flock 9
capture() {
    local name=$1
    shift
    "$@" >"$out/$name.tmp" 2>&1 || true
    mv "$out/$name.tmp" "$out/$name"
}
capture uname uname -a
capture boot-start uptime -s
capture collected-uptime cat /proc/uptime
capture cmdline cat /proc/cmdline
capture kernel.log journalctl -b -k --no-pager -o short-monotonic
capture journal.log journalctl -b --no-pager -o short-monotonic
capture failed-units systemctl --failed --no-pager
capture grubenv grub-editenv /boot/grub/grubenv list
capture efibootmgr efibootmgr
capture modules lsmod
capture devices lspci -nnk
capture usb lsusb -t
capture sound-cards cat /proc/asound/cards
capture network ip -brief address
mkdir -p "$out/pstore" "$out/pstore-archive"
cp -a /sys/fs/pstore/. "$out/pstore/" || true
cp -a /var/lib/systemd/pstore/. "$out/pstore-archive/" || true
for kind in remoteproc drm power_supply watchdog; do
    for dir in /sys/class/"$kind"/*; do
        [ -e "$dir" ] || continue
        for field in name state status capacity online identity bootstatus timeout; do
            [ -r "$dir/$field" ] || continue
            printf '%s: ' "$dir/$field"
            cat "$dir/$field" || true
        done
    done
done > "$out/hardware-state"
for field in mem_address mem_size record_size console_size pmsg_size ftrace_size; do
    [ -r /sys/module/ramoops/parameters/"$field" ] || continue
    printf '%s=' "$field"
    cat /sys/module/ramoops/parameters/"$field"
done > "$out/ramoops-layout"
trace=/sys/firmware/efi/efivars/SPXBootTrace-3f2f5454-6103-4d5c-9e77-268c2a7ac510
[ ! -f "$trace" ] || cp "$trace" "$out/efi-stage.bin"
[ ! -f "$base/attempt.json" ] || cp "$base/attempt.json" "$out/attempt.json"
# EFI-partition logs survive failures before the encrypted root is available.
[ ! -d /boot/spx-diagnostics ] || cp -an /boot/spx-diagnostics "$out/initrd-logs"
sync -f "$out"
printf 'Evidence saved to %s\n' "$out"
