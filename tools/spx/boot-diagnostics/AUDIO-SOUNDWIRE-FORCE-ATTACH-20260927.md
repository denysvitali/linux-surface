# T: first boot-time SoundWire force-attach

S registered the SLIM controller, bound WCD934x and created an ALSA card, but
both WSA881x SoundWire slaves remained `UNATTACHED` with no device number.
The initial SoundWire reads underflowed. T reuses S/R's exact kernel, DTB,
initramfs and modules and changes only the attempt marker plus
`soundwire_qcom.spx_force_attach=1` on the kernel command line.

The existing qcom SoundWire probe schedules `spx_swrm_enum_work` 300ms after
master probe when force-attach is enabled. That worker takes its short
force-attach branch before the `spx_core_enum` diagnostic loop. Keep
`spx_core_enum=0` and default `spx_no_assign=1`: the worker may mark logical
device 1 attached while routing writes to physical enumeration address 0.
This is a diagnostic of the existing mechanism, not proof of physical stereo
enumeration or audible playback. The exact worker markers, cached slave
status/device numbers, FIFO/read errors and soundcard state determine the
outcome. A scoped pass requires the controller/card baseline and at least one
WSA slave `ATTACHED` with device number 1 at the 620-second snapshot, with no
selected kernel fault and a healthy graphical/Wi-Fi/touch baseline.

Use a separate T archive, one-shot GRUB entry, automatic 620-second collector
and 900-second fallback. Retain `spx-known-good` as persistent default, verify
all payload/recovery hashes, and collect T's actual result before any further
hardware experiment. No live device unbind/rebind or module parameter writes.
