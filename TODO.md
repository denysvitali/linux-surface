# SPX port: what to do next

Boxes closed: 3 of 47 (B02, B03, D02). Run `tools/spx/progress` for the
current number. The order below is set by the user; agents do not reorder it.

## 1. Human session (pending, about 20 minutes)

Ask the user for this first. Steps are in
[PHYSICAL-TESTS.md](tools/spx/boot-diagnostics/PHYSICAL-TESTS.md), one action
each. It decides, or partly decides: I02, I03, I04, I05, I06, D01, U01, N02,
S01, S02, P03. Battery steps are left out (deferred by the user).

## 2. Current blocker: camera first frame (C01, then C02–C05)

- Known: the rear sensor identifies. Receiver SID and mask are resolved.
- Missing: resolved ownership of the `vdda-phy` and `vdda-pll` supplies,
  plus validated scene colours/orientation. EV captured real mainline frames.
- Start from the working 6.18 rear capture: commit `005adbc494a5` in
  `../linux-surface-kernel` and `docs/spx-camera-recon.md` section 7.
- Do not use dummy supplies or guessed RPMh votes. Do not repeat camera audits
  that change nothing.

Supply finding (2026-10-08): no vendor stack switches a regulator for the CSI
receivers. The SQ2 DSDT power tables for MPCS, VFE0, JPGE and CAMP contain no
PMIC vote (only sensors vote LDO1_A/14_A/17_A); Qualcomm's `sm8150-camera.dtsi`
names `pm8150l_l3` 1.2 V for the CSIPHYs but leaves it out of
`regulator-names`, so it is never requested; 6.18 v23 captured all three
sensors with no supply on the camss node. The pins are on the shared PHY
rails: 1.2 V = LDO3_C (named by Qualcomm), 0.88 V = LDO5_E (inferred: it is
the DSI/UFS/PCIe core rail, which carries the CSI 0.9 V nets on the SM8150
reference board; LDO9_E is USB-only). Both are already on for UFS/eDP.

Hypotheses:

5. RAW-to-display rendering omits black subtraction, AWB and transfer.
   **Implemented offline, physical acceptance pending:** `camera_render.py`
   adds full RAW10 decoding, provisional common black subtraction, bounded
   frame-derived grey-world AWB, common exposure normalization and sRGB
   transfer. Twelve fixtures pass, including neutral/primary patches and RGB
   rotations. `camera.py` keeps the diagnostic and adds a rear view rotated
   180° for the upside-down image reported by the user. EV was reprocessed
   (`RESULT-20261008-processing`); no acceptance or calibration claimed.
   Next: confirm the actual scene colours/pose with a known-colour neutral
   target before matrix tuning or a sensor/DT orientation change.

0. The offline renderer corrupts colour and orientation: `/tmp/spxjpg/dem.py`
   writes `(g, r, b)` into RGB and its `rot90cw` is a transpose. Compare a
   standard FFmpeg `bayer_grbg8` conversion of the saved EV bytes, with one
   common percentile stretch, and verify with a known-colour Bayer fixture.
   **Confirmed offline:** known GRBG colours and padded RAW10 rows decode
   correctly; EV matches the direct FFmpeg conversion. Fixed `camera.py` to
   produce a demosaiced, common-percentile PPM (`RESULT-20261008-render`).
   Physical orientation and scene colour still need the user's confirmation.

1. The only thing missing for a frame is the camss node itself, which was
   never enabled on mainline. Change: add camss (cell-identical to 6.18 v23)
   with `vdda-phy` = L5E, `vdda-pll` = L3C, linked to the rear OV13858 on
   CSIPHY2, and build `qcom-camss`. Expect: camss binds, the media graph
   shows ov13858 -> csiphy2, and a 2112x1568 raw frame of a real scene is
   captured. **Confirmed.** Trial `20261008ev`
   (boot `fffa14b0`): colour bars (129/119-stddev, full 16-255) prove the
   sensor -> CSI -> CSID -> VFE -> IOMMU path, and the demosaiced bright frame
   is a real scene (`RESULT-20261008ef`). The user identified it as the **back**
   camera and rejected the earlier scene description and colours. The EF
   render analysis is superseded by `RESULT-20261008-render`: its custom
   converter swapped R/G and transposed an image labelled as a rotation.
   The standard GRBG preview preserves sensor pixel orientation and applies
   one common percentile stretch; it has no white balance or calibration.
   The previous mode-flip explanation is also unsupported: `0xab ^ 0xa8`
   is `0x03`, so bits 3/4 do not change between those values. The mode tables
   match the working 6.18 source. Do not infer a sensor flip from the faulty
   render or guess a white balance. Next: the user confirms actual colours
   and tablet pose for the corrected EV preview, then choose a supported
   orientation/calibration change. Do the human-session items first.

2. If camss binds but STREAMON hangs or no frame arrives: compare the live
   CSIPHY/CSID register programming and clock rates with the 6.18 run
   (`camss-video.c` bisect knob, 400/300 MHz PHY rates).
3. If the frame is empty: IOMMU SID 0x0a00/0x04e0 fault or buffers never
   written; check `arm-smmu` faults and the CSID test generator path first.

## 3. Next blocker: playback PCM close and reopen (A01–A03)

- Known: the first playback cycle passes. After close and reopen the output is
  silent although the DSP consumes data and clock writes succeed (trials CB,
  DE, DG). The desktop works today only by holding one stream open.
- Do not destroy parked DSP sessions on a live boot.
- No other audio or microphone work until this is fixed.

## Parked (not finished; needs a new idea or the user's decision)

| Item | Why |
|---|---|
| D03 video decode | Venus core start times out, 8 boots |
| B07 accelerators (CDSP) | 3 boots without a usable result |
| P05 automatic thermal response | Load never reaches the trip points |
| N03, N04 cellular and GNSS | Modem needs real provisioning; no SIM service |
| I01 touch startup reliability | Works on recent boots; repeat count needs B01 |

## Needs a fixture or the user

- U01, U02, U04: USB stick, charger and dock on each port and orientation.
- U03: a person confirming the external monitor shows a picture after replug.
- A04: a USB-C or Bluetooth audio device.
- P01, P02 and the battery part of P03: deferred by the user.

## Last

B01, R01, R02 and F01–F04 (repeat boots, diagnostics, final candidate and
regression) come after the feature boxes.
