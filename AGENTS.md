# Agent rules

## Goal

Mainline Linux on the Surface Pro X with every fitted hardware feature working.
`PORT-CHECKLIST.md` is the acceptance checklist; its status table at the top is
the state of the port. Read that table, the newest `LOCAL-PROGRESS.md` entry and
the latest `tools/spx/boot-diagnostics/RESULT-*.md` before starting work.

Progress is measured in checklist boxes closed and features a person can use.
Builds, manifests, reviews and passing diagnostics are not progress.

## How to work (revised 2026-10-04)

These rules replace the earlier evidence-first process. A review of the
2026-09-22..10-04 sessions found 56 boots, no acceptance box closed and about
half of all tool calls spent on hashing and verification.

1. **Close boxes per feature.** When a feature's functional test passes, tick
   its box and record the boot ID, kernel release and result file. Do not wait
   for a final candidate. The final-candidate regression is the separate F02/F03
   step at the end. Reopen a box if the feature regresses.
2. **Breadth before depth.** Prefer the feature that is closest to working for
   a user. If a feature gets three boots without a functional gain, write down
   what is known, park it and move to the next one. Venus (D03) is parked.
3. **Ask for physical tests.** Many boxes need a person: typing, tapping, pen,
   plugging in devices, listening. Prepare those tests, batch them into one
   short session and ask the user explicitly, with the exact action needed.
   Do not keep working around a missing human observation.
4. **Reuse known findings.** The 6.18 tree in `../linux-surface-kernel` already
   has working audio, camera and display findings. Port them instead of
   re-deriving them one register at a time.
5. **Commit as you go.** One commit per feature or fix on `spx/next`, with the
   status stated honestly in the message (working, WIP, not working). Never
   leave kernel changes uncommitted across a boot.
6. **Keep per-boot overhead small.** For a diagnostic boot keep only: the
   known-good default, the one-shot selection, the automatic return, and the
   dmesg/journal capture. Do not build file manifests, "independent" rehash
   reviews, frozen preparation records or fault-injection suites for a boot
   that changes one variable. Shorten the baseline wait when the change cannot
   affect it.
7. **Keep documents short.** A result file is one page: what changed, what was
   observed, what it means, what is next. Do not paste hashes or file counts
   into `PORT-CHECKLIST.md`. Its status table stays under about 40 lines;
   history belongs in the result files.
8. **Do not play sound or power the speaker amplifiers** unless the user asked
   for that run. Do not capture camera or microphone data without saying so.

## Harness rules (2026-10-04)

- **Reload modules instead of rebooting.** Venus, spi-hid, the WSA/SoundWire
  codecs and the camera drivers are modules. On a running trial kernel, rebuild
  the one module and `rmmod`/`modprobe` it. Reboot only for built-in code, DTB
  or initramfs changes. Never unload MSM display modules.
- **Keep one kernel release name** (`LOCALVERSION`) and one build directory for
  the whole port, and build incrementally. A per-attempt release name forces a
  full rebuild and stops modules loading across attempts. Do not copy, tar or
  rehash the source tree for a build; the commit ID identifies the source.
- **One parameterised trial tool.** Do not write new `build-XX`, `prepare-XX`,
  `assemble-XX`, `deploy-XX` or `archive-XX` scripts or new systemd units per
  attempt. Use one script and one set of units that take the attempt ID.
- **Clean up after a trial:** remove its `/boot/spx-trial-*` directory, module
  tree and units once the result is collected, keeping only the current
  candidate and known-good.
- **Known findings** from the 6.18 work are indexed in
  `~/.claude/projects/-home-dvitali-Documents-git-linux-surface-kernel/memory/MEMORY.md`.
  Read the entries for a feature before working on it.

## Authorized SPX reboot loop (2026-09-22)

The user explicitly authorized repeated experimental boots to complete the
mainline port and preserve logs. When asked whether this permits boots that
may need a manual power cycle, the user answered: "Yes. Proceed. Don't ask."
Do not ask for the same authorization again. Automatic recovery across the
EFI handoff is still unvalidated; the authorization does not establish it.

Safety rules that still apply to every trial boot:

- Keep `spx-known-good` as the persistent default and select each trial once.
- Check that the known-good kernel, initramfs and DTB are intact before a
  reboot (a hash check of those few files is enough).
- Recheck the boot ID and any pending boot selection before every reboot. An
  interrupted reboot call may already have executed.
- Collect the result before choosing the next experiment. Never blindly re-arm
  a failed image.
- Change one variable per boot.
- Do not unbind or rebind live MSM display components; this froze the device.
- Never read `171c0000+0x2000` or the pinctrl `pinmux-pins`/`pins` debugfs
  files; both wedge the machine.

## Historical boot lock (2026-09-14)

Superseded by the authorization above. Its findings remain relevant: there is
no validated pre-kernel reset mechanism, the diagnostic DTB has no hardware
watchdog node, and a hang after ExitBootServices needs a manual power cycle.
The prepared, unvalidated APSS watchdog candidate is described in the
"Pre-kernel watchdog candidate" section of
`tools/spx/boot-diagnostics/RECOVERY.md`.
