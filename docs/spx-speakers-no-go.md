# SPX Speakers Bring-Up: No-Go

> **Update (2026-07-01):** [`spx-wsa-soundwire-no-go.md`](spx-wsa-soundwire-no-go.md)
> documented a register-level no-go on 06-23, but that conclusion was **RETRACTED**
> (see its banner): the 06-29 session showed frame-gen locks from APPS, a WSA
> responds, and the real blocker is a two-amp device-0 enumeration clash — with a
> staged single-amp decisive test. The speakers may yet be reachable from Linux.

> Status: **Blocked** as of 2026-06-21. Internal speakers are architecturally reachable on
> Surface Pro X (Windows proves the path on the same hardware), but on Linux they are blocked
> by a combination of a TrustZone firmware whitelist and a stubbed ADSP firmware image.
>
> **Recommended shipping answer:** Bluetooth audio (BlueZ A2DP/HSP/HFP) or USB-C audio
> (dock or USB dongle). Headphone jack and microphone work natively.

---

## TL;DR

The internal speakers on the SPX are 2x WSA881x class-D amplifiers behind the WCD9340 codec's
internal SoundWire bus. The path the hardware uses on Windows is fully understood: ADSP
loads an AudioReach graph over GLINK and drives the WCD9340 codec via AFE CDC register ops.
On Linux, the same hardware is dead because **two independent walls are stacked**:

1. The shipped `qcadsp8180.mbn` on Linux is a **stubbed** build: `AFECdcRegOp_stub.cpp` is a
   no-op, and there is no SoundWire / WSA / WCD codec driver code. Every AFE
   `CDC_DEV_CFG` we send returns `rc=0` and writes nothing to hardware.
2. The non-stub `qcadsp8180.mbn` (extracted from the Microsoft `surfaceprox_subextadsp.cab`,
   v1.0.1980.1, Sep 2023, sha256 head `09c06fe8`) is byte-perfect and correctly signed, but
   `qcom_scm_pas_init_image` returns `res.result[0] = -22` from TrustZone on warm reload and
   cold boot alike. The gate is internal to the locked secure boot and is not observable
   from Linux.

Each wall alone is fatal. Both together are an unconditional no-go with no Linux-side fix.
The lockdown is not SPX-unique — it is the sc8180x ADSP-on-Linux posture across all
publicly supported boards (Primus, Flex 5G, SPX), per the 2026-06-21 sdmshrike /
reference-search follow-up. The static GLINK RE angle is also not yet exhausted:
`apr_audio_svc` is a high-probability on-wire channel name worth probing next.

---

## Background

### Audio architecture on SPX (sc8180x, SQ2)

- **APPS side:** mainline q6adm / q6asm / q6afe / q6routing / sdm845 machine driver.
  q6asm_dai is the ALSA front-end. DMA is via BAM, with a PIO/FIFO NGD fallback.
- **DSP transport:** SLIMbus NGD to the WCD9340 codec (QCOM0425 in the DSDT).
- **Codec reset:** TLMM 143, asserted by the codec device's `_CRS`.
- **WSA881x amplifiers:** 2x class-D smart amps on the WCD9340's *internal* SoundWire
  bus. The ADSP is the SoundWire master; APPS has no direct MMIO path to the
  amplifiers.
- **Topology:** AFE ports feed ADM copps (NULL_COPP 0x10312 default), routed via
  `MATRIX_MAP_ROUTINGS_V5` to the SLIMbus / SoundWire sinks. The speaker graph lives
  entirely in the ADSP.

### What works on this machine (verified, 2026-06-11..2026-06-18)

- SLIMbus audio path: WCD9340 codec reachable over NGD.
- PIO/FIFO NGD transport works (`spx_pio_mode=1`; no BAM/INT_EN needed).
- q6asm PCM playback works once the DMA address is captured at
  `q6asm_dai_hw_params` time (not at open), so the DSP memory-map sees
  `runtime->dma_buffer_p` (see `spx-q6asm-phys-timing.md`).
- Headphone path (analog out via WCD9340) works.
- Mic input works.
- Codec reset: TLMM 143 from DSDT (SQ2 DSDT at
  `~/Documents/acpi/surface_pro_x_sq2/` shows codec QCOM0425 `_CRS` = reset
  TLMM143, INTR `GpioInt 0x100`, SPI4).

### Why speaker bring-up was the obvious next step

Headphone and mic are the only audio outputs on the chassis. Speakers are the headline
output feature, and the hardware (WSA881x) is well-supported on other Qualcomm platforms
running mainline. The work was justified by qcadcm8180.sys reverse engineering showing
the Windows path is normal ELITE APR.

---

## Evidence chain

### 1. WSA881x amps are UNATTACHED on Linux (2026-06-13)

**What we found.** The two WSA881x class-D amps sit on the WCD9340's internal SoundWire
bus. On Linux the ALSA `SpkrLeft DAC` / `SpkrRight DAC` mixer controls exist (the kernel
dailink enumerates the controls because the topology has them), but the amps are not
initialized. Probing the controls:

- `sset` strips the " Switch" suffix; the actual control name is `SpkrLeft DAC` exactly
  (with the trailing space-DAC, no "Switch"). Writing `1` to it does nothing audible.
- No `SoundWire` entries appear in `/sys/bus/soundwire/devices` for the WSA881x devices
  — only the WCD9340 master.
- The WCD9340 codec driver loads, but no SoundWire slave enumeration completes for
  the amp addresses.

**Why it matters.** The amps have a SoundWire slave address on the WCD9340's internal
bus. They are not enumerated because *something* inside the ADSP firmware has to
register them on the bus before the kernel sees them. That something is the
non-stub ADSP image, which is missing.

**Source location.** `spx-audio-wsa-soundwire-unattached.md` (memory file);
`drivers/spx_extras/spx_swr_direct.c` (apps-side probe); `scripts/spx-swr-enum-diag.sh`
(enumeration diagnostic).

### 2. Shipped qcadsp8180.mbn is STUBBED (2026-06-18, triple-verified, DECISIVE)

**What we found.** Reverse engineering the Linux-shipped `qcadsp8180.mbn`:

- Contains `AFECdcRegOp_stub.cpp` — the codec-reg opcode is a no-op stub.
- No SoundWire driver code.
- No WSA881x codec driver code.
- No WCD934x codec driver code.
- AFE `CDC_DEV_CFG` params are accepted with `rc=0` but write *nothing* to registers.
- AFE v3 16-byte instance header breakthrough (q6afe sha `a379b6e8`, `hdr_v3` knob)
  bypasses the silent-drop check but lands in the stub.

**Why it matters.** This is the wall. Even if every apps-side knob is correct, every
register write goes into a function that returns without doing anything. The "ringing
goes nowhere" symptom is confirmed at the firmware level, not just at the wire level.

**Source location.** `spx-firmware-cdc-regop-stub-nogo.md` (memory file) — the decisive
finding. Triple-verified: one RE pass, one dynamic AFE write test, one opcode payload
decompilation.

### 3. GCS / AudioReach path is dead (2026-06-17)

**What we found.** Windows loads the AudioReach speaker graph into the ADSP over GLINK
("GCS", codename "Graphite"). The relevant handlers ARE present in the Linux ADSP firmware:

```
gcs_check_graphite_response       ; opcode family 0x14001..0x1400e
APM_CMD_GRAPH_OPEN   0x01001000
```

But the GLINK responder is **absent**:

- GLINK `g_glink_audio_data` open: `failed to open` (cleanly returned by the ADSP).
- GLINK `g_glink_ctrl` open: ADSP crash at `glink_channel_migration.c:601` (assert).
  `spx_pin_after_qmi` module pin means crash recovery requires reboot.
- V8/V6 handler labels in raw byte search were false-positive matches.
- `spx_rx_topology=0x10000001` BREAKS the stream (`q6adm_open` returns ERR).

**Why it matters.** The GCS bypass is the only remaining path to inject a speaker graph
into a *running* ADSP without replacing the firmware. The path is reachable in principle
(architecture confirmed by qcglink8180.sys RE) but blocked because the GCS server is
dormant on the stub firmware.

**Source location.** `spx-gcs-2026-06-17-fw-findings.md`, `spx-gcs-glink-channel-names-2026-06-17.md`,
`spx-gcs-2026-06-17-qcglink8180.md`; `scripts/spx-gcs-rpmsg-probe.py`.

### 4. TrustZone PAS whitelist (2026-06-19..2026-06-20)

**What we found.** The non-stub `qcadsp8180.mbn` (extracted from Microsoft
`surfaceprox_subextadsp.cab` v1.0.1980.1, sha256 head `09c06fe8`) is byte-perfect
and correctly signed. It boots cleanly when copied to `/lib/firmware/qcom/msft/surface/pro-x-sq2/`
and warm-reloaded via PAS. The first thing the SCM call does is

```
qcom_scm_pas_init_image(...) → qcom_scm_pas_auth_and_reset(...)
  res.result[0] = -22   ; -EINVAL
```

Five hypotheses for the -22 were investigated and ruled out:

- Incomplete metadata: the file is byte-perfect, SHA matches Windows-driver extraction.
- SHM-bridge artifact: not warm-reload specific — same path on cold boot.
- Cold vs warm difference: confirmed same SMC path on both.
- Cert expiry: cert is not expired (2027 validity).
- Anti-rollback monotonic counter: would have produced a different error code
  (typically -3 / -EPERM, not -22).

Both stub and non-stub images chain to the same Pinewood CA. The local whitelist
interpretation (hash or cert serial stored in RPMB / secure storage) fits the symptoms
perfectly. No Linux-side change (DT, tzmem modes, carveouts, PAS API usage) alters
the -22 result — the gate is internal to the locked TZ.

**Why it matters.** This is the second wall. The non-stub image exists, is correct, is
signed — and is refused. The whitelist is in the QSEE / RPMB and is not rewritable from
APPS Linux.

**Source location.** `docs/spx-speaker-bringup-handover.md` (long-form), `docs/spx-audio-2026-06-11-findings.md`.

### 5. Windows proves the architectural path works (qcadcm8180.sys deep RE)

**What we found.** Reverse engineering `qcadcm8180.sys` and `qcglink8180.sys`:

- ELITE APR opcodes ARE synthesized in code (built via `mov+movk` — raw byte search
  misses them).
- dev 0x45 order:
  1. AFE SET_PARAM CDC_REG/SLIMBUS cfg (`0x10237` / `0x10235` / `0x10233`) — first.
  2. ADM open `0x00010327` (topology carried in data field; NULL_COPP `0x10312` default).
  3. MATRIX_MAP_ROUTINGS_V5 `0x00010325`.
  4. AFE_PORT_DEVICE_START `0x0001020c`.
  5. Apps spkr-prot `0x1025f` / `0x1021d`.
- `0x10326 DEVICE_OPEN_V5` is **absent**.
- **No apps-side SWR/SoundWire MMIO.** ADSP-owns-SWR confirmed by absence of MMIO ranges
  in the qcadcm driver.
- qcauddev GUID `dc424aec-4d0f-414a-8ea6-b33f4ccadf28` (d3=0x414a).
- Architecture: `qcauddev → \Device\GLINK → AUDDSPI query interface → qcglink8180
  → \Device\RPEN → qcrpen8180 → GLINK/SMEM → ADSP`.

**Why it matters.** The path is known to work on this exact hardware. The opcode sequence
is reproducible. The missing pieces are entirely on the ADSP side: the AudioReach graph
load (over GLINK) and the non-stub AFE CDC regop implementation.

**Source location.** `spx-windows-apr-driver-reveng.md` (memory file);
`spx-gcs-2026-06-17-qcglink8180.md`; `spx-afe-cdc-reg-cfg-wire-format-2026-06-17.md`.

### 6. Q6ASM DMA-phys timing fix (2026-06-13)

**What we found.** PCM playback needed the DMA address captured at
`q6asm_dai_hw_params` time (not at open) so the DSP memory-map saw
`runtime->dma_buffer_p`. With the open-time capture, the DSP mapped a wrong/stale
address and the buffer was silent.

**Why it matters.** This is a side-result of the work, not a blocker, but it made
q6asm-based diagnostics (q6asm-dai playback, DMA verification) usable for speaker
diagnostics. Filed here so future explorers don't re-discover it.

**Source location.** `spx-q6asm-phys-timing.md`.

---

## Linux-side firmware package status

External corroboration: the linux-surface `aarch64-firmware` repository
(`linux-surface/aarch64-firmware`) ships `qcadsp8180.mbn` at
`firmware/qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn`.

| Field | Value |
|---|---|
| File size | 10,758,800 bytes |
| SHA-256 | `2703ceb6a8bdfd24097a6edc6406ae29994c4b85c6ef634da254e2d38ec9f40f` |
| Git blob SHA | `c20bd8b38c537f46d6fbd16a92887a7e08d2683f` |
| Local copy (`/lib/firmware/qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn`) | matches |
| Windows-driver-extracted copy (`~/Documents/drivers/FileRepository/surfaceprox_subextadsp.inf_arm64_*/qcadsp8180.mbn`) | matches |
| Last commit touching file | `72fb231f08` (2022-07-11, "Add all required firmware") |
| Files updated since | none |
| README / changelog mentions of ADSP | none (README mentions SPX SQ1/SQ2 firmware generally and states firmware rights "lie with Microsoft and/or Qualcomm", but no per-component ADSP notes, no mention of Pinewood CA / stub / non-stub / speaker support) |
| CHANGELOG file | absent |
| `docs/` directory in the firmware repo | absent |

**Implication.** The community firmware package is byte-identical to what is on this
machine. There is no alternate non-stub image hidden in `aarch64-firmware` for the SPX.
The community is blocked on the same TZ gate we are. Escaping the STUB does not come
from a `git pull` — it requires either a vendor-built non-stub `.mbn` (which would
still hit the same TZ -22) or a third image known to be accepted by this exact SPX
TrustZone (none known).

---

## Why each Linux-side path is blocked

### Apps-side SoundWire register poking — not on critical path

The WSA881x amps live on the WCD9340's *internal* SoundWire bus. The ADSP is the bus
master. APPS has no MMIO path to those registers (`qcadcm8180.sys` has none either;
the absence of any SoundWire MMIO range in the qcadcm driver is the proof). Poking
apps-side registers would be at best a no-op and at worst a bus conflict.

### AFE CDC_DEV_CFG register writes — land in stub

Confirmed: every AFE `CDC_DEV_CFG` we send returns `rc=0` and writes nothing. The
v3 16-byte instance header (q6afe sha `a379b6e8`, `hdr_v3` knob) bypasses the
silent-drop check but lands in the stubbed `AFECdcRegOp_stub.cpp`. There is no
escape on this code path on the shipped firmware.

### GCS / AudioReach — GLINK responder missing

The opcode family is in the firmware (codename "Graphite") and
`APM_CMD_GRAPH_OPEN 0x01001000` is also in the firmware. But the GLINK responder
that the apps-side qcauddev opens (`g_glink_audio_data`, `g_glink_ctrl`) is
absent: one returns "failed to open", the other crashes the ADSP. The GCS server
is dormant. Bypass requires the non-stub ADSP, which is blocked at PAS.

### TrustZone policy — can't be changed from Linux

The PAS whitelist is in QSEE / RPMB and is signed by the Pinewood CA. No userspace
tool, kernel patch, DT change, tzmem mode, carveout adjustment, or PAS API variation
alters the result. The gate is observable only via XBL/TZ logging, OEM JTAG, or
instrumented Windows crash-dump tooling — none of which are available.

### Vendor tooling required — not accessible

- XBL / QSEE logging: not exposed on retail SPX.
- OEM JTAG: not present on retail SPX.
- Windows dynamic capture (ETW / WinDbg on a dual-boot install): would require
  Windows install, and the qcauddev8180 device is in `q_glink_persistent_data_*`
  channels whose wire names are not statically known (200+ brute-force candidates
  all returned `failed-to-open`).

---

## Workarounds (the shipping answer)

These are not "internal speakers" but they are real audio paths that work on retail
SPX hardware today:

- **Bluetooth audio** — A2DP / HSP / HFP via BlueZ. Pairing works; SBC and AAC
  codecs negotiated; output to speakers, headphones, or hearing-aid devices.
- **USB-C audio** — any USB-C dock with audio out, or a USB audio dongle. Class-compliant
  UAC1/UAC2 devices enumerate natively and route through the standard USB audio path.
- **HDMI / DisplayPort audio** — works when an external display is connected with audio
  capability.
- **Headphone jack (3.5 mm)** — works natively via WCD9340 analog out (already verified).

These should be the recommended audio configurations in user-facing documentation.
Internal speakers should be called out as "not supported on Linux" with the no-go
explanation: "the Linux ADSP firmware for this device is a stub; speaker amps
require non-vendor firmware which this device's TrustZone refuses to load."

---

## What would unblock this

In rough order of how realistic each is:

1. **A non-stub `qcadsp8180.mbn` that the SPX TrustZone accepts.** The community
   firmware package is byte-identical to what is locally installed, so this is not
   a `git pull` fix. It would require either:
   - A vendor-built non-stub `.mbn` whose signer is on the SPX whitelist
     (impossible without Pinewood CA access).
   - A third image — for example, from a developer firmware drop — that happens
     to be accepted (unknown).
2. **Vendor-level tooling to observe / modify TrustZone PAS policy.** XBL / TZ
   logging, OEM JTAG, or a Windows crash-dump tool capable of attaching to the
   Q6v5 Secure World. None of these are available on retail SPX.
3. **Windows dynamic capture (ETW / WinDbg).** A dual-boot install could
   instrument the qcauddev8180 driver and learn the actual on-wire GLINK channel
   name. This is the only realistic software-only path to making the GCS
   bypass work — but it is itself blocked on (1) above (the GCS server is
   dormant on the stub ADSP, so even a correct channel name is no use until
   a non-stub ADSP runs).
4. **A board-level fix to the SoundWire bus (electrical, not software).** Has
   been ruled out: the wire-level read failure (`cmd_data=0x0` from the
   codec-internal SoundWire master) is a firmware-side master, not a board
   strap.

---

## Files in this repo that document the journey

### Bring-up

- `scripts/spx-run2-pio-full.sh` — full PIO/FIFO NGD audio bring-up driver
  (what gets headphone/mic working without BAM).

### Diagnostic probes

- `scripts/spx-slim-qmi-probe.py` — SLIMbus QMI enumerator; reads the
  SLIMbus device table from the QMI service.
- `scripts/spx-gcs-rpmsg-probe.py` — opens GLINK channels by name to test
  AudioReach server presence.
- `scripts/spx-swr-enum-diag.sh` — SoundWire enumeration diagnostic; reads
  the WCD9340's internal SoundWire slave table.
- `scripts/spx-spkr-probe.sh` — speaker-path probe; iterates the Spkr*
  mixer controls and reports register-level response.

### Replay / sequence

- `scripts/spx-spkr-trigger.sh` — replays a single Windows-style AFE
  opcode sequence against the running ADSP.
- `scripts/spx-spkr-bringup-seq.sh` — full Windows AFE / ADM / MATRIX
  sequence replay in correct order.
- `scripts/spx-spkr-replay.sh` — older replay script (v1).
- `scripts/spx-spkr-replay-v2.sh` — newer replay script (v2); superseded
  by `spx-spkr-bringup-seq.sh`.
- `scripts/spx-spkr-replay-v2.sh.BROKEN-DO-NOT-RUN` — broken copy retained
  for historical reference; do not run.

### ACDB tools

- `scripts/spx-acdb-decode.py` — decodes the WCD9340 ACDB blobs.
- `scripts/spx-acdb-extract.py` — extracts ACDB blobs from the ADSP
  firmware image.

### Stage7 experiments (Q6ASM + GCS bypass path)

- `scripts/spx-stage7-bypass-step0.sh` — establishes the GLINK handle
  (initialization step).
- `scripts/spx-stage7-bypass-step4.sh` — sends the AudioReach graph
  via the GLINK handle.
- `scripts/spx-stage7-step4-mask-test.sh` — masks variants of the
  graph payload to find which fields the server rejects.

### Postboot check

- `scripts/spx-postboot-audio-check.sh` — runs at boot via the
  `spx-audio-postboot-check.service` systemd unit; verifies
  SLIMbus / q6asm / q6afe are alive.

### Other in-tree artifacts

- `drivers/slimbus/slimbus-qmi-probe.c` — QMI probe driver (kernel
  module), loaded alongside `slimbus_qcom` to expose the SLIMbus
  QMI channel to userspace.
- `drivers/spx_extras/spx_swr_direct.c` — apps-side SoundWire register
  poke driver (proved the apps-side path is a no-op; kept for
  diagnostic value).
- `drivers/spx_extras/Kconfig`, `drivers/spx_extras/Makefile` —
  kconfig / kbuild glue.
- `arch/arm64/boot/dts/qcom/sc8180x-wcd9340.dtsi` — audio DT overlay
  for the WCD9340 codec (TLMM 143 reset, SLIMbus port mapping).
- `systemd/spx-audio-postboot-check.service` — systemd unit that runs
  `scripts/spx-postboot-audio-check.sh` after boot.
- `build-install.sh` — convenience build / install script for the
  full SPX kernel + extras.

### Adjacent docs

- `docs/spx-audio-2026-06-11-findings.md` — long-form audio
  diagnostic log.
- `docs/spx-audio-post-reboot.md` — post-reboot recovery checklist
  (also covers the SLIM-NGD MMIO wedge recovery).
- `docs/spx-camera-recon.md` — camera bring-up findings (audio
  sister effort).
- `docs/spx-gcs-windows-capture.md` — Windows-side capture plan for
  GLINK channel name.
- `docs/spx-speaker-bringup-handover.md` — long-form engineering
  handover (the "everything" document); this file is the
  short-form no-go summary.

---

## Known hazards (for the next person)

These are not speaker-specific, but they cost real time when you hit them:

- **NEVER read `171c0000 + 0x2000` (SLIM-NGD MMIO register).** Wedges the CPU.
  Recovery checklist in `docs/spx-audio-post-reboot.md`. Safe windows read
  all-zero after the QMI ack; do not poke outside those.
- **NEVER read `pinmux-pins/pins` debugfs on sc8180x.** Oops leaves the
  pinctrl mutex held — all subsequent GPIO and bind operations enter
  D-state. Reboot-only recovery.
- **Display / boot black screen.** The dispcc vsync clock fix is required.
  The `kms-hook` initramfs needs `pwm_bl` and `leds_qcom_lpg` or the LUKS
  prompt stays black (no backlight). See `spx-display-boot-fix.md`.

---

## References

Memory files (all under `~/.claude/projects/.../memory/`):

- `spx-audio-codec-spi-aqstic.md` — WCD9340 codec is reached over SLIMbus
  NGD; PIO/FIFO NGD transport works.
- `spx-slim-ngd-mmio-hazard.md` — do not read `171c0000+0x2000`.
- `spx-pinctrl-debugfs-oops.md` — do not read pinmux-pins debugfs.
- `spx-audio-wsa-soundwire-unattached.md` — WSA881x amps are UNATTACHED
  on Linux; SpkrLeft/Right DAC controls exist but the amp is not
  initialized.
- `spx-windows-apr-driver-reveng.md` — qcadcm8180.sys deep RE; the
  Windows opcode sequence.
- `spx-gcs-2026-06-17-qcglink8180.md` — qcglink8180.sys / qcrpen8180.sys
  RE; the GLINK/SMEM transport to ADSP.
- `spx-gcs-2026-06-17-fw-findings.md` — GCS opcodes 0x14001..0x1400e
  ARE in the ADSP firmware; "Graphite" codename.
- `spx-gcs-glink-channel-names-2026-06-17.md` — g_glink_ctrl /
  g_glink_audio_data / g_glink_persistent_data_{n,i}ld.
- `spx-q6asm-phys-timing.md` — q6asm DMA phys capture at hw_params
  time, not open.
- `spx-afe-cdc-reg-cfg-wire-format-2026-06-17.md` — AFE SET_PARAM
  CDC_REG/SLIMBUS wire format; v3 16-byte header.
- **`spx-firmware-cdc-regop-stub-nogo.md` — THE DECISIVE FINDING.**
  Shipped qcadsp8180.mbn has `AFECdcRegOp_stub.cpp`; no SoundWire /
  WSA / WCD driver code. AFE CDC_DEV_CFG returns rc=0 and writes nothing.
  Triple-verified. This is the single most important file for
  understanding why speakers cannot work on Linux SPX today.
- `spx-display-boot-fix.md` — dispcc vsync clock + kms-hook initramfs
  needs pwm_bl/leds_qcom_lpg.
- `spx-glink-bypass-progress.md` — GLINK bypass progress notes.
- `spx-adsp-firmware-windows-vs-linux.md` — Windows vs Linux ADSP
  firmware comparison (non-stub vs stub).

Adjacent long-form docs in this repo:

- `docs/spx-speaker-bringup-handover.md` — engineering handover (the
  "everything" document).
- `docs/spx-audio-2026-06-11-findings.md` — long-form audio diagnostic
  log.
- `docs/spx-audio-post-reboot.md` — post-reboot recovery checklist.
- `docs/spx-gcs-windows-capture.md` — Windows-side capture plan.

---

## Closing

The work was not wasted. It produced a clear, evidenced understanding of why speaker
support is impossible on Linux SPX today (stub ADSP + TZ whitelist, two independent
walls), and a confirmed shipping path (Bluetooth via BlueZ; USB-C dock / dongle;
HDMI/DP; headphone jack — all working). The diagnostic hooks built up during the
effort (`scripts/spx-slim-qmi-probe.py`, `scripts/spx-gcs-rpmsg-probe.py`,
`scripts/spx-swr-enum-diag.sh`, `drivers/slimbus/slimbus-qmi-probe.c`,
`drivers/spx_extras/spx_swr_direct.c`) remain usable: if anyone ever produces a
non-stub `qcadsp8180.mbn` that the SPX TrustZone accepts, the existing probes will
verify the AudioReach graph load and the AFE CDC register path against the new image.

Until then: Bluetooth, USB-C, HDMI, headphone jack. Not internal speakers.

---

## 2026-06-21 follow-up

### sdmshrike / other sc8180x reference search

**What we did.** Searched the public linux-msm / kernel.org / vendor trees for every
sc8180x board (Primus reference, Lenovo Flex 5G, SPX, Realme/Oppo sdmshrike, Acer
Coolbo) and compared firmware blobs, PAS resource tables, and TZ chains. Also pulled
the linux-msm.github.io mainline status page and the WOA-Project 8180_CAS changelog.

**What we found.** All three publicly supported sc8180x boards (Primus, Flex 5G, SPX)
share the same `qcom,sc8180x-adsp-pas` binding, the same `sm8150_adsp_resource`
(pas_id=1), the same `qcom_scm_pas_prepare_and_auth_reset` call path, the same Pinewood
CA, and the same shared chipset firmware. There is exactly ONE public
`qcadsp8180.mbn` (sha256 `2703ceb6…`, last touched 2022-07-11) and it is the stub.
Nobody — not a single linux-msm user on Primus, Flex 5G, or SPX — has reported a
working ADSP sound card. The linux-msm status page lists "all audio (… ADSP
Elite/AudioReach)" as N/A globally for sc8180x.

**Whether SPX is uniquely locked.** NO. SPX is not uniquely locked at the TZ/PAS
layer — it is uniquely *tested*. The Pinewood CA is chipset-wide, not OEM-specific.
The "stub firmware + TZ whitelist" combination is a Microsoft/Qualcomm commercial
decision shipped to all sc8180x retail SKUs (we just have no public report of
Primus or Flex 5G even attempting to load a non-stub).

**Implication.** Stop framing this as an SPX-specific lockdown. The problem is
chipset-wide. A non-stub `qcadsp8180.mbn` accepted by the SPX TZ is unlikely to come
from another sc8180x board because no other board publishes a non-stub either. The
only realistic vector is a Lenovo / Microsoft / Qualcomm internal image extracted
from a driver `.cab` and signed by the same Pinewood CA — which is precisely what we
already tried (the `surfaceprox_subextadsp.cab` extraction) and hit the -22.

### GLINK channel name — static RE angle

**What we did.** Re-checked the `qcadsp8180.mbn` string table against the Linux
binding `qcom,glink-channels = apr_audio_svc` in `arch/arm64/boot/dts/qcom/sc8180x.dtsi`
line 3809, and against `Documentation/devicetree/bindings/soc/qcom/qcom,apr.yaml`.

**What we found.** `apr_audio_svc` is present in ALL THREE locations that must agree
for a GLINK channel to open: the ADSP firmware, the kernel DTS, and the documented
binding. The 200+ brute-force candidates tried on 2026-06-17 focused on the
`g_glink_*` names from `qcauddev8180.sys` `.data` — but those are *local qcauddev
handles* (Win32 device paths inside the user-mode audio service), not the on-wire
GLINK channel name. The wire name is what the ADSP firmware registers during APR
init and what the kernel matches via `qcom,apr-v2`; per the YAML binding and the DTS
it is `apr_audio_svc`. Other strong in-firmware candidates: `apr_voice_svc`,
`apr_apps2`, `apr_cdsp_adsp`, `apr_sdsp_adsp`.

**Whether the static angle is exhausted.** NO — it was mis-targeted. The static
angle is not exhausted; the candidate set was incomplete. `apr_audio_svc` was
likely never tried.

**Recommended next attempt.** `sudo python3 scripts/spx-gcs-rpmsg-probe.py
--channel apr_audio_svc` on the next probe boot, then `apr_voice_svc`, then
`apr_apps2`. If all three fail, dump the full firmware string table and grep
`[a-z_]{4,32}` excluding common C runtime / path / clang symbols to enumerate the
on-wire registration names exhaustively.

### Update to "What would unblock this"

The Windows-dynamic-capture path (#3) is now the *only* remaining software-only
unblock that the static angle has not already reached: `apr_audio_svc` is
high-probability and trivially testable without Windows. If `apr_audio_svc` opens
cleanly, the GCS server still won't respond (the GCS responder is dormant in the
stub firmware), so the *unblock* still requires the non-stub ADSP at PAS (#1) — but
the *channel-name* prerequisite for the GCS bypass will be retired. The TZ-policy
and non-stub-firmware walls remain unchanged.

---

Last updated: 2026-06-21 (initial no-go), 2026-06-21 (sdmshrike + GLINK follow-up)
