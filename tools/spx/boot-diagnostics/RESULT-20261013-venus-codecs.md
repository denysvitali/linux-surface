# 2026-10-13 Venus decoder: HEVC/VP8/VP9 verified, MPEG-2 hidden

boxes closed: 3 of 47; newly closed: none (D03 stays open: encoder parked,
MPEG-2 unsupported, browser paths for the new codecs untested).
Automatic: 18/48 functional pass, 43 blocked, 0 fail, 0 error on boot
`6e361af1-caec-4e8b-873b-dfd1d2021329`, kernel 7.3.0-rc2-spx-mainline-20261004bg+.
Report: `/var/lib/spx-boot-diagnostics/boots/6e361af1-caec-4e8b-873b-dfd1d2021329/hw-validation/`.

| Codec | Result (ffmpeg `<codec>_v4l2m2m -xerror`, 4 s 1080p, framemd5 vs software) |
|---|---|
| H.264 | 120/120 identical (640x360 baseline fixture), reopen passes |
| HEVC | 120/120 identical |
| VP8 | 120/120 identical |
| VP9 | 120/120 identical, exit 0, monotonic pts, 3 DROP_FRAME buffers recycled per run |
| MPEG-2 | not advertised on SC8180X; decode is unsafe (below) |

- **MPEG-2 (boot 45bccac9):** firmware logs `OPB is not supported in MPEG2
  Decoder`, then session error 0x1008 at about 18k IRQ/s, continuing after
  close; `vcodec0_gdsc` stuck off, reboot-only. A single-output layout is not
  established from any source, so commit `88f65136695f` hides the format and
  makes that error fatal for decoders. The containment path itself has not
  been exercised on hardware (doing so needs the fault).
- **VP9:** firmware returns extra full-size capture buffers flagged
  DROP_FRAME|ENDOFSUBFRAME; the driver completed them as error frames after
  consuming the shown frame's timestamp metadata. Commit `492a7b1dfc63`
  recycles them to the firmware instead.
- Fixtures are transcodes of the existing Big Buck Bunny source:
  `/var/lib/spx-boot-diagnostics/fixtures/media/{hevc.mp4,vp8.webm,vp9.webm}`.
- Not tested: drain/seek/resolution change with recycling, 10-bit, browser
  playback of HEVC/VP8/VP9, sustained runs. No encoder open or load.

Modules installed in the running release; previous pair saved in
`/var/lib/spx-boot-diagnostics/module-backups/venus-20261013-pre-mpeg2/`.
One baseline reboot (45bccac9 -> 6e361af1); the per-boot validation hook ran
on both boots.
