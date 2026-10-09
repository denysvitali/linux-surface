# SPX port: what to do next

Boxes closed: 3 of 47 (B02, B03, D02). Run `tools/spx/progress` for the
current number. The order below is set by the user; agents do not reorder it.

## 1. Human session (pending, about 20 minutes)

Ask the user for this first. Steps are in
[PHYSICAL-TESTS.md](tools/spx/boot-diagnostics/PHYSICAL-TESTS.md), one action
each. It decides, or partly decides: I02, I03, I04, I05, I06, D01, U01, N02,
S01, S02, P03. Battery steps are left out (deferred by the user).

2026-10-09 speaker session: user requests microphone feedback and no human
tests. Leave the physical session pending; do not substitute synthetic checks.

## Current blocker: speaker playback close and reopen (A01–A03, user requested 2026-10-09)

- First playback works; reopened playback is silent despite real DSP
  WRITE_DONE and successful clock writes (CB/DE/DG). The 6.18 stereo baseline
  kept its PCM open and does not establish acoustic reopen.
- Preserve parked DSP mappings. Corrected APR headers now allow playback
  CLOSE/OPEN, but UNMAP and AFE STOP remain unsafe/unverified. No unrelated
  audio/microphone variations.

1. **H-WSA-reset, refuted as a sufficient fix (WR):** the amp needs the Windows digital reset at
   teardown followed by complete native initialization. WQ boot `183438a1`
   never reached playback: its legacy `spx_write_only=1` setting was rejected
   by the native stereo guard. Correct that pairing in the native driver,
   retain `spx_write_only=0`, and run the existing two-PCM microphone test.
   WR boot `f7854ae1` detected both speakers initially, then reopened left
   fell to the noise floor (0.262 versus 0.233 RMS) despite successful native
   reinitialization. See `RESULT-20261009wr.md`. Do not repeat this reset trial.
2. **H-WCD-reset, refuted as sufficient (WT):** WCD keeps its SLIMbus playback stream active,
   but DAPM still resets RX7/RX8 on close. Suppress only those interpolator
   resets with `spx_skip_speaker_reset=1`, leaving clock/PA shutdown intact.
   Expected: existing microphone reopen test detects both channels on its
   second PCM. This switch is writable live; do not destroy parked DSP sessions.
   WS boot `1436256e` completed baseline checks but ended uncleanly with no
   acoustic result, return record or retained crash dump. The user does not
   know the restart cause. See `RESULT-20261009ws.md`; do not count this as
   an acoustic failure or blindly re-arm the same image.
   WT boot `2c78c7c8` stayed available with automatic audio omitted. The manual
   reopen test detected both initial channels, but second left was absent
   (0.097 RMS versus 0.340 baseline). Both reset skips were logged.
3. **H-RX-clock, live restoration failed; prevention untested:** stopping
   interpolator clocks while retaining SLIM playback may disrupt the path.
   Use a live module to force only INT7_CLK/INT8_CLK supplies through DAPM,
   preserving the card and DSP mappings. Expected: the existing acoustic
   reopen test detects both channels across close; unload restores the votes.
   WT: loaded `spx_audio_rx_hold` on the same boot; both supplies stayed on.
   Guarded parked FIFO recovery succeeded, but the first left tone on the
   already-failed route was absent (0.204 RMS versus 0.449 baseline). Module
   unloaded and votes restored. This does not test prevention before the first
   playback on a fresh DSP session. Do not repeat restoration on this session.
   Older findings (`spx-win-parity-knobs-implemented.md`, section 49.1) show
   RX0 overflow is a self-masking boundary flag, also present with audible
   output. It does not establish this hypothesis or justify a port reset.
   WU boot `876ae499` held both clocks before any PCM. Its first run stopped
   before tones: COMP7/8 mixer switches were off but hardware enable bits were
   still set. Their setter updates only software until the next clock event,
   which retention suppresses. Clearing the two bypass bits live preserved
   the clock votes; a retry consumed 168/168 buffers but its first left tone
   was absent (0.473 versus 0.342 baseline). No audible initial baseline was
   established, so prevention remains inconclusive. Fix the native disable
   control to apply bypass immediately before the first PCM, then repeat this
   same hypothesis on a clean start. See `RESULT-20261009wu.md`.
   WV boot `d717b2ee` included that fix and completed baseline collection,
   but ended uncleanly before audio testing. No return record or crash dump
   survived; restart cause is unknown. See `RESULT-20261009wv.md`. This is
   neither a speaker failure nor a pass, and the image must not be blindly
   re-armed unchanged.
4. **H-ASM-flush, refuted as sufficient (WT):** retained playback reuses an EOS-ended session
   without the PAUSE/FLUSH used by Qualcomm's downstream same-stream reuse.
   Use a one-shot live module with exported q6asm APIs, holding the PCM open
   mutex and requiring no open playback owner. Pause/flush playback only;
   no CLOSE/UNMAP/RUN or callback replacement. Expected: the unchanged
   microphone reopen test restores its first tone; a second-close failure
   would then support integrating flush at each retained prepare.
   PAUSE initially timed out with a reply to unregistered service 16.
   `q6asm_add_hdr()` leaves `src_svc` uninitialized on stack commands while
   APR preserves nonzero source IDs. After initializing it through a live
   ASM-only header correction, PAUSE/FLUSH both ACKed status 0, but the first
   left tone remained absent (0.658 versus 1.172 baseline).
5. **H-ASM-native-close, refuted as sufficient (WT):** the proven header defect also affects
   CLOSE, invalidating earlier attribution of all CLOSE timeouts to firmware.
   With corrected headers and no PCM owner, pause/flush then CLOSE playback;
   only if acknowledged, recreate the same playback format using retained
   memory mappings. Do not UNMAP, alter capture or unload the card. Expected:
   the existing acoustic test restores its first stereo playback. Stop on
   any command failure instead of discarding the retained client.
   CLOSE/OPEN/format all ACKed status 0 on the same boot. The first tone
   remained absent and WRITE_DONE stopped (158 submissions, 0 completions).
   Remapping session 1 to the retained speaker COPP through the native ADM
   API restored real DSP completions (153/153, zero fallback), but no tone
   (0.350 RMS versus 0.383 baseline). Retained DMA mappings still work;
   native ASM restart plus matrix reconnection does not restore sound.

User reminder (2026-10-09): minimize reboots; use module reloads wherever
possible. Current boot `f3702ad4` is known-good 6.18 after WV ended before its
test. No audio runs on recovery and no next boot selected. The mainline
compander-control correction is committed and builds, but needs hardware
validation. First resolve the interrupted boot; do not blindly re-arm WV.
No card/Q6-stack unload or AFE STOP: retained mappings outlive PCM opens and
AFE STOP has frozen the platform. Keep the existing reopen test.

## GTK window corruption (D01/D02, workaround confirmed 2026-10-09)

1. **Confirmed: H-renderer (FH, boot `1dd03623`).** The corrupted Text
   Editor lacked `GSK_RENDERER=opengl` and loaded Turnip Vulkan; Console and
   GNOME inherited the existing systemd OpenGL setting. The user confirmed
   the OpenGL editor is clear. Added the same setting to `/etc/environment`
   for PAM launches and reopened the editor with its saved draft intact.
   This is a working accelerated workaround, not an underlying Vulkan fix.
   See `RESULT-20261009-graphics.md`; full D01 acceptance remains open.

Graphics stopping point: the reported window corruption is resolved through
OpenGL. Continue the pending human session; no additional successful OpenGL
checks or kernel trial are needed. Vulkan investigation needs a specific
request for that path.

## 2. Camera first frame (parked for user-requested graphics fix; C01, then C02–C05)

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
11. **Answered: scene (fd, boot `89f87251`).** Lit scene: rear and IR show real
   frames; the dark frames were the scene. Open: user confirms colours and IR
   orientation, then resume/repeat start-stop. See `RESULT-20261008fd.md`.
14. **Rear exposure (fe/ff).** Washed out = default exposure at the black level;
   libcamera AE converges over about 90 frames (mean 17 -> 80); DT rotation 180
   reported to apps. Open: physical image validation and full lifecycle.
   Missing black correction was refuted in hypothesis 15 below.
   See `RESULT-20261008ff.md`.

15. **Refuted without a boot: missing rear black correction.** FF's processed
    metadata already reports `SensorBlackLevels = [4096,4096,4096,4096]`,
    equivalent to RAW10 level 64. The installed fallback includes BlackLevel,
    AWB and AGC. A duplicate tuning file cannot fix the reported quality gap.
16. **IR application integration (confirmed, FG):** libcamera rejected OV7251 because mandatory
    `V4L2_CID_ANALOGUE_GAIN` (0x009e0903) is absent; the driver exposes the
    same sensor gain as `V4L2_CID_GAIN`. Change that control ID, leaving the
    gain range and register writes unchanged. Expect: the missing-control
    error disappears and IR progresses to format negotiation in `cam -l`;
    then test whichever real format libcamera exposes. **FG, boot `5c0eb87d`:**
    IR is listed and streams 90 native RAW10 frames; RGB processing is missing.
    See `RESULT-20261009fg.md`.
17. **IR processed format (confirmed, FG):** libcamera's software ISP rejected monochrome
    `R10_CSI2P`. Add scalar RAW10 conversion and equal-channel statistics to
    its CPU path, using the existing black/exposure processing. Expect: real
    IR RGB output has equal channels and is written by the normal `cam` app.
    **Verified:** six offline format/gamma fixture cases; then 90 real 632x480
    BGR888 IR frames near 30 fps, with identical RGB channels. Rear GPU
    capture remains functional. Patch: `tools/spx/libcamera/`; private build
    `/var/tmp/spx-libcamera-0.7.2/build`, package integration pending physical
    image validation. Open: normalized gain helper, IR mounting metadata,
    illuminator/control applicability and full lifecycle. See FG result.

Current stopping point (FG): returned to known-good boot `276d70cb`; trial
payloads and units removed. Need the user's IR scene/orientation check and
the pending human session. Front hypotheses are exhausted; supply ownership
needs authoritative wiring evidence. Keep C01–C05 open; package integration
waits for physical image validation.

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
