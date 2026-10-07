# DX native Bluetooth discovery resumes — N02b closed

**Change:** a85933fbe5ac/afb742c5c340 add an owned native discovery/sleep helper.
After explicit rfkill fixture enable, observe automatic native power-up rather
than issuing a redundant power request. Existing sleep gates/unit/30s RTC alarm
and parked-audio contract remain. First fixture failure stays separately recorded.

**Observed:** boot `1c91d0d8-8b8f-41f0-b0f2-01eaffaf9fcd`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. Owned5s scans start/stop, with15 fresh
peers before and16 after one28.6273s normal systemd/login1 sleep. RTC IRQ3→4,
event416, alarm off, kernel entry/exit, same boot, service success and user thaw
prove sleep. Same controller/address/policy/rfkill/WLAN and BlueZ PID/start time
remain; no manual power/rfkill/HCI reset or module reload between scans. Kernel
has one normal QCA setup before the first scan and none after sleep. No new
UART/MSFT warning observed. End-to-end BOOTTIME89.0986s including sleep.

**Cleanup:** original Powered=false/PowerState=off-blocked/softblock1 returns;
all other radio policy/rfkill/WLAN and BlueZ identity retain. Owned scanner
reaped, same sensor providers and three motion streams, WLAN1MB and64KiB fsync
readback pass. Alarm/masks/files/inhibitor and parked-audio runtime PM restore;
all PCMs closed, amplifiers parked, FIFO0. No sound or capture during this test.
Private peer identities stay in RAM; saved evidence is aggregate counts.

**Meaning/next:** N02b closes immediately for one native discovery recovery on
AC. Pairing, peripheral data/use, reconnect, repeated reliability, intermittent
UART cause and full N02 remain open. Evidence:
functional/20261008dx/bluetooth-resume/result.json. Return/boot cleanup follows;
next grounded feature is default desktop microphone-client resume on a fresh boot.
