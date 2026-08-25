# Surface Pro X (SQ2, sc8180x) — speaker bring-up

## The goal

Make the built-in speakers work **fully**: clean audio, at maximum volume if wanted,
from both speakers, surviving normal use (not just one stream after a cold boot).

## Where we are (2026-08-24) — SPEAKER ALIVE; provenance corrected, objective forensics ready

The 2026-08-22 "hardware failure" verdict (PROGRESS §35/§36) is **OVERTURNED**:
2026-08-23 01:01 a green-gated four-phase localize on **AC at 50%** produced
clearly audible static from the right speaker, on byte-identical software to
every run judged dead (PROGRESS §39; `/tmp/spx-noise-localize-20260823-010005.log`).
The silence has an EXTERNAL gate. A naive power-state gate is REFUTED: the
15:56–16:03 A/B block was transcript-confirmed audible ON BATTERY at 44–46%,
and the silent evening ran at higher loaded voltage than the audible afternoon
(§39 honest-strains).

**§47 corrections (2026-08-24) — read before trusting any loudness trend:**

- The "noon 08-22 LOUD" anchor has NO user testimony (only "Continue"
  messages); the last confirmed tone is **15:58:27 CEST 08-22**, and every
  post-noon listen was an ~18 dB quieter carrier (-19.9 dBFS vs harness -2 dBFS).
  Loud-vs-faint comparisons across that boundary are VOID.
- Tone behavior at fixed config is NON-MONOTONE within minutes
  (tune → silent → tune, 14:50→15:58 08-22): intermittent contact competes
  with the §46 two-factor model (powered-hours soak × SOC-floor policy).
- Overdrive refuted: GPIO parked through the decay window, ~13 min total
  PA-on over four days, OCP enabled.
- **LDO14E rail gap:** Windows PEP votes `ldoe14` 1.8 V HPM for the codec;
  Linux DT never declared it and SPMI shows it OFF (`EN_CTL=0x00`). Constant
  off ⇒ baseline-marginality candidate, not the decay cause. Parity DTB
  STAGED but uninstalled:
  `sc8180x-surface-pro-x-speaker-ldo14e.dtb` (ldo14 1.8 V HPM always-on).
- WCD GPIO pins 3/4 float high since 08-11 (dir=0x06 val=0x18); Flex 5G uses
  wcdgpio pin 4 for its speaker rail. qcauddev scan found no writes there —
  semantics unknown, READ-ONLY only.
- Objective forensics WITHOUT a listener were attempted on 2026-08-24
  (`SPX_READBACK_ONLY=1 SPX_REG_READS=...` → §47-F): **NEGATIVE — WSA881x
  slave register reads are UNOBSERVABLE from APPS** even with a
  proven-attached amp (dedicated dev0 readback rc=4; spx_wsa_seq -EIO/zero
  across 24 regs). Do NOT spend another boot on amp register dumps. The only
  remaining objective window is E6 VI-sense via ADSP; everything else is
  listening-gated.
- Arming an automatic autotest run requires BOTH `grub-editenv set
  next_entry=<id>` AND the state file `/var/lib/spx-speaker-autotest/armed`
  (unit ConditionPathExists); GRUB alone boots but the unit silently skips.
  Keep test-env coherent with the booted entry's cmdline (stale expectations
  abort step [0]). `grub-editenv` needs the EXPLICIT FILE FORM
  (`sudo grub-editenv /boot/grub/grubenv …`) — the bare form silently fails
  to WRITE on this machine while reads fall back; verify after every set.
- **Whole-boot silence is now OBJECTIVE** (§50, 2026-08-25): mic-scored
  silent boots show the amp emitting ~15 dB BELOW room floor during the PA-on
  zero prefix, with bit-identical Q6 counters/DP4 banks/attach vs audible
  boots. Software-visible state cannot distinguish audible from silent —
  always run `SPX_MIC_CAPTURE=1` and read the `SPX MIC` line. Static is ALSO
  intermittent: one clean boot measured zero-prefix static at room floor.
- §49.22 "desync lives upstream of the amp" is WITHDRAWN: its DESYNCED
  evidence was taken at BAT 24% discharging (below the ~26–30% SOC collapse
  floor).
- The warm-reboot-rails hypothesis is REFUTED (§50.1): journal-verified
  predecessor chain shows CLEAN followed an audio-active boot and a SILENT
  boot followed a blacklisted rescue (rails dropped) — both directions
  contradict it. Mid-stream MCP_SLV_STATUS latch state and probe-time SWR
  bus-clsh are also non-discriminative (counterexamples both ways). Whole-boot
  silence is currently a per-boot random draw with no known predictor; the
  only untested state axis left is full power-OFF vs warm reboot.
- Repo has `AGENTS.md`: MANDATORY pre-reboot check — verify
  `uptime -s` + `boot_id`, assume an interrupted reboot call EXECUTED, never
  re-issue blindly (two duplicate reboots destroyed test boots 2026-08-25).
- The "Windows drives these speakers fine" premise is quoted from a 07-29
  note; no Windows install exists on THIS disk. Unverified here.

**§48 (2026-08-24) — seven-step Windows-vs-Linux delta hunt complete.** One RE
agent per playback-path step diffed qcauddev/qcadcm/DSDT/INF against this tree
(full ranked table + verification corrections in PROGRESS §48). Proven
identical (stop re-testing): paged framing, per-port transport params,
spx_win_transport register surface, four-port-not-required, FrameCtrl
broadcast, FIFO discipline, frame shape, lifecycle order, boost finals
(composed masked writes match Windows exactly). Top REAL deltas, ranked:
(1) Windows manages SLIM data channels via ADSP params 0x10235/0x10233 while
we blind-write PGD watermark regs — only delta matching a live defect (RX0
overflow every stream); test = staged v29 `spx_auto_speaker_cal=1` boot, no
listen needed. (2) `BOOST_LOOP_STABILITY 0x3133`: guarded Linux drives it to
0x00 (rev2 patch) vs Windows 0x8F; one spx_wsa_seq replay A/B. (3) Windows
masks enum IRQs (0x1c3fd, knob `spx_exact_windows_init`, boot-only) and never
writes SCP_DEVNUMBER. (4) Windows CLK_STP_NOW-parks the amp bus between
streams; ours stays runtime-'active' for days (soak-model fit). (5) Windows
soft-resets the WSA digital core at teardown (0x300b=0x07, 0x3005=0x00).
Caution: wsa881x INIT_WRITE is MASKED — compose masks before comparing
register deltas (naive immediates comparison overstated the boost gap).

**§49 (2026-08-24) — all §48 deltas implemented behind legacy-default knobs**
(10-agent fleet, PROGRESS §49; nothing deployed yet). New 0644 knobs:
`wsa881x spx_win_boost_loop_stab/spx_win_misc_ctl1/spx_win_gain_singleshot/
spx_win_teardown_reset`, `soundwire_qcom spx_idle_clk_stop_ms`,
`q6afe spx_slim_slave_eaddr_lsw/_msw/spx_slim_port_pgd_la/_intfdev_la`,
`wcd934x spx_pgd_rx_port_cfg`; scripts `spx-delta-ab.sh`,
`spx-idle-park-check.sh`. Defaults ⇒ byte-identical behavior. **DEPLOYED** to /lib/modules
updates/ (`.bak-pre49` copies kept) + mkinitcpio, 2026-08-24 22:00.
**§49.1 v29 boot (22:01, AC, BAT 47%): delta #1 NEGATIVE** — with
`spx_auto_speaker_cal=1` the cal fired 45 ms before PA-on and the RX0
overflow still hit exactly once per stream (stream1 `32/32/0`, hit +80 ms
after PA-off; stream2 `40/40/0`, hit −9 ms before PA-on; v28 baseline +72 ms
after PA-off). RECLASSIFIED: the handler clears RX0 `PGD_PORT_INT_EN` on the
first hit and DAPM re-arms it next stream, so the count is a self-masking 0/1
flag at a PORT BOUNDARY (idle C0 channel), never mid-stream ⇒ NOT a static
proxy; stop counting it. Ladder now listener-gated: #2 boost octet via
`SPX_WSA_SEQ=... ./scripts/spx-delta-ab.sh` on this boot. CORRECTION:
autosuspend was already armed (3000 ms); `spx_pm_held` force-attach hold is
what keeps the controller 'active' — idle-park tests need a boot WITHOUT
`spx_force_attach=1`. Teardown-reset knob must pair with a cold-init replay
next stream. Modules built in-tree but NOT installed to /lib/modules.

**§49.4 (22:39 v28 boot, BAT 44 % discharging, AC OFF): first stream AUDIBLE —
user: "Static and then an almost clean tune"** (static first, then nearly clean
440 Hz). Attach proven (0x1), 32/32/0. Refutes a plain boot-time SOC-floor gate
again; static-then-clean = the preroll-static signature. Capture-parking
q6asm-dai (`parked[2][16]`) is live on this boot; `scripts/spx-mic-capture.sh`
is the next objective-listener step (after the peer session's delta-#2 A/B).

**§49.5-49.10 (22:34–23:23):** delta-#2 boost-octet A/B: "Both A and B were
the same" ⇒ CLOSED NEGATIVE; mic capture made SAFE (q6asm-dai parks capture clients,
`scripts/spx-mic-capture.sh`) — SLIM TX path is real (ADC2 = live noise) but
ALL WCD DMICs read digital zero; Windows' mic array is WCD DMIC1+DMIC0 (ACDB
`DMIC_2_1_STEREO`); refuted DMIC gates: MCLK, LDO14E, pad drive. LDO14E
parity boot (`spx-speaker-v32-ldo14e`, rail votes fine) = silent first tone,
then static+tune; NOT a cure; only objective delta = `MCP_SLV_STATUS` held 0x1
mid-stream (n=1). Every v28-class first tone tonight: 44 % audible, 39 % silent,
37 % (unmapped testimony).

**§49.12-49.14 (23:4x-00:0x) BREAKTHROUGH — built-in mics work:** WCD9340
DMIC0/DMIC1 capture live once `ANA_MICB1` vout = 1.8 V (`0x622 |= 0x10`);
mainline wcd934x never calls `wcd_dt_parse_micbias_info()` so every MIC BIAS
ran at 1.0 V ⇒ digital zero. Not bit7/clock/pad/LDO14E/MICB3. Fix added in
wcd934x_codec_probe (parse + log). Objective listener recipe:
`scripts/spx-mic-capture.sh DMIC1 <s>` + `/tmp/goertzel.py` (needs the
speaker audible: AC or battery > ~32 %). Delta #2 and #5 closed negative
("same"); tone collapsed at BAT 29-30 % within one boot.

**§49.17 (00:24 08-25) OBJECTIVE LISTENER PROVEN:** autotest with
`SPX_MIC_CAPTURE=1` (test-env) records DMIC1 during the guarded tone and
prints `SPX MIC: … 440Hz=18.11 neighbours=0.14 ratio=128 (TONE DETECTED)`.
Every future boot scores its own first tone; static is measurable from
`<run>/mic-DMIC1.wav`. Quiet knobs: `SPX_PA_VOLUME=4 SPX_TONE_GAIN=1.6`
(test-env) — the user asked for less volume at night.

**§49.19 mic evidence:** static = stationary broadband hiss (2-12 kHz, peak
~3.5-4 kHz, +20 dB over room floor during digital zero); the in-boot
"decay" = amp BUS DESYNC (tone gone, hiss 2.5x louder and bursty) — the mic
classifies SYNCED vs DESYNCED runs (`scripts/spx-mic-analyze.py`). Tone is
odd-harmonic dominated (3rd +9.9 dB): clipping vs driver roll-off, decide
with a 1 kHz tone (daytime, user's "play" required).

State of play:

- Software bring-up remains COMPLETE and validated: endpoint B / sink 8 / C1 /
  master DP4 / SPK2 / WCD GPIO pin2, S16_LE 48 kHz, DSP-completion paced,
  transport bit-exact against the Windows ground truth.
- Every stream renders (`q6asm_dai.spx_keep_asm`, default on): real DSP counters
  (`write_done>0`) on every stream, so one boot can host a live A/B sweep.
- The speaker WORKS. The live quality defect is the ORIGINAL residual broadband
  static — reconfirmed 2026-08-23 to not pass the PA gain stage (`PA Volume`
  12→0 killed tone, not static; §33), so it is not the audio data.
- Still-valid negatives: SPI4 read-oracle dead from Linux (§34); era/natural
  enumeration undeliverable (§36); pin1 physically silent (v20/v21 — caveat:
  pre-08-20 boots have no power-state log); the whole-boot-silence class is
  REOPENED (historic causes may be mixed).

Rules that change (effective now):

- **Never judge a listening run without recording power state** — AC present?
  battery %? charging/pending-charge/discharging? Logged next to every listen.
  A silent run without a power record is void.
- Re-baseline procedure = `scripts/spx-noise-localize.sh` PLUS the power-state
  check. Until the gate is mapped, take measurements on mains at the >=50%
  hold; spend a battery <48% listen only deliberately, to confirm the mechanism.
- Do not schedule repair/reseat/replacement work; that premise is gone.

Windows RE facts stand (`docs/windows-re/`): all codec register control goes
over SPI4 at 24 MHz (oracle dead from Linux, §34); the ADSP `AFECdcRegOp` is a
stub (demotes `q6afe.spx_auto_speaker_cal`); Windows never broadcasts
`SCP_FrameCtrl` — it programs the destination bank completely and flips it;
Windows opens all four WSA descriptors per side (four-port streamed clean and
changed nothing statically, §32/§33).

**Never judge a listening run without proving the amp attached first.** A live
sweep was audible once and near-silent on an immediate replay with identical
software; the silent run read `MCP_SLV_STATUS=0x0` at every sample — no amp ever
announced — while the DSP still reported `32/32/0`. Q6 counters cannot detect this.
`scripts/spx-portmask-sweep.sh` now waits for a real device-0 announce, waits for
`SPX FORCE-ATTACH: stable attachment` plus the cold-init replay, and aborts rather
than playing if presence never appears. Its env knobs: `SPX_PA_VOLUME` (gain A/B),
`SPX_BOOST_SWITCH` (boost off), `SPX_ZERO_ONLY=1` (pure-zero noise-source control).

## Where we were (2026-08-11)

Audio plays, but it is not clean. Live listening through 2026-08-11 confirmed:

0. V16 reproduced the clack and 440 Hz tone with static from the physical right
   speaker using the stock `qcadsp8180.mbn`.  The Windows ADSP image is not
   required; powering WCD GPIO pin2 (`SPX_AMP_GPIO_ON=0x04`) recovered output.

1. DAC-only transport: startup clack, then tone with static.
2. COMP-only transport: low tone with static.
3. Windows-style four-port allocation: loud startup transient, then silence.
4. First boot with absolute-deadline Q6 period replenishment: whole-boot
   silence despite a valid device-0 attach and correctly programmed stream
   lifecycle. This result disproves success; the cadence change remains
   unvalidated.
5. The SPX-only S24_LE backend test produced **absolute silence** despite a valid
   device-0 attach and populated, regularly submitted PCM buffers. It is reverted
   to S16_LE.
6. Repeating only the unacknowledged broadcast `SCP_FRAMECTRL_B0/B1`
   bank-switch command three times also produced **absolute silence** with valid
   attachment, format/map readback, and stream lifecycle. It is restored to one
   broadcast.
7. Every post-change cold boot has been silent since the Q6 fallback period
   worker switched from relative re-arming to an absolute deadline. The next
   staged test restores relative cadence while retaining S16 and all settled
   transport settings.

The audited guarded boot returns to the last audible baseline: one WSA codec in the
playback DAI link, physical device 0 with fixed device-0 write routing, and only
the DAC SoundWire descriptor. The disproven mirror/write-twice/watchdog modes are
off. Fifteen independent reviews completed on 2026-08-09. This is still only a
single-speaker candidate: do not select it until its corrected modules, DTB and
initramfs have been rebuilt/restaged and the no-audio rescue boot has been proven.

Only the amp on **WCD GPIO pin2** is powered. Listening identifies it as the
physical RIGHT speaker. The forced device-0 attach still uses the DT `left_spkr`
codec object, so that software label does not identify which physical amp answered.

## Hard rules

- **Never make sound without an explicit request for THAT run** (2026-08-25
  00:5x feedback: "This was loud as fuck"). Lower PA volume / tone gain does
  NOT quiet a run — the static is not attenuated by the PA stage (§33) — so
  every amp bring-up is loud until the static is fixed. Default to silent
  work; ask and wait before any stream; at night don't propose sound.
- **Never reboot or power off the machine without explicit user authorization.**
  The user has authorized the guarded one-time GRUB feedback loop for the current
  speaker work; keep the persistent default on `spx-audio-rescue` and never arm a
  test entry until all logging, watchdog and rollback checks pass.
  **2026-08-23 update:** the user then granted STANDING authorization —
  "Reboot. You're free to reboot as many times as you want" — so cold-boot
  speaker tests may be executed autonomously. Keep the persistent default on
  `spx-audio-rescue`; never leave an unverified entry as default.
- **Never `rmmod`/reload `soundwire_qcom` on a live system** — re-probe oopses and
  only a reboot recovers. Reloading `snd_soc_wsa881x` perturbs amp state.
- **Always `sudo mkinitcpio -P` after installing modules** into
  `/lib/modules/$(uname -r)/updates/`. The initramfs bundles those `.ko` files; skip
  this and the boot silently loads the *stale* copy. This has voided whole test boots.
- **`grubenv next_entry` is single-use** — consumed by the boot it steers. Keep
  `spx-audio-rescue` as the persistent default and arm only the freshly generated,
  fully audited one-time entry as the final operation before a test reboot. Never
  reuse a stale v3/v4 entry after changing a module or harness. Verify after boot
  with `grep -o spx_wsa_gpio_val=0x00 /proc/cmdline`.
- **One variable per test boot.** Never put an unverified DTB or cmdline on the
  default GRUB entry.
- **Never open a CAPTURE PCM (arecord on any MultiMediaN) on the current
  q6asm-dai** — 2026-08-24 22:40: one 4 s DMIC0 arecord closed with CMD_CLOSE +
  UNMAP (never ACKed by this ADSP), the unmap timed out (-110), and from then
  on every ASM MEM_MAP timed out, including the parked PLAYBACK session
  (`write_done=0`) — the boot's speaker path is dead until reboot. The
  `spx_keep_asm` parking covers playback only. Fix (park capture too, handle
  READ_DONE) before trying again.
- Never read `/sys/module/soundwire_qcom/parameters/spx_reenum` (write-only, blocks
  forever), never read pinctrl `pinmux-pins`/`pins` on sc8180x (oops, reboot-only),
  never read MMIO `171c0000+0x2000`, never probe GLINK/rpmsg channels (ADSP crash).

## Testing etiquette

Every result comes from the user *listening*. That is expensive and tiring — make
each test high-information, run at most one tone per configuration change, and never
ask about a run whose preconditions were invalid (e.g. amp not attached: check
`MCP_SLV_STATUS`/"writes go to device" first). Prefer register captures over listens.

~~**Only the first stream after a cold boot is a valid quality measurement.**~~
Superseded 2026-08-20 by `spx_keep_asm`: every stream now reports real DSP
consumption, so a single boot can host several listens. Prefer live A/B over a
reboot whenever the knob is 0644 and read at `hw_params` or stream open.

## How to bring the speaker up

```sh
./scripts/spx-speakers-up.sh  # run as the desktop user, never through sudo
```

`scripts/spx-amp-recover.sh` is unsafe for a live stream and is not part of the
guarded path. It can reset the controller and enable the PA before ports are
prepared; do not use it until recovery is serialized and stream-aware.

Music: `ffmpeg -i x.mp3 -t 10 -ar 48000 -ac 2 out.wav && aplay -D plughw:0,0 out.wav`

Key detail: after the idle cold-init replay, the PA gain must be **force-written** —
the guarded script toggles `SpkrLeft PA Volume` 0 then 8. A plain re-set is an ALSA
no-op while the hardware register has been reseeded to the 0 dB floor.

## Hardware model

WSA881x smart amp on the **WCD9340 codec's internal** SoundWire master
(`drivers/soundwire/qcom.c`), reached over a SLIMbus AHB bridge regmap. No MMIO, no
usable IRQ. **Unicast writes always report success even when dropped**, and reads are
unreliable — so never trust a write, and never read-modify-write.

- `MCP_SLV_STATUS` (0x1090): `0x1` = present at device 0, `0x4` = attached at device 1,
  `0x0` = absent *or stale*. It is refreshed only by the attach recipe.
- Device 0 (unenumerated) is the **stable, self-healing** state; device 1 is fragile.
  `spx_write_dev0=1` routes writes there.
- Amp power is `SD_N` via WCD GPIO regs 0x42 (dir) / 0x43 (val). **Physical HIGH = amp
  ON, LOW = off** — measured 2026-07-29 with `spx_wsa_power_probe.ko` (park low gives a
  quiet bus, `INT_STATUS=0x0`; raising either pin makes a slave announce). This matches
  `powerdown-gpios = <&wcdgpio N GPIO_ACTIVE_LOW>` in the DT. The earlier "LOW = on"
  note here was **wrong**, which made `val=0x06` ("both parked off") power BOTH amps
  and clash them, and `val=0x04` ("pin1 on") actually power pin2.
  Correct values: `0x00` = both off, `0x02` = pin1 only, `0x04` = pin2 only.
  The legacy `spx-wsa-pin2-test` entry is unsafe and must not be used. pin1 and pin2
  are the two amps' independent enable lines. A power-cycle needs **10 s** off.
- Loud static with no tone = amp desynced from the bus with the PA still on.

## Windows driver reference (the ground truth)

Extracted drivers live in `~/Documents/drivers/FileRepository/`. The WSA881x/SoundWire
code is in **`qcauddev8180.sys`** (section `PAGEwcda` @ `0x14006e000`) —
*not* `qcadcm8180.sys`, which is only the ACDB calibration manager and contains zero
WSA registers. Windows runs an **apps-side** SoundWire driver, so the ADSP does not own
the register path. Useful entry points: `wsa_reg_write` `0x140098640`,
`wsa_reg_read` `0x140098788`, master rw `0x14009afa8`/`0x14009b388`, PA bring-up
`0x140098af0`/`0x140099058`, shutdown `0x14009a228`.

The live Windows binary is
`~/Documents/spx-winlive/qcauddev8180-LIVE.sys` (sha256
`2c3f32...`). Its static left descriptors map slave ports 1/2/3/4 to
master ports 1/2/3/7 with channel masks 1/f/3/3; the right descriptors map
to 4/5/6/8. The sample intervals and offsets match
`sc8180x-wcd9340.dtsi`, and Windows opens all four descriptors.

The miniport and ACDB files establish the logical path without establishing a
physical-side label. `TopologySpeaker` is device `0x45`, 48 kHz, 24-bit, stereo.
`Speaker_cal.acdb` property `0x113b7` maps it to codec key `0x15200`, AFE port
`0x4004` (`SLIMBUS_2_RX`), and channels `0xc0/0xc1`. `Codec_cal.acdb` names that
key `SPEAKER_PHONE_SPKR_STEREO` and selects endpoint tokens `0x01010004` and
`0x01010005`; qcauddev maps those to internal sinks 7 and 8. Neither the miniport,
ACDB, nor the INF says which token, SoundWire preset, or GPIO is physical left or
right. Treat MP1/SP1 and MP4/SP1 as paths A/B until isolated-channel listening
identifies them. The Windows 24-bit value describes the logical device; it does
not by itself prove the WSA SoundWire transport width, which is a 1-bit PDM link.

Implemented from this RE (live-tunable, with cross-platform defaults off):
- `snd_soc_wsa881x.spx_win_pa_seq` — ANA_CTL bit-2 latch pulse, staged DAC ramp,
  VI-sense teardown, 1 ms/step PA gain ramp.
- `soundwire_qcom.spx_win_transport` — stop writing `BLOCK_CTRL_1`, slave
  `BlockCtrl3` and `HCTRL` (Windows leaves them at reset; we wrote `0xFF`/`0xFF`/`0xF0`),
  and compose `PORT_CTRL` in one write instead of read-modify-write over the flaky bridge.
  Verified in silicon: those registers now read 0, and mid-stream
  `DP1_PORT_CTRL_B0 = 0x01000107`, which is correct.

## Settled — do not retry

- `spx_mirror_banks=1` and `spx_write_twice=1` **desync the amp** (static/silence).
  Keep both 0.
- `spx_verify_bank` (Windows' `COMP_STATUS[5:4]==2` handshake) **does not apply** to
  this master: it reads `0x14201`, that field is always 0, even while the bus runs.
- `spx_dr_freq=19200000` (dual-edge rate) → **complete silence**. Keep the 9.6 MHz default.
- `SpkrLeft COMP Switch` must be **off**: the compander/DRE stream fights the register
  gain mode and mutes real audio.
- The static is *not* sample-edge, boost converter, COMP7, or digital clipping — all
  A/B tested.
- SLIMbus PIO is control-only; the audio data path is ADSP AFE → SLIMbus hardware, so
  PIO jitter is not a static suspect.
- `spx_init_on_pmu` (replaying the init table in PRE_PMU) **makes it worse** — ~240 ms
  of register traffic at every stream start, while the port already streams. Default
  is 0; `spx_rearm_init` now replays cold init only while no stream is configured and
  never enables/unmutes the PA itself.
- **Nothing writes to the bus during steady-state playback** (kprobe-verified: 0 writes
  between PA-on and teardown). So the static is *not* caused by mid-stream register
  traffic, and it originates upstream of SoundWire — in the ADSP AFE → SLIMbus → codec
  interpolator path, or in the codec's SWR data source.

## Whole-boot silence and dropped bank switches

Some boots produce **no sound at all**, in every configuration, with identical
modules, knobs and GRUB entry to a boot that was audible. Recovery, power-cycling and
re-init do not rescue such a boot. Before drawing *any* conclusion from a silent
result, establish that the boot can make sound at all — otherwise every A/B that boot
is meaningless. (Boots "E" and 2026-07-27's eleventh were fully silent; the ninth,
with the same settings, was audible.) A retained root-cause experiment showed that
manually mirroring the enabled configuration into the still-active bank restored
sound mid-stream. Since broadcast bank switches have no response, a dropped
`SCP_FRAMECTRL` write is invisible in an otherwise correct trace.

## Reference trace

`docs/traces/stream-silent-20260727.txt` — full kprobe capture of one stream
(bring-up + tone + teardown, 256 writes) from a silent boot. The port sequence in it
is structurally *correct*, which is why it is worth keeping as a baseline:

```
prepare : 0x0132=0x07 0x0134=0x01        (DP1 SampleCtrl1/OffsetCtrl1, bank 1)
switch  : bcast 0x0070=0x07              (SCP_FrameCtrl_B1 -> bank 1)
enable  : 0x0122=0x07 0x0124=0x01 0x0120=0x01   (bank 0 params + ChannelEn=1)
switch  : bcast 0x0060=0x07              (SCP_FrameCtrl_B0 -> bank 0, enabled)
PA      : 0x311b ramp 0x99..0x09 (REG mode, +18 dB), then 0x311a=0xfc
teardown: 0x311a=0x7c, ChannelEn -> 0
```

Capture with `sudo insmod drivers/spx_extras/spx_wr_trace.ko max=4000` before the
bring-up, then `dmesg | grep spxwr`.

## Open threads

0. Re-establish an audible baseline before running any further A/B.  See
   "No audible baseline" below — this now blocks everything else.
1. Validate the restored relative Q6 fallback cadence; the absolute-deadline
   version never produced sound on a cold boot.
2. If the first stream is audible but dirty, capture the serialized DP1 master
   snapshot and compare it against the static Windows descriptor table.
3. Second amp / DT left-right name inversion.
4. Master/slave DP1 ChannelEn parity is ruled out as the whole-boot silence
   gate.  V5 verified both master banks as `0x01000107`, logged enable/disable
   shadows on both sides, completed the stream, and was silent.

## Debug tooling (`drivers/spx_extras/`)

| module | purpose |
|---|---|
| `spx_swrm_regs.ko` | legacy idle-only bridge dump; never use during playback (the guarded path uses `soundwire_qcom.spx_snapshot`) |
| `spx_wsa_seq.ko` | replay arbitrary WSA register sequences: `seq=reg:val:delay_ms,...` |
| `spx_wr_trace.ko` | kprobe tracer of every SoundWire write (no ftrace in this kernel) |
| `spx_wcd_gpio.ko` | drive managed amp-enable pins: `dir=0x06 val=0x02` powers only pin1 |

These "fail" to load with `-EAGAIN` **by design** so they can be re-run without `rmmod`.

Deeper history and per-boot findings: `~/.claude/.../memory/spx-bank-switch-rca.md`
and `docs/spx-*.md`.

## 2026-08-09 guarded v3 runtime result

The automatic v3 test proved a real pre-stream device-0 attachment
(`MCP_SLV_STATUS=0x1`), completed the idle cold-init replay, opened ALSA, ran
`hw_params active_ports=1`, and fired both PA PMU events.  The serialized
active-stream snapshot showed active bank 0 with
`DP1_PORT_CTRL_B0=0x01000107`, exactly the intended DAC transport.  The status
latch cleared to `0x0` after the bank switch, as seen in older runs, so the first
harness revision stopped the tone after about 1.3 seconds and safely parked the
amp.  There were no kernel faults and audible output was not confirmed.

A fresh-boot attach initially missed status again, but its one safe same-boot
retry attached and submitted the full five-second stereo tone window.  GNU
`timeout` escalated its TERM to KILL while the protected persistent PCM teardown
was still closing, returning 137; the normal delayed PA POST_PMD arrived about
3.8 seconds later.  The initial harness treated 137 as failure even though the
full test interval ran.  It again verified GPIO-low cleanup, with no kernel
fault.  The harness now accepts this bounded 137 result and waits up to eight
seconds for the delayed PA POST_PMD before judging the lifecycle.

For the next guarded run, a real `0x1` remains mandatory in the GPIO-high window
before logical attach or playback.  After that proof, `0x0` is treated as the
documented ambiguous/stale latch state during later pre-stream, active-stream and
post-stream checks; any non-device-0 address, incorrect active bank, missing DAPM
lifecycle event or kernel fault still aborts the test.

Two later attempts falsely aborted because their single pre-stream sample landed
on `0x0`.  A no-audio timing probe then powered only pin1 and took 40 serialized
master snapshots over about 2.4 seconds: 23 read `MCP_SLV_STATUS=0x1` and 17 read
`0x0`, while GPIO remained high throughout.  This proves the status latch flickers
even before streaming.  The harness now samples immediately after GPIO-high until
it observes at least one real device-0 `0x1`, remembers that physical proof, and
then permits later ambiguous zero samples.  It still rejects every other nonzero
address and never opens ALSA unless device 0 was actually observed first.

## 2026-08-09 guarded v4 runtime result

The v4 one-time boot loaded the intended `spx_shadow_dp1_enable=1` module and
completed the full guarded five-second stream without a kernel fault.  The real
device-0 presence window, idle cold-init replay, ALSA submission, DAC-only
`hw_params`, PA PMU/PMD lifecycle, and verified GPIO-low cleanup all passed.  The
slave DP1 enable and disable writes were shadowed across both banks.  The user
heard nothing.  The serialized master snapshot was
`B0=0x01000107, B1=0x00000107`: slave-only shadowing did not reproduce the older
mid-stream recovery, which explicitly enabled bank 1 on both sides.  The next
single-variable test therefore adds only master DP1 ChannelEn parity; gain and
all other transport/analog settings remain unchanged.

## 2026-08-09 guarded v5 runtime result

V5 added the missing master-side half of the historical DP1 repair.  During the
full five-second tone the serialized snapshot proved
`B0=0x01000107, B1=0x01000107`, while fresh logs proved slave and master enable
shadows (`0x01`) and teardown shadows (`0x00`).  Device 0 was physically observed
before attach, cold init and the PA PMU/PMD lifecycle completed, GPIO-low cleanup
was verified, and no kernel fault occurred.  The user heard nothing.  Therefore
DP1 bank-enable parity is not the current silence gate.  The next cold-boot A/B
restores PA Volume 12, the exact +18 dB value from the last audible recovery
runs; the tested transport remains unchanged.

## 2026-08-09 guarded v6 runtime result

V6 changed exactly one variable from v5: `SpkrLeft PA Volume` 8 -> 12, the exact
+18 dB value from the last audible recovery runs.  The kernel command line,
modules and DTB were byte-identical to v5.  The run
(`runs/b1f315df-...-20260809T172639Z-914`) passed every software gate: real
device-0 presence in the GPIO-high window (`MCP_SLV_STATUS=0x1` with a valid
`COMP_PARAMS=0x016840c6` canary), idle cold-init replay, the DAC-only mixer
path, a verified `0 -> 12` PA Volume transition in `mixer.log`, a full
five-second 48 kHz S16_LE stereo tone, mid-stream `B0=0x01000107
B1=0x01000107`, verified GPIO-low parking, no kernel fault, exit status 0.

The user heard **nothing**.  PA gain is therefore eliminated: v3-v6 have now
each disproven one hypothesis (gain, slave DP1 shadowing, master/slave DP1
bank parity) while passing every software gate.  Open thread 0 is closed.

Transport cross-check (open thread 2, done offline from this capture):
`SWRM_DP_PORT_CTRL` = `en_chan<<24 | offset2<<16 | offset1<<8 | sinterval`, so
`0x01000107` = chan `0x01`, offset2 `0x00`, offset1 `0x01`, sinterval `0x07`.
That is bit-exact against master port 1 in `sc8180x-wcd9340.dtsi` (`0x07`,
`0x01`, `0x00`), which matches the Windows static left descriptor.  The
single-port DAC transport therefore holds no discrepancy against the Windows
ground truth; the only remaining structural difference is Windows opening all
four descriptors, which was already tested (loud transient, then silence).

## No audible baseline — this blocks every further A/B (2026-08-09)

Four consecutive guarded boots (v3, v4, v5, v6) passed **every** software gate —
real device-0 presence, cold-init replay, correct mixer path, full five-second
tone, correct mid-stream `DP1_PORT_CTRL`, verified GPIO-low parking, no kernel
fault — and all four were silent.  We therefore have no proof that any boot in
this series can make sound at all, and per the whole-boot-silence rule every
single-variable result in the series is uninterpretable.

Two things changed between the last audible run and v3, neither ever validated
as audible:

1. `cfc49f4bed61` ("audit Surface Pro X speaker bring-up") rewrote 1015 lines
   across `wsa881x.c` (463), `qcom.c` (300), `wcd934x.c` (64) and `wcd934x.c`
   (mfd, 49).  Its DTSI hunk is comment-only, so the port parameters are
   unchanged — but the driver logic underneath them is not.  This is a
   multi-variable change that landed without a listening test.
2. Every guarded entry forces `snd_soc_wsa881x.spx_win_pa_seq=1` and
   `soundwire_qcom.spx_win_transport=1`.  Both are RE-derived, both ship with
   cross-platform defaults of **0**, and neither has ever been shown audible.
   `spx_win_transport=1` stops writing `BLOCK_CTRL_1`, slave `BlockCtrl3` and
   `HCTRL`, leaving them at 0 instead of `0xFF`/`0xFF`/`0xF0`.  Those govern
   block packing.  Windows can leave them at reset because Windows opens all
   four descriptors; the single-port DAC config plausibly cannot.  Wrong
   framing with correct control registers produces exactly the observed
   signature: a bit-exact `DP1_PORT_CTRL` trace and no audible output.

The v3-v6 A/Bs were single-variable deltas layered on top of both of these.

**Next test (staged, no reboot needed).**  Both knobs are runtime-writable
(0644), so the baseline can be probed on a live boot for the cost of one listen:
`scripts/spx-prere-baseline.sh` sets `spx_win_pa_seq=0` and
`spx_win_transport=0` and plays one tone.  This is deliberately two variables —
the goal is a baseline, not isolation.  It is an *audibility* test, not a
quality one (only the first stream after a cold boot measures quality).

- Audible  -> the RE knobs are the gate; one more listen bisects which.
- Silent   -> suspicion moves to the `cfc49f4bed61` rewrite; boot the pre-audit
  tree (`a88666f0b27d`) to recover a known-audible reference.

## v7 result (2026-08-09) — pre-RE baseline, SILENT

`spx-speaker-dev0-v7-prere` is derived from the audited v6 block and differs
from it in exactly the title, the `--id`, and two knobs:
`soundwire_qcom.spx_win_transport` 1 -> 0 and
`snd_soc_wsa881x.spx_win_pa_seq` 1 -> 0.  Kernel, DTB
(`...dtb.speaker-dev0-v3-audited`), initramfs and every other parameter are
byte-identical, and no kernel code changed since the v6 build, so no rebuild or
`mkinitcpio` run was needed.  PA Volume stays at 12.

Deliberately two variables: this is a baseline probe, not an isolation test.

- Audible -> the RE knobs are the gate; one more cold boot bisects which.
- Silent  -> suspicion moves to the `cfc49f4bed61` rewrite; boot the pre-audit
  tree (`a88666f0b27d`) to recover a known-audible reference.

### v7 outcome

The first v7 boot aborted in step `[0]`: the guarded bring-up hardcoded
`spx_win_transport=1` and `spx_win_pa_seq=1` as boot invariants, so it refused
the pre-RE command line before touching hardware.  No tone played and the amp
was never powered, so that cold boot stayed pristine.  Fixed in
`01f5fc38d6f7`: exactly those two expectations are now overridable via
`SPX_EXPECT_WIN_TRANSPORT` / `SPX_EXPECT_WIN_PA_SEQ`, defaulting to 1 so every
existing guarded entry is unchanged.

The re-run was then a genuine first-stream-after-cold-boot measurement, with
both knobs 0 from the command line (no live write).  Every gate passed —
device-0 presence, cold init, DAC-only mixer path, PA Volume 12, full
five-second tone, `B0=0x01000107 B1=0x01000107`, verified parking, no fault.

The user heard **nothing**.

The reverse-engineered knobs are therefore eliminated.  Note this is not a
no-op comparison: with `spx_win_transport=0` the `PORT_CTRL` path falls back to
read-modify-write over the AHB bridge instead of composing the word in one
write, and it *still* read back `0x01000107`.  Both code paths, both silent.

## The audible baseline on disk — FIRST ATTEMPT WAS WRONG (2026-08-09)

Five consecutive gate-perfect silent boots (v3-v7) mean the useful move is no
longer another hypothesis but recovering a known-audible reference.  The
2026-07-28 configuration survives intact:

- GRUB entry `spx-windows-native-audio`, preserved in
  `/boot/grub/grub.cfg.bak-20260729-010942`.
- DTB `/boot/dtb/qcom/sc8180x-surface-pro-x.dtb.windows-audio` (mtime 07-28 15:56).
- A coherent module snapshot in `/lib/modules/$(uname -r)/updates/`: every one of
  `soundwire-qcom`, `snd-soc-wsa881x`, `snd-soc-wcd934x` and `soundwire-bus`
  carries the suffix `.pre-fullbuild-20260728-161033`, same 15:56 timestamp.

Its kernel command line is the important surprise.  The **entire** SPX knob set
was `slim_qcom_ngd_ctrl.spx_probe_stage=8 spx_pio_mode=1 spx_allow_full=1
spx_pin_after_qmi=1` — no `spx_write_dev0`, no `spx_core_enum`, no
`spx_no_assign`, no `spx_win_*`, no `spx_wsa_gpio_val`.  The audible runs set
every module parameter **at runtime from the bring-up script**, whereas v3-v7
bake about thirty knobs into the command line.

So the gap between the audible era and this series is four simultaneous
differences — DTB, command line, built modules, and the `cfc49f4bed61` driver
rewrite — not the two knobs v7 tested.

Caveat before booting it: that entry has no `panic=10` / `oops=panic` /
`ramoops.console_size` and its DTB has no watchdog node, so the guarded harness
cannot run on it and a hang needs a hard power cycle.

Three candidate next tests, in decreasing confidence and increasing safety:

1. Full 07-28 reconstruction (modules + DTB + minimal cmdline, manual bring-up).
   Deliberately multi-variable; the point is a reference, then re-bisect forward.
2. Pre-audit DTB only (`eeb15ca58849`, already built).  Isolates the sound-dai
   and audio-routing block the audit added, keeps modules and the guarded
   harness.  Risk: the pre-audit DTS disables `right_spkr` while the inherited
   DAI link still references it, which may stop the card probing at all.
3. Revert `qcom.c`, `wsa881x.c` and both `wcd934x.c` to `a88666f0b27d`, rebuild,
   `mkinitcpio -P`, keep the audited DTB and harness.  Isolates the rewrite with
   all safety rails, but drops `spx_shadow_dp1_enable` and `spx_snapshot`, so
   the entry and harness need small edits.

### Correction: `spx-windows-native-audio` is NOT the audible entry

The reconstruction above was built on two mistakes, both now disproven:

1. **Git history before 2026-08-09 is squashed.**  `005adbc494a5`,
   `a88666f0b27d` and `cfc49f4bed61` are all 08-09 commits containing
   accumulated work, so `a88666f0b27d` is *not* the 07-28 tree and
   `git show a88666f0b27d:scripts/spx-speakers-up.sh` is an 08-09 artifact.
   Do not use git to date anything before 08-09; use the `/boot/grub/grub.cfg.bak-*`
   files and the `/lib/modules/.../updates/*.ko.<suffix>` mtimes instead.
2. **`spx-windows-native-audio` was a different experiment.**  Its minimal
   command line lacks `spx_wsa_gpio_val`, `spx_core_enum`, `spx_no_assign` and
   `spx_write_only`, all of which the bring-up script hard-requires and aborts
   without.  It cannot have been the entry that produced a tone.

**What the GRUB backups actually show.**  In `grub.cfg.bak-20260729-010942` the
only speaker entry is `spx-wsa-pin2-test`: `dtb.wsa-pin2`, with
`wcd934x.spx_wsa_gpio_dir=0x06 wcd934x.spx_wsa_gpio_val=0x06
soundwire_qcom.spx_core_enum=1 spx_force_attach=1 spx_blind_attach=1`.
`spx_wsa_gpio_val=0x00` does not appear in any backup until 2026-08-04.

So **the audible 07-26/07-28 runs booted `spx_wsa_gpio_val=0x06`** — which the
later polarity correction re-interpreted as *both amps powered*.  Every silent
boot since (v3-v7 and the 08-04 onward series) boots `0x00` and then raises pin1
only, i.e. exactly one amp.

That is a real, untested, single-variable difference between the audible era and
every silent boot, and it sits upstream of everything v3-v7 varied.  It also
sits awkwardly against [[spx-wsa-enum-collision]], which says two amps at
device 0 collide — yet a tone was heard in that configuration, twice.

Note the guarded bring-up drives the GPIOs itself (`val=0x00`, then `0x02`), so
changing the command line alone does not reproduce the old state; the script's
power sequence has to leave both amps enabled too.

**Attempted and reverted:** the 07-28 15:56 module snapshot was installed and
`mkinitcpio -P` run, then fully restored after the premise collapsed.  Keep in
mind those modules predate `spx_shadow_dp1_enable` and `spx_snapshot`, so
booting any v3-v7 entry against them fails to load `soundwire_qcom` on an
unknown parameter and leaves the machine with no sound card.

## 2026-08-11 — AUDIBLE BASELINE RECOVERED (v15)

The v15 guarded cold boot produced a **clack, then a 440 Hz tone with static** from
the physical right speaker — the first audible run since 2026-07-28 and the end of
the eight-boot silent series (v3-v7, v9, v10, v13/14).

The v15 configuration, exactly:

- DTB `sc8180x-surface-pro-x.dtb.speaker-dev0-v12-winfw` = the audited v3 DTB plus
  two edits: ADSP `firmware-name` -> `qcadsp8180-win.mbn`, and the ADSP carveout
  restored to 28 MiB (`memory@96e00000` span `0x1c00000`, CDSP shifted to
  `0x98a00000`/`0x600000`).  Without the carveout the win image fails PAS with -22.
- **`SPX_AMP_GPIO_ON=0x04`** via `/var/lib/spx-speaker-autotest/test-env` — power
  the **pin2** amplifier, not pin1.  Everything else is the v6 command line.
- Attach took 4 samples (`MCP_SLV_STATUS` 0x0,0x0,0x0,0x1), then the normal
  five-second tone.  `SPX ASM stream 1: submitted=22 write_done=19 fallback=18`.

Two variables changed together (win firmware and pin2); the next single-variable
boot bisects them.

### What the ASM counters proved

`q6asm-dai` now reports `submitted/write_done/fallback` at stream close.  The result
is a hard rule for every future test:

**Only the FIRST stream of a boot has `write_done > 0`.**  Every later stream in the
same boot reports `write_done=0` ("DSP CONSUMED NOTHING") — `spx_persist_stream`
parks the SLIMbus stream and AFE port, and the DSP never re-attaches to the new
session.  The fallback worker fakes period progress, so ALSA still looks healthy.
Any A/B run on a second or later stream of a boot is **meaningless**; several
mid-session probes on 2026-08-11 were invalidated this way.

### pin1 vs pin2

The pin1 amp has never produced any audible sound, not even a power-on click,
across the whole silent series.  The pin2 amp clicked audibly the first time it
was ever powered and then produced this tone from the physical RIGHT speaker.
Suspect pin1's amp or its speaker is dead; work on pin2 from now on.  Do not infer
the physical side from the bound `left_spkr` codec object while forced device-0
addressing is in use.

### Tooling corrections found while probing

- `spx_wsa_seq.ko` rejects any register outside `0x3000-0x36ff`, so every attempt to
  poke slave DP1 registers (`0x0120`-`0x0134`) through it silently did nothing.  The
  "audible poke" run was therefore master-writes-only, and neither master bank poke
  alone reproduced it — the audibility came from that run being the boot's first
  stream, not from the pokes.
- `spx-audio-modules` looked up the ADSP at a hardcoded `remoteproc1`; the win-fw
  boot enumerates it as `remoteproc2`, so the loader timed out and no sound card
  appeared.  It now searches by `name == adsp`.
- The autotest unit required `soundwire_qcom.spx_no_assign=1` on the command line,
  which blocked the era-addressing entries; that condition is removed.

## 2026-08-11 — v16 firmware bisect: stock ADSP is audible

V16 changed one variable from v15: it booted the audited stock-firmware DTB and
therefore loaded `qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn` instead of
`qcadsp8180-win.mbn`.  It retained `SPX_AMP_GPIO_ON=0x04` and every v6 transport,
codec, mixer and safety setting.

The user heard the same signature: a clack, then the 440 Hz tone with static from
the physical right speaker.  The boot log independently validates the A/B:

- remoteproc loaded stock `qcadsp8180.mbn` (10,758,800 bytes);
- GPIO 0x43 was driven with managed value `0x04` (pin2 only);
- device 0 was observed after one sample and both active master DP1 banks were
  `0x01000107`;
- the first stream closed with `submitted=22 write_done=19 fallback=18`.

Conclusion: **pin2 was the audibility gate; the Windows ADSP firmware and its
larger carveout are unnecessary.**  Use stock firmware for all further work.
The static is a separate data-quality problem.

The counters also invalidate the old premise behind forced timer pacing.  Basic
write acceptance ACKs are filtered in `q6asm.c`, so the 19 `write_done` callbacks
were real `ASM_DATA_EVENT_WRITE_DONE_V2` events.  V17 should change only
`q6asm_dai.spx_force_timer_pacing=0`: queue one buffer and replenish it from the
DSP completion event, retaining the two-period watchdog as a fallback.  If the
static is caused by timer/DSP drift, this should clean it up; if WRITE_DONE stops,
the watchdog safely returns to the v16 pacing path.

V17 is staged as GRUB id `spx-speaker-v17-event-pacing`.  Its command line is
token-identical to v16 except for `q6asm_dai.spx_force_timer_pacing=0`.  A
pre-boot audit found that the first implementation could let WRITE_DONE and the
two-period watchdog both submit at their boundary. The corrected callback arms
the watchdog before each submit and must cancel it to claim a completion; if the
watchdog is already running, it alone switches the stream to timer fallback.
The same patch derives the watchdog period from ALSA frames so S24_LE's 32-bit
container is timed correctly. The validated v17 vermagic-matched module sha256 is
`6dc4f351a93ac0cc619098e0b6686484b12cff2effe32f356b4152be35ca0083`;
the racy build is preserved as `q6asm-dai.ko.bak-v17-racy`, and the prior v16
module as `q6asm-dai.ko.bak-v16-timer-pacing`. `mkinitcpio -P` completed for both
normal and rescue images. The persistent default remains `spx-audio-rescue`.

## 2026-08-11 — v17 DSP-event pacing is audible

The first automatic attempt aborted before hardware access because the harness
expected boolean `0` while sysfs reports `N`. The guard now normalizes `0/1` to
`N/Y`; no PCM was opened, so the manual guarded retry remained the boot's valid
first stream.

V17 then produced a clack and 440 Hz tone with a bit of static. The stream was
entirely DSP-paced: `submitted=20 write_done=20 fallback=0`. Both master DP1
banks were `0x01000107`, device 0 was physically observed before playback and
again afterward, PA/GPIO teardown completed, and no kernel fault occurred.
Therefore timer/DSP drift was not the sole source of static, but completion
pacing is the better baseline and its watchdog ownership fix is validated.

Next single-variable test: request the Windows logical S24_LE format at the
Q6ASM frontend while leaving the known-audible S16/PDM backend unchanged. The
guarded harness now accepts `SPX_TONE_FORMAT=S24_LE`, and the Q6 close counter
logs the actual frontend bit depth. The log-only v18 module is installed with
sha256 `ed54b6de367990efdcca7b786ea8b72e4b5d4446855a43533684c0eb64218fbe`;
the validated v17 build is preserved as `q6asm-dai.ko.bak-v17-event-pacing`.

## 2026-08-11 — v18 S24_LE frontend is transport-clean but inaudible

The guarded first stream really opened Q6ASM at 24 significant bits and stayed
entirely DSP paced: `bits=24 submitted=28 write_done=28 fallback=0`. SoundWire
DP1 remained enabled in both banks, teardown completed and no fault occurred.
The listening result was a quieter startup clack, low-volume static, then a
second clack; there was no identifiable 440 Hz tone.

Therefore Windows' 48-kHz/24-bit endpoint declaration is logical Windows/ADSP
truth, but S24_LE is not a usable format on the present legacy Linux Q6ASM path.
Keep the Linux frontend and backend at the proven S16_LE baseline while routing
is completed. Do not widen the WSA/SoundWire backend on the strength of the
Windows miniport alone.

## 2026-08-11 — v19 stages Windows endpoint B as an isolated S16 test

V15-v18 powered physical GPIO pin2 but bound Linux `left_spkr`, so they exercised
the MP1/SPK1 software path through the pin2 amplifier. V19 instead binds only
`right_spkr`, whose board topology is slave DP1 -> master DP4 (`<4 5 6 8>`),
WCD RX1/INT8/COMP8/RX8 -> SPK2, and GPIO pin2. This matches the second ordered
Windows codec endpoint (`0x01010005`, qcauddev sink 8) as a strong positional
inference; Windows does not literally join that token to MP4 or name its side.

The guarded right-only DTB is
`sc8180x-surface-pro-x.dtb.speaker-right-v19`, sha256
`3c32f9a36af310a45859e445fc4c2e8d6d594f3ca45bb2293cbc3b04d0b2ceaa`.
The diagnostic SoundWire module now snapshots DP4 and shadows the selected
master DP1 or DP4 into both banks; installed sha256
`b493d7fa5014a507f5fc50e2bd0437c6aa9bb3ac377da2b7622b133fd8be2880`.
The harness requires S16_LE/48-kHz/stereo ALSA hw_params, C1/front-right-only
submission, DP4 `0x01000607` in both banks, slave-DP1/master-DP4 shadow logs,
the exact endpoint-B DT/GPIO/routes, and Q6 `bits=16`, `fallback=0`, nonzero and
equal submitted/completed counts. GRUB id is `spx-speaker-v19-endpoint-b`; the
persistent default remains `spx-audio-rescue`.

### V19 result: endpoint B is audible on pin2

The user heard a clack, the 440 Hz tone and a bit of static. The live proof was:

- only `sdw:...:00:2` bound, with WCD GPIO pin2 and port map `4 5 6 8`;
- active ALSA hw_params were exactly S16_LE, 48 kHz and two channels, with
  `speaker-test -s 2` selecting C1/front-right only;
- slave DP1 and master DP4 enable/disable were both shadowed, and active DP4
  banks were both `0x01000607`;
- Q6ASM closed with `bits=16 submitted=19 write_done=19 fallback=0`;
- PA teardown completed, GPIO returned to `0x00`, and no kernel fault occurred.

The autotest unit reported failure only because `speaker-test -s 2` prints
`- Front Right` without its numeric channel prefix; the guard expected
`1 - Front Right`. The string check is corrected. This does not invalidate the
audio or transport result.

Combined with the Windows endpoint ordering, V19 empirically joins C1 / token
`0x01010005` / sink 8 to Linux endpoint B / MP4/SP1 / SPK2 / physical pin2.
Both MP1/SPK1 and MP4/SPK2 paths produce the same residual static on pin2, so
the old left-software-path mismatch was not the static source. Next isolate
endpoint A with C0 and its own GPIO pin1 before attempting simultaneous stereo.

## 2026-08-11 — v20 endpoint A is digitally complete but physically silent

The user thinks nothing was audible. This is not an upstream stream failure:
only WSA unit1/pin1 was active, the pin1 amp announced at device 0, C0/front-left
opened at S16_LE/48 kHz/stereo, both MP1 banks were `0x01000107`, slave/master
DP1 enable and disable shadows completed, PA/RDAC events ran, and Q6 reported
`bits=16 submitted=19 write_done=19 fallback=0`. GPIO cleanup and the watchdog
guards passed without a fault.

The existing three-corner matrix is therefore:

- endpoint A / MP1 / SPK1 -> pin2: audible (v15-v17);
- endpoint B / MP4 / SPK2 -> pin2: audible (v19);
- endpoint A / MP1 / SPK1 -> pin1: silent (v20).

That strongly localizes the problem to pin1's WSA analog output, speaker or
unobservable slave-side writes. V21 is a final cross-proof: endpoint B's proven
MP4/SPK2/C1 route is retained but its sole logical WSA powerdown GPIO is
deliberately overridden to pin1, with pin2 kept off. This is guarded by explicit
`SPX_ALLOW_CROSS_GPIO=1` and is not a production DT. DTB sha256:
`a7196b6f00135046cf097933f53e894479ab895b9ac5b66aba8d272ed9767088`.

Do not enable both current DTS WSA nodes under force mode. The force path aliases
all enabled codecs to device number 1. Older hardware probing also found real
slaves `0217:2110` unique IDs 3 and 4 while the current DTS declares `0217:2010`
IDs 1 and 2; permanent stereo must correct those identities and use sequential
device1/device2 assignment rather than the one-amp forced-dev0 mechanism.

### V21 result: pin1 physical output is nonfunctional

The user heard nothing. V21 retained endpoint B's exact proven MP4/SPK2/C1 path
and changed only its powerdown GPIO from pin2 to pin1. The run still had active
DP4 banks `0x01000607`, the expected slave-DP1/master-DP4 shadows, S16_LE at
48 kHz, and `bits=16 submitted=19 write_done=19 fallback=0`; PA/RDAC events and
cleanup passed without a fault. V19's same endpoint/route on pin2 was audible.

This is a clean physical localization: pin1's WSA control core announces, but
its analog amplifier/output, speaker or wiring does not emit sound. Leave pin1
off and do not attempt dual attach until hardware is repaired. The only usable
speaker path is endpoint B / sink8 / C1 / MP4-SP1 / SPK2 / GPIO2 (physical right
per the earlier chassis-side listening report). Continue quality and lifecycle
work on that isolated pin2 baseline.

## 2026-08-11 — v22 replays Windows' protection-disabled WSA state

The Linux cold-init path had unconditionally replayed qcauddev's conditional
speaker-protection enable sequence even though the guarded baseline exposes
only the DAC port, keeps VISENSE off, and does not load device `0x45`'s module
`0x1025f` protection calibration. DriverStore `qcauddev8180.sys` SHA-256
`47a1b7b7167141fe025c4cb5d6af295f8ce8862394b22bdd7c79ab017b65661d`
instead disables protection with `3110=00`, `3111=00`, `3140=95`, a 1-ms
wait, then `313a=ce`. V22 changes only that WSA cold-init state.

The guarded endpoint-B/pin2 run is internally valid. The loaded WSA module is
SHA-256 `e3a21aa6e32083884c6fb3e4c85d5fe465d716dadca88a67c7d6c2d9730d0e3a`;
its object code contains the ordered Windows writes and the idle cold replay
completed without a write error. Playback was S16_LE/48-kHz/stereo C1, active
DP4 banks were both `0x01000607`, and Q6 reported
`bits=16 submitted=19 write_done=19 fallback=0`. PA/RDAC teardown, DP-bank
disable and GPIO parking passed; there was no kernel fault. Individual WSA
registers are write-only in this mode, so the evidence proves correct software
submission rather than electrical readback. In the acoustic comparison with
v19, the user heard the tone mixed with static and a split-second interruption.
Protection-off therefore did not eliminate the noise.

The interruption has a likely measurement cause: 0.61 seconds after PA-on the
harness requested its seven-register active-stream snapshot through the shared
WCD/SLIMbus bridge. That transaction occupied about 165 ms. No XRUN, Q6 stall,
bank change, PA event or SoundWire error accompanied the gap; Q6 remained
`19/19/0`. A clean A/B therefore removed the controller snapshot while samples
were flowing; pre/post snapshots and non-reading DP1/DP4 shadow logs retained
the other safety evidence.

The listened no-snapshot repeat then produced only a clack, low-volume static
and the closing clack: no 440-Hz tone. Yet it was host-identical to the audible
run (S16/48k/C1, `19/19/0`, DP1/DP4 shadows, full PA lifecycle), and even kept
`MCP_SLV_STATUS=1` before and after playback. The only confirmed audible v22
included the active controller read. Treat that read as a possible marginal
transport-latch/wake operation rather than removing it outright.

The next harness opens one PCM containing three seconds of exact stereo digital
zero followed by five seconds of 440 Hz on C1. It runs the controller snapshot
during the zero prefix, leaving over a second for the shared bridge to settle
before tone samples begin. This keeps the only operation correlated with
audibility, prevents it from cutting audible samples, and adds no live mixer
write or second Q6 session.

The first pre-roll run again produced clack + low static + clack, but it exposed
a test-vector error rather than a transport failure. DP4 read back as
`0x01000607` in both banks and Q6 completed `64/64` with fallback zero. FFmpeg's
default sine amplitude was only -18 dBFS (about 16 dB below speaker-test), and
aplay selected 6000/24000-frame period/buffer sizes. The harness now scales the
right-channel sine to -2 dBFS and explicitly requests the proven 12000/48000
frames, while retaining the three-second zero prefix and active snapshot.

The corrected pre-roll control was still completely inaudible. It nevertheless
proved active DP4 `0x01000607` in both banks, used the verified waveform SHA-256
`68203ba7c6545c4b3290c416d3763a0eb8f0701d30b5e65e85435803a1b7c90c`,
and completed Q6 `32/32` with fallback zero. The problem is therefore below the
host-visible Q6/controller configuration, in nondeterministic slave-write/DAC/
analog state.

V23 tests qcauddev's opt-in PA profile-3 branch. The installed WSA module is
SHA-256 `0f6280ea321daca06a1031f3dfd86b96ca74bbb57d00337a2d119f9d0e5b2d2b`.
Profile 3 writes DAC `c2`, OCP `b4->b6->b2`, driver `fc`, waits 2 ms, and skips
the mutually exclusive non-profile-3 DAC staging and VI diagnostic/teardown;
the existing gain ramp and final `fd/ac` remain. Profile `0` preserves v22 for
rollback. Because Linux deliberately keeps protection/VISENSE off until it can
load runtime `0x1025f` calibration, this is an exact PA-branch test but not the
complete Windows protected profile. GRUB id: `spx-speaker-v23-pa-profile3`.
