# Agent rules

## Goal and checklist

Mainline Linux on the Surface Pro X with every fitted hardware feature working.
The active implementation and regression checklist is
[`AUTO-HW-CHECKLIST.md`](AUTO-HW-CHECKLIST.md). It is generated from the runnable
catalog in `tools/spx/hw-validation`; never hand-edit its rows or tick its boxes.

| File | What it is |
|---|---|
| `AUTO-HW-CHECKLIST.md` | Automatic checks, their latest boot results and unmet dependencies. Generated. |
| `PORT-CHECKLIST.md` | Historical 47 full acceptance boxes, including physical checks. Not the automatic work queue. |
| `TODO.md` | Current defect, next hypothesis, missing support and parked unsafe work. |
| `LOCAL-PROGRESS.md` | Short local log, newest result first. |
| `tools/spx/boot-diagnostics/RESULT-*.md` | One page per trial, linking its hardware-validation report. |
| `tools/spx/hw-validation/README.md` | Canonical validator, catalog, commands and result semantics. |
| `.claude/skills/spx-*/SKILL.md` | Port, blocker, trial, voluntary human checks and status playbooks. |

Read `TODO.md`, `AUTO-HW-CHECKLIST.md` and the newest `LOCAL-PROGRESS.md`
entry before starting work. Run `tools/spx/progress` for both automatic results
and the historical full acceptance count. Builds, commits and enumerated nodes
are not working hardware. A missing tool is not a missing driver; a loaded
driver is not a working feature.

## Automatic validation (user requested 2026-10-13)

1. **One automatic source of truth.** Use `tools/spx/hw-validation`. Consolidate
   earlier automatic suites into it; do not maintain a second catalog, copied
   checklist or handwritten completion totals. The sibling `../validation`
   app is only for voluntary human checks. The duplicate `../hw-validation`
   suite is retired; preserve earlier reports as history, not active evidence.
2. **Run after every boot.** This includes baseline, trial and recovery boots.
   The persistent boot hook must record a report under
   `/var/lib/spx-boot-diagnostics/boots/<boot-id>/hw-validation/`. Check it before
   interpreting a trial or choosing the next experiment. If validation could
   not start, record why and rerun when the prerequisite is available. Do not
   silently skip a boot or use a previous boot's report as its result.
3. **Test all safely automatic hardware.** Include real Wi-Fi and Bluetooth
   scans, display/GL/Vulkan, hardware video decode and encode applicability,
   audio, cameras, cellular/GNSS, USB/Type-C, input driver health, sensors,
   CPU/memory/storage, firmware, security and power interfaces. A feature with
   missing support or a fixture remains in the generated catalog as blocked.
   Where enumeration is all that is implemented, label it inventory and keep
   the functional requirement open. Hardware acceleration must reject software
   fallback. Supported formats and encode are separate from one H264 pass.
4. **Record honest results.** Reports contain boot ID, kernel release, time,
   check ID, precise tested scope, result and reason/evidence. Only a successful
   functional check is ticked. Inventory is `observed`; unmet prerequisites or
   known unsafe paths are `blocked`; proven failures are `fail`; unexpected
   runner problems are `error`. Never count those as passes. Generate the
   checklist from the catalog and results, including failed and blocked rows.
   These results do not close a historical full acceptance box automatically.
5. **Manual tests are excluded.** No typing, touching, pen drawing, cable swaps,
   listening, visual judgement, charger unplugging or physical wake is a
   requirement in the automatic checklist. Do not ask for those during porting
   or substitute synthetic physical events. Keep voluntary physical checks in
   `../validation` and `PHYSICAL-TESTS.md`; a human runs them when they want.
6. **Safety still applies.** Scans and small disposable-file checks may run
   automatically. Do not disconnect the live network, toggle radios, change
   firewall policy, modeset/unbind MSM, load parked accelerators, run the
   fault-producing encoder, suspend/reboot or run battery/endurance tests from
   the validator. Camera/microphone capture needs an announced explicit opt-in;
   discard raw private data. This broad validation request does not lift the
   specific parked encoder, speaker/amplifier or DSP-lifecycle restrictions.
   Record blocked coverage instead of attempting a known unsafe test.
7. **Fix one real defect at a time.** Mandatory regression validation is an
   exception to the old prohibition on rechecking passing features, not a
   reason to invent new test variants. Use the generated failures and existing
   findings to identify missing kernel/DT/userspace support. Keep one explicit
   current defect and one item per testable hypothesis in `TODO.md`; do not
   create TODOs for collection, staging or bookkeeping. Do not select an easier
   feature to manufacture progress. Follow `spx-blocker`.
8. **Reuse known findings.** The 6.18 tree in `../linux-surface-kernel` has
   working audio, camera and display. Port those instead of re-deriving them.
   Read the feature entries in
   `~/.claude/projects/-home-dvitali-Documents-git-linux-surface-kernel/memory/MEMORY.md`.
   Record whether a gap is missing support, an observed defect, a dependency or
   a safety restriction; do not conflate these.
9. **Commit real changes; keep overhead small.** One commit per feature/fix on
   `spx/next`, honestly marked working, WIP or not working. Never leave kernel
   changes uncommitted across a boot. No bookkeeping-only commits, manifests,
   tree copies or repeated hash reviews. A boot needs the verified default,
   one-shot selection, automatic return, logs and hardware validation. Follow
   `spx-trial`; results stay one page and link the detailed generated report.
10. **Stop honestly.** If no untested, safe hypothesis or available prerequisite
    remains, report the concrete block and stop. An open-ended goal does not
    authorize unsafe tests or endless scaffolding. Reports start with
    `boxes closed: N of 47; newly closed: IDs/none` for the historical count,
    then automatic functional pass/total and blocked/fail/error coverage. Do
    not present inventory or test-code coverage as completed hardware support.

## Build and device

- **Reload modules instead of rebooting.** Venus, spi-hid, the WSA/SoundWire
  codecs and the camera drivers are modules: rebuild the one module and
  `rmmod`/`modprobe` it. Reboot only for built-in code, DTB or initramfs
  changes. Never unload MSM display modules.
- **One kernel release name and one build directory** for the whole port,
  built incrementally. Do not copy, tar or rehash the source tree.
- **One trial tool:** `tools/spx/trial.py` with the attempt ID. No new
  per-attempt scripts or systemd units.
- **Clean up after a trial:** remove its `/boot/spx-trial-*` directory, module
  tree and units once the result is collected. Keep only the current candidate
  and known-good.

## Agents

One coordinator owns the checklist, the build directory, the device and every
reboot. It may spawn agents for bounded work (`spx-port`).

- Roles: a researcher (read-only brief on one feature), a porter (patch in its
  own git worktree, commits on `spx/wip/<feature>`), a device tester (one
  functional test on the live hardware). Definitions are in `.claude/agents/`.
- Research and patch writing may run in parallel for independent parts of the
  current work. The user requested ten agents for the validation/guidance
  rework on 2026-10-13; they do not share device or build access. For ordinary
  kernel porting use at most four offline agents unless the user says otherwise.
- The device and the build directory are exclusive. Take the lock first:
  `tools/spx/spx-lock acquire device|build <owner>`; release it afterwards;
  check with `tools/spx/spx-lock status`. A reboot clears the locks.
- Only the coordinator builds, integrates, ticks boxes and reboots.
- No review agents: none that review manifests, re-hash artifacts or verify
  another agent's bookkeeping.

## Sound and capture

- Do not play sound or power the speaker amplifiers unless the user asked for
  that run. Do not capture camera or microphone data without saying so.
- **Acoustic feedback loop (authorized 2026-10-04).** The user said: "You need
  to build a feedback loop. I can't be around to tell you if it worked or not.
  Use the microphones!" Bounded speaker playback and microphone capture are
  allowed for automated audio testing. Announce capture, keep minimum PA gain
  and bounded levels and durations, and park the amplifiers on completion or
  failure. Since 2026-10-08 this is for verifying a fix to the playback reopen
  defect only (rule 4). It does not authorize unrelated sound or camera capture.
- **Night (2026-10-05).** Keep test signals at the quiet digital peak
  (1433/32768 or lower) and minimum PA gain. No louder peak-4000 run at night.
- **Battery tests are deferred** at the user's request (2026-10-05). Do not ask
  for charger unplugging or run battery load or endurance tests.

## Reboots

**2026-10-13 user authorization:** "Reboot is allowed." This supersedes the
2026-10-12 prohibition on reboot commands. Prefer module tests in place and
retain the baseline, one-shot trial and recovery rules below. This does not
restart the parked, fault-producing encoder experiments.

**2026-10-12 user stop:** Do not reboot this device anymore. This overrides
the older standing reboot authorization below. Venus/Chromium work is offline
only after repeated hangs/resets; no live browser or module trials without
new explicit user authorization. User later authorized one decoder-only
Venus/Chromium retry on 2026-10-12 after being warned it may hang/reset.
This does not authorize any reboot command or encoder test. The user then
requested continuing work to fix the remaining playback defect; bounded
Venus decoder/browser validation is allowed, with no reboot commands or encoder.

**Baseline policy (user requested 2026-10-09):** the verified 7.x candidate
is the persistent `spx-mainline` baseline. Keep 6.18 (`spx-known-good`) as a
manual recovery entry. Ordinary boots and trial returns use 7.x. Promoted
baseline boots have no automatic trial return. Do not demote the default to
6.18 without the user's instruction. This does not close B01 acceptance.

The user authorized repeated experimental boots on 2026-09-22, including boots
that may need a manual power cycle: "Yes. Proceed. Don't ask." Do not ask for
that authorization again. Automatic recovery across the EFI handoff is not
validated; a hang after ExitBootServices needs a manual power cycle
(`tools/spx/boot-diagnostics/RECOVERY.md`).

Every trial boot:

- Keep `spx-mainline` as the persistent default and select each trial once.
- Check that the baseline and recovery kernel, initramfs and DTB are intact (a hash check
  of those files is enough).
- Recheck the boot ID and any pending boot selection before every reboot. An
  interrupted reboot call may already have executed.
- Collect the result before choosing the next experiment. Never blindly re-arm
  a failed image.
- Change one variable per boot, or several independent changes that each have
  their own functional test.

Never:

- unbind or rebind live MSM display components (this froze the device);
- read `171c0000+0x2000` or the pinctrl `pinmux-pins`/`pins` debugfs files
  (both wedge the machine).
