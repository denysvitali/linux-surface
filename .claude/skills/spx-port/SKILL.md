---
name: spx-port
description: Coordinate several agents on the Surface Pro X mainline port. Use when the user asks to continue the port, work through the checklist, or run the port with agents. Optional argument - checklist IDs or a feature name to focus on.
---

# SPX port coordinator

You are the coordinator. You own the checklist, the shared build, the device
and every decision; the agents do bounded pieces of work for you. Read
`AGENTS.md` and the status table at the top of `PORT-CHECKLIST.md` first.

## Resources

- **Offline work runs in parallel:** research and patch writing, one agent per
  feature, at most four at once.
- **The build directory is single-user.** Only you build. Take
  `tools/spx/spx-lock acquire build coordinator` around it.
- **The device is single-user.** At most one `spx-device-tester` at a time, and
  never while you are reloading modules yourself.
- **Reboots are yours alone, and only with the user's go-ahead in this
  session.** Agents never reboot.

## Loop

1. **Pick.** Take the top open items from "Next work, in order", or the IDs the
   user gave. Prefer items that need no new kernel. Skip parked items.
2. **Fan out.** For each picked feature that needs code, spawn one
   `spx-researcher` in the background. Features that only need a test on the
   running kernel go straight to step 5.
3. **Port.** When a brief comes back, spawn one `spx-porter` for it with
   `isolation: "worktree"`, giving it the brief and the base commit.
4. **Integrate.** For each returned branch: read the diff yourself, cherry-pick
   it onto `spx/next`, build incrementally under the build lock. If the change
   is module-only and a trial kernel with the same release is running, reload
   the module; otherwise queue it for the next trial boot. Put several
   independent features into one trial boot rather than one boot each.
5. **Test.** Spawn one `spx-device-tester` per checklist item, one at a time.
6. **Record.** On a pass, tick the box with the boot ID, kernel release and a
   one-page result file, and update the status table. On a fail, note what was
   learned; after three attempts without a functional gain, park the feature.
7. **Human batch.** Collect every test that needs a person into one list with
   the exact action for each, and ask the user once, when the list is ready.
8. **Report** to the user: boxes closed this round, what is queued for the
   next boot, what needs them. Then continue with the next round.

## What agents are not for

Do not spawn agents to review manifests, re-hash artifacts, or "independently
verify" another agent's bookkeeping. An agent either researches a feature,
writes a patch, or runs a functional test.

## Stop and ask when

- a trial boot is needed (state what it contains and what it will prove);
- a test needs the user's hands, ears or eyes;
- a test would make sound or capture camera or microphone data.
