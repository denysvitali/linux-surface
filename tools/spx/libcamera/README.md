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
