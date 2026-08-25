# 00 — Synthesis: how Windows makes the SPX speakers work, and what Linux is missing

Team of 10 RE agents, 2026-08-21/22. Source docs: `01`–`10` in this directory.
Scope: static RE only (no Windows capture exists anywhere on disk — doc 10).
Current Linux state: endpoint B / MP4-SPK2 / C1 / GPIO pin2 / S16_LE audible
**with residual static** (present even during digital-zero audio) and a codec-side
`overflow error on RX port 0` on every stream.

## 1. The complete Windows pipeline (who owns what)

```
app → audiosrv (+ Dolby DAX3 / ProxyAPO host effects, default ON)
  → WaveRT → portcls → qcaudminiport8180 (KS topology, no HW protocol)
  → qcauddev8180:
      · ALL WCD9340 register control over SPI4 @24MHz (\_SB.SPI4, MMIO 0x88C000)
        - incl. the internal SoundWire master (@0xc85 region), all WSA881x writes,
          PA sequences, AND (implied by elimination, doc 03) the codec SLIM PGD ports
      · ADSP commands over APR/GLINK apr_audio_svc:
        CDC_REG_CFG_INIT 0x10237 → CDC_SLIMBUS_SLAVE_CFG 0x10235 /
        SLIMBUS_SLAVE_PORT_CFG 0x10233 → ADM open 0x10327 (NULL_COPP 0x10312)
        → MATRIX_MAP_ROUTINGS_V5 0x10325 → AFE_PORT_DEVICE_START 0x1020c
        → FB spkr-prot 0x1025f/0x1021d (runtime cal) or disable seq (DriverStore copy)
      · ACDB blobs served by qcadcm8180 (pure property server, doc 01: zero transport code)
  → ADSP firmware (stock image = Windows' image byte-for-byte):
      ASM stream → AFE port 0x4004 SLIMBUS_2_RX → AFESlimbusDriver channel
      → SlimBusMaster core → BAM-Lite pipe → SLIMbus hardware   [doc 05]
  → WCD9340 SLIM RX ports (PGD) → INP_MUX → INT7/INT8 interpolators
  → [FIXED SILICON] interp → internal SWR master DOUT            [doc 06]
  → SWR frames → WSA881x slave DP1 → DAC/PA                      [doc 02 pending]
```

Ownership table (the one-glance summary):

| Function | Windows owner | Linux owner | Match? |
|---|---|---|---|
| Codec register control | qcauddev via **SPI4** | wcd934x via SLIMbus AHB bridge | **different transport**, same registers |
| Internal SWR master + WSA | qcauddev (apps side) | soundwire-qcom + wsa881x | equivalent model |
| Speaker graph/cal to DSP | ADM params from ACDB (device 0x45, key 0x15200) | **nothing sent** (NULL_COPP, topology 0) | **MISSING** |
| SLIMbus data path | ADSP firmware (BAM-Lite) | ADSP firmware (same image) | identical |
| Host effects | Dolby/PEQ APOs pre-ADSP | none | content-only, cannot cause transport static |
| Amp discovery | SWR enum (no ACPI nodes for amps) | forced dev-0 | equivalent |

## 2. Settled questions (do not reopen)

1. **No programmable interp→SWR routing exists** — fixed silicon, proven four ways
   (doc 06). Any future "find the missing routing register" idea is dead.
2. **qcadcm contains nothing transport-related** (doc 01) — stop mining it.
3. **The ADSP cannot write WCD9340 registers** — AFECdcRegOp is a stub string-proven
   in both stock and win images (doc 05). All codec control was always host-side.
4. **No ADSP test-pattern generator exists** (doc 05 Q4) — firmware-sourced known-data
   diagnostics are not available.
5. **Windows' 48k/24-bit endpoint declaration is logical only** — the WSA link is
   1-bit PDM; S24_LE already failed live (v18).
6. **Effects/APOs are host-side** (docs 07/10) — they shape content, not transport.
7. **The amps have zero ACPI presence** (doc 07) — nothing more to mine there.
8. **Windows never used SLIMbus for codec reads** — SPI4 did them; our flaky-read
   saga is a self-inflicted transport property (doc 07 §deltas #1).

## 3. Candidate causes of the residual static — ranked

Static is present during digital-zero preroll ⇒ it is *added noise/framing garbage*,
not mis-shaped content. RX0 FIFO overflow at the codec every stream ⇒ the codec-side
SLIM RX port consumes more than it drains at least transiently.

1. **Codec SLIM PGD port config differs (watermark/multi-channel map).**
   Linux hardcodes `PORT_CFG = 12-byte-watermark<<1 | enable = 0x05` per RX port
   and writes the *accumulated* payload word to every enabled port
   (wcd934x.c:1775–1783). Doc 03 proved qcslimbus never touches these registers;
   doc 05 proved the ADSP can't. So on Windows either qcauddev programs them over
   SPI4 differently (values TBD in doc 02), or nobody does (reset values apply).
   *Testability:* runtime-writable regmap writes; cheap A/B once doc 02 lands.
2. **Missing ADM-side per-module calibration/graph.** Windows sends six module
   instances × AGII gain curves + graph 0x10000008 selection after ADM open,
   before AFE start (doc 04). Linux sends nothing. Gain curves alone shouldn't
   cause silence-band noise, but module config could gate rate-match behavior
   (doc 05 shows sample-count contract machinery exists).
   *Testability:* extend spx-acdb-extract.py → emit tuples → replay via ADM
   SET_PP_PARAMS probe; medium effort, single listen.
3. **AFE-side codec/SLIM param subset differences.** v29's staged six-step
   `spx_auto_speaker_cal=1` covers CDC_SLIMBUS_SLAVE_CFG/PAGE_CFG/PORT_CFG +
   SLIMBUS_CONFIG(48000, 0xc0/c1) + CDC_REG_CFG(0x15200 blob) but was never
   listened to (title/cmdline mismatch found by doc 09). One guarded boot answers it.
4. **Single-port vs four-port descriptor operation.** Windows opens all four SWR
   descriptors per side; Linux opens one. Known-audible single-port rules this out
   as an audibility gate, but the frame shape differs (doc 02 pending = decode what
   each port carries). Blocked on dual-attach addressing fix regardless.
5. Ruled out by this round: channel-map zero (refuted — sdm845.c override sets
   0xc0/0xc1); missing interp routing (fixed silicon); ADSP fw choice (stubbed
   identically); host effects; protection state (v22).

## 4. Proposed next tests (single-variable, cheapest first)

T0. **Fix the v29/v30 GRUB entry mismatch, arm v29 (`spx_auto_speaker_cal=1`).**
    Everything is already staged; one guarded boot answers candidate 3.
T1. **SLIM PGD watermark/port-config A/B** (after doc 02 confirms Windows values):
    add a wcd934x module param to override PORT_CFG/MULTI_CHNL values at stream
    prepare; boot with Windows-derived values. No rebuild of other layers needed.
T2. **ADM cal injection**: extract the six (instance, param_id, payload) triples
    from Speaker_cal.acdb, replay through a debugfs/probe SET_PP_PARAMS path
    before AFE start. Guarded-boot A/B.
T3. (Only if T0–T2 all fail to change anything) revisit four-descriptor stereo
    after fixing dual-attach addressing (DTS unique IDs 3/4, sequential dev1/dev2).

Each T costs exactly one first-stream listen; harness audit (doc 09) confirms the
guarded chain is ready and disarmed; persistent default remains spx-audio-rescue.

## 5. Harness/housekeeping actions surfaced by the audit (doc 09)

- v30 entry title claims "debugfs cal firing" but its cmdline lacks the knob — fix
  or delete before arming anything new.
- Autotest unit lives outside git (/usr/local/sbin/spx-speaker-autotest + systemd
  unit) — consider tracking copies in-repo.
- Add a mechanical check (harness step [0]) that bundled initramfs modules match
  installed ones; mtime discipline alone has voided boots before.
- Record vmlinuz sha256 somewhere durable.

## 6. Doc 02 additions (final agent report)

- **Transport parity confirmed bit-exact**: paged AHB bridge (`0xc85`/`0xc95`
  RMW/`0xc96` ready poll, 5 retries), `DP_PORT_CTRL` packing, banked frame-ctrl,
  slave DPn banked registers, `MCP_SLV_STATUS` semantics, command-FIFO roles —
  all identical between qcauddev and Linux `soundwire_qcom`. The residual static
  is therefore very unlikely to live in the SWR transport parameterization.
- **Windows never broadcasts `SCP_FrameCtrl`.** Its bank switch programs the
  *destination* bank's master words AND slave registers from per-port records
  (source of truth), then flips an internal byte and writes only the frame-ctrl
  word. Consequences: (a) our dropped-broadcast whole-boot-silence failure mode
  cannot occur on Windows; (b) `spx_mirror_banks=1` was NOT Windows-parity —
  mirror-at-write-time desynced the amp, whereas compose-per-bank-from-records
  is the real design. A faithful port = keep both banks complete, program the
  inactive one on any param change, switch by writing FRAME_CTRL[new] alone.
- **Every write is verified**: command-counter tagging, post-submit drain/status
  with nested retries, readback compare (≤10 tries). Windows distrusts the bus
  exactly like our rules say to.
- **Frame timing derives from a 153.6 MHz root** (19.2 MHz × 8) — consistent
  with the settled 9.6 MHz audible setting; no new clock knob implied.
- **Interrupt DPC is reactive only** — attach worker on bit 0, FIFO flush
  (`0x308←0xffffff`) on error bits 0x40/0x80, slave callback on 0x800. No
  missing pro-active register sequence exists for Linux to copy.
- Still open after doc 02: **who programs the codec's SLIM PGD RX-port
  registers (watermark class, `0x140+4p`/`0x30+p`) on Windows** — doc 02 scoped
  itself to the SWR-master layer and deferred codec-register sequences to a
  companion pass. Candidates remain "qcauddev over SPI4 with different values"
  vs "nobody (reset values apply)". This keeps candidate 1 of section 3 alive;
  one targeted follow-up RE session on qcauddev's codec-regmap write sites
  would settle it without any listening.

## 7. Final ranked test plan (supersedes section 4 ordering)

T0. Arm v29 (`spx_auto_speaker_cal=1`) after fixing the v30 title/cmdline
    mismatch — zero code changes, answers the staged-but-untested AFE cal layer.
T1. Follow-up RE (no listen): find qcauddev's codec-SLIM-PGD write sites/values.
    Then either replicate them via a wcd934x override param, or prove Windows
    leaves them at reset (→ try removing our 12-byte watermark write entirely).
T2. ADM cal injection (six module instances × AGII curves from Speaker_cal.acdb)
    via SET_PP_PARAMS before AFE start.
T3. Destination-bank programming model in soundwire_qcom (both banks complete,
    no broadcast switch) — robustness fix for the whole-boot-silence class;
    also required groundwork before any dual-descriptor stereo attempt.
