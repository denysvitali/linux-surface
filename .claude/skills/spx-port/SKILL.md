---
name: spx-port
description: Coordinate the Surface Pro X mainline port. Use when the user asks to continue the port, work through the checklist, or run the port with agents. Optional argument - a checklist ID to work on instead of the current blocker.
---

# SPX port coordinator

You own the checklist, the build directory, the device and every decision.
Read `AGENTS.md` and `TODO.md` first. The other playbooks are `spx-blocker`,
`spx-trial`, `spx-human-session` and `spx-status`.

## Loop

1. **Status.** Run `tools/spx/progress`. If it reports the checklist is not
   frozen, fix that before anything else (move the sub-boxes to the result
   files or the history file).
2. **Human session.** User deferred hands-on checks until the end on
   2026-10-13. Do not ask during porting; retain missing observations in
   `TODO.md` and leave their boxes open. Follow `spx-human-session` when the
   user starts the final checks. Do not replace them with automated tests.
3. **Blocker.** Take the current blocker from `TODO.md`, or the ID the user
   gave. Follow `spx-blocker`. Do not pick a different feature because it is
   easier or testable without a person.
4. **Agents, only if they help the blocker.** One `spx-researcher` for a brief,
   then one `spx-porter` (with `isolation: "worktree"`) per independent patch.
   At most four at once. Read each returned diff yourself, cherry-pick it onto
   `spx/next` and build incrementally under the build lock.
5. **Test.** Module-only change on a running trial kernel: reload the module.
   Otherwise one trial boot (`spx-trial`). One `spx-device-tester` at a time.
6. **Record.** Tick the box only if its full text is met. Otherwise write the
   one-page result file and the next hypothesis in `TODO.md`.
7. **Report or stop.** Follow `spx-status`. Stop when `spx-blocker` says to.

## Limits

- Only you build, integrate, tick boxes and reboot. Agents never reboot.
- Reboot rules are in `AGENTS.md`. In Claude Code, also ask the user before
  each reboot unless they gave the go-ahead in this session.
- No agents that review manifests, re-hash artifacts or check another agent's
  bookkeeping.
- Ask before a test that makes sound or captures camera or microphone data,
  unless `AGENTS.md` already authorizes that run.
