boxes closed: 3 of 47; newly closed: none.

# External DP failure: AUX error handling corrected, crash cause still open

Previous boot `67344337-3bd0-42c6-a585-d091ac64ee36`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+ #16`, connected Surface USC DP port 0
and a ThinkPad Thunderbolt 4 Dock at 22:54:43 on 2026-10-20. The retained
journal shows repeated sink-count AUX timeouts / firmware HPD IRQ failures,
then an unexpected AUX interrupt, exhausted retries, LTTPR training failure,
and failed atomic enable at 22:56:34. Queued disconnect/connect events are
followed by frame-done, vblank and commit timeouts through 22:57:06.
No panic/oops stack survived in the journal or pstore: the precise crash
site and the original AUX failure remain unproven.

**Concrete source defect fixed (WIP, not a demonstrated panic fix):**
`msm_dp_ctrl_on_link()` ignored the return from both fallback link-status
reads. On an AUX failure it could inspect uninitialized or stale stack bytes
in `link_status` to choose lane/rate fallback and continue training. Check
both returns and leave the retry loop on error, using the existing training
pattern / mainlink teardown. This is relevant to the observed AUX failures,
but the journal does not establish that either fallback branch ran during
this incident. It does not fix or identify why AUX stopped responding.

**Offline checks:** both training-step status reads are now guarded before
status consumers; the same source-level regression assertions reject the
pre-fix source. The single `drivers/gpu/drm/msm/dp/dp_ctrl.o` target compiles
successfully in the established work-build with its current configuration.
No full module build, deployment, hardware operation or reboot performed.

**Next gate:** coordinator must complete the module build and arrange a
controlled baseline-preserving trial with current-boot automatic validation
before claiming any runtime recovery. Preserve a panic stack if another
failure occurs. Firmware ACK ordering is only a hypothesis: synchronous IRQ
processing delays the ordered USC queue, but changing ACK handling without
protocol evidence could incorrectly claim an IRQ was handled. Existing
20261010a event serialization and stream-timeout cleanup remain intact.

Current-boot automatic coverage supplied by the diagnostic investigation:
26/49 functional, 44/52 inventory, 31 blocked, 0 fail/error. Those results
predate this offline source change and do not validate it.
