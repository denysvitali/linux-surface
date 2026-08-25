# 05 — ADSP firmware: AFE / SLIMbus strings analysis

Targets:
- `/lib/firmware/qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn` (stock, sha256 `2703ceb6...`, build `ADSP.HT.5.1-00494-SC8180X-1`, Q6 build Aug 2019, OEM `xbx-disri-01`)
- `/lib/firmware/qcom/msft/surface/pro-x-sq2/qcadsp8180-win.mbn` (sha256 `09c06fe8...`, build `ADSP.HT.5.1-00751-SC8180X-1`, Mar 2023, CRMBuilds path)

**The two images are NOT identical** (different sha256, different builds). Both were analyzed.
Note: the live stock file is byte-different from `qcadsp8180.mbn.STUBBED-BACKUP` in the same
directory (different string counts) but still contains `AFECdcRegOp_stub.cpp` strings — i.e.
the codec-register op is STILL a stub in both images; only surrounding modules differ.

## Q1 — SLIMbus controller/data-path code

### Evidence

| string | offset (stock) | interpretation |
|---|---|---|
| `AFESlimbus` | `8a2de0` | AFE slimbus device driver present |
| `AFESlimbusDriver.cpp:Failed to open data channels for port id 0x%x` | `a1fb6c` | real SLIMbus data-channel open path exists |
| `AFESlimbusDriver.cpp:SLIMbus multi end point supported/not supported` | `a1fbb8`/`a1fbf0` | multi-EP resource-group allocation logic |
| `AFESlimbusDriverUtils.cpp:Failed to allocate master port...max end points` | `a1fc8c` | master-port allocator with EP limits |
| `AFESlimbusDriverUtils.cpp:Failed to do ReConfigNow()` | `a1feec` | mid-stream reconfig supported |
| `SlimBusConfig.c:[DevId] Driver Initialization (master:%d)(protocols:0x%x)` | `a12ba4` | full SlimBus master core driver |
| `SlimBusMaster.c:Set datashift workaround bit (port %d)` | `a14b30` | per-port data-shift workaround |
| `SlimBusBamLib.c:BAM pipe transfer ... invalid data shift` | `a150ac` | **BAM-Lite data path** used for audio samples |
| `LPASS_AUD_SB_SLIMBUS_BAM_LITE` / `LPASS_QCA_SLIMBUS` | `1b61f`/`1b675c` region | NPA clock/power nodes for AUD + QCA slimbus cores |
| `slimbus_qmi` / `SlimBusQmiSvc` | win `7f9ec1`/`89ecf0` | win image exposes slimbus control over QMI |
| `[INFO] Slimbus device is being opened (client:...)` | win `899f18` | win has a slimmer SlimBus driver, no `.c` filenames |

Counts: stock `slimbus`=218 hits vs win=54; stock has full `SlimBus{Config,Master,Msg,Qurt,BamLib}.c`
debug strings; win keeps only service names (`SlimBusMsg`, `SlimBusMaster`, `SlimBusQmiSvc`) and
HWIO/NPA/clock messages — release build without file:line strings.

### Answer

Yes. The stock ADSP contains a complete SLIMbus **master** stack: AFE-level device driver
(`AFESlimbusDriver*.cpp`) on top of a Qualcomm SlimBus core driver (`SlimBusConfig/Master/Msg/
Qurt/BamLib.c`) using **BAM-Lite** pipes for the audio data path, plus NPA nodes for both the
AUD and QCA slimbus cores. The win-era image carries the same functionality but stripped of
file-name debug strings.

### Confidence

High for existence of the code path. Medium for how it is reached at runtime (the AFE CDC-reg
op that would drive WCD934x registers is stubbed in BOTH images).

## Q2 — PDM/SoundWire/clock logic in AFE

### Evidence

| string | offset | interpretation |
|---|---|---|
| `\bpdm\b`, `\bswr\b`, `\bwsa\b`, `\bmclk\b`, `interpol*`, `fsync` word matches | none | **zero hits** outside QDSS/TPDM trace-module noise |
| `lpass_audio_core_aud_slimbus_npl_clk` | stock `8caab4`, win `1efbf1` | NPL clock node exists but named under slimbus, not SWR |
| `lpass_audio_core_sw_npl_clk` / `audio_wrapper_sw_npl_clk` | stock `8c6888`/`8caab4`, win `8c9b38` | generic soundwire-class NPL clock present as clock-name token only |
| `AFEHalI2sV3.c` (real) vs `AFEHalI2sV1/V4_stub.c` | stock module list | I2S HAL active; no equivalent `AFEHalSwr*` or `AFEHalPdm*` module exists |
| `AFEHalPcmV*_stub.c`, `AFEHalTdmV1.c` | stock module list | TDM/PCM HALs present; SoundWire/PDM HAL absent |

No string resembling `SWR`, `SoundWire`, `wsa881x`, `pdm_clk`, `interpolator`, `fsync` appears
in either image (word-boundary case-insensitive search, TPDM excluded).

### Answer

No dedicated PDM/SoundWire/WSA driver code in either ADSP image. The only "swr/npl" traces are
clock-name tokens (`lpass_audio_core_*_npl_clk`) consumed by the clock framework. Consistent
with the project's earlier finding: on this platform the WCD9340's *internal* SoundWire master
is driven from Linux (apps side), and the ADSP reaches the amp only via the SLIMbus data path
(AFE port -> SLIMbus channel), not via any ADSP-side SoundWire controller.

### Confidence

High (absence-of-string argument over ~25k strings per image; TPDM false positives excluded).

## Q3 — Stream timing/watermark expectations

### Evidence

| string | offset | interpretation |
|---|---|---|
| `%s, High Watermark Disconnect 0x%08x` | `8af599` | USB-audio class driver watermark event |
| `underrun OUT isoch xfer, slot %d` | `8ae4c4` | USB isoch underrun (not AFE) |
| `AFEDecoder_If.cpp:afe_get_data_from_decoder port_id:0x%x decoder service, underrun` | `a196e0` | AFE decoder underrun reporting |
| `AFEEncoder_If.cpp:afe_get_data_from_encoder ... underrun` | `a1b3ec` | encoder-side counterpart |
| `AFEAancDataHandler.cpp:AANC Buffer overflow. Read pointer Moved. Dropping %d samples` | `97ef00` | sample-drop policy on overflow |
| `MixerSvc_OutPortHandler.cpp:MtMx#%lu: i/p port %lu underflow setup failed` | `a2f87c` | mixer underflow handling |
| `[WARN] Detected port overflow/underflow (client:...)(port: %ld)` | `89b66b` | generic port xrun detection |
| `%s, AFE num_samples_per_virtual_frame %d alignment_multiplier %d expected_num_samples %d` | `8afc6f` | AFE frame/sample-count expectation check |
| `%s, reported_samples %d, samples_per_uf %d, samples_per_f %d, samples_per_si %d` | `8b0575` | per-frame/per-superinterval sample accounting (drift/rate-match domain) |
| `AudioStreamMgr_adsppm.cpp:ADSPPM request latency %lu us by ASM` | `a2e0e4` | ASM requests bus/compute latency per stream |
| `cdc_apr_if.cpp:CDC:Port=0x%x: ISR status 0x%lx, ASM_DATA_EVENT_READ_DONE_V2 [...]` | `a31e20` | READ_DONE events emitted from CDC ISR path |
| `npa_watermark_event(name,...lo_watermark...hi_watermark)` | `1d0c2e` | NPA watermark infra (power, not PCM) |

### Answer

The firmware models streams as sample-count contracts, not period/watermark counts:
`expected_num_samples` vs `reported_samples` per virtual frame / superinterval (rate-matcher),
with underrun/overflow logged per AFE port and sample-drop on overflow. There is **no**
"app must submit N periods ahead" style error string; the host-side pacing obligation is not
expressed as a watermark anywhere in these images. Implication for SPX: the DSP does not
appear to enforce a specific app-side buffer cadence beyond keeping the DMA/SLIMbus pipe fed;
the observed first-stream-only WRITE_DONE behavior is more likely an AFE-port/SLIMbus-channel
lifecycle issue than a host timing contract.

### Confidence

Medium-high. Strings show the checks exist; exact thresholds are constants, not strings, and
were not extracted (out of budget).

## Q4 — TPG / test pattern / diagnostic facilities

### Evidence

| string | offset | interpretation |
|---|---|---|
| `\bTPG\b`, `TestPattern`, `TEST_PATTERN` | none in either image | no AFE test-pattern generator |
| `diagbuf_check_overrun_pattern: Log %04X` | `1de44c` | diag-log buffer overrun fill pattern only (not audio) |
| `pp_sensors.cpp:pp_sns_get_holding_pattern` | `a00b00` | voice-UI sensor holding state, unrelated |
| `AFESidetoneIIR.cpp:Loopback path is not enabled...` | `980c08` | sidetone loopback exists (Rx->Tx within codec), not a tone source |
| `LOOPBACK_CTL_LPASS` + `smp2p_dal_loopback.c` | `1aca9e`/`1cd458` | SMEM/SMP2P loopback transport for diag, not audio |
| `vsm_..._Loopback Module ID detected/enabled` | `a0bea0` region | voice-session loopback module (voice call audio loop) |
| `TONE`/`tonedemod` tokens | various | DTMF/tone demodulation only; `AFEDtmf.cpp` present |

### Answer

**UNRESOLVED / effectively NO**: neither image exposes an AFE-level test-pattern generator or
tone injector that strings reveal. The only self-generated audio paths are DTMF (dial-tone,
voice-domain) and sidetone/loopback routing inside the codec, neither of which injects into a
playback SLIMbus endpoint. Making the ADSP source known data instead of host samples has no
strings-supported mechanism here.

### Confidence

High that no TPG string/module exists; medium overall because a silent diagnostic facility
would not necessarily leave strings.

## Q5 — AFE port config handling hints

### Evidence

Module inventory (unique source filenames matching slim/afe/pdm/swr):

Stock image: `AFESlimbusDriver.cpp`, `AFESlimbusDriverUtils.cpp`, `AFESbMultiEp.cpp`,
`AFECdcPwrCtl.cpp`, `AFECdcRegOp_stub.cpp` (STUB!), `AFECodecHandler.cpp`,
`AFEDeviceConfig.cpp`, `AFEDeviceDriver.cpp`, `AFEDevCommon.cpp`, `AFEPortManager.cpp`,
`AFEPortHandlers.cpp`, `AFERateMatch.cpp`, `AFESampRateConv.cpp`, `AFEDmaManager*.cpp`,
`AFEHalDmaTypeDefaultV7.cpp` (only V7 real, V1-V6+V8 `_stub`), `AFEHalI2sV3.c`,
`AFEHalTdmV1.c`, `AFESwMad.cpp`, `AFEUSBAudioDriver.cpp`, plus `SlimBusBamLib.c`,
`SlimBusConfig.c`, `SlimBusMaster.c`, `SlimBusMsg.c`, `SlimBusQurt.c`, `SlimBusTarget.c`.

Win image subset differs notably: **no `AFECdcRegOp*` at all**, no `AFESlimbusDriver*` /
`AFESbMultiEp*` / SlimBus `.c` files, but retains `AFECdcPwrCtl.cpp`
(`9fd1f0 Failed to Open SLIMBUS core driver`), `AFEDeviceConfig.cpp`
(`9f8fe4 Failed to register with SLIMBUS driver`), `AFESwMad` (48 refs), `SlimBusQmiSvc`,
`sbd_perch_{tx,rx}_intr_o[n]` interrupt tokens (18 refs, same count as stock).

Key config-related strings:

| string | offset | interpretation |
|---|---|---|
| `AFECdcRegOp_stub.cpp:AFE cdc reg access ... is stubbed` (read/multi-read/write/update) | stock `a1c010`-`a1c1b8` | **the codec register-access service AFE offers to apps is a no-op** — confirms prior finding, now string-proven in the live file too |
| `AFECdcPwrCtl.cpp:Failed to Open SLIMBUS core driver` | stock `a40940`, win `9fd1f0` | CDC power control rides the same SLIMbus master driver |
| `AFECdcPwrCtl.cpp:Unable to create/register clock gear event` | stock `a40974+` | codec power follows SLIMbus clock-gear changes |
| `AFE_PARAM_ID_SW_MAD_CFG` / `AFE_SW_MAD_SUCCESS` | stock tokens | software MAD device configurable via param ID |
| `AFE_CONNECT_REQ` / `AFE_HWMAD` | stock tokens | port connect request / hardware-MAD naming |
| `SLIMBUS_MASTER`/`SLIMBUS_SLAVE` device strings | stock `1d1def`/`1d1ece`, win `1d767f`/`1d775e` | slimbus device role enumeration |
| `Slimbus_Master`/`Slimbus2_Master`/`Aif_Master`/`HwRsmp_Master` | win `1dddde+` | win resource-table/PM device names: two slimbus masters (AUD + QCA) |
| `AFEDmaManagerUtils.cpp:Get buffer size called with 0 buffers` | `a1dc94` | DMA manager sizes buffers per port config |

### Answer

Port configuration flows through `AFEDeviceConfig` -> SLIMbus driver registration ->
`AFESlimbusDriver(Utils)` channel/master-port setup, with power controlled by `AFECdcPwrCtl`
over clock-gear events. The one piece Windows apps use to poke WCD registers directly
(AFE CDC reg-op) is a compiled-in stub in this image — so even Windows could not have used the
ADSP to write WSA/WCD registers here, reinforcing the apps-side SoundWire model. The practical
data path for our speakers is: ASM stream -> AFE port (SLIMBUS_x_RX) -> AFESlimbusDriver
channel -> SlimBus master BAM-lite pipe. No PDM/SWR alternative path exists in firmware.

### Confidence

High for module inventory and the stub proof; medium for the exact runtime wiring (no
disassembly performed, budget-bound).

## Incomplete items (UNRESOLVED)

- Exact numeric thresholds for `expected_num_samples` / rate-match constants (needs r2/disasm).
- Whether the win image's slimmer SlimBus driver changes channel-allocation behavior vs stock
  (no disasm done; string surface suggests same functionality, fewer logs).
- No AFE TPG found, but a stringless diagnostic hook cannot be fully excluded.
