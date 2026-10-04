# X: keep the detached WSA out of PCM transport

W's verified silent PCM test submitted DSP buffers and completed without
SoundWire errors, but both WSA codec instances configured DAC port 1 and
started their PA paths. Sysfs showed only the left WSA Attached/1; the right
was UNATTACHED/N/A. Its internal `dev_num` was stale at 1, so the existing
enumerated-mode transport predicate accepted it.

The bounded X source correction requires `slave->status ==
SDW_SLAVE_ATTACHED` in enumerated mode before accepting its device number.
The same guard avoids DAPM PA/RDAC and digital-mute register writes to an
unattached codec. Other modes retain their previous behavior. The isolated
`wsa881x.o` compile passed. Do not use a live parameter change to test this
on W; build and archive a distinct X kernel, modules, DTB and initramfs.

Reuse W's audio selectors except the attempt marker. X's boot baseline should
still pass SLIM registration, one logical WSA attachment, no write overflow
or status failure, FD680, Wi-Fi and touch. After its verified 620-second
archive, run the same one-second silent PCM test. X passes the transport
criterion only if the attached left WSA adds one DAC port and starts its PA,
the detached right WSA is excluded from `hw_params` and has no PA/RDAC
events, and the PCM completes without new SoundWire or DSP errors. Record
the right control-read underflow separately. No result here establishes
audible output.
