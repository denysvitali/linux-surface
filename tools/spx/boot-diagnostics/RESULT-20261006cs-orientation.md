# CS: reported upside-down image during left tilt

Boot `a0a7c1af-7a7a-445b-9f47-df3e7c48d242`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Observation:** user reports "Tilted left. It's upside down." At11:48CEST,
a bounded native active-user client reports `left-up`, tilt`vertical`.
A fresh3s accelerometer stream returns finite measurements dominated by
X≈+9.88m/s², Y≈+0.09, Z≈+0.14 and exits0 with successful disable.
Mutter's internal-panel logical transform is1 (90°); orientation-lock isfalse.
No rotation setting or mount matrix was changed during collection.

**Meaning:** sensor events reach the desktop, but this human observation does
not establish correct physical mapping. The current private library explicitly
uses identity compatibility fallback for the invalid firmware placement matrix.
S02 physical rotation remains open; accepted stream/API subfeatures retain their
scope. It remains unclear whether "upside down" describes the image or device.

**Known mapping:** the retained Windows LSM6DSO config already supplied to SSC
maps x→+y, y→+x, z→+z. Applying the permutation again could duplicate firmware
transformation. Its placement values do not provide a valid display matrix;
neither installed nor upstream sensor hwdb supplies a Surface mapping.

**Next:** clarify the reported pose, then record two labeled positions as viewed
facing the screen: camera edge up in ordinary landscape, then camera edge left
in portrait. Their gravity vectors/native orientation determine in-plane signs
and permutation. A flat screen-up pose separately establishes Z if needed.
Do not guess a sign flip from the ambiguous observation or disable auto-rotation
to hide it. The clarification question is pending; TPM work continues.

Evidence: `/var/lib/spx-boot-diagnostics/functional/20261006cs/orientation/`
native/accelerometer logs and Mutter state; retained Windows config
`8180_cls_lsm6dso_display.json`.
