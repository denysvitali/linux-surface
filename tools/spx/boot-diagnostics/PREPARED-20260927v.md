# V prepared: readless WSA881x probe mode

U boot `db7ee26c-fe9f-4106-bc22-e5454ba51f9e` remains live after its
independently verified logical attachment pass. V reuses U's exact R kernel,
corrected `0x2010` DTB, initramfs and 202-file module tree. Its only command
line changes are the attempt marker and
`snd_soc_wsa881x.spx_enumerated_mode=1`. The mode is latched at codec probe;
it suppresses the SoundWire core's failing slave interrupt-mask read and
uses shadow-backed codec writes. See AUDIO-WSA-READLESS-20260927.md.

V's private archive verifies all 922 reused-build files and the U DTB build
snapshot. The installed review rehashed 14 payload/recovery/runtime files,
all 202 module files and the exact U payload comparison. Its SHA256 is
`a42644479455d1c2e33c657a3c6b1b3b3598c41c268dae7caafa719a5b5e6ec7`.
The U preboot snapshot copied to V has 312 hashed files, manifest SHA256
`5c6bee5f03143707482ec46e3f6a3c7b8e95a1e5ef78441521acec41f888d939`.
`spx-known-good` is still saved, `next_entry` empty and EFI BootNext absent.
V's 620-second collector and 900-second fallback are enabled and inactive
on U. No V boot is selected at this writing.

Use only V's archived one-shot queue helper, which checks the current boot,
entry and hashes, then schedules a separate 30-second immediate reboot guard.
Do not replay it after its request marker exists. The standing authorization
covers a boot that may need a manual power cycle; EFI handoff recovery is
unvalidated. Do not change live audio parameters or unbind devices.
