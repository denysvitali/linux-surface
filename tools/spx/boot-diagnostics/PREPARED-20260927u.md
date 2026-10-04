# U prepared: corrected WSA881x DT identities

T's failed force-attach result and 900-second return are archived and
independently verified. Known-good boot
`d8cc4fba-bbc0-455c-bd0f-2c9788d6d4f0` is live. U changes exactly the two
WSA speaker DT compatible strings from `sdw10217211000` to
`sdw10217201000`; decompilation of the old/new DTBs confirmed no other DT
changes. U DTB SHA256 is
`ee7f763c14a07b9f956ca65871a9a19851392b444bd754323db6df951fe6f81a`.

The U archive keeps a fresh source/config/DTB snapshot and copies the exact
922-file R build. The installed module tree's 202 files, reused R kernel and
initramfs, U DTB, known-good recovery files and runtime helpers rehashed.
Installed review SHA256 is
`5f1591ee68a5cb1d708e9cef85d95d70d84fa7a4e320da3b0711669ba5210ac3`.
Known-good remains the persistent GRUB default. No one-shot entry or EFI
BootNext is selected. U has its own enabled, currently inactive 620-second
collector and 900-second known-good fallback. The preboot known-good snapshot
has 126 hashed files, manifest SHA256
`905541e9e03d2a6eb2960d356fa9ecfd1fc63f38312a72a6fc1d5e9bcf12a4f8`.

Use only the archived `queue-once.py`. It verifies the current boot, hashes,
saved default and empty one-shot selection before `grub-reboot`. Its separate
30-second guard checks the pending selection and hashes again immediately
before reboot. Do not replay it after `reboot-requested` exists. The standing
authorization covers a trial that may need a manual power cycle; automatic
recovery across EFI handoff remains unvalidated. Do not live-unbind devices.
