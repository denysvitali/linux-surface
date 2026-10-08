boxes closed: 3 of 47; IDs closed since last report: none.

# Rear camera display processing (offline, WIP)

**Source:** saved EV high-byte GRBG, boot
`fffa14b0-0b51-4b25-ac98-10f9c9b4351c`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. No new capture, boot or kernel change.

**Changed:** `camera_render.py` decodes all ten packed RAW bits with row
padding, demosaics linear GRBG to RGB48, subtracts a configurable common black
pedestal, computes bounded grey-world AWB, applies common exposure normalization
and sRGB transfer. `camera.py` retains its diagnostic preview and adds a separate
processed `view*.ppm`; the existing trial installer includes the renderer.
The rear view has a true RGB 180° viewing rotation based on the user's prior
upside-down observation, not a claim about mounting metadata or flip registers.

**Observed:** 12 offline tests pass: RAW10 low bits/padding, exact GRBG colour
order, black subtraction/AWB, primary and neutral patches, transfer reference
points, non-square rotations, partial-frame selection and error preservation.
Four trial-module tests and 25 existing preflight tests pass. The saved EV
image was reprocessed to a 2112x1568 JPEG with RGB gains
`[1.06872, 1.0, 1.85002]`, computed from that frame rather than entered by hand.
The archived input has only eight significant bits; the tool cannot restore its
lost low bits. No user confirmation of this processed output has been received.

**Meaning:** the previous raw-to-display path omitted basic ISP stages; the
processed preview now implements them. Grey-world is a scene-derived heuristic
and can fail on a scene dominated by one colour. Black=64 RAW10 counts is a
provisional simple-ISP default consistent with archived black-level evidence,
not established sensor calibration. No vendor colour matrix is applied: its
mode/channel conventions remain unresolved. The transfer curve alone does not
transform sensor primaries to calibrated sRGB.

**Next:** physical acceptance of colours and upright orientation using an
upright known-colour/neutral target and recorded tablet pose/illumination, then
normal application integration and remaining camera lifecycle tests. C03 and
C05 are not complete. Keep the raw and diagnostic views alongside the processed
image; do not change sensor flips on the basis of the earlier faulty renderer.
