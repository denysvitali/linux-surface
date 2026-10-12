# Agent rules

## Goal

Mainline Linux on the Surface Pro X with every fitted hardware feature working.

| File | What it is |
|---|---|
| `PORT-CHECKLIST.md` | The 47 acceptance boxes. Frozen. |
| `TODO.md` | What to work on now, what is parked, what needs the user. |
| `LOCAL-PROGRESS.md` | Short local log, newest trial first. |
| `tools/spx/boot-diagnostics/RESULT-*.md` | One page per trial. |
| `.claude/skills/spx-*/SKILL.md` | Playbooks: `spx-port`, `spx-blocker`, `spx-trial`, `spx-human-session`, `spx-status`. Any harness may read and follow them. |

Read `TODO.md`, the checklist status table and the newest `LOCAL-PROGRESS.md`
entry before starting work.

**Progress is the number of checklist boxes closed** (`tools/spx/progress`
prints it) and features a person can use. Builds, passing diagnostics, partial
passes, TODO items, commits, boots and result files are not progress.

Two earlier processes failed and these rules exist because of them. Until
2026-10-04: 56 boots and no box closed, half the tool calls spent on hashing
and review. From 2026-10-04 to 10-08: 511 TODO items, 481 commits and about 97
reboots for one box closed (2 to 3 of 47), because the agent split boxes into
49 narrower sub-boxes, ticked 47 of those, and spent 204 TODO items on audio
tests, the one feature it could score without a person.

## Rules

1. **The checklist is frozen.** Do not add, split, rename or re-scope boxes.
   Only the user does. No lettered sub-boxes.
2. **A box closes only when its full text is met** on a real boot. Record the
   boot ID, kernel release and result file. A narrower pass is a line in the
   result file. If part of a box needs a person, it stays open until the person
   has done that part. Reopen a box if the feature regresses.
3. **One blocker at a time, in depth.** Work on the current blocker in
   `TODO.md` until its box closes or rule 5 applies. Only the user changes the
   blocker order. Follow `spx-blocker`.
4. **Do not extend what already passes.** No further tests, harness variants or
   acceptance criteria for a feature whose remaining gap is a human observation
   or a parked defect. In particular: no new audio or microphone test
   variations until the playback reopen defect is fixed.
5. **Stop when there is nothing real to do.** Stop and report when the current
   blocker has no untested hypothesis left, or needs a person, a fixture or
   information that is not available. Stopping with a one-page report is a
   correct outcome. An open-ended goal such as "continue until all hardware
   works" does not require inventing work or picking an easier feature.
6. **The human session comes first when it is pending.** Many boxes need a
   person: typing, touch, pen, buttons, USB, looking at the panel. Ask for the
   session in `TODO.md` at the start of a session and whenever the user is
   present. If the user declines, do not substitute automated stand-ins.
   Follow `spx-human-session`.
7. **Reuse known findings.** The 6.18 tree in `../linux-surface-kernel` has
   working audio, camera and display. Port those instead of re-deriving them.
   The findings index is
   `~/.claude/projects/-home-dvitali-Documents-git-linux-surface-kernel/memory/MEMORY.md`;
   read the entries for a feature before working on it.
8. **Commit as you go.** One commit per feature or fix on `spx/next`, status
   stated honestly (working, WIP, not working). Never leave kernel changes
   uncommitted across a boot. Do not make commits that only record bookkeeping.
9. **Keep overhead small.** A trial boot needs the known-good default, the
   one-shot selection, the automatic return and the dmesg/journal capture.
   No manifests, rehash reviews, preparation records or fault-injection suites.
   A result file is one page: what changed, what was observed, what it means,
   what is next. Follow `spx-trial`.
10. **TODO items and reports.** One TODO item per box being worked on and one
    per hypothesis being tested; none for recording, collecting, staging or
    returning to known-good. Every report starts with "boxes closed: N of 47"
    and the IDs closed since the last report. Follow `spx-status`.

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
- Research and patch writing may run in parallel, at most four agents, all for
  the current blocker.
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

**2026-10-12 user stop:** Do not reboot this device anymore. This overrides
the older standing reboot authorization below. Venus/Chromium work is offline
only after repeated hangs/resets; no live browser or module trials without
new explicit user authorization.

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
