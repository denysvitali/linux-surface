# AO exact-AM handoff, prepared 2026-10-02

AO follows AN's verified preboot abort (see RESULT-20261002an.md). The current
AM boot is still `6dfad462-25b7-4e5e-90fc-3bd18c1c3095`; its archived 620.68-second
pass and post-result evidence remain exact. AO tests the same direct handoff
using release `7.3.0-rc2-spx-mainline-20261001am+`. The kernel, 202 module files,
DTB, private initramfs, source/config, pin2 and native-attachment selectors are
unchanged. Only the kernel attempt marker changes to `20261002ao`.

The source guard now gives Git command-local trust for this exact repository,
retaining the byte-exact archived diff check. Full `preboot()` passed under a
real systemd service with no SUDO_UID, including boot identity, parent pass,
live baseline, artifacts, recovery and pending-selection checks. Its report is
`service-context-review.json`; freeze requires this service's successful result.

Install review verified 1,354 build files, 272 symlinks, 202 installed module
files, 17 payload/recovery/runtime hashes and all 5,183 working module files and
links. Known-good entry, EFI loaders and three recovery payloads are unchanged.
The collector/reviewer are exact AM identity transformations; 12 strict scope
expressions and six negative scope cases are unchanged. Actual guard extraction
passes two positive/11 negative preboot and one positive/eight negative fallback
cases. GRUB and systemd unit validation pass. Timers remain 620/900 seconds,
enabled but inactive on AM. The generic 600-second return excludes AO.

The 223-file outgoing snapshot manifest is
`4574d7891b2e84893a708f0aee4628db3efb6262ab2ec08358888e9f18a62669`.
Ten deployment sources are frozen under manifest
`5ae98625c3000deab957f9eac32f2e897a1f3074e6744345915c9aa4763cf8d6`.
Native Happy continuation was verified for host PID 272148, current Codex thread
`01a0fb73-77a8-7152-9fdf-545691026ee3`, daemon-started/running,
resumeOnDaemonStart=true and prompt `continue`. No legacy resume marker exists.

Selection uses an exclusive AO request and a 30-second immediate guard, which
rechecks boot ID, pending/default selection and all protected artifacts before
reboot. Actual `queue-review.json` and `reboot-check-passed.json` are authoritative;
this preparation record does not assert that AO has booted. AN remains archived
and unselected. Persistent default remains `spx-known-good`.

On continuation, inspect actual boot ID/cmdline first. If AO booted, run
`sudo -n python3 tools/spx/boot-diagnostics/review-ao-handoff.py` early to freeze
pstore against the outgoing baseline. Callback software completion requires a
fresh retained console containing the exact outgoing AM identity, then shutdown
begin and complete in order. Absence leaves execution/persistence unverified;
completion does not prove electrical rail-off or startup reliability.

Collect the 620-second AO result and run `review-ao-result.py` before choosing
another experiment. Failed AO leaves the 900-second return armed; confirm the
actual known-good return and preserve evidence. Never blindly re-arm. No manual
PCM/audio/input or live reset/rebind. EFI/early-kernel recovery remains unvalidated.
