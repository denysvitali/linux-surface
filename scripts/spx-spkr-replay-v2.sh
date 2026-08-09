#!/bin/bash
echo "DO NOT RUN. This recipe was proven invalid 2026-06-19 (ultrathink verification):"
echo " 1. The 0x15200 'codec register blob' is a MISREAD: all 29 CDCLUT0 dp_off"
echo "    values are OUT OF BOUNDS the DATAPOOL (offsets ~0x13252 vs pool 0x1b94)."
echo "    The decoded {reg,value} pairs do not exist."
echo " 2. The SWR master is behind an AHB BRIDGE WINDOW (codec 0xc85=WR_DATA,"
echo "    0xc89=WR_ADDR, 0xc8d=RD_ADDR, 0xc91=RD_DATA), NOT at 0xc85+offset."
echo "    Writing 0xc89/0xe89/0x1185/0x1cc9/0x1281/0x1381 = garbage into real"
echo "    codec registers, risking the working headphone path."
echo " 3. soundwire-qcom IS ALREADY the APPS-direct SWR master driver (via that"
echo "    bridge). There is no 'bypass' to build; it already fails at the wire."
echo "See scripts/spx-spkr-replay-v2.sh.BROKEN-DO-NOT-RUN for the original."
exit 1
