#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# Build and install everything the SPX audio bring-up touches:
#   - DTB (sc8180x-surface-pro-x)
#   - drivers/slimbus      (slimbus core, slim-qcom-ngd-ctrl)
#   - drivers/soundwire    (soundwire-qcom)
#   - drivers/mfd          (wcd934x)
#   - sound/soc/codecs     (snd-soc-wcd934x, snd-soc-wsa881x)
#   - sound/soc/qcom       (q6afe-dai, q6asm-dai and friends)
# Each installed file gets a timestamped backup. Run from the repo root.

set -eu

cd "$(dirname "$0")"

KVER="$(uname -r)"
KDIR="/lib/modules/$KVER/kernel"
FW_DIR="/usr/lib/firmware/qcom/msft/surface/pro-x-sq2"
DTB_SRC="arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb"
DTB_DST="/boot/dtb/qcom/sc8180x-surface-pro-x.dtb"
DTB_TEST_SRC="arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x-speaker-left.dtb"
DTB_TEST_DST="/boot/dtb/qcom/sc8180x-surface-pro-x.dtb.speaker-left"
TS="$(date +%Y%m%d-%H%M%S)"
JOBS="$(nproc)"

echo "== building (kernel $KVER, ts $TS) =="
# KBUILD_MODPOST_WARN: the top-level Module.symvers no longer carries all
# vmlinux exports (clobbered by partial builds); the symbols resolve fine
# at load time, so demote modpost undefined-symbol errors to warnings.
make -j"$JOBS" qcom/sc8180x-surface-pro-x.dtb
make -j"$JOBS" qcom/sc8180x-surface-pro-x-speaker-left.dtb
make -j"$JOBS" KBUILD_MODPOST_WARN=1 M=drivers/slimbus modules
make -j"$JOBS" KBUILD_MODPOST_WARN=1 M=drivers/soundwire modules
make -j"$JOBS" KBUILD_MODPOST_WARN=1 M=drivers/mfd modules
make -j"$JOBS" KBUILD_MODPOST_WARN=1 M=sound/soc/codecs modules
make -j"$JOBS" KBUILD_MODPOST_WARN=1 M=sound/soc/qcom modules

# install <src> <dst>: timestamped backup of dst, then copy.
inst() {
	src="$1" dst="$2"
	if [ -f "$dst" ]; then
		sudo cp "$dst" "$dst.$TS"
	fi
	sudo cp "$src" "$dst"
	echo "installed: $dst"
}

inst_no_backup() {
	src="$1" dst="$2"
	sudo cp "$src" "$dst"
	echo "installed: $dst"
}

echo "== installing =="

# Keep all boot entries paired with the known-working Linux ADSP image.
if [ -f "$FW_DIR/qcadsp8180.mbn.linux-surface" ]; then
	sudo cp "$FW_DIR/qcadsp8180.mbn.linux-surface" "$FW_DIR/qcadsp8180.mbn"
	echo "firmware: Linux ADSP image restored"
fi

# Never overwrite the generic DTB from this experimental tree. The bootloader
# default is deliberately pinned to the separately preserved .dtb.wsa image.
inst_no_backup "$DTB_TEST_SRC" "$DTB_TEST_DST"
inst drivers/slimbus/slimbus.ko              "$KDIR/drivers/slimbus/slimbus.ko"
inst drivers/slimbus/slim-qcom-ngd-ctrl.ko   "$KDIR/drivers/slimbus/slim-qcom-ngd-ctrl.ko"
inst drivers/soundwire/soundwire-bus.ko      "$KDIR/drivers/soundwire/soundwire-bus.ko"
inst drivers/soundwire/soundwire-qcom.ko     "$KDIR/drivers/soundwire/soundwire-qcom.ko"
inst drivers/mfd/wcd934x.ko                  "$KDIR/drivers/mfd/wcd934x.ko"
inst sound/soc/codecs/snd-soc-wcd934x.ko     "$KDIR/sound/soc/codecs/snd-soc-wcd934x.ko"
inst sound/soc/codecs/snd-soc-wsa881x.ko     "$KDIR/sound/soc/codecs/snd-soc-wsa881x.ko"
inst sound/soc/qcom/qdsp6/q6adm.ko           "$KDIR/sound/soc/qcom/qdsp6/q6adm.ko"
inst sound/soc/qcom/qdsp6/q6afe.ko           "$KDIR/sound/soc/qcom/qdsp6/q6afe.ko"
inst sound/soc/qcom/qdsp6/q6afe-dai.ko       "$KDIR/sound/soc/qcom/qdsp6/q6afe-dai.ko"
inst sound/soc/qcom/qdsp6/q6routing.ko       "$KDIR/sound/soc/qcom/qdsp6/q6routing.ko"
inst sound/soc/qcom/qdsp6/q6asm.ko           "$KDIR/sound/soc/qcom/qdsp6/q6asm.ko"
inst sound/soc/qcom/qdsp6/q6asm-dai.ko       "$KDIR/sound/soc/qcom/qdsp6/q6asm-dai.ko"

# This machine has an updates/ override layer, which depmod prefers over
# kernel/. Keep it synchronized or a reboot silently reloads stale modules.
if [ -d "/lib/modules/$KVER/updates" ]; then
	inst drivers/slimbus/slimbus.ko            "/lib/modules/$KVER/updates/slimbus.ko"
	inst drivers/slimbus/slim-qcom-ngd-ctrl.ko "/lib/modules/$KVER/updates/slim-qcom-ngd-ctrl.ko"
	inst drivers/soundwire/soundwire-bus.ko    "/lib/modules/$KVER/updates/soundwire-bus.ko"
	inst drivers/soundwire/soundwire-qcom.ko   "/lib/modules/$KVER/updates/soundwire-qcom.ko"
	inst drivers/mfd/wcd934x.ko                "/lib/modules/$KVER/updates/wcd934x.ko"
	inst sound/soc/codecs/snd-soc-wcd934x.ko   "/lib/modules/$KVER/updates/snd-soc-wcd934x.ko"
	inst sound/soc/codecs/snd-soc-wsa881x.ko   "/lib/modules/$KVER/updates/snd-soc-wsa881x.ko"
	inst sound/soc/qcom/qdsp6/q6adm.ko         "/lib/modules/$KVER/updates/q6adm.ko"
	inst sound/soc/qcom/qdsp6/q6afe.ko         "/lib/modules/$KVER/updates/q6afe.ko"
	inst sound/soc/qcom/qdsp6/q6afe-dai.ko     "/lib/modules/$KVER/updates/q6afe-dai.ko"
	inst sound/soc/qcom/qdsp6/q6routing.ko     "/lib/modules/$KVER/updates/q6routing.ko"
	inst sound/soc/qcom/qdsp6/q6asm.ko         "/lib/modules/$KVER/updates/q6asm.ko"
	inst sound/soc/qcom/qdsp6/q6asm-dai.ko     "/lib/modules/$KVER/updates/q6asm-dai.ko"
fi

sudo depmod -a

echo "== installed hashes =="
sha256sum "$DTB_DST" \
	"$KDIR/drivers/slimbus/slimbus.ko" \
	"$KDIR/drivers/slimbus/slim-qcom-ngd-ctrl.ko" \
	"$KDIR/drivers/soundwire/soundwire-qcom.ko" \
	"$KDIR/drivers/mfd/wcd934x.ko" \
	"$KDIR/sound/soc/codecs/snd-soc-wcd934x.ko" \
	"$KDIR/sound/soc/codecs/snd-soc-wsa881x.ko" \
	"$KDIR/sound/soc/qcom/qdsp6/q6adm.ko" \
	"$KDIR/sound/soc/qcom/qdsp6/q6afe.ko" \
	"$KDIR/sound/soc/qcom/qdsp6/q6afe-dai.ko" \
	"$KDIR/sound/soc/qcom/qdsp6/q6routing.ko" \
	"$KDIR/sound/soc/qcom/qdsp6/q6asm.ko" \
	"$KDIR/sound/soc/qcom/qdsp6/q6asm-dai.ko"

echo "== done; use the one-time speaker-left test entry; known-good remains default =="
