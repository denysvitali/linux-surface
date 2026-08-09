#!/bin/bash
# SPX wsairq + slimfix bring-up
# Loads modules, bumps probe stage, triggers reenum — in correct order.

set -e

echo "=== SPX wsairq + slimfix bring-up ==="
date

# 1. Confirm slimfix kernel (uname doesn't carry the suffix; check BOOT_IMAGE)
echo "[1] Checking kernel..."
uname -r
if ! grep -q "BOOT_IMAGE=[^ ]*slimfix" /proc/cmdline; then
    echo "    ERROR: not booted from the slimfix vmlinuz (check BOOT_IMAGE in /proc/cmdline)"
    exit 1
fi

# 2. Confirm wsairq DTB
echo "[2] Checking DTB..."
if [ ! -f /proc/device-tree/soc@0/slim-ngd@171c0000/slim@1/codec@1,0/interrupts ]; then
    echo "    WARN: codec IRQ not in DTB (ls dtb/soc@0/.../codec@1,0/)"
fi

# 3. Load base modules
echo "[3] Loading slimbus/soundwire/wcd934x..."
sudo modprobe slimbus 2>&1 | tail -3
sudo modprobe soundwire_qcom spx_core_enum=1 2>&1 | tail -3
sudo modprobe wcd934x spx_wsa_en_pin=2 2>&1 | tail -3

sleep 2

# 4. Bump NGD controller stage
echo "[4] Bumping NGD stage..."
sudo bash -c 'echo 8 > /sys/module/slim_qcom_ngd_ctrl/parameters/spx_probe_stage'
sudo bash -c 'echo 1 > /sys/module/slim_qcom_ngd_ctrl/parameters/spx_pio_mode'
sudo bash -c 'echo 1 > /sys/module/slim_qcom_ngd_ctrl/parameters/spx_allow_full'
sudo bash -c 'echo Y > /sys/module/slim_qcom_ngd_ctrl/parameters/spx_pin_after_qmi'

# 5. Re-probe NGD child
echo "[5] Re-probing NGD child..."
if [ -e /sys/bus/platform/drivers/qcom,slim-ngd/qcom,slim-ngd.1 ]; then
    sudo bash -c 'echo qcom,slim-ngd.1 > /sys/bus/platform/drivers/qcom,slim-ngd/unbind' 2>&1 || true
    sleep 1
    sudo bash -c 'echo qcom,slim-ngd.1 > /sys/bus/platform/drivers/qcom,slim-ngd/bind'
    sleep 4
fi

# 6. Trigger SoundWire reenum
echo "[6] Triggering SoundWire reenum..."
sudo bash -c 'echo 1 > /sys/module/soundwire_qcom/parameters/spx_reenum' 2>&1 || true

sleep 5

# 7. Report state
echo "[7] Final state:"
echo "    /sys/bus/slimbus/devices:"
ls /sys/bus/slimbus/devices/ 2>&1
echo "    /sys/bus/soundwire/devices:"
ls /sys/bus/soundwire/devices/ 2>&1
echo "    /sys/bus/soundwire/controllers:"
ls /sys/bus/soundwire/controllers/ 2>&1
echo
echo "=== Done. Check dmesg for SoundWire slave attach events. ==="
