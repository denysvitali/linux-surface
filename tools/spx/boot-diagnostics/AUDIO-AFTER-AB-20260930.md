# Next boundary: attachment without the forced worker

AB matched2110/unique3 to left firmware and initialized that codec before the
forced worker. Its complete620s matching/baseline result passed. This permits
a narrower native-attachment trial rather than inventing another DT identity
or physical device number.

AC reuses exact AB DTB and AA kernel/modules/initramfs/config, retaining all
GPIO/transport/DAC/diagnostic selectors. Change only the attempt marker and
soundwire_qcom.spx_force_attach=1 to0. spx_core_enum, exact_windows_init and
watchdog remain defaultoff. No PCM, playback, capture, GPIO change, extra
physical address assignment or device rebind is scheduled.

On this fresh boot the global forced flag startsfalse. With core_enum=0 and
force_attach=0, probe does not schedule the legacy enum worker. Native hardware
status/enum IRQ handling remains enabled. The forced status override, duplicate
right logical assignment, terminal IRQ masking, forced dev0 write rewrite,
blind FIFO mode and forced controller PM reference no longer run. These are
consequences of the one selector change. The codec's enumerated-mode shadow
read-modify-write behavior remains active, so this is not an ordinary regmap
read or acoustic test.

Require the bounded existing-read trace to repeat2110/unique3 with pendingforce0
and forced0; exactly two DT-backed codecs; left Attached/1; GPIO software state;
controller/DSP/card/graphics/Wi-Fi/touch baseline; taint0; no selected faults,
WSA FIFO/init/status errors or native bus/clock-stop errors. Worker entries and
force-attach markers must be absent, and runtime force/core/watchdog parameters
must be0. Preserve a read-only runtime-PM snapshot, including unsupported-field
errors, and trace/init/IRQ evidence. More than one native init is observational
and must not be mistaken for verified bus stability.

Collect at620s, archive/hash before any fallback stop; failed scope keeps900s
return armed. Keep known-good default, one selection, verify bootID/selection
and hashes before reboot. A userspace fallback does not validate EFI handoff
recovery. Inspect the result before another experiment. Native status and
submitted writes alone cannot establish physical readback, idle-resume success,
working data ports, acoustic output or the right speaker's actual identity.
