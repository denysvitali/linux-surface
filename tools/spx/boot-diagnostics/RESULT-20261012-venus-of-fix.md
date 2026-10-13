boxes closed: 3 of 47; newly closed: none.

# Venus OF fix + native session polling trial

Boot6c15131e-36e5-415a-af0c-22d8a46122b2,
kernel7.3.0-rc2-spx-mainline-20261004bg+.
Candidate50af624d3d50 includes recovered native-session pollingd2485a0c6984.
Matched core/decoder/encoder compiled from recovered source; scoped autoload
barrier prevents mixing installed child ABI. No hardware constants changed.

One existing baseline H.264 fixture decode fails REQBUFS-110 in1.81s,
zero frames. Session initialization advances to state3; previous session-init
timeout no longer appears. Failure now occurs at input buffer requirements:
command0x211009 SID0, CMD0/18 MSG0/0 after firmware failure/recovery.
Firmware SFR: VIDEO.IR.1.2-00042-PROD-1 Err_Fatal,
Z:\b\venus_proc\venus\dxva\src\dxva_venus.c:1004:33394.
Unknown instance SIDff packet21001 logged; decoder session error0.
Polling delivered replies but is NOT a complete decode fix. Exact firmware
assertion cause remains unknown; queue indices after recovery do not identify
which original command triggered it.

All three candidates unloaded. Post-trial journal shows NO previous bad
of_node_put/refcount error, host WARNING or Internal error; boot ID unchanged.
OF fix passes this teardown only, not repeated-lifetime acceptance. Removed
temporary autoload policy, installed modules unchanged, device lock released.
No reboot/sound/camera/microphone capture/display reload.
Logs /var/tmp/spx-venus-of-fix-{kernel,decode}.log.

Next: offline compare session properties/buffer-requirement protocol with
known-working6.18 findings and retained vendor evidence; no unchanged retry.
D03 stays open.
