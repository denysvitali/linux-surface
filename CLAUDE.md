# Surface Pro X (SQ2, sc8180x) — speaker bring-up

## The goal

Make the built-in speakers work **fully**: clean audio, at maximum volume if wanted,
from both speakers, surviving normal use (not just one stream after a cold boot).

## Where we are (2026-08-09)

Audio plays, but it is not clean. Live listening on 2026-07-28 confirmed:

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

Only the **left** amp (DT `pin1`, physically the RIGHT speaker — the DT names are
inverted) is brought up. The second amp is untouched.

## Hard rules

- **Never reboot or power off the machine without explicit user authorization.**
  The user has authorized the guarded one-time GRUB feedback loop for the current
  speaker work; keep the persistent default on `spx-audio-rescue` and never arm a
  test entry until all logging, watchdog and rollback checks pass.
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
- Never read `/sys/module/soundwire_qcom/parameters/spx_reenum` (write-only, blocks
  forever), never read pinctrl `pinmux-pins`/`pins` on sc8180x (oops, reboot-only),
  never read MMIO `171c0000+0x2000`, never probe GLINK/rpmsg channels (ADSP crash).

## Testing etiquette

Every result comes from the user *listening*. That is expensive and tiring — make
each test high-information, run at most one tone per configuration change, and never
ask about a run whose preconditions were invalid (e.g. amp not attached: check
`MCP_SLV_STATUS`/"writes go to device" first). Prefer register captures over listens.

**Only the first stream after a cold boot is a valid quality measurement.**

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
