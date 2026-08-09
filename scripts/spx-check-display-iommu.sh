#!/bin/sh
# Post-reboot check after the mdss SMR 0x421 + disable_bypass removal fix.
echo "=== cmdline (disable_bypass should be ABSENT) ==="
cat /proc/cmdline | tr ' ' '\n' | grep -iE "disable_bypass|smmu" || echo "  (no disable_bypass — good)"
echo "=== running FDT mdss mask (should be 0x421) ==="
dtc -I dtb -O dts /sys/firmware/fdt 2>/dev/null | grep -A0 "0x800 0x42" | head
echo "=== SMMU FAULTS (if any unmatched SID remains, it names it here) ==="
sudo dmesg | grep -iE "arm-smmu|Unhandled context fault|global fault|FSR|FSYNR|iova=|fault.*0x|smmu.*fault" | grep -viE "probing|SMMUv2|stage 1|coherent|stream matching|context banks|page sizes|Stage-1|preserved|Adding to iommu" | head -20
echo "=== display state ==="
echo "eDP-1 status: $(cat /sys/class/drm/card0/card0-eDP-1/status 2>/dev/null)"
echo "modes: $(cat /sys/class/drm/card0/card0-eDP-1/modes 2>/dev/null | tr '\n' ' ')"
echo "=== DPU scanout (should still be 2880x1920; the question is whether pixels are correct now) ==="
sudo dmesg | grep -iE "panel edid|conservative|No display modes|adreno_load_gpu|zap_shader|GMU OOB" | head
