boxes closed: 3 of 47; newly closed: none.

# Front vendor colour correction, 2026-10-10

Boot `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. No reboot, kernel or module change.

**Changed:** added an explicit daylight simple-IPA tuning option using the
front OV5693 vendor CC13 IPE matrix; no guessed WB gains. Distro package and
private default fallback unchanged. File is tools/spx/libcamera/tuning/daylight/
simple/ov5693.yaml. Coefficients are from profile3/symbol377/offset322256,
CCT4600..10000K; the corresponding regions in profiles21/30 are identical.

**Observed:** vendor CC13 conversion maps stored row-major RGB to hardware
GBR ordering; schema defines9 matrix coefficients and3 offsets. Front offsets
are zero; BPS/IFE matrices are identity. Normal-light matrix applicability
outside this scene, AEC/lux selection and CCT transition interpolation are
not validated. Offline same-RAW test using the2750..3100K row makes the saved
chart more saturated;1.648% of channel values become negative before clamp,
none exceed white. This is diagnostic, not a general tuning decision.

GNOME Night Light was active2700K. Initial matched attempts captured noise
because the displays were blanked; discarded as colour evidence. User asked
agent to unlock: active session2 unlocked, normal idle inhibitor held during
subsequent captures. Night Light on/off changes AWB R/B1.148/2.676 ->1.822/1.653,
CCT3176 ->5059K, gain4 ->2. Both valid240-frame captures preserve chart detail.
Night Light restored after each bounded run.

With Night Light off, daylight CCM capture completes240 frames at about29fps;
metadata reports the exact matrix, CCT5014K, R/B1.803/1.663, gain3, shutter16511us,
EV-2. Viewed the result: colour wheel/magenta more saturated, but spatial
neutral tint remains. Gain differs from baseline2, confounding brightness.
Screen ROI near-clipping0% ->0.048%; no full colour accuracy claimed.
Previews /tmp/spx-front-20261010/{nightlight-valid-off,vendor-daylight}.png.

**Meaning/next:** missing CCM is a supported colour-quality lead; this
explicit daylight option works through the native processing stage. Need user
colour assessment and a suitable neutral illumination/reference to resolve
spatial colour variation. Full automatic tuning/AEC/CCT selection, cold boot,
resume, persistent DT and app/package integration remain; C02 stays open.
Capture closed, CCI suspended, privacy LED0, viewer/inhibitor released.

Primary implementation references (downloaded into /tmp, not redistributed):
[CC13 conversion](https://github.com/comprehensive9/vendor_qcom_proprietary/blob/11se/camx/src/hwl/iqsetting/cc13setting.cpp),
[CC13 schema](https://github.com/comprehensive9/vendor_qcom_proprietary/blob/11se/chi-cdk/api/chromatix/XSD/isp/cc_1_3_0.xsd),
[CC13 selection](https://github.com/comprehensive9/vendor_qcom_proprietary/blob/11se/camx/src/hwl/iqinterpolation/cc13interpolation.cpp).
