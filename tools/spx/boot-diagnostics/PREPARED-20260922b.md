# SPX graphical comparison — 2026-09-22

**Result: failed graphical trial.** GNOME started, then the GPU frequency-vote
path timed out and the GMU watchdog expired. The bounded return did not run.
See [RESULT-20260922b.md](RESULT-20260922b.md) for archived evidence, boot IDs
and the next comparison. The preparation description below is historical.

Trial `20260922b` reuses the exact kernel, modules, DTB and initramfs from
the [successful text-target trial](RESULT-20260922a.md). The command line
changes `systemd.unit=multi-user.target` to `systemd.unit=graphical.target`
and changes the identifying marker to `spx_attempt=20260922b`. GDM is enabled
and configured to log in the existing desktop user automatically.

The release remains `7.3.0-rc2-spx-mainline-20260922a+`. Artifact paths and
hashes are unchanged; see [the original build record](PREPARED-20260922a.md).
The new CMAC board-fragment setting is for a subsequent build and is not
included in this experiment.

The attempt archive is
`/var/lib/spx-boot-diagnostics/attempts/20260922b/`. Its manifest references
the complete immutable parent build archive and records the shared installed
artifact hashes. It also preserves the preceding boot configuration, parent
result, authorization, new entry and preflight state. Do not interpret this
preparation record as evidence that a boot succeeded: inspect `attempt.json`,
`reboot-requested` and the actual boot logs.

Preboot recovery ID is `6def46d6-0373-4d53-b9c2-55458510b530`. The persistent
default remains `spx-known-good`; select this trial once. The APSS watchdog,
initramfs logger, early host snapshots and 180-second return timer remain.
Automatic recovery across EFI handoff is still unvalidated, covered by the
user's explicit acceptance of possible manual power cycling.

Collect the graphical boot's full journal, early snapshots, initramfs logs,
pstore and recovery journal before selecting a further experiment. Check
whether GDM and GNOME started, whether the return timer completed, and whether
GPU faults or the earlier loss of progress recurred. No live MSM unbind/rebind.
