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
- Missing: real ownership of the `vdda-phy` and `vdda-pll` supplies. No frame
  has been captured on mainline.
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

1. The only thing missing for a frame is the camss node itself, which was
   never enabled on mainline. Change: add camss (cell-identical to 6.18 v23)
   with `vdda-phy` = L5E, `vdda-pll` = L3C, linked to the rear OV13858 on
   CSIPHY2, and build `qcom-camss`. Expect: camss binds, the media graph
   shows ov13858 -> csiphy2, and a 2112x1568 raw frame of a real scene is
   captured. **Confirmed.** Trial `20261008ev`
   (boot `fffa14b0`): colour bars (129/119-stddev, full 16-255) prove the
   sensor -> CSI -> CSID -> VFE -> IOMMU path, and a bright capture has real
   scene structure (87 distinct values, 28.6 column spread). C01 opens:
   supplies are real (L5E/L3C ride the shared UFS/eDP rails) but the person
   must confirm the picture in
   `/var/lib/spx-boot-diagnostics/functional/20261008ev/camera/preview-bright.pgm`,
   and C02/C03 still need repeated start/stop and resume. Do the
   human-session items first; camera item: view that preview.
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
