#!/bin/bash
# One line of power/thermal context for SPX speaker measurements.
#
# PROGRESS §39 rule (2026-08-23): a listening run without a power record is
# void — the silence gate is suspected to be supply state (every attended
# silent run sat on discharging battery <50%, every audible run on the mains
# 47–50% hold), so every phase marker must carry one of these lines.
#
# Pure sysfs reads; never touches audio state. Writes to the journal via
# `logger -t spx-power` AND prints the same line on stdout so run logs
# capture their own context inline.
#
# Usage: scripts/spx-power-snapshot.sh [tag]

read1() { cat "$1" 2>/dev/null || echo '?'; }

ADP=$(read1 /sys/class/power_supply/ADP1/online)
BST=$(read1 /sys/class/power_supply/BAT1/status)
BCAP=$(read1 /sys/class/power_supply/BAT1/capacity)
BV=$(read1 /sys/class/power_supply/BAT1/voltage_now)
BI=$(read1 /sys/class/power_supply/BAT1/current_now)
BP=$(read1 /sys/class/power_supply/BAT1/power_now)
# Real PMIC ADC of the system rail (regulator.2's sysfs stub lies). The
# WSA881x boost starts at >= 3.00 V; this machine rests ~3.38 V.
# 2026-08-23: iio:deviceN is enumeration-order dependent (a plugged apds9960
# can take slot 0), so resolve the PMIC ADC by its channel name instead.
VPH='?'
for iio in /sys/bus/iio/devices/iio:device*; do
	[[ -e $iio/in_voltage_vph_pwr_input ]] || continue
	VPH=$(read1 "$iio/in_voltage_vph_pwr_input")
	break
done
BOB_ST=$(read1 /sys/class/regulator/regulator.10/state)

TEMPS=
for tzdir in /sys/class/thermal/thermal_zone*; do
	[[ -d $tzdir ]] || continue
	TV=$(read1 "$tzdir/temp")
	TT=$(cat "$tzdir/type" 2>/dev/null | tr ' -' '__')
	[[ $TV == '?' ]] && TV=$(read1 "$tzdir")
	TEMPS+=" ${TT}=${TV}mC"
done

LINE="tag=${1:-manual} adp=$ADP bat=$BST/$BCAP% V=${BV}uV I=${BI}uA P=${BP}uW vph=${VPH}uV bob=$BOB_ST$TEMPS up=$(cut -d ' ' -f1 /proc/uptime)"
logger -t spx-power "$LINE" 2>/dev/null || true
echo "$LINE"
