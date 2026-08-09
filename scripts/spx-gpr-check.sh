#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# Run this AFTER booting the GRUB entry:
#   "EXPERIMENTAL: GPR/AudioReach over apr_audio_svc (q6apm)"
#
# It checks whether the GPR transport connected to the sc8180x ADSP over the
# apr_audio_svc GLINK channel and whether q6apm/AudioReach ("Graphite") came
# up. Decisive signals:
#   - gpr/q6apm probe with NO timeout, a sound card appears  -> BREAKTHROUGH
#   - "gpr ... timed out" / q6apm fails / no card            -> firmware does
#                                                               not speak GPR
#                                                               on this channel
#   - ADSP state != running                                  -> ADSP crashed
set -u

echo "=== 1. which DTB booted? (want gpr + apr_audio_svc) ==="
fdt=/sys/firmware/fdt
sudo grep -aqo "qcom,gpr" "$fdt" 2>/dev/null && echo "  qcom,gpr present: YES" || echo "  qcom,gpr present: NO (not the GPR DTB!)"
sudo strings "$fdt" 2>/dev/null | grep -qx "apr_audio_svc" && echo "  apr_audio_svc string present: YES"

echo
echo "=== 2. ADSP remoteproc state (want: running) ==="
cat /sys/class/remoteproc/remoteproc2/state 2>/dev/null

echo
echo "=== 3. load AudioReach stack if not auto-loaded ==="
for m in q6apm_dai snd_q6apm q6apm_lpass_dais q6prm q6prm_clocks; do
	lsmod | grep -q "^$m " || sudo modprobe "$m" 2>&1 | sed "s/^/  modprobe $m: /"
done
echo "loaded:"; lsmod | grep -iE "gpr|q6apm|q6prm|apr" | awk '{print "  "$1}'

echo
echo "=== 4. did GPR connect / q6apm probe? (dmesg) ==="
sudo dmesg | grep -iE "gpr|q6apm|q6prm|graphite|apm_|audioreach|adsp.*audio|glink.*apr_audio" | tail -30

echo
echo "=== 5. errors / timeouts (want NONE) ==="
sudo dmesg | grep -iE "gpr.*(timed out|fail|error)|q6apm.*(fail|error|timeout)|glink.*(assert|migration)|rproc.*(crash|fatal)" | tail -20

echo
echo "=== 6. rpmsg: is apr_audio_svc bound by gpr now? ==="
ls /sys/bus/rpmsg/devices/ 2>/dev/null | grep -iE "apr_audio|gpr|17300000" || echo "  (none)"

echo
echo "=== 7. sound card (want a q6apm-based card) ==="
cat /proc/asound/cards 2>/dev/null || echo "  (no card)"

echo
echo "=== 8. display sanity (should still be native) ==="
echo -n "  fb: "; cat /sys/class/graphics/fb0/virtual_size 2>/dev/null | tr , x
echo "DONE. Paste this whole output back."
