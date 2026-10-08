boxes closed: 3 of 47; IDs closed since last report: none.

# Rear colour tuning recovered offline

**Change:** added `tools/spx/camera_tuning.py`, a read-only decoder for the
Surface's existing Parameter Parser V1.3.2 tuning blobs. It follows the
section table, 72-byte symbols, selector ancestry and the CC12/CC13
DRC -> HDR/AEC -> LED -> AEC -> temperature reference chains. It retains
coefficients, trailing region bytes and exact offsets without selecting or
applying a profile.

**Observed:** `tuned.rfc_ov13858.bin` has nine colour-module roots. BPS and
IFE coefficients are identity. Seven IPE selector profiles (3, 21, 30, 48,
57, 75, 84) contain 52 temperature regions, 51 with non-identity matrices.
For example, profile 3's 4800–9000 trigger region has coefficients:
`[2.204985, -1.408550, 0.203568; -0.135290, 1.490566, -0.355270;
0.033720, -1.208660, 2.174937]`. These are decoded vendor values, not
scene-derived gains. Row sums are approximately one.

**Verification:** rear, front and default blobs decode with every colour
reference, array size and selector chain consistent. Maximum rear row-sum
deviation from one is 0.004386. That is a structural sanity check, not
validation of actual colours. No boot, capture or hardware access occurred;
the source scene remains EV boot `fffa14b0-0b51-4b25-ac98-10f9c9b4351c`,
kernel `7.3.0-rc2-spx-mainline-20261004bg+`.

**Meaning/next:** a real vendor matrix-processing lead exists beyond per-plane
white balance. Coefficient order, selector semantics and region-tail meaning
remain unresolved; no candidate was applied. Upstream libcamera's
[simple pipeline](https://raw.githubusercontent.com/libcamera-org/libcamera/master/src/libcamera/pipeline/simple/simple.cpp)
supports CAMSS software processing, and its
[CCM algorithm](https://github.com/libcamera-org/libcamera/blob/master/src/ipa/simple/algorithms/ccm.cpp)
accepts temperature-dependent matrices. Its AWB subtracts black level before
computing ratios. Use that path before claiming calibrated colour. Libcamera
is absent locally and shell downloads cannot resolve external hosts in the
current restricted environment. Physical colours/orientation and C01 supply
ownership remain open.

Commit attempted after verification: Git cannot create the worktree's
`index.lock` because its metadata in `../linux-surface-kernel/.git/` is now
read-only. The helper and associated notes remain uncommitted; no kernel
source or device state changed.
