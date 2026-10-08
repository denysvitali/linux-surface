boxes closed: 3 of 47; IDs closed since last report: none.

# Camera renderer correction (offline)

**Source:** EV boot `fffa14b0-0b51-4b25-ac98-10f9c9b4351c`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. This session used its surviving 2112x1568
8-MSB Bayer image; the original packed RAW10 was retired. No new capture or boot.

**Changed:** `camera.py` now unpacks GRBG RAW10 respecting row stride, uses
FFmpeg `bayer_grbg8` demosaicing, and writes an RGB PPM with one common
0.2–99.8% contrast stretch. It preserves sensor pixel orientation and channel
ratios. Rendering errors are recorded without interrupting capture cleanup.
It also uses the last complete frame when a partial trailing frame is present.

**Observed:** the custom `/tmp/spxjpg/dem.py` used for EF writes `(g, r, b)`
into RGB output; its `rot90cw` transposes coordinates without the required
flip. EF's colour/orientation deductions from that renderer are unreliable.
The new decoder reproduced a known GRBG fixture (R=200, G=100, B=40) with
the expected channel order despite row padding. Partial-frame, flat-image and
truncation checks succeeded. EV output matches a direct FFmpeg conversion;
common stretch endpoints are 16 and 75. No scene-specific gains were applied.

The earlier register explanation is unsupported: `0xab ^ 0xa8 = 0x03`, so
the cited bits 3/4 do not change. The OV13858 mode tables match the working
6.18 source. This does not establish the actual flip-bit meanings.

**Meaning/next:** the preview defect is fixed in software; correct physical
orientation and scene colour remain unvalidated. Ask the user to identify
the actual colours and tablet pose from the corrected preview before choosing
a sensor or metadata change. The pending mainline human session comes first.
C01 still needs resolved supply ownership; no camera box is complete.

Saved Bayer evidence, PPM and PNG are root-only in
`/var/log/spx-camera-archive/20261008ev-render/`. The decoder requires FFmpeg;
it records `preview_error` if unavailable. Camera capture has not run with
this updated helper yet.
