# AM one-time SPI-HID lifecycle trial, prepared 2026-10-02

User authorized proceeding after preserving the exact working boot and pruning
older installed combinations. Recovery remains6.18.3-1-surface+, kernel slimfix,
original initramfs and .dtb.wsa; spx-known-good stays persistent default. All5183
working module files/links and EFI loader payloads are preserved. Only AM is newly
installed beside it; no historical trial slot or module version was restored.

AM attempt20261001am uses distinct7.3.0-rc2-spx-mainline-20261001am+ release,
187 modules/202 installed files,54 private initramfs module payloads, original
corrected DTB5adbda17.... See BUILD-20261001am.md for full source/config/payload
hashes and lifecycle tests. Full1354-file/272-link build archive remains immutable.
Only SPI-HID core/header and LOCALVERSION differ from AL/AK build baseline.
AM command line is exact AK pin2/native0/enum_diag1/cmd_diag1/startup_diag1 reference
with just the attempt marker changed. No playback/PCM/capture/input event tests.

Deployment preparation uses the current boot-prune snapshot to pin the three
recovery artifacts, entire working module tree, exact recovery menu and EFI files.
Historical AL/AK installed paths are not required. working-recovery.json's digest
is pinned in attempt.json. The runtime shared guard checks actual boot ID/cmdline,
recovery/module/EFI integrity, persistent default, EFI BootNext and pending entry.
The default source40_custom is unchanged; standard41_custom execution is restored
so its compiled loader reads AM's custom.cfg. Global preload remains working.wsa.
GRUB syntax and recovery-entry byte identity are checked before installing menu.

AM finalizer and independent result reviewer are exact identity substitutions of
AK. Strict graphics/Wi-Fi/touch readiness, native/error/topology/DT identity/GPIO,
soundcard/taint and bounded diagnostic criteria stay intact. The finalizer runs
at620s, archives and hash-checks results, and stops fallback only if criteria pass.
At900s, AM's fallback guard confirms actual AM boot/release/cmdline and viable
known-good payloads/modules/menu/EFI before invoking the shared collector/return
path, which rechecks boot ID/pending selection immediately before reboot. Ordinary
600s return explicitly excludes AM; the short return is suppressed by the same
inherited600-window selector. Timer service timeout180s leaves fallback time.

Actual extracted guard tests:2 preboot positive/9 negative cases,1 fallback
positive/8 negative cases; wrong boot/release/cmdline, young age, active timer,
conflicting selection, wrong exclusion, bad artifacts/recovery, existing fallback
marker and late boot-ID change rejected.6 strict scope negatives pass. These mock
checks are not hardware recovery proof. Native Happy continuation is confirmed
running for the same thread, resumeOnDaemonStart=true with message continue;
whitelisted fields only stored. No retired custom resume helper is re-armed.

Before selecting, archive actual known-good collector/boot/cmdline/GRUB/EFI state,
deployment sources, runtime hashes, config and payloads. The queue creates an
exclusive request marker, selects only spx-trial-20261001am once, checks selection
and boot ID again, and schedules an immediate guard in30s. The guard rehashes
recovery and trial artifacts and verifies pending selection before requesting
reboot. Failure clears its own selection and retains markers for inspection; do
not blind-retry. No second attempt is queued.

After reboot: read actual boot ID/release/cmdline and collect results before any
next experiment. Expect final-result around620s. If AM fails or finalization fails,
leave900s fallback armed; verify actual known-good return and archive pstore/journal
before reassessment. Firstincomingfromknown-good cannot test the new candidate's
outgoing shutdown callback. Only an actual AM pass and fresh review permit a
proposed same-artifact AN direct handoff, never ahead of result. Shutdown markers
can be later than journald; missing pstore markers leave execution/retention
unverified. Complete marker proves helper return, not electrical rail-off.
AL startup failure remains unresolved, and early EFI recovery remains unvalidated.

Authoritative status is installed-review.json/queue-review.json/reboot-check-passed.json,
attempt.json and actual current boot identity, not this prospective run description.
