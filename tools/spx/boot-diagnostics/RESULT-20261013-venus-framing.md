boxes closed: 3 of 47; newly closed: none.

# Venus stalls on split H.264 headers

Boot `93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`; no reboot/reset.

**Hypothesis:** Chromium's standalone SPS/PPS/SEI buffers prevent Venus
startup. Used installed v4l2-ctl 1.32.0 rather than a new harness/browser build.
Extracted 120 H.264 pictures from the existing Big Buck Bunny fixture by
stream copy. Both inputs contain identical 130,961 payload bytes; their first
picture has Chromium's SPS31/PPS9/SEI702/IDR413 order. Only buffer boundaries
differ: 120 whole access units versus 123 individually separated NAL units
(the fixture has one slice per picture). No video encoding or audio ran.

Loaded the coherent, incrementally rebuilt Venus core+decoder under the device
lock with old-module autoload blocked; encoder absent. Each test requested
unknown OUTPUT dimensions (driver returns 96x96), H264, sizeimage 2097152,
16 OUTPUT buffers, 8 requested CAPTURE buffers, source-change-driven CAPTURE
startup, 60 output frames and a 20-second external bound. Output discarded.

| Input / same module load | Decoded buffers | Observation |
|---|---:|---|
| Whole access units | 60 | SOURCE_CHANGE to 1920x1088, normal decoding |
| Separate headers/slices | 0 | select timeout; late sequence event and FLUSH timeout |
| Whole units after split failure | 60 | Normal decoding restored by input framing alone |

All commands exited 0: v4l2-ctl's exit code alone hides its select timeout.
Split teardown reproduced unread FLUSH_DONE behind sequence callback, matching
the Chromium trace. Whole-unit recovery rejects a persistent second-session
failure as the explanation. This supports the framing diagnosis on hardware;
it does not validate the Chromium patch, image quality or browser display.
Unlike Chromium, v4l2-ctl queues initial OUTPUT before STREAMON.

Modules removed, temporary policy removed, locks free; post-test journal has
no new host warning/refcount/fault. Logs and framed inputs are
`/var/tmp/spx-framing-20261013-{au,split,au-reopen}.log`, `*-kernel.log`, `*.hdr`.
Next: build Chromium candidate `961a50b3c2d1`, exercise parser/EOS/fragmentation
and actual browser playback/reopen. Local full-browser build resources remain
missing. D03 stays open; encoder remains parked and human checks deferred.

References: [H.264 buffer contract](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/pixfmt-compressed.html),
[v4l2-ctl 1.32 source](https://github.com/gjasny/v4l-utils/blob/v4l-utils-1.32.0/utils/v4l2-ctl/v4l2-ctl-streaming.cpp).
