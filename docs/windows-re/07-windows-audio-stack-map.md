# Windows RE 07 — complete Windows audio device graph (master stack map)

Agent 7 of 10. Sources: `~/Documents/drivers/FileRepository/*` INF/binary reads,
`~/Documents/acpi/surface_pro_x_sq2/dsdt.dsl`, `~/Documents/spx-winlive/*`,
ACDB decodes (cross-checked against agent-4's `04-acdb-deep-extraction.md`),
and the accumulated qcauddev/qcadcm RE in CLAUDE.md + memory notes. Static RE
only — no Windows capture exists anywhere on disk (agent 10 proved this).

Headline structural fact: **Windows talks to the WCD9340 over SPI4, not
SLIMbus.** The DSDT gives the codec device (`AUDD`) a `SpiSerialBusV2`
resource on `\ _SB.SPI4` at exactly 24 MHz alongside its reset/interrupt
GPIOs. Linux instead reaches the same codec through the SLIMbus NGD interface
element — the path whose reads are unreliable and needed the paged-bridge
discipline. Every "reads return zeros/garbage" wall we hit lives on the
transport Linux chose; Windows never used it for control.

## Stack diagram

Render path, app → physical right speaker (endpoint B shown; endpoint A is the
mirror with MP1/sink7):

```
 app (WASAPI client)
  └─ audiosrv.exe            audio engine, 48 kHz float mix
      ├─ Dolby DAX3 APO      PEQ + regulator-speaker-dist + Atmos virtualizer,
      │                      DEFAULT ON, full_dsp_support=false → host CPU
      ├─ ProxyAPO.dll        Qualcomm effect proxy (CProxyAPOEFX/MFX),
      │                      forwards property sets toward DSP effects
      └─ WaveRT cyclic buffer  shared-mode render buffer
          └─ portcls.sys     KS port/filter plumbing
              └─ qcaudminiport8180.sys   Wave/Topology miniport
                  · TopologySpeaker = device 0x45, KSNODETYPE_SPEAKER
                  · imports ONLY portcls/WDF/WppRecorder (no qcauddev linkage)
                  · audminiext INF: peakmeter poll 10 ms per wave pin
              └─ [control plane] qcauddev8180.sys   function driver
                  · binds ADCM\QCOM0425 (codec MFD) + AUDD\QCOM0437 (MBHC)
                  · codec registers  → SPI4 (\\_SB.SPI4, 24 MHz, IRQ GSIV 0x27C)
                    · WCD9340 internal SoundWire master (@codec off 0xc85)
                      · wsa_reg_write 0x140098640 / wsa_reg_read 0x140098788
                      · master rw 0x14009afa8 / 0x14009b388
                      · PA bring-up 0x140098af0/0x140099058, shutdown 0x14009a228
                      · static descriptor tables: LEFT slave ports 1/2/3/4 →
                        master ports 1/2/3/7 (masks 1/f/3/3);
                        RIGHT slave ports → master ports 4/5/6/8
                  · ADSP commands    → APR over GLINK:
                      qcauddev8180 → \Device\GLINK → qcglink8180.sys
                        → \Device\RPEN → qcrpen8180.sys → SMEM/GLINK
                        → on-wire channel `apr_audio_svc` → ADSP
                    sequence (from qcauddev code):
                      1. AFE SET_PARAM CDC_REG_CFG_INIT 0x10237 then
                         CDC_SLIMBUS_SLAVE_CFG 0x10235 /
                         SLIMBUS_SLAVE_PORT_CFG 0x10233/0x10234
                         (svc opcode 0x100fa, port opcode 0x100fc — note
                         svc 0x100fa differs from mainline's 0x100f3)
                      2. ADM open 0x10327 (NULL_COPP 0x10312 default)
                      3. ADM MATRIX_MAP_ROUTINGS_V5 0x10325 (ASM COPP ↔ AFE port)
                      4. AFE_PORT_DEVICE_START 0x1020c (SR/ch/bitwidth from the
                         ACDB device record; STOP 0x1020d)
                      5. apps-side FB speaker protection SET_PARAM:
                         module 0x1025f FB_SPKR_PROT_V2_RX, param 0x1021d,
                         + FEEDBACK_PATH_CFG 0x1022c, VI_PROC_V2 0x1026a
                    DriverStore DriverFile copy disables protection:
                      3110=00 3111=00 3140=95 wait 1ms 313a=ce
          └─ ADSP firmware qcadsp8180.mbn  (legacy APR/ELITE; the SAME stubbed
             image Linux ships — sha 2703ceb6… byte-identical. It never owned
             SWR/WSA on Windows either.)
              └─ AFE port 0x4004 = SLIMBUS_2_RX   ← ACDB device-0x45 map
                  (prop 0x113b7: codec key 0x15200, port 0x4004, ch 0xc0/0xc1;
                  48 kHz keyed by prop 0x12eed {48000, 0x1da})
                  · SLIMbus data channels run as hardware flow (BAM), not CPU:
                    SLM1 BamBaseAddr 0x17184000 (registry, qcslimbus INF)
              └─ SLIMbus NGD 0x171C0000 → WCD9340 codec
                  · codec DAPM: SLIM RX0/1 → INT7/8 → COMP7/8 → SPK1/2 OUT,
                    and RX7/8 → internal SWR master → WSA881x
              └─ SoundWire 1-bit PDM link inside the codec package
                  └─ WSA881x amp ×2; SD_N from WCD GPIO bank pins 1 and 2
                     (no ACPI object exists for either amp — see below)
```

Capture side mirrors this through the same drivers (MBHC/AUDD\QCOM0437,
fluence modules on the ADSP) and is irrelevant to render.

## Per-driver roles

| module | role | evidence |
|---|---|---|
| `qcaudminiport8180.sys` (765 976 B) | portcls Wave+Topology miniport; owns the KS topology for TopologySpeaker(0x45)/UsbHs/BthHfp/Handset/MicArray; no direct hardware protocol | imports only portcls/WDF/WppRecorder |
| `ProxyAPO.dll` (301 184 B) | effect proxy bound via `PKEY_FX_Association = KSNODETYPE_SPEAKER`; exports CProxyAPOEFX/CProxyAPOMFX | audmini INF FX\0/EP\0 CLSIDs |
| `qcauddev8180.sys` (637 560 B; live sha 2c3f32…) | the real worker: codec register access (SPI4), internal-SWR master programming incl. all WSA881x writes, PA sequences, APR command construction toward ADSP | RE entry points in CLAUDE.md; INF binds |
| `qcadcm8180.sys` (682 896 B) | ADCM manager: PIL-loads `qcadsp8180.mbn`, hosts GLINK/APR services, ACDB blob loading, GUID→AFE-param dispatch, SMMU window config | INF registry below |
| `qcslimbus8180.sys` (184 592 B) | SLIMbus NGD manager for ADSP\QCOM0410; SLM1/SLM2 port/channel/BAM config | INF HKR,SLM1/SLM2 block |
| `qcglink8180.sys` / `qcrpen8180.sys` | GLINK provider + RPEN transport; carry APR frames to `apr_audio_svc` | 2026-06-17 RE |
| `qcadsp8180.mbn` | ADSP image; stubbed codec-reg op, no SWR code — identical bytes to Linux's stock fw | memory notes + agent 10 |
| `qcwdsp8180.mbn` (1 409 024 B) | WCD9340 onboard CPE (WDSP) firmware; shipped but the runtime state conflicts (see open questions) — treat as unused for speakers | auddevext package |
| ACDB `_cal.acdb` ×7 | per-device calibration; only `Speaker_cal.acdb` contains device 0x45 | agent-4 doc |
| Dolby DAX3 DLLs | host-CPU speaker processing (PEQ/regulator/virtualizer) | dax3 INF/XML |
| `audioendpoint.inf` | Microsoft null-driver class for `MMDEVAPI\AudioEndpoints`; creates no policy, zero Surface data | read in full |

## Registry config dump

All values verbatim from the decoded UTF-8 INF copies in `/tmp/spx-re7/`.

`qcauddev8180.inf` — `HKR,AUDD\CodecInitializationParameters`:
`MajorVersion=3 MinorVersion=2 IHGPIO=0 mclk_speed=2 mclk2_speed=0x010001
vdd_buck=1 IsWDSPAvailable=1 VBATFlag=0 IsMBHCReq=1 IgnoreIrqs=0 SlaveInfo=2
SwrSleep=0 WcdInstanceOffset=0`.

`HKR,AUDD\GPIO`: `NoofGPIOs=1`; `GPIO\1{GPIOUID=0,INDEX=0,INITIALVALUE=0}` —
one managed GPIO component (the codec reset, TLMM 143 per DSDT).

Power: `HKR,PWRC NoofPEPComponents=0x18`;
`HKR,POWERPROFILES DevicePowerProfile PackagesCount=0xD` — each package is
`{GroupID_DeviceID, POWERTYPE, COMPONENT_GPIOUID, STAGE}`; observed packages:
devices `0x46,0x4A,0x42,0x49,0x4C,0x4E,0x4D,0x51,…` with GPIOUIDs
`0x9,0xA,0xC,0xD,0xE,0xF,0x10,0x10,…`, all `POWERTYPE=0 STAGE=1`. This is a
PEP power-shutdown ordering graph across eighteen codec components — nothing
like it exists on Linux (DAPM supplies approximate it).

`qcadcm8180.inf` (`HKR,ADCM…`): logging flags FALSE/FALSE/TRUE,
`EnableADCMSelfRestart=FALSE EnableAudioPDR=TRUE`;
AVCS retry timeouts 150 ms / 15 000 ms, `FirstBootDynamicModulesLoadState=0`;
SMMU: base 0/0 end 0x1FFFFFFF/0, `AudioAridBase=0x07030000`;
POIPU_V1 window: base MSB 1 LSB 0 → end MSB 1 LSB 0xFFFF0000 (= our
[0x1_00000000, 0x1_FFFF0000) IOVA window);
AVTimer base 0x170F7000 num/den 10/120; EBI 0x80000000–0x2_80000000 cacheable;
`NoofPreallocatedBuffersforSVA=0`.

`qcslimbus8180.inf`: SLM1 `MasterEA=02A0 0017 0200(be bytes) EEAssign=01 00 02 03
MyEE=1 LocalBasePortNum=11 NumLocalPorts=5 LocalChannelBaseNum=65
BamBaseAddr=0x17184000 IsAudioInterface=1 CHLD{NumChld=1, "SLM1\QCOM0424"}`;
SLM2 same shape with `LocalBasePortNum=5 NumLocalPorts=1 BamBaseAddr=0x17204000
NumChld=0`.

`surfaceprox_subextadsp.inf`: `AdspImagePath=%13%\qcadsp8180.mbn`,
`SubsystemLoad\ADSP MemoryReservation=0x1a00000` (26 MiB) align 0x100000, plus
~35 ADSP-side `.so.1` payloads + `fastrpc_shell_0` with FASTRPC hash-map keys
(inventory in agent-10 doc).

`surfaceprox_audminiext.inf`: peakmeter poll interval 0xa ms per wave pin;
`AudioResourceConstraints_8180.xml`: max 8 concurrent AudioSessions, max 2
OffloadRestrictions streams, 104 rules total.

Dolby (`dax3_ext_qc_dolbyatmos_dolbyaccessoem.inf` payload
`AUDD_DEV_042C_SUBSYS_CLS08180_ADCM_SUBSYS_CLS08180.xml` — Surface-matched by
SUBSYS string): `internal_speaker fs="48000" total_count=2 front_count=2,
Left output_route=0 Right output_route=1 delay=0`; profile enables
`speaker-peq-enable=1 regulator-speaker-dist-enable=1 sbf_eq_enable=0`;
`Default_settings.xml`: `<DolbyEnabled endpoint="internal_speaker"
spatial_audio="on/off" value="true"/>`, default profile "movie",
`full_dsp_support=false`.

## ACPI findings

Hierarchy from dsdt.dsl (~line 75990–76260, GIO0 line 89601, SPI4 line 72513):

```
\_SB.ADSP   QCOM041D  IRQ Edge High 0xC2        (PIL boot device, _DEP PEP0/PILC/GLNK/IPC0/RPEN/SSDD)
 └ SLM1     _ADR 0   MMIO 0x171C0000 len 0x2C000   IRQ Level High 0xC3
    └ ADCM  _ADR 0                                  → qcadcm8180 (CHLD "ADCM\QCOM0425")
       └ AUDD           GpioIo(Exclusive,PullNone,,0x0640, "\\_SB.GIO0"){0x008F}   ← codec SYS_RST_N = TLMM 143, debounce 1600 µs
                       GpioInt(Edge,High,Exclusive,PullDown,"\\_SB.GIO0"){0x0100}  ← codec INTR (firmware-aggregated to GIC_SPI 571)
                       SpiSerialBusV2 "\\_SB.SPI4", 0x16E3600 Hz (=24 MHz)         ← CODEC REGISTER BUS
                       CHLD {"AUDD\QCOM0437","AUDD\QCOM042C"}                      → qcauddev (MBHC + codec children)
                          └ QCRT _ADR 1, MBHC _CRS {0x79,0x00}
\_SB.GIO0   QCOM040D  MMIO 0x03000000+0xDDC000  IRQ 0xF0   (TLMM GPIO controller; owns pins 0x8F/0x100 above)
\_SB.SPI4   QCOM040F  MMIO 0x0088C000 len 0x4000  IRQ 0x27C  (QUP SE; the codec bus)
```

Key negative result: **the two WSA881x amps have no ACPI presence at all** —
no device, no `_CRS`, no GPIO reference outside the codec. Their SD_N lines
live in the WCD9340's own GPIO bank (pins 1/2), reachable only through the
codec register file. Windows discovers them exclusively through the
SoundWire enumeration that its apps-side SWR master performs, exactly like
Linux's forced/device-0 model. There is also no SoundWire-manager ACPI node:
the internal master is reached as codec registers (offset 0xc85 region) over
SPI4, which is why no separate SWR device exists in the DSDT.

Cross-checks that hold: TLMM 143 reset matches the Linux `reset-gpios` and the
2026-06-11 probe; pin 0x100 INTR → GIC_SPI 571 matches the empirically
confirmed Linux wiring; SPI4 MMIO 0x0088C000 sits in the QUP region Linux
leaves unused.

## Endpoint policy

- One logical endpoint: `TopologySpeaker` device **0x45**, 48 kHz, stereo,
  Windows-declared 24-bit. ACDB ties it to codec key **0x15200**, AFE port
  **0x4004** (`SLIMBUS_2_RX`), channel masks **0xc0/0xc1**
  (`Speaker_cal` DPROPLUT 0x113b7, byte-verified twice independently).
- Two ordered codec endpoint tokens from `Codec_cal` key 0x15200:
  **0x01010004** (A) and **0x01010005** (B), which qcauddev maps to internal
  sinks **7 and 8**. Neither the miniport, ACDB nor INF names a physical side.
- Physical binding now settled empirically by v19/v20/v21: **token B / sink 8 /
  master-port group 4/5/6/8 → GPIO pin2 → audible (physical RIGHT)**;
  token A / sink 7 / group 1/2/3/7 → pin1 → physically dead. Treat A/pin1 as
  broken hardware until repaired.
- Windows opens **all four** SoundWire descriptors (both amps' full port sets)
  every session; Linux's guarded path opens exactly one (DP1 or DP4). All four
  at once was tried once on Linux (loud transient → silence) and remains the
  biggest unreplicated transport difference.
- Effects policy: PEQ + loudness regulator + Atmos virtualizer ON by default
  in host APOs; the ACDB gain tables were tuned for that pre-shaped signal,
  not raw sines.
- Session arbitration: ≤8 AudioSessions, ≤2 offload streams (constraints XML);
  cosmetic for bring-up.

## Additional artifacts inventory

| artifact | sha256 / size | role guess |
|---|---|---|
| `qcadsp8180.mbn` (subextadsp pkg) | `2703ceb6a8bd…` 10 758 800 B | ADSP fw — byte-identical to Linux's stock stub; v16 proved stock works |
| `qcwdsp8180.mbn` (auddevext pkg) | `bf78b4e4f34b…` 1 409 024 B | WCD9340 CPE/WDSP fw; Windows-side usage contradicted (see open questions) |
| `qcauddev8180-LIVE.sys` | `2c3f32…` 637 560 B | live-extracted function driver; primary RE target |
| `ProxyAPO.dll` | 301 184 B | effect proxy (above) |
| Dolby DLLs (`DolbyDax3Apo.dll` 1 175 192 B, `DolbyAPOv251/2100/vlldp*.dll` 1.7–2.5 MB, `DAX3API.exe` 2 384 968 B, `Dax3Ref/DapControl/SSID`, `CaptureStreamMonitor`) | — | host APO chain |
| fastrpc payloads (~20 AVS `.so.1` + decoders + `fastrpc_shell_0`) | see agent-10 doc | ADSP offload compute; NOT the render path |
| Cortana/Alexa keyword bins (`surfaceprox_listenext`) | — | voice capture only |
| `AudioResourceConstraints_8180.xml` | 104 rules | session arbitration |
| seven `_cal.acdb` blobs (Bluetooth 109 503 … Headset 350 793, Speaker 269 125) | — | calibration; Speaker_cal is the only 0x45 carrier |
| Windows traffic captures | **none exist on this machine** | ground truth stays static-only |

## Linux-vs-Windows structural deltas

Ordered by how much they could matter to the residual-static / bring-up work:

1. **Codec register transport: SPI4 vs SLIMbus.** Windows reads/writes WCD9340
   registers over `\ _SB.SPI4` at 24 MHz; Linux uses the SLIMbus NGD interface
   element (217:250:1:0), whose reads are unreliable enough to need canary
   validation and the paged-bridge discipline. A SPI transport would remove
   the entire class of read-garbage problems — but mainline `wcd934x` has no
   SPI frontend, so this is a new-MFD-glue project, not a knob.
2. **Descriptor breadth.** Windows opens all four WSA descriptors (left
   1/2/3/7 + right 4/5/6/8) in one session with the frame shaped accordingly;
   Linux activates one DP group. Single-descriptor operation is *known
   audible*, so this is a quality lead, not an audibility gate.
3. **Host DSP shaping.** Windows feeds the ADSP a stream already processed by
   PEQ/regulator/Atmos; Linux sends raw PCM. Any "sounds different from
   Windows" comparison must account for this before blaming transport.
4. **Format declaration vs transport.** Windows declares 48 k/24-bit stereo at
   the endpoint while the WSA link itself stays 1-bit PDM; v18 proved S24_LE is
   unusable on the Linux Q6ASM frontend. Keep S16_LE; the Windows number is
   logical-only.
5. **Speaker-protection state.** Windows runtime loads module `0x1025f`
   calibration (device 0x45 path) while the DriverStore copy disables it
   (3110=00 3111=00 3140=95 313a=ce); v22 reproduced protection-off and it did
   not fix the noise. VI sense stays off until real `0x1025f` cal can load.
6. **Power model.** Windows orders shutdown through a PEP POWERPROFILES graph
   (18 components, 13 packages); Linux approximates with DAPM. Only relevant
   if teardown glitches appear.
7. **Same firmware, different owner.** The ADSP image is byte-identical and
   stubbed on both OSes; all codec/amp control was host-side on Windows too.
   This permanently kills "load the Windows ADSP fw" hypotheses (v15/v16
   already showed stock fw is fine) and validates the apps-side approach.
8. **IRQ delivery.** Same signal, different envelope: ACPI GpioInt on GIO0 pin
   0x100 (Windows) vs hard-wired GIC_SPI 571 (Linux, empirically confirmed).
   Equivalent.

## Confidence + open questions

High confidence (read directly from files, multiple sources agree): the stack
diagram's module list and bindings; every registry value quoted; the ACPI
hierarchy including SPI4@24 MHz; ACDB 0x45→key 0x15200→port 0x4004→ch
0xc0/c1; absence of amp ACPI nodes; absence of captures.

Medium confidence: the claim that qcauddev performs WSA register writes
itself rests on the RE'd entry-point table plus the descriptor tables, not on
a trace (none exists); the "opens all four descriptors" behavior comes from
the static descriptor set plus CLAUDE.md's earlier analysis, not a runtime
observation.

Open questions:

1. `IsWDSPAvailable` conflicts across sources: the INF sets `1`, while the
   runtime-disable finding in memory says the base driver ends up with 0.
   Resolve only if WDSP ever becomes interesting (it is not on the render
   path either way).
2. Does the ADSP receive the SLIMBUS_2_RX *data* via BAM DMA only, or does
   ADCM also push codec-register writes down the same APR pipe? The stubbed
   `AFECdcRegOp` says such writes would land nowhere — strong evidence the
   answer is "BAM data only, all control was host-side".
3. Exact `{key,val}` pair semantics inside `Codec_cal` CDCLUT0 records remain
   partially decoded (agent-4 doc); only key 0x15200's endpoint tokens are
   fully pinned.
4. If SPI4 codec access is ever attempted on Linux, the unknown is whether the
   QUP SE4 firmware/config on SPX accepts raw SPI transfers without Windows'
   setup sequence — untested.
5. Whether Windows' four-descriptor session changes the codec interpolator/
   SWR clocking in a way single-descriptor Linux cannot replicate — the top
   candidate explanation for residual static, and testable only by opening
   both DP groups simultaneously (needs the dual-attach addressing fix first).
