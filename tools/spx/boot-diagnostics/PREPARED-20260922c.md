# SPX graphical GPU-policy comparison — 2026-09-22

**Result: GPU/GMU failure reproduced.** The snapshot confirmed
`simple_ondemand`, and the custom GPU writes were absent. See
[RESULT-20260922c.md](RESULT-20260922c.md) for the failure timeline, power-state
confounder, archived evidence and next source correction. The preparation
description below is historical.

Trial `20260922c` follows the [GMU failure in B](RESULT-20260922b.md).
It retains the same kernel/modules/DTB/initramfs and graphical target, changing
the attempt marker and adding `spx_gpu_profile=skip` to the command line.

That marker skips the custom `gpu-freq.service` through a systemd condition.
It also guards only GPU sysfs writes in the user's `power-profile-watcher.sh`
and `power-profile-cycle.sh`; their power-profiles-daemon operations remain.
The driver's default governor controls frequency on this trial. Recovery boots
without the marker retain the existing custom behavior. No live GPU change
or MSM unbind/rebind was performed while preparing this experiment.

The diagnostic collector now records devfreq governor names in hardware-state
evidence. Shell syntax, the unit condition and both profile-script branches
were checked with GPU writes mocked. The CMAC kernel-config correction remains
staged for a later build; it is not part of this comparison.

Preboot recovery ID: `73b6d050-8d08-47f8-8b97-321056304df4`.
Permanent attempt archive:
`/var/lib/spx-boot-diagnostics/attempts/20260922c/`. It preserves the preceding
boot configuration, scripts and collector, their changed copies and hashes,
the new entry, authorization, parent result and continuation setup. Kernel
source/config and all binary artifacts are unchanged from the complete
`../20260922a/build/` archive and remain hash-checked through this manifest.

The persistent default is `spx-known-good`; select C once. Retain the early
logger and 180-second return timer. Inspect its actual boot result before
further changes. A successful run would implicate the frequency-policy change
as an isolation variable, without proving that removing it repairs the driver.
A failed run must be compared with B's HFI vote/GMU evidence.

The resume helper now handles Happy's documented-by-observation empty-session
text response. Twelve continuation tests pass. Actual automatic prompt
delivery is still unverified; check its service log after recovery.

C preboot power observation: AC is now online and battery charging at 42%;
B was on battery. This environmental change limits strict causal attribution
of any improvement to the GPU override guard alone. Power state is archived.
