# Surface Pro X boot diagnostics

Current rules are in [AGENTS.md](../../../AGENTS.md), current work in
[TODO.md](../../../TODO.md), and automatic coverage in
[AUTO-HW-CHECKLIST.md](../../../AUTO-HW-CHECKLIST.md). Historical physical/full
acceptance is [PORT-CHECKLIST.md](../../../PORT-CHECKLIST.md). Consult the newest
[LOCAL-PROGRESS.md](../../../LOCAL-PROGRESS.md) entry for current driver state;
old results do not describe today's installed system.

## Every boot

1. Preserve dmesg/journal, boot ID, release and pstore using the existing
   collector. Do not clear crash evidence or change boot selection.
2. Run the canonical [hardware validator](../hw-validation/README.md). The
   persistent hook applies to mainline baseline, trial and manual recovery
   boots, and records JSON/Markdown at
   `/var/lib/spx-boot-diagnostics/boots/<boot-id>/hw-validation/`.
3. Inspect that boot's result before another experiment. A missing runner,
   busy device lock, missing tools or a failed check needs an explicit recorded
   status. Rerun if validation could not complete. A report from another boot
   is never a substitute.
4. Generate the automatic checklist from the catalog and report. Functional
   success, inventory, blocked prerequisites and actual failures remain
   distinct. Do not close historical acceptance from a narrow result.

The validator never initiates suspend/reboot, changes kernel/DT/module/power
policy, disconnects live networking or retries the fault-producing encoder.
Capture requires announced opt-in; speaker/DSP and battery restrictions remain
in `AGENTS.md`. Manual tests are separate and voluntary.

## Trials and recovery

Use only `tools/spx/trial.py` and the `spx-trial` playbook. Keep the verified 7.x
`spx-mainline` as persistent default; select each trial once with its automatic
return. 6.18 `spx-known-good` remains manual recovery. Promoted baseline boots
have no automatic trial return. Do not demote the default.

Before any reboot check current boot ID, pending selection and the baseline/
recovery kernel, initramfs and DTB. Interrupted calls may already have run.
Collect results before selecting another trial; never re-arm a failed image
unchanged. EFI-handoff recovery remains unvalidated; a hang may need a manual
power cycle. See [RECOVERY.md](RECOVERY.md). Never unbind/rebind MSM or read the
unsafe MMIO/pinctrl files named in `AGENTS.md`.

A result is one page: boot/release, change, observation, hardware-validation
summary/link, meaning and next step. No manifests, preparation records or
bookkeeping-only commits. Keep only current candidate and baseline/recovery
payloads; clean obsolete trials after collection.

## History

Older reconstructions and trial reports are evidence for their recorded boot,
not current instructions. The previous long README is preserved as
[README-HISTORY-20261013.md](README-HISTORY-20261013.md); its old default,
manifest and per-attempt procedures are superseded by the current rules above.
