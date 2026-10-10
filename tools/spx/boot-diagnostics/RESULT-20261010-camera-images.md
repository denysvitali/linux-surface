boxes closed: 3 of 47; newly closed: none.

# Images from the three fitted cameras, 2026-10-10

Boot `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. User deferred the neutral fixture and
requested rear/IR images next, with calibration later. No reboot.

**Changed:** private libcamera libipa now registers OV7251 gain conversion
code/16, matching its existing Raspberry Pi helper and the native driver's
direct two-byte gain writes. Added patch0004. Signed simple IPA rebuilt;
distro package, kernel, graph and IR illuminator unchanged.

**Observed:** announced sequential captures, all sensor test patterns off.
Rear returned3 complete2112x1568 GRBG RAW10 frames (2640-byte stride,
4139520 bytes/frame), then90 processed1280x960 BGR frames around29.95fps.
Viewed output is dark and nearly uniform: mean36.41/stddev2.37 in8-bit RGB.
RAW high bytes mean15.98/stddev0.15, around the sensor black pedestal. This
does not demonstrate a recognizable rear scene or establish its cause;
dark/covered view versus sensor/image-path defect remains unresolved.

IR initially returned90 processed632x480 frames around30.10fps, equal RGB,
mean38.73/stddev1.08; viewed image nearly flat. Missing helper reported
register16 as16x although the established conversion is1x. After adding the
helper,120 frames around30.01fps report gain6x, native control96, shutter
32943us. Equal RGB retained; mean61.93/stddev19.88, range0..149. Viewed image
now shows screen/wall boundaries. Scene/display changed between captures,
so no precise photometric before/after claim. Ambient capture only, no IR
emitter activation. A subsequent requested IR raw-role capture was adjusted
by libcamera to632x480 RGB888: saved as ir-quick.rgb, NOT a RAW10 claim.

Fresh front capture returned120 processed1280x960 frames around57.34fps
with existing EV-2, gain3, shutter16511us. Viewed chart is recognizable,
off-centre/clipped left. Default uncalibrated tuning used; no colour pass.

**Meaning/next:** image data obtained from all three sensors on this boot;
front and IR resolve scene structure, rear does not yet. Gain helper fixes a
real IR exposure-unit bug. Calibration deferred at user's request. C02/C03/
C04 stay open for full image/control/lifecycle acceptance. No test-pattern
image substituted for a real scene; no suspend, sound or microphone capture.
Images, RAW rear data and logs saved privately under
`~/Documents/tmp/CAMERA_IMAGES_20261010/`. View front.png, rear.png, ir.png;
ir-before.png retains the pre-fix comparison. Camera capture closed, privacy
LEDs0, CCI suspended, viewer/inhibitor released and locks released.

Validation: signed IPA incremental build, on-device metadata/control match,
equal-channel check and actual image inspection; patch reverse-apply check.
Initial broad build failed on unavailable default-Python jinja2/ply; scoped
simple-IPA build succeeded using the existing project venv. Other patches
and front/rear gain mappings preserved.
