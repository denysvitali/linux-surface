boxes closed: 3 of 47; newly closed: none.

# Fresh camera image check, 2026-10-11

Boot `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. User requested a fresh check. No code,
driver, graph, illumination, display or boot change. Calibration deferred.

**Observed:** announced sequential captures,120 processed frames per sensor,
using the existing signed private libcamera CPU software ISP. Viewed each PNG.
Rear1280x960 now resolves a room scene, including wall/furniture/cables;
still dim/noisy, around30fps, final shutter33306us/gain23.640625. Yesterday's
nearly flat image no longer describes the current view. This establishes
recognizable rear scene data, not correct colours/orientation or lifecycle.

IR632x480 around30fps returns equal RGB and dim vertical scene boundaries;
final shutter32943us/gain6x. IR illuminator remained off.
Front1280x960 around56fps shows a dim/noisy wall boundary. First capture
used the prior chart's EV-2, final gain33; an ordinary EV0 capture reaches
gain127 at16511us and remains dim/noisy. Neither is a colour reference.
All requested captures completed normally; no repeated tuning variants.

**Meaning/next:** all three sensors deliver fresh image data; rear now has
a recognizable scene. Full C02/C03/C04 acceptance remains open. Calibration
stays deferred. PNGs/logs/metadata saved under
`~/Documents/tmp/CAMERA_IMAGES_20261011/`; front-minus2 preserves the earlier
exposure setting separately. No camera frames added to git. Capture closed,
privacy LEDs0, CCI suspended, device lock released. No audio, microphone,
emitter, suspend or reboot action.
