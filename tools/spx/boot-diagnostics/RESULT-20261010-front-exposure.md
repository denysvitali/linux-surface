boxes closed: 3 of 47; newly closed: none.

# Front image exposure and RAW colour checks, 2026-10-10

Boot `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. No reboot or kernel/module changes.

**Changed:** private libcamera simple IPA now accepts standard ExposureValue
(-4..4 EV), rescales the black-subtracted metering histogram and reports EV
in frame metadata. EV0 retains the existing mapping; each new session starts
at EV0. Patch 0003 is in tools/spx/libcamera; distro package unchanged.

**Observed:** inspected saved RAW and processed images. The monitor is
oblique/off-centre, cut off on the left, with substantial dark top/right
surround. Saved low-gain RAW has no clipped pixels, but its viewer had exited.
Fresh bounded neutral/primary-pattern captures establish expected BGGR channel
responses. In red ROI RAW R119.81/G67.71/B37.35, green R80.85/G264.01/B73.39,
blue R39.80/G53.51/B59.53 (black level16). This argues against a Bayer swap.
Uniform grey screen has spatially different neutral ratios; this measurement
does not separate screen viewing-angle effects, illumination and lens shading.
CPU/GPU chart comparison from handoff has matching tint, refuting a GPU-only
explanation as sufficient.

Stationary chart CPU captures: EV0 180frames, gain20; -2 EV 240frames, gain5;
both shutter16511us, about57fps. Screen ROI x40..859/y300..899 near-clipping
(any RGB channel >=250) falls56.789% ->0%. White ROI RGB255/254/255 becomes
162.75/162.60/164.40. Viewed both: chart detail returns; colours remain muted.
Grey ROI changes141.41/154.92/145.74 ->75.33/80.94/87.07, so neutral tint is
not globally solved. New session without a script reports EV0 again.
Final incremental build and patch reverse-apply check succeed.
Previews: /tmp/spx-front-20261010/ev-{zero,minus2}.png; raw data remain in /tmp.

**Meaning/next:** exposure compensation works for this framing, not general
camera calibration. No guessed WB or CCM applied. Existing parser extracts
front identity BPS/IFE and three IPE profiles, each with5 non-identity of6
regions; selection/ordering assumptions remain unvalidated. Need user colour
assessment of the -2 EV preview before choosing the remaining colour fix;
spatial calibration needs a suitable reference/illumination. C02 stays open
for colour, full usability, resume and persistent DT/package deployment.
All captures closed; privacy LED0; CCI suspended; temporary viewer stopped.
