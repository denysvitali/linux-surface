# qcadcm8180.sys — static RE: what it programs for the speaker path (answer: nothing)

Target: `/home/dvitali/Documents/spx-winlive/qcadcm8180-LIVE.sys`
SHA-256 `a4cd624a018f6eef7036c832231c9f195c606d6d287befac734a59f245f93a19`,
ARM64 PE, 682 896 bytes. Analysis was fully static (radare2 + custom ADRP/ADD
xref resolvers + exhaustive immediate-encoding scans); no hardware touched,
no reboots.

## Headline verdict

**qcadcm8180.sys is Qualcomm's "AudioDspCalMgr" — an ACDB calibration-file
manager, not an audio-path programmer.** It contains **zero** AFE/SLIMbus
programming: no transport opcodes, no register payloads, no sample-rate or
packet-size constants, no channel-to-port map, and no 16-vs-24-bit conversion
parameters. Its build path is embedded in the binary:
`Z:\b\WP\AudioDspCalMgr\rel\10.5\src\adcm_driver.c` (VA 0x140017048, duplicate
in INIT at 0x1400b7458).

Everything the driver "knows" about the speaker path arrives at runtime as
bytes parsed out of the ACDB files (`Speaker_cal.acdb`, `Codec_cal.acdb`,
`avs_config.acdb`, `.qwsp`, `acdbdelta`) and is relayed onward verbatim.
This confirms and extends the 2026-06-17 finding
(`spx-afe-cdc-reg-cfg-wire-format-2026-06-17.md`): the bodies of AFE
`CDC_SLIMBUS_SLAVE_CFG` / `CDC_SLIMBUS_SLAVE_DEV_MAPPING` are opaque ACDB
datapool blobs memcpy'd into the SET_PARAM payload — they do not exist as
constants in any apps-side driver.

## Answers to the five priority questions

| # | Question | Answer |
|---|----------|--------|
| 1 | SLIMBUS_SLAVE_CFG / SLIMBUS_SLAVE_PORT_CFG payload layout, byte-exact | **Not in this binary.** No opcode constant, no payload template, no field-setting code. The wire layout is only obtainable from the already-decoded ACDB datapool + the framing RE done previously. |
| 2 | Sample-rate / packet-size / watermark settings | **Absent.** Exhaustive scans for 48000 Hz (`0xBB80`) and all plausible SLIMbus interval/watermark values found zero hits in code or data. |
| 3 | Channel-to-port mapping for channels 0xc0/0xc1 | **Absent.** Neither `0xC0C0` nor `0xC1C0` appears anywhere; the mapping lives in the ACDB blob behind property `0x113b7` (see below). |
| 4 | Is the WCD9340 SWR side configured via ADSP params or apps-side? | Neither via this driver. qcadcm has no SWR/WSA/WCD knowledge at all; it only serves calibration *properties* to whoever asks over APR/RPEN/GLINK. The ADSP-side consumption of those blobs happens inside the DSP firmware, invisible to any apps module. |
| 5 | 16-vs-24-bit rate/format conversion params | **Absent.** No format constants; the Windows 24-bit declaration is a logical endpoint attribute carried in ACDB/topology data, not a qcadcm setting. |

## Zero-hit scan table (both LIVE binaries)

Every encoding variant was scanned: raw dwords, MOVZ/MOVK single and paired
immediates at every legal bit position, ORR wide immediates, packed arrays.

| Constant | Meaning | qcadcm8180-LIVE.sys | qcauddev8180-LIVE.sys |
|---|---|---|---|
| 0x10212 | AFE SLIMBUS_CONFIG | absent | absent |
| 0x10235 | CDC_SLIMBUS_SLAVE_CFG | absent | absent |
| 0x10236 | CDC_REG_CFG | absent | absent |
| 0x10237 | CDC_REG_CFG_INIT | absent | absent |
| 0x10242 | CDC_SLIMBUS_SLAVE_DEV_MAPPING | absent | absent |
| 0x10296 | CDC_REG_PAGE_CFG | absent | absent |
| 0x10312 | ADM NULL_COPP | absent | absent |
| 0x02500100 / 0x02500000 | derived e_addr lsw/msw (PGD/IFD) | absent | absent |
| 0xBB80 | 48000 Hz | absent | absent |
| 0x15200 | SPEAKER_PHONE_SPKR_STEREO codec key | absent | absent |
| 0xC0C0 / 0xC1C0 | channel masks 0xc0/0xc1 pair | absent | absent |

The absence of opcode constants is expected once the architecture is clear:
opcodes are synthesized by the ADSP-facing layer (per the earlier qcauddev
APR reveng), while qcadcm never emits commands at all — it answers property
requests.

## What the driver actually is (anatomy)

### PE layout (radare2 `iS`)

| section | file off | raw size | VA | notes |
|---|---|---|---|---|
| .text | 0x400 | 0x16c00 | 0x140001000 | init/dispatch glue |
| .rdata | 0x17000 | 0x7a00 | 0x140018000 | strings, GUID tables |
| .data | 0x1ea00 | 0x400 raw (vsize 0x15000) | 0x140020000 | mostly bss-like pools/state |
| PAGE | 0x20600 | 0xa00 | 0x140037000 | small pageable helpers |
| PAGEqq6 | 0x21000 | 0x7fa00 | 0x140038000 | main code mass |
| INIT | 0xa0a00 | — | 0x1400b8000 | DriverEntry path |

### Embedded identity strings (all VA-verified)

- `adcm_driver.c` build path @ 0x140017048 (+ INIT dup 0x1400b7458).
- `"apr_audio_svc"` @ 0x1400170c0 — the on-wire GLINK/APR channel name
  (matches `sc8180x.dtsi` and `qcom,apr.yaml`; consistent with the 2026-06-21
  confirmation that this is the ADSP audio channel).
- `\Device\RPEN` UTF-16 @ 0x140017868; `"lpass"` @ 0x1400170b8 and
  0x14001ce20 — GLINK edge/device plumbing.
- ACDB container/LUT names: `QCMSNDDB` @ 0x140003078 and 0x1400664c8 /
  0x140066590 / 0x140066658 / 0x140066720; `WDPRPLUT` @ 0x140002980 /
  0x140002d60; `WGPRPLUT` @ 0x140002f38; `DPROPLUT` @ 0x14005ea50 /
  0x14005ef28 / 0x14005f458; `GPROPLUT` @ 0x14005eca0; combined
  `GLBLLUT/VSTM/ASTM` blob @ 0x14005f7a8 & 0x14005fb70; combined
  `WMCN/CDCLUT0/WSGC/WMID` blob @ 0x14005ff28;
  `"QCMSNDDBCDCLUT0 DATAPOOL"` @ 0x140061b58.
- File names handled: `"acdbdelta"` @ 0x14001c080, `"avs_config.acdb"`
  @ 0x14001cac8, `".qwsp"` @ 0x14001cad8, plus an `AcdbFilePath1..N`
  UTF-16 series from 0x14001c1c0.
- Misc: `"Q6ADM_VCMU_CONTEXT"` ASCII @ 0x14001cde0; `"SMEM"` @ 0x14001ce18;
  `EnableADCM…` UTF-16 @ 0x140017080.

### The DPROP property server — where 0x113b7 lives

A 38-entry u32 property-id table sits at **0x14001c100–0x14001c194**
(file offset 0x1b100):

```
0x113af 0x132b9 0x1314e 0x113b7 0x132ac 0x12e0e 0x113b2 0x12e48
0x113aa 0x12eed 0x12e0f 0x113ab 0x1324f 0x1314d 0x1327e 0x12ef6
0x130fd 0x113ac 0x1327f 0x113a9 0x12efe 0x12e47 0x12e53 0x113ad
0x130de 0x12a4b 0x131a7 0x130df 0x113b3 0x12e11 0x12e10 0x113b6
0x130e0 0x12e54 0x1314c 0x13150 0x13241 0x13240
```

`0x113b7` (the Speaker_cal property that maps codec key 0x15200 → AFE port
0x4004 / channels 0xc0,0xc1) is at **0x14001c10c** and is the *only* 0x1xxxx
dword in the entire file — its value bytes are served from the ACDB datapool,
never stored in the driver.

Handler mechanics observed:

- 0x113b7-family handler @ ~0x14003c6c8: input-size gates
  (`ldr w8,[x20,8]; cmp …; b.hs`), failures trace-logged through helper
  0x140001890 with component-GUID pointer x4=0x14001ca88 and line codes
  0x22/0x47/0x48, returning NTSTATUS -0xc / -8; the success path copies the
  result out through what imports label as `KeQueryPerformanceCounter`
  (import-slot mislabeling; it is the copy-out call).
- Property 0x113b3 handler @ 0x14003c764 builds a 14-byte request
  `{[sp+0x14c]=0x000113b3, [sp+0x148]=input}` and calls 0x140061208,
  returning `[sp+0x154]`.
- Props 0x138c/0x138d @ 0x14003c84c write the u16 pair `{0x000a, 0x0009}`
  and invoke an import as `(x0=x21, x1=2, x2=&pair, x3=2)` — the only
  hard-coded data-bearing write in the server, unrelated to SLIMbus.

### Record builder (the 0x08001000 constant)

Builder at **0x140037248–0x14003726c** constructs 32-byte records over a
linked list (head sentinel at VA **0x140034080**):

```
add  x10, x21, 0x28
mov  w11, 0x1000
movk w11, 8, lsl 16        ; w11 = 0x08001000
ldr  x8, [x20, 8]
ldp  x8, x9, [x8]
stp  x8, x9, [x10, -0x10]  ; record[0..15] = two u64s from node+8
str  w11, [x10], 0x20      ; record[16] = 0x08001000
strb wzr, [x20, 0x29]
str  wzr, [x20, 0x2c]
ldr  x20, [x20, 0x10]
```

Node fields used: +8, +0x18, +0x29, +0x2c; record fields [x21] = byte
offset, [x21+8] = entry offset, [x21+0x10] = index. Input gate
`cmp w2, 0x30`; a four-u32 GUID match loop selects entries. The literal pool
at 0x140037400 carries the NTSTATUS codes 0xc000000d, 0xc0000023, 0xc0000010,
0xc0000184, 0xc0000295. A state enum lives in .data at **0x1400205e8**
(`==2`, `==4` branches) and a callback fnptr at **0x1400205f0**, invoked as
`(3,&a,4,&b,payload)` then `(2,node+0x2c,…)`.

Interpretation of `0x08001000`: written into every record's third dword, it is
consistent with a Q6 address-form tag / region marker in the calibration
blob index, **not** an e_addr (the derived e_addr constants are absent — see
scan table). Do not treat it as a SLIMbus address.

### Object pools and tracing

~20 list heads referenced from code in .data 0x140034000–0x140034400:
0x140034048, 0x140034068, 0x140034080 (the record list), 0x1400340d0,
0x1400340d8, 0x140034120, 0x140034148, 0x140034150, 0x140034178, 0x140034180,
0x140034200, 0x140034260, 0x1400342a0, 0x140034340, 0x140034348, 0x140034360,
0x1400343b0, 0x1400343c8, 0x1400343e0, 0x1400343f8. Example ctor at
0x14006c29c allocates 0x240 NonPaged bytes, failing with 0xc0000184.

WPP-style tracing dominates .rdata references. Helper 0x140001890 takes
(x0=handle/[obj+0x40], w1, w2, w3=line#, x4=component-GUID-table, w5).
GUID tables decoded (little-endian):

- **0x14001ca88** (hottest target, 391 refs; 4 entries):
  f36db503-c029-38c8-c322-886ba036d576 · 28cad0fd-1fd2-3745-c067-2a7247435078
  · 9a16e51e-19dd-375a-0f38-5a86357a5596 · 37e89b53-e2f3-341d-bcdd-f5d2c90c49db.
  A resolver sweep of the surrounding region (0x14001c700–0x14001ca78) shows
  14 further distinct per-function trace GUIDs, each referenced by exactly one
  call site — normal WPP per-function registration, not configuration data.
- **0x14001cd60** (66+35 refs; registered at 0x140007a8c with w1=0x2b):
  8108f26e-eed1-3f3e-a66b-9cb368a6c594 · c98d5aff-063b-5c35-fb2f-90a25f7d2936
  · 74a1d4db-e5a7-573a-0c7b-8448994f3f89.
- Others: 0x14001cdc0 (87), 0x14001cd20 (84), 0x14001cb90/cbc0/ccb0/cbd0/
  cd00/cd30/cd40/cd80/cd90/cca0/cdb0; standalone GUIDs 0x14001cf30 =
  1f4bfb59-e2bf-8f34-b85e-d86ac2b95e91, 0x14001ce08 =
  0cbbcb78-3ee5-2e3c-1d63-e7b09c806349, 0x14001ce28 =
  1e842197-6302-f937-b980-383d8376fb48, 0x14001ce48 =
  3b5cb511-076b-1d36-aedb-7c7374ddd663.

LUT descriptor records at 0x14001ba98+ (16-byte `{u64 0; u64 count<<32|lut_id}`):
(count 4, id 0x683), (2, 0x1dc), (4, 0x5d3), (2, 0x88), (2, 0x1ce), (4, 0x742)
— ACDB LUT inventory, not transport config.

## Implication for the Linux port

Nothing further can be extracted from qcadcm8180.sys. The authoritative sources
for the speaker-path payloads remain:

1. **The ACDB decode** — `scripts/spx-acdb-decode.py` and its output
   (`/tmp/spx-acdb-decoded.json`): property 0x113b7 blob, CDCLUT0 key 0x15200
   pages/tokens, and the datapool bytes that become SLIMBUS_SLAVE_CFG /
   DEV_MAPPING bodies.
2. **qcauddev8180.sys framing RE** — ADM open 0x10327, MATRIX_MAP_ROUTINGS_V5
   0x10325, AFE_PORT_DEVICE_START 0x1020c ordering, and the SET_PARAM v3
   header (16-byte instance hdr) documented in
   `spx-afe-cdc-reg-cfg-wire-format-2026-06-17.md`.
3. **The ADSP firmware itself** for anything below the APR boundary (it owns
   the actual WCD9340/SWR register writes; the apps side never issues them).

Any teammate still hoping to find "the SLIMbus config" inside qcadcm should
stop: this binary only locates, parses and serves the calibration bytes.
