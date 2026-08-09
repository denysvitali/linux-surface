#!/bin/bash
# Post-reboot diagnostic: did the WSA881x enumerate via the APPS soundwire path?
set +e
echo "===== 1. card + soundwire bus ====="
cat /proc/asound/cards 2>/dev/null | grep sdm845
echo "--- /sys/bus/soundwire/devices (THE KEY CHECK) ---"
ls -l /sys/bus/soundwire/devices/ 2>/dev/null
echo "--- sdw device status + dev_num ---"
for d in /sys/bus/soundwire/devices/*; do
  [ -e "$d" ] || continue
  echo "  $(basename $d): status=$(cat $d/status 2>/dev/null) dev_num=$(cat $d/dev_num 2>/dev/null) mfg=$(cat $d/mfg_id 2>/dev/null) part=$(cat $d/part_id 2>/dev/null)"
done

echo; echo "===== 2. codec SWR clock gate + master state (read over SLIMbus) ====="
RM=/sys/kernel/debug/regmap/217:250:1:0
echo "  WCD934X_CDC_CLK_RST_CTRL_SWR_CONTROL (0x0d43) [BIT0 must be 1 if swm probed]:"
sudo cat "$RM/registers" 2>/dev/null | grep -E "^0d4[1-6]"
echo "  --- SWR master block @0xc85 (COMP_STATUS=0xc99, MCP/ENUM/SLV_STATUS later) ---"
sudo cat "$RM/registers" 2>/dev/null | awk '/^0c8[5-9a-f]/||/^0c9[0-9a-f]/||/^0ca[0-9a-f]/' | head -32

echo; echo "===== 3. soundwire-qcom driver + enumeration events in dmesg ====="
sudo dmesg 2>/dev/null | grep -iE "soundwire|swrm|wsa881|sdw:|qcom_swrm|spx_poll|auto enumeration|SLAVE_ATTACH|UNATTACH|ATTACH" | tail -25

echo; echo "===== 4. wcdgpio powerdown state (are amps powered?) ====="
sudo gpioinfo 2>/dev/null | grep -iE "powerdown|wcd" | head
echo "  --- gpio line consumer 'powerdown' ---"
for chip in /sys/class/gpiochip*/; do :; done
sudo find /sys/kernel/debug/gpio -maxdepth 0 2>/dev/null && sudo cat /sys/kernel/debug/gpio 2>/dev/null | grep -iE "wcd|powerdown|sd_n|shutdown" | head
