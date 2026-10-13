---
name: spx-human-session
description: Prepare and run the hands-on Surface Pro X test session with the user (keyboard, touch, pen, buttons, USB, panel, Bluetooth, rotation, wake) and record the results against checklist boxes. Use when the user is available for physical tests or asks what they need to test.
---

# SPX human session

Manual checks are voluntary and excluded from `AUTO-HW-CHECKLIST.md` by the
user's 2026-10-13 instruction. Use this playbook only when the human requests
physical checks; do not prompt, schedule them or wait for them during porting.
They can record separate evidence for historical `PORT-CHECKLIST.md` boxes.
The sibling `../validation` app provides the voluntary physical interface.

## Prepare (before asking)

1. The device must be on the mainline candidate, not known-good. Record
   `uname -r` and `/proc/sys/kernel/random/boot_id`.
2. Take the steps from `tools/spx/boot-diagnostics/PHYSICAL-TESTS.md`. Drop
   every step whose feature is not running on this boot, and the battery and
   charger steps (deferred by the user).
3. For each remaining step, start whatever must be recording first (for
   example `libinput debug-events`, `evtest`, `udevadm monitor`,
   `iio-sensor-proxy` monitor) so the user's action is captured without them
   reading anything back. Do not record audio or camera for this session.

## Ask

Send the user one numbered list. Each step is one physical action and the
answer you need is "works", "fails: what happened" or "not available". Say
how long it takes. Do not ask them to run commands.

## Run

Go step by step. After each action, check the captured events yourself and
combine them with what the user saw. If a step fails, note it and move on;
do not debug during the session. If the user ends the session early, keep
what you have.

## Record

1. Write one result file,
   `tools/spx/boot-diagnostics/RESULT-<date>-physical.md`: a table of step,
   box ID, user observation, captured evidence, verdict.
2. For each box: tick it only if its full text is now met. Most boxes also
   require resume or repeat behavior; if that part is untested the box stays
   open and you write exactly which part is left.
3. Update the "Human session" and "Needs a fixture or the user" sections of
   `TODO.md`: remove what is done, list what is left as the next session.
4. Report with `spx-status`.

Do not replace a declined or missing human step with an automated stand-in
(synthetic input events, loopback, self-scored tests). It stays pending.
