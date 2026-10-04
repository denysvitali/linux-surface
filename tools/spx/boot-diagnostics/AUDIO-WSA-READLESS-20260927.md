# V: readless WSA881x initialization

U corrected the two DT speaker IDs and reached one logical WSA slave at
device 1. The core then attempted a read-modify-write of SCP_INTMASK1 and
underflowed because `spx_no_assign=1` deliberately leaves the physical amp
at enumeration address 0. Later codec register reads at logical device 1
also underflowed. U's preserved result demonstrates this boundary.

Reuse the exact U kernel, modules, corrected DTB and initramfs. Change only
the attempt marker and add the boot-only codec selector
`snd_soc_wsa881x.spx_enumerated_mode=1`. In the existing WSA driver this
sets `scp_int1_mask=0` before the SoundWire core initializes the slave,
which skips the failing SCP_INTMASK1 read-modify-write. It also makes the
codec's register updates use a shadow-backed full write and selects the
existing DAC-only Surface path. It does not drive the amplifier shutdown
GPIO at probe; firmware-established power levels remain. Keep SoundWire
`spx_no_assign=1`, force attach and all NGD selectors as in U.

The first scoped criterion is logical `Attached`/device 1, no WSA slave
initialization or status-update failure, a WSA cold-init entry, controller
and ALSA card registration, healthy FD680/Wi-Fi/touch, taint zero and no
selected kernel fault. Record all SWR FIFO/read errors and both slave states.
A passed init does not prove that fire-and-forget writes reached the physical
amp or that playback is audible. Playback needs separate evidence after
this prerequisite is established.

Keep `spx-known-good` as persistent default, select V once, hash-check its
boot/recovery files before reboot, collect at 620 seconds, and return at
900 seconds if the scoped result fails. Do not change live parameters or
unbind display/SLIM/SoundWire devices.
