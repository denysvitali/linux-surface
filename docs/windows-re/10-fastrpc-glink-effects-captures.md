# Windows RE 10 — fastrpc, glink dir, effects/APO chain, existing captures

Agent 10 of 10. Lanes nobody else covered: (a) qcadsprpc userspace/fastrpc,
(b) additional audio binaries in the DriverStore, (c) audioendpoint + effects
chain, (d) hunt for real Windows traffic captures on disk, (e)
`~/Documents/spx-winlive/glink/`.

Headline: **no capture of real Windows audio traffic exists anywhere on this
machine**, and nothing in these lanes touches the speaker data path — except
one actionable item: the qcadsprpc INF ships a **boot-enabled WMI autologger**
that would have captured fastrpc (not audio) traffic had Windows ever run with
it. The Dolby APO XML files are new primary evidence that Windows applies
**host-side DSP processing to the internal speaker stream** before it reaches
the ADSP.

## Fastrpc findings

Package `qcadsprpc8180.inf_arm64_9408d6cb3c14fe26/` (all sizes bytes):

| file | size | role |
|---|---|---|
| qcadsprpc8180.sys | 130240 | kernel fastrpc driver, ACPI\QCOM0460 |
| libadsprpc.dll / libsdsprpc.dll / libcdsprpc.dll | 136920 each | user-mode RPC stubs → `%SystemRoot%\System32` |
| libadsprpcarm32.dll / libsdsprpcarm32.dll / libcdsprpcarm32.dll | 103936 each | 32-bit x86 emulated variants → System32 |

`qcadsprpcd8180.inf_arm64_5aeb0c19e2d61f7c/`: "Audio RPC Daemon" driver only
(no DLLs), bound to **ACPI\QCOM048A**; its optional device ACL section is
commented out.

Registry (from the INF, all under `HKR,ARPC\SMMU`):
- `FastRPCADSPSidInfo` = SIDs **0x1b23, 0x1b24, 0x1b25** (three ADSP contexts),
  `FastRPCADSPAridBase` = ARID bases `0x17030010/11/12`,
  `FastRPCADSPCbIndex` = 3 entries.
- `FastRPCCDSPSidInfo` = SIDs **0x1441–0x1448** (eight CDSP contexts), ARID
  bases `0x17030000/05/06/13/19/1F`, cb indexes 0x21-0x28.
- Cross-check: our q6asm mem-map fix uses SID 0x1b21 for the apps PCM domain;
  fastrpc owns the *next three* SIDs (0x1b23-25). The two mechanisms are
  separate SMMU contexts and do not collide.
- Security descriptor grants access to SYSTEM, Administrators and two
  S-1-5-80-* service SIDs (the audioservice/sensors daemons), i.e. fastrpc is
  service-reachable but not arbitrary-app reachable.

**Does any speaker-audio function route through fastrpc? No.** Fastrpc is an
*offload compute* channel: an app mmaps buffers, calls into a DSP-side `.so`
via `fastrpc_shell_0`. The payloads shipped on SPX are in
`surfaceprox_subextadsp.inf_arm64_c641730723c4cdc5/ADSP/`:

- `fastrpc_shell_0` — the ADSP-side dynamic loader itself.
- `libsysmon_skel.so`, `libsysmondomain_skel.so`, `libstabilitydomain_skel.so`,
  `libsysmonquery_skel.so` — sysmon/stability telemetry skeletons (the actual
  fastrpc consumers).
- ~20 AVS/voice modules: `fluence_{ef,pro_vc,pro_vr,bs,sm,voiceplus}_module.so.1`,
  `smecns_v2`, `mmecns`, `ffv_module`, `AudioContextDetection.so.1`,
  `AudioSphereModule.so.1`, `VoiceWakeup_V2_Module.so.1`.
- Media decoders (WmaStd/WmaPro/Alac/Vorbis/Ape/Flac/Heaac/EtsiEaacPlus/
  EtsiAmrWbPlus/Ldac `.so.1`) plus `CFCMModule`, `SVACmnModule`, `SAPlusCmnModule`.
- `map_SHARED_LIBS_*.txt` / `map_AVS_SHARED_LIBS_*.txt` — build manifests whose
  paths prove these are the ADSP image's own dynamically loaded modules
  (`1000.adsp.prod`), staged by the INF next to `qcadsp8180.mbn`
  (sha256 `2703ceb6a8bd…` = byte-identical to Linux's stubbed stock fw).

None of these implement AFE/SLIMbus/SoundWire transport or WSA control. The
decoders are for *compressed offload* sessions (which Linux never opens);
Fluence/CNS are voice-capture chains. The speaker render path stays entirely
inside the ADSP firmware + kernel APR/GLINK drivers. Fastrpc = dead end for
speaker work, but the SID map above is worth keeping for any future
compute-offload experiment.

**Autologger finding:** the qcadsprpc INF enables, at boot,
`HKLM\SYSTEM\CurrentControlSet\Control\WMI\Autologger\adsprpc`
(GUID `bb6ddbab-2b34-4d77-aa07-8c9f05822cfd`, Start=1, level 5, flags 0xFF,
provider `{09533D70-822C-4A34-B3AA-970714567089}`, LogFileMode 0x400 =
sequential file) and a second `adsprpcd` autologger in the rpcd INF. Had the
user ever captured `C:\Windows\System32\LogFiles\WMI\adsprpc.etl` off a Windows
install, it would contain fastrpc session traffic. It would **not** contain
audio register writes (fastrpc ≠ AFE path). No such .etl exists locally.

## glink dir inventory

`~/Documents/spx-winlive/glink/` is **not captures** — it is the live-extracted
driver set from the 2026-06-17 GCS/GLINK session:

| file | size | identical to FileRepository copy? |
|---|---|---|
| qcauddev8180-LIVE.sys | 637560 | yes (same size; sha256 `2c3f32…` recorded in CLAUDE.md) |
| qcadcm8180-LIVE.sys | 682896 | yes |
| qcslimbus8180-LIVE.sys | 184592 | yes |
| qcglink8180.sys | 221136 | FileRepository copy not present separately |
| qcrpen8180.sys | 112800 | same |

Top level of `~/Documents/spx-winlive/` additionally holds the seven ACDB blobs
(Codec/Global/Hdmi/Bluetooth/General/Handset/Speaker `_cal.acdb`, 9–350 KB)
plus duplicate copies of the two LIVE .sys files. These binaries were the
input to every prior static RE pass (agent lanes 1–7); they contain no runtime
data.

## Effects/APO chain

The Windows playback chain for the internal speakers has **two host-side CPU
processing stages before WaveRT**, both confirmed from package contents:

1. **ProxyAPO (Qualcomm miniport's effect proxy)** —
   `surfaceprox_audmini.inf_arm64_f6e0b3707e5d358c/ProxyAPO.dll` (301184 B) +
   `qcaudminiport8180.sys` (765976 B, portcls Wave/Topology miniport, imports
   only portcls/WDF/WppRecorder — no qcauddev linkage). INF wires
   `FX\0`/`EP\0` CLSIDs for `TopologySpeaker` (and UsbHs/BthHfp/Handset/MicArray
   topologies) to ProxyAPO via `PKEY_FX_Association = KSNODETYPE_SPEAKER`.
   Exports `CProxyAPOEFX`/`CProxyAPOMFX` (endpoint + mode effects). This is the
   thin proxy that forwards property sets toward the DSP-side effect engine.
2. **Dolby Atmos DAX3 (OEM extension)** —
   `dax3_ext_qc_dolbyatmos_dolbyaccessoem.inf_arm64_6ae12f3e966838f2/` +
   `dax3_swc_aposvc_arm64.inf_arm64_68a721b8abfa02c6/`:
   - `AUDD_DEV_042C_SUBSYS_CLS08180_ADCM_SUBSYS_CLS08180.xml` — the OEM tuning
     blob matched to hardware id `AUDD\VEN_QCOM&DEV_042C&SUBSYS_CLS08180`
     (**Surface-specific**: SUBSYS_CLS08180 is the Surface subsystem string).
     Its `internal_speaker` endpoint declares **fs="48000", total_count=2,
     front_count=2, Left output_route=0, Right output_route=1, delay=0** — an
     independent confirmation of the stereo/48 kHz logical endpoint shape we
     already use.
   - Speaker profile enables `speaker-peq-enable=1`,
     `regulator-speaker-dist-enable=1`, virtualizer angles, `sbf_eq_enable=0`.
   - `Default_settings.xml`: `<DolbyEnabled endpoint="internal_speaker"
     spatial_audio="on/off" value="true"/>` and default profile "movie" →
     **Atmos/virtualizer processing was ON for the internal speakers by
     default**; `full_dsp_support=false` means the heavy lifting runs as a
     host APO, not inside the ADSP.
   - DLLs: `DolbyDax3Apo.dll` (1175192), `DolbyAPOv251/2100/vlldp{,120,130,140}.dll`
     (1.7–2.5 MB each), `DAX3API.exe` (2384968), `Dax3Ref.dll`, `Dax3DapControl.dll`,
     `DAXSSID.dll`, `CaptureStreamMonitor.dll`.
   - Microsoft inbox APOs (`wdmaudioapo.inf`): WMALFXGFXDSP (Loudness EQ /
     bass boost) registered but not Surface-bound; `c_apo.inf` is just the APO
     device class; `audioendpoint.inf` is Microsoft's null-driver class for
     `MMDEVAPI\AudioEndpoints` — it creates no policy and holds no Surface data.

Relevance to the static problem: APOs run before WaveRT and cannot inject noise
into an otherwise clean stream; they only change content. But if we ever want a
"Windows-equivalent" reference tone, note Windows fed the ADSP a stream already
shaped by PEQ + loudness regulator + Atmos virtualizer — meaning the ACDB
speaker calibration was tuned for that pre-shaped signal, not for raw sine.
For pure bring-up this changes nothing; keep APOs out of the comparison.

## Existing capture catalog

Result of sweeping `/home/dvitali/Documents`, `/tmp`, `/home/dvitali/Downloads`,
kernel `docs/`, `runs/` and the Claude memory dir for captures/ETW/WinDbg
artifacts:

- **No `.etl`, no WinDbg logs, no crash dumps, no GLINK/APR packet dumps exist
  anywhere on disk.** `docs/spx-gcs-windows-capture.md` is only the *plan*
  (Tiers 1–3: WPP trace, WinDbg bp on the qcauddev GCS fnptr at +0x12498, static
  RE fallback); its target directory `~/Documents/spx-trace/` was never created
  — Tier 1/2 were never executed on Windows.
- `docs/traces/stream-silent-20260727.txt` (14 KB): the only traffic capture in
  the tree — **Linux-side** kprobe record of 256 SoundWire writes during one
  silent stream. Structurally correct port sequence; used as the reference
  trace in CLAUDE.md.
- `runs/` (guarded boot artifacts) contains no Windows data.
- Memory notes `spx-gcs-glink-channel-names-2026-06-17.md` etc. record the
  *failed probing attempts* (200+ guessed GLINK channel names; the one live
  probe of `g_glink_ctrl` crashed the ADSP) — negative evidence only.
- The `netwmbclass`/`networkprivacypolicy` hits from the name-based sweep are
  Wi-Fi drivers, false positives.

Conclusion: reconstructing Windows ground truth remains purely static RE. The
only untried capture avenue is running the Tier-1/Tier-2 plan in
`docs/spx-gcs-windows-capture.md` on a Windows boot — which requires booting
Windows on this machine and is a user decision.

## Other artifacts

- `surfaceprox_audminiext.inf_arm64_2ff1c4a397bcaf7a/` — INF-only "extension"
  package matching `AUDD\VEN_QCOM&DEV_042C&SUBSYS_CLS08180` (Surface) and
  `SUBSYS_CLSA8180`; sets only peakmeter poll intervals (0xa ms) per wave pin.
  No binaries. Cosmetic.
- `surfaceprox_auddevext.inf_arm64_e3a905a254bddc9a/qcwdsp8180.mbn`
  (sha256 `bf78b4e4f34b…`, 1409024 B) — WCD9340 onboard CPE/WDSP (Tensilica
  Xtensa) firmware. Already ruled out by memory note
  `spx-adsp-firmware-windows-vs-linux.md`: base driver sets
  `IsWDSPAvailable=0`, so Windows disables the codec-internal DSP. Not the
  speaker path.
- `surfaceprox_listenext/` — Cortana/Alexa keyword models (`en-US-Cortana.bin`
  etc.) for the capture/voice-activation path; irrelevant to render.
- `surfaceprox_audmini.../AudioResourceConstraints_8180.xml` — 104 consumer
  rules limiting concurrent AudioSessions (max 8) and OffloadRestrictions
  streams (max 2); documents how Windows arbitrated phone call vs media vs
  keyword detector sessions. No register-level content.
- `surfaceprox_subextcdsp/qccdsp8180.mbn` — compute DSP firmware, not audio.
- No GPIO-expander or sensor driver touches the amp enable lines; amp power
  stays inside the WCD9340 GPIO bank as established.

## Relevance assessment

| lane | verdict for speaker bring-up |
|---|---|
| fastrpc | Dead end for render path; keep SID table (ADSP 0x1b23-25 / CDSP 0x1441-48) for future offload experiments |
| glink dir | Already-consumed static RE inputs; no new data |
| APO/effects | Two host-side stages (ProxyAPO + Dolby DAX3, PEQ+regulator+virtualizer, default ON); explains ACDB tuning target; no bearing on static |
| captures | None exist; Windows ground truth stays static-only unless user boots Windows and runs docs/spx-gcs-windows-capture.md Tier 1/2 |
| other packages | auddevext WDSP disabled by Windows itself; listen/constraints irrelevant |

## Confidence + open questions

High confidence (direct file reads): fastrpc payload inventory, absence of any
capture artifact, APO package contents and registry wiring, glink dir identity,
WDSP-disabled fact.

Medium confidence: exact equivalence between `-LIVE.sys` copies and their
FileRepository counterparts rests on byte-size equality plus the previously
recorded qcauddev sha256; a full sha256 pass over all four pairs was not run.

Open questions for the team:
1. Does the Dolby `output_route 0/1` mapping correspond to AFE ports 0x4004 /
   MP4 ordering? (Agent 7's stack map should correlate; not resolvable here.)
2. Was the adsprpc autologger ever flushed on the user's Windows install
   (would need a look at `C:\Windows\System32\LogFiles\WMI\` there)? Low value
   for speakers either way.
3. If Windows ground truth becomes blocking again, the cheapest new evidence
   is still Tier 1 of `docs/spx-gcs-windows-capture.md` (5-minute WPP trace on
   a Windows boot), not anything left on disk here.
