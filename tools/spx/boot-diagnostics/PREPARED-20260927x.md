# X prepared: exclude the unattached WSA from PCM transport

W boot `e6989b7a-9ee5-4138-939d-84f8f73f53d5` passed its automatic
codec-init baseline and a bounded digital-zero PCM stream, but the silent
stream activated both WSA PA paths even though the right slave remained
UNATTACHED/N/A. X is a distinct
`7.3.0-rc2-spx-mainline-20260927x+` kernel that gates enumerated-mode
stream participation and DAPM/mute writes on actual `SDW_SLAVE_ATTACHED`
status. All W audio selectors and the corrected DTB are otherwise retained.

The X build archive has 964 verified regular files and 272 symlinks;
manifest SHA256 is
`2203967412e23b4db2b97859f6864d9f1f5aac28fb07e2dd109124cc09b449ed`.
The independent artifact review SHA256 is
`2132656c7e81e697f9fe264b9aa579cb57a05d1b249e769aebffbe056b2331bd`.
The installed module tree has 202 verified files. The X compressed kernel,
initramfs and DTB hashes are
`da35df6d9d10796d382ba52b28aa5ea3b1b358114ef42825b62badad3a7acbc7`,
`f33669ab706433df5c4c791579c59681923353c4fe5ace38037faa3bc675e63b`
and `ee7f763c14a07b9f956ca65871a9a19851392b444bd754323db6df951fe6f81a`.
The consumed W boot slot was backed up and hash-checked in X's permanent
archive before its boot-partition files were removed.

X's independent installed review SHA256 is
`42aea0760c68d4eaed3eba9d7a9b4a439827d09943c1f9c45424b294f374ddce`.
Its 320-file W preboot snapshot manifest SHA256 is
`f6c2b277723726f2c13b3515a80481081a0796faa4dbb5384cf554314e9fbe03`.
The three recovery files, all X payload/runtime files, complete build and
installed modules were verified. GRUB still saves `spx-known-good` as
persistent default, `next_entry` is empty, and EFI BootNext is absent. X's
620-second result collector and 900-second fallback are enabled but inactive
on W. No X boot is selected at this writing.

Use only the archived `queue-x-once.py`. Its separate reboot guard rechecks
the boot ID, pending entry and hashes immediately before reboot. After X
starts, run the archived `x-silent-pcm.py` once between 120 and 600 seconds.
The 620-second collector will accept X only if the left attached codec joins
the silent DAC stream, the right unattached codec is excluded with no PA/RDAC
events, the PCM exits successfully without new FIFO or PA errors, and the
graphics/Wi-Fi/touch baseline remains healthy. A pass does not prove audible
speaker output.
