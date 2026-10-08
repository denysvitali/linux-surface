boxes closed: 3 of 47; IDs closed since last report: none.

# Baseline green cast: controlled white-balance comparison

**Source:** last complete 2112x1568 GRBG RAW10 frame of the existing 6.18 v23
rear capture, stride 2640, under
`/var/log/spx-camera-archive/v23-multi-20260809/`. No new capture or boot.
This is the same frame used for the preceding matrix experiment, not EV.

**Test:** reused the existing `camera_render.py` to unpack all ten bits and
demosaic to linear RGB48. Computed grey-world gains after provisional common
black subtraction: R=1.36186337, G=1, B=1.52246971. Compared this output with
unity gains while holding every other stage fixed: black=64 RAW10 counts,
common exposure white=11.5 above black, sRGB transfer and unchanged pixel
orientation. No vendor matrix, guessed neutral patch or manually selected
colour gain was used.

**Observed:** the unity-gain control retains a visible green cast. The
frame-derived gains substantially reduce it. The comparison holds exposure
and transfer identical, so their change cannot account for that difference.
The image remains strongly noisy because its signal is near black level.

**Meaning:** missing white balance explains a substantial part of the
baseline's green appearance. This is evidence of the effect of the omitted
stage, not calibrated colour acceptance: grey-world assumes a statistically
neutral scene, and black=64 remains provisional. No actual scene colours or
illumination were established. No camera box is complete.

**Next:** run the already integrated renderer on a correctly exposed mainline
capture with known neutral/colour targets before choosing vendor CCMs or
claiming usable camera colour. Current sandbox still prevents privileged
device management and writes to this worktree's external Git metadata.

Outputs: `processed-awb.ppm`, `processed-no-awb.ppm`, parameters and
`awb-comparison.png` in `/tmp/spx-camera-matrix-test/`. No renderer or kernel
source was changed during this comparison; notes remain uncommitted.
