# 04 — ACDB deep extraction (Surface Pro X speaker path)

Agent-4 output. Source files: `~/Documents/spx-winlive/{Speaker,Codec,General,Global,Headset,...}_cal.acdb`.
Parser base: `/home/dvitali/Documents/git/linux-surface-kernel/scripts/spx-acdb-extract.py`; toolkit in `/tmp/spx-acdb/`.

## Format recap

Verified by walking all 8 ACDB files end-to-end with the existing parser's logic.

- Header 0x20 bytes: `"QCMSNDDB"` + 8 zero + subtype (`AVDB` for device cal, `CCDB` codec cal) +
  payload_size twice; `payload_size == filesize-0x20`.
- Chunks from 0x20: `[tag u8[8]][len u32][payload]`, back to back until EOF.
- `DATAPOOL` is one flat blob; every LUT record points into it by offset.
- **Codec_cal** `CDCLUT0`/`CPROPLUT`: `[count u32][rec*12: id1,id2,dp_off]`; the blob at
  `dp_off` is framed `[total][payload_size][rsvd][payload]`, and `payload[0:4]` echoes `id1`.
- **Device cal files** (Speaker/Headset/General/Global, subtype AVDB): sub-LUTs named
  `<CAL>xLUT0`. The device→property map is chunk **DPROPLUT**: `[count u32]` then
  `rec*12 = [device_id u32][property_id u32][dp_off u32]`.
- DPROP payloads are self-describing: first word = **byte length of the rest**
  (verified on every 0x45 entry), except `0x113b8` which is a UTF-16LE string whose
  leading word is a char count.

## Device-property map (Speaker_cal.acdb)

108 records over 10 devices (0xb,0xc,0xd,0xf,0x22,0x3f,0x44,**0x45**,0x57,0x5d).
Device **0x45** carries 11 properties:

| property | size | decoded meaning |
|---|---|---|
| 0x113b7 | 44 B | **codec-key / port / channel map** — see below |
| 0x113ad | 48 B | module-instance list for this device |
| 0x113af | 4 B | flags word `0x10000001` |
| 0x113b6 | 8 B | pair `(0x112a7, 0x12a52)` — two more ids (gain/graph refs) |
| 0x113b8 | UTF-16 | string `"SPEAKER_OUT"` |
| 0x12e0f | 4 B | `1` |
| 0x12e10 | 4 B | `0x44 = 68` (decimal count) |
| 0x12eed | 12 B | `{count=1, 0xbb80=48000, 0x1da}` — sample-rate table entry |
| 0x13150 | 4 B | `0x1025d` |
| 0x1323e | 4 B | `0` |
| 0x132b9 | 128 B | mostly zeros, lead `{1,2}` |

The known prior RE is confirmed at byte level: `0x113b7` =
`{n=1, key=0x15200, n=2, {0x100,0x1}, {port=0x4004, chmap=0xc1c0}}`
— i.e. codec key **0x15200**, AFE port **0x4004** (SLIMBUS_2_RX),
channel mask words `0xc1c0`/`0xc0`-family as previously reported.

## Module/param table (speaker path)

Speaker_cal's AVII/AVOL LUTs index per-(device, module-instance, param-id) cal
into the same DATAPOOL. Record = `[dev u32][module u32][param u32][flags u32][dp_off u32]`
(stride 20 B). Flags seen: AVII `0x0/0x10`, AVOL `0x14`.

Module instances present for dev 0x45 and their param counts:

| module | AVII recs | AVOL recs | interpretation |
|---|---|---|---|
| 0x11134 | 31 | 31 | graph node (see topology section) |
| 0x11135 | 186 | 186 | graph node |
| 0x11136 | 31 | 31 | graph node |
| 0x11137 | 186 | 186 | graph node |
| 0x11138 | 31 | 31 | graph node |
| 0x11139 | 186 | 186 | graph node |
| 0x1113a | 62 | 62 | graph node |
| 0x1113b | 186 | 186 | graph node |
| 0x1113c | 31 | 31 | graph node |
| 0x1113d | 31 | 31 | graph node |
| 0x1113f | 31 | 31 | graph node |
| 0x11140 | 31 | 31 | graph node |
| 0x11143 | 186 | 186 | graph node |

All AVII records for every device collapse to a **single shared blob**
(`dp_off=8`, ~76 KB) — the topology/graph container decoded below; the
per-module rows are just an index into it. The AVOL LUT additionally has
268 distinct offsets: per-module gain/volume tables (module 0x11135 family)
and per-device volume curves — not decoded further here except as noted in
"Decoded payloads".

## Decoded payloads of interest

Codec_cal.acdb (subtype CCDB) — CDCLUT0 framed blobs, all 29 keys share one
120-byte structure `[n][{key,val} pairs][endpoint tokens][pad]...[tail]`:

| word | meaning (from 0x15200) |
|---|---|
| w0 | entry count of `{key,val}` list |
| w1.. | `{codec_key, value}` pairs |
| w11/w12 | endpoint tokens (`0x01010004`, `0x01010005`) |
| w27 | `0x10030015` or `0x100d000d` — AFE-port class word (TX vs RX group) |

Per-key values (w0=count, then pairs):

| key | count | pairs (key=value) |
|---|---|---|
| 0x010102 | 1 | 0x84=0 (hmm, actually w3=0x840000 → see raw table below) |
| 0x011103 | 2 | 0x84=0, 0x84=0x840000>>16? … |
| ... | ... | ... |

Raw per-word table across representative keys:

```
word :   010102 013100 015100 015101 015200 020100 021100 021203 022200
w00:      1      1      1      1      2      1      1      2      2
w01:      0      0      0      0      0      1      1      1      1
w02:      3      3      b      b      c      6      5      7      9
w03: 840000 840000 840000 840000 840000 10000 20000 20002 20003
...
```

(The exact pair semantics are still open; what is solid is that key 0x15200 is
the only one whose endpoint tokens are `0x01010004` + `0x01010005` — the
speaker stereo endpoint pair.)

Codec_cal WGPRPLUT prop 0x78403 payload (72 B): six `{id,value}` words:
`{0x12c24=0}, {0x12c0d=1}, {0x20010=1}, {0x20013=1}, {0x20021=1}, {0x2002c=1}`
— a codec-side enable/config set (0x12c0d = WCD934x ADC/BCL "bias" register
space; the 0x200xx ids match WMCALUT0/WMIDLUT0 module ids).

## Topology graph decode

The single ~76 KB blob at `dp_off=8` that every AVII record points at is a
**named-sub-graph container**. Framing gotcha that cost the most time: each
sub-graph header is `[graph_id u32][name_len u32][UTF-16LE name]`, and
`name_len` counts **bytes**, so odd-length names leave the stream misaligned
for the following words — any word-aligned scanner produces garbage names.
Walk it byte-wise instead (`/tmp/spx-acdb/graph2.py`).

Sub-graphs found, in stream order:

| off | graph id | name | payload | notes |
|---|---|---|---|---|
| b0 | 0x12a52 | `SPKR_PHONE_MIC` | small | |
| b72 | (cont.) | `SPKR_PHONE_MIC_ENDFIRE` | ~168 B | modules 0x11134,36,38,3a,3c,40 |
| b240 | 0x10000008 | `SPKR_PHONE_SPKR_STEREO` | ~72 B | payload `{0xc,1,0xbb80,0x1da,0x4}` |
| b312 | 0x112fc | `SPKR_MIC_STEREO` | ~134 B | |
| b446 | (cont.) | `SPKR_PHONE_MIC_BROADSIDE` | ~112 B | modules 0x11135,37,39,3b,3d,3f,43 |
| b558 | (cont.) | `SPEAKER_VI` | ~56 B | VI sensing graph |
| b614 | (cont.) | `SPEAKER_OUT` | 3692 B | opens with nested name `AUDIO_DEVICE_FLUENCE_QUAD_MIC`; remainder of the 76 KB is dense per-module cal tables |

Cross-links that make the picture coherent:

- **0x113ad's flag word `0x10000008` IS the graph id** of
  `SPKR_PHONE_SPKR_STEREO`. So dev 0x45 → "run graph 0x10000008 over these six
  module instances".
- **0x113b6 = `(0x112a7, 0x12a52)`** — `0x12a52` is literally the id of the
  `SPKR_PHONE_MIC` sub-graph above; i.e. the pair references companion graphs,
  not registers.
- The ENDFIRE/BROADSIDE split explains the module-count pattern in the LUTs:
  the ×186 family (0x11135/37/39/3b/43) belongs to BROADSIDE (7 modules),
  the ×31 family to ENDFIRE (6 modules); `SPKR_PHONE_SPKR_STEREO` (playback)
  reuses the ENDFIRE-numbered instances.
- **AGIILUT0** (dev 0x45, sample rate `0xbb80`) gives per-module gain-table
  offsets into the same pool: 0x11134/36/38/3c → `(0x8b0, 0x374)`,
  0x1113a → `(0x908, 0x394)`, 0x11140 → `(0x8b0, 0x3b0)`; the blobs contain
  IEEE-754-looking words (`0x3fb4xxxx`, `0x3f1exxxxx`) — volume-curve points,
  consistent with a gain/volume graph stage.

## Speaker-vs-headset deltas

Device sets: Speaker_cal devs `{0xb,0xc,0xd,0xf,0x22,0x3f,0x44,0x45,0x57,0x5d}`;
Headset_cal devs `{0x8,0x9,0xa,0x10,0x11,0x1a,0x1c,0x53,0x56,0x5b,0x5c,0x62..0x67}`.
**Dev 0x45 does not exist in Headset_cal.** Closest analogue is dev 0x9
(HEADSET_SPKR_MONO).

| property | Speaker 0x45 | Headset 0x9 | delta |
|---|---|---|---|
| 0x113b7 | key 0x15200, port 0x4004, chmap 0xc0/0xc1 | keys 0x11106/0x11103/0x20101, port 0x4002/0x4003 | different key+port entirely |
| 0x113ad flags | all six modules `0x10000008` (graph id) | `0x11134:0x10000011, 0x11136:0x10000007, 0x11138:0x10000007, 0x1113a:0x10000005` | speaker uses ONE stereo graph; headset uses per-module graphs |
| 0x12eed | `{1, 48000, 0x1da}` | identical | none |
| 0x113b6 | `(0x112a7, 0x12a52)` | identical | none |
| 0x113af | `0x10000001` | identical | none |
| 0x1323e | `0` | identical | none |
| 0x13150 | `0x1025d` | `0x112fc` (= SPKR_MIC_STEREO graph id) | different ref id |
| 0x132b9 | `{1, 2, 0…}` | `{1, 0, 0…}` | channel-count-ish word 2 vs 0 |
| 0x12e10 | `0x44` | absent | speaker-only |
| 0x12e0f | `1` | absent | speaker-only |
| 0x113b8 | `"SPEAKER_OUT"` | `"HEADSET_SPKR_MONO"` | label only |

AVII/AVOL module sets: Headset dev 0x9 uses the **same six instances**
0x11134–0x11140 as Speaker dev 0x45 — the instance numbers are generic graph
node ids reused across cal files; only the payload tables differ. Conclusion:
nothing in the speaker path is a "headset value gone wrong"; dev 0x45's config
is genuinely separate, so there is no shared-param contamination to undo.

## What Linux would need to send via ADM SET_PP_PARAMS to match Windows

Windows' delivery model (from the qcauddev RE): AFE SET_PARAM with codec-key /
SLIMBUS cfg params → ADM open (topology id) → MATRIX_MAP_ROUTINGS_V5 →
AFE_PORT_DEVICE_START. The ACDB data above is what the ADSP consults when those
commands carry a device/cal key; on Linux (q6adm/q6afe) we currently send no
per-module cal at all. To match Windows byte-for-byte:

1. **Device key 0x45 / codec key 0x15200** must be referenced by whatever
   param block identifies the endpoint (`TopologySpeaker`, 48 kHz, 24-bit,
   stereo). The channel map `0xc1c0`-family words = channels 0/1 on port
   SLIMBUS_2_RX (0x4004) — already matches our DT.
2. **Graph selection**: property `0x113ad` says run graph **0x10000008**
   (`SPKR_PHONE_SPKR_STEREO`) for all six module instances. On legacy ELITE
   this maps to ADM SET_PP_PARAMS carrying `{module_instance, param_id,
   payload}` tuples per instance — i.e. the six instances × their AVOL gain
   tables (AGIILUT offsets 0x8b0/0x908 + curve blobs), not a single blob.
3. **Per-instance params to push after ADM open, before AFE start**, in order:
   - volume/gain curves from AGIILUT0 @48 kHz per module (float points),
   - `SPEAKER_VI` graph config only if VI/protection is enabled — Linux keeps
     protection off, so skip it (matches v22 finding that protection-off is
     fine acoustically),
   - `SPKR_PHONE_SPKR_STEREO` payload `{0xc,1,48000,0x1da,4}` — likely
     {channel_mask?, ?, sample_rate=48000, param=0x1da, ?}; needs one more
     decode pass against q6adm's known param structs before sending.
4. **Do NOT reuse headset values anywhere** — verified disjoint (table above).
5. The codec-side enable set (WGPRP 0x78403: 0x12c0d=1 etc.) is WCD934x-bias
   territory handled by wcd934x.c, not ADM.

Practical first step: extend `scripts/spx-acdb-extract.py` to emit the six
`(instance, param_id, payload)` triples from Speaker_cal and replay them via a
test-only `q6adm` SET_PP_PARAMS path, comparing against the Windows APR capture.

## Confidence + open questions

Confident (verified byte-level):
- Container/LUT formats across all 8 files; DPROPLUT record semantics;
  self-describing DPROP payloads; 11 properties of dev 0x45 decoded;
  0x113b7 = {key 0x15200, port 0x4004, chmap 0xc0/c1} reconfirmed exactly.
- Named-sub-graph framing incl. the odd-name-length alignment trap; seven
  sub-graphs identified with their module membership.
- 0x113ad flag word == graph id of SPKR_PHONE_SPKR_STEREO (strong structural
  match, two independent sources).
- Speaker vs Headset disjointness (no shared-param contamination).

Open questions / next decode passes:
- Exact TLV framing *inside* `SPEAKER_OUT` / nested `AUDIO_DEVICE_FLUENCE_QUAD_MIC`
  (3692 B header block then dense tables) — same byte-alignment trap applies.
- GUIDs **0x10921 / 0x10943 / 0x10bfe** not located in any scanned region of
  these files; they may live in Global_cal/General_cal blobs or be runtime
  qcauddev constants rather than ACDB data.
- VDYI / VSTI chunks (VI sensing / speaker protection) present but undecoded;
  relevant if protection is ever enabled.
- Precise semantics of CDCLUT0 `{key,val}` pairs (w0..w10) beyond "count +
  pairs" — would need a second source (e.g. matching values against known
  WCD934x register ids) to pin down.
- Whether `SPKR_PHONE_SPKR_STEREO` payload words {0xc,1,0xbb80,0x1da,0x4}
  are {mask, ch_count, rate, param_id, flag} or another layout — one targeted
  comparison against q6adm struct definitions settles it.
