# Bounded Venus real-film output fixtures

[Big Buck Bunny project attribution/license](https://peach.blender.org/about/):
(c) copyright 2008, Blender Foundation / www.bigbuckbunny.org.
The project publishes its film under Creative Commons Attribution3.0.
The exact distribution comes from
[Blender's download directory](https://download.blender.org/demo/movies/BBB/).
Download index, headers, license page, original ZIP/MP4 and computed source
hashes are retained; no publisher checksum/signature was provided.

[prepare.py](prepare.py) extracts one MP4 from the ZIP and creates a four-second
real-film excerpt at30s,640x360/30fps/120 frames. Software libx264 makes baseline
and high-profile/B-frame H.264 streams. Explicit software H.264 decoding twice
produces identical120-frame references for both clips, with120 distinct image
hashes each. A separate independent reparse checks timestamps, sizes and exact
repeat equality. No hardware codec is used in preparation.

The45-file fixture manifest is
`3a251cbe1a6d72a1601011d260a85f4faaa6519e111ff97ca0d824f68d0aa612`.
Private download/preparation: `/var/tmp/spx-video-media-20261003/`.
Root-owned verified copy:
`/var/lib/spx-boot-diagnostics/fixtures/video-media-20261003/`.
Independent copy/reference review is stored beside that sealed tree.
FFmpeg9.0.1 versions/decoder/encoder lists, binary hashes, all commands and
raw stdout/stderr are archived. Preparation does not pass D03.

[run-az.py](run-az.py) is prepared for a verified actual AZ boot only, after
normal Venus driver bind and decoder/encoder node registration. It requires
exact boot/release/cmdline, candidate and fixture hashes, taint0 and an active
900s known-good return timer. It records V4L2 FD witnesses while invoking
explicit `h264_v4l2m2m` codecs. Both decoder outputs must match every reference
frame's pixels. The encoder must produce120 valid640x360 H.264 frames and a
software-decoded average PSNR of at least32dB against the raw film input.
Every hardware subprocess has a45s deadline, and failures/logs remain archived.
No run has occurred. Actual parser checks accept both original reference pairs;
dropped/reordered/changed-pixel/wrong-size/malformed-hash controls reject.

This is an initial bring-up test. Sustained playback, higher resolutions,
other fitted codecs, secure media, idle/resume and all checklist requirements
on one final candidate remain necessary. Node registration or a prepared
reference is not video acceleration acceptance.
