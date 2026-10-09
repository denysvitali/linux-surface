boxes closed: 3 of 47; newly closed: none.

# Venus startup repaired; hardware decoding remains WIP

Boot `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. User authorized parallel Venus-only
work despite camera locks. No reboot, camera capture or persistent module swap.

**Changes and observations:**
- Archived firmware 00040/00061 alone still timed out with startup status zero.
  Installed 00042 and firmware lookup restored; temporary files removed.
- Original SQ2 miniport's VIDEO_VAR secure-call table supplies
  `0/0x25800000/0x01000000/0x24800000`. Native SC8180X omitted these values.
  Commit fb2a02e15657 adds them. At 01:28 secure setup returned zero and
  firmware became ready (`0x40000001`, ten polls), but SYS_INIT timed out.
- Firmware consumed commands and produced successful SYS_INIT responses, but
  no response interrupt arrived. DSP unmasking, extra wrapper acknowledgement
  and disabling firmware power collapse each failed; all three reverted.
- Vendor startup explicitly polls its response queue. Commit b5f19ba708f2
  polls through the native parser for Iris1 startup with IRQ serialization
  and the existing deadline. At 01:35:15 the driver bound and registered
  video32/video33. Decoder enumerated H.264/VP8/VP9/HEVC/MPEG2 and NV12/Q08C.
- First bounded FFmpeg H.264 decode produced **zero frames**. Session setup
  caused an ARM access fault (SID2340, IOVA40f22170; firmware PC3415c).
  Failed runtime-PM recovery loop stopped by unloading Venus at 01:36:21;
  removal emitted a warning. Display/camera modules were not changed.
- Firmware and original miniport agree that session IDs are table indices;
  Linux sends pointer hashes. New WIP assigns unique Iris1 IDs below
  MAX_SESSIONS under the core lock and uses them for all session commands
  and response lookup, preserving hashed IDs for other variants.
  All three Venus modules compiled/modposted successfully. Matching candidate
  modules were used together to account for the changed instance structure.
- At 01:42:11 the follow-up could not reach firmware: vcodec0_gdsc was stuck
  off and core probe returned -110. Thus the bounded-ID fix is **untested on
  firmware**, not a failed decode result. No repeat of this stuck-state test.

**State and next:** Venus modules unloaded; temporary autoload blacklist removed;
installed firmware/modules unchanged. Candidate modules remain in the canonical
build source's Venus directory. Next: after a clean boot coordinated with the
active camera session, load all three matching candidates and test bounded
H.264 decoding. Session domain/notification behavior may still need work.
No browser acceleration or D03 acceptance claimed; this is a kernel/firmware
integration failure, not evidence that switching to Chrome would solve it.
