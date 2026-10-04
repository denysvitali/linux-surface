# Next boundary after AI

AI reproduced pin2 native command error despite corrected right identity and
recorded a device0 write to SPKR_DRV_GAIN. The PA gain setter currently lacks
the detached-slave check used by the boost setter. SoundWire transfers take
slave->dev_num; an unassigned slave can supply0 on the native path. The history
does not identify the actual caller or prove this request caused the IRQ error.

Next source candidate: call wsa881x_spx_slave_available in put_pa_gain and return
-ENODEV before runtime PM, gain ramp delays or register writes when detached in
SPX enumerated mode. Preserve attached and non-enumerated behavior, shadow reads,
codec cold init and routing. This narrows a concrete unsafe control path; it does
not fix touch or establish functional audio.

Freeze AI source/config/results before editing. Verify the exact C callback
against instrumented stubs, checking no PM/write/sleep for detached slaves and
identical existing ramps/errors for attached and non-enumerated callers. Compile
native codec object and archive source, harness and logs. Require a new complete
kernel/module/private-initramfs build before trial AJ; reuse exact corrected DTB,
pin2/native0/command-historyY and unchanged strict no-error/touch baseline scope.
No simultaneous pin or address/routing change. Collect actual AI fallback and
hash-check recovery before selecting the next distinct image once. No live
control/PCM/capture/input-event test or component restart/rebind is authorized
by this silent experiment. EFI/early-kernel automatic recovery remains unvalidated.
