#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# SPX camera CCI probe. Run after booting the "spx-camera-test" GRUB entry.
#
# Answers one question: are the camera sensor supply rails always-on?
#   - a sensor answers with its chip ID  -> rails are up, bring-up can proceed
#   - nothing answers on any bus         -> rails are firmware-gated (or the
#                                           CCI/PHY mapping is wrong)
#
# Everything here is loaded by hand from the build tree, so nothing depends on
# the initramfs and no module needed installing.

set -eu
cd "$(dirname "$0")/.."

echo "== preconditions =="
if ! grep -q camera-test /proc/cmdline 2>/dev/null; then
	:  # cmdline is identical to known-good by design; check the DTB instead
fi
if [ ! -d /proc/device-tree/soc@0/cci@ac4b000 ] && \
   [ ! -d /proc/device-tree/soc@0/cci@ac4c000 ]; then
	echo "!! no cci node in the booted DT - you are NOT on the camera-test"
	echo "!! entry. Re-arm it and reboot; do not trust any result from here."
	exit 1
fi
echo "ok: cci node present in booted DT"

echo
echo "== loading camcc (camera clock controller) =="
if [ ! -d /sys/bus/platform/drivers/camcc-sc8180x ]; then
	sudo insmod drivers/clk/qcom/camcc-sc8180x.ko
fi
sudo dmesg -C 2>/dev/null || true

echo "== loading CCI i2c controller =="
sudo modprobe i2c-qcom-cci || true
sleep 1

echo
echo "== CCI adapters =="
for a in /sys/class/i2c-adapter/*; do
	n=$(cat "$a/name" 2>/dev/null || true)
	case "$n" in *cci*|*CCI*) echo "  $(basename "$a"): $n";; esac
done
ls -d /sys/bus/platform/devices/ac4a000.cci /sys/bus/platform/devices/ac4b000.cci 2>/dev/null || \
	echo "  (no cci platform devices - check dmesg for probe deferral)"

echo
echo "== camera rail LDO14_A on, over SPMI =="
# RPMh refuses cmd-db resource "ldoa14" from the APPS RSC: the write is never
# ACKed (-ETIMEDOUT) and, worse, it keeps its active TCS slot, so a SECOND
# rpmh_write() hangs uninterruptibly. Windows votes this rail from PEP
# firmware, i.e. a different RSC DRV. SPMI reaches the same PMIC directly and
# sidesteps the ownership question entirely. Verified: sid 1 (PMIC A
# secondary), LDO14 base 0x4d00, TYPE=0x04 (LDO), VSET already 0x0708 = 1800 mV.
sudo insmod drivers/spx_extras/spx_pmic_ldo.ko sid=1 ldo=14 enable=1 2>/dev/null || true

echo
echo "== Windows-exact power-on (no bus sweep) =="
echo "   (TLMM12 reset, cam_cc_mclk2 @19.2MHz on TLMM15,
    CCI1 on gpio17-20 AND CCI2 on gpio31-34, both @100kHz)"
# do_sweep=1 is DELIBERATELY OMITTED. Measured 2026-08-07: two consecutive
# camera boots died hard ~33 s after this service started, both with the journal
# ending mid-flood of "i2c-qcom-cci ac4c000.cci: master 1 queue 0 timeout" (298
# of them) and no shutdown record. The full 7-bit sweep hammers the ac4c000 /
# ac4d000 buses that are already known to stall, and that is what wedges the
# machine - NOT leftover rail state, which is what we previously blamed.
# The sweep has also already served its purpose: the front OV5693 was located at
# 0x36 and the driver binds it as 4-0036, so there is nothing left to discover
# here. Power-on, reset and MCLK still happen; only the scan is skipped.
sudo insmod drivers/spx_extras/spx_cam_go.ko 2>/dev/null || true
sleep 1
dmesg | grep -E 'spxldo|spxcam' | tail -40

echo
echo "== ov5693 sensor driver =="
# The DT gives the sensor always-on regulator-fixed stand-ins, because the real
# rails (LDO17_A avdd 2.85V, LDO14_A dovdd 1.8V, LDO1_A dvdd 1.2V) cannot be
# voted over RPMh from the APPS RSC - they are raised over SPMI above.
# The node also carries power-domains = <&camcc TITAN_TOP_GDSC> so that
# clk_prepare_enable(xvclk) in the driver's power-on can actually ungate MCLK2.
# udev autoloads ov5693 at boot from the DT modalias, long BEFORE the rails are
# raised over SPMI - that probe always fails with -110 and a plain modprobe
# afterwards is a no-op because the module is already loaded. Unload first so the
# probe is retried now that the sensor actually has power, MCLK and reset.
# Drop CAMSS first as well.  Leaving its async notifier/media graph alive while
# rebinding the sensor produced a real bound 4-0036 device but no ov5693 entity
# in /dev/media0 on 2026-08-08.  Rebuilding the graph only after the powered
# sensor has registered removes that race.
sudo modprobe -r qcom-camss 2>/dev/null || true
sudo modprobe -r ov5693 2>/dev/null || true
sudo modprobe ov5693 2>/dev/null || true
sleep 1
dmesg | grep -iE 'ov5693' | tail -10
for d in /sys/bus/i2c/drivers/ov5693/*; do
        [ -e "$d/name" ] && echo "  bound: $(basename $d)"
done 2>/dev/null

echo
echo "== CAMSS (Titan 480 ISP) =="
# The SC8180X CAMSS support is adapted from sc8280xp: upstream already maps
# "qcom,sc8180x-camss" onto sc8280xp_resources, so the register/clock/IRQ
# layout is identical. interconnects are deliberately OMITTED - an absent
# "interconnects" property makes of_icc_get return NULL (skip constraints)
# rather than an error, and this board's interconnect ids are unverified.
# dyndbg=+p turns on every dev_dbg in the driver. STREAMON hard-hangs the SoC, so
# the only record of how far it got is what reached the ramoops console buffer
# BEFORE the hang - which means the more the driver prints on the way in, the
# more precisely the next boot can localize the hang. CONFIG_DYNAMIC_DEBUG=y.
# spx_stop_after bisects the SoC hang by bounding how many upstream subdevs get
# s_stream(1): 1=vfe, 2=+csid, 3=+csiphy, 4=+sensor, -1=stock/all. There is no way
# to log from inside the failing boot (the SoC dies, and a watchdog bite resets
# via the PMIC so ramoops is lost too), so SURVIVAL is the measurement: a boot
# that comes back and writes these logs proves every enabled stage is safe.
# The level auto-advances so consecutive camera boots walk the bisect themselves.
STOPF=$(cat /var/lib/spx-stop-after 2>/dev/null || echo 1)
echo "  spx_stop_after=$STOPF  (1=vfe 2=+csid 3=+csiphy 4=+sensor)"
# MUST unload first. udev autoloads qcom-camss at boot from the DT modalias, so a
# plain modprobe here is a NO-OP and spx_stop_after silently stays at its default.
# Measured 2026-08-07: three "bisect" boots reported "spx_stop_after now = -1"
# despite being armed with 0/1, i.e. every one of them was really a full-chain run
# and the bisect never happened. Same trap already hit with ov5693 above.
sudo modprobe -r qcom-camss 2>/dev/null || true
sudo modprobe qcom-camss spx_stop_after=$STOPF dyndbg=+p 2>/dev/null || \
	sudo modprobe qcom-camss spx_stop_after=$STOPF 2>/dev/null || true
# Prove it took, rather than assuming: this value is the one that matters.
cat /sys/module/qcom_camss/parameters/spx_stop_after > /var/lib/spx-stop-after-used 2>/dev/null || true
echo "  VERIFY spx_stop_after = $(cat /sys/module/qcom_camss/parameters/spx_stop_after 2>/dev/null)"
sleep 1
dmesg | grep -iE 'camss|csiphy|csid|vfe' | tail -25

echo
echo "-- module identity (did the rebuilt qcom-camss actually load?) --"
# initramfs bundles the .ko, so a missed mkinitcpio silently boots the STALE copy.
sha256sum /lib/modules/$(uname -r)/updates/qcom-camss.ko 2>/dev/null | cut -c1-20
cat /sys/module/qcom_camss/parameters/spx_stop_after 2>/dev/null | sed 's/^/  spx_stop_after now = /'

echo
echo "-- IFE/TITAN power domains + camcc clocks (safe reads, pre-stream) --"
# If the VFE block is unclocked or unpowered at s_stream time, its first register
# access hangs the NoC. These are plain debugfs reads and touch no hardware.
grep -iE 'ife|titan|camcc' /sys/kernel/debug/pm_genpd/pm_genpd_summary 2>/dev/null | head -20 \
	|| echo "  (pm_genpd_summary unavailable)"
grep -iE 'cam_cc_(ife_0|camnoc|cpas|core)' /sys/kernel/debug/clk/clk_summary 2>/dev/null | head -20 \
	|| echo "  (clk_summary unavailable)"

echo
echo "-- v4l2 subdev / media nodes --"
ls -l /dev/v4l-subdev* /dev/video* /dev/media* 2>/dev/null || echo "  (none)"
# NOT truncated. This graph is the cheapest evidence of which CSIPHY the DTB's
# port@N actually selected - the sensor->PHY link is IMMUTABLE, so it names the
# PHY without having to stream at all. A previous "head -40" cut the dump off
# before the ov5693 entity block and cost a whole boot's worth of information.
command -v media-ctl >/dev/null && media-ctl -p 2>/dev/null

echo
echo "== interpretation =="
echo "  The front OV5693 lives at 0x36 on cci@ac4a000 i2c-bus@1 (measured"
echo "  2026-08-06, chip id 0x5690). Its module EEPROM answers at 0x50."
echo
echo "  Sensor bound (4-0036 under /sys/bus/i2c/drivers/ov5693) -> the sensor"
echo "  driver owns the part. That was confirmed on 2026-08-06."
echo
echo "  camss probing + /dev/video0 appearing -> the ISP is up; then verify the"
echo "  media graph links ov5693 -> csiphy0 -> csid -> vfe."
echo "  camss probe fails on a clock/GDSC -> a camcc id is wrong for sc8180x."
echo "  Graph links but streaming gives no frames / lane errors -> the sensor is"
echo "  NOT on csiphy0; the CSIPHY assignment is UNVERIFIED (the ACPI-derived"
echo "  CCI mapping proved wrong, so its PHY claim is not trustworthy either)."
echo "  Retry with port@1/2/3 - one PHY per boot."
echo
echo "  Rear (0x10) and aux (0x60) are still unlocated; two CCI buses"
echo "  (ac4c000 both, ac4d000 bus@0) still stall and may hide them."
