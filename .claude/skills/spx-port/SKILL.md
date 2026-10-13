---
name: spx-port
description: Coordinate the Surface Pro X mainline port using the generated automatic hardware checklist, per-boot validation and one current defect.
---

# SPX port coordinator

You own the generated checklist, build directory, device and every reboot.
Read `AGENTS.md`, `TODO.md`, `AUTO-HW-CHECKLIST.md` and the newest
`LOCAL-PROGRESS.md` entry first.

## Loop

1. Run `tools/spx/progress`. Separate automatic functional passes from inventory,
   blocked dependencies and historical full acceptance.
2. Check this boot's hardware-validation JSON/Markdown under
   `/var/lib/spx-boot-diagnostics/boots/<boot-id>/hw-validation/`. If missing or
   incomplete, run the canonical suite before choosing another experiment.
   It must run after baseline, trial and recovery boots, not only trial boots.
   Use `sudo systemctl restart spx-hw-validation.service` after repairing a
   prerequisite, then `automatic-validation.py verify` as documented in the
   canonical README. The installed binary must be rebuilt/reinstalled after
   validator/catalog changes.
3. Use the generated automatic failures and `TODO.md` to work the current
   defect in depth (`spx-blocker`). Keep missing driver/DT/userspace support,
   tools/fixtures and known unsafe paths distinct. Do not silently drop a feature.
4. Delegate independent bounded work. For this user-requested validation rework,
   ten agents are allowed; ordinary kernel porting uses at most four offline
   agents unless the user specifies otherwise. Only you integrate/build/reboot;
   one device tester holds the device lock. No bookkeeping review agents.
5. Prefer module changes over reboots. Built-in/DTB/initramfs changes use
   `tools/spx/trial.py` and `spx-trial`. Do not unload MSM.
6. After changes, rerun affected functional checks; after every boot run the
   whole safely automatic catalog. Record blocked unsafe tests instead of
   attempting them. Generate `AUTO-HW-CHECKLIST.md` from the actual report;
   never tick it by hand or close historical acceptance from inventory.
7. Report precisely (`spx-status`) or stop when there is no safe untested
   hypothesis/prerequisite. Do not invent test variants to create progress.

Manual tests are excluded from this work queue. A human can use `../validation`
or `spx-human-session` when they want; do not prompt or wait for them. Physical
behaviour is not established by synthetic input or automatic enumeration.
Sound, camera/microphone capture, battery tests and parked encoder work retain
all restrictions in `AGENTS.md`.
