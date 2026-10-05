# SRTC countdown contract verified on recovery

On boot `403ca502-ca68-47b8-88be-926a175708e5`, kernel
`6.18.3-1-surface+`, the supported SSAM SRTC timer commands successfully read,
arm, count down and disable the DC timer. This is firmware-interface evidence,
not a suspend or wake pass.

**Changed:** `trial.py srtc-timer` reads both AC/DC values, refuses to overwrite
an active timer for the current power source, requests a bounded 30-second
countdown, and disables/verifies it in cleanup. The temporary cdev module is
unloaded after the test. No reboot or sleep occurred.

**Observed:** both timers initially read `4294967295` (disabled). On DC, timer1
reported 30 seconds, then 26 after four seconds. Disable/readback returned
`4294967295`; both timers were disabled afterward. The helper completed, the
cdev module unloaded, and the device lock was released.

**Meaning:** the firmware contract and bounded cleanup work through SSAM on the
recovery kernel. Expiry routing, GPIO180 wake delivery, mainline availability
and suspend/resume remain unknown. P03 stays open; this does not establish an
RTC alarm device.

**Next:** identify a supported expiry event/wake path from firmware or existing
SSAM code before any controlled suspend. Preserve the current known-good boot
policy. No audio, microphone or camera capture was performed.
