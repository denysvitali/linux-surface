# S prepared: first controller registration trial

S uses the exact R kernel, DTB, initramfs and 202 installed module-tree files.
Its private build archive copied and rehashed all 922 R build files and 272
symlinks; build manifest SHA256 is
`64c76945a5a49701269d3798932ce25e528392cc3c05b4c0910c4c294ec033b5`.
The only command-line differences from R are `spx_attempt=20260927s`,
`spx_stage8_step=2`, and `spx_allow_full=1` in place of step 1. The verified
R boot-slot hashes and three known-good recovery hashes are unchanged.

R's result is archived and independently rehashed. Its fallback stopped after
a 620.99-second scoped pass. S's 620-second collector and 900-second fallback
are installed and enabled, with the old 600-second return excluded for S.
The collector records the full kernel journal, SLIM devices and drivers,
codec lines, soundcards, graphical/Wi-Fi/touch baseline and selected faults.
Controller registration with two SLIM devices is the scoped pass;
soundcard/playback are separately reported.

Installed-state review passed with `spx-known-good` saved and `next_entry`
empty. No S boot is selected at this writing. The one-shot queue helper and
immediate reboot guard are archived in the S attempt directory. Do not replay
them after a request marker. Experimental boots may require manual power
cycling under the user's standing authorization; automatic EFI-handoff
recovery is not validated.
