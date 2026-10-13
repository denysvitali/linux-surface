boxes closed: 3 of 47; newly closed: none.

# Implementation interrupted by reset

Current boot `2b94566a-91c2-4b2d-a724-401145281725`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

Sensor startup commit c5a8df108c70 is integrated and deployed. Provider and
proxy remain running after the restart; provider reports SSC ready. No
physical acceptance claim, no new microphone/camera capture or gain changes.

Venus final modules freshly linked with matching ABI and bounded allocator
verified in ELF on preceding boot2530c4ce. The session issued a core reload;
that boot ended at07:42:07, near this attempt. Final journal evidence is
a warning in __flush_work (kernel/workqueue.c:4409), CPU4 v4l_id/61989,
then NULL dereference at0x20. Earlier Venus startup logged HFI read_ret=-61
and firmware-version read failure. No orderly shutdown or complete panic
trace retained; pstore empty. oops=panic panic=20 makes crash-triggered reset
plausible, not proven. Successful reload/decoding is NOT established. Do not
retry automatically.

Type-C worker reported WIP commit7e02402c417d, but its Git object is now
empty and its brief is zero bytes. Patch is not integrated or deployed.
Preserve remaining worktree/source data; repository recovery must precede
further commits. No live display reload or requested reboot.

Cellular/CDSP remains blocked on authoritative endpoint/channel/firmware
contracts. Sleep stays masked. Stop module experiments here: reset plus
repository corruption makes continued changes unsafe. Next: recover Type-C
patch from surviving files/transcript and investigate reset evidence before
any hardware experiment. No checklist change.
