#!/bin/bash
# SPX: blind-write the WSA881x DP1 (speaker/PDM audio) port config over SoundWire.
# The slave's DP1 was observed unprogrammed (CHANNELEN=0, OFFSETCTRL=0) while DP2
# was fully correct. Values mirror the master's DP1_PORT_CTRL_B0 = 0x01000107:
# en_chan=0x01 offset1=0x01 SI-1=0x07. Run DURING playback.
set -u
cd "$(dirname "$0")/../drivers/spx_extras"
w() {
	sudo insmod ./spx_wsa_write.ko wsa_reg=$1 wsa_val=$2 2>/dev/null
	sudo rmmod spx_wsa_write 2>/dev/null
	printf "  wrote 0x%04x = 0x%02x (%s)\n" "$1" "$2" "$3"
}
w 0x0122 0x07 "SAMPLECTRL1_B0 (SI-1)"
w 0x0132 0x07 "SAMPLECTRL1_B1"
w 0x0124 0x01 "OFFSETCTRL1_B0"
w 0x0134 0x01 "OFFSETCTRL1_B1"
w 0x0125 0x00 "OFFSETCTRL2_B0"
w 0x0135 0x00 "OFFSETCTRL2_B1"
w 0x0102 0x00 "PORTCTRL"
w 0x0105 0x01 "PREPARECTRL ch1"
w 0x0120 0x01 "CHANNELEN_B0 ch1"
w 0x0130 0x01 "CHANNELEN_B1 ch1"
