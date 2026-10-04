# Audio boundary after Q

Q completed the stage-7 PIO capability waiter while the SLIM controller
remained unregistered. The next existing selector, probe stage 8, is a much
larger boundary than step 7. It requires `spx_allow_full=1` and PIO or DMA.
The child probe then runs runtime resume and `slim_register_controller()`.
With the current state DOWN, runtime resume can call the full NGD power-up
path, including QMI and controller setup, rather than simply retaining Q's
staged state. Registration can enumerate child SLIM devices and trigger codec
drivers. These effects are not covered by Q's result.

Before a stage-8 boot, review that path and its failure/teardown handling as
a new source change. Add a bounded stage-8 step that stops before controller
registration and records the runtime-resume state and exact extra MMIO/QMI
work. Require an explicit success/failure return rather than accepting an
outer probe success after an inner error. Check the still-open PIO thread,
worker, QMI, runtime PM and SSR/remove ordering before permitting codec
registration. A distinct build and archive are required for any new source
change; preserve Q's exact result and known-good recovery hashes.

No stage-8 hardware selection is made by this document. The Q capability
result alone is not evidence of a soundcard or functional audio.
