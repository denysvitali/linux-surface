#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Raise the three Surface Pro X camera rails directly over SPMI.
#
# RPMh cannot vote these PEP-owned rails from the APPS RSC.  The transient
# helper validates the PMIC peripheral type before every write and deliberately
# returns -EAGAIN, so no helper module remains loaded.
set -eu
cd "$(dirname "$0")/.."

if [ "$(id -u)" -ne 0 ]; then
	exec sudo "$0" "$@"
fi

set_rail()
{
	rail=$1
	insmod drivers/spx_extras/spx_pmic_ldo.ko \
		sid=1 ldo="$rail" enable=1 2>/dev/null || true
}

read_rail()
{
	rail=$1
	insmod drivers/spx_extras/spx_pmic_ldo.ko \
		sid=1 ldo="$rail" dump=0 2>/dev/null || true
	dmesg | grep "spxldo: LDO${rail}_A" | tail -n 1
}

echo "== raising camera rails: LDO14_A, LDO17_A, LDO1_A =="
for rail in 14 17 1; do
	set_rail "$rail"
done

echo "== verified rail state =="
failed=
for rail in 14 17 1; do
	line=$(read_rail "$rail" || true)
	echo "$line"
	case "$line" in
		*"rail is ON"*) ;;
		*) failed=1 ;;
	esac
done

if [ -n "$failed" ]; then
	echo "!! one or more camera rails did not read back ON"
	exit 1
fi

echo "camera rails are ON"
