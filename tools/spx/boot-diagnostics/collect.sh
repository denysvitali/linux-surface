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
ngd_state() {
    local ngd_module=/sys/module/slim_qcom_ngd_ctrl
    local field
    if [ ! -d "$ngd_module" ]; then
        printf 'slim_qcom_ngd_ctrl is not loaded\n'
        return
    fi
    for field in "$ngd_module"/parameters/* "$ngd_module"/refcnt; do
        [ -r "$field" ] || continue
        printf '%s: ' "$field"
        cat "$field" || true
    done
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
capture audio-ngd-state ngd_state
capture audio-loader-state systemctl show spx-audio-modules.service \
    -p LoadState -p ActiveState -p SubState -p Result -p ExecMainStatus
capture audio-loader.log journalctl -b -u spx-audio-modules.service --no-pager -o short-monotonic
capture iptsd-state systemctl show 'iptsd@*.service' \
    -p Id -p LoadState -p ActiveState -p SubState -p Result -p ExecMainStatus
capture input-devices cat /proc/bus/input/devices
capture network ip -brief address
capture wireless iw dev
capture network-manager nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status
capture iwd-state systemctl show iwd.service -p ActiveState -p SubState -p ExecMainStatus
capture crypto cat /proc/crypto
# Cached SMEM DRAM data helps compare the GPU's UBWC configuration.
capture smem-hbb cat /sys/kernel/debug/qcom_smem/hbb
capture smem-dram-frequencies cat /sys/kernel/debug/qcom_smem/dram_frequencies
mkdir -p "$out/pstore" "$out/pstore-archive"
cp -a /sys/fs/pstore/. "$out/pstore/" || true
cp -a /var/lib/systemd/pstore/. "$out/pstore-archive/" || true
for kind in remoteproc drm power_supply watchdog devfreq; do
    for dir in /sys/class/"$kind"/*; do
        [ -e "$dir" ] || continue
        for field in name state status capacity online identity bootstatus timeout governor; do
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
