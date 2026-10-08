boxes closed: 3 of 47; IDs closed since last report: none.

# Vendor matrix applied to a real rear-camera frame (offline)

**Source:** last complete frame of the preserved 6.18 v23 capture,
`/var/log/spx-camera-archive/v23-multi-20260809/rear-2112x1568-two-frames.raw`.
2112x1568 GRBG RAW10, stride 2640. This is an older capture, not EV or a new
mainline boot. EV's surviving image is now root-only; this restricted session
cannot read it or elevate through sudo.

**Test:** unpack all ten bits, demosaic with FFmpeg `bayer_grbg16le` to
`rgb48le`, and compare baseline with rear `cc13_ipe` profile 3, symbol 421,
region 0 (4800–9000 temperature trigger). Tried row-major RGB and reversed
RGB/BGR interpretations of that same vendor matrix. This is an explicit
candidate, not a claim that Windows would select it for this scene.

Before multiplication, subtract an assumed black level of 64 RAW10 counts
and clamp negative inputs to zero. All outputs use the same baseline
0.2–99.8% display stretch (63–75 RAW10 counts). No white-balance gains,
gamma adjustment or mounting rotation were added. A known-value fixture
confirmed that FFmpeg preserves the sub-8-bit precision in RGB48 output.

**Observed:** both matrix interpretations intensify the visible green cast.
RGB produces 30.3911% negative channel samples before display clipping;
BGR produces 30.7451%. Baseline black-subtracted R/G/B means are
0.9592/1.3058/0.8571 RAW10 counts, versus 0.4503/1.5121/0.3182 (RGB)
and 0.5369/1.4897/0.2459 (BGR). The frame is heavily underexposed and most
variation lies in the bottom two RAW10 bits; eight-MSB processing loses it.

**Meaning:** this selected matrix alone is insufficient for this capture.
The test does not select another profile, establish correct coefficient
ordering, validate the assumed black level, or rule out vendor matrices as
part of a complete calibrated pipeline. Next: exposure/black-level/AWB and
supported selector mapping before repeating a matrix trial. No box changes.

Comparison PNG, full-resolution PPMs and parameters are in
`/tmp/spx-camera-matrix-test/`. These are temporary local artifacts. The
source capture and matrix extractor make the test reproducible. No device
state or kernel source changed. Git metadata remains read-only in this session.
