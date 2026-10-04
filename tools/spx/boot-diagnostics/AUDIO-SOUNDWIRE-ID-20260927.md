# U: correct the two WSA881x DT identities

T's force-attach worker ran, but its `part_id == 0x2010` filter skipped both
declared `0x2110` slaves. The prior hardware DevID observation is `0x2010`;
the codec driver supports it. Change only the two DT SoundWire compatible
properties to `sdw10217201000`. The rebuilt DTB decompiles identically to
R/T's DTB except for those two strings.

Reuse the exact R/T kernel, 202-file installed module tree and initramfs.
Preserve the U source/config/DTB build evidence and installed payload hashes.
Use `spx_stage8_step=2`, `spx_allow_full=1`, `spx_pio_mode=1` and
`soundwire_qcom.spx_force_attach=1` as in T, changing the attempt marker to U.
Do not change SoundWire parameters on a live boot or unbind devices.

U's primary criterion is at least one WSA slave with cached status `ATTACHED`
and device number 1 after the worker's matched-slave log, while retaining
SLIM registration, the ALSA card, FD680, Wi-Fi, touch and a fault-free kernel.
Also record codec read failures, slave IDs and both slave states. An attached
logical slave does not establish physical bus writes, stereo or playback.
Keep `spx-known-good` saved, arm a single trial, verify boot ID and pending
selection before reboot, collect at 620 seconds and return to known-good at
900 seconds if the scoped result fails.
