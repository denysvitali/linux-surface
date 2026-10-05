# Battery telemetry reference; mainline measurement deferred

Recovery boot `403ca502-ca68-47b8-88be-926a175708e5`, kernel
`6.18.3-1-surface+`. P02 remains open; no acceptance box closed.

**Observed:** 16 read-only samples over approximately 30 seconds report mains
offline, Discharging and 14% battery. Reported power spans 3.574–4.769 W,
median 4.2985 W; energy falls from 4.24 to 4.21 Wh. Desktop activity was
uncontrolled. This is a recovery reference, not a mainline idle measurement or
a controlled comparison. No workload, sound, capture, sleep or reboot occurred.
Numeric evidence is in
`/var/lib/spx-boot-diagnostics/functional/20261005powerbaseline/baseline.json`.
The device lock was released afterward.

**Prepared:** a bounded `trial.py power-measure` command for an already-running
mainline trial records idle/load/recovery battery power and energy, CPU
frequencies and temperatures. It requires battery discharge and at least 20%
charge throughout, preserves power policy, and reaps its modest CPU workers on
failure. A read-only call to its telemetry guard rejects the actual 14% battery
before workload startup. Offline checks do not establish a hardware
power-management pass. All 31 trial-helper tests pass, including low-charge
refusal, worker cleanup on failure and successful three-phase summaries.

**Next:** recharge, then run the measurement on mainline with sufficient return
timer headroom. Keep display brightness and desktop activity comparable for a
later recovery comparison. Do not run it at the current 14% charge.

The read-only audio comparison found keep-ASM and keep-COPP already ported;
the known 6.18 acoustic pass kept one PCM open and supplies no reopen fix.
Camera receiver analog ownership and SSAM wake callback contracts remain
unresolved. No unchanged audio/camera/suspend trial was repeated.
