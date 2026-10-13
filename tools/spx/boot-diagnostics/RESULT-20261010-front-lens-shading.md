boxes closed: 3 of 47; newly closed: none.

# Front lens-shading calibration, 2026-10-10

Boot `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. No reboot or camera driver change.

**Changed:** loaded the standard i2c-dev module built incrementally with
`CONFIG_I2C_CHARDEV=m LOCALVERSION=+`; canonical config remains unset. Module
was unloaded afterwards, not installed. No live lens-shading correction added.

**Observed:** vendor front tuning contains matching BPS/IFE 17x13 R/Gr/Gb/B
normal-light meshes and a golden calibration mesh. CamX LSC34 applies
normal * golden / per-unit EEPROM response. The front module descriptor names
st_m24c64 at 8-bit address0xa0 (Linux0x50), with one 221-point uint16 LE mesh
per channel at byte4157,4599,5041,5483. Only these1768 calibration bytes were
read, using two-byte address pointers and <=12-byte reads; no scan or EEPROM
programming. Idle read timed out. An announced front-only RAW stream powered
the module and returned129 frames around57fps; no new image files captured.
The powered EEPROM read succeeded. All four centres are1023; channel ranges
R241..1023, Gr285..1023, Gb287..1023, B301..1023, consistent with response grids.

On the SAME saved uniform-grey RAW, black16, nine80x80 ROIs wholly within the
screen (x200/500/800,y450/650/850), G/R and G/B spatial spread (population
std/mean) is6.018%/8.214% uncorrected. Static3000..3100K mesh gives
5.999%/7.247%; EEPROM-calibrated mesh gives6.532%/6.515%. The3500..4400K
mesh gives6.121%/7.463% static and6.651%/6.702% calibrated. These two regions
bracket saved CCT3378; no guessed trigger interpolation. Offline bilinear
sampling accounts for both sensor flips and the binned crop; this is a
diagnostic approximation to vendor resampling, not production validation.

Viewed the fixed-WB/gamma before/after contact image: correction brightens
edges but residual neutral tint remains. The screen is oblique, off-centre
and clipped on the left; monitor angular/spectral variation remains a
confound. This does not establish a camera colour pass or reject lens shading
for real scenes. Native on-chip LENC is a different/coarser format; not enabled.

**Meaning/next:** per-unit calibration is accessible and structurally valid,
but does not resolve this reference's spatial colour variation. Need a diffuse
neutral reference before selecting live shading correction. C02 remains open
for colour, resume, persistent DT and app/package integration. Scratch grids,
ROI results and viewed image: /tmp/spx-front-20261010/front-{lsc,lsc-golden,
eeprom-lsc}.json, lsc-comparison.json, lsc-contact.png. Stream closed; sensor
runtime suspended, temporary i2c-dev unloaded, device/build locks released.

Continuation preflight: current read-only SLIM `spx_s2idle_retain=N` fails
the normal-sleep helper's loaded-audio gate. Native system suspend otherwise
uses force-runtime suspend, the known unsafe PIO-collapse path. Resume needs
a prepared retention-enabled trial boot. Camera TODO excludes autonomous
reboot; no sleep, additional capture or reboot performed.

Primary implementation reference:
[CamX LSC34 calibration](https://github.com/comprehensive9/vendor_qcom_proprietary/blob/11se/camx/src/hwl/iqinterpolation/lsc34interpolation.cpp).
