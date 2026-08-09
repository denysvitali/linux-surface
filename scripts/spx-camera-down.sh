#!/bin/sh
# spx-camera-down.sh - put the camera subsystem back down before a reboot.
#
# Why this exists: three camera test boots (v12, v14, v16) failed to boot at all,
# and v14/v16 each directly followed a boot in which qcom-camss had been loaded
# and the sensor rails raised over SPMI. Leaving the ISP powered and the rails up
# across a warm reboot is the one thing those runs had in common, so tear it all
# down explicitly rather than relying on the reboot to do it.
#
# Run this at the end of a camera test boot, BEFORE asking for a reboot.
set -e
cd "$(dirname "$0")/.."

echo "== leaving camera drivers loaded until reboot =="
# Never unload any live camera module on this platform.  It is not limited to
# qcom_camss: the 2026-08-09 CSID-testgen run completed and closed /dev/video0,
# then hung immediately in the first attempted unload (ov5693).  The resulting
# RCU stalls and kick_all_cpus_sync soft lockups prevented the automatic reboot.
# A reboot removes the modules safely; only the three sensor rails need explicit
# shutdown here.

echo
echo "== dropping the sensor rails (reverse of bring-up order) =="
# Bring-up raises 14 (dovdd 1.8V), 17 (avdd 2.85V), 1 (dvdd 1.2V); drop in reverse.
for L in 1 17 14; do
        sudo insmod drivers/spx_extras/spx_pmic_ldo.ko sid=1 ldo=$L enable=-1 2>/dev/null || true
done
dmesg | grep spxldo | tail -6

echo
echo "== verify all three are OFF =="
for L in 14 17 1; do
        sudo insmod drivers/spx_extras/spx_pmic_ldo.ko sid=1 ldo=$L dump=0 2>/dev/null || true
done
dmesg | grep -E 'spxldo: LDO(14|17|1)_A' | tail -3

echo
echo "If any rail still reads ON, say so before rebooting - that is the state"
echo "suspected of breaking the following boot."
