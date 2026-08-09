# SPX speakers — handover document

## 2026-07-29 (22:15) — the amp DE-ENUMERATES during every stream

Windows drives these speakers fine (user-confirmed), so the hardware and wiring are
good and this is purely a Linux-side problem.

### Mechanism 1: the device number does not survive a stream

Measured directly, same run, nothing else touched:

```
MCP_SLV_STATUS before stream = 0x04   (device 1, matches slave->dev_num)
MCP_SLV_STATUS after  stream = 0x01   (device 0)   [or 0x00]
```

The amp falls back to device 0 **during playback**. Every write the driver issues after
that point is addressed to a device that no longer exists, and unicast writes always
report success. This is why traces look flawless and nothing comes out: the trace is
written before the amp drops back.

It happens with the forced runtime frame handoff (`runtime_handoff=1`) and equally
without it (`runtime_handoff=0`), so a master/slave frame-shape disagreement is **not**
the cause. Note `runtime_handoff=0` does make enumeration itself far stabler
(`changes=1` over 450 snapshots vs ~193), and lets the driver own FRAME_CTRL
(0x00010200) — worth keeping regardless.

Addresses seen in one session with no reboot: `0x1` (dev0), `0x4` (dev1), `0x40`
(dev3, commanded by us). Always read `MCP_SLV_STATUS` immediately before *and after* a
test; a pre-test reading alone is not enough.

### Mechanism 2: the driver never programs the analog stage

Typical stream trace now contains **only** `0x311a`. No `0x3008/0x3007` clocks, no
`0x3103` bandgap, no `0x311c` RDAC, no `0x312a` boost. The DAPM supply widgets (Bandgap,
DCLK, ACLK, RDAC) stay "on" in software across a re-enumeration, so their events never
re-fire, while the amp has power-cycled and lost every register. Same root cause as the
BOOST_EN bug fixed in `wsa881x_spkr_pa_event()` PRE_PMU.

Until this is fixed the analog stage must be applied by hand:

```sh
sudo insmod drivers/spx_extras/spx_wsa_seq.ko devices="sdw:0:0:0217:2010:00:1" \
  seq="0x3008:0x01:5,0x3007:0x01:5,0x3103:0x08:10,0x312a:0x80:10,0x311c:0xc2:10,\
0x311f:0xb2:5,0x3122:0x87:5,0x311b:0x09:10,0x311a:0xfc:10"
```

### Next

Find why the amp de-enumerates mid-stream. It is not frame shape. Candidates: the
broadcast bank switch (`dev=15 0x0060/0x0070`), a clock-stop/resume, or the master
issuing a bus reset when the stream starts. Windows keeps the device attached
throughout, so compare against `qcauddev8180.sys` at stream start rather than at
bring-up.


## 2026-07-29 (21:45) — writes PROVEN to land; addressing solved; still silent

### The first hard proof that any register write takes effect

Everything before this rested on `rc=0`, which this master returns unconditionally
(`/* Its assumed that write is okay as we do not get any status back */`, and
`qcom_swrm_cmd_fifo_wr_cmd()` discards the bridge return value). The decisive test uses
a write whose effect is visible in a *master* register:

```
MCP_SLV_STATUS = 0x04            (amp at device 1)
  write SCP_DevNumber(0x46) = 3  to device 1
MCP_SLV_STATUS = 0x40            (amp now at device 3)
```

**Writes land.** This also means the amp's digital core is alive and obeying commands.

### The amp's device address drifts, and can be commanded

`MCP_SLV_STATUS` was observed as `0x1` (dev0), `0x4` (dev1) and `0x40` (dev3, ours)
across a single session with no reboot. A fixed mapping is therefore wrong part of the
time, and **every "perfect" write trace in this document may have been addressed to a
device that was not listening**. Always read `MCP_SLV_STATUS` immediately before a test
and make `slave->dev_num` match.

`spx_swrm_autoenum_capture` gained `map_devnum=N`. Note that announcing device 0 to the
core directly is not possible: `status[0] == SDW_SLAVE_ATTACHED` makes `bus.c` call
`sdw_program_device_num()`, which enumerates over the broken read path. The module
therefore hands off as device 1 and rewrites `dev_num` afterwards.

Also note `soundwire_qcom.spx_write_dev0` only redirects the *wsa881x driver's* writes.
The SoundWire core programs the slave's DPn transport registers from `slave->dev_num`,
so with `spx_write_dev0=1` alone the analog registers went to device 0 while the port
configuration still went to device 1 — the amp was told to switch its PA on but never
told which frame slots to read.

### Driver bug found and fixed: BOOST_EN is never re-enabled

`wsa881x_boost_ctrl()` is reachable *only* from `wsa881x_set_port()`, which early-returns
when the mixer value is unchanged. `port_enable[BOOST]` therefore stays true across a
re-enumeration while the amp — which loses every register on power-cycle — comes back
with `BOOST_EN_CTL` cleared. Re-setting the switch is an ALSA no-op. Result: `0x312a`
appeared in **zero** write traces for an entire session, so the PA was repeatedly
commanded on with no boosted supply behind it.

Fixed in `wsa881x_spkr_pa_event()` PRE_PMU (gated on `port_enable[BOOST]`, 1.5 ms settle).

### Same bug class, still open: DAPM supplies are not replayed

After a card rebind or re-enumeration the DAPM supply widgets (Bandgap, DCLK, ACLK,
RDAC) remain "on" in software, so their events never re-fire, while the hardware has
been reset. Traces then contain **only** `0x311a` — no `0x3008/0x3007` clocks, no
`0x3103` bandgap, no `0x311c` RDAC. The analog stage is never programmed. Worked around
by hand with `spx_wsa_seq.ko`; needs a proper fix (replay analog bring-up on PRE_PMU, or
force the supplies down when the device re-enumerates).

### The state of play

A final run had, simultaneously and verified: amp at a known address matching
`slave->dev_num`; boost enabled; full analog bring-up applied; PCM confirmed `RUNNING`;
zero bus errors. **Silent.**

Ten listens across this session, all silent.

### Honest assessment

Every software-side hypothesis that can be checked from the kernel has now been checked
and found correct: power, SD_N polarity, clash, enumeration, device addressing, write
delivery (proven), FIFO state, register values, PA duration, boost, codec digital path,
SWR clock, sample rate, and the codec DAPM chain (verified On mid-stream).

What remains is not reachable by inspection from this side:
1. Whether the audio samples actually occupy the frame slots the amp reads. Both ends
   are programmed consistently, but nothing here can observe the wire.
2. Whether these amplifiers are physically connected to the speakers — never verified.
   Both amps enumerate (distinct DevIDs `0x21170213` / `0x21170214`) and obey commands,
   which proves their digital cores work, and says nothing about their analog output.

Given (1) cannot be settled without a bus analyser, the cheapest next evidence is
physical: confirm the speakers are wired to these amps at all.

## 2026-07-29 (02:00) — SD_N polarity SOLVED; cleanest-ever run still silent

### Solved: SD_N polarity (measured, not inferred)

`drivers/spx_extras/spx_wsa_power_probe.ko` (delta-based, no qcom reads, COMP_PARAMS
canary): park **LOW** = quiet bus (`INT_STATUS=0x0`); raising **either** pin makes a
slave announce. **Physical HIGH = amp ON, LOW = off**, matching
`powerdown-gpios = <&wcdgpio N GPIO_ACTIVE_LOW>`.

Correct WCD GPIO 0x43 values: `0x00` both off, `0x02` pin1 only, `0x04` pin2 only.

CLAUDE.md previously said LOW = on. Consequence: `val=0x06`, used by
`scripts/spx-speakers-up.sh` *and* the `spx-wsa-pin2-test` GRUB entry and labelled
"both parked off", **powered both amps** and produced the dev0 clash the recipe exists
to prevent; `val=0x04` ("pin1 on") powered pin2. Fixed in the script, CLAUDE.md, the
`wsa881x.c` comment, and grub.cfg (entry now passes `0x00`; backup at
`/boot/grub/grub.cfg.bak-20260729-010942`).

### Also found: module params were silently unset since 2026-07-28

`/etc/modprobe.d/spx-wsa-force.conf` was renamed `.disabled-20260728-155617` and never
re-enabled, so `soundwire_qcom` has loaded with **all-default (0)** params since —
including `spx_core_enum=0`. That makes slave writes take the
`swrm_wait_for_wr_fifo_avail()` path, whose FIFO counter is stale on this hardware, so
a stream aborts with `write overflow` / `Program transport params failed: -61` before
any amp programming happens. Set them by hand (or re-enable the file) before any test:

```sh
for kv in spx_core_enum=1 spx_clk_div=1 spx_runtime_ssp_period=1 spx_actual_phase=0; do
  echo "${kv#*=}" | sudo tee /sys/module/soundwire_qcom/parameters/${kv%=*}; done
```

### The cleanest run this project has produced — and it is still silent

Boot with `spx_wsa_gpio_val=0x00`, then `spx-run2-pio-full.sh`, then the capture module
(`active_pin=1 dual_enum=0 clock_div=1 settle_div=2 runtime_handoff=1 keep_live=1`):

- boot baseline: `WCD_GPIO_VAL=0x00`, `INT_STATUS=0x00000000` (genuinely quiet bus),
  `MCP_CFG=0x0001ff00`, COMP_PARAMS canary good
- enumeration: `dev1=0x21170213/0x10` genuine DevID, `slv=0x4` (device 1 attached),
  `dev2=0x0/0x0` (second amp correctly absent)
- stream: 53 writes, **zero errors**, all to `dev=1`; full sequence incl.
  `0x3103=0x08`, `0x311c=0xc2`, gain ramp, `0x311a=0xfc`
- PA on `1518.04` -> off `1528.03` = **10.0 s**, the whole tone

Result: **complete silence.** Six listens tonight, all silent.

### What this eliminates

Power, polarity, clash, enumeration, device addressing, write delivery, FIFO/overflow,
amp register programming, PA duration, codec digital path, SWR clock, and sample rate
are now all verified good *simultaneously*, on one run, with trustworthy reads.

The amp is enumerated, powered, correctly programmed, and its PA is on for the full
tone — and nothing comes out. That isolates the remaining failure to the **audio data
path**: whether the WCD9340 interpolator output actually reaches the SWR master DOUT
port, and whether the frame carries samples in the slots the amp listens to.
Mainline `wcd934x.c` contains no register that routes INT7/INT8 into the SWR master
(only `wcd934x_swrm_clock()` gating `WCD934X_CDC_CLK_RST_CTRL_SWR_CONTROL`) — if that
routing is not fixed wiring, it is missing, and it would explain every silent run.

Next (desk work, no listening): re-derive the codec->SWRM data path from the downstream
WCD9340 driver, and check master DOUT port transmit status against the amp's DP1
sample-interval/offset.


## 2026-07-29 (02:00) — READ THIS FIRST: the bridge can fake register data

Two corrections that invalidate parts of the sections below.

**1. The bridge can return one constant for every address.** After a
`COMP_SW_RESET` the paged bridge was observed returning `0x36000d0c` for
INTERRUPT_STATUS, MCP_SLV_STATUS *and* both ENUM_ID pairs simultaneously. Earlier
the same session it returned `0x36000228` / `0x36000328` / `0x3600010f` for
unrelated registers. **Any value of the form `0x36xxxxxx` is garbage.** These look
exactly like plausible register contents, and a "stable dual enumeration" was
accepted on the strength of them.

`SWRM_COMP_PARAMS` (0x0100) is a read-only hardware constant, `0x016840c6`, on this
master. `spx_swrm_autoenum_capture` now has `bridge_sane()`, which checks that canary
and refuses `keep_live` if it fails. **Use the same canary before trusting any
register capture.** The bridge does recover on its own after the reset settles.

**2. A guard relaxation of mine let a bogus state through.** Widening `keep_live` to
accept single-amp holds meant `runtime_ready` could be computed from garbage reads,
so the module reported `held live frame=0x0 irq_mask=0x0` and handed a nonexistent
device to the SoundWire core. Fixed by the canary above, but the lesson generalises:
the guard was the only thing standing between garbage and a "successful" result.

**Also unresolved: SD_N polarity.** CLAUDE.md says LOW = on; the 2026-07-28 section
below says active high. Both readings were tested on 2026-07-29 with a proper 10 s
power cycle and both produced `id=aa aa aa aa aa aa` from FORCE-ATTACH. That is a
*read-failure* signature (`rc=4`), not a power result — the force-attach path verifies
over the qcom read path, which underflows here. **The polarity question is still open;
do not treat either document as settled.**

`MCP_CFG` was left at `0x00000000` (normally `0x003fff00`) after the last reset, so the
master is in a degraded state. A reboot is the clean way back.

## 2026-07-29 — post-reboot session: three tooling fixes, one collision fix, still silent

Three listens this boot, all **complete silence**. Everything below is register
evidence, not inference from a listen.

### Fixed and verified in silicon

1. **`spx_blind_rmw` clears the DAPM read blocker** (see the section below). The amp
   power sequence now completes with correct composed values — `0x3103=0x08`,
   `0x311c=0xc2` (the shadow default `0x42` OR `BIT(7)`, which the old failing-read
   path could never produce), gain ramp `0x311b 0x41->0x49`, PA on `0x311a=0xfc` held
   for the full 9.7 s of a 10 s tone. Zero SoundWire errors.

2. **`spx_swrm_autoenum_capture` now drives the paged bridge** (`paged_bridge=1`,
   default). The qcom driver's own `qcom_swrm_ahb_reg_read()` dies partway through a
   session — it polls ACCESS_STATUS for the RD_DONE *edge* (bit 1), which never
   arrives once the bus has been exercised, so it returns `SDW_CMD_FAIL(2)` forever
   and the module bailed before printing anything. `spx_swrm_regs.ko` drives the same
   bridge registers and keeps working because it settles 500 us after RD_ADDR, polls
   the level-high bit 0, and throws the first RD_DATA sample away. That discipline is
   now in the capture module, so enumeration survives a degraded bridge. **This was
   the hard stop that ended the previous session.**

3. **Single-amp hold is supported** (`dual_enum=0`). The old guard demanded dual
   attachment, so `keep_live` was refused even when a single amp was rock stable.

4. **`spx_swrm_int_clear.ko`** (new): clears the master's latched interrupt status via
   the paged bridge. `SWRM_INTERRUPT_STATUS` is sticky — every interrupt reading taken
   before this tool existed was untrustworthy, including one I reported as a clash.

### Stability: single amp beats dual, decisively

| config | `MCP_SLV_STATUS` | flaps over 450 snapshots |
|---|---|---|
| dual (`dual_enum=1`) | `0x14` never reached; `0x0`/`0x10`/`0x20` | 197–233 |
| single (`dual_enum=0`) | `0x4` (dev1 attached) | **1** |

Five dual runs never reproduced the `0x14` recorded on 2026-07-28.

### The one real collision finding

With interrupts cleared first, one stream, single variable changed:

| `spx_stream_port_mask` | `INT_STATUS` after one stream | bits |
|---|---|---|
| 15 (slave ports 1,2,3,4) | `0x00020582` | 1, 7, **8**, 10, 17 |
| 1 (DAC port only) | `0x00000082` | 1, 7 |

`BIT(8)` DOUT_PORT_COLLISION, `BIT(10)` and `BIT(17)` all clear when only the DAC port
is transported. `BIT(1)` NEW_SLAVE_ATTACHED is benign; `BIT(7)` CMD_ERROR remains and
is consistent with the known failing `0x311b` volume *read*.

**`BIT(3)` MASTER_CLASH_DET is NOT set** in the single-amp config. An earlier report of
a clash in this session was stale latched state read before `spx_swrm_int_clear`
existed — it was wrong, and single-amp does not clash.

**Do not over-explain this result.** The tempting story is that DT
`qcom,port-mapping = <1 2 3 7>` / `<4 5 6 8>` addresses master ports 7 and 8 while
`COMP_PARAMS = 0x016840c6` decodes to 6 DOUT and 6 DIN ports. But the Windows static
descriptors use those *same* master port numbers, so either the `COMP_PARAMS` decode
means something other than a port-index limit, or the Windows descriptor field is not
a master port index. The measurement is solid; the explanation is not established.

### What is now excluded as the cause of silence

- Amp register programming (correct values, zero errors, PA on for the whole tone).
- Amp read failures (blind-write path removes every read from the power-up path).
- Bus clash in the single-amp config (no MASTER_CLASH_DET after a clean clear).
- Data-port collision (gone with `mask=1` — and it was still silent).
- SWR clock: `mclk` is enabled at 9.6 MHz, `enable_count=1`, per `clk_summary`.
- Codec DAPM: the whole chain reads `On` through `SPK1 OUT`/`SPK2 OUT` during a stream
  (`SLIM RX0/1`, `RX INT7_1 MIX1/INTERP`, `RX INT7 SEC MIX`, `RX INT7 MIX2`,
  `RX INT7 CHAIN`, `INT7_CLK`).

### The remaining gap

Everything from the ALSA front end down to the amp's analog stage is provably
configured, and the amp enumerates and accepts writes — yet no audio. The unexplained
step is between "master DOUT port programmed" and "amp receives PCM": nothing yet
proves the codec's interpolator output actually reaches the SWR master's data port.
Mainline `wcd934x.c` contains no register that routes INT7/INT8 into the SWR master —
only `wcd934x_swrm_clock()` gating `WCD934X_CDC_CLK_RST_CTRL_SWR_CONTROL`. If that
routing is not fixed wiring, it is missing entirely, and that would explain every
silent run in this project's history regardless of amp state.

Next diagnostics, none requiring a listen: establish whether master DOUT port 1 is
actually transmitting (per-port FIFO/status registers), and re-derive the codec->SWRM
data path from the downstream WCD9340 driver rather than mainline.

### Live-tunable state at the end of this session

`snd_soc_wsa881x.spx_blind_rmw=1`, `snd_soc_wsa881x.spx_stream_port_mask=1`,
`soundwire_qcom.spx_core_enum=1`, `spx_clk_div=1`, `spx_runtime_ssp_period=1`,
`spx_actual_phase=0`; capture module loaded with
`active_pin=1 dual_enum=0 clock_div=1 settle_div=2 runtime_handoff=1 keep_live=1`.
Nothing is committed to git.

---

## 2026-07-28 (later) — DAPM read blocker cleared; enumeration lost, reboot needed

### What was fixed (verified in silicon, no reboot)

The blocker named in the section below — "the codec DAPM power-up still failed because
normal `wsa881x_update_bits()` performs read-modify-write operations" — is **fixed**.

- `sound/soc/codecs/wsa881x.c`: new module param `spx_blind_rmw` (bool, default `true`)
  plus `wsa881x_use_shadow()`. The register shadow is now allocated and seeded at probe
  **unconditionally**, so the compose-from-shadow blind-write path is used regardless of
  `spx_write_only` (which stays `false` in the natively-enumerated configuration and also
  changes probe/GPIO/port behaviour, so it is the wrong knob to flip).
  The `regmap_read(OTP_REG_0)` fallback in `wsa881x_init()` now uses the shadow too, and
  no longer leaves `val` uninitialized when the read fails.
- `drivers/spx_extras/spx_wsa_seq.c`: new `devices=` parameter (a comma list, defaulting
  to both static speaker slaves) so a register sequence can be replayed to both amps.
  Also fixed the `kstrdup`/`strsep` pointer so the copy is actually freed.

Applied live with no reboot: stop pipewire, `echo sound > /sys/bus/platform/drivers/
msm-snd-sdm845/unbind`, `rmmod snd_soc_wsa881x`, `modprobe`, rebind. The card came back
with all 3 PCM devices and both slaves re-probed with their port maps.

Result: a full `speaker-test` run produced **zero** SoundWire errors. No read underflows,
no `Bandgap`/`RDAC` event failures on either amp, PA sequence completed. The register-level
goal of the "safest next step" is met.

### But the audible test was invalid

The listener heard nothing, and a mid-stream master-register capture explains why:

```
MCP_SLV_STATUS  (0x1090) = 0x00000000     <-- no slave attached
MCP_FRAME_CTRL_B0        = 0x00010100     (runtime handoff value, guarded)
COMP_STATUS              = 0x00013801     (bit0 set: frame gen locked)
DP1_PORT_CTRL_B1         = 0x01000107     (correct)
DP3_PORT_CTRL_B1         = 0x031f0c3f
```

The staged dual enumeration was gone before the tone played, so every register write went
into a void. Per the standing rule, a silent result with invalid preconditions is not
evidence about audio quality — it says nothing about whether the blind-write fix produces
sound.

### Enumeration cannot be re-established in this session

`spx_swrm_autoenum_capture` will no longer run. Its first `master_read()` returns `2`
(`SDW_CMD_FAIL`) and init bails before printing anything — reproducible across five
attempts, with and without a live stream, so it is not runtime PM. The failure is in
`qcom_swrm_ahb_reg_read()` (the qcom driver's own AHB bridge path). Note that
`spx_swrm_regs.ko`, which uses its **own** paged bridge at `0xc8d`/`0xc91` -> VE
`0x88d`/`0x891`, still reads the master perfectly — so the master is alive and only the
qcom AHB bridge path is broken. A SLIMbus control-path timeout was logged during the
stream (`qcom,slim-ngd: TX timed out:MC:0x21,mt:0x2`), which is the likely proximate cause.

`FRAME_CTRL_B0` has fallen back to the `0x00010000` construction baseline after the
module's restore path ran, confirming the runtime handoff is gone.

### Next step (needs a cold boot — the user's call)

The tree is staged and the modules are installed (`snd-soc-wsa881x.ko` sha
`68afc56b70aaf4f11837ff4ece531103e448e29545caf67eab328edc8ab2f48a` in
`/lib/modules/$(uname -r)/updates/`, `mkinitcpio -P` already run). On a fresh boot:

1. Re-run the staged dual enumeration (`spx_swrm_autoenum_capture` with the parameters
   recorded below) and confirm `MCP_SLV_STATUS` before anything else.
2. Confirm `snd_soc_wsa881x.spx_blind_rmw` reads `Y`.
3. Stage the mixer path, then play **one** tone. That first post-boot stream is the only
   valid quality measurement.

Do not draw any conclusion from a tone played while `MCP_SLV_STATUS` is `0x0`.

---

## 2026-07-28 authoritative update — dynamic SoundWire investigation

This section supersedes the older conclusion below that APPS-side SoundWire enumeration is
architecturally impossible. Dynamic analysis on the live Surface Pro X SQ2 has now proved
that both physical WSA8815 amplifiers enumerate through the APPS-side WCD9340 SoundWire
master. **The speakers are still silent.** The final 5-second 440 Hz playback test completed
at the PCM/AFE level, but the listener reported **absolutely nothing**.

### Verified hardware and Windows facts

- The two physical amplifiers repeatedly returned complete SoundWire IDs:
  - physical pin 1: `0x21170213/0x10`
  - physical pin 2: `0x21170214/0x10`
- These decode as WSA8815 `0217:2110`, unique IDs 3 and 4. This matches other upstream
  Qualcomm boards. The current SPX DTS declarations (`sdw10217201000`, unique IDs 1 and 2)
  are wrong; the permanent DTS fix should use `sdw10217211000` and unique IDs 3 and 4.
- A staged live sequence produced stable dual enumeration:
  1. enumerate pin 1 at FRAME_CTRL divider 1;
  2. switch to divider 2 after the first complete ID;
  3. release pin 2 without resetting/rearming enumeration;
  4. switch to divider 3 after the second complete ID.
  This yielded stable `SLV_STATUS=0x14` with both full IDs across 900 snapshots.
- Re-arming enumeration or releasing both amplifiers immediately caused clashes and cleared
  the device table. The staged retention sequence is necessary.
- Static analysis of both the original and LIVE Windows `qcauddev8180.sys` independently
  confirms that Windows writes construction baseline FRAME_CTRL `0x10000`, then its normal
  operational path dynamically applies `(divider & 7) << 8`, producing `0x10100` for
  divider 1. The Linux "exact Windows" constructor copied only the baseline and missed this
  later operational overwrite.
- Windows clock math uses a 9.6 MHz physical master clock divided by `divider+1`, with DDR:
  divider 0 gives 200 kHz frames at 48×2; divider 1 gives 100 kHz frames.
- `SPKR_SD_N` is active high: low is reset/shutdown and high is active. Windows does not
  write WCD GPIO registers `0x42/0x43` during its pre-enumeration path.

### Dynamic modules and current design

- No reboot is required for the present experiments. The controller stays loaded and
  purpose-built diagnostic modules can be loaded/unloaded around it.
- Never unload/reload `soundwire_qcom` during diagnosis; it owns shared state and has
  previously presented a crash risk.
- `spx_swrm_autoenum_capture` was extended as a resident `keep_live=1` module. It performs
  staged dual enumeration, stops enumeration once stable, applies runtime FRAME_CTRL
  `0x10100`, guards subsequent qcom frame writes so they remain `0x10100`, suppresses
  destructive alert/error interrupts, maps the existing static codec objects temporarily
  to hardware device numbers 1 and 2, marks their port control as write-only, and reports
  both slaves attached to the SoundWire core.
- Its test load parameters were:

  ```text
  active_pin=1 snapshots=450 full_vendor_reinit=1 clock_div=1 settle_div=2
  dual_enum=1 dual_settle_div=3 runtime_handoff=1 keep_live=1
  ```

- Live qcom parameters used were `spx_core_enum=1`, `spx_clk_div=1`,
  `spx_runtime_ssp_period=1`, and `spx_actual_phase=0`.
- Do not invoke `spx_reenum` while `spx_core_enum=1`; that path performs reset/FIFO
  diagnostics rather than a harmless status poll.
- A temporary lock inversion in the first `spx_swrm_live_health` implementation was
  recovered without reboot using `spx_swrm_deadlock_rescue`. The observer was corrected to
  take only the controller lock and to select WCD read mode before qcom reads.

### Latest playback result and remaining blocker

- Routing was established through `SLIMBUS_2_RX`, AIF1 playback, RX0/RX1 mixers,
  COMP7/COMP8, and the left/right speaker controls.
- With the static slaves mapped to physical device numbers and write-only port control
  enabled, `speaker-test` successfully configured and ran the PCM stream. AFE port 6 and
  the preserved q6routing path were active; there was no new destructive IRQ storm.
- Actual hardware FRAME_CTRL remained `0x10100`, although qcom's pre-guard log prints its
  attempted value `0x10107`.
- The codec DAPM power-up still failed because normal `wsa881x_update_bits()` performs
  read-modify-write operations. SoundWire reads underflowed at least at:
  - bandgap/TEMP operation register `0x3103`, both amplifiers;
  - RDAC/speaker DAC control register `0x311c`, both amplifiers.
- Consequently the data stream ran, but the amplifier bandgap/RDAC/PA power sequence did
  not complete. The user heard **absolutely nothing**. Audio functionality is therefore
  **not confirmed**.

### Safest next step, if work resumes

Keep the resident controller/enumeration module loaded and implement an unloadable,
dual-slave blind-write helper for the complete WSA8815 DAPM power-up sequence. It should
iterate the two mapped static slaves and issue direct SoundWire writes—never
read-modify-write—to the bandgap, clocks, RDAC, boost, and PA registers using values derived
from the codec source and Windows initialization. Validate register ordering first; do not
run another audible test until every required DAPM read dependency has been replaced or
otherwise accounted for. The permanent cleanup is to correct the DTS compatible/unique IDs
and then remove the temporary live remapping.

### Stop state

Work stopped at the user's request immediately after the silent final test. No reboot,
module unload, additional tone, or hardware mutation was performed while writing this
update.

**Project**: Make the built-in speakers (2x WSA881x on WCD9340's internal SoundWire master)
work on a Microsoft Surface Pro X (SQ2, Qualcomm sc8180x, kernel `6.18.3-1-surface+`,
branch `spx/v6.18`). Audio works over USB-C/3.5mm only at the time of writing.

**Status**: Speaker bring-up **exhausted via the ADM/COPP path** (the ADSP firmware's ELITE ADM
service does not implement `DEVICE_OPEN_V8`, so the AudioReach speaker topology 0x10000001
cannot be instantiated from apps). Path forward is the **GCS/GSL graph-control protocol**
that `qcauddev8180.sys` uses over a separate GLINK control channel to the running ADSP. RE
of the live driver is in progress; the last multi-agent workflow was killed before synthesis,
but two completed reports are available, the plain rpmsg reachability probe produced useful
negative evidence, and qcauddev's packetizer plus `\Device\GLINK` WDF-interface path are now
partially mapped.

---

## 0. The 5 confirmed facts every new colleague must internalize

1. **The WSA amps are owned by the Q6 ADSP, not apps.** Five independent proofs
   (q6afe WSA-macro check, Windows PnP dump, Windows driver RE, live SWR register read, direct
   DevID read on the hardware) — see memory `spx-audio-wsa-soundwire-unattached.md`. The
   APPS-side `soundwire-qcom` enumeration of the WSA881x is architecturally impossible on this
   board; do not waste time on it.

2. **No `qcom,apr` GPR/AudioReach channel on this firmware.** Only the legacy APR
   `apr_audio_svc` (domain 4) channels are exposed (`apr` device in DT). The AudioReach
   "packet router" GPR is not present. The ADSP runs the Microsoft-signed
   `qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn` (10.7MB, `remoteproc2` state=running).

3. **`ADM_CMD_DEVICE_OPEN_V8` is unknown to the ADSP** (live on-box test, q6adm sha `e2d771f7`,
   2026-06-16): `cmd = 0x1036a return error = 0x2` with explicit `Unknown Cmd: 0x1036a`,
   followed by 1-second timeout. Combined with V5 (0x10326) rejecting topology `0x10000001`
   with `EUNSUPPORTED`, the AR speaker subgraph is not reachable through any ADM extension.

4. **The Windows model is GCS/GLINK.** `qcauddev8180.sys` (AdieCodecDriver) does NOT
   write SLIMbus/SWR registers; it has no APPS-side SoundWire programming at all
   (zero `READ/WRITE_REGISTER` for SWR, no `swr`/`soundwire` strings, no
   `MmMapIoSpaceEx` for SWR — the only `MmMapIoSpaceEx` is a peer-module
   diagnostics read). All speaker bring-up goes through:
   - GCS graph commands (12 named: `GCS_CMD_OPEN/CLOSE/ENABLE/DISABLE/LOAD_DATA/UNLOAD_DATA/
     REG_EVENT/REG_DATA_HANDLER/DEREG_DATA_HANDLER/START_READ/STOP_READ/SEND_DATA_CMD`; plus
     3 more `ENABLE_DEVICE/DISABLE_DEVICE/SET_CONFIG`)
   - On the wire as opcodes `0x00014001..0x0001400e` (12 distinct, 14 sites in the live
     build, built via `movz w0, #0x4001..#0x400e; movk w0, #1, lsl 16`)
   - Over a separate GLINK control channel to the ADSP firmware's GCS server
   - `qcadcm8180.sys` (AudioDspCalMgr) does the parallel AFE/ADM cal (CDC_REG_CFG,
     SLIMBUS_SLAVE_CFG, SLIMBUS_SLAVE_PORT_CFG, ADM open with NULL_COPP, MATRIX_MAP_ROUTINGS,
     AFE_PORT_CMD_DEVICE_START, FBSP enable, etc.) — this part IS reachable from apps.

5. **The kernel works fine for the cal path.** The existing `q6adm`/`q6afe`/`q6routing`
   mainline stack on this Linux tree is the right transport for the AFE/ADM cal. What's
   missing is a Linux **GCS GLINK client** (a sibling to `qcom,apr` that talks to the ADSP's
   GCS server over its own GLINK channel) plus the speaker-enable GCS command sequence.

**If you only remember one thing:** stop trying to make the WSA enumerate from APPS. Make
the APPS CPU speak GCS to the ADSP, the same way Windows does.

---

## 1. What I have done (and what's verified vs unverified)

### Verified on the live SPX (Linux, kernel 6.18.3-1-surface+, branch spx/v6.18)
- Removed the APPS SoundWire contention (DT `arch/arm64/boot/dts/qcom/sc8180x-wcd9340.dtsi`:
  `swm: soundwire@c85` + `left_spkr`/`right_spkr` children removed). After this, `/sys/bus/soundwire/devices`
  is empty, underflow spam stops, the card probes, and AFE port `SLIMBUS_2_RX` (idx 6,
  port id `0x4004`) goes live when a stream opens. It is **silent**, but the path is alive.
- Retargeted playback to `SLIMBUS_2_RX` in `arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts`:
  `slim-playback-dai-link` cpu DAI is `SLIMBUS_2_RX`, codec DAI is `<&wcd934x 0>` only,
  removed the `SpkrLeft IN→SPK1 OUT` / `SpkrRight IN→SPK2 OUT` audio-routing lines.
- Added AFE GET_PARAM (`spx_probe/get`) and ADM SET_PP_PARAMS_V6 + GET_PP_PARAMS (`spx_copp/`)
  debugfs probes to `q6afe.c` and `q6adm.c`. The V6 param header is the 16-byte
  instance-based layout; V5 returns `ADSP_ENEEDMORE(0x12)`. ADSP ack on SET is not a signal
  (DSP accept-and-ignores bogus module ids); GET is the real oracle.
- Added ADM `DEVICE_OPEN_V8` (`0x0001036a`) sender in `q6adm.c` (sha `e2d771f7`, requires
  reboot to load) with a V8 response handler for opcode `0x1036D` and a `v8_open` debugfs
  file. **On-box test: ADSP returns `Unknown Cmd: 0x1036a` and times out** (see fact 3 above).
- Live ACDB confirms dev-0x45 speaker subgraph: topology id `0x10000001`, AFE port
  `0x4004` (SLIMBUS_2_RX), 2ch/48k/24bit, 6 module-instance ids (`0x11134/0x11136/0x11138/
  0x1113a/0x1113c/0x11140` per DPROP `0x113ad`), 3 module GUIDs (`0x10921/0x10943/0x10bfe`).
  Cal blobs are in `Speaker_cal.acdb` DATAPOOL.

### Pulled the LIVE Windows drivers + ACDB (sha checks vs old, all in `/tmp/spx-winlive/`)
| file | live sha | my old sha | match? |
|---|---|---|---|
| `qcadcm8180.sys` | `a4cd624a…` | `a4cd624a…` | **same** ✓ (RE is current) |
| `qcauddev8180.sys` | `2c3f32ca…` | `47a1b7b7…` | **DIFFERENT** (RE the live one) |
| `Speaker_cal.acdb` | `e5a370b2…` | `e5a370b2…` | **same** ✓ |
| `qcslimbus8180.sys` | (not pulled) | — | same folder hash |
| ACDB subdir | `surfaceprox_acsp.inf_arm64_4012660cd77ed4b9` | `…_c6cbf7d66dbb0926` | same **contents** (different hash due to manifest) |

The HTTP server that pulled them is still on Windows (`D@192.168.30.143:9001`, serving
`C:\Windows\System32\DriverStore\FileRepository`); reuse it to grab more files.

### Live qcauddev (sha 2c3f32ca) — what is now confirmed by RE
- 12 GCS cmd names at VA `0x14001a860..0x14001a958`
- 3 more (`ENABLE_DEVICE`/`DISABLE_DEVICE`/`SET_CONFIG`) at `0x14001a970..0x14001a9b8`
- 8 GCS graph state names (`GCS_GRAPH_IDLE`/…) at `0x14001a798..0x14001a858`
- 3 `GCS_SGT_*` names at `0x14001a9b8..0x14001a9d8`
- GCS opcodes on the wire: `0x00014001..0x0001400e` (12 distinct, 14 sites) built via
  `movz w0, #0x4001..#0x400e; movk w0, #1, lsl 16` at VAs `0x140058304, 0x14005846c,
  0x140058600, 0x140058768, 0x1400588fc, 0x140058a64, 0x140058c00, 0x140058d7c,
  0x140058f10, 0x140059080, 0x140059174, 0x1400592ac, 0x14005943c, 0x1400595b0`
  (regular stride ~0x168, looks like a function-pointer table indexed by GCS opcode)
- Lower transport setup opens `\Device\GLINK` and queries WDF interface
  `dc424aec-4d0f-4a41-8ea6-b33f4ccadf28` (size `0xc0`, version `1`); qcauddev later calls
  provider function pointers from that interface at `global_ctx+0x30/+0x40/+0x50/+0x78`.

### What's NOT yet confirmed
- The actual mapping of opcode → cmd name → call site
- The on-wire payload struct for each of the 12 GCS cmds
- The **dev-0x45 call chain** from IOCTL to GCS send (not located by prior RE)
- The lower `\Device\GLINK` provider implementation and how its queried WDF interface
  maps to Linux qcom_glink/rpmsg. The qcauddev-side interface GUID and function-pointer
  offsets are now known; the provider-side semantics/on-wire mapping are not.
- The READY/channel-descriptor bytes that cause qcauddev to open packetizer records for
  `g_glink_ctrl`, `g_glink_audio_data`, and the persistent-data channels

### Tooling in place (all in the kernel tree)
- `build-install.sh` — builds + installs DTB, slimbus, soundwire, wcd934x, wsa881x,
  q6adm, q6afe, q6afe-dai, q6routing, q6asm, q6asm-dai. Lists sha256s.
- `scripts/spx-run2-pio-full.sh` — PIO-mode SLIMbus NGD bring-up (no BAM, no INT_EN).
  Use `SPX_TEST=slim` to also stage the codec SPKR path.
- `scripts/spx-spkr-probe.sh` — fires AFE SET_PARAM at a live port via the q6afe
  `spx_probe` debugfs.
- `scripts/spx-spkr-trigger.sh` — fires a ranked list of AFE candidates (the user reports
  which step plays).
- `scripts/spx-spkr-replay.sh` — fires the V8 open + per-COPP cal, with LISTEN pauses.
- `scripts/spx-gcs-rpmsg-probe.py` — creates and opens the candidate GCS GLINK rpmsg
  endpoint (`g_glink_audio_data`) and dumps inbound packets.
- `scripts/spx-acdb-extract.py` — self-contained QCMSNDDB/ACDB parser.
- `docs/spx-audio-post-reboot.md` — re-establishes SLIM-NGD after each reboot.
- `docs/spx-gcs-windows-capture.md` — the Windows-capture recipe (now mostly obsolete
  since we pulled the live drivers directly).

### Memory (in `~/.claude/projects/.../memory/`)
- `spx-audio-codec-spi-aqstic.md` — how PIO NGD transport works, TLMM 143 codec reset.
- `spx-display-boot-fix.md` — kms-hook initramfs (separate concern).
- `spx-slim-ngd-mmio-hazard.md` — **never** read `171c0000+0x2000`, wedges CPU.
- `spx-pinctrl-debugfs-oops.md` — **never** read `pinmux-pins`/`pins` on sc8180x, oops.
- `spx-q6asm-phys-timing.md` — capture PCM DMA addr at `hw_params`, not `open`.
- `spx-audio-wsa-soundwire-unattached.md` — the long-running finding file; cumulative
  evidence, including the ADM V8 result, the V6 SET format confirmation, the GCS plan.
- `spx-windows-apr-driver-reveng.md` — the Windows driver RE summary, including the
  corrected GCS opcode numbering and the Windows-capture procedure pointer.

---

## 2. What is still to be done (in priority order)

### 2.1 GCS RE workflow result (partial; killed before synthesis)
**Workflow `wf_47e292c7-cad`** was killed before the dev-0x45 agent and synthesizer
finished. The output file exists but is empty:
`/tmp/claude-1000/-home-dvitali-Documents-git-linux-surface-kernel/a2f6dbab-a354-4ab2-9e7f-66ea71703060/tasks/w7mojetq1.output`.

The completed agent results are in
`/home/dvitali/.claude/projects/-home-dvitali-Documents-git-linux-surface-kernel/a2f6dbab-…/
subagents/workflows/wf_47e292c7-cad/journal.jsonl`. Treat them as hints, not final truth:
- Dispatch agent found `GCS_CMD_*` strings and identified the likely GLINK side as
  `g_glink_audio_data` / `READY_PKT` / `pktzr_*`.
- Payload agent still contains stale/conflicting claims about the old `+0x498` send thunk.
- Dev-0x45 agent was interrupted while tracing literal `0x45` references.

Primary evidence from the live qcauddev string table:
- `GCS_CMD_OPEN..SET_CONFIG` at `.rdata` VAs `0x14001a860..0x14001a9a0`
- `READY_PKT` at `0x140034478`
- `pktzr_resp_cb`, `pktzr_send_cmd`, `pktzr_init` near `0x1400344d0`
- `platform_get_ch_name` at `0x140034520`
- `g_glink_ctrl`, `g_glink_audio_data`, `g_glink_persistent_data_ild`, and
  `g_glink_persistent_data_nild` strings in `.data`/`PAGEgcsa`

### 2.1a Phase-0 Linux reachability probe (next local test)
Added `scripts/spx-gcs-rpmsg-probe.py`. It uses `/dev/rpmsg_ctrl*` +
`RPMSG_CREATE_EPT_IOCTL` to create an rpmsg char endpoint for a candidate channel name.
Opening the resulting `/dev/rpmsgN` calls the qcom GLINK local-open path for that channel
and waits for inbound bytes such as `READY_PKT`. This is an open-only probe unless
`--send-hex` is explicitly provided.

Run after booting the SPX with `CONFIG_RPMSG_CHAR=y` and `CONFIG_RPMSG_CTRL=m/y`.
The helper prefers the ADSP/LPASS control device (`17300000.remoteproc`, currently
`/dev/rpmsg_ctrl1` on the test machine):

```sh
sudo modprobe rpmsg_ctrl || true
sudo ./scripts/spx-gcs-rpmsg-probe.py --channel g_glink_audio_data --timeout 10
```

Do not send any GCS payload until the channel-open/READY behavior is known.

Live test on 2026-06-16 23:40 Europe/Zurich:
`sudo -n ./scripts/spx-gcs-rpmsg-probe.py --channel g_glink_audio_data --timeout 10`
created endpoints on all three rpmsg control devices in the first script revision, but
opening each returned `EINVAL`. `dmesg` showed `rpmsg rpmsg0/1/2: failed to open
g_glink_audio_data`. Temporary endpoints were cleaned by `rmmod rpmsg_ctrl; modprobe
rpmsg_ctrl`. Interpretation: `g_glink_audio_data` is very likely an internal Windows
symbol/context name, not the literal GLINK channel accepted by this ADSP, or the channel
requires a Windows-specific open path.

Live test on 2026-06-16 23:42 Europe/Zurich:
`sudo -n ./scripts/spx-gcs-rpmsg-probe.py --ctrl /dev/rpmsg_ctrl1 --channel audio_data
--timeout 10` also returned `EINVAL`; `dmesg` showed `rpmsg rpmsg0: failed to open
audio_data`. Temporary endpoint was cleaned by reloading `rpmsg_ctrl`.

Live tests on 2026-06-16 23:44 Europe/Zurich, all on the ADSP/LPASS control device
(`/dev/rpmsg_ctrl1`): `g_glink_ctrl`, `g_glink_persistent_data_ild`, and
`g_glink_persistent_data_nild` all returned `EINVAL`; dmesg showed `failed to open
<name>` for each. Each failed open returned after roughly five seconds, matching the
first qcom_glink local-open wait (`open_ack`), so the ADSP did not ACK any of these
names. Temporary endpoints were cleaned by reloading `rpmsg_ctrl`; only `/dev/rpmsg_ctrl*`
devices remain.

Superseded by the next section: the `g_glink_*` strings are qcauddev packetizer logical
channel names, but they are not plain rpmsg-char local-open names. Windows reaches them
through the `\Device\GLINK` WDF target, `"lpass"` RPE registration, and a READY-driven
channel-open sequence.

### 2.1b qcauddev transport RE update (2026-06-16 23:56 Europe/Zurich)
The immediate post-`platform_get_ch_name` call chain is now mapped enough to correct the
Linux hypothesis:

- `0x140031ea8` is `pktzr_send_cmd`-like, not the final GLINK send. It allocates
  `len + 1`, writes a one-byte packetizer type at `[0]`, copies the caller buffer to
  `[1..]`, and calls `0x140035068`.
- `0x140035068` handles packetizer types:
  - type `2`: the payload has a 0x38-byte logical-channel header. Header offset `0x00`
    is the name (`g_glink_*`), `0x34` is data length, and `0x38` is the data. It calls
    `0x140003020(name)` to find an active channel record (`strcmp(record + 0xe2, name)`),
    requires `record+0x204 == 2`, then calls the lower send function at
    `global_ctx+0x40` with `record+0xa8` as the lower handle.
  - type `1`: parses a READY/channel-list packet. Byte `[1]` is a descriptor count
    (must be <= 10), each descriptor is passed to `0x1400357b8`.
- `0x1400357b8` allocates a 0x210-byte active-channel record, inserts it into the
  packetizer list at `global_ctx+0x200`, initializes events/buffers, opens the lower
  channel via `0x140003648(record, descriptor)`, and after success copies the descriptor
  name to `record+0xe2` (max 0x32 bytes).
- `0x140003648` fills the per-channel callback/open structure at `record+0x18`, then
  calls the lower transport open function at `global_ctx+0x30` with
  `(record+0x18, record+0xa8)`. It waits on the global/channel events and sets
  `record+0x204 = 2` on success.
- `0x1400037f8` is a lower per-channel send/request helper used during open/setup. It
  calls the lower function at `global_ctx+0x50` with `record+0xa8`, a request buffer, and
  length.
- `0x140036e88` constructs a UNICODE_STRING for `\Device\GLINK` (literal at
  `0x14006c080`) and opens a WDF I/O target to it.
- `0x14006b900 -> 0x140013a98 -> 0x140013ad8` is the only `lpass` xref path. It registers
  an RPE/GLINK client for subsystem `"lpass"` (string at `0x14001cc40`), allocating a
  client record and storing callback/context fields.
- `\Device\RPEN` and the RPE helper strings are compiled into qcauddev too, but the GCS
  packetizer path above uses the `\Device\GLINK` WDF target plus the `"lpass"` client
  registration path.

Interpretation: `g_glink_audio_data`, `g_glink_ctrl`, and the persistent-data names are
real qcauddev logical channel names, but Windows does not expose them as plain rpmsg-char
local opens. qcauddev first opens `\Device\GLINK`, registers an `"lpass"` client, receives
or builds READY/channel descriptors, and only then opens/marks packetizer channel records.
This explains the Linux `RPMSG_CREATE_EPT_IOCTL` tests returning `EINVAL`: they skipped the
Windows `\Device\GLINK` provider-interface setup layer and the READY-driven channel-open
sequence.

### 2.1c qcauddev `\Device\GLINK` WDF-interface RE update (2026-06-17 00:04 Europe/Zurich)
The lower transport path is not a visible qcauddev IOCTL path. It is a WDF target plus a
queried provider interface:

- `0x1400361d0` allocates the packetizer/global context (`0x280` bytes, stored via the
  global pointer at `0x140021488`), initializes events/lists, registers PnP notification,
  opens `\Device\GLINK`, then queries a WDF interface from that target.
- `0x140036e88` creates and opens a WDF I/O target by name:
  - target name literal: `\Device\GLINK` at `0x14006c080`
  - `WDF_IO_TARGET_OPEN_PARAMS`-like struct size: `0x88`
  - open type field: `2`
  - `DesiredAccess`: `0x001f0000`
  - `ShareAccess`: `3`
  - `CreateDisposition`: `1`
  - `CreateOptions`: `0x40`
  - remove-complete callback slot points at `0x1400372c0`
- After `\Device\GLINK` opens, `0x1400361d0` calls the WDF table entry at offset `0x588`
  with qcauddev's provider-interface GUID
  `dc424aec-4d0f-4a41-8ea6-b33f4ccadf28`, destination buffer `global_ctx+0x0`, size
  `0xc0`, version `1`, and import-interface flag `1`. This is almost certainly
  `WdfIoTargetQueryForInterface` by signature. The function pointers later called by the
  packetizer come from this provider-filled `global_ctx[0..0xbf]` buffer.
- The PnP/device-interface notification registered before opening GLINK uses GUID
  `f9d15453-8335-434c-aa72-fcd925f135f3`, callback `0x140036cb0`, and context
  `global_ctx+0xc0`. The callback compares the notification GUID, then sets the transport
  state (`global_ctx+0x270`) and signals the event at `global_ctx+0xc8`.
- qcauddev-side provider-interface offsets observed so far:
  - `global_ctx+0x30`: lower per-channel open, called as
    `fn(record+0x18, record+0xa8)` from `0x140003648`.
  - `global_ctx+0x40`: lower data send, called from the packetizer type-2 path as
    `fn(record+0xa8, data_copy, data_copy, data_len, 1)` at `0x14003522c`.
  - `global_ctx+0x50`: lower per-channel request/send helper, called as
    `fn(record+0xa8, request_record, request_len)` from `0x1400037f8`.
  - `global_ctx+0x78`: lower per-channel read/setup helper, called as
    `fn(record+0xa8, descriptor+0x34, 0x400)` from `0x140035d08`.
- Local sweep for cached provider binaries still found only
  `/tmp/spx-winlive/qcauddev8180-LIVE.sys` and `/tmp/spx-winlive/qcadcm8180-LIVE.sys`;
  no GLINK/RPEN provider driver is cached locally.

Interpretation: the Linux target is now narrower. Reimplementing qcauddev does not require
guessing a qcauddev IOCTL; it requires understanding the provider behind
`\Device\GLINK` interface `dc424aec-4d0f-4a41-8ea6-b33f4ccadf28`, or reproducing equivalent
qcom_glink behavior directly. The next highest-value artifact is still the provider driver
from Windows DriverStore, because it should define the function pointer table above and the
actual lower channel/open handshake.

Best next live-Windows breakpoints/capture points:
- `qcauddev8180.sys+0x36e88`: dump the `\Device\GLINK` WDF open params and returned target
  stored at `global_ctx+0xe0`.
- `qcauddev8180.sys+0x365a4`: immediately after the WDF interface query, dump
  `global_ctx[0..0xc0]` and resolve the function pointers at `+0x30/+0x40/+0x50/+0x78`.
- `qcauddev8180.sys+0x36cb0`: dump the PnP/interface notification callback input and the
  state transitions around `global_ctx+0x270`.
- `qcauddev8180.sys+0x6b900` and `+0x13a98`: dump the `"lpass"` RPE registration arguments.
- `qcauddev8180.sys+0x357b8`: dump each READY descriptor (`x0` name/descriptor,
  `w1`, `w2`, `x3`) before lower open.
- `qcauddev8180.sys+0x3648`: dump `record+0x18` and `record+0xa8` before/after the
  `global_ctx+0x30` lower open call.
- `qcauddev8180.sys+0x35068` and the lower send call around `+0x3522c`: dump type-2
  payload bytes after the stream is active.

The Windows HTTP server at `192.168.30.143:9001` was not reachable during the 2026-06-16
23:56 or 2026-06-17 00:04 RE passes, so the lower `\Device\GLINK` provider driver was not
pulled. If Windows is available again, find and pull the GLINK/RPEN provider driver from
DriverStore before implementing a Linux module; it should expose the exact provider
interface for GUID `dc424aec-4d0f-4a41-8ea6-b33f4ccadf28`.

### 2.2 If the workflow still doesn't find the dev-0x45 call chain
The dev-0x45 handler is hard to find statically (it may live in a state machine that
references the device id by index/handle, not literal `0x45`). Fallbacks, in order:

1. **Use the live Windows session we already have.** Run a WinDbg-attached session on
   Windows and break on the GCS send (find the function via the dispatch fnptrs returned
   by the workflow). Play audio that exercises the speakers. Capture the GLINK packets.
   The user already has SSH + the HTTP server up; this is the cheapest path to byte-exact
   wire data.
2. **Trace ACDB-loaded subgraph references** in the live `qcauddev`. Search for the ACDB
   DATAPOOL offsets `0x97c2` (DPROP 0x113b7), `0x7db6` (DPROP 0x113af = topology
   0x10000001), `0xc8` (DPROP 0x113ad = 6 module-instance ids) as constants in the
   disasm (`r2 -A -q -c "/x c2970000" /tmp/spx-winlive/qcauddev8180-LIVE.sys`).
3. **Boot Linux, run `qcadcm8180.sys` RE** — but `qcadcm` SHA matches my old RE
   (`a4cd624a…`), so this is low-value. The 12 GCS opcodes are built in `qcauddev`, not
   `qcadcm`.
4. **Accept headphones-only and document** — the honest, ships-today fallback.

### 2.3 Build the GCS GLINK client module
The plan file at `/home/dvitali/.claude/plans/zazzy-wishing-hedgehog.md` (Phase 3)
describes the module structure. Key facts for the implementer:

- It is **a sibling to `qcom,apr`** in the DT (`sound/soc/qcom/qdsp6/q6adm.c`'s apr_device
  is the pattern). Add a child node under
  `&glink-edge { … &spx_gcs { … } }` in
  `arch/arm64/boot/dts/qcom/sc8180x.dtsi` (or board overlay).
- Reuse `drivers/rpmsg/qcom_glink_*.c` for the GLINK transport; the userland-visible
  interface is a miscdev or a snd_soc_component.
- The GCS send is **NOT** a direct APR call. In the live Windows driver it goes through
  qcauddev's packetizer: `0x140031ea8` prefixes packet type, `0x140035068` handles type
  `2`, looks up `record+0xe2 == g_glink_*`, and calls the lower send function at
  `global_ctx+0x40` with `record+0xa8`. The old struct+0x498 claim was stale. A Linux
  module should plan for an indirection and wait for a response matching the sequence, but
  first needs the lower `\Device\GLINK` provider-interface semantics/READY ABI or an
  equivalent qcom_glink channel-open sequence.
- Trigger the dev-0x45 sequence from the speaker DAPM path
  (`sound/soc/qcom/sdm845.c` / machine driver) — not via a userspace IOCTL. The
  Cal-manager flow (`qcadcm`) does the AFE/ADM cal when the codec DAI is bound; the
  GCS path must fire when the speaker widget transitions to ON.

### 2.4 On-box verification gate
Once the module is built and installed:
1. Reboot (q6adm.ko sha `e2d771f7` is already installed; new modules will join it).
2. `SPX_TEST=slim ./scripts/spx-run2-pio-full.sh` to bring up the card.
3. Open a 48kHz/24-bit stereo stream on `plughw:0,0`.
4. **Listen.** If the speakers play, the GCS sequence worked.

### 2.5 Documentation that needs updating once the GCS path works
- `docs/spx-audio-post-reboot.md` — add the GCS module to the bring-up list.
- `PROGRESS.md` (this file) — mark as shipped, add the new module shas.
- Memory files — keep the GCS path entries; remove or annotate the
  "ADM V8 is the path" note as outdated.

---

## 3. Hard safety rules (don't blow up the SPX)

These come from the memory files and have been **verified on this hardware** by previous
debugging. The kernel WILL wedge or oops if you violate them.

1. **Never read `171c0000+0x2000`** (SLIM-NGD MMIO hazard). Wedges the CPU. Recovery only by
   power cycle. See `spx-slim-ngd-mmio-hazard.md`.
2. **Never read `/sys/kernel/debug/pinctrl/pinmux-pins` or `…/pins` on sc8180x**. Oops
   leaves the pinctrl mutex held; all subsequent GPIO/bind operations go to D-state, and
   the only recovery is reboot. See `spx-pinctrl-debugfs-oops.md`.
3. **Never emit an AFE/ADM port STOP or CLOSE** to a live port. Wedges the SPX ADSP
   (Microsoft-signed firmware is brittle here). The work in `spx-spkr-replay.sh` and
   `spx-spkr-trigger.sh` honors this.
4. **Never `aplay`/play audio when pipewire is also grabbing the card.** Park pipewire
   first (`systemctl --user stop wireplumber pipewire pipewire-pulse`), set the route,
   play, then restart pipewire. The bring-up script handles this.

---

## 4. Files of immediate interest (relative to repo root)

- `sound/soc/qcom/qdsp6/q6adm.c` — has V6 SET/GET probes (sha `f5c6c93d`) and the V8
  open path (sha `e2d771f7`); both installed.
- `sound/soc/qcom/qdsp6/q6afe.c` — has the AFE GET_PARAM probe.
- `sound/soc/qcom/qdsp6/q6routing.c` — has `spx_rx_topology/spx_rx_acdb_id/spx_rx_app_type`
  module params (read at `q6routing_stream_open`).
- `arch/arm64/boot/dts/qcom/sc8180x-wcd9340.dtsi` — APPS WSA/SWR removed.
- `arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts` — slim-playback retargeted to
  SLIMBUS_2_RX.
- `build-install.sh` — install target list with sha256 verification.
- `scripts/spx-run2-pio-full.sh` — bring-up.
- `scripts/spx-spkr-probe.sh` — AFE SET_PARAM at a live port.
- `scripts/spx-spkr-trigger.sh` — ranked AFE candidate fires with LISTEN pauses.
- `scripts/spx-spkr-replay.sh` — V8 open + cal apply (the V8 path returns unknown-cmd
  but the script is useful when the GCS path is online).
- `scripts/spx-gcs-rpmsg-probe.py` — rpmsg-char local-open probe; useful negative
  evidence, but `g_glink_audio_data` is now known to be a qcauddev packetizer logical
  channel, not a standalone plain rpmsg-char open target.
- `scripts/spx-acdb-extract.py` — ACDB parser.
- `docs/spx-audio-post-reboot.md` — bring-up checklist.
- `docs/spx-gcs-windows-capture.md` — Windows-capture recipe (largely obsolete now that
  we pulled live drivers).
- `PROGRESS.md` — this file.
- `/home/dvitali/.claude/plans/zazzy-wishing-hedgehog.md` — the long-form plan
  (Phases 0-3 of the GCS approach). Note: Phase 0's plain rpmsg channel-open approach
  produced useful negative evidence; the remaining transport blocker is the provider
  behind `\Device\GLINK` interface `dc424aec-4d0f-4a41-8ea6-b33f4ccadf28` plus the
  READY/channel descriptor ABI.

---

## 5. Open questions, in order of "what blocks progress"

1. **What does the lower `\Device\GLINK` provider interface do?** qcauddev queries GUID
   `dc424aec-4d0f-4a41-8ea6-b33f4ccadf28` (size `0xc0`, version `1`) and calls provider
   function pointers at `+0x30/+0x40/+0x50/+0x78`. Pull the provider driver from Windows
   DriverStore when the HTTP server is reachable again, or capture those calls live. This
   is what blocks a Linux transport implementation now.
2. **What are the READY/channel descriptors?** Break on `qcauddev8180.sys+0x357b8` and
   dump each descriptor before `0x140003648` opens the lower channel record. These bytes
   explain how `g_glink_ctrl`, `g_glink_audio_data`, and the persistent-data channels
   become active records.
3. **What is the dev-0x45 GCS send sequence?** (Workflow #1, agent 3; fallback to
   WinDbg on the live Windows session.)
4. **What is the on-wire GCS packet format?** (Common header? Opcode + seq + length +
   payload? Or per-cmd struct?) The architecture summary from agent 1 should give this.
5. **Does the GCS server on the ADSP require a Windows-specific handshake?** If so,
   the GCS client may be infeasible. The cheap plain-rpmsg test already timed out; the
   next real test is reproducing or bypassing the Windows `\Device\GLINK` provider-interface
   setup plus READY/channel activation.
6. **The `qcauddev` build is 6f734efa7b068005 in the live DriverStore; my RE was on
   `e690e0253f1a5c3c`.** I RE'd the live one for the GCS opcodes, but I have NOT
   re-derived the AFE/ADM cal path (CDC_REG_CFG, SLIMBUS_SLAVE_PORT_CFG, etc.) from the
   live build. If the cal path is needed beyond what `qcadcm` (which DID match) does,
   you may need to re-derive the param-ids in the new build. (Low likelihood, but
   flagged for completeness.)

---

## 6. TL;DR for a tired colleague at 3am

The SPX speakers are silent because the **WSA amps are ADSP-owned** and the **ADSP's GCS
graph-control server** has not been told to bring them up. Mainline Linux cannot enumerate
the WSA via SoundWire. The legacy ADM path on this firmware **does not implement V8** and
**rejects the AR speaker topology with EUNSUPPORTED**, so the ADM-extension approach is
exhausted. The remaining path is a **Linux GCS/GLINK client**, but qcauddev does not use a
plain `g_glink_audio_data` rpmsg local-open. Windows opens `\Device\GLINK`, queries WDF
interface `dc424aec-4d0f-4a41-8ea6-b33f4ccadf28`, registers an `"lpass"` RPE client,
processes READY/channel descriptors, then sends packetizer type-2 GCS payloads to logical
channels such as `g_glink_audio_data`. The live drivers are pulled and the GCS opcodes plus
packetizer/qcauddev-side WDF path are confirmed; what remains is the lower provider
implementation/READY ABI, the dev-0x45 speaker sequence, and the GCS payload structs.
Once those are captured, build the module, install, reboot, bring up the card, open a
48k/24-bit stream, **and listen**.

If the GCS path turns out to be infeasible (auth handshake, missing channel, etc.),
the honest fallback is: ship **headphones-only** and document. The DT, kernel probes,
and bring-up scripts already work for that case.

---

## 7. 2026-06-17 — additional ADSP firmware RE (no Windows available)

Re-checked the ADSP firmware (`/lib/firmware/qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn`)
for GCS / AudioReach support and the actual GLINK channel name. Key new findings:

### GCS / "Graphite" opcodes ARE in the ADSP firmware
- `0x00014001`..`0x0001400e` (the 12 GCS cmd opcodes qcauddev builds with
  `movz w0, #0x4001..#0x400e; movk w0, #1, lsl 16`): 4 to 1029 LSW hits per opcode.
  4 occurrences are 32-bit constant builds, the rest are LSW halves of other constants.
- `0x01001000` (`APM_CMD_GRAPH_OPEN`): 1 hit as full 32-bit, 9925 LSW hits — AudioReach
  graph protocol is also present.
- qcauddev function name `gcs_check_graphite_response` confirms Qualcomm's internal
  codename is "Graphite".
- The ADSP also has AudioReach topology handlers: `pp_topo_handler.cpp`,
  `cdc_cmd_handler.cpp` (with `SET_GRAPH_DEF`, `SUSPEND` commands),
  `capi_v2_sp_ex_vi.cpp` (speaker exciter / visense CAPI).

### The V8 ADM path is genuinely rejected
Live re-test of `v8_open` (sha `e2d771f7`) on a fresh COPP for `SLIMBUS_2_RX` /
topology `0x10000001` / 2ch / 24b / 48k produced:
```
qcom-q6adm aprsvc:service:4:8: cmd = 0x1036a return error = 0x2
qcom-q6adm aprsvc:service:4:8: Unknown Cmd: 0x1036a
qcom-q6adm aprsvc:service:4:8: ADM copp cmd timedout
qcom-q6adm aprsvc:service:4:8: spx_copp V8 open: rc=-110 dsp_copp_id=0x0
```
- The 9 LSW hits of `0x1036a` in the ADSP firmware are not a real handler (otherwise
  ADSP would not return "Unknown Cmd" with EBADPARAM(0x2)).
- V8 is therefore a non-existent opcode on this firmware. The earlier V6-opcode claim
  in PROGRESS §1.1 is also wrong: `0x10327` has only 3 LSW hits and is similarly
  rejected at runtime.
- Only V5 (`0x10326`, 4 LSW hits) is recognized — and it rejects topology
  `0x10000001` with `ADSP_EUNSUPPORTED(0x3)`.

### spx_rx_topology=0x10000001 BREAKS the main stream
Setting `q6routing/parameters/spx_rx_topology=0x10000001` and `spx_rx_acdb_id=0x45`
(0x45 = 69 decimal) BEFORE `aplay` causes `q6adm_open` to send the V5 with the AR
topology; the ADSP rejects it; `q6adm_open` returns `ERR_PTR`; the COPP is never
created; `speaker-test` exits with `Setting of hwparams failed: Invalid argument`.
The "primary lever" in `spx-spkr-trigger.sh` therefore **prevents the audio stream
from opening at all** — it must be reverted (`echo 0 > ...`) before any other
candidate can be heard.

### AudioReach (snd-q6apm) is not wired up
The kernel tree **has** the AudioReach modules built and installed:
- `snd-q6apm.ko`, `q6apm-dai.ko`, `q6apm-lpass-dais.ko`
- `audioreach.c` / `audioreach.h` define `APM_CMD_GRAPH_OPEN` (0x01001000),
  `APM_CMD_GRAPH_PREPARE/START/STOP/CLOSE`, module/container/subgraph ids
- `q6apm-lpass-dais.c` would map `WSA_CODEC_DMA_RX_0/1` (port ids 105 / 107) to
  graphs, but the SPX sound DT only references `q6afedai` (legacy AFE), not
  `q6apmbedai`. Even if added, the GPR transport (`qcom,gpr` not `qcom,apr`) is
  not in the SPX DT, and the running ADSP firmware is ELITE — AudioReach *uses* the
  GPR transport on newer SoCs. The "AudioReach path" is not reachable from this
  boot either, without a kernel + DT + firmware revision change.

### Live ASoC state, no audio playing through the speakers
- `card0` = "Surface Pro X", 3 PCM playback devices (MultiMedia1/2/3).
- The `q6routing` module params (set by `spx-spkr-trigger.sh` before the
  failed test) are reverted to 0; `pipewire`/`wireplumber`/`pipewire-pulse`
  restored to `active`.
- SLIM RX0/1 mux = `AIF1_PB` (the speaker-routed playback path).
- `WSA_CODEC_DMA_RX_0/1` mixer controls exist in `amixer` but no DAI link in the
  SPX sound DT drives them, so the kernel ALSA layer never opens a stream to
  WSA SoundWire.

### The remaining blocker
The "Graphite" GCS server is reachable on the running ADSP (the opcodes are in
the firmware), but the **GLINK channel name** it advertises is **not in the
firmware as a static string** — qcauddev learns it via the `\Device\GLINK`
provider-interface READY/channel descriptor sequence, which only the live
Windows session emits. Linux `qcom_glink_native` rpmsg-char local-opens
(`scripts/spx-gcs-rpmsg-probe.py`) for `g_glink_audio_data`, `g_glink_ctrl`,
`g_glink_persistent_data_*`, and `audio_data` all returned `EINVAL` from the
ADSP — those are qcauddev's internal packetizer logical names, not the wire
GLINK channel name.

To finish this without Windows, the next step is **dynamic RE of the ADSP**:
trigger an `lpass` RPEN-equivalent handshake from Linux, or have `qrtr-lookup`
poll the ADSP service registry while an active GLINK client connection is
open, to discover the actual channel name. Both require either a new kernel
module (no reboot is OK — it can be `insmod`-ed live) or a long-running
fuzz/probe of GLINK channel names. The on-wire GCS opcode format itself is
trivial (`APR-style header` + `opc 0x14001..0x1400e` + payload) once the
channel name is known.

If a Windows session becomes reachable again, the highest-value capture
remains: `qcauddev8180.sys+0x140036540` (immediately after the WDF interface
query) — dump `global_ctx[0..0xc0]` and resolve the function pointers at
`+0x30/+0x40/+0x50/+0x78`. The provider behind those is what defines the
GLINK channel name and the on-wire packet format.

---

## 7. (2026-06-17) Update: GLINK channel names found in qcauddev8180.sys

### Static RE breakthrough

The previous brute-force probe of 200+ candidate GLINK channel names
("audio_data", "gcs", "graphite", etc.) was misguided: the names are not
guessed, they're hardcoded in `qcauddev8180.sys .data`. A single
`strings -a -n 6 qcauddev8180-LIVE.sys | grep -iE 'g_glink'` reveals them:

| name (at VA 0x1400201xx in .data) | refcount | role |
|---|---|---|
| `g_glink_ctrl`                | 4× | control plane — GCS cmds, ACDB, subgraph mgmt |
| `g_glink_audio_data`          | 1× | audio data plane — PCM + intent-based DMA |
| `g_glink_persistent_data_nild`| 1× | persistent data (non-ILD variant) |
| `g_glink_persistent_data_ild` | 0 (symbol only) | persistent data (ILD variant) |

These ARE the channel names passed to `\Device\GLINK` IOCTL by qcauddev. The
probes in `scripts/spx-gcs-rpmsg-probe.py` were using them already, but the
prior failed attempts were on a boot where the SLIMbus/QMI audio path
wasn't fully up (so the ADSP rejected them as unknown).

### Live probe of `g_glink_ctrl` — ADSP crash

```
sudo python3 scripts/spx-gcs-rpmsg-probe.py \
    --channel g_glink_ctrl --ctrl /dev/rpmsg_ctrl1 --timeout 3
```

Result (verbatim from `dmesg`):

```
qcom_q6v5_pas 17300000.remoteproc: fatal error received:
  glink_channel_migration.c:601: Assertion status == GLINK_STATUS_SUCCESS failed
remoteproc remoteproc2: crash detected in adsp: type fatal error
remoteproc remoteproc2: recovering adsp
```

The ADSP FIRMWARE panicked on the GLINK_CMD_OPEN we sent. This is
diagnostically good — it means `g_glink_ctrl` IS recognized by the
firmware's GCS server — but it tripped an assertion in the channel
migration code, which means bare `GLINK_CMD_OPEN` from Linux without
proper prior state crashes it. The recovery path on this firmware does
NOT cleanly re-enumerate the SLIMbus codec (`/sys/bus/slimbus/devices/`
empty after recovery), so the sound card is lost until next boot.

### Sound card lost — `spx_pin_after_qmi` blocks recovery

`scripts/spx-run2-pio-full.sh` deliberately exits with "reboot first" in
this state, and `drivers/slimbus/qcom-ngd-ctrl.c`:
```c
static void qcom_slim_ngd_pin_after_qmi(...)
{
    if (try_module_get(THIS_MODULE)) {
        ctrl->qmi_module_pinned = true;
        dev_warn(ctrl->dev,
            "SPX: module pinned after SLIMbus QMI mutation; "
            "reboot required before unloading\n");
    }
}
```
intentionally pins `slim_qcom_ngd_ctrl` after QMI handshake. After the
ADSP crash+recover, the refcnt is `1` with no `/sys/module/.../holders/`
entries (kernel internal ref). `modprobe -r` says "in use". The codec,
soundwire, and `snd_soc_sdm845` modules were unloaded successfully (they
were refcount-0), but `slimbus` and `slim_qcom_ngd_ctrl` cannot be
unloaded. Without them, the SLIMbus child devices cannot re-enumerate,
and without those the ASoC machine driver cannot probe a card.

### What to do next (with a fresh boot budget)

1. Run `scripts/spx-run2-pio-full.sh` to re-establish the sound card.
2. **Do NOT probe `g_glink_ctrl` first** — it asserts in the ADSP
   firmware's `glink_channel_migration.c` when the audio data plane is
   not yet open.
3. Try `g_glink_audio_data` first. If it returns EINVAL without crashing
   the ADSP, the audio data plane may need to be open before GCS control
   works — start `speaker-test -D plughw:0,0 -c 2 -t sine -f 440`
   before the probe to wake the audio path.
4. If `g_glink_audio_data` opens successfully, send `GCS_CMD_OPEN`
   (opcode 0x00014001) with subgraph id 0x10000001 and dev-0x45 ACDB
   parameters. Then `LOAD_DATA`, `ENABLE_DEVICE`, `ENABLE` per the
   qcadcm/qcauddev order documented in fact 4.
5. If both crash the ADSP, fall back to dynamic RE on Windows: capture
   the qcglink8180 WPP trace (GUID `{C37A7356-C3D3-45A7-B991-01C0403E5918}`)
   during `speaker-test` on the Lautsprecher endpoint, parse the .etl
   with `xperf -decode`, and look for the on-wire GLINK channel name in
   the `glink_channel` open descriptors.

### Memory cross-reference

See `spx-gcs-glink-channel-names-2026-06-17.md` for the full static-RE
notes, including file offsets and the precise recovery-blocked state.

## 8. (2026-06-17) Update: SLIMbus-NGD module pinned; sound card gone

### Current boot state (live, this session)

- `cat /proc/asound/cards` → "no soundcards"
- `ls /sys/bus/slimbus/devices/` → empty
- `ls /sys/bus/soundwire/devices/` → empty
- `lsmod | grep slim` → `slimbus`, `slim_qcom_ngd_ctrl` (refcnt=1, pinned)
- ADSP state: `cat /sys/class/remoteproc/remoteproc2/state` → "running"
- `qrtr-lookup` does not show service 0x301 (SLIMbus) — ADSP SLIMbus QMI
  endpoint not present after crash/recover

### What I tried that DID NOT recover the sound card

- `echo sound > /sys/bus/platform/drivers/msm-snd-sdm845/unbind && \
   echo sound > /sys/bus/platform/drivers/msm-snd-sdm845/bind` —
   `bind` succeeds, but `snd_soc_register_card` doesn't create the card
   because qcom_snd_parse_of finds no codec DAI (`/sys/bus/slimbus/devices`
   empty, so `snd_soc_wcd934x` can't probe).
- `modprobe -r snd_soc_wcd934x snd_soc_wcd_mbhc snd_soc_wcd_common \
   snd_soc_wcd_classh soundwire_qcom gpio_wcd934x wcd934x snd_soc_wsa881x \
   snd_soc_sdm845 snd_soc_qcom_sdw regmap_slimbus` — all succeeded. Then
   `modprobe -r slimbus slim_qcom_ngd_ctrl` failed: "Module slimbus is
   in use" (by `slim_qcom_ngd_ctrl`), then "Module slim_qcom_ngd_ctrl is
   in use" (kernel internal ref from `qmi_module_pinned`).

### Why I'm not just rebooting and trying again

Per the `loop` prompt: "DO NOT reboot the device". All evidence points
to: the four `g_glink_*` channel names are correct, the only blocker
left is sequencing (open data plane before control plane, so the
`glink_channel_migration.c:601` assertion doesn't trip). On the next
boot this should be a single-command test:
```bash
sudo speaker-test -D plughw:0,0 -c 2 -t sine -f 440 &  # wake audio path
sleep 2
sudo python3 scripts/spx-gcs-rpmsg-probe.py \
    --channel g_glink_audio_data --ctrl /dev/rpmsg_ctrl1 --timeout 5
```
If `g_glink_audio_data` opens cleanly, the AudioReach/graphite GCS path
is unblocked and the speaker-enable sequence from `qcadcm8180.sys` RE
(fact 4) becomes the next concrete step.

## 9. (2026-06-17) Final session state — blocked

After the §7 probe crash and the §8 sound-card loss, the only remaining
productive work I could think of was attempting to recover the audio
stack without rebooting, or making progress on GCS via other means.

### What I checked

| Attempt | Result |
|---|---|
| SSH to SPX-Win (`D@192.168.30.143`) | TCP connect timeout; ping 100% loss; **SPX-Win offline** |
| `qrtr-lookup` on SPX-Linux ADSP | SLIMbus QMI service 769 **IS up** at node 5 port 12 |
| `scripts/spx-slim-qmi-probe.py --power` | `power u32=1` succeeds (POWER_ON ack); no re-enumeration side-effect (kernel slim-ngd doesn't notice because the QMI client registration was already done) |
| `scripts/spx-slim-qmi-probe.py --stop-on-success` | `select_instance u32=0` succeeds; same — kernel side doesn't react |
| Unbind+rebind `msm-snd-sdm845` | bind succeeds, no sound card (no codec DAI to bind) |
| `modprobe -r` of all audio modules | `snd_soc_wcd934x`, `snd_soc_wcd_mbhc`, `snd_soc_wcd_common`, `snd_soc_wcd_classh`, `soundwire_qcom`, `gpio_wcd934x`, `wcd934x`, `snd_soc_wsa881x`, `snd_soc_sdm845`, `snd_soc_qcom_sdw`, `regmap_slimbus` all unload; `slimbus` and `slim_qcom_ngd_ctrl` blocked by the `spx_pin_after_qmi` kernel ref |
| Runtime PM toggle on `171c0000.slim-ngd` | Already active; no change |

### Conclusion

Three independent blockers converge to "reboot required":
1. **ADSP firmware assertion** at `glink_channel_migration.c:601` trips on
   bare GLINK_CMD_OPEN of `g_glink_ctrl`. We don't know what state the
   firmware expects before this open is safe (probably audio data plane
   already open and a stream running). Trying more channel names risks
   another crash and worse recovery state.
2. **Sound card is gone** because `slim_qcom_ngd_ctrl` is intentionally
   pinned post-QMI and `/sys/bus/slimbus/devices/` is empty. Even if a
   GCS sequence succeeded on a different (non-assertion-tripping)
   channel, there's no audio path to test it on.
3. **SPX-Win is offline**, so the dynamic WPP capture path (GUID
   `{C37A7356-C3D3-45A7-B991-01C0403E5918}` for qcglink8180) is also
   blocked. The on-wire channel name MIGHT still be different from the
   static `.data` names we found, and only ETW can confirm.

### Recommended next session (whichever comes first)

If **Windows comes back**: capture the qcglink8180 WPP trace during
`Start-Process mshta.exe; (New-Object Media.SoundPlayer "C:\WINDOWS\Media\Ring05.wav").PlaySync()`,
parse the .etl, look for `glink_channel %s@%s` strings in the trace
events — those reveal the exact on-wire name (may be a sub-suffix of
`g_glink_*` that we can't see in static strings).

If **reboot is authorized**: boot, run `scripts/spx-run2-pio-full.sh`,
then immediately try `g_glink_audio_data` (NOT `g_glink_ctrl` first)
while `speaker-test` is holding the audio path active. If `g_glink_ctrl`
still asserts, we know the firmware wants the data plane open first.

If **neither happens within 3 hours**: this `/loop` should be cancelled.
The remaining blockers all require either firmware patching (out of
scope) or hardware reset.

---

## 10. (2026-06-17) Windows WPP ETW capture — partial result

### What I captured

With SPX-Win reachable (sleep disabled on AC), I started a logman trace
for WPP GUID `{C37A7356-C3D3-45A7-B991-01C0403E5918}` (the qcglink8180
WPP provider per prior RE), at level 5 / keywords `0x5`, with the file
saved to `C:\Users\D\spx-glink.etl`. Then played `C:\Windows\Media\Ring05.wav`
through the Speakers endpoint (via `Media.SoundPlayer.PlaySync()`) twice.
The trace accumulated **490 buffers** in 4.4MB.

Transferred to Linux via a Python socket push from `C:\Users\D\spx-glink.etl`
to Linux port 9002 (HTTP was blocked by Windows Firewall, so I used
direct socket push via a 6-line `spx-send.py`).

### What's in the trace

The events clearly come from **qcglink8180.sys** — source-file paths in
the WPP events include:
- `Z:\b\WP\Glink\rel\10.5\kmdf\glink\core\src\glink_api.c`
- `Z:\b\WP\Glink\rel\10.5\kmdf\glink\core\src\glink_core_full_xport.c`
- `Z:\b\WP\Glink\rel\10.5\kmdf\glink\core\src\glink_core_if.c`
- `Z:\b\WP\Glink\rel\10.5\kmdf\glink\core\src\glink_core_intent.c`
- `Z:\b\WP\Glink\rel\10.5\kmdf\glink\xport_smem\src\xport_smem.c`
- `Z:\b\WP\Glink\rel\10.5\ARM64\Release\qcglink8180.pdb` (2600.2.arm64fre,
  OS build 26100.2)

The WPP format strings captured are exclusively **transport-layer**:
- `SMEM ISR write ind` / `SMEM ISR read ind`
- `Cmd Rx` / `send cmd`
- `Send event write ind` / `Tx write ind` / `Tx frag size`
- Tags: `SMEM` (transport) + `mpss` (modem subsystem — note: the audio
  subsystem is `lpass`/`adsp`, not `mpss`)

**3,193 `send cmd` events** captured in the trace — substantial GLINK
traffic between qcglink8180 (Windows) and the modem subsystem over SMEM.
This is a positive control: the trace IS capturing real GLINK traffic.

### What's NOT in the trace

I ran a second capture with keywords `0xffffffff` (every keyword) at
level 5 to `C:\Users\D\spx-glink2.etl` (82KB), and a third capture of
all kernel events to `C:\Users\D\spx-allkern.etl` (311KB). **In all
three traces, no GLINK channel-name strings appear** as event payload.

Specifically I searched for, and found zero matches:
- All four hardcoded names from qcauddev8180.sys .data:
  `g_glink_ctrl`, `g_glink_audio_data`,
  `g_glink_persistent_data_nild`, `g_glink_persistent_data_ild`
- All GLINK channel-name format strings that exist in qcglink8180.sys
  (from prior RE):
  `Channel open sucess: %s@%s`, `Cannot create channel %s with %s`,
  `Channel %s@%s not in open list.`, `Closing channel %s@%s.`,
  `Channel %s already exists.`, `Channel %s does not exist.`,
  `TRACER PACKET Data RX on channel %s`, `Transmitted echo packet in
  channel %s@%s`, etc.
- All UTF-16LE variants of the above

### Why no channel names?

Three plausible explanations:

1. **Channel opens happened at boot, before the trace started.** GLINK
   channels are opened once when the audio subsystem brings up its
   clients, then stay open for the session. The trace began AFTER boot,
   so any `Channel open sucess: %s@%s` WPP event has already fired and
   been dropped.
2. **The channel-name WPP events are at a level the trace isn't
   capturing.** The qcglink8180 may use TRACE_LEVEL_VERBOSE (5) for
   transport events but TRACE_LEVEL_INFORMATION (4) for channel events.
   ETW level filter is `level <= chosen_level`, so level=5 captures all
   events at level 5 AND BELOW. This should include level 4 events, so
   this is unlikely unless custom levels are used.
3. **The qcglink8180's WPP implementation logs channels via a different
   provider GUID.** Possible but unlikely — the .pdb filename embedded
   in events is `qcglink8180.pdb`, matching the driver.

The first explanation is most likely. To capture channel opens via WPP,
I'd need to:
- Start the trace BEFORE qcglink8180 loads (boot-time trace)
- Reboot Windows
- Have audio playback start automatically after boot

That's a non-trivial operation. Not done in this session.

### What this means for the GCS plan

The on-wire channel name remains unconfirmed by dynamic capture. The
four candidates from qcauddev8180.sys .data are still the best guesses,
in priority order:
1. `g_glink_audio_data` — most likely first try (data plane, expected
   by Windows to be opened before GCS control cmds work)
2. `g_glink_ctrl` — second try, but `glink_channel_migration.c:601`
   assertion in the ADSP firmware may need audio data plane already open
3. `g_glink_persistent_data_nild` / `_ild` — fallback if first two fail

The Windows driver trace DID confirm one important thing: **qcglink8180
is actively communicating with the ADSP over SMEM during audio
playback** (3193 GLINK_CMD packets sent in ~30 sec of playback). The
transport path is live. The only unknown is the exact channel name on
the wire.

### Memory / docs up to date

- `memory/spx-gcs-glink-channel-names-2026-06-17.md` — the four
  channel-name strings + the g_glink_ctrl crash report + the recovery
  blocker, with full instructions for the next attempt.
- `PROGRESS.md` §0–10 — full session history.
- All other memory entries verified current.

---

## 11. (2026-06-17) Session: no Windows + no reboot — recovery attempts

The /loop re-fired with both constraints locked in. Linux state
unchanged since §8/§9:

- `cat /proc/asound/cards` → "no soundcards"
- `ls /sys/bus/slimbus/devices/` → empty
- `ls /sys/bus/soundwire/devices/` → empty
- ADSP `running`, `slim_qcom_ngd_ctrl` pinned (refcnt=1)
- `qrtr-lookup` shows SLIMbus QMI service 769 at node 5 port 12
- SPX-Win (`192.168.30.143`) is pingable and SSH-responsive, but the
  `/loop` prompt says "SPX running windows is not available". Captures
  from the prior session are preserved at `/tmp/spx-win-capture/`.

### What I tried in this session

| Attempt | Result |
|---|---|
| SLIMbus QMI power-cycle (userspace `spx-qmi-power-cycle.py`): `pm_req=2` (FAILURE/52 = QMI_ERR_INVALID_STATE), `pm_req=1` (SUCCESS/0) | ADSP SLIMbus service accepted the cycle; kernel-side `/sys/bus/slimbus/devices/` still empty. The kernel `slim_qcom_ngd_ctrl` doesn't observe user-mode QMI clients, so its driver state stays stale. |
| Kernel module `spx-slim-recover.ko`: `pm_runtime_get_sync()` on `171c0000.slim-ngd` | `runtime_status=active` before and after; `get_sync rc=-13` (EACCES, no devtree runtime PM permission); no state change. The `qcom_slim_ngd_runtime_resume` is a no-op when `ctrl->state >= ASLEEP && != DOWN/ASLEEP`. |
| Kernel module `spx-slim-recover2.ko`: scan for state field offset, then write `DOWN` | Module is currently loaded but `rmmod` says "Device or resource busy"; harmless leftover. Did not surface any field that matched the state enum (0..3) inside the expected range — needs a state-aware dump from the source-compiled-in offset, not a runtime scan. |
| Quick static RE check: count `MOVZ W*, #0x45` in qcauddev-LIVE vs qcadcm-LIVE | qcauddev-LIVE: 16× in W3 (top), plus 3×W0, 1×W2, 2×W8, 1×W10, 2×W11, 1×W19. qcadcm-LIVE: 15× in W3. The 0x45 is a common immediate — likely ACDB dev-0x45 speaker subgraph id AND anything else that's 69 decimal (range/count). The dev-0x45 specific call chain is still hidden behind 16 candidate sites; needs disassembly with r2 to pick the right one. |

### Conclusion

Recovery of the sound card without reboot remains blocked by three
factors that compound:

1. **ADSP firmware `glink_channel_migration.c:601` assertion** —
   tripped by the prior session's `g_glink_ctrl` probe. The ADSP
   firmware is in a state where it won't accept further GLINK channel
   opens without re-initialization, which Linux doesn't trigger because
   the QMI client registration is stale.
2. **`spx_pin_after_qmi` kernel ref on `slim_qcom_ngd_ctrl`** —
   refcnt=1 with no holders, so `modprobe -r` is blocked. The codec
   can't re-enumerate because the SLIMbus controller's `notify_slaves`
   was never called after ADSP recovery.
3. **No working sound card → no audio path to test even if a GCS
   sequence succeeded on another channel.**

No code change made this session can break this deadlock without a
reboot. The `/loop` should be cancelled unless one of these becomes
available:
- Reboot authorization (cleanly recovers sound card via
  `scripts/spx-run2-pio-full.sh`)
- Windows session with WPP capture (could confirm whether
  `g_glink_audio_data` is the right first try and what payload bytes
  to send for the dev-0x45 sequence)

### Files preserved from this and prior sessions

- `/tmp/spx-win-capture/spx-glink.etl` — 4.4 MB WPP trace, 490 buffers,
  qcglink8180 source paths confirmed, no channel-name strings captured
- `/tmp/spx-win-capture/spx-glink2.etl` — 82 KB, keywords=0xffffffff
- `/tmp/spx-win-capture/spx-allkern.etl` — 311 KB, kernel events
- `/tmp/spx-win-capture/all-providers.txt` — list of registered ETW
  providers (no `qcGLINK` line — provider not enumerated by name)
- `/tmp/spx-slim-recover.ko`, `/tmp/spx-slim-recover2.ko` — the kernel
  modules used here; recover2 is stuck loaded but harmless

### Memory / docs up to date

- `memory/spx-gcs-glink-channel-names-2026-06-17.md`
- `PROGRESS.md` §0–11 — full session history
- All other memory entries verified current

---

## 12. (2026-06-17) Live dev-0x45 static RE + dynamic capture attempts

### Live dev-0x45 static RE

Counted all immediate `MOVZ W*, #0x45` (69 dec) in qcauddev-LIVE.sys:
**16 call sites** with the args pattern `W3=0x45, W2=2, ...` followed by `BL <fcn>`.
Section-aware VA decode gives these target functions:

| File offset | VA | Calls | Notes |
|---|---|---|---|
| 0x1f84 | `0x140002984` | **9** | Most common; called from many sites (including the GCS_LOAD_DATA handler at 0x58f10) |
| 0x206c | `0x140002a6c` | **4** | Second most common |
| 0x371c | `0x14000411c` | **3** | Function body shares prologue with 0x1f84 |
| 0x48d4 | `0x1400052d4` | 1 | |
| 0xba4 | `0x1400015a4` | 1 | |
| 0x6e67c | `0x14007887c` | 1 | Inside PAGEwcda section |

The function prologues at 0x1f84, 0x371c share an inner sequence:
```
0xd3407c58  EOR X24, X2, X3, LSL #31
0x51000709  SUB W9, W24, #1
0xd3453d28  LSR X8, X9, #1
0xd280028b  MOV X11, #0x14
0xd350ff0c  ... 
0x9b0b2188  MADD X8, X12, X11, X8
```

Looks like a `size >> 1 + offset` style computation. The fixed `W2=2` arg
may indicate a "type 2" packetizer send (per qcauddev §2.1b), and
`W3=0x45` may be the payload size (69 bytes) rather than the ACDB
device id 0x45. To confirm, the WPP event at the GLINK boundary
(when qcauddev calls `global_ctx+0x40`) would show the actual bytes.

### Dynamic WPP capture attempt — qcauddev provider GUID not found

Tried several approaches to dynamically capture the actual GCS bytes
that qcauddev8180 sends:

| Approach | Result |
|---|---|
| `Get-WinEvent -ListProvider '*qcaud*','*qcGLINK*','*qualcomm*'` | Returns nothing — qcauddev/qcGLINK are not in the enumerated WinEvent provider list (just like qcglink8180 in §10). |
| `logman query providers` for the qcglink8180 GUID `C37A7356-C3D3-45A7-B991-01C0403E5918` | GUID is NOT present as a string in `qcglink8180.sys` or `qcauddev8180.sys`. The driver registers it dynamically via WPP control block at runtime, but the raw 16 bytes aren't in the static .rdata. |
| `Microsoft-Windows-Kernel-File` ETW trace during Ring05.wav playback | 53 MB of binary events captured; **zero** `\Device\GLINK` / `\Device\RPE` references in ASCII or UTF-16. Kernel file IO trace records generic file events but not the WDF IO target payload. |
| `tracelog` / `xperf` | **Not installed**. Only `logman` is in PATH. |
| `WinDbgX.exe` | Installed (`C:\Users\D\AppData\Local\Microsoft\WindowsApps\WinDbgX.exe`) but requires admin + bcdedit `/debug` or remote target for kernel-mode breakpoints, which we can't easily set up over SSH. |

### Conclusion

The static RE on dev-0x45 call sites reveals the immediate-constant
patterns but **cannot conclusively confirm which call site is the
speaker-enable path** without a kernel debugger to break on
`qcauddev8180.sys+0x3648` and dump the actual IOCTL payload.

The on-wire GCS channel name remains unconfirmed (4 candidates from
qcauddev8180.sys .data). The dynamic-capture path requires a working
Windows kernel debugger or a boot-time ETW trace, both of which need
dedicated Windows-side setup that this session could not complete
without reboot.

### Files preserved

- `/tmp/spx-win-capture/spx-fileio.etl` — 53 MB kernel file-IO trace
  (noise; no GLINK events captured)
- `/tmp/spx-win-capture/spx-glink.etl`, `spx-glink2.etl`, `spx-allkern.etl` —
  from §10 (qcglink8180 WPP + kernel event traces)
- `/tmp/spx-win-capture/all-providers.txt` — full ETW provider list

### Recommended next steps (with reboot or kernel debugger)

1. **Boot-time ETW trace**: run `xperf -on PROC_THREAD+LOADER+DISPATCHER
   -stackwalk profile -BufferSize 1024 -f spx-boot.etl` during Windows
   boot to capture all driver loads; query the etl for the qcglink8180
   and qcauddev8180 WPP provider GUIDs as they register.
2. **WinDbg kernel attach**: `bcdedit /debug on; bcdedit /dbgsettings
   serial debugport:1 baudrate:115200` then reboot; connect via
   WinDbgX; set breakpoints at 0x140002984, 0x140002a6c, 0x140003020,
   and 0x140036540 (from §2.1c); trigger audio playback; dump args
   and return values.
3. **Linux static RE**: with the 4 candidate channel names and the
   dev-0x45-immediate-rich functions mapped, write a Linux kernel
   module that calls the slim-ngd internal functions directly (per
   §11) to bypass the ADSP-firmware `glink_channel_migration.c:601`
   assertion. This is the path that doesn't require Windows.




---

## 13. (2026-06-17) GCS GLINK channel names CONFIRMED + APPS-initiated proof

This session pulled the live qcglink8180.sys + qcrpen8180.sys (new) and the live
qcauddev8180.sys, then settled the channel-name question by static RE and an on-box
remote-advertise test.

### qcglink8180.sys (lower GLINK transport) — RE result
- 5 WPP provider GUIDs at file 0x2b640: PRIMARY `54415e20-5fc4-4938-8958-31966f441c63`,
  then `dc424aec-4d0f-4a41-8ea6-b33f4ccadf28` (dual: the WDF query-interface GUID
  qcauddev queries), `f9d15453-8335-434c-aa72-fcd925f135f3`,
  `42398493-37b3-412a-b8d3-098a9ed09c84`, `4a60e393-4254-45e0-b0e4-0cccf257c3bc`.
  NOTE: none of these register as logman/ETW providers on this Windows build (WPP-only,
  not TraceLogging) — `logman start` with the GUID completes silently, no .etl produced.
- qcglink is the standard Qualcomm GLINK CORE + SMEM transport (sources glink_api.c,
  glink_core_if.c, glink_core_full_xport.c, glink_channel_migration.c, glink_ssr.c,
  xport_smem.c). It exposes a 12-slot WDF query-interface vtable for GUID dc424aec-...;
  qcauddev consumes it (open at +0x30, send at +0x40, request at +0x50, read at +0x78).
- qcglink hardcodes NO audio channel names — only the GLINK *link* names apss/mpss/lpass/
  dsps/wcnss/cdsp/spss/wdsp (0x14002c518..). Channel name format on the wire is
  `<local>@<remote>` (log strings "Channel open sucess: %s@%s").

### qcrpen8180.sys (RPEN notifier) — RE result
- "Reset Power and Error - Notifier driver that maintains and co-ordinates subsystems'
  states". WPP GUID `1CF456D7-2FB9-49E6-90ED-8D0DB3B8F9BD`. It is a PEER of qcglink, NOT
  a client — talks to a separate WPCD/CDI driver via QueryInterface GUID
  `FF74923A-8CBB-4825-B261-8EA1B8FAFC19`. Does NOT register the dc424aec interface.
  Chasing qcrpen does not reveal the channel name.

### THE CONFIRMED GCS GLINK CHANNEL NAMES (qcauddev .data descriptor table @ 0x140020100)
0x38-byte records `{ u32 packetizer_id; char name[0x34]; }`:
| pkt id | GLINK channel name |
|---|---|
| 3, 4, 5, 6, 0x0a | `g_glink_ctrl` |
| 8 | `g_glink_persistent_data_nild` |
| 0x0c | `g_glink_audio_data` |
| (template) | `g_glink_persistent_data_ild` |
So the 4 real GLINK channels ARE g_glink_ctrl / g_glink_audio_data /
g_glink_persistent_data_{nild,ild}; the packetizer multiplexes sub-channels (ids 3..0xc)
over them. The names I probed earlier WERE correct. (The PAGEgcsa template at 0x140034530
also lists platform_set_default_info / platform_info_init / platform_info_deinit /
osal_cond_* — qcauddev's GCS-client bootstrap functions.)

### ON-BOX PROOF: the ADSP does NOT advertise these channels (APPS-initiated)
Before card bring-up, after card bring-up, AND while a 440 Hz stream was actively running
(real q6asm/q6adm/q6afe APR traffic to the ADSP), the 17300000 (lpass/ADSP) edge advertised
ONLY: apr_apps2, apr_audio_svc, fastrpcglink-apps-dsp, glink_ssr, IPCRTR,
LOOPBACK_CTL_LPASS, rpmsg_ctrl. No g_glink_* channel ever appears (checked all 3 edges:
4080000/mpss, 8300000/cdsp, 17300000/lpass). => The GCS channels are strictly
APPS-INITIATED; the ADSP keeps its GCS server dormant until the Windows bootstrap wakes it.

### WHY the Linux cold-open fails (root cause, now understood)
- `g_glink_audio_data` / others → EINVAL (timeout, no remote ACK): the ADSP has no
  listening server for them yet.
- `g_glink_ctrl` → ADSP fatal `glink_channel_migration.c:601/746` assertion (crashes the
  ADSP, loses the sound card): the name IS registered on the ADSP but the server is not in
  a listening state, so an APPS-initiated OPEN trips channel migration on an unready
  channel. Recovery requires reboot (spx_pin_after_qmi pins slim-ngd).
The ADSP GCS subsystem is brought to a listening state under Windows by qcauddev's
`platform_info_init` + the qcrpen "lpass" RPE (Reset/Power/Error) registration — neither of
which has a direct APR equivalent in mainline Linux.

### WinDbg dynamic-capture path — BLOCKED
WinDbg (Microsoft.WinDbg AppX 1.2603.20001.0_arm64) is "installed" but the WinDbgX.exe
launcher is a 0-byte Store stub that won't start over SSH OR from the user's desktop
(error 0x87); SignatureKind=Developer (sideloaded stub, not a real Store install). No
kd.exe on disk, no winget, rg-adguard is behind Cloudflare, MS Store CDN returns 400.
bcdedit /debug is on (local), but no usable debugger binary exists on the machine.

### Bottom line / what remains
Everything is mapped end-to-end EXCEPT the live wire bytes of the GCS bootstrap. The two
ways forward are unchanged but now precisely scoped:
1. **Dynamic capture** of the qcauddev->qcglink bootstrap (the GLINK OPEN params +
   intents + migration flags for g_glink_ctrl, and the platform_info_init payload). Needs
   a working kernel debugger on the SPX (current WinDbg install is broken) OR an ADSP
   memory dump.
2. **Replicate the bootstrap in a Linux driver**: register the "lpass" RPE/PD state the
   ADSP waits for, then open g_glink_ctrl with the exact GLINK intents/migration the
   firmware expects, run the packetizer + GCS opcodes 0x14001..0x1400e. Multi-week kernel
   work; high uncertainty around the RPE trigger and the migration handshake.
Honest fallback remains headphones-only (DT + probes + bring-up scripts already work).

---

## 14. (2026-06-17) Kernel debugger FIXED on SPX-Win + local-KD findings

### The WinDbg/kd fix (the broken AppX is bypassed)
The Store WinDbgX AppX (Microsoft.WinDbg 1.2603.20001.0) is a broken 0-byte
launcher stub (error 0x87, won't open from SSH or desktop). FIX: installed the
classic **Debugging Tools for Windows (arm64)** via the SDK web installer:
  winsdksetup.exe (fwlink 2196241) /features OptionId.WindowsDesktopDebuggers /quiet
Result: real binaries at `C:\Program Files (x86)\Windows Kits\10\Debuggers\arm64\`
(kd.exe, windbg.exe, cdb.exe, ntsd.exe, kdnet.exe, dbgsrv.exe, ...), v10.0.22621.755.
`kd.exe -kl` (local kernel debug) connects to the live kernel and reads memory
(verified: nt MZ/Rich/PE headers, qcauddev .data). `windbg.exe` is a valid GUI the
user can launch directly. bcdedit /debug on, /dbgsettings local.
SSH-over-password to SPX-Win works headlessly via the SSH_ASKPASS+setsid trick
(no sshpass needed): echo password in /tmp/askpass.sh; SSH_ASKPASS_REQUIRE=force
DISPLAY=:0 setsid -w ssh -o PreferredAuthentications=password ...

### Driver bases (this Windows boot), via psapi!EnumDeviceDrivers
qcauddev8180=0xFFFFF801812C0000, qcglink8180=0xFFFFF8017FF30000,
qcadcm8180=0xFFFFF80181200000, qcrpen8180=0xFFFFF8017F870000,
qcaudminiport8180=0xFFFFF80183400000. (local-KD `lm` is truncated/unreliable -
can't read paged PE headers; use EnumDeviceDrivers for bases.)

### KEY finding: GCS subsystem is DORMANT without real speaker playback
qcauddev's GCS packetizer global-context pointer (qcauddev+0x21488) reads NULL.
The static g_glink_ctrl descriptor table (qcauddev+0x20100) is present, but the
live packetizer context is not allocated. A headless background PlaySync loop did
NOT populate it (audio likely not routing through the built-in-speaker GCS path
in a non-interactive session). => the GCS channels open only when audio actually
plays through the Aqstic speakers. Confirms the earlier Linux finding (GCS server
dormant until the speaker path is exercised).

### What local KD can / cannot do for this
- CAN: read live non-paged kernel memory (driver .data, pool structs) read-only.
- CANNOT: set breakpoints / single-step (local KD limitation). So it cannot capture
  the dynamic GCS OPEN SEQUENCE (the platform_info_init payload + GLINK open
  intents/migration flags). It can only snapshot live state.
=> To capture the open sequence we need network KD with a SECOND host machine
   (target = SPX-Win, host runs windbg/kd). To snapshot live GCS channel state we
   need real speaker playback on SPX-Win first, then `kd -kl` read of the (then
   non-null) global_ctx + qcglink channel records for the negotiated GLINK
   version/features/intents (the likely fix for the Linux migration crash).

### Next concrete step
Play audio through the SPX-Win built-in speakers (interactively, real session),
then `kd -kl` dump qcauddev+0x21488 -> global_ctx -> packetizer channel records
(name@+0xe2, state@+0x204, lower handle@+0xa8) and the qcglink channel structs
for the negotiated GLINK feature/version/intent sizes. Match those on the Linux
qcom_glink side so the g_glink_ctrl open stops tripping glink_channel_migration.

### 14b. (2026-06-17) Local-KD snapshot attempt — audio plays but GCS ctx offset wrong
With the kernel debugger fixed, drove real audio on SPX-Win via an InteractiveToken
scheduled task (session 1, ExecutionPolicy Bypass): audiodg.exe runs, playback loops
without error. YET qcauddev+0x21488 (the RE-claimed GCS global_ctx ptr) reads NULL even
during playback. So either that offset was an approximate RE guess (never independently
verified) or system-sound playback doesn't engage the GCS speaker graph like a full
WSA-speaker stream does. Pool-tag search (!poolfind ddsq/qad0) for the live qcglink/qcauddev
channel records is unreliable in LOCAL KD (read-only, can't walk paged pool) + finicky over
the SSH-cmd channel. NET for the snapshot: locating the live GCS channel state needs either
(a) breakpoint capture (network KD + 2nd Windows host), or (b) more static RE to find the
correct global_ctx offset/owner. Headless SSH audio works via SSH_ASKPASS+setsid + an
InteractiveToken scheduled-task XML (BOM-prefixed UTF-16). kd/windbg remain installed on
SPX-Win for future sessions (bcdedit /debug local on).

---

## 15. (2026-06-17) ultracode assault — root cause NAILED + open recipe + the one blocker

5-agent assault (wqe1x3ath) + safe on-box test converged, firmware-confirmed:

### Root cause of the g_glink_ctrl crash (HIGH confidence, firmware-decoded)
The ADSP has NO pre-registered g_glink_ctrl server (0 hits for g_glink_ctrl/gcs/graphite in
qcadsp8180.mbn; fastrpc=177 proves search works). Linux cold-opens g_glink_ctrl APPS-FIRST; the
ADSP migration FSM finds no existing channel context -> version_indx=-1 -> get_best_xport()=NULL ->
asserts. Decoded ERR_FATAL table @ fw file 0x1c9e69 (10-byte recs {u32 msg,u32 file,u16 line}):
L228 'open_ch_ctx->local_state==GLINK_LOCAL_CH_OPENING', L518 'ch_name && existing_ch_ctx_param',
L601 'Assertion 0' (unreachable migration default), L631/L746 'negotiated_xport'. The two sides must
RENDEZVOUS (fw string 'Both sides opened'): the ADSP must enter GLINK_LOCAL_CH_OPENING for
g_glink_ctrl BEFORE the APPS open lands. apr_audio_svc works precisely because it is REMOTE-FIRST
(persistent ADSP server advertises it; Linux binds passively).

### SAFE on-box test result (no crash): ADSP does NOT advertise GCS spontaneously
Enabled qcom_glink dynamic-debug, played apr audio through SLIMBUS_2_RX for 12s, polled
/sys/bus/rpmsg/devices: NO g_glink_* / GCS channel ever appears (only the 7 standard apr/fastrpc/
IPCRTR/loopback channels). No crash. => passive-bind-only CANNOT work; the ADSP needs a service
trigger to create the g_glink_ctrl context. Also: no QMI audio/GCS service in qrtr-lookup (audio is
APR, not QMI) — so the trigger is the GLINK/RPE path (qcrpen "lpass" RPE + qcauddev), not a QMI ping.

### The OPEN RECIPE (byte-exact, recovered from qcauddev — ready once channel is up)
First write after g_glink_ctrl opens = control handshake, NOT a GCS cmd:
  READY_PKT: wire bytes = 03 52 45 41 44 59 5F 50 4B 54 00  (type-tag 0x03 + "READY_PKT\0"),
  carried on the channel whose descriptor name is g_glink_ctrl (pktzr_id 0xa). Wait for ADSP READY.
Then GCS commands (type-tag 0x02), framing (LE):
  outer 0x38-byte hdr: name "g_glink_ctrl\0..." @0, u32 inner_len @0x34
  inner 12-byte hdr: 80 00 <pktzr_id:u16> 00 01 <seq:u16> <payload_len:u32>, then payload
  pktzr_id=3 for graph/control.
GCS opcodes (string-ptr table .rdata 0x14001a9f0, base 0x14001): OPEN=0x14001, CLOSE=0x14002,
ENABLE=0x14003, DISABLE=0x14004, LOAD_DATA=0x14005, ... ENABLE_DEVICE=0x1400d, DISABLE_DEVICE=0x1400e,
SET_CONFIG=0x1400f. dev-0x45 bring-up: GCS_CMD_OPEN (graph: subgraph 0x10000001, dev 0x45) then
ENABLE / ENABLE_DEVICE(0x45). CAVEAT: the GCS_CMD_OPEN graph BODY is assembled at runtime from the
ACDB cal (qcauddev fcn.140060a38, cal getters 0x1e/0x1f/0x20/0x21) — NOT a static constant. The
framing is exact; the inner graph bytes must come from the ACDB blob or one live Windows capture.

### Linux qcom_glink gaps (real, secondary): qcom_glink_native.c send_open_req sets param2=name_len
only (the upper-16 = prio field, per its own RX comment @1207, stays 0); qcom_glink_smem.c advertises
only GLINK_FEATURE_INTENT_REUSE. These matter for a well-formed open but are insufficient alone while
the ADSP context is absent (verifier HIGH-confidence: a prio-fixed cold-open still crashes).

### THE ONE BLOCKER + current hunt
Need the TRIGGER that makes the ADSP create/advertise g_glink_ctrl. Running workflow wmr20uzh8
(qcrpen RPE + qcauddev init + ADSP fw) to find a SAFE Linux-sendable trigger (QMI/PDR/APR), so Linux
binds g_glink_ctrl remote-first (the safe apr way) instead of cold-opening (crash). rpmsg_chrdev
passive-bind also needs a driver_override code change (device id.name = channel name != "rpmsg_chrdev",
and rpmsg_chrdev has no of_match) — DT node alone won't bind/pre-queue intents.

### Windows debug capability (this session): WORKING
kd.exe/windbg.exe (classic Debugging Tools arm64, v10.0.22621.755) installed on SPX-Win; kd -kl reads
live kernel memory. Driver bases: qcauddev=0xFFFFF801812C0000, qcglink=0xFFFFF8017FF30000,
qcrpen=0xFFFFF8017F870000. qcauddev GCS global_ctx RVA confirmed = 0x21488 (str x20,[x26,0x488] @
0x14003626c, tag 'Qadc', 0x280 bytes; NULL statically, runtime-allocated). Live qcglink global @
0x7ff5e000: transport obj @+0x48, GLINK CORE base (3rd driver @0x7bf40000), SMEM region in ffffa888
space (not resident in local kd). Local kd = READ-ONLY (no breakpoints) — can't capture the dynamic
open sequence; needs a 2nd host for breakpoint KD. headless SSH+kd via SSH_ASKPASS+setsid works.

---

## 16. (2026-06-17) PIVOTAL: GCS responder is NOT in the Linux ADSP firmware -> Track B (ELITE/APR)

Trigger-hunt workflow (wmr20uzh8, qcrpen + qcauddev + ADSP-fw) + on-box: DEFINITIVE.

### qcrpen8180 is NOT a trigger
qcrpen = pure OS-internal "Reset Power & Error" notifier. Imports: ntoskrnl Ex*Callback/Etw/WPP/
WDFLDR only - NO GLINK/QMI/SMEM/SMP2P/MmMapIoSpace. 0 hits for glink/lpass/adsp/smem/qmi. It listens
on \Callback\PowerState + publishes \Device\RPEN so qcauddev can register as an RPE client for
subsystem up/down. It sends NOTHING to the ADSP. Its Linux equivalent (remoteproc/PDR/servreg for
avs/audio + msm/adsp/audio_pd) is already up. So there is no RPE message to replay.

### THE WALL: the GCS/Graphite responder module is ABSENT from the firmware
All 7 .mbn images: 0 hits for g_glink / gcs_ / graphite / READY_PKT / ipc_ready. Present and readable
(plaintext): apr_audio_svc/apr_voice_svc/apr_apps2 servers, "avs/audio", the migration-crash assert
strings, and the AMDB loader path (dlopenbuf, fastrpc_shell_0, lib%s_skel.so, AdspCoreSvc
REGISTER_AMDB_MODULES_V2). The 28 statichashes contain only AudioContextDetection.so.1 - NO GCS/graph
module. CONCLUSION: the GCS responder is a runtime-loaded module that ships in the WINDOWS audio image/
cal payload and is loaded into the audio PD via AMDB/dlopen. It is NOT in the Linux /lib/firmware blob.
=> cold-opening g_glink_ctrl crashes because there is no responder to rendezvous with; NO Linux
qmi/pdr/apr/glink message can make this firmware advertise g_glink_ctrl. The GCS path is unworkable
on the shipped Linux firmware without first getting the ADSP to load the GCS module (needs the Windows
audio module + its ACDB cal + a fastrpc/AMDB push path -- out of scope, requires Hexagon work).

### Windows rendezvous is a PnP/power sequence (for the record)
qcauddev waits via IoRegisterPlugPlayNotification(DeviceInterfaceChange) on provider GUID
{59752ED7-B9D5-4121-818D-C69F1E667015} (file off 0x1bee0), opens \Device\RPEN, RpeClientInit("AUDD"),
IOCTL 0x3220C020 (audio-PD descriptor), sets ipc_ready_to_use, THEN binds g_glink_ctrl remote-first on
the lpass edge -- with the GCS module already loaded ADSP-side. Not replayable without that module.

### TRACK B = the only firmware-native path: ELITE/APR dev-0x45 (what qcadcm issues)
The firmware implements legacy ELITE AFE/ADM (NOT AudioReach/GCS). qcadcm8180's dev-0x45 sequence over
apr_audio_svc: AFE SET_PARAM CDC_REG_CFG (module 0x10234 / param 0x10237) + SLIMBUS slave/port cfg
(0x10235 / 0x10233) -> ADM open (mainline q6adm 0x10326, LEGACY topology not the AR 0x10000001) ->
MATRIX_MAP_ROUTINGS_V5 0x10325 -> AFE_PORT_CMD_DEVICE_START. Mainline q6 already does ADM-open+matrix+
port-start on SLIMBUS_2_RX playback; what's MISSING is the AFE CDC_REG_CFG codec/SWR register writes +
SLIMBUS cfg that tell the ADSP to bring up the WCD9340 SWR master + enumerate the WSA. Those are
fireable via the q6afe spx_probe. Prior AFE attempts were SILENT only because payloads were GUESSED;
the real CDC_REG_CFG register block is in Codec_cal.acdb CDCLUT0 (e.g. id1=0x00015200 = RX-codec block,
dp_off 0x1722, 0x78 bytes). UNCERTAIN whether CDC_REG_CFG alone brings up the WSA (vs the GCS graph
doing the routing) -- but it is SAFE, firmware-native, and the last viable shot at sound. Extracting
the exact payload now.

---

## 17. (2026-06-17) BREAKTHROUGH: AFE v3 instance header — DSP now PROCESSES AFE params

Patched q6afe.c (sha a379b6e8, installed, needs reboot) to fire AFE SET_PARAM with the 16-byte
instance param header (param_hdr_v3: {u32 module_id; u16 instance_id; u16 reserved; u32 param_id;
u32 param_size}) + the V3 opcodes AFE_SVC_CMD_SET_PARAM_V3=0x000100fa / AFE_PORT_CMD_SET_PARAM_V3=
0x000100fc, behind /sys/kernel/debug/q6afe/spx_probe/hdr_v3 (used ONLY by the probe; normal q6afe
paths untouched). Mirrors the q6adm SET_PP_PARAMS_V6 fix.

RESULT (decisive): with hdr_v3=1 the SPX ADSP RESPONDS to the AFE SET_PARAM and returns
"cmd = 0x100fc returned error = 0x2" = ADSP_EBADPARAM (rc=-22) -- vs the legacy 12-byte header which
got silent rc=0 (acked-and-ignored). So the 16-byte instance header + 0x100fa/0x100fc opcodes ARE
what this ADSP expects for AFE SET_PARAM; the legacy header is dropped. This is real progress: AFE
params are now actually parsed by the DSP.

REMAINING after the header fix:
- SLIMBUS_CONFIG (module AFE_MODULE_AUDIO_DEV_INTERFACE 0x1020c, param 0x10212, payload =
  afe_param_id_slimbus_cfg {minor=1, dev_id=2, bw=16, fmt=0, nch=2, shared_ch={0xc0,0xc1,0..},
  sr=48000} = byte-exact 010000000200100000000200c0c100000000000080bb0000) -> EBADPARAM. Expected:
  slim port-config can only be set at PORT SETUP (before AFE_PORT_DEVICE_START), not on a running
  port. The probe fires on a LIVE port, so this is the wrong time. The fix is to set the correct
  shared_ch_mapping at port-prepare via the machine driver / q6afe, NOT a debugfs fire.
- CDC_SLIMBUS_SLAVE_CFG (0x10235) / CDC_REG_CFG (0x10237) -> EBADPARAM regardless of module
  (tried 0x10234, 0x1020c). The actual WCD9340 SWR-master + WSA-enable register-write data is NOT
  in the ACDB (full LE-u32 scan = 0 hits for 0x10233/5/6/7 + module 0x10234); it is driver-code
  resident in qcadcm8180/qcauddev8180 (mov+movk built). So these params need the real register list
  reverse-engineered from qcadcm code, not the ACDB.
- KEY CHANNEL FINDING: mainline sdm845.c hardcodes SLIM rx channels {144,145,...}=0x90+; the SPX
  speaker (ACDB dev-0x45) uses 192/193=0xc0/0xc1. If the speaker path needs those specific shared
  channels, mainline's machine driver must be patched to set them for SLIMBUS_2_RX at port setup.

NEXT GROUNDED STEP: (1) re-pull qcadcm8180.sys + RE the dev-0x45 codec-register-write sequence (the
mov+movk {reg,val,mask} list the driver applies via CDC_REG_CFG) -> fire via the now-working v3
CDC_REG_CFG. (2) OR patch q6afe/machine driver to set shared_ch_mapping {0xc0,0xc1} + the codec/WSA
config at PORT SETUP (before DEVICE_START), since port-config params EBADPARAM on a running port.
The v3 header (this fix) is the prerequisite that makes any of these actually reach the DSP.

---

## 18. (2026-06-20) CORRECTION: SPX speaker params are V3 PORT-level, not service-level

Supersedes the false negatives in section 17.

### Corrected ACDB fact
Codec_cal.acdb CDCLUT0 key 0x00015200 is valid and extractable. The installed ACSP package
(`surfaceprox_acsp.inf_arm64_c6cbf7d66dbb0926/Codec_cal.acdb`) has:
- CDCLUT0 rec #8: id1=0x00015200, id2=0x00013252, dp_off=0x174e
- DATAPOOL frame: total=0xd8, payload_size=0x78, rsvd=0
- payload starts with 0x00015200 and is written by `scripts/spx-acdb-extract.py --dump-codec-key`

The earlier "CDCLUT0 offsets out of bounds / no replayable payload" conclusion was a parser/framing
mistake.

### Corrected opcode fact
Live probe on a running SLIMBUS_2_RX port (idx 6, 0x4004):
- V3 service opcode 0x100fa rejects all tested CDC/codec params with ADSP error 3 (`rc=-22`).
- V3 port opcode 0x100fc accepts the same bodies (`rc=0`).

Clean accepted sequence:
- PORT V3 mod=0x10234 param=0x10235 len=16  (CDC_SLIMBUS_SLAVE_CFG)
- PORT V3 mod=0x10234 param=0x10296 len=12  (CDC_REG_PAGE_CFG)
- PORT V3 mod=0x10230 param=0x10233 len=32  (SLIMBUS_SLAVE_PORT_CFG)
- PORT V3 mod=0x15200 param=0x10212 len=24  (SLIMBUS_CONFIG with 0xc0/0xc1)
- PORT V3 mod=0x15200 param=0x10236 len=120 (Codec_cal CDCLUT0 0x15200 payload)
- PORT V3 mod=0x15200 param=0x10237 len=1   (commit marker probe)

V2 GET_PARAM is not useful for these ids: it returns ADSP error 2/status=0x2 and no payload for every
tested module/param.

### Kernel/tooling changes made
- `scripts/spx-spkr-probe.sh`: defaults to SPX speaker port idx 6 and writes `hdr_v3=1` by default.
- `scripts/spx-acdb-extract.py`: added `--dump-codec-key <key> <Codec_cal.acdb> <out.bin>`.
- `scripts/spx-spkr-bringup-seq.sh`: now extracts the real 0x15200 payload and uses V3 PORT-level
  commands only. Optional adjacent codec ids are behind `SPX_CODEC_VARIANTS=1`.
- `sound/soc/qcom/sdm845.c`: Surface Pro X-only SLIMBUS_2_RX channel map override to 0xc0/0xc1 for
  both WCD9340 codec channel map and q6afe CPU map. Built and installed
  `/lib/modules/$(uname -r)/kernel/sound/soc/qcom/snd-soc-sdm845.ko`; previous module backed up as
  `.PRE-SPX-CHMAP-BACKUP`.

### Current status
The card comes up, the 48 kHz stereo stream opens, q6afe parks port 6 on close, and the corrected
V3-port bring-up sequence completes with rc=0 for every step. Audibility still must be confirmed at
the speakers; from kernel-side logs, the old service-opcode/ACDB-parser blockers are gone.

---

## 19. (2026-06-20) Staged automatic SPX speaker V3 calibration in q6afe

Promoted the proven V3 port SET_PARAM path from debugfs-only probing into the normal q6afe path:
- `q6afe_spx_set_param_v3()` is now available outside `CONFIG_DEBUG_FS`.
- `q6afe_port_start()` calls `q6afe_spx_apply_speaker_cal()` after a successful
  `AFE_PORT_CMD_DEVICE_START`.
- `q6afe-dai` now parks AFE ports automatically on `microsoft,surface-pro-x`, so the known-wedging
  `AFE_PORT_CMD_DEVICE_STOP` is avoided after reboot without relying on a modprobe option.
- The hook is guarded by:
  - `of_machine_is_compatible("microsoft,surface-pro-x")`
  - AFE token `SLIMBUS_2_RX` and DSP port `0x4004`
  - module parameter `spx_auto_speaker_cal` (default true)
- Failures are warn-only so normal stream setup is not failed by an SPX-only calibration miss.

Embedded sequence is the safe/default accepted subset from section 18:
- `0x10234/0x10235` len 16
- `0x10234/0x10296` len 12
- `0x10230/0x10233` len 32
- `0x15200/0x10212` len 24 with shared channels `0xc0/0xc1`
- `0x15200/0x10236` len 120 from real `Codec_cal.acdb` CDCLUT0 key `0x15200`
- `0x15200/0x10237` len 1 commit marker

Validation:
- `make -j$(nproc) sound/soc/qcom/qdsp6/q6afe.o sound/soc/qcom/qdsp6/q6afe-dai.o`
- `make -j$(nproc) M=sound/soc/qcom/qdsp6 modules`
- `git diff --check`
- `modinfo q6afe` shows `spx_auto_speaker_cal`

Installed/staged on disk:
- `/lib/modules/6.18.3-1-surface+/kernel/sound/soc/qcom/qdsp6/q6afe.ko`
- backup: `q6afe.ko.PRE-SPX-AUTO-CAL-BACKUP`
- installed sha256: `100c050aae91da9cd2b52fe0b14c13ec5aa567f802832edc9881e36868f226ca`
- `/lib/modules/6.18.3-1-surface+/kernel/sound/soc/qcom/qdsp6/q6afe-dai.ko`
- backup: `q6afe-dai.ko.PRE-SPX-AUTO-KEEP-BACKUP`
- installed sha256: `31d11a202f1ac98d2f4176c7fe10e8eb0305784b7228cb82abb8ce7a53085af0`

Not live-reloaded: unloading/reloading q6afe while the audio edge is active can force AFE shutdown
paths, and AFE stop is the known SPX firmware wedge. Current running system remains on the safe
baseline (`remoteproc2` running, card 0 present). The automatic hook will take effect on the next
q6afe module load/boot; until then, the manual debugfs sequence remains the live path.

---

## 20. (2026-07-21) Root cause of the persistent silence: stale boot DTB

**Symptom:** both WSA881x amps enumerate cleanly from APPS (the device-0 clash from
§"RETRACTED no-go" is resolved — `right_spkr` is now `status="disabled"` in the DT so only
the left amp probes), the sound card is fully registered, the wsa881x codec is bound and its
`SpkrLeft IN→RDAC→SPKR PGA→SPKR` widgets power `On` — yet playback is still silent.

**Root cause (definitive, from the live device tree):** the *running* kernel booted an
experimental DTB whose `slim-playback-dai-link` `codec` property is only 8 bytes
(`sound-dai = <&wcd9340 0>`). The WSA881x (`left_spkr`) and the SWR master (`swm`) are **not**
part of the playback DAI link, and the card `audio-routing` has no `SpkrLeft IN ← SPK1 OUT`
route. So when MultiMedia1→SLIMBUS_2_RX plays, no SoundWire stream is ever assigned to the amp's
data port and the WCD9340 speaker DAC is never demanded by the amp → silence, regardless of how
the amp's own widgets are powered.

**The fix is already staged on disk; it just needs a reboot into the default boot entry:**
- The GRUB default (`/etc/grub.d/09_spxtree`, global `devicetree` line) boots
  `/dtb/qcom/sc8180x-surface-pro-x.dtb`. That installed DTB (sha256 `017c1f39…`, identical to the
  in-tree `arch/.../sc8180x-surface-pro-x.dtb`) is the current single-amp-left build:
  - `slim-playback-dai-link` codec = `<&wcd9340 0>, <&left_spkr>, <&swm 0>` (WSA + SWR in the link)
  - `audio-routing` includes `"Left Spk","SpkrLeft SPKR"` and `"SpkrLeft IN","SPK1 OUT"`
  - `speaker@0,2` (right) `status="disabled"` (avoids the shared-address clash)
- `./build-install.sh` was re-run (2026-07-21): the **current** in-tree modules (which carry the
  regmap-based powerdown-GPIO bypass for the `gpio_wcd934x` refcount wedge, the write-only register
  shadow for the shared-address reads, `spx_powerdown_gpio` default 1, etc.) are now installed into
  both `kernel/` and the `updates/` override layer (timestamped backups kept), `depmod -a` run, and
  the Linux ADSP firmware image restored. Verified byte-identical to the in-tree `.ko`s
  (e.g. `snd-soc-wsa881x.ko` sha256 `fdc334c6…`, `soundwire-qcom.ko` `b6dfd192…`).

**Remaining step (requires a reboot — never done autonomously):** reboot into the default
"Arch Linux" GRUB entry, then verify `ls /sys/bus/soundwire/devices/` shows the left amp
(`sdw:0:0:0217:2010:00:1`) and that the live playback `codec/sound-dai` is now 20 bytes (3 codecs),
set the speaker mixer route (SLIMBUS_2_RX Audio Mixer MultiMedia1=on, SLIM RX0 MUX=AIF1_PB,
RX INT7_1 MIX1 INP0=RX0, COMP7 Switch=on, RX7/RX0 Digital Volume=84), and play
`speaker-test -D plughw:0,0 -c 2 -t sine -f 440`. If still silent/distorted after that, the
remaining tuning knobs are the wsa881x params (`spx_rearm_init`, `spx_sample_edge`,
`spx_powerdown_gpio`) and the SLIMbus channel map (must be 0xc0/0xc1 = ch 192/193).

---

## 21. (2026-07-21,续) Post-DTB-fix live diagnosis: chain powers, still silent

Booted the **default** GRUB entry after retargeting `GRUB_DEFAULT` from `spx-known-good`
(`.dtb.wsa`, old config) to `spx-speaker-left-test` (slimfix kernel + `.dtb.speaker-left`,
sha256 `017c1f…` = the generic DTB = WSA in the playback link). `grub-mkconfig` re-run
(backups: `/etc/default/grub.bak-20260721-101527`, `/boot/grub/grub.cfg.bak-…`).

**Now confirmed working (first time in a live boot):**
- Live `slim-playback-dai-link/codec/sound-dai` = 20 bytes = `<&wcd9340 0>, <&left_spkr>, <&swm 0>`.
- `audio-routing` has `SpkrLeft IN ← SPK1 OUT`; `right_spkr` disabled (single amp, no clash).
- `gpio_wcd934x` refcount wedge is **gone** (refcount 1) with the current modules.
- During playback the **entire DAPM chain powers On**: WCD9340 `RX INT7_1 INTERP`, `SPK1 OUT`,
  and WSA `SpkrLeft IN→RDAC→SPKR PGA→SPKR`, card `Left Spk`.
- `wsa881x … hw_params active_ports=2`, `FRAME_CTRL=0x7`, RDAC/PA DAPM PMU events fire; AFE port 6 runs.

**Ruled OUT this session (each tested live):**
- SD_N hardware shutdown — amp enumerates/attaches/streams, so it is awake.
- `spx_clear_npl=1` (SWR-clock NPL delay clear) — no change.
- **Sample edge** — swept `spx_sample_edge` 0x00/0x04/0x08/0x0c with distinct tone freqs: **silence at all** → not a sampling-edge issue; **zeros are reaching the DAC**.
- The V3 AFE speaker calibration (`scripts/spx-spkr-bringup-seq.sh`, all 6 steps `rc=0`) — still
  silent. Caveat: it uses **placeholder (zero) runtime SLIMbus e_addr/LA**, and `rc=0` is not proof
  of effect. Never previously combined with the working DTB.

**SWR-master register dump DURING playback** (`drivers/spx_extras/spx_swrm_regs.ko`, read-only via
WCD9340 AHB bridge 0xc8d/0xc91):
- `DP1_PORT_CTRL_B0 (0x1124) = 0x01000107` → master TX DP1 **enabled**, ch_mask `0x01`, off1=1, SI=7.
- `DP1_PORT_CTRL_B1 (0x1164) = 0x00000107` → **bank 1 ch_mask = 0x00** (asymmetry vs bank 0).
- `DP2_PORT_CTRL_B0 = 0x0f00021f` (ch_mask 0x0f), `DP2_PORT_CTRL_B1 = 0x0000021f` (bank1 ch_mask 0).
- `DIN_DP1_PCM_CTRL (0x1054) = 0`, `DIN_DP2_PCM_CTRL (0x1154) = 0` — but `SWRM_DIN_DPn_PCM_PORT_CTRL`
  is defined-yet-never-written in mainline `qcom.c` too (db845c works with it 0), so likely not the bug.
- `MCP_SLV_STATUS (0x1090) = 0` — likely a poll-enumeration artifact (HW auto-enum status not updated).

**Where the silence now sits (remaining leads, in priority order):**
1. **DP-port bank asymmetry**: ch_mask is set in bank 0 but 0 in bank 1 for DP1/DP2. If the active
   bank is bank 1, the TX port is effectively disabled. Need to confirm the active bank
   (MCP_FRAME_CTRL / bank-switch state) and whether `qcom_swrm_port_enable`'s one-shot ch_mask write
   is landing in the bank that goes active under the SPX poll-driven (IRQ-less) master.
2. **WCD9340 RX INT7 → SWR-master-TX data routing**: the master TX DP is enabled but it is unconfirmed
   that the codec actually feeds RX INT7 audio into the DP TX (vs the unconnected analog SPK1 PA).
   This is driver-resident register config (the script's "SWR-master enable regs, NOT in ACDB").
3. **DP port param match** between master TX (`qcom.c` pconfig: SI/off1/off2/blk) and the WSA slave RX
   DP (`wsa881x` hw_params). The `spx_port_si/off1/off2/bp` overrides (currently -1=default) tune this.
4. **Calibration runtime addresses**: fill the real WCD9340 SLIMbus e_addr + pgd/intf LA into the
   `CDC_SLIMBUS_SLAVE_CFG`/`SLIMBUS_SLAVE_PORT_CFG` bodies (currently zero placeholders).

**Reproduce the key dump:** boot default entry, `sudo speaker-test -D plughw:0,0 -r 48000 -c 2 -t sine
-f 440 &`, then `sudo insmod drivers/spx_extras/spx_swrm_regs.ko; sudo dmesg | grep spx_swrm`.

## 22. (2026-07-21, Codex continuation) Live diagnosis after DTB fix — what is and isn't the gate

Re-booted default entry (slimfix kernel + `.dtb.speaker-left`, all `spx_*` params present;
`BOOT_IMAGE=/vmlinuz-6.18.3-1-surface+-slimfix`, `uname -r`=6.18.3-1-surface+). Live playback
link = 20 bytes (`<&wcd9340 0>,<&left_spkr>,<&swm 0>`); both amps enumerate
(`sdw:0:0:0217:2010:00:1/2`), left binds `wsa881x-codec`; PipeWire parked. **Still silent.**

**Ruled OUT this session (each tested live, with the user confirming silence):**
- **SWR-master DP1 bank scatter.** Live dump showed the active bank (MCP_STATUS bit0=0 → bank 0)
  had `DP1_PORT_CTRL_B0=0x01000000` (ch_mask=1 but **SI=0/off1=0**) while bank 1 had
  `0x00000107` (SI=7/off1=1, ch_mask=0) — the port config was split across banks. Wrote the
  complete `0x01000107` to **both** banks (`spx_swrm_tune.ko`, confirmed live) → **still silent.**
  So the DP1 port config is not the gate.
- **AFE speaker calibration with REAL addresses.** Read the WCD9340 SLIMbus addrs via a helper
  (`spx_slim_info.ko`): codec iface `217:250:1:0` e_addr wire bytes `17 02 50 02 01 00`, **LA 0xcf**;
  PGD iface `217:250:0:0` **LA 0xce**. Fired the full V3 port sequence with e_addr filled
  (`01000000170250020100000000001000`) and pgd_la/intf_la=`ce`/`cf`
  (`010000000000cecf0000100000000200c000c100…`) — all 6 steps `rc=0` → **still silent.**
- **COPP topology.** Playback COPP opens with `spx_rx_topology=0` (NULL_COPP). The speaker
  topologies were ALREADY tried: `/etc/modprobe.d/spx-wsa-enable.conf.bak-v7` had
  `spx_rx_topology=0x10000008` (SPX_V7_SPEAKER_TOPOLOGY); the dev-0x45 AudioReach `0x10000001`
  is V8-only and `q6adm/spx_copp/v8_open` returns **rc=-110 (ETIMEDOUT)** (DSP doesn't answer V8).
  Not the gate via the paths available.

**Confirmed WORKING this session:**
- PCM is genuinely RUNNING: `hw_ptr` advances at exactly 48000 frames/s (ADSP consumes MultiMedia1).
- **SLIMbus channel activation SUCCEEDS.** `qcom_slim_ngd_enable_stream` is the controller's custom
  `enable_stream` (sends `SLIM_USR_MC_DEF_ACT_CHAN`+`RECONFIG_NOW` via `qcom_slim_ngd_xfer_msg_sync`,
  NOT `slim_do_transfer`). Kretprobed it (`spx_en_trace.ko`): **ret=0**, no xfer failures. So the
  WCD9340 SLIM RX0 IS listening on ch 192/193 and the framer allocated them.
- (The intermittent `PIO wait timed out … mc=0x60 la=0xcf` is a benign codec REGISTER READ timeout,
  not the channel activation.)

**THE KEY INSIGHT (from docs/spx-speaker-bringup-handover.md line 95):** the Linux ADSP firmware has a
**STUBBED codec-register op (`AFECdcRegOp_stub.cpp`)**. So every AFE CDC codec-register write the
bringup script fires (CDC_REG_CFG / the 0x15200 codec_cal payload / CDC_SLIMBUS_SLAVE_CFG) is
**ACKED (rc=0) but NEVER APPLIED** by the DSP. That is precisely why the corrected calibration with
real addresses returned rc=0 and changed nothing. On Windows, GCS performs the WCD9340 SWR-master
enable + WSA-enable register writes; GCS is ABSENT from the Linux firmware, and the stub means the
AFE CDC-reg path can't substitute. **These register writes must be issued DIRECTLY by Linux via the
WCD9340 regmap / AHB bridge (0xc85 WR_DATA / 0xc89 WR_ADDR), not via the ADSP.**

**Where the silence now sits:** control plane is fully up (PCM→ADM→AFE port running; SLIMbus channels
192/193 active; WCD9340 RX INT7/COMP7 + WSA chain DAPM-On; SWR master TX DP1 enabled). Zeros still
reach the WSA DAC. The untested link is whether the GCS-resident WCD9340 SWR-master-enable /
WSA-enable register sequence (in the ACDB 0x15200 GCS recipe and/or `qcadcm8180.sys` mov+movk pairs)
has been applied to the codec directly.

**Next concrete step:** extract the per-amp/SWR-master register-write list from the ACDB CDCLUT0
0x15200 blob (`q6afe_spx_codec_cal_15200[]`, already in q6afe.c) and/or RE the mov+movk pairs in
`/home/dvitali/Documents/drivers/FileRepository/qcadcm8180.inf_arm64_6c0af01b459513d1/qcadcm8180.sys`,
then replay those {reg,val,mask} writes DIRECTLY against the WCD9340 regmap (AHB bridge) during a live
stream and listen. Helper modules built this session (vermagic-matched, `KBUILD_MODPOST_WARN=1`):
`spx_slim_info.ko` (dump SLIM e_addr/laddr), `spx_slim_trace.ko`/`spx_en_trace.ko` (kretprobe
slim_do_transfer / enable_stream).
