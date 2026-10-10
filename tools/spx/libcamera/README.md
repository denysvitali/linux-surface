# Surface Pro X monochrome software ISP

`0001-softisp-mono-raw10.patch` applies to upstream libcamera **v0.7.2**.
It converts CSI-2 packed monochrome RAW10 to RGB/BGR with equal channels,
retains all ten input bits, and provides scalar statistics for the existing
black-level and exposure algorithms. Monochrome sensors select the CPU
converter; colour Bayer sensors retain the configured GPU/CPU choice.
There is no IR colour matrix or sensor calibration in this patch.

Verified on mainline trial FG: 90 processed IR frames, 632x480 BGR888, near
30 fps, with equal RGB channels. Rear GPU capture still produced 90 frames.
See [the result](../boot-diagnostics/RESULT-20261009fg.md). The sensor gain
helper and camera properties remain incomplete; reported IR analogue gain
uses the fallback's raw register units.

The private source/build used for verification is
`/var/tmp/spx-libcamera-0.7.2/{,build}`. It retains the distro libcamera version
and does not install over the package. On the mainline candidate with rear
and IR enabled, run its application with:

```
sudo /var/tmp/spx-libcamera-0.7.2/build/src/apps/cam/cam -l
```

The returned known-good boot has no camera nodes; listing there cannot
reproduce FG's capture.

Reproduction: apply the patch to v0.7.2, configure Meson with
`-Dpipelines=simple -Dipas=simple -Dsoftisp-gpu=enabled -Dcam=enabled
-Dtest=true`, and disable optional applications/bindings not being built.
Build `src/apps/cam/cam`, `src/ipa/simple/ipa_soft_simple.so.sign`,
`src/libcamera/proxy/worker/soft_ipa_proxy` and `test/mono10p` with Ninja.
Run `meson test -C build mono10p --no-rebuild` before real capture. The fixture
checks packing/low bits, poisoned row padding, cropping, first-frame gamma,
RGB/BGR/32-bit output and equal-channel statistics using memory-backed frames.

Upstream [software ISP source](https://github.com/libcamera-org/libcamera/tree/v0.7.2/src/libcamera/software_isp).

Front OV5693: `0002-ov5693-gain-units.patch` corrects the sensor helper for
the kernel control's whole-unit gain representation (the driver performs
the register scaling). Apply after the monochrome patch and rebuild
`src/ipa/simple/ipa_soft_simple.so.sign`. The private build contains both
patches; the distro package is unchanged. Lit front capture on 2026-10-10
produced 120 processed frames at about 29 fps. Physical colour validation
and suspend/resume remain open; see RESULT-20261010-camera-status.md.

Front exposure: `0003-softisp-exposure-compensation.patch` adds the standard
`ExposureValue` request control (-4..4 EV) to the simple IPA. Apply after
patches 0001/0002 and rebuild `src/ipa/simple/ipa_soft_simple.so.sign`.
It rescales the black-subtracted metering histogram; EV0 retains the original
mapping. Each new session defaults to EV0; it reports the request in metadata.
No white balance multipliers, sensor registers or colour matrices are changed.

For a bright screen surrounded by darkness, pass this capture configuration
with the existing cam option `--script=/path/to/exposure.yaml`:

```yaml
frames:
  - 0:
      ExposureValue: -2.0
```

On the stationary front-camera chart, EV0 used gain 20 and -2 EV used gain 5,
both at 16511us. Near-clipping (any RGB channel >=250) in the visible screen
ROI fell from 56.8% to 0%; chart details returned. This is user-selected exposure
compensation, not general colour calibration. Colours remain muted and neutral
patch ratios vary spatially. Full C02 acceptance remains open.
See [the result](../boot-diagnostics/RESULT-20261010-front-exposure.md).

The explicit `tuning/daylight/simple/ov5693.yaml` option enables the front
sensor's vendor normal-light daylight CCM through the existing simple IPA.
Set `LIBCAMERA_IPA_CONFIG_PATH` to the absolute `tuning/daylight` directory
when launching the private cam application. Keep `LIBCAMERA_SOFTISP_MODE=cpu`
for the verified path. The single matrix is for the validated daylight scene,
not a complete temperature/exposure-dependent tuning profile; it is not loaded
by default. Source coefficients are identical across three front IPE profiles
in the 4600..10000K region; offsets are zero and RGB ordering is supported by
vendor conversion code. BPS/IFE matrices are identity.

Verified: 240 front frames around29fps with the requested matrix in metadata;
chart colours are visibly more saturated, but neutral ratios vary spatially.
GNOME Night Light was2700K; temporarily disabling it changed the scene estimate
from3176K to5059K. Restored afterward. Capture viewing requires the desktop
unlocked and displays on; hold a normal GNOME idle inhibitor during a bounded
capture. Screen-off noise is not a colour result. See
[the colour result](../boot-diagnostics/RESULT-20261010-front-colour.md).
