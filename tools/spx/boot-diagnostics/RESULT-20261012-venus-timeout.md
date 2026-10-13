boxes closed: 3 of 47; newly closed: none.

# Venus session timeout localized

Boot b9c406c9-df8d-4609-9aac-23682d85d911,
7.3.0-rc2-spx-mainline-20261004bg+. Diagnostic WIP3fd103055904
built coherent core/decoder/encoder with no compiler/link diagnostics.
One existing H.264 fixture trial; scoped child-autoload barrier, no old ABI.

Startup confirms VIDEO_VAR cp0/0x25800000 nonpixel0x01000000/0x24800000
SCM success. Core starts, decoder/encoder register. Decode fails REQBUFS
in1.40s, zero frames. Timeout is session-init command0x10007, SID0,
state2; CMD queue read/write33/33, MSG queue637/643, cached IRQ0x4.
Firmware consumed the command and six message words remain unread. This
supports queued-response/missing IRQ handling, not an unconsumed command.
Message type/content are not yet proven; no claim of valid session response.

All three candidates unload cleanly; temporary autoload policy removed,
installed modules unchanged and locks released. No reboot/sound/capture,
MSM reload/suspend or new hardware numeric constants. Logs:
/var/tmp/spx-venus-timeout-{kernel,decode}.log.

Next hypothesis: serializing native parser draining with IRQ thread during
existing Iris1 completion wait delivers queued response without resending,
changing SID or extending deadline. Porter implementing bounded WIP;
then same baseline decode once. D03 remains open.
