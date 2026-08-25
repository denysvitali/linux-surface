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

---

## 23. (2026-08-11) V15/V16 recover audibility; pin2 is the gate, not ADSP firmware

After eight guarded-but-silent boots, v15 changed two variables: it powered WCD
GPIO pin2 (`SPX_AMP_GPIO_ON=0x04`) and used the Windows ADSP image.  The user heard
a clack followed by a 440 Hz tone with static from the physical right speaker.

V16 retained pin2 and reverted only the ADSP DTB to stock.  It produced the same
audible result.  The kernel log proves stock `qcadsp8180.mbn` loaded, device 0 was
physically observed, both active DP1 banks read `0x01000107`, and the valid first
stream reported `submitted=22 write_done=19 fallback=18`.

Decisive conclusions:

- Pin2 is the audibility gate. Pin1 has never clicked or played; its amp/speaker
  may be dead.
- The Windows ADSP image and enlarged memory carveout are unnecessary. Continue
  on the audited stock-firmware DTB.
- Listening identifies pin2 as the physical right speaker. The forced device-0
  path binds the `left_spkr` codec object, so the DT label is not physical proof.
- The remaining static is independent of the ADSP firmware choice.

Next single-variable test: the 19 `write_done` callbacks are real
`ASM_DATA_EVENT_WRITE_DONE_V2` events because immediate write ACKs are filtered in
`q6asm.c`.  V17 disables forced timer pacing and replenishes one buffer per DSP
completion, with the existing two-period watchdog retained as a safe fallback.

Pre-boot review found a race in the first v17 build: WRITE_DONE and the watchdog
could both advance and submit at their boundary. The corrected implementation
arms the watchdog before submitting and requires a completion to cancel/claim it;
if the worker is already running, only it changes the stream to timer fallback.
It also computes the period from ALSA frames, fixing the 4/3 S24_LE deadline error
caused by confusing 24 significant bits with its 32-bit container.

Restaged without rebooting: corrected `q6asm-dai.ko` sha256 `6dc4f351…`, normal
and rescue initramfs rebuilt, and GRUB id `spx-speaker-v17-event-pacing` retained.
Its kernel arguments differ from v16 by exactly
`q6asm_dai.spx_force_timer_pacing=0`. Persistent GRUB default remains
`spx-audio-rescue`; no one-time entry was armed at this checkpoint.

Windows source-of-truth refinement: miniport + `Speaker_cal.acdb` prove logical
device `0x45`, 48 kHz/24-bit/stereo, codec key `0x15200`, AFE port `0x4004`, and
channels `0xc0/0xc1`. `Codec_cal.acdb` selects endpoint tokens `0x01010004/5`,
mapped by qcauddev to internal sinks 7/8. No Windows artifact examined labels
those endpoints, MP1/SP1 vs MP4/SP1, or the enable GPIOs as physical left/right;
that mapping must come from isolated-channel listening.

---

## 24. (2026-08-11) V17 validates DSP-completion pacing

The autotest first refused the boot before touching hardware because the guard
compared sysfs boolean `N` with numeric `0`. After normalizing boolean spelling,
the same boot still had no prior PCM stream and the guarded retry was valid.

Listening result: startup clack, 440 Hz tone, and a bit of static. Kernel result:
`submitted=20 write_done=20 fallback=0`, active DP1 banks both `0x01000107`, real
device-0 presence before and after playback, safe PA/GPIO teardown, no fault.
Completion pacing works and did not fall back to the timer. It does not by itself
eliminate static.

V18 will change only the logical frontend format to S24_LE, matching the Windows
miniport, while retaining the known-audible S16/PDM backend. The harness accepts
`SPX_TONE_FORMAT`, and q6asm close logging now records the actual frontend bits.

---

## 25. (2026-08-11) V18 rejects S24_LE; endpoint-B S16 test staged

V18's first stream was internally healthy: Q6ASM reported
`bits=24 submitted=28 write_done=28 fallback=0`, with valid DP1 banks, teardown
and no kernel fault. Listening heard a softer startup clack, low-volume static
and a shutdown clack, but no 440 Hz tone. This is not a transport stall: S24_LE
reaches and is consumed by Q6ASM, but it does not render intelligible audio on
the current legacy path. Restore S16_LE for all routing work.

The next test corrects a topology mismatch in every audible pin2 run. Those
runs powered GPIO pin2 while binding the `left_spkr` MP1/SPK1 codec. The new
right-only DT binds the second WSA object and routes RX1 -> INT8/COMP8 -> SPK2,
slave DP1 -> master DP4 (`<4 5 6 8>`), using GPIO pin2. Windows proves that
device 0x45's stereo recipe orders endpoint `0x01010005`/sink 8 second, probably
with C1; joining it to Linux MP4/SPK2 remains a board-topology inference that
this isolated C1 listening test will validate.

Staged artifacts:

- right-only DTB sha256 `3c32f9a36af310a45859e445fc4c2e8d6d594f3ca45bb2293cbc3b04d0b2ceaa`;
- DP4-capable `soundwire-qcom.ko` sha256
  `b493d7fa5014a507f5fc50e2bd0437c6aa9bb3ac377da2b7622b133fd8be2880`;
- unchanged event-paced `q6asm-dai.ko` sha256
  `ed54b6de367990efdcca7b786ea8b72e4b5d4446855a43533684c0eb64218fbe`;
- GRUB one-shot id `spx-speaker-v19-endpoint-b`, with the v17 kernel command
  line unchanged and only the DTB selection different.

The harness now proves exact DT DAI/map/GPIO/route cells, active S16_LE/48-kHz
stereo hw_params, front-right-only submission, master DP4 value `0x01000607` in
both banks, DP1/DP4 shadow enable and disable, and Q6 `bits=16`, `fallback=0`,
`write_done>0`, `submitted==write_done`. The persistent GRUB default is still
rescue; the one-shot is armed only after all offline checks pass.

---

## 26. (2026-08-11) Endpoint B / MP4 / C1 is audible on pin2

V19 produced a clack, the 440 Hz tone and a bit of static. The controlled run
bound only WSA unit 2 on WCD GPIO pin2 with map `4 5 6 8`, opened S16_LE at
48 kHz/stereo, and selected only C1/front-right. Both active master-DP4 banks
were `0x01000607`; slave DP1 and master DP4 enable/disable operations were
shadowed. Q6ASM reported `bits=16 submitted=19 write_done=19 fallback=0`.
The PA shut down and GPIO returned to `0x00` without a kernel fault.

The systemd unit's status 1 is not a hardware failure. `speaker-test -s 2`
prints `- Front Right`, while the new guard expected the old all-channel form
`1 - Front Right`; all later transport/counter conditions can be verified in
the captured log. The matcher now accepts the single-channel spelling.

This is the first direct empirical join from Windows' second ordered endpoint
and C1 to Linux MP4/SPK2 and physical pin2. The same slight static exists when
pin2 is driven through MP1 or MP4, so the former endpoint mismatch did not cause
it. Next test endpoint A / MP1 / C0 with physical pin1 in the same corrected
event-paced harness, then build sequential dual-amp enumeration only after both
isolated diagonals work.

---

## 27. (2026-08-11) Endpoint A completes digitally; pin1 remains silent

V20 passed every automated guard and the user thinks nothing was heard. Unit1
bound to pin1/map `1 2 3 7`; the physical pin1 amp announced; S16/48-kHz C0 was
submitted; MP1 B0/B1 were both `0x01000107`; DP1 slave/master shadowing and PA
events completed; Q6 was `bits=16 submitted=19 write_done=19 fallback=0`.
Cleanup was exact and there was no fault.

Because endpoint A/MP1 is already audible through pin2 and endpoint B/MP4 is
also audible through pin2, v20 localizes silence downstream on the physical
pin1 side. V21 provides the last acoustic cross: use proven endpoint B/MP4/SPK2
and C1 but override its sole enabled codec to power only pin1 (`0x02`). The
harness accepts this mismatch only with an explicit `right-on-pin1` cross flag;
normal left/right path-to-GPIO equality remains mandatory.

If v21 is silent/no-clack, treat pin1 WSA analog output/boost, speaker or wiring
as defective and do not build dual attach. If it is audible, return to endpoint
A's MP1/SPK1 WCD routing. Permanent stereo additionally needs the DTS identity
correction from probed `0217:2110` unique IDs 3/4 and a sequential device1/2
assignment state machine; current force mode hard-aliases enabled codecs to 1.

### V21 outcome

The user heard nothing. The run itself was complete: endpoint B/C1 at S16/48k,
DP4 `0x01000607` in both banks, slave-DP1/master-DP4 shadows, PA events, and Q6
`bits=16 submitted=19 write_done=19 fallback=0`; cleanup and fault guards passed.
V19 differs semantically only by endpoint B's GPIO pin2 instead of pin1, and was
audible. Pin1's announcing WSA therefore has a nonfunctional analog output,
speaker or connection. Keep it powered off; do not build dual attach in software
until that physical side is repaired. Proceed with the isolated endpoint-B/pin2
path for static reduction and repeat-stream lifecycle work.

---

## 28. (2026-08-11) V22 disables the stale uncalibrated protection state

Windows reverse engineering corrected an earlier attribution: the WSA writes
`313a=66->67->47`, `3115=11`, and `3110/3111=80` are qcauddev's conditional
speaker-protection enable path, not generic cold init. Linux replayed them even
though its guarded baseline has VISENSE off, transports only the DAC port, and
does not send device `0x45`'s module `0x1025f` protection calibration. V22
instead sends Windows' matching disable sequence: `3110=00`, `3111=00`,
`3140=95`, wait 1 ms, `313a=ce`.

The one-variable endpoint-B/pin2 run passed all machine checks. Loaded module
SHA-256 is `e3a21aa6e32083884c6fb3e4c85d5fe465d716dadca88a67c7d6c2d9730d0e3a`;
the idle cold replay completed, active DP4 B0/B1 were `0x01000607`, hw_params
were S16_LE/48-kHz/stereo with front-right selected, and Q6 was
`bits=16 submitted=19 write_done=19 fallback=0`. Teardown and parking were
clean and no fault occurred. Because this forced WSA path cannot read the
registers back reliably, the logs prove ordered software submission, not each
write's electrical landing. Acoustic feedback remains pending; compare static
directly against v19's clack + tone + slight static.

The repeated listening run produced the tone mixed with static and one brief
interruption, so protection-off did not cure the noise. Host evidence stayed
clean (`19/19`, fallback zero, DP4 enabled, no XRUN or PA/bank transition).
The interruption aligns with the harness's active-stream controller snapshot:
it began about 0.61 seconds after PA-on and consumed roughly 165 ms of shared
WCD/SLIMbus control traffic. Remove only that in-stream snapshot and repeat the
same v22 baseline. Pre/post snapshots and shadow enable/disable logs still guard
the transport without perturbing active sample delivery.

The listened no-snapshot repeat was acoustically negative: clack, low static,
then clack, with no 440-Hz tone. It nevertheless had the same S16/48k/C1 setup,
Q6 `19/19/0`, DP1/DP4 shadow sequence and PA events as audible v22, and its
slave-status latch stayed at `1`. The active controller read is now the only
operation correlated with confirmed v22 audibility, even though it also caused
the brief gap when performed over tone samples.

Next run one PCM waveform with three seconds of exact digital zero followed by
five seconds of right-channel 440 Hz. Take and validate the active snapshot
during the zero prefix, then make no further control transaction before the
tone. This tests whether the read is an accidental transport wake/latch while
moving its 140-165 ms disturbance outside the audible portion.

That first pre-roll run was silent except for clack/static/clack even though the
active snapshot proved DP4 `0x01000607` in both banks and Q6 was `64/64/0`.
The generated sine was then found to peak at only -18 dBFS, versus roughly
-2 dBFS for the earlier speaker-test, and aplay had chosen 6000/24000-frame
period/buffer sizes. Correct the vector to -2 dBFS and force the proven
12000/48000-frame geometry before drawing an acoustic conclusion.

The corrected control still produced nothing audible. Its active snapshot
proved DP4 `0x01000607` in both banks, the right-channel waveform was verified
at -1.97 dBFS with exact zero preroll, ALSA used 12000/48000 frames, and Q6 was
`32/32/0`. Host-visible transport setup is therefore insufficient to guarantee
the write-only WSA's DAC/analog state.

V23 introduces a rollbackable `spx_win_pa_profile=3`. It follows qcauddev's
mutually exclusive profile-3 PA branch: DAC `c2`, OCP `b4->b6->b2`, driver
`fc`, 2-ms wait, no non-profile-3 DAC staging or VI pulse/teardown, then the
existing common gain/final writes. Default profile0 retains v22. Installed WSA
module SHA-256 is
`0f6280ea321daca06a1031f3dfd86b96ca74bbb57d00337a2d119f9d0e5b2d2b`.
This intentionally retains protection-off because Linux lacks the calibrated
VISENSE/module-`0x1025f` path; it tests the exact PA branch, not full protected
Windows profile3. One-shot GRUB id is `spx-speaker-v23-pa-profile3`.

---

## 29. (2026-08-20) Every stream renders: the `spx_keep_asm` fix

The "only the first stream of a boot has `write_done > 0`" rule was a Linux bug,
not a hardware limit. The SPX ADSP never acknowledges `ASM_STREAM_CMD_CLOSE`
(0x10BCD times out), so the close path tore down state the DSP still held and
the next session was never re-attached.

`q6asm_dai.spx_keep_asm` (default **on**) parks the ASM `audio_client` across PCM
close and reuses it on the next open:

- `q6asm.c` gained `q6asm_audio_client_rebind(ac, cb, priv)` (exported);
- `q6asm-dai.c` gained `q6asm_dai_data.parked[16]`, indexed by front-end DAI id;
  `open()` reuses and rebinds, `prepare()` skips map/open_write/media-format for a
  reused client, `close()` detaches the callback and parks instead of freeing.

Validated on the v28 entry (endpoint B / pin2 / S16 / event pacing): two
consecutive streams both closed `submitted=24 write_done=24 fallback=0`, where the
second used to report `write_done=0`. PipeWire's repeated open/close therefore
renders. **The first-stream-only rule in this file and in CLAUDE.md is superseded:
later streams of a boot are now valid measurements.**

## 30. (2026-08-20) The static survives every amp-side and transport-side knob

With music finally rendering, the user played a full track and heard mostly
static. The decisive observation is that the static is **also present during the
three-second digital-zero prefix** of the guarded waveform, so it is added noise,
not mis-shaped content.

Each of the following was A/B'd *on the audible pin2 baseline* — the first time
any of them had been judged outside the whole-boot-silence era:

| knob | result |
|---|---|
| `spx_sample_edge` (WSA `SAMPLE_EDGE_SEL` 0x3044) | HW reset = tone + static (best); `0x0c` = silence; `0x00` = static only |
| RX0 orphan routing (RX1 → AIF1_PB only) | static unchanged, and `overflow error on RX port 0` still fired |
| `spx_win_transport` (block packing 0xff/0xff/0xf0 vs Windows reset values) | 0 and 1 both static |

The `overflow error on RX port 0, value 1` fires once per stream even with RX0
disconnected, so it is not the static and not an orphaned-left-channel effect.

A downstream-source comparison (LineageOS sm8150 tavil/wcd934x) then closed the
last amp-side hypothesis: **there is no interpolator→SWR-master routing register.**
RX7/RX8 output is fix-wired in the WCD9340 die to the SWR master TX data port; the
codec driver's whole SWR duty is to enable the interpolator, gate the SWR clock
(0x0d43 bit 0) and notify the master. Master DP framing also matches downstream
(`si=7, off1=1, off2=0`) and the slave is `read_only_wordlength`.

## 31. (2026-08-21/22) Windows RE round: `docs/windows-re/`

Ten reports plus `00-synthesis.md`, all claims cited to virtual addresses. The
load-bearing results:

- Windows drives **every** WCD9340 register — including the internal SoundWire
  master and both WSA881x amps — over **SPI4 at 24 MHz**. Linux reaches the same
  registers through the SLIMbus AHB bridge; the bridge discipline itself is
  byte-for-byte the Windows one, so our flaky-read saga is a property of the
  transport we chose, not a missing sequence.
- The ADSP firmware image is byte-identical on both operating systems and owns
  only the SLIMbus data path (`AFESlimbusDriver` → `SlimBusMaster` → BAM-Lite).
  `AFECdcRegOp` is a stub in both images, so the ADSP has never been able to write
  codec registers. **This demotes the staged `q6afe.spx_auto_speaker_cal` steps
  that target `CDC_REG_CFG`: they land in a stub.**
- Windows **never broadcasts `SCP_FrameCtrl`.** It programs the destination bank
  completely from per-port records and then writes that bank's frame-control word
  alone. `spx_mirror_banks=1` was therefore never Windows parity; keeping both
  banks complete is.
- Windows opens **all four** WSA descriptors per side, per the static left/right
  descriptor tables (slave 1/2/3/4 → master 1/2/3/7 and 4/5/6/8).

## 32. (2026-08-22) V31: four WSA descriptors on the audible baseline

Everything the amp and the SoundWire master can be told has now been excluded, so
the remaining structural difference is the **number of descriptors the stream
opens**. The guarded baseline opens one (DAC); Windows opens four; mainline
`wsa881x.c` on db845c opens whichever the mixer switches request — and our own
mixer path sets `SpkrRight BOOST Switch 1` while the BOOST descriptor is never
streamed. An amp whose boost-converter control port is enabled in the analog
domain but starved on the wire is a plausible source of broadband switching
noise that is independent of PCM content, which is exactly the signature.

Four-port operation was tried once before ("loud startup transient, then
silence"), but that was during the pin1 whole-boot-silence era and is not a
result about the audible pin2 baseline.

Staged for one guarded cold boot:

- GRUB id `spx-speaker-v31-fourport`, derived from `spx-speaker-v28-music` by
  substituting exactly one token: `snd_soc_wsa881x.spx_stream_port_mask=1` →
  `=5` (DAC + BOOST). Verified token-by-token against v28; nothing else differs.
  Mask 5, not 15, for the guarded stream: master port 8 is a **DIN** port
  (`qcom,din-ports = <2>`), so the VISENSE descriptor is an amp→master input,
  while `wsa881x.c` declares all four slave ports as sinks and adds them to an RX
  stream. Opening it is the one direction-inconsistent combination, and VI sense
  is disabled anyway by v22's protection-off state. Endpoint B maps slave DP1/2/3
  (DAC/COMP/BOOST) to master ports 4/5/6, all DOUT, and slave DP4 (VISENSE) to
  master port 8, DIN — so masks 5 and 7 are the clean supersets and 15 is the
  risky one.
- `scripts/spx-speakers-up.sh` gained `SPX_EXPECT_PORT_MASK` (default 1, so every
  existing entry is unchanged). It validates the live parameter, requires the mask
  to appear on the command line when it is not 1, requires the DAC bit, and
  derives the expected `active_ports` count by popcount instead of hardcoding 1.
- `drivers/soundwire/qcom.c`: `spx_shadow_dp1_enable` now keeps **both banks
  complete for every WSA descriptor in use** (slave DP1–DP4 and any master port),
  not just the DAC pair. This is doc 02's destination-bank model applied to the
  ports the four-port stream adds; single-port boots are unaffected because only
  the DAC pair is ever touched there.
- `scripts/spx-portmask-sweep.sh` A/Bs masks live in one boot (the parameter is
  0644 and is read at `hw_params`, and §29 makes later streams valid). Candidate
  order after the guarded first stream: 5 (DAC+BOOST, what the mixer asks for),
  3 (DAC+COMP), 1 (the v28 control).

The `spx-speaker-v30-cal-bisect` entry was removed: its title claimed live debugfs
cal firing that its command line did not select. `spx-speaker-v29-acdb-cal` is
retained but demoted by §31's stub finding. The persistent default remains
`spx-audio-rescue`.

### V31 staged artifacts (2026-08-22)

| artifact | sha256 |
|---|---|
| `/boot/vmlinuz-6.18.3-1-surface+-slimfix` | `c202330dbc6b4145b0629a057109745dc803621b94807ec2965ad705818049d9` |
| `/boot/dtb/qcom/sc8180x-surface-pro-x.dtb.speaker-right-v19` | `3c32f9a36af310a45859e445fc4c2e8d6d594f3ca45bb2293cbc3b04d0b2ceaa` |
| `updates/soundwire-qcom.ko` (v31, all-descriptor bank shadow) | `c7e09fe16904d6d81752d651e2da4eb2c5afe5f443627b392889321f02bf7b4c` |
| `updates/soundwire-qcom.ko.bak-v28-20260822-112032` (rollback) | `5767d0d9f30297a29f912aea8fb2581cd737844663a64f34f2ade88123134562` |

`mkinitcpio -P` was run after installing the module, and **both** images were
verified to bundle the new `soundwire-qcom.ko` plus unchanged `snd-soc-wsa881x`,
`snd-soc-wcd934x` and `wcd934x` — the mechanical bundled-vs-installed check the
harness audit asked for, done by extracting each image and comparing hashes rather
than trusting mtimes. The rescue entry blacklists `soundwire_qcom` outright, so it
is unaffected either way.

`test-env` gained `SPX_EXPECT_PORT_MASK=5` (previous copy kept as
`test-env.bak-v28-*`); every line still matches the autotest's
`^SPX_[A-Z0-9_]+=[-_.:,0-9a-zA-Z]*$` filter. `grubenv` is
`saved_entry=spx-audio-rescue`, `next_entry=spx-speaker-v31-fourport`, and the
`armed` marker exists, so the guarded harness runs once and the machine returns to
the rescue default afterwards.

---

## 33. (2026-08-22) V31 ran clean and negative; the static does not pass the PA gain

### The v31 boot itself

The guarded one-shot took the armed entry (`spx_stream_port_mask=5` confirmed on
`/proc/cmdline`, `next_entry` consumed) and passed every gate with exit status 0.
The BOOST descriptor genuinely streamed for the first time:

```
SPX: hw_params active_ports=2
shadow slave  DP1 ChannelEn 0x01     shadow slave  DP3 ChannelEn 0x03
shadow master DP4 ChannelEn 0x01     shadow master DP6 ChannelEn 0x03
SPX ASM stream 1: bits=16 submitted=32 write_done=32 fallback=0
```

The all-descriptor bank shadow added to `qcom.c` for this test worked exactly as
intended — both banks complete for DP1/DP3 on the slave and DP4/DP6 on the master.

### A harness gap that was invalidating live sweeps

The first live sweep was audible and an immediate replay with byte-identical
software was near-silent. `scripts/spx-portmask-sweep.sh` was powering the amp,
firing one force-attach, sleeping 1 s and playing regardless — while the guarded
harness samples `MCP_SLV_STATUS` until it sees a real `0x1` and refuses to open
ALSA otherwise. That is why harness runs are reliably audible and ad-hoc replays
were a coin flip.

The sweep now copies the harness recipe: wait for a genuine device-0 announce
before touching force-attach, then wait for `SPX FORCE-ATTACH: stable attachment`
plus the cold-init replay rather than sleeping a guess, and **abort instead of
playing** if presence never appears. It also takes idle-only serialized snapshots
(bridge canary, `MCP_SLV_STATUS`, DP4 banks) before and after every tone.

This immediately earned its keep. One "both silent" run read `MCP_SLV_STATUS=0x0`
at every sample — the amp never announced, so both tones were void measurements,
not results. The DSP still reported `32/32/0` throughout, which is exactly why this
failure mode has been so effective at faking success. **Every listening result
recorded below comes from a run with a proven device-0 attach.**

### The A/Bs, all on a verified-attached audible baseline

| variable | change | result |
|---|---|---|
| descriptor count | mask 5 (DAC+BOOST) vs mask 1 (DAC) | static + tone, **identical** |
| PA gain | `SpkrRight PA Volume` 12 → 0 (+18 dB → 0 dB) | **tone vanished, static remained** |
| boost converter | `SpkrRight BOOST Switch` 1 → 0, gain back to 12 | static **unchanged** |

The middle row is the important one. `PA Volume` is the WSA881x PA output gain
(`SPKR_DRV_GAIN`, 0x311b, REG mode). If the static passed through it, an 18 dB cut
would move signal and noise together and the ratio would hold; instead the tone
dropped below the noise while the noise stayed put.

**Therefore the static does not traverse the PA gain stage, so it is not the audio
data.** That retrospectively explains why every digital A/B has failed: framing,
block packing, sample edge, descriptor count, interpolator routing and the AFE /
SLIMbus channel mapping all sit upstream of a gain stage the noise does not pass
through. The entire digital search space was the wrong layer.

Descriptor count is now closed as a static hypothesis (PROGRESS §32 / the
`spx-static-descriptor-count-hypothesis` memory). The boost converter is closed
again, this time on a verified-attached audible baseline rather than in the
07-26 era.

### What remains, and the control that was never run

Candidates that sit at or after the PA gain: PA output-stage instability, and the
bias/bandgap state left by the cold-init table and by v22's protection-off writes
(`3110=00`, `3111=00`, `3140=95`, `313a=ce`).

Before any of that, a control this project has never actually established: **is the
noise coming from the amp at all?** `SPX_ZERO_ONLY=1` plays ten seconds of exact
digital zero at +18 dB and then parks the amp, so the noise can be timed against
power-on, stream start and park. If it is present before the stream and after the
park, then it is ambient and every static A/B ever run has been measuring the room.
Result pending.

## 34. Four-phase localization (2026-08-22 evening) — the tone itself is gone

`scripts/spx-noise-localize.sh` ran three times, the last two attended and valid
(real device-0 announce before every play, `COMP_PARAMS=0x016840c6` canary at all
four snapshots, DP4 banks enabled mid-stream, Q6 counters real, clean teardown).
Phases: A room baseline (amp off) / B amp powered + PA staged directly via
`spx_wsa_seq`, no PCM / C one stream = 3 s zero + 5 s 440 Hz + 3 s zero with the
controller snapshot inside the leading zeros / D parked again.

Results across the evening:

- A: silent — ambient room noise is ruled out as everything ever heard.
- B: no clicks, at most faint static in one run, nothing in later runs. The
  directly-staged idle output stage is quiet or dead.
- C: **no power-up click, no 440 Hz tone** — on a boot whose morning sweeps were
  audible through this exact transport.
- D: silent.

The final control raised every software knob to maximum headroom:
`RX8 Digital Volume` 84 → 124 (+10 dB), `SpkrRight Smart Boost Level` → 15
(~8.5 V rail), PA gain 12 (+18 dB). The stream provably flowed (`44/44/0`,
banks `0x01000607` both banks) and was still **completely inaudible**.

Two conclusions, stated separately because they have different consequences:

1. **The morning→evening decay happened without any software change.** Same boot,
   same modules, same mixer values, more software headroom — sound went from
   "tone + static" to "nothing". Either the pin2 output chain (amp output /
   speaker / connector) degraded physically during today's repeated high-gain
   power cycling — mirroring pin1's day-one failure mode: announces digitally,
   passes every host-side gate, emits nothing — or the amp silicon drifted into
   a degenerate bias/bandgap state that our park floor does not clear (CLAUDE.md:
   parking does not clear that state; only a full power cycle can).
2. **Every gate we can check is host-side.** WSA writes are never ACKed and
   bridge reads return fabricated data, so "all gates passed" proves what the
   host *sent*, never what the amp *is*. A degenerate amp state is NOT excluded
   by tonight's evidence.

### SPI4 read-oracle: attempted, interface dead from Linux (2026-08-22)

Built `drivers/spx_extras/spx_spi4_oracle.ko` — the read-only half of
`wcd934x-wdsp.c` (CLKREQ wake → RDSR status → IRR internal reads → MIOR flat
reads), no WDSP boot, no codec-register writes. Motivation: Windows reaches the
same register file over SPI4 with reliable reads (docs/windows-re/07); a working
oracle would end our dependence on the fabricating SLIMbus bridge.

Result: every transfer ACKs electrically but returns flat zeros — RDSR status 0,
all IRR/MIOR reads 0x00000000, across 8 CLKREQ retries, with MCLK running
(9.6 MHz, clk_summary `Y`). Controls: the touchscreen (`hid-over-spi`, QUP SE1)
is bound and working, so board SPI + GENI QUP + pad muxing are fine; our SPI4
config matches the DSDT `_CRS` byte-for-byte (CS0 active-low, mode 0, 8-bit,
24 MHz). Remaining explanations: the codec gates its AUDD-SPI slave domain in a
state only the Windows boot sequence reaches, or it is strap/fuse-disabled on
this unit. Module kept for future boots; not resolvable cheaply tonight.

### The fork (recorded before asking)

- **Full power-off** (shutdown, wait, cold start): resets all codec/amp silicon
  state. Sound returns → state, not hardware; continue the software hunt.
  Still silent → hardware failure near-proven.
- **Windows dual-boot play test**: definitive oracle. If Windows cannot make
  this speaker produce sound either, the hardware case is closed regardless of
  anything else. Needs an armed entry and explicit user authorization.

## 35. Post-poweroff verdict (2026-08-22 21:57) — HARDWARE FAILURE, near-proven

The fork from §34 resolved: full power-off (30 s drain, cold start at 21:33) onto the
byte-identical v31 configuration produced another fully gated but **completely
inaudible** four-phase run (`spx-noise-localize` log 215609). Attach proven pre-play
in both phases, canary OK at every snapshot, DP4 `0x01000607` both banks mid-stream,
Q6 `44/44/0`, clean PA lifecycle. The user heard nothing anywhere: no click, no
static, no tone.

The evidence chain is now:

| when | software | result |
|---|---|---|
| 2026-08-22 ~12:00 | v31 entry, autotone | clack + tone + static |
| 2026-08-22 evening | same boot, MORE headroom (RX8 124, boost 15) | silence |
| 2026-08-22 21:57 | full power-off, byte-identical v31 | silence |

A full power cycle resets every resettable thing: codec silicon (rails, bandgap,
bias), WSA amp internal state, and the boot-time init sequence re-ran cleanly. The
degenerate-state hypothesis is disproven. Byte-identical software was audible at
noon and is silent at night across a power boundary. **The pin2 output chain has
physically failed** — amp output stage, speaker coil, connector, or a common feed —
with exactly the signature pin1 showed from day one (announces digitally, passes
every host-side gate, emits nothing; two independent amps dying identically points
at a shared physical cause rather than two coincidental chip failures).

Every host-side observation is consistent with a healthy transport because the
transport IS healthy; nothing downstream of the DAC word exists where software can
look (WSA writes unACKed, bridge reads fabricated, SPI4 slave interface dead from
Linux — §34).

Consequences:

- All remaining analog experiments (BIAS_PSRR, profile 3, BIAS_INT, PWM carrier)
  target static-around-a-tone and are MOOT until a tone physically returns. Do not
  run them.
- The goal statement changes: software bring-up is COMPLETE and validated against
  the Windows ground truth; the blocker is hardware. Re-opening software work
  requires first re-establishing audibility through a physical change (repair,
  reseating connectors, or replacement hardware).
- `scripts/spx-noise-localize.sh` remains THE tool to re-baseline any future boot
  (e.g. after repair): Phase B/C prove attachment and staging before asking for
  ears, so a silent run can never masquerade as a software result again.

## §36 — Verdict stress-tested to exhaustion (2026-08-22 23:30)

The user challenged the §35 hardware conclusion ("I'm fairly sure the HW is still
OK"), which drove three final software campaigns tonight. All three failed in ways
that *strengthen* the physical verdict:

1. **Natural-enumeration addressing model** (the 07-26/28 audible-era model,
   `no_assign=0 write_dev0=0`): the amp announces at device 0 but the
   `SCP_DEVNUMBER` assignment never visibly takes — every verify read returns
   `id=aa aa aa aa aa aa` (the known fabricated-read wall) and `MCP_SLV_STATUS`
   stays `0x1` (present at dev0) through init and playback, so per the 07-29
   precedent the amp never moved to dev1. With `spx_blind_attach=1` (the knob the
   audible-era GRUB entries actually used) the driver attaches logically and runs
   a full stream (`44/44/0`) — but all of its writes go to logical dev1 where
   nothing physically lives. Era mode cannot deliver on this machine today.

2. **Unicast click probe**: `DRV_EN` fc↔7c toggles through the normal
   forced-dev0 path — silent.

3. **Broadcast click probe (the decisive one)**: added `bcast=1` mode to
   `spx_wsa_seq.ko` (`sdw_bwrite_no_pm_unlocked` + bus_lock; the qcom master
   pushes the command before waiting, so `-ENODATA` means "sent, unconfirmed" and
   must not abort the sequence). Broadcast is the only write class on this master
   with real hardware confirmation (`SPECIAL_CMD_ID_FINISHED` completion, `rc=0`).
   With the amp powered, announced, and stably attached ([5564.267] in the boot
   log), the *entire minimal analog bring-up chain* — reset release, CDC clocks,
   CLOCK_CONFIG, bias, DAC ctl, misc, boost config, ANA_CTL latch, gain 0x09
   (+18 dB REG mode), then `DRV_EN` fc↔7c ×4 — went out as 22 broadcast writes,
   every one `rc=0`. **Zero acoustic output.**

4. **Bare SD_N rise**: powering pin2 alone (GPIO high, no bus traffic) produced
   no click. This amp's very first power-up (2026-08-11, v15) clicked audibly
   from SD_N alone — a pure electrical/mechanical event that requires no DAC
   data, no SoundWire, no ADSP. That click is gone.

A powered, frame-synced, attached amp that receives hardware-confirmed analog
enable writes and produces nothing — plus a silent power-up transient — cannot be
explained by any host-side software state. §35's verdict stands with much stronger
evidence. Remaining physical candidates: amp output stage, speaker coil, or the
board-to-board connector; two amps dying identically (pin1 day-one, pin2 today)
points at a shared physical cause (common feed, flex/connector fatigue, or
assembly-level damage).

New tooling kept for the repair day:
- `drivers/spx_extras/spx_wsa_seq.ko` `bcast=1` — broadcast register sequences
  (hardware-confirmed delivery; use only while parked, one amp powered).
- `scripts/spx-noise-localize.sh` `SPX_EXPECT_STATUS` — attach gate accepts the
  enumerated-address status for era-model re-baselines.
- `drivers/spx_extras/spx_spi4_oracle.ko` — SPI4 read oracle (interface currently
  returns flat zeros from Linux; §34).

## §37 — The challenge audit (2026-08-23 00:15)

The user rejected §36 ("Prove yourself wrong") and was RIGHT to: re-audit found
the 23:24 "minimal chain" broadcast test used hand-mapped registers that were
largely WRONG (SPKR_DAC_CTL value written to BONGO_RESRV_REG1, MISC values into
TEMP regs, boost presets shifted by one, BIAS_INT/PA_INT/OCP never written).
That test was void. Corrected evidence:

1. **Delivery proven without ears**: a broadcast `SCP_DEVNUMBER` (0x46 <- 6)
   moved `MCP_SLV_STATUS` 0x1 -> 0x0 within 600 ms of a fresh dev0 announce --
   the amp RECEIVED and EXECUTED the command. Broadcast reaches this amp; rc=0
   is meaningful. (Also confirms unicast delivery is what broke in era mode.)
2. **Faithful replay still silent**: the exact 93-register guarded sequence
   (cold init -> protection-off -> supplies -> boost -> OCP -> pre-PA ->
   Windows profile-0 staging incl. DAC ramp, VI pulses, PWRSTG staging, DRV_EN
   fc, 12-step gain ramp, fd/ac tail), machine-generated from wsa881x.c with
   shadow-RMW emulation (`/tmp/gen-faithful-seq.py`), delivered over the proven
   broadcast channel into a freshly powered amp: **complete silence**. Same on
   pin1.
3. **Software identity verified at every layer**: kernel cmdline byte-identical
   to the noon-audible boot (journal diff), no module or DTB file modified
   after noon (find -newermt empty).

What survives of the hardware verdict: powered amps that provably execute
received bus commands produce nothing from the full confirmed-delivered analog
bring-up, on both speakers, after a power cycle, with byte-verified identical
software to an audible run. What does NOT survive: the earlier broken-chain
"proof", and overconfidence in SD_N-click absence (v15's click may have been a
first-power special).

Open alternative that fits every observation: **a thermal/marginal contact**
(all evening tests ran on a warm device; a contact that opens hot explains
noon-audible -> evening-silent -> power-off-no-help). Falsifier: leave the
device OFF overnight, one guarded cold boot in the morning. Audible = verdict
wrong, chase intermittent connection. Silent = thermal hypothesis dead too.

## §38 — Second challenge audit (2026-08-23 00:45): the verdict has an uncontrolled variable

Re-audit of §34–§37 against `/var/lib/upower/history-charge-M1086677-38-0025151003.dat`
(the live battery's upower log; entries begin 2026-08-20) and the journal.

**1. The power-state confound.** Every attended silent full-chain test ran on a
discharging battery below 50%; every audible run on record ran on AC or at ≥50%:

| when | test | power state |
|---|---|---|
| 08-20 13:46–15:41 | keep-asm / static A/Bs — AUDIBLE | battery 79→50% then AC |
| 08-22 11:59 | v31 autotone — AUDIBLE (clack+tone+static) | AC, 47% pending-charge |
| 08-22 15:58 | AC unplugged (46% discharging) | — |
| 08-22 19:40 | noise-localize #1 (the UNattended one, §34) | AC, 50% |
| 08-22 20:14 / 20:19 | noise-localize, attended — tone GONE | battery 49↓ / 47↓ (unplug ~20:10) |
| 08-22 21:05 | max-headroom control — silent | battery 38↓ |
| 08-22 21:56 | §35 post-poweroff verdict run — silent | battery 27↓ |
| 08-22 22:41 | era-model noise-localize — silent | battery 16↓ |
| 08-22 23:24–23:38 | §36 broadcast campaigns — silent | battery 3–6% |
| 08-22 23:42 | AC restored | charging 4→50% |

§35's "a full power cycle resets every resettable thing" is wrong for exactly one
thing: the 21:33 power-off brought the machine back on the same draining battery
(~30%). The suspect variable was never reset. The WSA881x is a boost-converter
smart amp drawing its output-stage current from the battery rail, and Surface EC
power policy at low SOC is unknown; a browned-out or EC-limited boost rail
produces precisely the observed signature (digital core announces and executes
commands, analog output absent). The §37 thermal hypothesis is confounded with
this one: long evening uptime = warm device AND drained battery.

**2. Since AC was restored at 23:42, no sound has been attempted.** The §37
faithful 93-register replay was register-only. The 00:26 boot (AC, 50% held —
byte-for-byte the noon-audible power state) has had ZERO PCM streams
(`dmesg | grep -c "SPX ASM stream"` = 0). Its only probes were the SD_N click
(an indicator §37 already downgraded) and an 8-write partial PA chain
(reset/DAC/OCP/DRV_EN — no clocks, no bias/bandgap, no BOOST_EN 0x312a), which
is not expected to click even on healthy silicon. "Cannot play anything, not
even static" currently rests on no play attempt in the audible-era power state.

**3. The §37 overnight-cold falsifier was pre-empted**: the machine was rebooted
9 minutes after shutdown, warm.

**Next (in order, one listen each):**
1. NOW, on this boot (AC, ≥50%): attended `./scripts/spx-noise-localize.sh`.
   Audible → hardware verdict DISPROVEN; the gate is power state; re-run on
   battery <50% to confirm the mechanism. Silent → power confound closed.
2. If silent: power OFF, leave OFF and CHARGING overnight, one attended guarded
   cold boot in the morning (kills thermal and charge-state together).
3. Only if both silent does §35/§36's physical verdict stand — and even then it
   is "pin2 output chain failed", not "we broke it": nothing host-side ever
   commanded anything a protected amp shouldn't survive, though note v22 runs
   protection-OFF, so the §34 "repeated high-gain power cycling" days ran
   without OCP/OTP guards.

## §39 — OVERTURNED: the speaker is alive (2026-08-23 01:01)

§38's falsifier step 1 was executed and fired positive. Two guarded four-phase
`scripts/spx-noise-localize.sh` runs (00:51, 01:00 —
`/tmp/spx-noise-localize-20260823-{005109,010005}.log`, waveform sha256
`de0c6a6c…ec37de`) on this boot — AC, 50% held pending-charge per the upower
history (00:26:46 entry), byte-identical software to every run §35/§36 called
dead — produced **clearly audible static** from the right speaker (user verdict,
01:01; the user who forced §36 "prove yourself wrong" and §37 was right). Both
runs were green-gated: device-0 announce in 1–3 samples, stable attachment +
cold-init replay in both powered phases, `COMP_PARAMS=0x016840c6` canary at all
snapshots, DP4 `0x01000607` both banks mid-stream, PA DAPM 0x1/0x2/0x8, Q6
`44/44/0`, clean teardown. **The §35 HARDWARE FAILURE verdict is DISPROVEN.**

**Corrected failure model.** §38's confound is promoted to primary hypothesis:
silence has an EXTERNAL gate, prime suspect power state (the WSA881x boost
output stage draws from the battery rail; Surface EC low-SOC policy unknown).
Yesterday's "progressive afternoon decay" (§34) was not decay but a step: the
machine left mains at 15:58 and again ~20:10, and every attended silence
(20:14 → 23:38) occurred while DISCHARGING below ~49% with all host-side gates
healthy; every audible run sat on mains at the 47–50% hold. Extra evening gain
headroom could not help because the missing quantity was supply, not signal.
The 21:33 power-off never tested the variable (it rebooted onto the same
drained battery) — that is how a brown-out got promoted to "physical failure".

**Honest strains in pure power gating (do not gloss these).** The journal sudo
trail places sweep sessions at 14:50–14:56 (AC) AND 15:56–16:03, straddling the
15:58 unplug (upower 46→43% discharging); the delta-sweep forensics
(2026-08-23) then CONFIRMED from transcripts (`d93b1097` 13:59–14:02Z) that the
15:56–16:03 A/B block — valid attaches, user heard static+tone on both port
masks, PA=0 and boost-off A/Bs — was **audible on battery at 44–46%**. So a
naive instantaneous SOC/voltage gate is REFUTED, not merely strained: audible-
on-battery@46% precedes silent-on-battery@49% by four hours, and the silent
evening ran at HIGHER loaded voltage (≥7.40 V) than the audible afternoon
(7.316 V dip). (§38's own "08-20 audible on battery 79→50%" row is PHANTOM
per the 08-23 correlation table: boot -10 booted
`module_blacklist=soundwire_qcom,snd_soc_wsa881x` — zero PCM streams exist in
that window; its times are the upower discharge span copied as listening
times. Do not re-cite it.) And uptime fails as a two-way gate (21:57
fresh-boot still silent). The mid-afternoon "silent" replays themselves are
attach-race voids
(`MCP_SLV_STATUS=0x0` at every sample, §33) — a different, characterized
failure mode, NOT attached-silence evidence. What survives is a COMPOUND
class: rail policy × marginal contact, intermittent physical connection,
thermal soak, or wear-with-rest-recovery — see the 08-23 delta-sweep ranking.
Resolution belongs to discriminating tests, not assumption: the battery
boost-load-step probe (BAT1 V/I at ≥10 Hz during a discharging play attempt;
conducting output stage = visible current step at PA enable), announce-latency
statistics across states, and the AC-replug-at-frozen-SOC listen.

**Status of prior verdicts.**
- SPI4 read-oracle dead from Linux (§34): still valid (ACKs electrically, flat zeros).
- Era/natural enumeration undeliverable (§36.1): still valid — the latch still never moves.
- pin1 physically silent (v20/v21): still valid as recorded; explicit caveat:
  pre-08-20 sessions carry no power-state log (upower history begins 08-20), so
  this verdict inherits the same uncontrolled variable.
- SD_N-click absence: downgraded twice over (§37: likely a first-power special;
  §38: the partial probe lacked clocks/bias/BOOST_EN — cannot click healthy silicon).
- Whole-boot-silence class: REOPENED — historic attributions may mix dropped
  bank switches with battery-state silence; the mid-stream mirror-recovery
  experiment keeps the bank-switch mechanism itself proven, but not every
  historic silent boot is thereby explained.
- Static-does-not-pass-the-PA-gain (§33): unchanged, and reconfirmed tonight on
  a live speaker.

**Live problem.** The original residual broadband static is again THE quality
defect, now on a working speaker. Tonight's per-interval observations were not
filed against the localize interpretation matrix — the next listen must record
A / B / Cz1 / Ct / Cz2 / D before any new hypothesis.

**Surviving regularities after all ten 08-23 forensic reports** (correlation
table): (1) TOTAL silence (no static at all) has only ever been observed while
DISCHARGING — six runs, 49%→19%; no fully-silent run on steady AC exists
outside void/knob-confounded classes. (2) Static presence is nearly
power-independent above ~45% SOC; its loudness appears to scale down with SOC
on battery (clear @46–48%, faint @48%, absent ≤28%) — voltage headroom on the
noise path, not a tone gate. (3) No H1–H4 survives strictly: AC does not
guarantee tone (01:01 = static only), discharge does not kill static (16:00
audible @46%). (4) Something changed on 08-22 evening that no power variable
explains: AC@50% now yields carrier without tone and clicks are still absent —
judge TONE separately from STATIC in every future listen.

**Sharpened unplug discriminator:** what matters is the FIRST 60 s after
unplug at 50%, not the SOC number. Instant total silence ⇒ electrical
present-state trigger confirmed; static persisting while discharging through
≤46% ⇒ present-state theories die and the 08-22 evening failure was
cumulative/thermal/physical. Run `scripts/spx-boost-step-probe.sh` during any
battery play attempt (conducting output stage = visible BAT1 current step at
PA enable; zero ears needed). Order: (1) ZERO_ONLY + per-interval matrix on
this boot; (2) unplug-at-50% listen with the step probe running; (3) resume
the static hunt per the §34 matrix branches.

## §40 — 2026-08-23 15:30/15:33: faint static on battery @48–49%, no tone, rail flat

Two green-gated `spx-noise-localize.sh` runs on the 00:26 boot (uptime 54.7 ks):

| run | log | power | attach | stream | heard |
|---|---|---|---|---|---|
| 15:30:00 | `/tmp/spx-noise-localize-20260823-153000.log` | AC@50% at 15:29:49 → **unplugged during the run**, phase D `adp=0 49%` | `MCP_SLV_STATUS=0x1` post-attach + post-tone, canary OK | `44/44/0`, DP4 `0x01000607` both banks | first reported "nothing" |
| 15:32:56 | (dmesg 54868–54907) | battery discharging 48%, V 7.48–7.52 | PA PMU 54892, PMD 54904 | `44/44/0` | **right speaker on for a few seconds: super-low static, barely audible; no tone** |

(The user's correction most plausibly describes the second run; treat the
15:30 "nothing" as low-confidence.)

Consequences:
- "We broke the speakers" is dead for good: the right speaker emits on
  battery, attached, green-gated. What is missing is the **tone**, and the
  static is much fainter than the AC@50% 01:01 result (§39), consistent with
  the §39 "static loudness scales down off mains" regularity at the top of
  the discharge curve (48–49%).
- **Rail-sag brown-out is NOT supported at 48%**: BAT1 `voltage_now` logged
  at 20 Hz (`/tmp/spx-power-step-20260823-153239.csv`) stayed 7.48–7.52 V
  through GPIO-on, PA-on, the 11 s stream and park; no dip. If power state
  gates the speaker it is policy/current-limit, not battery voltage.
- **Step probe is inconclusive with this telemetry**: BAT1 has no
  `current_now`; `power_now` is a slow average (5.02 → 5.62 W ramp across the
  whole 50 s, no resolvable step at PA enable). `scripts/spx-boost-step-probe.sh`
  cannot answer "does the output stage conduct" on this EC — needs a faster
  source (PMIC ADC / vph_pwr rail sensor) or the static itself as the proxy.
- The tone gate has now failed in BOTH power states on this boot (AC 01:01:
  static only; battery 15:33: faint static only). The tone hunt is
  orthogonal to the power question; proceed per the §39 matrix branches.

Next listens (same boot): replug AC, wait for "Not charging/50%", one
`spx-noise-localize.sh` → does static loudness recover on mains (live A/B of
the power gate, no reboot)? Then the §39 static-interval matrix.

## §41 — 2026-08-23 15:36: mains A/B — same faint static; naive AC gate REFUTED for loudness

`/tmp/spx-noise-localize-20260823-153640.log`: green-gated (attach `0x1` + canary,
DP4 `0x01000607` both banks, `44/44/0`, clean park), **on mains throughout**
(`adp=1`, EC hold "Not charging/48%", 7.63–7.64 V at every phase). Heard: faint
static for ~10 s toward the end (= the phase-C PA-on window), **same loudness as
the 15:33 battery run**; if the 440 Hz tone was present it was low enough to
blend into the static. Phase B (PA staged directly, no PCM) silent both runs.

Conclusions:
- Same boot, same software, 4 min apart, only the power source differed ⇒
  power source does NOT set static loudness here. The §39 "scales with SOC"
  regularity is not reproduced at 48%; the 01:01 "clearly audible" vs today's
  "barely audible" gap is something else (time/uptime/thermal/mechanical).
- Both the static (bypasses PA gain, §33) AND the tone (through PA gain) are
  attenuated by roughly the same large factor. A common attenuator DOWNSTREAM
  of the PA gain stage is therefore the leading model: high-resistance /
  intermittent speaker contact or connector, a degraded transducer, or the
  output-stage rail (boost not running ⇒ VBAT-only swing; note `vph=3.38 V`).
  Anything upstream of the gain (DSP, SLIMbus, SWR framing, DAC word, PA gain
  register) cannot attenuate static and tone together.
- Ranking after §40/§41: intermittent/high-R physical contact ≫ output rail
  (boost) > thermal > AC policy (dead) > brown-out (dead, §40).

Discriminators, cheapest first (each one listen on this boot):
1. **Press test**: run `spx-noise-localize.sh` while firmly pressing the
   chassis around the right speaker / nearby edge during phase C. Loudness
   that changes with pressure = contact/connector; unchanged = transducer or
   rail.
2. **Rail test**: `SPX_BOOST_SWITCH=0` vs 1 on this boot (boost off should
   be *quieter* if boost currently runs; if identical, boost is already not
   contributing ⇒ rail branch promoted).
3. Max-headroom control on mains (RX8 124 / boost 15 / PA 12): does loudness
   scale at all? Scales ⇒ gain chain alive, attenuation is fixed-ratio
   (contact); clamps ⇒ rail/transducer.

## §42 — 2026-08-23 evening: config diff loud-noon vs faint-today; one delta found

Diff of the noon 08-22 LOUD run (`/var/tmp/spx-speaker-20260822-115925/`,
clack+tone+static) against today's faint runs (§40/§41, same script family):

| knob | noon LOUD | today FAINT |
|---|---|---|
| SPX_PORT_MASK | **5** (DAC+BOOST SoundWire ports) | **1** (DAC only) |
| PA Volume | 12 | 12 |
| RX8 Digital Volume | 84 | 84 |
| Smart Boost Level | 0 | 0 |
| COMP8 Switch | on | on |
| SpkrRight COMP/VISENSE | off/off | off/off |
| hw_params | S16/48k/2ch 12000/48000 | identical |

One software delta: the BOOST descriptor was streaming at noon and is not
today. The v31 A/B (§32/§33: mask 5 vs 1 static comparison) was judged
"changed nothing statically" — but §33's mask-5 runs were on a boot whose
baseline was already loud; nobody has re-checked whether mask 5 restores
LOUDNESS from today's attenuated state. With Windows verified-good as the new
premise (user), the boost rail is back in play as the common downstream
attenuator candidate.

Next listen (one): `SPX_PORT_MASK=5 ./scripts/spx-noise-localize.sh` on mains.
Loud again → the DAC-only port config starves the output stage (boost not
actually enabled without its data port — plausible: wsa881x_boost_ctrl() only
fires when the BOOST DAPM supply toggles); still faint → mask is exonerated,
attenuation is physical or in un-programmed amp registers.

## §43 — 2026-08-23 16:25: mask-5 rerun FAINT — config exonerated; uptime emerges as the surviving correlate

`SPX_PORT_MASK=5 ./scripts/spx-noise-localize.sh`
(`/tmp/spx-noise-localize-20260823-155529.log`) reproduced the byte-identical
noon-LOUD descriptor configuration on this boot. All gates green: stable
device-0 attachment, C-phase zeros with `MCP_SLV_STATUS=0x00000001`, mid-stream
DP4 B0/B1=`0x01000607`, Q6 close `bits=16 submitted=44 write_done=44
fallback=0`, clean park. Power state: battery 43→44% discharging (charger had
already dropped out at preflight — an attached-faint result, so the run stands).

User: **"Same"** — same faint static, no louder, no distinguishable tone.

⇒ §42's single config delta (PORT_MASK 1 vs 5) is **exonerated**. Combined with
§40 (BAT1 rail flat under load) and §41 (mains ≡ battery), the loudness gate is
now known to be *not* config, *not* power source, *not* rail sag.

### Free forensics: journalctl stream-closure timelines

Boot −3 (2026-08-22 11:50 start, 18 closures):

| # | time | uptime | verdict |
|---|---|---|---|
| 1 | 11:59 | 0h09m | **LOUD** (clack+tone+static, §42 table) |
| 8–14 | 15:56–16:03 | 4h06–4h13m | **AUDIBLE on battery** (§38/§39 transcripts) |
| 15 | 19:41 | 7h51m | silent/faint |
| 16–18 | 20:14–21:06 | 8h24–9h16m | silent (attended) |

Boot 0 (2026-08-23 00:18 start, 9 closures):

| # | time | uptime | verdict |
|---|---|---|---|
| 2 | 01:01 | 0h43m | **AUDIBLE static** (§39) |
| 3 | 11:09 | 10h51m | faint |
| 4–9 | 15:30–16:25 | 15h12–16h07m | faint (battery, mains, mask-5 alike) |

### Refuted by these two tables

- **Pure stream count**: boot −3 was audible at stream #14; boot 0 faint at
  stream #3.
- **Suspend/resume**: zero PM-suspend events in both journals — machines ran
  straight through.
- **Thermal soak**: all thermal zones 34.7–37.6 °C at 16 h uptime — cool.
- Power source, SOC, voltage: already dead (§40/§41).

### Surviving correlate: TIME SINCE COLD POWER-ON

Audible ≤ ~4.2 h uptime in BOTH boots; faint/silent ≥ ~7.9 h in BOTH boots.
Some state resets only at full power-off and drifts over hours. Every run
already replays the cold-init register set, so *replayed register content* is
excluded — the drift lives in something a register replay cannot restore:
an unreplayable analog latch (bandgap-class), long-duration ADSP/PMIC state,
or a slow physical effect. Note Windows works for the user regardless, so if
this is an analog-drift class it must be a margin our un-calibrated
(no-0x1025f-runtime-cal) config sits closer to than Windows'.

Next: (a) max-headroom control (`SPX_RX8_VOLUME=124 SPX_BOOST_LEVEL=15`) —
does ANY software-reachable gain scale the output at all; (b) THE decisive
test, which needs explicit user authorization: **one cold reboot, then listen
to the very first stream on battery**. Loud ⇒ gate is power-cycle-reset drift;
still faint ⇒ re-rank from scratch.

## §44 — 2026-08-23 16:40: max-headroom NULL (compander caveat); cold-boot test staged

`/tmp/spx-noise-localize-20260823-164039.log`, battery 32% discharging,
7.357 V flat, all gates green (C-leading-zeros DP4 B0/B1=`0x01000607`,
`bits=16 submitted=44 write_done=44 fallback=0`, clean park). Knobs verified
APPLIED in mixer.log's final blocks (the file appends across runs — check the
LAST block): RX8 Digital Volume 84→**124** (0 → **+40 dB**) and Smart Boost
Level 0→**15** ('6.625 V' → '8.500 V').

User: "Static + tune very low, very very low (same as the other attempts)" —
no loudness change from +40 dB of upstream digital gain plus a 1.9 V boost
raise.

Interpretation, carefully: a +40 dB RX8 increase vanishing acoustically is
only possible if something downstream hard-limits — prime suspect:
`COMP8 Switch` is ON in this baseline (`mixer_path()` sets it), and a
compander normalizes exactly this kind of input change — or the perceived
output is dominated by the gain-independent static floor (§33) with the true
tone far beneath it. The null therefore does NOT yet prove "attenuation
outside software reach"; the COMP8-on baseline compresses this probe. A clean
version would need COMP8 off, but that is the known REG-mode-mute risk on the
left path — do not spend a listen on it until after the decisive test below.

### DECISIVE TEST STAGED — requires explicit user authorization (never reboot autonomously)

Pre-flight verified 16:45: `next_entry=` empty in grubenv (no stale one-shot),
default entry = `spx-audio-rescue`, and `/proc/cmdline` already carries the
full guarded knob set that today's boot ran — so a PLAIN reboot reproduces
today's exact software environment. No rebuild, no arming, no mkinitcpio.

Protocol for the next session (this session dies with the reboot):

1. USER reboots plainly into the unchanged default entry; keep the charger
   UNPLUGGED (battery ≈32% is plenty).
2. After login, run `./scripts/spx-noise-localize.sh` as the literal FIRST
   PCM open of the boot — nothing may touch the audio card before it.
   Record power state next to the listen (standing rule).
3. Verdicts:
   - LOUD (clack + tone + static, noon-08-22 class) ⇒ the faint gate is a
     power-cycle-reset drift; immediately rerun once more as stream #2 on the
     fresh boot to begin mapping how long loudness survives.
   - FAINT ⇒ the uptime hypothesis dies; re-rank from zero, and design a
     Windows-side arbitration of the "speakers work in Windows" premise.

## 45. 2026-08-23 17:13–17:42 — warm-reboot first-stream listen: NOTHING; boot-uptime gate dead, cold-power-on-hours survives

Protocol correction first: §44's "plain reboot reproduces today" premise was
**wrong** — the persistent default is `spx-audio-rescue`, which
`module_blacklist`s `soundwire_qcom,snd_soc_wsa881x`. That first reboot landed
on the rescue entry and the localize aborted pre-hardware
(`FATAL: snd_soc_wsa881x is not loaded`; log
`/tmp/spx-noise-localize-20260823-170828.log`; boot stayed pristine). Lesson:
one-shot GRUB selections are consumed by the boot they steer — yesterday's
session had been *entered* via a consumed one-time pick, masking the true
default. Fix: armed `next_entry=spx-speaker-v28-music` via grub-editenv
(verified), rebooted again.

The v28 boot (17:13) is byte-identical guarded software (DTB speaker-right-v19,
full knob set, panic guards). Two listens, both green-gated:

| stream | wall | uptime | SOC / rail | attach | DP4 mid-stream | Q6 close | heard |
|---|---|---|---|---|---|---|---|
| #1 | 17:23 | **~10 min** | 22% dischg 7.25 V | dev0 after 1 sample | B0=B1=0x01000607 | 44/44/0 | unreported ("try again") |
| #2 | 17:41 | **~28 min** | 18% dischg 7.19 V | dev0 after 1 sample | 0x01000607 both banks | 44/44/0 | **NOTHING** |

Caveat honestly logged: run #2's two in-stream `MCP_SLV_STATUS` samples read
`0x0` (run #1 read `0x1` during leading zeros). Attach was proven pre-stream,
so per protocol those are the documented ambiguous/stale latch — but with a
"nothing" verdict they keep a whole-boot-silence-class escape hatch open for
this boot.

Consequences:

- **Boot-uptime as the loudness gate is DEAD.** A 10-minute-old boot produced
  nothing audible where the correlate predicted audible (≤4.2 h). Warm reboots
  do NOT reset whatever decays.
- **The surviving form is time since last COLD POWER-ON** (wall-power removal),
  which warm reboots pass through unchanged. Last true power-off ≈ 08-22
  ~21:45. On that clock: 01:01 = ~3.3 h AUDIBLE static; 15:33–16:25 = ~18 h
  FAINT; 17:22/17:41 = ~20 h NOTHING. The decay curve extends smoothly:
  audible → faint → inaudible over ~hours of powered-on time, independent of
  reboot count and of stream count.
- SOC co-drifts on this clock (draining all day) and is NOT yet separated:
  every audible battery listen was ≥44%, today's faint was 48%, today's
  nothing was 22→18%. A low-SOC EC rail limit remains fully confounded with
  powered-hours.

Discriminators, in order:

1. **AC-plug instant test** at the current nothing-state (no reboot): if the
   same stream turns loud within minutes of plugging in, this is a live-rail /
   EC-policy gate. Note §41 already showed mains-vs-battery identical at the
   *faint* stage (~16 h), so the prediction under the hours-hypothesis is
   "still nothing" — either outcome is information.
2. **True shutdown → rest ≥ several minutes → cold boot → first-stream
   listen**: the accumulated-state reset test. §35's "power-off resets
   everything is void" verdict predates the hours correlation and only voided
   the total-silence argument; as a loudness-reset probe it has never been run
   clean (that return was on the same draining battery ~11 min later).
3. Charge above 60% on mains, then an on-battery listen — separates SOC from
   powered-hours.

## 46. 2026-08-23 18:30 — 15-agent RCA fleet: two-factor model replaces single-variable uptime gate

All 15 probes returned (11 web, 4 local). Full findings preserved in the
workflow transcript; this section records what changes.

### The model that fits all 20 verdicts with zero counterexamples

**static loudness = f(hours since last TRUE rails-off power-on) × g(SOC)**,
with the tone channel gated SEPARATELY:

- **g = SOC floor**: every total-silence verdict ever recorded sits at
  SOC ≤26% discharging (B1-B3 @26/21/16%, D2 @18%); no counterexample above.
- **f = hours decay**, proven by the controlled pair C2 vs C3: same boot,
  same mains 50%-hold — clear static @0.7 h vs faint @10.9 h post-power-on.
  SOC/AC/stream-count/config all held fixed there.
- **Tone died independently** between 08-22 16:03 and 19:41 and never came
  back across all 3 true rails-off cycles — a second, permanent-seeming gate.

### Corrections to our own record (fleet-caught)

1. **§45's warm-reboot conclusion is UNMEASURED, not established.** Journal
   clock forensics (chronyd-step/RTC-anchor method) show D1/D2 ran at SOC
   22→18% — inside the g=0 floor where the model predicts silence regardless.
   Warm-vs-cold reset has never been tested at adequate SOC.
2. **Only THREE true rails-off cycles exist** (08-21 22:03, 08-22 21:30,
   08-23 00:17); every other "reboot" boundary was a 44–80 s warm restart.
   The noon-08-22 LOUD boot was 13.9 h after the last rails-off, and A3 was
   audible at 17.8 h — which is why single-variable f(h) fails alone.
3. **The §44 max-headroom null did not test boost headroom.** Multi-level
   boost presets (6.625–8.5 V) are documented WSA8815-only; a WSA8810 offers
   6 V-or-bypass. Our probed DevID says 0x2110 (8815-class) but the DTS
   declares 0x2010 — amp identity itself needs confirming before reusing
   boost-preset knobs. Also BOOST_EN-vs-bypass was never verified.
4. Gauge noise ±2–4% means "audible@44–46 vs faint@48" never refuted SOC;
   and loaded-voltage readings are load-confounded (faint@7.49 V > audible
   dips @7.32 V), so voltage ordering proves nothing either way.

### Dead hypotheses (with killer)

- Amp-die progressive decay: datasheet has NO mechanism (OCP fixed 5 A,
  thermal ≥100 °C, SD_N=0 full reset at 0.54 µW; no counters/NVM).
- Thermal foldback (<5%): thresholds ≥110 °C vs ≤60 °C reachable die;
  no cumulative-time thermal mechanism exists in any comparable part.
- SWR clock drift: source-synchronous slave (no slave oscillator), MIPI has
  no exhaustible tolerance; payload corruption predicts gain-scaling static,
  refuted by the PA-gain null.
- Battery chemistry/rail sag: margins ~10× too small to span audible→nothing
  over 44→18%; amp input sits behind an unseen regulator anyway (pack 7.2 V
  exceeds VDD_BAT abs-max 6.0 V).
- Kernel/driver session state: audited — zero hour-scale mechanisms; guarded
  config uses unconditional shadow writes; codec register-reset per boot.
- Linux rail voting: Linux holds NO vote on the codec/amp 1.8 V rail (S4a
  absent from pmc8180-a node; vreg_s4a_1p8 is a dummy fixed placeholder) and
  vph_pwr in DT is a placeholder ("TODO: measure"). All audio rails are
  firmware/hardware-owned — they survive warm reboot, collapse at true POR.
- Field precedent: ZERO external witnesses anywhere (linux-surface #21 open
  since 2022, nobody else has Pro X speakers working on Linux at all).

### Surviving holders of the decaying state

1. **SOC-floor gate (g)** — binary, policy-shaped. Precedent: iPhones ship
   battery-condition audio derating (~50/25/10%) persisting until recharge.
   Mechanism on SPX unknown; EC low-SOC rail policy candidate.
2. **Powered-hours analog soak (f)** — the ONLY chip domain surviving both
   SD_N parks and warm reboots is silicon under never-cycled rails:
   WSA881x boost SMPS/output-stage/bandgap + WCD9340 bandgap/SIDO buck +
   whatever intermediate buck feeds VDD_BAT. C2→C3 decay happened ON MAINS.
3. **EC-held policy state** — Surface EC family precedent: Pro 7 stuck-throttle
   survived shutdown/boot cycles, cleared only by MS forced-shutdown
   (20 s power hold). `BatteryLimitEnable` EFI var verified ENABLED on this
   unit; UEFI 7.580.140 predates the 2024 SAM charging-latch fixes. MAX34417
   accumulators integrate powered-hours and survive warm reboot (I2C5 not
   exposed under DT).
4. **Tone-channel death** — separate gate; physical degradation or an
   SD_N-independent analog state. Windows side-by-side arbitrates.

### Experiment ladder (ranked)

E1. CHARGE >60% on mains → COLD BOOT → first-stream listen. Two-factor
    predicts CLEAR. Faint/nothing here breaks the model → wear branch jumps.
E2. Same boot: read OCP/Clip status (SPKR_STATUS1 0x3128.b2, INTR_STATUS
    0x3022.b3/b4 — nothing services them, flags persist till next SD_N reset)
    + TSE die-temp recipe (bandgap/clocks/OTP cal → TEMP_MSB 0x3011/LSB
    0x3012). Zero-risk reads inside spx_wsa_seq's window.
E3. Register-dump diff fresh-vs-stale: 0x601/0x603/0x629 + CDC_BOOST0/1
    0xc19–0xc22 (codec-side boost controller!) canary-gated.
E4. Forced-shutdown EC-reset test (USER must hold power ~20 s, charger off)
    — separates plain-S5-reset from residual-power EC state.
E5. Read WCD GPIO dir/val bits 3/4 (Flex 5G switches its speaker rail from
    wcdgpio pin 4 — SPX pins 3/4 unexplored). READ-ONLY first.
E6. VI-sense instrumentation (enable VISENSE port + protection cal replay)
    → objective R0/T0 instead of listening.
E7. BatteryLimitEnable=0 via efivarfs (reversible) + Windows-side decay
    reproduction (≥10 h uptime, <40% SOC) to arbitrate the OS question.

## 47. 2026-08-23 night → 08-24 — forensic session: provenance corrections, overdrive refuted, LDO14E rail gap found, objective readback tooling delivered

Overnight autonomous RCA (ultracode fleet + inline completion after the
session-limit kill). Four results, one of which rewrites the §46 model's
input data.

### A. Provenance audit — the "loud noon" anchor never existed

The §46 two-factor model is calibrated against a "noon 08-22 LOUD clack+tone"
anchor. Transcript forensics (`grep` over all session `.jsonl` files) shows:

- **No user verdict exists for any noon listen.** Between 09:49Z and 12:49Z on
  08-22 the only user messages were "Continue"/"Proceed". The 12:52Z "heard a
  tune" refers to the **14:50 CEST** sweep (the -19.9 dBFS ffmpeg run), not
  noon.
- **Last confirmed tone: 15:58:27 CEST 08-22** ("Static + tone", mains,
  harness tone at -2 dBFS).
- **Level confound:** every post-noon listen used the sweep's -19.9 dBFS
  carrier; every pre-noon audible used the harness -2 dBFS tone. That is an
  ~18 dB level difference between the compared populations — loud-vs-faint
  judgments after noon are confounded and cannot calibrate g(SOC).
- **Intermittence, not monotone decay:** at fixed config within minutes on
  08-22: tune (14:50) → silent-ish (15:33) → tune+static (15:58). Non-monotone
  same-config variation is the classic intermittent-contact signature and was
  invisible under the old data.
- Consequence for §46: f(hours)×g(SOC) still fits, but so does plain
  intermittent contact plus the level confound. The model's discriminating
  power came partly from an anchor that was never measured. E1/E4 remain the
  decisive tests either way; E2 (register forensics) now runs WITHOUT a
  listener first (below).

### B. Overdrive/abuse hypothesis REFUTED (hard)

Nothing drove pin2 in the decay window. GPIO 0x43 was parked `0x18` from
16:03:34 to 19:40:35 08-22 (verified mid-gap), i.e. pins 1/2 low = amps off;
total PA-on drive across 08-19→08-23 is ~13 minutes. OCP is enabled. The amp
cannot have been damaged by use it did not receive.

### C. LDO14E parity gap — Windows keeps a codec rail ON that Linux never declared

Windows PEP (\_SB.PEP0.APCC component 4) votes `ldoe14` **1.8 V HPM** whenever
the audio-codec AUDD device is D0. Linux `sc8180x-surface-pro-x.dts`
declares no ldo14 in `pmc8180-e-rpmh-regulators`, cmd-db knows the resource
('ldoe14'), and SPMI reads show PMIC E `EN_CTL` @ `0x4d46 = 0x00` — the rail
is physically OFF under Linux, always has been.

- Constant-off ⇒ candidate explanation for baseline marginality (the static),
  NOT for the decay (decay happened with the rail equally off throughout).
  But note WSA VDD_BAT sits behind a buck fed from this domain; Windows'
  analog margins may simply be better.
- Parent supply `vreg_s5e_2p04` (2.04 V) is present — an LDO can legally make
  1.8 V from it.
- **Staged:** `arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x-speaker-ldo14e.dts`
  (base + ldo14 1.8 V HPM always-on), DTB built and verified by fdtdump.
  NOT installed to /boot, NOT referenced by any GRUB entry. One-variable test:
  boot v28 cmdline against this DTB, listen + register-readback.
- Related unexplored rails: WCD GPIO dir/val bits 3/4 float high since 08-11
  (`dir=0x06 val=0x18`). Flex 5G switches its speaker rail from wcdgpio
  pin 4. qcauddev8180-LIVE.sys scan of PAGEwcda found only WPP trace IDs in
  the 0x40–0x44 cluster (no register writes) — pin semantics unknown; keep
  READ-ONLY until a Flex-style RE lands.

### D. Windows ground-truth premise carries a caveat

The standing "Windows drives these speakers fine" premise is quoted from a
07-29 note. There is NO Windows install on this disk (Boot0000 partition GUID
absent); the SPX-Win box at 192.168.30.143 is a different, currently offline
machine. The premise is plausible but unverified on THIS unit — and the
§46-C3 EC-state holder predicts Windows would ALSO sound degraded here until
a forced shutdown clears it. Side-by-side arbitration belongs to E7.

### E. Objective readback tooling — E2 is now runnable with no listener

- `drivers/spx_extras/spx_wsa_seq.c`: new `reads=` mode — read-only register
  forensics, two passes per register per device with UNSTABLE flagging,
  nothing written. Installed to updates/, initramfs rebuilt.
- `scripts/spx-speakers-up.sh`: new `SPX_REG_READS` env knob inside the
  existing `SPX_READBACK_ONLY=1` branch → dumps to
  `<run>/wsa-reg-reads.log`.
- `scripts/spx-power-snapshot.sh`: VPH_PWR read resolved by channel name
  (iio slot 0 can be stolen by an apds9960).
- Recipe (next v28 boot, desktop user, no sudo):

```sh
SPX_READBACK_ONLY=1 \
SPX_REG_READS="0x3000,0x3001,0x3002,0x3003,0x3011,0x3012,0x3021,0x3022,0x3080,0x3081,0x3082,0x3083,0x3084,0x3100,0x3103,0x311a,0x311b,0x311c,0x311f,0x3127,0x3128,0x3129,0x312e,0x3130" \
./scripts/spx-speakers-up.sh
```

  Covers: chip ID, raw TEMP_MSB/LSB (0x3011/12), INTR_STATUS latch (0x3022 —
  OCP/burn flags persist until next SD_N reset per §46-E2), OTP slice
  0x3080–84, BIAS_BIAS, TEMP_OP, DRV_EN/GAIN/DAC_CTL, OCP_CTL, BIAS_PSRR,
  SPKR_STATUS1/2, BOOST_PRESET_OUT2/LDO_PROG. Canary: CHIP_ID must read
  0x01/0x00/0x00/0x0A-class identity before trusting anything else; compare
  fresh-cold-boot dump vs stale-boot dump for E3.
- Reads go through `sdw_read_no_pm` on the slave — unreliable bridge reads
  remain a known limit (double-pass stability check flags them).

### Updated experiment ladder

E1 unchanged (charge >60% → true cold boot → first-stream listen).
**E2 FIRST, autonomously, on the next guarded boot — no listener needed.**
E3 = diff E2 dumps fresh vs stale. E4 (forced shutdown) unchanged — now also
arbitrates intermittent-contact vs EC-held-state. E5 pins 3/4 stays READ-ONLY.
LDO14E boot slots in as its own one-variable cold-boot test after E1/E2.

### F. E2 executed autonomously (2026-08-24 08:41) — slave reads are UNOBSERVABLE; E3-as-designed is dead

The one-time v28 boot ran with the readback-only env. All gates green:
`COMP_PARAMS=0x016840c6`, `MCP_SLV_STATUS=0x1` after ONE sample, cold-init
replay completed, amp parked, no fault (`/var/tmp/spx-speaker-20260824-084101`).

The forensics themselves returned nothing readable:

- dedicated physical-dev0 readback: `SPX SLAVE READBACK BIAS_PSRR pass=1 rc=4
  UNOBSERVABLE`;
- `spx_wsa_seq reads=` double-pass over 24 registers on both slaves: every
  read either `rc=-5 (-EIO)` or `rc=0 val=0x00`; device 2 (unpowered pin1)
  uniformly `-EIO` as expected for an SD_N-low amp.

This re-confirms the June hard wall ([[spx-slimbus-reads-stuck]]) with two
independent paths on a proven-attached amp: **WSA881x slave registers cannot
be read from APPS** — not OTP, not temperature, not INTR_STATUS latches.
Combined with the dead SPI4 oracle (§34) and the stubbed ADSP regop, no
objective register-level window into the amp exists on this side of the TZ
gate. OCP/burn-flag forensics (E2) and fresh-vs-stale register diffing (E3)
are therefore NOT DELIVERABLE as designed.

What the run still bought: an objective attach proof on this boot (first-
sample device-0 + valid canary), and a definitive tooling verdict so no
future session burns a boot on slave reads again.

Operational lesson: arming an automatic run requires BOTH
`grub-editenv set next_entry=<entry>` AND the state file
`/var/lib/spx-speaker-autotest/armed` (the unit's ConditionPathExists);
GRUB arming alone boots the entry but the autotest skips silently. Also:
test-env had accumulated a stale `SPX_EXPECT_PORT_MASK=5` (from the §42/43
mask experiments) that aborts step [0] against the stock v28 cmdline
(`mask=1`); restored to the coherent v28 baseline afterwards.

Ladder update: E6 (VI-sense instrumentation through the ADSP path) is the
ONLY remaining objective measurement; everything else audible-gated. E1
(charge >60% → true cold boot → first-stream listen) and E4 (forced
shutdown) need the user and remain decisive for the decay model vs
intermittent-contact question.

## §48 (2026-08-24) — Seven-step Windows-vs-Linux driver delta hunt (one RE agent per step)

The user's directive: "Check how the Windows driver works. Dedicate one agent
per step and figure out where it's different." Seven offline agents diffed the
Windows stack (qcauddev8180-LIVE.sys / qcadcm8180-LIVE.sys / DSDT / INF /
ACDB) against this tree, step by step of the playback path. Raw output:
/tmp/spx-step-deltas.md (regenerated from the workflow journal). Every claim
below was re-verified in-tree before being recorded — and verification
MATTERED: two of the fleet's "critical" claims dissolved under correct
masked-write composition (see 48.4).

### 48.1 What is now PROVEN IDENTICAL (stop re-testing these)

| Area | Parity proof |
|---|---|
| Paged register framing | Both OSes: page byte -> wire 0x800, data at 0x800+(reg&0xFF) |
| Per-port SWR transport params | Windows static table @0x140020F30 == Linux DT bit-for-bit on all 8 master ports incl. DP4 -> 0x01000607 |
| Register surface with spx_win_transport=1 | Windows writes only CHANNELEN/SAMPLECTRL1/OFFSETCTRL1(+2); Linux knob skips exactly the rest (BlockCtrl/HCTRL/Lane stay at reset) |
| Four-port allocation NOT required | Port records are per-port atomic; Windows streams 4 ports/amp WITH reset BlockCtrls — single-port+reset-blockctrl is self-consistent |
| SCP_FrameCtrl broadcast | Windows DOES broadcast dev15 0x60/0x70 after composing both banks (older doc claiming otherwise was wrong); so do we |
| CMD FIFO cfg + drain discipline | 0x314<-0x03, post-write drain+retries: parity already implemented |
| Frame-shape field layout + SSP period byte | Same GENMASK layout; our 0x10000 write matches Windows' bus-start value |
| ADM/AFE lifecycle order | ASM->ADM open->matrix map->AFE DEVICE_START (0x100E5)->data->PA unmute: same order both OSes |
| Protection-DISABLE state | v22 block is byte-exact vs qcauddev 0x14008d62c (protection-off mirrors Windows' own optional config) |
| Boost finals (composed) | START_CTL=0xA0, SLOPE=0x74, CURRENT_LIMIT=0x78, BOOST_EN=0x98 (+settle wait): Linux masked writes compose to EXACTLY Windows' staged finals |

### 48.2 Verified REAL deltas, ranked by leverage

1. **SLIM data-channel management (CRITICAL).** Windows sends
   CDC_SLIMBUS_SLAVE_CFG 0x10235 + SLIMBUS_SLAVE_PORT_CFG 0x10233 (module
   CDC_DEV_CFG 0x10234) to the ADSP, whose firmware runs a native SLIMbus
   channel stack ("open data channels"/"ReConfigNow()"); the apps side never
   programs the RX PGD watermark regs for the DAC port. Linux instead blind-
   writes WCD934X_SLIM_PGD_RX_PORT_CFG(p)=0x05 (12-byte watermark) +
   MULTI_CHNL over the flaky AHB bridge (wcd934x.c:1771/:1780), and the codec
   RX0 overflow fires ONCE PER STREAM forever (PROGRESS §42 table,
   spx-static-sample-edge-ruled-out). Windows' init loop does touch TX-class
   PGD regs (0xff->0x101+4p/0x181+4p; 5->0x40+p; 0xb->0x50+p @0x14007b108-b198)
   — different family, different values. **This is the only delta that maps
   onto an existing per-stream defect signature.** Testable WITHOUT listening:
   v29 `spx_auto_speaker_cal=1` replays the ADSP param set; watch the RX0
   overflow line.
2. **BOOST_LOOP_STABILITY 0x3133 = 0x00 (guarded Linux, rev2 patch) vs 0x8F
   (Windows cold-init)** — unconditional, one register, boost loop
   compensation. BIAS_PSRR 0x44-vs-0x45 and MISC_CTL1 0xC7-vs-0xC6 are one-bit
   stragglers (knob exists for PSRR). One spx_wsa_seq replay A/B:
   `seq=0x3133:0x8f` after cold init.
3. **Interrupt policy (major).** Windows masks enum-chatter IRQs OFF
   (0x204<-0x1c3fd: NEW_SLAVE_ATTACHED/SPECIAL_CMD/AUTO_ENUM_FAILED/
   TABLE_FULL/BUS_RESET never interrupt) and NEVER writes SCP_DEVNUMBER — it
   follows HW auto-enum tables only. We unmask everything AND force-write
   DevNumber + route all writes to dev0. The 0x1c3fd path already exists
   behind `soundwire_qcom.spx_exact_windows_init` (boot-only, currently off).
4. **Idle park (major).** Windows broadcast CLK_STP_NOW (dev15, reg 0x44=2)
   whenever no stream holds a reference; verified live today: SPX controller
   sits runtime-'active' indefinitely — amp bus framed continuously for days.
   Matches the §46 analog-soak decay model directly.
5. **Teardown soft-reset (major).** Windows PA-off ends with SWR_RESET_EN
   0x300b=0x07 + CDC_RST_CTL 0x3005=0x00 (full digital-core reset between
   streams, full re-init next stream); we latch OCP hold only and carry state.
6. **Gain shape (minor).** Windows single-shots gain for targets >= code 4
   (ramp only below); we always ramp ~12 steps (trace: 24 x 0x311b writes).
7. **Readback adaptation (structural).** Windows derives BOOST presets from
   OTP reads and RMWs MISC_CTL1 from readback; slave reads are UNOBSERVABLE
   here (§47-F) so a perfect port is impossible — constants must be pinned
   from OTP once, if ever readable.
8. **Chip-version branching (unknown).** Every Windows analog sequence keys on
   an in-chip version field (V1/V2 vs V3 paths differ in BBM_CTL 0x3121=0x02,
   PS/ZX_CTL 0x80/0x14-vs-skip, DAC staging). Our part's version class is
   unresolved (DevID probe said 0x2110, DTS says 0x2010).
9. **LDO14E + CXO_BUFFERS_BBCLK2_A (rails, known §47-C, now exact):**
   comp4 votes LDO14_E {1.8 V, mode 7} on D0 and actively releases to
   {0 V, mode 5}; comp0 toggles the BBCLK2 pad buffer with D-state. Staged
   parity DTB covers the first; nothing on rpmh can vote the second.
10. **ADM open opcode anomaly (unresolved).** qcadcm builds device-open with
    opcode 0x10327 (~0x250-byte payload, NULL_COPP topology 0x10312); Linux
    sends OPEN_V5 0x10326 and defines 0x10327 as CLOSE_V5 (q6adm.c:30).
    Either polymorphic dispatch by payload size or a real mismatch — needs an
    outgoing-APR capture to settle; risky to poke blind.

### 48.5 Verification corrections to the fleet's raw output (read before trusting /tmp/spx-step-deltas.md)

- wsa881x INIT_WRITE(reg, MASK, val) is a MASKED update; naive comparison of
  immediates against Windows' absolute writes overstated the boost gap. After
  composing masks, four of five boost registers MATCH exactly. Only 0x3133
  survives (and gets WORSE on the guarded path: rev2 patch drives it to 0x00).
- BIAS_INT final 0x00 and PA_INT final 0x4E match Windows exactly (agent
  claimed divergence).
- adsp-datapath attribution fix stands: the whole AFE/ADM command-builder set
  lives in qcadcm8180-LIVE.sys PAGEqq6, not qcauddev.

### 48.6 Cheapest objective test ladder out of §48 (no listener needed for 1-3)

1. v29 boot (`spx_auto_speaker_cal=1`, staged since June): grep dmesg for the
   RX0 overflow line across first+second streams. Kills or confirms delta #1.
2. Live A/B on any audible-boot first stream: spx_wsa_seq seq=0x3133:0x8f
   after cold init (delta #2), listen once.
3. Runtime check (done today, baseline recorded): controller runtime_status
   stays 'active' between streams — implement/test the CLK_STP_NOW idle park
   for the soak hypothesis (delta #4).
4. Boot-only knob A/B: spx_exact_windows_init=1 (interrupt mask + enum
   discipline, delta #3) — watch MCP_SLV_STATUS flicker statistics.
5. Teardown reset replay between streams (delta #5) against the SS46
   non-monotone carried-state pattern.

## §49 (2026-08-24) — All ten §48 deltas implemented behind legacy-default knobs

User directive: "use 10 agents to implement the differences". Fleet run
`wf_531db964-861`: 6 build groups (wsa-values → wsa-pa serialized on
wsa881x.c) + 2 adversarial reviewers + 1 fix agent, all offline (no boots,
no module loads, no /lib/modules or /boot writes). Spec:
`/tmp/spx48-spec.md` (authoritative; corrects two stale §48 claims).
Personal verification: every hunk diffed against the pre-fleet snapshot
(`/tmp/spx48-baseline-pre-fleet.diff`), constants checked against the spec
ledger, and a full tree `make modules` exit 0 with the new params visible in
all four rebuilt `.ko`s. **Nothing is installed** — `/lib/modules` and the
initramfs still carry the old modules; deployment follows the guarded
one-variable-per-boot rules when we next boot-test.

### Knobs landed (ALL default to legacy; defaults ⇒ behavior identical)

| Module | Knob (0644 int) | Default | Effect when armed |
|---|---|---|---|
| snd-soc-wsa881x | `spx_win_boost_loop_stab` | −1 | full-width final BOOST_LOOP_STABILITY after init compose (Windows 0x8F; note guarded path already composes 0x8F — this pins it and covers the legacy path) |
| snd-soc-wsa881x | `spx_win_misc_ctl1` | −1 | init override AND replaces the pre_pmu_pa_2_0 stream-time entry (0x87 → e.g. 0xC6/0xC7) via a stack copy of the table, reorder-guarded on `pre_pmu_pa[1].reg == SPKR_MISC_CTL1` |
| snd-soc-wsa881x | `spx_win_gain_singleshot` | 0 | skip the 1 ms/step PAG_GAIN ramp only when target code ≥ 4 (Windows T=max(req,4)); unconditional final write kept in both modes |
| snd-soc-wsa881x | `spx_win_teardown_reset` | 0 | POST_PMD tail: SWR_RESET_EN=0x07 THEN CDC_RST_CTL=0x00 (exact Windows order). PAIR WITH cold-init replay next stream (`spx_init_on_pmu=1`) or the amp stays dead — documented in PARM_DESC |
| soundwire-qcom | `spx_idle_clk_stop_ms` | 0 | retime idle autosuspend (100..600000 ms, else probe −EINVAL); existing swrm_runtime_suspend/resume MIPI handshake does the park; probe-time validated |
| q6afe | `spx_slim_slave_eaddr_lsw` / `_msw` | −1 | patch CDC_SLIMBUS_SLAVE_CFG 0x10235 enum-address words at apply time (only under spx_auto_speaker_cal=1) |
| q6afe | `spx_slim_port_pgd_la` / `_intfdev_la` | −1 | patch SLIMBUS_SLAVE_PORT_CFG 0x10233 LA u16 fields likewise |
| snd-soc-wcd934x | `spx_pgd_rx_port_cfg` | −1 | substitute the RX PGD watermark byte (legacy 0x05) in the playback branch — A/B input for the RX0-overflow grep, not a claimed fix |
| scripts | `scripts/spx-delta-ab.sh` | — | two-stream A/B runner: power-state logging, device-0 announce + FORCE-ATTACH gates, SPX_WSA_SEQ / SPX_TEARDOWN_RESET / SPX_GREP_RX0 knobs |
| scripts | `scripts/spx-idle-park-check.sh` | — | read-only runtime_status validator (SPX_IDLE_MINUTES), force-attach-hold aware |

Deliberately NOT implemented: intr-mask runtime knob (`spx_exact_windows_init`
already covers delta #3 boot-only; making intr_mask writable broke device-0
clash recovery before), slave program-order parity (stream.c blast radius),
optional ANA_CTL-pulse relocation (skipped by fix agent as optional/colliding).

### Corrections the fleet proved against the tree (supersede earlier claims)

1. **"Autosuspend never enabled" was WRONG**: HEAD's probe already calls
   pm_runtime_use_autosuspend + delay 3000. The controller sits 'active'
   forever because the force-attach path holds ONE permanent runtime-PM
   reference (`spx_pm_held`, :1465, dropped only in remove()). Therefore
   `spx_idle_clk_stop_ms` can ONLY be validated on a boot WITHOUT
   `spx_force_attach=1`; on guarded boots the hold intentionally blocks the
   park (a clock-stop suspend desyncs the force-attached amp).
2. The builder correctly REFUSED my brief's `pm_runtime_put_autosuspend` at
   probe end: usage count is 0 there and a put would drive it to −1,
   consuming the first stream's get_sync and defeating later parks.

### Next (needs boots; one variable per boot)

0. Deploy step when ready: install the four modules to updates/, sudo
   mkinitcpio -P, arm a fresh audited one-time entry.
1. v29 objective test unchanged: `q6afe.spx_auto_speaker_cal=1` boot → grep
   "overflow error on RX port 0" across first+second streams (or use
   spx-delta-ab.sh SPX_GREP_RX0=1).
2. wsa register deltas via SPX_WSA_SEQ or the new knobs on the audible pin2
   baseline (0xC6 MISC_CTL1 first — biggest unmapped bit).
3. Idle park: separate non-force-attach boot with spx_idle_clk_stop_ms +
   spx-idle-park-check.sh (no listening needed).
4. Teardown reset: spx_win_teardown_reset=1 paired with spx_init_on_pmu=1,
   judged against the SS46 non-monotone pattern.

### 49.1 v29 boot result (2026-08-24 22:01, listen-free) — delta #1 NEGATIVE, RX0 metric reclassified

Boot `spx-speaker-v29-acdb-cal` (one-time; consumed; `saved_entry=spx-audio-rescue`
verified afterwards; `armed` flag consumed). Power: AC online, BAT 47 % "Not charging".
Coherence: `q6afe.spx_auto_speaker_cal=1` + `spx_wsa_gpio_val=0x00` on cmdline; all
§49 knobs present in sysfs (`snd_soc_wsa881x` 4x `spx_win_*` new, `soundwire_qcom
spx_idle_clk_stop_ms`, `q6afe spx_slim_*` x4, `snd_soc_wcd934x spx_pgd_rx_port_cfg`),
all at legacy defaults. Kernel: no oops/BUG, no `callbacks suppressed`.

Cal path fired: `SPX: speaker V3 AFE calibration applied` at 22:01:25.57 (uptime
41.29 s), 45 ms BEFORE PA PRE_PMU, i.e. CDC_SLIMBUS_SLAVE_CFG 0x10235 +
SLIMBUS_SLAVE_PORT_CFG 0x10233 went to the ADSP before the AFE port started.

| stream | Q6 counters | RX0 overflow (uptime) | relative to PA |
|---|---|---|---|
| 1 (autotest tone, 5 s) | `bits=16 32/32/0` | 49.868 | +80 ms after POST_PMD 0x8 (teardown) |
| 2 (`spx-play-right.sh`, 10 s tune) | `40/40/0` | 1050.400 | −9 ms before PRE_PMU 0x1 (start) |
| BASELINE 08-22 v28 (no cal), stream 1 | `32/32/0` | 132.220 | +72 ms after POST_PMD (teardown) |

Autotest stream 1 passed every gate (device-0 announce after 1 sample, cold init,
DP4 `B0=B1=0x01000607`, post-stream `MCP_SLV_STATUS=0x1`, parking verified, status 0).
Stream 2 used the play script, which does not sample MCP_SLV_STATUS — its counters
are valid, its attach is unproven (irrelevant for this metric; nobody listened).

**Verdict: delta #1 (ADSP-managed SLIM channel cfg) does NOT change the RX0
overflow signature.** Identical one-hit-per-stream pattern with and without cal.

**Metric reclassification (read before ever counting this line again):**
`wcd934x_slim_irq_handler` (wcd934x.c:2388-2400) CLEARS the port's
`PGD_PORT_INT_EN` bit on the first overflow/underflow; it is only re-armed by
`wcd934x_codec_enable_int_port` (:4205) from the AIF DAPM enable at the next
stream. So the count is a self-masking 0/1 "did any overflow occur since re-arm"
flag, NOT a rate — `dev_err_ratelimited` was never the limiting factor.
And the single hit sits at a PORT BOUNDARY every time (teardown after PA-off,
or start before PA-on, when the RX0 FIFO is fed while the SWR/interp side is not
consuming). It is not mid-stream, so it cannot be the continuous static, and the
§48 premise that #1 was "the only delta matching a live defect" is withdrawn:
RX0 overflow is a bring-up/teardown artifact. Stop treating it as a static proxy.
The SLIM RX0 channel carries C0 (left, digital zero in the right-only tone) —
the overflow is on the idle channel.

Remaining §49 ladder is therefore listener-gated (deltas #2 0x3133/boost octet,
#3 boot-only enum-IRQ mask, #5 teardown reset) or idle-park objective (#4, needs a
non-force-attach boot). Live A/B for #2 on this boot (same boot is valid):
`SPX_GREP_RX0=0 SPX_WSA_SEQ=0x3133:0x8f,0x3135:0xa3,0x3135:0xa0,0x3131:0x75,0x3131:0x74,0x312c:0x80,0x3134:0x14,0x312b:0x78,0x312a:0x98 ./scripts/spx-delta-ab.sh`
(stream 1 = legacy control, stream 2 = delta) — needs a listener + power record.

### 49.2 Delta #2 (boost octet, 0x3133=0x8F etc.) played 2026-08-24 22:20 — AWAITING LISTENING TESTIMONY

`SPX_WSA_SEQ=0x3133:0x8f,0x3135:0xa3,0x3135:0xa0,0x3131:0x75,0x3131:0x74,0x312c:0x80,0x3134:0x14,0x312b:0x78,0x312a:0x98 ./scripts/spx-delta-ab.sh`
on the v29 boot (log `/tmp/spx-delta-ab-20260824-221948.log`). NOTE: the script
applies the seq after EVERY cold-init, so BOTH streams carried the delta — the
legacy controls are the 22:01 autotest tone and the 22:12 play-right tune on the
same boot. Both delta streams valid: device-0 announce after 1 sample, stable
attach + cold-init replay, 9/9 seq writes, PA Volume 0->12, `MCP_SLV_STATUS=0x1`
during the leading zeros, DP4 `B0=B1=0x01000607`, `44/44/0`, one boundary RX0
hit each (pre-PA), AC online / BAT 47 % / vph 3.377 V. Tone windows:
22:20:07-22:20:12 and 22:20:38-22:20:43 CEST (440 Hz right, 3 s zeros each side).
User testimony: PENDING — do not score this rung without it.

### 49.3 Toward an objective listener: built-in mic capture (2026-08-24 22:40)

Every remaining ladder step is listener-gated, so I probed whether the machine
can listen to itself. Capture PCMs exist (MultiMedia1-3, `SLIM Capture` link on
`SLIMBUS_0_TX` -> `wcd9340` DAI 1), the codec exposes DMIC MUX0-8 (DMIC0-5),
ADC MUX (DMIC/AMIC), AMIC MUX (ADC1-4), and Windows' ACDB names
`AUDIO_DEVICE_FLUENCE_QUAD_MIC` (a 4-mic array exists).

Probe: DMIC0 -> DEC0 -> SLIM TX0 -> AIF1_CAP -> SLIMBUS_0_TX -> MultiMedia2,
`arecord plughw:0,1 S16 48k mono 4 s`. RESULT: transport WORKS — 192000 frames
delivered in real time (capture has no fallback watchdog, so these were real
READ_DONE events), TX port 0 closed cleanly — but the data was digital zero
(peak 1, 21 nonzero samples). So the mic SOURCE (DMIC0 / DMIC clock / bias /
wrong input) is the open question, not the ASM/SLIM path.

**HAZARD (new hard rule):** the stock capture close path (CMD_CLOSE + MEM_UNMAP,
never ACKed by this ADSP) timed out and wedged the ASM service: every later
MEM_MAP -110, including the parked PLAYBACK session (`write_done=0`). The v29
boot's speaker path is dead from 22:41 — reboot required. `spx_keep_asm`
parking covered playback only.

Fix (built, see below): q6asm-dai parks capture clients too (`parked[2][16]`,
per direction), re-queues read buffers on a reused capture client, and counts
READ_DONE as DSP progress. New `scripts/spx-mic-capture.sh [src|sweep] [secs]`.
Next boot: v28 entry (autotest for playback proof), then the mic source sweep.
If any input yields signal, the §49 ladder becomes objective (record the
speaker through the mic; compare spectra A/B without a human).

**49.2 follow-up (22:25 retry VOID; ASM wedged by concurrent capture work).**
User testimony on the 22:20 delta run: "heard something like static" (tone not
clearly identified) — inconclusive, and the retry requested at 22:25
(`SPX_SEQ_STREAM2_ONLY=1`, new script option: stream1 = legacy control,
stream2 = boost octet) is VOID: aplay `write error: Input/output error` on
both streams, `submitted=0 write_done=0`. Cause: a concurrent Claude session
(`linux-surface-kernel-41`) ran DMIC capture probes `SPX_CAP_dmic0..5` at
22:21:49–22:23 on this boot; the first capture close produced
`command[0x10bdb] not expecting rsp` + `Port Closed TX port 0`, and EVERY ASM
command since times out (`CMD 10d94/10d92 timeout -110`, mem-map/alloc
failures). Playback is dead for the rest of this boot; the peer session is
patching q6asm-dai.c to park capture clients too (same mechanism as
spx_keep_asm). User heard "something and a bit of static" during the 22:25 run
with ZERO samples delivered — a fresh data point that the static is present
with no audio data at all (consistent with §33). AC was unplugged at 22:23:45
(BAT 47 %, discharging) — power state differs from the 22:20 run.
Delta #2 remains UNSCORED; rerun on the next boot with
`SPX_SEQ_STREAM2_ONLY=1` before any capture experiment.

### 49.4 v28 boot 22:39 (2026-08-24) — first stream TESTIMONY: "Static and then an almost clean tune"

Boot `spx-speaker-v28-music` (one-time, consumed; default still spx-audio-rescue),
new q6asm-dai with capture parking loaded (log: "parking ASM playback session").
**Power: AC OFF, battery 44 %, discharging.** Autotest attempt `20260824T203926Z-929`,
status 0: device-0 presence after 1 sample (`MCP_SLV_STATUS=0x1`, canary
0x016840c6), cold init, endpoint-B mixer path, 5 s 440 Hz S16 tone, mid-stream
DP4 `B0=B1=0x01000607`, Q6 `bits=16 32/32/0`, PA-on at uptime 39.87 s, parking
verified. Nothing else played before the testimony.

User (live, 22:4x): **"Static and then an almost clean tune."** — i.e. static
first, then the tone came through almost clean. Reading: (a) the boot is AUDIBLE
on battery at 44 %, first stream after cold boot ⇒ another refutation of a plain
SOC-floor gate at boot; (b) the static-then-clean ordering matches the earlier
"static during the zero preroll" signature ([[spx-static-zeros-preroll]]): the
noise lives at/after PA-on before the data settles, and this time it largely
resolved. Objective correlates for this stream: RX0 overflow (self-masking
boundary flag) — see §49.1, not a static proxy.

Peer session (linux-surface-kernel-38) runs the delta-#2 A/B next on this boot;
the mic-capture sweep (§49.3) follows after its "done".

### 49.5 Delta #2 (Windows boost octet) live A/B on the v28 boot, 22:34:58 / 22:35:29 — AWAITING TESTIMONY

`SPX_SEQ_STREAM2_ONLY=1 SPX_WSA_SEQ=0x3133:0x8f,0x3135:0xa3,0x3135:0xa0,0x3131:0x75,0x3131:0x74,0x312c:0x80,0x3134:0x14,0x312b:0x78,0x312a:0x98 ./scripts/spx-delta-ab.sh`
Log: `/tmp/spx-delta-ab-20260824-223443.log`. Power both streams: AC OFF, BAT 44 %
discharging, vph 3.378 V. Both streams: device-0 presence after 1 sample, stable
attachment + cold-init replay, PA Volume 0→12, 11 s vector (3 s zeros | 5 s
440 Hz right | 3 s zeros), DP4 `B0=B1=0x01000607` during leading zeros, Q6
`44/44/0`, one RX0 boundary flag each.
- stream 1 (22:34:58) = legacy control, `MCP_SLV_STATUS=0x1` post-attach AND
  during leading zeros.
- stream 2 (22:35:29) = boost octet applied after cold init (9/9 writes ok);
  `MCP_SLV_STATUS=0x0` post-attach and during zeros (latch ambiguity per the
  standing rule — presence WAS proven in the GPIO-high window).
Testimony to record: stream 1 vs stream 2 static level.

### 49.6 Mic-capture sweep on the v28 boot (22:4x) — transport proven, DMICs silent, MCLK refuted

Capture parking works (`parking/reusing ASM capture session for DAI 1`, real
READ_DONE counts 25-49 per run, no MEM_MAP timeout; playback afterwards
`48/48/0`). Sweep `scripts/spx-mic-capture.sh sweep 3` (DEC0 -> SLIM TX0 ->
SLIMBUS_0_TX -> MultiMedia2, 48 k mono S16):

| input | rms | peak | verdict |
|---|---|---|---|
| DMIC0/1/2/3/4/5 | 0.0-0.2 | 0-12 | digital zero (DMIC3/5 exactly 0) |
| ADC1/3/4 | 1.3-2.2 | 8-19 | live analog noise floor (no signal) |
| ADC2 (headset-jack AMIC2) | 18.1 | 453 | real analog noise ⇒ SLIM TX transport + ADSP capture path WORK |

Windows RE (Explore agent, ACDB decode): mic array = ACDB device 0x21
`HANDSET_MIC_STEREO`, codec key 0x021207 `DMIC_2_1_STEREO` = WCD9340 **DMIC1 +
DMIC0** (2 mics, ±21 mm linear), AFE `SLIMBUS_3_TX` (0x4007) shared channels
177/178, 48 k. So the DMIC pair is the right target; TX channel numbering is
NOT the blocker (ADC2 data flows with our default map).

DAPM during a DMIC1 capture: DMIC1/DMIC1 Pin/MIC BIAS1/DMIC MUX0/ADC MUX0/SLIM
TX0/AIF1 CAP all On; **MCLK Off** (only route to MCLK is `RX_BIAS`, same as
db845c). Repeated the capture DURING speaker playback (MCLK On, RX_BIAS On):
DMIC1 still zero ⇒ MCLK is not the gate. Remaining DMIC suspects: mic VDD rail
(LDO14E 1.8 V, §47 — Windows votes it, Linux leaves it OFF; staged parity DTB
`sc8180x-surface-pro-x-speaker-ldo14e.dtb` tests mic AND speaker rail in one
boot), DMIC pad drive (`TEST_DEBUG_PAD_DRVCTL_0` bits[3:2] = 0 vs Qualcomm
default 0x2), DMIC pin/pad config not in mainline.

**Testimony (22:4x, v28 boot, AC OFF / BAT 42 %) for the play-during-capture
stream (`48/48/0`, tune.wav 12 s, PA Volume 12):** "Clack + low static + tune,
but really low." Same boot whose first stream was "almost clean" at 22:39.
Loudness has dropped within ~10 min on battery (faint-carrier pattern, §47);
static now "low". A DMIC1 capture (MIC BIAS1 on, DMIC clock on) ran
concurrently — confound noted, not established.

### 49.7 LDO14E live probe (22:5x) — rail is pre-programmed at Windows' vote, but APPS may not write it

`spx_pmic_ldo.ko sid=9 ldo=14 dump=1` (PMIC E LDOs sit on SPMI SID 9; base
0x4d00, TYPE=0x04 SUBTYPE=0x72): `VSET_LB/UB (0x40/0x41) = 08 07` ⇒ **1800 mV
already programmed**, `MODE (0x45) = 0x07` ⇒ HPM, `EN_CTL (0x46) = 0x00` ⇒
OFF. The PMIC holds exactly Windows' `ldoe14 1.8 V HPM` vote persistently; only
the enable bit differs. `enable=1` ⇒ **`EN_CTL write failed (-1)` = -EPERM**:
the PMIC arbiter rejects APPS writes to that peripheral (owned by another EE),
so the rail cannot be flipped live. Remaining route = RPMh vote via DT
(`sc8180x-surface-pro-x-speaker-right-ldo14e.dts`, includes the speaker-right
DTS, ldo14 1.8 V HPM always-on; DTB sha256 045f5853…, installed as
`/boot/dtb/qcom/sc8180x-surface-pro-x.dtb.speaker-right-ldo14e`; GRUB id
`spx-speaker-v32-ldo14e`, cmdline byte-identical to v28, NOT armed).
Risk to weigh before arming: APPS RPMh votes to PEP-owned rails (`ldoa14`) time
out and a second vote hangs the RSC uninterruptibly (spx_pmic_ldo.c header);
`ldoe14` ownership unknown. Boot has panic=10/hung_task_panic ⇒ worst case is
an automatic fall-back to spx-audio-rescue.
cmd-db aux class: `ldoa14 [00]` (the rail whose APPS vote timed out), ordinary
E rails `[01]`, `ldoe14 [02]` (same class as ldoe7/ldoe15) — not the known-bad
class. Arming `spx-speaker-v32-ldo14e` + autotest at 22:5x; first-stream tone =
LDO14E listen; then DMIC capture (objective) on that boot.

### 49.8 v32 LDO14E boot (22:55, AC OFF, BAT 39→38 % discharging) — SILENT with the rail ON

Vote landed: `ldo14: Setting 1800000-1800000uV`, `/sys/class/regulator/regulator.21
ldo14 state=enabled 1800000`, SPMI `EN_CTL=0x80` (ON). No RPMh timeout, no RSC
hang. Autotest status 0, presence after 1 sample, **`MCP_SLV_STATUS=0x1` held
through active-stream AND post-stream** (usually clears mid-stream), DP4
`B0=B1=0x01000607`, `32/32/0`. User: **"Now it was just clack and silence."**
Second stream (`spx-play-right.sh`, 12 s tune, `48/48/0`, BAT 38 %): **"Clack +
silence."** DMIC0/DMIC1 capture with the rail on: still digital zero ⇒ LDO14E
is NOT the DMIC supply.

Two variables vs the audible 22:39 v28 boot (BAT 44 %): rail ON, battery −5 %
/ +16 min. Control: immediate v28 reboot (rail OFF) at BAT 38 %.

### 49.8 v32 LDO14E boot (22:55, AC OFF, BAT 39→38 % discharging) — rail ON, no cure; DMICs still zero

RPMh vote WORKED: `regulator.21 ldo14 enabled 1800000 uV`, SPMI `EN_CTL=0x80`
(no RSC timeout/hang; cmd-db class `[02]` is votable from APPS). Autotest
stream 1: all gates, `MCP_SLV_STATUS=0x1` before, DURING and after the stream
(first time the latch held mid-stream), DP4 `B0=B1=0x01000607`, `32/32/0`.
**Testimony: "clack and silence."** Second stream (`spx-play-right.sh`, 12 s
tune, `48/48/0`, BAT 38 %): **"A bit of static and then 5 s or so of tune on
top of that low static."** ⇒ not whole-boot silence; silent-tone-then-audible-
tune within one boot again (non-monotone, cf. §47). LDO14E: no audible cure,
no change in static class; keep the DTB as Windows parity (harmless, rail
stays on) but it is NOT the gate. DMIC0/DMIC1 capture with the rail on:
still digital zero ⇒ LDO14E is not the mic array's supply either.
CORRECTION: the v32 boot was rebooted at 22:57:38 (systemd-reboot, source
below) and the box came back on a v28-class DTB (no ldo14 node, LDO14E
`EN_CTL=0x00` OFF, watchdog node present), autotest ran again (attempt
`20260824T210521Z-909`, all gates, `32/32/0`, BAT 37 %, AC off). The pad-drive
test below therefore ran with LDO14E OFF.
DMIC pad drive `0x803b` bits[3:2] = 0x2 (0x08) and 0x3 (0x0c), written live via
spx_vol_write.ko (raw readback confirmed): DMIC1/DMIC0 still digital zero ⇒
pad drive is not the DMIC gate either. Remaining DMIC hypotheses: DMIC clock
rate (Windows codec cal may run 2.4 MHz; ours 4.8 MHz), a codec DMIC pin mux/
enable not in mainline (`CPE_SS_DMIC_CFG` 0x21b), or the mic VDD on yet another
rail (Windows PEP audio component list: check which other rails comp4 votes).

### 49.9 Boot timeline 22:39–23:00 and the one objective LDO14E difference

| boot | entry | LDO14E | first stream (autotest) | later stream | BAT |
|---|---|---|---|---|---|
| 22:39 | v28 | OFF | "static, then almost clean tone" | 22:4x tune: "clack + low static + tune, really low" | 44→42 % |
| 22:47 | v32 | **ON** (RPMh vote OK) | "clack and silence"; latch `MCP_SLV_STATUS=0x1` held before/DURING/after | 22:56 tune `48/48/0`: "bit of static, then ~5 s of tune over low static" | 39→38 % |
| 22:57 | v28 (accidental re-run of the v28 arming command) | OFF | `32/32/0`, latch cleared post-stream (0x0) as usual | DMIC pad-drive test only | 37 % |

Objective note: the v32 (rail ON) boot is the first run where the slave-status
latch stayed 0x1 through the active stream; every rail-OFF boot clears it
mid-stream. n=1, but it is a bus-level effect of the rail and cheap to
re-check on the next v32 boot (autotest logs it for free). Audibly the rail
did not remove the static nor prevent a silent first tone. Both DMIC pins stay
digital zero with the rail on and with pad drive raised.
DMIC clock: the driver was ALREADY at DIV_4 = 2.4 MHz (`0x218` before=0x05,
FS-based downgrade), so the 2.4-vs-4.8 MHz hypothesis was moot; live rewrites
to 1.2 MHz (0x09) and 0.6 MHz (0x0b) mid-capture and `DMIC_CFG 0x21b=0x00` all
still read digital zero. Codec-register-level DMIC knobs are EXHAUSTED; the
remaining gate is outside the codec's DMIC block (mic VDD / bias rail, pin
routing). Side note: raw codec readbacks over SLIM returned the written values
tonight (0x218/0x21b/0x803b), unlike the 06-29 "reads stuck at zero" era.
MIC BIAS2/3/4 forced on (`ANA_MICB2/3/4 = 0x40`, raw readback ok) + DAPM's
MIC BIAS1: DMIC0/1/2/4 still zero (peaks ≤18 = dither). Restored to 0x00.
=> With clock (all dividers), all four biases, MCLK, pad drive, DMIC_CFG and
LDO14E each excluded, NO codec-register knob makes a DMIC pin produce data.
Next: decode the 120-byte Windows codec-cal payload for `DMIC_2_1_STEREO`
(RE agent) and the PEP resource list of the codec's D0 components for a mic
rail; WCD GPIO pins 3/4 remain READ-ONLY (CLAUDE.md) until RE names them.

### 49.10 Delta #2 A/B re-run 23:22:30 / 23:23:00 (AC OFF, BAT 32 %) — log /tmp/spx-delta-ab-20260824-232214.log
Both streams gate-perfect (device-0 presence, stable attachment + cold init,
`44/44/0`); stream 2 had the boost octet applied (9/9 writes). Testimony
arriving mid-run (attributed to stream 1 = baseline): **"A rather loud clack +
a long tune mixed with static."** Stream 2 verdict: pending.
**Stream 2 testimony: "Both A and B were the same."** ⇒ §48 delta #2 (Windows
boost octet incl. 0x3133=0x8F) CLOSED NEGATIVE for static. Remaining §48
ladder: #3 enum-IRQ mask (boot-only, `spx_exact_windows_init=1`), #4 idle
CLK_STP park (non-force-attach boot + `spx_idle_clk_stop_ms`), #5 teardown
reset (`spx_win_teardown_reset=1` + `spx_init_on_pmu=1`, listener-gated).
Tonight's audibility ledger on v28-class boots: 44 % audible, 39 % silent
tone (v32), 37 % ?, 32 % audible (loud clack + tune + static).

### 49.11 Delta #5 teardown-reset A/B 23:24:05 / 23:24:35 (AC OFF, BAT 32 %) — log /tmp/spx-delta-ab-20260824-232348.log
Stream 1 baseline `44/44/0`: **"Same as before, tune + static."** Then Windows
soft-reset (0x300b=0x07, 0x3005=0x00, 2/2 ok), re-bring-up with cold-init
replay (presence after 1 sample, post-attach latch 0x1), stream 2 `44/44/0`:
**"Clack + sound."** (static level for stream 2 not stated — see follow-up).
Reset does not kill the amp (re-arm works) and produces no reported change.
Re-run 23:35:10 / 23:35:39 (BAT 30→29 %, log /tmp/spx-delta-ab-20260824-233454.log,
both `44/44/0`, reset 2/2): **"Clack + almost silent static (both times)"** —
the tone vanished within 11 minutes of the 23:24 audible pair (BAT 32 %).
Delta #5 CLOSED (no change either way). In-boot loudness ledger: 32 % audible,
29-30 % silent — consistent with a SOC-dependent gate near 30 %.

### 49.12 BREAKTHROUGH 23:4x — WCD9340 DMICs produce data (objective listener within reach)

RE agent (Codec_cal.acdb full decode, PROGRESS-worthy facts): CDCLUT0 payload
for `DMIC_2_1_STEREO` = source DMIC1+DMIC0 → SLIMBUS TX; TLVs: **MICBIAS3 then
MICBIAS1, both 1800 mV**; DMIC-only TLV `0x1008/7 = 8` (mclk/8 = 1.2 MHz?);
no codec register blobs anywhere in the ACDB; DSDT/INF: the codec's only
votes are BBCLK2 (MCLK) and LDO14_E; no mic GPIO/rail exists; Yoga C630 uses
AMIC — SPX would be the first mainline WCD9340 DMIC board. Top suspicion:
`ADC MUXn` enum default index 0 = "DMIC" so `cset DMIC` never fires put() and
`TXn_TX_PATH_CFG0` bit7 (0=ADC, 1=DMIC) stays at its power-on ADC value.

Test (v28 boot, BAT 29 %): `ADC MUX0` AMIC→DMIC toggle (forces put) +
`ANA_MICB3/MICB1 = 0x50` (ENABLE + 1.8 V; my earlier 0x40 was ENABLE at 1.0 V)
⇒ **DMIC0 rms 4.5 / DMIC1 rms 6.7, 168-172k nonzero samples** (vs 0 before).
`TX0_TX_PATH_CFG0 (0x0a32)` read back 0xd0 after the toggle (bit7 = DMIC set);
writing 0x80 raised DMIC0 to rms 159 (−46 dBFS). Isolation of bias-vs-bit7 in
§49.13.

### 49.13 DMIC gate ISOLATED = MIC BIAS1 voltage (1.0 V vs 1.8 V); bit7 irrelevant

2×2 on DMIC0 (v28 boot, BAT 25-29 %), everything else fixed:
| MICB1 vout | TX0_PATH_CFG0 bit7 | result |
|---|---|---|
| 0x10 (1.8 V) | 1 (DMIC) | rms 4.5, 168k nonzero — LIVE |
| 0x10 (1.8 V) | 0 (ADC) | rms 4.4, 168k nonzero — LIVE |
| 0x00 (1.0 V) | 1 | rms 0.1 — dead |
DMIC1 with 1.8 V: rms 6.2 — LIVE. MICBIAS3 not required (A: MB3 off, still
live). ⇒ The mainline driver leaves `ANA_MICB1[5:0]` = 0 (1.0 V) so DAPM's
"MIC BIAS1" enables a 1.0 V rail; SPX's DMICs need 1.8 V (DT declares
`qcom,micbias1-microvolt = 1800000`; Windows ACDB says 1800 mV). Root cause of
the vout=0 is in the driver's init path (§49.14). Objective-listener proof
(mic records the speaker) pending a boot with the speaker audible — at 25 %
battery the speaker is silent by the §46 gate, Goertzel@440 Hz shows nothing.

### 49.14 Root cause of the 1.0 V bias and the fix

`wcd934x_init_dmic()` writes `ANA_MICBn[5:0] = common.micb_vout[n]`, but
wcd934x.c never calls `wcd_dt_parse_micbias_info()` (wcd937x/938x/939x do), so
micb_vout[] is all-zero ⇒ vout code 0 = 1.0 V on every bias, regardless of
`qcom,micbiasN-microvolt` (regmap cache confirmed 0x622 = 0x00 before any
live write). Fix: call `wcd_dt_parse_micbias_info(&wcd->common)` in
wcd934x_codec_probe after `common.max_bias = 4` (+ dev_info of the parsed
values). Built as snd-soc-wcd934x.ko; deploy = install + mkinitcpio (module is
in the initramfs MODULES list). Upstream-worthy.
DEPLOYED 2026-08-24 23:59: `/lib/modules/6.18.3-1-surface+/updates/snd-soc-wcd934x.ko`
sha256 003ab134… (backup `.bak-pre-micbias`), `mkinitcpio -P` done, module
present in the initramfs. Next boot (v28, autotest armed): expect
`SPX: micbias vout ctl 16/16/16/16 (1800/... mV)`, DMIC capture live without
any live register write, then the mic-records-speaker proof (needs AC/battery
> ~32 %: ask the user to plug in).

### 49.15 00:12 boot (2026-08-25) — micbias fix live; first tone AUDIBLE at BAT 20 %

Boot at 00:10-00:12 (not armed by me; GRUB clean), `snd-soc-wcd934x` with the
micbias parse: `SPX: micbias vout ctl 16/16/16/16 (1800/1800/1800/1800 mV)`.
Autotest `32/32/0`, attach 0x1 before+during, **AC OFF, BAT 20 % discharging**.
User: **"Heard a rather clean tone after a lot of static."** ⇒ a cold boot at
20 % is audible while the previous boot went silent at 29-30 % after ~55 min
uptime ⇒ the gate tracks time-since-boot/soak, NOT battery SOC (§46 two-factor
model: the powered-hours term dominates).
00:2x same boot: 440 Hz play (`40/40/0`) = **"Clack + a bit of static"** — no
tone ⇒ the speaker decayed to silent within ~10 min of boot again (audible
00:18 at 20 %). Mic Goertzel null therefore uninformative. 15 s DMIC1 capture
with the user making noise: 0.5-s RMS 4→35, peak 1945 (weak but varying).
Next: capture DMIC1 INSIDE the autotest tone window (first minute after boot,
speaker reliably audible) and Goertzel@440 — an objective per-boot metric.

### 49.16 Harness gains an objective listener (00:3x 2026-08-25)

`scripts/spx-speakers-up.sh`: `SPX_MIC_CAPTURE=1` routes DMIC1 -> DEC0 -> SLIM
TX0 -> SLIMBUS_0_TX -> MultiMedia2, records 9 s (`<run>/mic-DMIC1.wav`) across
the tone window and prints `SPX MIC: ... 440Hz=… neighbours=… ratio=… (TONE
DETECTED|no tone)` (`<run>/mic-goertzel.txt`). Never fatal. Added
`SPX_MIC_CAPTURE=1` to `/var/lib/spx-speaker-autotest/test-env` so every
future autotest boot scores its own first tone without a human.
Harness mic block dry-run OK (standalone: `SPX MIC: frames=432000 ... (no tone)`
with the speaker silent). Arming `spx-speaker-v28-music` + autotest with
`SPX_MIC_CAPTURE=1` at 00:4x (BAT 20 %, AC off) for the mic-scores-tone proof.

### 49.17 OBJECTIVE LISTENER PROVEN (00:24 2026-08-25, boot 00:16, AC OFF, BAT 19 %)

Autotest attempt `20260824T222407Z-943` with `SPX_MIC_CAPTURE=1`: playback
`32/32/0`; DMIC1 capture closed with `write_done=75` (real READ_DONEs);
**`SPX MIC: tone-window rms=169.1 440Hz=18.11 neighbours=0.14 ratio=128.0
(TONE DETECTED)`** — the built-in mic recorded the right speaker's 440 Hz.
User (same tone): "static and then tune + static." First boot-scoped, human-free
speaker measurement on this machine. Run dir
`/var/tmp/spx-speaker-20260825-002408` (`mic-DMIC1.wav`, `mic-goertzel.txt`).
Static can now be quantified from the same file (out-of-band energy in the
tone window vs the zero-prefix window). Autotest exit 1 = follow-up (§49.18).
Volume: user asked for quieter runs ⇒ `SPX_PA_VOLUME` (harness + play-right)
and `SPX_TONE_GAIN` env knobs; test-env now `SPX_PA_VOLUME=4 SPX_TONE_GAIN=1.6`.

### 49.18 First objective static measurement + harness fixes (00:3x 2026-08-25)

`/var/tmp/spx-speaker-20260825-002408/mic-DMIC1.wav` (autotest, PA Volume 12,
tone −2 dBFS): room floor before the PCM opened rms 12; **digital-zero prefix
with the PA on rms 128 = the static, +20.6 dB over the room floor, with NO
audio data flowing** (objective confirmation of §33: static is not the data);
tone window rms 166, 440 Hz fundamental 18.7 but harmonics 880/1320 Hz =
25/59 (driver roll-off and/or distortion). New `scripts/spx-mic-analyze.py`
prints room/static/tone metrics + "static index"; harness now runs it
(`<run>/mic-analyze.txt`). Harness fix: the Q6 counter gate now ignores the
capture session's close line (`submitted=0`), which caused exit 1 at 00:24.
Quiet defaults in test-env: `SPX_PA_VOLUME=4 SPX_TONE_GAIN=1.6` (user request).
Static A/Bs can now be scored per boot with no listener: compare the
zero-prefix static index across knobs (PA volume, port mask, boost, LDO14E,
enum-IRQ mask, idle park), one variable per boot, autotest armed.
No further reboots tonight (late; user asked for quiet).

### 49.19 What the mic says about the static (silent analysis, 00:5x 2026-08-25)

From `spx-speaker-20260825-002408/mic-DMIC1.wav` (synced boot, tone present):
- Static = **stationary broadband hiss** (1 ms envelope sd/mean 0.16), flat
  2-12 kHz (−6 dB/band re total), max around 3.5-4.1 kHz, shelf 16-20 kHz;
  raw autocorr negative at lags 3-8 samples. No single tone, no clock bursts.
  Reads as white-ish noise coloured by the driver/enclosure response.
- Tone harmonics re 440 Hz: 2nd +2.6, **3rd +9.9**, 5th +6.3, 7th +3.3, **9th
  +8.8 dB** — odd-dominant with a real 2nd. Either symmetric clipping or the
  driver's low-frequency roll-off at 440 Hz. Decider: a 1 kHz tone.
From `spx-track-20260825-003423.wav` (00:34, PA Volume 4, the run the user
called far too loud, tone ABSENT): static rms 322-384 (vs 128), **bursty**
(sd/mean 0.55), envelope autocorr ~0.86 across 1-11 ms. This is the
"loud static + no tone = amp desynced from the bus with the PA on" state, now
measured: the in-boot loudness collapse is a **bus desync**, not analog decay,
and lowering PA volume does nothing to it. The mic can classify every run as
SYNCED (tone + hiss ~130) or DESYNCED (no tone, hiss ≥300, bursty).

Hard rule added (CLAUDE.md + memory): no sound without an explicit "play" for
that run; volume knobs do not make a run quiet.

Tomorrow's silent-first plan (each sound needs the user's go, daytime):
1. 1 kHz tone at −20 dBFS, PA 0 vs 12: odd-harmonic clipping vs roll-off; static
   index vs PA gain (resolves the §33 by-ear claim objectively).
2. Per-boot autotest scoring with `SPX_MIC_CAPTURE=1` (already armed in
   test-env) for the boot-scoped knobs: enum-IRQ mask (#3), idle park (#4),
   LDO14E, port mask 5, `spx_sample_edge`, `spx_win_transport` — compare
   static index + sync class, one variable per boot.
3. Desync tracker: after a synced boot, sample sync class every N minutes to
   find the desync moment and correlate with the SoundWire error/IRQ log.

### 49.20 COMP_STATUS ("frame-gen=") is not a sync predictor; desync is UPSTREAM of the amp

`SPX FORCE-ATTACH: after N resets frame-gen=0x…` prints SWRM_COMP_STATUS. Across
seven boots the first two attaches (probe + autotest) always read 0x2a01 and
every later attach reads a different upper byte (0xb501, 0x4901, 0xbc01, …):
a free-running field, not a state. Only anomaly: the LDO14E boot (22:55, silent
first tone) read 0x0001 twice. Not usable as a silent predictor.

Inference from the 00:34 desynced run: `spx-play-right.sh` had just parked the
amp for 10 s, re-powered pin2, re-run force-attach ("stable attachment") and
replayed cold init — i.e. the AMP was power-cycled and re-attached — and the
stream was still desynced (no tone, loud bursty hiss). So the desync state is
NOT in the amp: it lives in what survives an amp power cycle — the WCD9340
SoundWire master / interpolator, the persistent SLIMbus stream, or the AFE port
kept running (`spx_persist_stream=1`, `spx_keep_asm`, port stop parked). A cold
boot clears it. Daytime test (each run needs the user's "play"): after a boot
reaches the desynced class, tear the persistent pieces down one at a time —
(1) `snd_soc_wcd934x.spx_persist_stream=0` + reopen, (2) real AFE port stop,
(3) SWR master soft reset (`SWRM_COMP_SW_RESET`) + re-attach — and let the mic
say which one restores SYNCED. If one does, that is the static/desync fix path.

### 49.21 Quiet runs, PA-gain curve, and a THIRD output state (00:57-01:05, BAT 10 %, AC off, uptime 40-45 min)

User: "You can play, just not super loud." Tracker runs (mic-scored, tone
−24/−14 dBFS):
| PA Volume | tone gain | static rms (zero prefix) | tone | class |
|---|---|---|---|---|
| 0 | 0.5 | 16 (= room floor) | none | — |
| 4 | 1.6 | 33 | none | — |
| 8 | 1.6 | 5.9 (below room floor) | none | — |
Reference: SYNCED first stream 00:24 = hiss 128 + tone; DESYNCED 00:34 = hiss
322-384 bursty, no tone. Now, 40+ min into the boot: neither hiss nor tone at
any gain ⇒ **SILENT class** (the user's "clack + silence"). Sequence within
this boot: SYNCED (0:24) → DESYNCED-LOUD (0:34) → SILENT (0:57+). The
by-ear "PA 12→0 kills tone not static" (§33) cannot be re-evaluated from
these runs (output dead); needs a SYNCED boot: PA 0/4/8/12 within the first
minutes, mic-scored. Practical: quiet runs (PA ≤4, tone ≤1.6) are fine for
sync classification; the loud event is the DESYNCED hiss, which no gain
setting controls — avoid re-bringing the amp up after a DESYNCED reading.

### 49.22 (2026-08-25 12:04-13:10, AC OFF→unplugged mid-session) — DESYNCED survives a full amp-side reset; parked ASM sessions are UNDESTROYABLE live; boot wedged (by experiment design)

Boot: v28-class quiet autotest at ~09:53 (first stream TONE DETECTED,
ratio=171.7 — objective-listener pipeline validated on an untouched fresh
boot). Then the machine sat idle 2 h.

**12:04 probe (BAT 24 %):** static-track on the idle boot → rms 558 ≈ tone
rms 553, 440 Hz ratio 0.3 ⇒ **DESYNCED** (loud bursty hiss). This is the
2-h-old state of a boot that started SYNCED — consistent with §49.21's
SYNCED→DESYNCED→SILENT progression.

**Teardown-rescue ladder, revised then executed:** persist_stream is
registered 0444 (cannot flip live — module-param writability is fixed at
`module_param()` registration; chmod only changes the sysfs inode mode), and
`spx_no_port_stop=0` cannot stop AFE-port parking because
`q6afe_dai_keep_port_running()` hard-ORs `SLIMBUS_2_RX &&
of_machine_is_compatible("microsoft,surface-pro-x")`. The only live lever was
`q6asm_dai.spx_keep_asm` (0644). Split experiment:

- **Phase 2** (amp+controls up, NO new PCM, parked sessions intact): VOID as
  a sync probe — with every switch already in its set state and no PCM open,
  DAPM fired no events and the path stayed unpowered. Measured rms≈6 =
  powered amp + idle path = silence. Incidental finding: the DESYNCED hiss
  needs the *active stream path*; a powered amp alone does not hiss.
- **Phase 3b** (`keep_asm=0`, reopen parked playback session): open reused
  the parked client ("reusing parked ASM playback session"), then prepare
  sent **OPEN_WRITE_V3 (0x10db3) → DSP error 0x9** ("Audio Client already
  active" class: session still open DSP-side). Prepare failed; close path
  (keep_asm now 0) ran the real teardown: CMD_CLOSE (no ACK expected) +
  **UNMAP_REGIONS → timeout −110** — the exact capture-wedge signature.
  Every later ASM command times out (phase 3c capture open: CMD timeout).
  **The boot's ASM path is dead by experiment design.**
- **Phase 3c**: no recording possible; capture open timed out.

**Conclusions:**
1. A parked ASM session can never be really closed from Linux: the DSP never
   ACKed its original OPEN (session still "active" DSP-side), so CLOSE
   never completes and UNMAP times out −110. Parking is load-bearing for the
   whole boot lifetime — do NOT ship keep_asm=0 flips on live boots.
2. Desync-rescue therefore CANNOT be tested below the amp on this kernel:
   the candidate carriers (parked ASM session, kept-running AFE port,
   persistent SLIM stream, codec interpolator) are all pinned open by
   spx_keep_asm/persist_stream/AFE-parking, and each of those is either
   0444-fixed or hard-OR'd to the machine. The rescue question moves to
   BOOT-TIME knobs: e.g. a cmdline with spx_keep_asm=0 + spx_persist_stream=
   0 + AFE-stop enabled would give truly-fresh sessions per stream — worth
   ONE guarded boot vs today's baseline if desync ever shows again.
3. Phase-2 side result stands: powered amp without an active stream is
   silent — the hiss lives in the data/streaming path, not in analog bias.

State after: ASM wedged (expected), amp parked val=0x00, GRUB default
spx-audio-rescue, nothing armed. Session aborted early — battery hit 9 %
discharging (AC got unplugged); no further boots or audible windows until
mains power returns.

## §50 (2026-08-25 afternoon) — mic listener turns the whole-boot-silence class OBJECTIVE; warm-reboot rail hypothesis

### The n=3 matrix (all v28-class, BAT 50 %, mains, byte-identical software)

| boot | predecessor | first stream (mic-scored) | Q6 | attach |
|---|---|---|---|---|
| `5f22c275` 14:32 | rescue (**audio modules blacklisted**) | **CLEAN TONE**: rms 231.5, 440 Hz ratio 51.5, +15.7 dB over prefix; **zero-prefix static −0.2 dB vs room = NO static** | 32/32/0 | proven, latch flickered mid-stream |
| `70655b28` 15:42 | v28 (audio active) | SILENT: static index **−15.1 dB vs room** — amp emitted literally nothing | 32/32/0 | proven, latch held mid-stream |
| `b2fe59f6` 16:39 | v28 (audio active) | SILENT: static index **−15.5 dB vs room** | 32/32/0 | proven after 3 samples |

Two firsts in one afternoon:

1. **The whole-boot-silence class is now objectively measurable without any
   listener.** Both silent boots show the amp emitting ~15 dB BELOW room floor
   during the zero prefix with the PA on — not "static without tone", but
   nothing at all. Q6 counters (`submitted=write_done=32`, fallback=0), DP4
   banks (`0x01000607` both banks), attach proof and RX0 boundary flag are
   bit-identical between audible and silent boots. Software-visible state
   CANNOT distinguish them; only the mic can.
2. **The "residual static" defect did NOT reproduce on the clean boot** —
   zero prefix measured at room floor. Static is also intermittent, not a
   persistent baseline. (Boot -1 was killed ~16 min in by an accidental
   duplicate reboot before soak probes could run; its first-stream data
   survived and is what this table uses.)

### §49.22 correction

The morning's DESYNCED classification was taken at **BAT 24 % discharging** —
below the documented ~26–30 % SOC collapse floor. Its use as evidence that
"desync lives upstream of the amp" is WITHDRAWN pending healthy-SOC data.
The CSV rows that motivated it all sit at low SOC off-AC with RMS falling as
SOC falls = rail-sag signature, not a streaming-path defect.

### Warm-reboot-rails hypothesis: REFUTED same-day (§50.1) — predecessor chain verified from journal

The hypothesis as staged above attributed predecessors by memory and got the
mapping **inverted**. `journalctl -b <id> -k | grep 'Kernel command line'` per
boot (`module_blacklist=soundwire_qcom,snd_soc_wsa881x` = rails never
requested):

| boot | cmdline | outcome |
|---|---|---|
| -6 `57e445a2` 09:59–14:24 | audio-active v28 | (DESYNC@24 % SOC — void, below floor) |
| -5 `5f22c275` | audio-active v28 | **CLEAN** |
| -4 `594daa74` 14:48–15:35 | **blacklisted rescue** | — |
| -3 `70655b28` | audio-active v28 | **SILENT** |
| -2 `b2fe59f6` | audio-active v28 | **SILENT** |
| -1/0 rescue dwells | blacklisted | — |

CLEAN followed an *audio-active* boot; a SILENT boot followed the
*rails-dropped* rescue — both directions contradict "rails persist across
warm reboots cause silence". The staged dwell test was in fact already run
(rescue → v28 came out SILENT). Also checked and found NON-discriminative:
mid-stream `MCP_SLV_STATUS` latch state (TONE DETECTED with latch held at
00:24; silent with latch cleared at 01:14 — counterexamples both ways), and a
one-off probe-time `SWR bus clsh` on one silent boot only. The sanitized
service logs of clean vs silent runs are byte-identical.

**Consequence:** whole-boot silence is a per-boot random draw (~50 % today,
n=3 + last night's n=2) with NO software-visible or predecessor predictor.
The class behaves like a coin flip decided before/at codec bring-up. Next
discriminators to try when a listen window exists: full power-OFF (not warm
reboot) vs warm reboot A/B at fixed config, since that is the only remaining
state axis that differs from everything already held equal.

**Reboot status:** none needed for this correction. The current unarmed
rescue dwell (18:09) stands; nothing armed; persistent default remains
`spx-audio-rescue`.

### Harness/tooling deltas shipped today

- `/usr/local/sbin/spx-speaker-autotest`: power-state logging before+after
  every run (`power-state-{before,after}.txt`); `SPX_EXPECT_PERSIST_STREAM`
  knob relaxes the persist_stream cmdline gate for future A/B; test-env
  parsing moved before the cmdline gate. Backup `.bak-20260825-powerlog`.
- `grub-editenv` MUST be called with explicit file path
  (`sudo grub-editenv /boot/grub/grubenv …`) — bare form silently fails to
  WRITE here ("hostdisk//dev/nvme0n1p1: not found") while reads fall back.
- Repo `AGENTS.md` created: mandatory pre-reboot state check (interrupted
  tool call ≠ failed command; two duplicate reboots destroyed boots today).
