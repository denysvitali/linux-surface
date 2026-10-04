# R prepared: bounded stage-8 runtime resume

R is a distinct `7.3.0-rc2-spx-mainline-20260927r+` kernel. The source
change adds boot-only `spx_stage8_step=1`, which calls PIO runtime resume and
stops before `slim_register_controller()`. `spx_allow_full` remains disabled.
The source boundary and failure-marker rule are in
`AUDIO-STAGE8-STEP1-20260927.md`.

The immutable build archive is
`/var/lib/spx-boot-diagnostics/attempts/20260927r/build/`. Its 922 regular
files match manifest SHA
`64c76945a5a49701269d3798932ce25e528392cc3c05b4c0910c4c294ec033b5`.
The exact embedded config, 187 modules, 202 installed module-tree files, DTB,
private initramfs and initrd logger passed the independent artifact review.
R payload SHA256: kernel
`ff542f59274e42bf1367fc7f3432da2ac25ac4154749aaf48533a88e7e1225a5`,
initramfs
`613a2d16eb471f44fd2d5af5dad024fe21176d4672498d0a3c2e53c713c9ebfc`,
DTB `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5`.

Installed-state review in the R attempt archive verified the deployed payloads,
all three known-good recovery hashes, runtime files, and the installed module
tree. It archived and hash-checked the consumed P boot slot before removing
that slot from `/boot`; P modules and the immutable Q/P archives remain. The
GRUB default is `spx-known-good` and `next_entry` is empty. No R boot has been
selected at this writing.

R has its own 620-second automatic result collector and 900-second fallback.
The collector requires the stage-8 resume success marker with AWAKE state,
exactly one power-up branch, no controller registration, no selected kernel
fault, and the graphical/Wi-Fi/touch baseline. An explicit resume failure
marker fails the scoped test even if the outer child probe reports success.
The old 600-second return is excluded for R. Only the one-shot queue helper
may select R; its separate immediate pre-reboot helper rechecks boot ID,
GRUB selection, recovery files and deployed runtime hashes. The user already
authorized repeated experimental boots that may need manual power cycling;
automatic recovery across EFI handoff remains unvalidated.
