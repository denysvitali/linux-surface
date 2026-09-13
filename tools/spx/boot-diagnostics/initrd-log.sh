#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
set -eu
mountpoint=/run/spx-diagnostics
mkdir -p "$mountpoint"
for attempt in $(seq 1 60); do
    [ ! -e /dev/disk/by-partuuid/028d76d8-a17e-4748-b9c1-515996a265ca ] || break
    sleep 1
done
mount -t vfat -o rw,iocharset=cp437 /dev/disk/by-partuuid/028d76d8-a17e-4748-b9c1-515996a265ca "$mountpoint"
trap 'sync; umount "$mountpoint" || true' EXIT
trap 'exit 0' TERM INT
out="$mountpoint/spx-diagnostics/$(cat /proc/sys/kernel/random/boot_id)"
mkdir -p "$out"
cat /proc/cmdline > "$out/cmdline"
# Snapshot immediately, then keep the latest ring until switch-root stops us.
while :; do
    dmesg > "$out/kernel.tmp"
    mv "$out/kernel.tmp" "$out/kernel.log"
    sync -f "$mountpoint"
    sleep 1
done
