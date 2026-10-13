---
name: spx-trial
description: Run a Surface Pro X trial using trial.py, validate all safely automatic hardware after boot and record its report.
---

# SPX trial boot

Prefer a module reload when possible. A boot changes one variable, or several
independent changes with separate functional checks.

## Before

1. Write the hypothesis, change and expected observation. Commit kernel changes
   on `spx/next` (WIP is fine).
2. Acquire build/device locks. Build incrementally in the one build directory
   with the one release name.
3. Check baseline and recovery kernel/initramfs/DTB hashes. Recheck current boot
   ID and pending selection before every reboot; interrupted calls may already
   have executed.
4. Ensure the persistent automatic hardware-validation boot hook and canonical
   runner are installed. It applies to baseline, trial and recovery boots.
   Rebuild/reinstall the binary after validator changes. Before choosing another
   trial or promoting a candidate, verify the current boot's complete report:

       sudo python3 -B tools/spx/boot-diagnostics/automatic-validation.py verify

   `trial.py boot` and `promote` enforce this check. A report with hardware
   failures still permits a corrective trial; missing/fixture/older-boot or
   incomplete evidence must be resolved first. Recovery return records the
   report and runner paths/status without waiting indefinitely for validation.

## Run

Use the single tool; options are in `tools/spx/README.md`:

    sudo python3 -B tools/spx/trial.py prepare <attempt> [flags]
    sudo python3 -B tools/spx/trial.py install <attempt>
    sudo python3 -B tools/spx/trial.py boot <attempt>

`spx-mainline` (7.x) remains the persistent default. Select the trial once and
retain its bounded automatic return. `spx-known-good` (6.18) is manual recovery,
not the ordinary default. Promoted baseline boots have no trial return.
Reboot authorization and restrictions are in `AGENTS.md`; do not create new
per-attempt scripts or units.

## After

1. Collect `/var/lib/spx-boot-diagnostics/functional/<attempt>` and this boot's
   `/var/lib/spx-boot-diagnostics/boots/<boot-id>/hw-validation/` result. Run the
   full canonical automatic suite if absent/incomplete; report missing tools,
   busy locks or failures explicitly. Never substitute a previous boot report.
2. Generate `AUTO-HW-CHECKLIST.md` from catalog/results. Wi-Fi/BT scans, graphics,
   storage and every other safe automatic check must be represented. Parked or
   permission-gated tests remain blocked, never silently skipped or passed.
3. Write one page `RESULT-<attempt>.md`: boot ID, release, what changed, observed
   outcome, automatic pass/fail/blocked/error summary and report link, meaning
   and next hypothesis. No manifests or hash/file-count narration.
4. Add at most five lines to `LOCAL-PROGRESS.md`, update the hypothesis in TODO,
   clean obsolete trial payload/module tree/units and release locks. Keep only
   current candidate and baseline/recovery. Do not re-arm a failed image unchanged.

Manual observations are voluntary and excluded from the automatic checklist.
No bookkeeping-only commits; include results with the feature/fix commit.
