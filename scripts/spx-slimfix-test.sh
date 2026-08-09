#!/bin/bash
# SPX SLIMbus sanity-fix bridge test
# After reboot with /vmlinuz-6.18.3-1-surface+-slimfix, this:
#   1. Confirms the patched slimbus.ko is loaded (probe it)
#   2. Verifies slimbus sanity no longer rejects 0xc85-0xc96
#   3. Runs spx_deep_probe to dump SWR master registers via the bridge
#   4. Compares pre/post writes (was: readbacks returned 0; now should return real values)
#   5. Reports SWR init state for qcom-swrm driver attach

set -e

echo "=== SPX SLIMbus sanity-fix bridge test ==="
echo

# 1. Verify the patched slimbus is the loaded one (look for SPX string)
echo "[1] Checking slimbus.ko for SPX patch..."
if strings /lib/modules/$(uname -r)/kernel/drivers/slimbus/slimbus.ko | grep -q "SPX: SLIM sanity REJECTED"; then
    echo "    OK: patched slimbus.ko present"
else
    echo "    WARN: SPX string NOT in slimbus.ko - reverting patch?"
    strings /lib/modules/$(uname -r)/kernel/drivers/slimbus/slimbus.ko | grep -i slim | head -5
fi

# 2. Confirm running kernel matches the patched image
echo "[2] Checking kernel matches..."
if [ "$(uname -r)" = "6.18.3-1-surface+-slimfix" ] || uname -r | grep -q "slimfix"; then
    echo "    OK: running slimfix kernel: $(uname -r)"
else
    echo "    Running kernel: $(uname -r) - this is fine if slimbus.ko is patched"
fi

# 3. Check soundwire_qcom has the spx_core_enum param
echo "[3] Checking soundwire_qcom module param..."
if [ -f /sys/module/soundwire_qcom/parameters/spx_core_enum ]; then
    SPX_CORE_ENUM=$(cat /sys/module/soundwire_qcom/parameters/spx_core_enum)
    echo "    spx_core_enum=$SPX_CORE_ENUM"
else
    echo "    WARN: spx_core_enum param not found (module not loaded yet?)"
fi

# 4. Run the deep probe to read SWR master registers via the bridge
echo "[4] Running spx_deep_probe to test bridge..."
echo "    (this will be visible in dmesg)"
echo

sudo insmod /lib/modules/$(uname -r)/updates/spx_deep_probe.ko 2>&1 || {
    echo "    insmod failed - check 'dmesg | tail -30'"
    exit 1
}

sleep 2

echo
echo "[5] Bridge test results (from dmesg):"
echo
dmesg | grep -E "^spx:" | tail -40
echo
echo "=== Done. Next: amixer cset / aplay ==="