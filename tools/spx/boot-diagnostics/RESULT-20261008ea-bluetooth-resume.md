# EA retained active Bluetooth discovery passes — N02c closed

**Change:** bcf927690d70 retains one scanner;1329041a26fa preserves immediate
Bluetooth proof while applying existing native WLAN grace after stop/reap.
Actual boot `701bb5d8-e4b3-4ac1-85cb-e8eea4ea2c31`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`; no kernel/build/reboot/audio change.

**Observed:** scannerPID7235/startticks/stdin/stdout pipes identical across
29.4476s normal AC sleep. RTC IRQ4->5/event416/alarmoff, kernel/service/thaw
proof passes. One scan-on only;15 pre-sleep peers,3 post-drain peers with2 NEW
and1 RSSI events in5s.781 queued bytes discarded to EAGAIN, partial frame and
private peer sets cleared. Reports are freshly delivered after drain; actual
transmission timestamps are unproven. Same controller/policy/rfkill/BlueZ/WLAN
UUID; no interval power/rfkill/reset/module/restart repair. Whole87.307s.

**Cleanup:** one scan-off, scanner stopped/reaped before infrastructure checks;
original off-blocked/soft1 preference restored. Native WLAN recovers within
bounded observation,1MB transfer, same motion providers/three streams and64KiB
fsync/readback pass. Masks/alarm/inhibitor/PCMs closed/amps parked/FIFO0/PMauto
restore; all final gates pass. Private evidence:
functional/20261008ea/bluetooth-discovery-resume/result.json and journals.

**Meaning:** N02c closes for one retained discovery client and one normal AC
sleep. Pairing/data/peripheral reconnect, repeated active-client reliability,
intermittent UART cause and full N02 remain open. First WLAN-ordering failure
is preserved in RESULT-20261008ea-bluetooth-fixture.md; default microphone
sleep remains parked in RESULT-20261008ea.md. No playback/capture in this run.
