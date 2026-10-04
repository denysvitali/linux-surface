# S: first SLIM controller registration boot

R's 620.99-second archived result independently verified a clean PIO runtime
resume to AWAKE and capability exchange. S reuses R's exact kernel, DTB,
initramfs and module tree. Only the attempt marker and NGD boot selectors
change: `spx_stage8_step=1` becomes `2`, and `spx_allow_full=1` is added.
Stage 8 step 2 follows the same runtime resume path and then calls
`slim_register_controller()`.

Registration synchronously creates the two SLIM devices described by the
WCD9340 DT include. Their probes can issue logical-address queries and start
codec work, so S is a new hardware boundary. The scoped success criterion is
one `SLIM controller Registered` marker, two enumerated SLIM devices, and a
healthy graphical/Wi-Fi/touch baseline with no selected kernel fault. A
soundcard, codec bind, SoundWire devices and playback are separate outcomes
to record, not prerequisites for the registration result.

Use a separate S archive, one-shot GRUB entry, 620-second result collector,
900-second fallback and exact hash checks. Keep `spx-known-good` persistent;
the R payload path may be reused only after its hash-verified success.
Never live-unbind/rebind MSM or SLIM devices. An early hang can still require
manual power cycling under the user's existing authorization.
