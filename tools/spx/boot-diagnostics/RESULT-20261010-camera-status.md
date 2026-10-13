boxes closed: 3 of 47; newly closed: none.

# Front camera live implementation, 2026-10-10

Boot: `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`.
Kernel: `7.3.0-rc2-spx-mainline-20261004bg+`. No reboot.

**Changed:** enabled the front OV5693/CSIPHY0 graph through a temporary
live overlay and in source DT, with user-confirmed rotation 180. Native
OV5693 now enables AVDD/DOVDD/DVDD sequentially before clock/reset release.
The default 1296x972 binned mode uses the vendor native readout window and
ISP offsets, with mode-dependent analogue registers. Built and installed
the native sensor module for this release. Private libcamera v0.7.2 now
uses the kernel control's whole-unit analogue gain representation.

**Observed:** original binned capture stalled with either flip; full
resolution worked. Extending the crop ends returned uniform grey frames;
analogue registers alone did not fix the stall. The complete vendor binned
window returns real scenes with both flips. The user confirms orientation
is now correct, but reported green tint in the earlier dark preview.
Corrected-gain lit capture produced 120 processed 1280x960 frames at about
29 fps; white/coloured reference objects were not visible. Preview:
`/tmp/spx-front-20261010/lit.png`. User confirmed this wall was white. A subsequent 120-frame phone-pattern
capture ran about 29 fps but overexposed the screen. Lower phone brightness
returned a visible colour wheel and coloured patches in `phone-dim.png`
(120 frames; final interval 19 fps). User confirms a green tint against the supplied Dreamstime chart. CPU
comparison streamed 120 frames (~57 fps), but the scene moved and cannot
isolate the converter. Both use uncalibrated whole-scene AWB; sensor CCM
is absent. Next: stationary CPU/GPU comparison before changing tuning.

Final driver streamed processed and raw frames, reopened with CCI runtime
power set to auto, and streamed full 2592x1944 after normal module reload.
CCI returned to runtime suspend. No startup timeout was observed in these
final runs, but earlier CCI-on success was not reproducible as a root fix.
Neither cold-start reliability nor system suspend/resume is established.

**Meaning/next:** C02 remains open for physical colour/exposure validation
and resume. C01/C03–C05 remain open; this round did not capture rear/IR.
The front graph exists only in the running overlay and source DT: persistent
boot DTB deployment remains outstanding. The distro libcamera package is
unchanged. No camera frames are committed. Finish the lit reference-scene
check, then coordinate the required resume observation with the user.
