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

6. The front OV5693 and IR OV7251 only need the v23 wiring that worked on
   6.18 (front: CCI0 bus 1, MCLK2/GPIO15, reset GPIO12, CSIPHY0 two lanes;
   IR: CCI0 bus 0, MCLK3/GPIO16, enable GPIO23, CSIPHY3 one lane), and the
   colour/processing gap is the missing ISP stage, which libcamera's software
   ISP supplies. Change: commit `23848bdb15dd` (DT, sensor modules) plus
   `UDMABUF`/`DMABUF_HEAPS` and a bounded `cam` step. Expect: all three
   sensors in the graph, two informative raw captures each, and `cam -l`
   listing three cameras with 20 processed frames each.
   **Partly refuted (ew, boot 9366f2e2).** Front OV5693 fails on CCI bus 1
   at identify (`master 1 queue 0 timeout`, reg 0x300a -110); IR OV7251
   probes but has no graph link; rear logs no probe; no frames. See
   `RESULT-20261008ew.md`.
7. Hypothesis: front fails only because gpio19/20 are missing from the CCI0
   pinctrl. **Refuted (ex, boot 028f358f).** Same timeout with the pins added;
   MCLK2 and the three rails are on during the probe. See `RESULT-20261008ex.md`.
8. **Refuted: H-reset.** `ov5693_sensor_powerup()` releases reset before
   identify, so the output-low `cam_front_reset` pin does not hold the sensor.
   Source reading only; no trial needed.
9. **Confirmed: H-async (fa, boot `b1da04a0`).** With the front node disabled
   and its CSIPHY0 endpoint removed, the rear and IR link to CSIPHY2/CSIPHY3 and
   stream. Camss waits for every CSIPHY endpoint's remote. See
   `RESULT-20261008fa.md`.
10. **Answered: H-rear (ez).** The rear OV13858 probes silently. Its link was
   missing because of the camss notifier, not the sensor. See
   `RESULT-20261008ez.md`.
12. **Refuted: v23 extra CCI pads (fb, boot `1a5a2dde`).** gpio31-34/41/42 as
   `cci_i2c` did not fix front bus 1. Untested: enable CCI1-3 as v23 did.
13. **Refuted: CCI1 enabled (fc, boot `b1b3e2d9`).** Front bus 1 unchanged. No
   untested hypothesis left for the front OV5693; rear and IR work with it off.
11. **Open: scene.** Rear and IR scene frames are flat and dark (fa). Check
   the physical setup with the user before any sensor or ISP change.

5. RAW-to-display rendering omits black subtraction, AWB and transfer.
   **Implemented offline, physical acceptance pending:** `camera_render.py`
   adds full RAW10 decoding, provisional common black subtraction, bounded
   frame-derived grey-world AWB, common exposure normalization and sRGB
   transfer. Twelve fixtures pass, including neutral/primary patches and RGB
   rotations. `camera.py` keeps the diagnostic and adds a rear view rotated
   180° for the upside-down image reported by the user. EV was reprocessed
   (`RESULT-20261008-processing`); no acceptance or calibration claimed.
   **Controlled real-frame comparison:** reused this renderer on the archived
   6.18 rear RAW10 frame; held black=64, white=11.5 and sRGB transfer fixed.
   Changing only grey-world gains from unity to R=1.36186/B=1.52247 reduced
   the baseline green cast (`RESULT-20261008-white-balance`). Strong noise
   and missing physical colour validation remain; no vendor matrix applied.
   Next: confirm the actual scene colours/pose with a known-colour neutral
   target before matrix tuning or a sensor/DT orientation change.
   Live-trial attempt cannot start in the current restricted session:
   known-good `6.18.3-1-surface+`, boot `5c85d8e5-876a-4c84-8c48-93f27164d80b`;
   candidate build directory unreadable, camera nodes unavailable, and sudo
   rejected by `NoNewPrivs=1`. Needs restored device-session access; standing
   reboot authorization remains valid. No trial was selected or capture run.

4. Residual colour error may require the vendor's colour matrix rather than
   per-plane gains. Decode the rear tuning blob's CC12/CC13 reference chains
   and recover the temperature-dependent coefficient sets with their module
   and profile IDs. Expect non-identity matrices in an enabled processing
   stage. **Coefficients recovered:** rear BPS/IFE sets are identity; IPE
   has seven selector profiles, 52 temperature regions, 51 non-identity.
   `camera_tuning.py` follows all references and preserves selector/trigger
   chains (`RESULT-20261008-colour-tuning`). This supports a missing ISP
   processing lead; it does not prove the scene colour cause or RGB ordering.
   Next: establish selector semantics/coefficient ordering and use libcamera's
   CAMSS software ISP with black-level correction and AWB before colour-matrix
   tuning. Libcamera is absent locally; shell downloads are blocked by the
   current restricted environment. No guessed gains or kernel colour patch.
   **Matrix-only trial negative:** applied profile 3 / symbol 421 / region 0
   to the accessible 6.18 rear RAW10 frame, preserving all ten bits. Both RGB
   and BGR interpretations intensified the green cast; about 30% of channel
   samples became negative before clipping. This selected matrix alone is
   insufficient (`RESULT-20261008-matrix-test`); other profiles and the full
   exposure/AWB pipeline remain untested. EV is inaccessible in this sandbox.

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
