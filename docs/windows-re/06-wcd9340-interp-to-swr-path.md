# 06 — WCD9340 interpolator → internal SoundWire data path

Scope: how audio physically travels from the WCD9340 (Tavil) SLIMbus RX side to
the codec's **internal SoundWire master** (`soundwire@c85`) and out to a WSA881x
amp on the Surface Pro X. Question asked: *which registers couple an SLIMbus RX
channel to a SoundWire DOUT port?*

Answer up front, then the evidence:

> **There is no programmable RX→SWR data-routing register in this codec.**
> The coupling INTn→SWR-DOUT is fixed silicon routing. Everything software can
> steer per-stream is (a) the INP_MUX input selectors feeding each interpolator,
> (b) per-interpolator clock/rate/gain/compander/boost/DSMDEM enables, and
> (c) the SoundWire DPn transport parameters (ChannelEn / sinterval / offsets)
> plus bank switching. This is proven four independent ways below (§4).

## 1. End-to-end signal chain (SPX speaker path)

```
APPS PCM
  → q6asm FE → ADM/COPP → ADSP AFE port 0x4004 (SLIMBUS_2_RX)      [q6afe.c]
  → ADSP drives SLIMbus channels; APPS subscribes them via slim_ifd
  → WCD9340 SLIMbus RX ports 16..23 ("RX0".."RX7")                 [wcd934x.c:87]
  → INP_MUX selects which RX port feeds each interpolator input    [0x0d0f-0x0d12]
  → interpolator INT7 (SPK1) / INT8 (SPK2): rate, gain, DSMDEM     [RX7/RX8 block]
  → compander7/8 + boost0/1 (analog conditioning, optional)        [0x0b34.., 0x0c19..]
  → FIXED hardwired link: INT7→SWR master dout ports, INT8→others
  → internal SWR v1.3 master @0xc85 frames PDM onto SDATA_OUT      [qcom.c over AHB bridge]
  → WSA881x slave DP1 (DAC/PDM in), PA gain                        [wsa881x.c]
```

The Windows ground truth agrees structurally: qcauddev8180.sys static left
descriptors map slave ports 1/2/3/4 → master ports 1/2/3/7 with channel masks
1/f/3/3 (right: 4/5/6/8), byte-matching `sc8180x-wcd9340.dtsi`
(`qcom,port-mapping = <1 2 3 7>` / `<4 5 6 8>`), and ACDB maps device 0x45 to
AFE port 0x4004. Windows opens all four descriptors; our guarded runs use one
(DAC-only DP1 or DP4).

Note what is *not* in that chain: no mux between interpolator output and SWR
DOUT. The SWR master has its own clock/frame generator (MCP_* regs) and per-port
transport params, but its **data source per DOUT port is not register-selected**
anywhere mainline can see.

## 2. Codec-side register list (all via SLIMbus regmap, paged window)

Access path: `regmap_init_slimbus()` on `slim217,250`, selector reg/window per
`drivers/mfd/wcd934x.c`; the SWR master block sits inside the same page space.

### 2.1 Input muxes — the ONLY data-steering registers

| reg | name | function |
|---|---|---|
| 0x0d0f | CDC_RX_INP_MUX_RX_INT7_CFG0 | INT7 inp0 sel[3:0], inp1 sel[7:4] |
| 0x0d10 | CDC_RX_INP_MUX_RX_INT7_CFG1 | INT7 inp2 sel[3:0] |
| 0x0d11 | CDC_RX_INP_MUX_RX_INT8_CFG0 | INT8 inp0/inp1 |
| 0x0d12 | CDC_RX_INP_MUX_RX_INT8_CFG1 | INT8 inp2 |

Selector encodings (enums at wcd934x.c:444-462):
`INTn_1_INP_SEL`: 0=ZERO, 1=DEC0, 2=DEC1, 3=IIR0, 4=IIR1, **5..12 = RX0..RX7**.
`INTn_2_INP_SEL`: **1..8 = RX0..RX7**, 9=PROXIMITY.
These choose *which SLIM channel* enters the interpolator — they do **not**
touch the SWR side.

### 2.2 Interpolators INT7/INT8 (speaker paths)

Base stride 0x14 between adjacent interps; RX_PATH_CTL(rx)=0xb41+rx*0x14.

| INT7 | INT8 | name | function |
|---|---|---|---|
| 0x0bcd | 0x0be1 | RX_PATH_CTL | clk_en(bit5), reset(bit6), rate[3:0]; PGA mute bit4 |
| 0x0bce | 0x0be2 | RX_PATH_CFG0 | HD2, bypass, etc. |
| 0x0bcf | 0x0be3 | RX_PATH_CFG1 | bit0 = SBOOST supply request |
| 0x0bd2 | 0x0be6 | RX_PATH_MIX_CTL | mix-path clk/mute |
| 0x0bd3 | 0x0be7 | RX_PATH_MIX_CFG | mix interp input rate (INTn_2 sel rate) |
| 0x0bdd | 0x0bf1 | RX_PATH_MIX_SEC0 | secondary mix input sel |
| 0x0bdf | 0x0bf3 | RX_PATH_DSMDEM_CTL | DSM/dem enable — last digital stage before analog/SWR serialize |

Rate programming: `wcd934x_set_prim_interpolator_rate()` (wcd934x.c:1533)
scans every interp's CFG0/CFG1 selectors for a match against
`ch->shift + INTn_1_INP_SEL_RX0` and writes the rate field into that interp's
RX_PATH_CTL; `set_mix_interpolator_rate` does the same against CFG1 low nibble
and writes RX_PATH_MIX_CTL. Ear/speaker interps reject 44.1 kHz.

### 2.3 Compander / boost

| INT7/SPK1 | INT8/SPK2 | function |
|---|---|---|
| 0x0b31 CTL0 | 0x0b39 CTL0 | COMPANDER CTL0 = 0xb01+(interp−1)*8 (wcd934x.c:4290): CLK_EN b0, SOFT_RST b1, HALT b2 — the only compander reg mainline touches. INT7→idx6→0x0b31, INT8→idx7→0x0b39; header cross-check: COMPANDER7_CTL3=0x0b34/CTL7=0x0b38 ⇒ base 0x0b31; COMPANDER8_CTL3=0x0b3c/CTL7=0x0b40 ⇒ base 0x0b39. HPH_CMP_EN goes into the same interp's RX_PATH_CFG0 (0x0bce/0x0be2) via rx_path_cfg0_reg |
| 0x0b34/0x0b38 CTL3/CTL7 | 0x0b3c/0x0b40 | header-defined, unused by mainline (Windows qcauddev candidates) |
| 0x0c19 BOOST_PATH_CTL | 0x0c21 | boost clk/en |
| 0x0c1a-0c1c | 0x0c22-0c24 | boost ctl/cfg1/cfg2 |

`wcd934x_config_compander()` (wcd934x.c:4290): PRE_PMU CLK_EN + SOFT_RST pulse +
HPH_CMP_EN; POST_PMD reverse with HALT. Analog conditioning only.

### 2.4 Clocks / misc

| reg | function |
|---|---|
| 0x0d43 (CDC_SWR_CLK_ENABLE whole byte 0x01) | SPX machine writes full byte before ACCESS_CFG=0x0f — mirrors qcauddev8180.sys order |
| 0x803e | NPL clear (bit4) on spx_clear_npl after clock restart |
| 0x800 SEL/window regs | regmap paging, not audio |
| 0x42 / 0x43 | wcdgpio dir/val — amp SD_N powerdown pins (pin1/pin2) |

### 2.5 Internal SWR master block (@0xc85, reached over AHB bridge)

Bridge discipline (see memory [[spx-swrm-paged-bridge-required]],
[[spx-bridge-returns-fake-register-data]]): reads go through
SWR_AHB_BRIDGE_RD_DATA_0..3 + ACCESS_STATUS (0xc85-range); direct reads are
unreliable/fake — always validate with the COMP_PARAMS==0x016840c6 canary.

Master register map as used by drivers/soundwire/qcom.c (v1.3 layout):

| offset | macro | function |
|---|---|---|
| 0x300/304/308/30C/314/318 | CMD_FIFO_* | command FIFO (write/read/err/status) |
| 0x500 | ENUMERATOR_CFG | enumeration control |
| 0x530+8m / 0x534+8m | SLAVE_DEV_ID_m lo/hi | dev-id table |
| 0x101C+40m | MCP_FRAME_CTRL_BANK(m) | frame shape per bank m |
| 0x1044 | BUS_CTRL | bus config |
| 0x104C | STATUS / 0x1090 MCP_SLV_STATUS | attached-slave latch (0x1 dev0, 0x4 dev1) |
| 0x1124+100(n−1)+40m | DP_PORT_CTRL_BANK(n,m) | **per-port transport word, banked** |
| 0x1128 | PORT_CTRL_2 | port ctrl ext |
| 0x112C+100(n−1) | BLOCK_CTRL_1(n) | block packing (non-banked) |
| 0x1130/1134/1138 | BLOCK_CTRL2 / HCTRL / BLOCK_CTRL3 | packing/hctrl/block3 |
| 0x1054+100(n−1) | DIN_PCM_PORT_CTRL(n) | din port ctrl |
| ≤0x1740 | max_register | |

**DP_PORT_CTRL word format** (verified live, both banks):
`en_chan<<24 | offset2<<16 | offset1<<8 | sinterval`.
Endpoint A (master DP1): `0x01000107`. Endpoint B (master DP4):
`0x01000607` — chan 1, off1/off2/sinterval from DT pcfg entries selected by
slave `m_port_map`.

Slave-side (WSA881x) DP1 params travel as SoundWire writes to the slave:
SAMPLECTRL1/PORT_CTRL/PORT_CTRL_2 (e.g. trace `0x0132=0x07 0x0134=0x01`,
ChannelEn `0x0120=0x01`) plus bank switches broadcast on SCP_FrameCtrl
B0/B1 (`0x0060`/`0x0070`). PA: SPKR_DAC_CTL(ANALOG_BASE+0x1C),
SPKR_DRV_EN/GAIN (0x1A/0x1B), gain ramp 0x311b.

## 3. What actually happens during stream bring-up (trace evidence)

`docs/traces/stream-silent-20260727.txt` (256 writes, kprobe on every SWR
write). Bring-up sequence, verbatim:

```
prepare : 0x0102=0x00                       (port ctrl 2 / prep-disable)
          0x0132=0x07 0x0134=0x01           (slave DP1 SampleCtrl1/OffsetCtrl1, bank 1)
          0x00f0=0x01                       (UNEXPLAINED dev0 write, master range)
switch  : bcast 0x0070=0x07                 (SCP_FrameCtrl_B1 -> bank 1)
          0x0102=0x00
          0x0122=0x07 0x0124=0x01           (bank-0 params)
          0x00e0=0x01                       (UNEXPLAINED dev0 write)
          0x0120=0x01                       (slave DP1 ChannelEn=1)
switch  : bcast 0x0060=0x07                 (bank 0 active, stream enabled)
PA      : 0x311b ramp 0x99..0x09, 0x311a=0xfc
teardown: 0x311a=0x7c, ChannelEn->0
```

Key observations:

1. **Zero codec-page writes appear on SoundWire during the entire capture.**
   All codec configuration (INP_MUX, PATH_CTL, compander, boost, SWR clock)
   travelled earlier over SLIMbus via the codec regmap. The SWR bus carries
   only slave-port programming and audio frames.
2. Nothing selects a data source for the DOUT port. Enabling ChannelEn is the
   only act that connects audio to the wire — consistent with fixed routing.
3. Two unexplained device-0 writes `0x00f0=0x01` / `0x00e0=0x01` flank the
   bank switches. They sit in the master's own register page range (0x00xx),
   not a slave address, and their purpose is undocumented here — open item;
   candidates are master-side per-bank enable/sticky latches. Worth capturing
   once more with the serialized snapshot to see whether values differ.

## 4. Proof there is no programmable routing register

Four independent lines of evidence:

1. **Header census**: `include/linux/mfd/wcd934x/registers.h` contains **no**
   `CDC_RX_TOP_*` symbol at all (grep returns nothing) and nothing in the
   0x3xxx page. There is no "top-block routing" register family in this
   generation — unlike later codecs (WCD938x) where TOP blocks exist.
2. **DAPM graph is declarative**: `"SPK1 OUT"`/`"SPK2 OUT"` are plain outputs
   and `"RX INT7 CHAIN"`/`"RX INT8 CHAIN"` are MIXER widgets with NULL event
   handlers (wcd934x.c:5219-5220, 5370-5374). If hardware needed a register
   touch to connect interp→SWR, those widgets would carry SND_SOC_DAPM_REG or
   an event callback; they don't.
3. **Git history**: no commit in this tree ever added code writing a
   "routing"/"path-select" register between interpolators and the SWR master.
   The only SWR-related codec writes are the clock enable (0x0d43) and NPL
   clear (0x803e).
4. **Cross-chip analogue**: `sound/soc/codecs/lpass-wsa-macro.c` (WSA macro on
   sm8250+, different chip) exposes exactly the same shape —
   `CDC_WSA_CLK_RST_CTRL_SWR_CONTROL` clock gate, bare SPK1/SPK2 OUT outputs,
   no PDM-source mux. Qualcomm's architecture serializes the interpolator
   output onto fixed DOUT lanes; only the *timing* is programmable.

Consequence: if audio reaches INT7/INT8 (verify via INP_MUX + PATH_CTL +
DSMDEM), the SWR side needs only correct DPn transport params and bank state.
If the amp hears noise/static instead of tone, the corruption happened
upstream of the interpolator serialization — i.e. wrong SLIM channel content
from the ADSP AFE (channel map/rate mismatch), which matches the standing
conclusion [[spx-static-upstream-confirmed]].

## 5. m_port_map is timing-only (common misconception)

DT `qcom,port-mapping = <1 2 3 7>` (left) / `<4 5 6 8>` (right) feeds
`slave->m_port_map[]`; `qcom_swrm_compute_params()` uses it purely to pick
which `pconfig[]` entry supplies sinterval/offset1/offset2 for that port
(qcom.c:2931/3053). It never changes *which data* flows — ChannelEn=1 on
master DP1 carries whatever the fixed lane carries regardless of the mapping.
So changing m_port_map cannot fix static; it can only fix framing/timing
artifacts (wrong sample intervals).

## 6. Debug recipe (register-level proof of the path)

To prove end-to-end connectivity without listening:

1. INP_MUX: read (cache) `0x0d0f/0x0d11` — expect inp0 = RX0 sel (5) for the
   active endpoint's configured route.
2. `RX7/RX8 RX_PATH_CTL` rate nibble == stream rate (0x04 = 48k).
3. `RX_PATH_DSMDEM_CTL` nonzero while stream active.
4. Master `DP_PORT_CTRL_BANK(n, active_bank)` == expected word
   (`0x01000107` DP1-A / `0x01000607` DP4-B).
5. Slave DP1 ChannelEn shadow logs both banks (spx_shadow_dp1_enable).
6. `MCP_SLV_STATUS==0x1` observed at least once in GPIO-high window.

If all six hold and the speaker still emits static, the fault is provably in
the SLIM channel payload from the ADSP (or the amp's analog side), not in any
missing routing step — because none exists.

## 7. Windows cross-check anchors

- qcauddev8180.sys PAGEwcda @0x14006e000; `wsa_reg_write` 0x140098640,
  PA bring-up 0x140098af0/0x140099058.
- Static descriptor table: left slaves 1/2/3/4→masters 1/2/3/7 masks 1/f/3/3;
  right 4/5/6/8→4/5/6/8. Byte-equal to dtsi pcfg rows (sinterval 0x07/0x1f/
  0x3f/0x07..., offset1 0x01/0x02/0x0c/0x06..., offset2 0/0/0x1f/0...).
- Windows leaves BLOCK_CTRL_1/BlockCtrl3/HCTRL at reset (our
  `spx_win_transport=1` mimics this); tested both ways on the audible pin2
  baseline — ruled out as the static source ([[spx-static-win-transport-ruled-out]]).
- ACDB: device 0x45 → port 0x4004, tokens 0x01010004/0x01010005 (endpoints A/B);
  V19/V21 empirically joined token B ↔ MP4/SPK2/pin2 (audible) and showed pin1
  analog path dead.
