# 08 — What the current Linux stack programs on the SPX playback path

Purpose: authoritative snapshot of what the **current** Linux drivers program at every
layer of the speaker playback path, so Windows RE docs 01–07 can be diffed against it.

Path covered: ALSA app → `q6asm` FE ring → `q6routing` matrix map → ADM COPP →
AFE `SLIMBUS_2_RX` (`0x4004`) → WCD9340 SLIM PGD RX ports → WCD9340 internal SoundWire
master `@0xc85` (master DP1/DP4) → WSA881x slave DP1 → DAC/PA.

Method: source read of this tree (branch `spx/v6.18`) plus `sudo fdtdump
/sys/firmware/fdt` for the booted blob and `/proc/cmdline`.

**Verification status (important).** The system examined live is a **non-audio
"slimfix" boot** (kernel `6.18.3-1-surface+-slimfix`): its FDT has **no** `swr-master`,
no `left_spkr`/`right_spkr`, binds `q6apm` bedais in the sound node, and its cmdline
blacklists `soundwire_qcom` and `snd_soc_wsa881x`. There is **no sound card** this
boot. Every "live value" below therefore comes from the last valid guarded-run logs
(v19/v21/v22 era) and is marked **UNVERIFIED-today**: structurally proven then,
not re-readable on the running system. Anything not even log-proven is `UNVERIFIED`.
`spx_reenum` is deliberately not touched (write-only parameter).

## Layer 1 — ALSA app → q6asm frontend (`q6asm-dai.c`)

| What Linux programs | file:line | Live value | Notes |
|---|---|---|---|
| Period count bounds | sound/soc/qcom/qdsp6/q6asm-dai.c:28–31 | 2..8 periods, max period 65536 B, min 128 B | guarded harness requests 12000/48000 frames |
| Playback hw caps | sound/soc/qcom/qdsp6/q6asm-dai.c:240–262 | S16_LE \| S24_LE(?), 8 k–192 k, 1–8 ch | v18 proved S24_LE frontend inaudible → harness pins S16_LE/48 k/stereo |
| Module knobs | sound/soc/qcom/qdsp6/q6asm-dai.c:110–127 | `spx_force_timer_pacing` (default true), `spx_keep_asm` (true), `spx_period_adjust_ms` | since v17 the validated path is DSP-event pacing: `spx_force_timer_pacing=0`, `submitted==write_done`, `fallback=0` |
| High-IOVA alias map | sound/soc/qcom/qdsp6/q6asm-dai.c:145 | phys told to DSP = `iova \| sid<<32`, sid=`0x1b21&0xF`=1 | non-stock; stock maps plain DMA addrs |
| Watchdog fallback submit | sound/soc/qcom/qdsp6/q6asm-dai.c:309–330 | sets `write_fallback`, queues one `q6asm_write_async`, re-arms after `period_jiffies` | ownership rule: WRITE_DONE must cancel it; if already running → permanent timer fallback |
| Completion event pacing | sound/soc/qcom/qdsp6/q6asm-dai.c:334–410 | timer mode fills all periods per event; event mode one buffer + `period_jiffies*2` | v17 result `bits=16 submitted=20 write_done=20 fallback=0` (fully DSP-paced) |
| Period timing derive | q6asm_dai_prepare (~:520) | `period_jiffies = DIV_ROUND_UP(bytes_to_frames(period)*HZ, rate)` | derived from ALSA frames so S24_LE's 32-bit container times right |
| Frontend bit depth | sound/soc/qcom/qdsp6/q6asm-dai.c:800–807 | 16 (S16_LE baseline) | logged at close as `bits=16` |

## Layer 2 — q6asm core: session open + shared-mem map (`q6asm.c`)

| What Linux programs | file:line | Live value | Notes |
|---|---|---|---|
| Module knobs | sound/soc/qcom/qdsp6/q6asm.c:36–48 | `property_flag=0`, `mem_pool=4` | pool 3 = physical → −110 stalls; pool 4 = SMMU/virtual ACKs. Stock is 3 |
| Session open | q6asm_open_write | LEGACY_STREAM_SESSION, endpoint ASM_END_POINT_DEVICE_MATRIX, postproc `ASM_NULL_POPP_TOPOLOGY` (`0x10C68`), fmt `ASM_MEDIA_FMT_MULTI_CHANNEL_PCM_V2` | no Windows device-0x45 graph, no app-type calibration |
| Memory map regions | __q6asm_memory_map_regions | contiguous buffer → `num_regions=1`, `buf_sz=ALIGN(period_sz*periods,4096)`, `token=(session<<8)\|dir`, `shm_addr_lsw/msw` = alias phys | MAP_REGIONS opcode `0x10D92`; differs from Windows' multi-region scatter map |
| Media format | q6asm_media_format_block_multi_ch_pcm | `is_signed=1`; channel_mapping from `q6dsp_map_channels` → 2ch = FL(1), FR(2) | sound/soc/qcom/qdsp6/q6dsp-common.c |
| Client reuse | `spx_keep_asm` | ASM client kept across close/open | part of the parked-session family (see Notes column of L3) |

## Layer 3 — routing matrix → ADM COPP → AFE port start (`q6routing/q6adm/q6afe`)

| What Linux programs | file:line | Live value | Notes |
|---|---|---|---|
| Route preservation | sound/soc/qcom/qdsp6/q6routing.c:29 | `spx_keep_copp=true` — close does **not** tear down COPP/matrix | parked-DSP-state family |
| Topology overrides | sound/soc/qcom/qdsp6/q6routing.c:363–373 | `spx_rx_topology=0`, `spx_rx_acdb_id=0`, `spx_rx_app_type=0` | zero ⇒ stock defaults used |
| ADM open topology | sound/soc/qcom/qdsp6/include/q6adm.h:8 (`NULL_COPP_TOPOLOGY 0x00010312`), q6adm.c:44 (`ADM_LEGACY_DEVICE_SESSION 0`) | NULL_COPP 0x10312 | Windows uses device `0x45`, key `0x15200`, app-type/calibration graph — Linux has none |
| Matrix map V5 | sound/soc/qcom/qdsp6/q6adm.c:31 (opcode `0x10325`) | matrix `ADM_MATRIX_ID_AUDIO_RX`, copp list = the one COPP id | optional V7 header rewrite knob `SPX_V7_SPEAKER_TOPOLOGY 0x10000008` (q6adm.c:38) exists but is off by default |
| Device-open V5 payload | q6adm_device_open | flags, mode, `endpoint_id_1=afe_port`, topology_id, `dev_num_channel`, bit_width, rate, mapping `q6dsp_map_channels` (FL=1/FR=2) | UNVERIFIED-today which of device_open vs legacy path fires on the guarded runs |
| AFE port id | sound/soc/qcom/qdsp6/q6afe.c:119 | `AFE_PORT_ID_SLIMBUS_MULTI_CHAN_2_RX = 0x4004` | matches ACDB `TopologySpeaker` port 0x4004 (doc 05) |
| Port map table | sound/soc/qcom/qdsp6/q6afe.c:743 | SLIMBUS_2_RX entry | rate/width/ch filled from BE hw_params |
| SLIM port config payload | q6afe_slim_port_prepare, sound/soc/qcom/qdsp6/q6afe.c:1676–1696 | sb_cfg_minor_version, sample_rate=48000, bit_width=16, num_channels, data_format, **`shared_ch_mapping[0..3]`** | **PRIME STATIC SUSPECT**: this array is only ever written by `q6slim_set_channel_map` (q6afe-dai.c:481–522), and the card-level channel-map propagation handles only `WSA_CODEC_DMA_RX_*`/`RX_CODEC_DMA_RX_*`/`TX_CODEC_DMA_TX_*` DAI types — for the SLIMBUS_2_RX BE it **never fires**, so the ADSP receives an all-zero channel map |
| AFE start | q6afe_port_start, sound/soc/qcom/qdsp6/q6afe.c:2020+ | `set_param_v2(cfg, AFE_MODULE_AUDIO_DEV_INTERFACE)` then APR `AFE_PORT_CMD_DEVICE_START{0x4004}` | Windows order: CDC_REG cfgs → ADM open → matrix map → DEVICE_START (docs 03/04) |
| Optional codec-cal replay | sound/soc/qcom/qdsp6/q6afe.c:380 `spx_auto_speaker_cal` | default **off** | would send CDC_SLIMBUS_SLAVE_CFG / SLIMBUS_CONFIG(module 0x15200)/CDC_REG_CFG_INIT — the Windows ADSP-owned writes Linux never replays by default |
| Port stop suppression | sound/soc/qcom/qdsp6/q6afe-dai.c (keep_port_running) | `SLIMBUS_2_RX` AFE port never stopped on SPX (`microsoft,surface-pro-x`) | parked-session family; DSP-side port stays up across streams |

## Layer 4 — WCD9340 codec: DAPM path + SLIM PGD RX ports (`wcd934x.c`)

DAPM route for endpoint B (v19): `Slimbus2 Playback` → `SLIMBUS_2_RX` AIF_IN
(sound/soc/qcom/qdsp6/q6afe-dai.c:557, :794) → `SLIMBUS_2 RX Audio Mixer` →
`RX2 Interpolator` mux (`rx_prim_mix_text`, sound/soc/codecs/wcd934x.c:619,
values ZERO…RX7) → INT2 → `SPK1 OUT`/`SPK2 OUT` → WSA amp IN. Endpoint B uses
RX1/INT8/COMP8/RX8 per DT (`sc8180x-wcd9340.dtsi`, SPK2 pinmux).

| What Linux programs | file:line | Live value | Notes |
|---|---|---|---|
| Watermark macro | sound/soc/qcom/qdsp6/../codecs/wcd934x.c:41–50 | `WCD934X_SLIM_WATER_MARK_VAL = ((12BYTES)<<1)\|ENABLE = 0x05` | macro is local to wcd934x.c, not registers.h |
| Per-RX-port channel map | sound/soc/codecs/wcd934x.c:1741–1815 (`wcd934x_slim_set_hw_params`) | `WCD934X_SLIM_PGD_RX_PORT_MULTI_CHNL_0(ch->port) = 1<<ch->shift`; `WCD934X_SLIM_PGD_RX_PORT_CFG(ch->port) = 0x05` | PGD regs 0x140+4p / 0x30+p; this is the codec-side half of the channel map that AFE never fills |
| Stream allocate | same function | `slim_stream_allocate("WCD934x-SLIM")`, ports prepared/committed via slimbus stream API | control path only; audio data is ADSP AFE→SLIM HW |
| Interpolator rate | wcd934x_hw_params → `wcd934x_set_interpolator_rate` | 48 k on the selected INT | standard |
| Persist stream knob | sound/soc/codecs/wcd934x.c:508–516 | `spx_persist_stream=1` gates `wcd934x_spx_persist` (AIF1_PB) | keeps the WCD SLIM stream prepared across close — parked-session family |
| INT7/INT8 cfg regs | include/linux/mfd/wcd934x/registers.h:485/:487 | 0x0d0f / 0x0d11 | interpolator enable/cfg for SPK1/SPK2 paths |
| RX watermark readback | UNVERIFIED | UNVERIFIED-today (write-only in guarded logs) | no capture of final PGD values exists |

## Layer 5 — SoundWire master @0xc85: DP1/DP4 transport (`soundwire/qcom.c`)

Controller bring-up (Windows-init block, drivers/soundwire/qcom.c:2180–2245):
SW_RESET → CMD_FIFO_CFG=0x03 → MCP_CFG pings-off → intr_mask=0x1c3fd →
ENUMERATOR_CFG=1 → FRAME_CTRL_BANK0=BIT(16) → MCP_BUS_CTRL CLK_START →
COMP_CFG enable → poll COMP_STATUS. With `spx_core_enum=1` the FRAME_CTRL value
becomes `cols<<rows \| ssp_period<<16 \| actual_phase<<11 \| clk_div<<8`
(qcom.c:2251–2269); bank switches re-assert it via `qcom_swrm_pre_bank_switch`
(qcom.c:2613–2640).

| What Linux programs | file:line | Live value | Notes |
|---|---|---|---|
| Module knobs | drivers/soundwire/qcom.c:34,:103,:1083,:138,:165–177,:2655 | `spx_core_enum=1 spx_write_dev0=1 spx_no_assign=1 spx_shadow_dp1_enable=<0\|1> spx_frame_phase=1 spx_runtime_ssp_period=1 spx_win_transport=<0\|1>` | guarded v19 cmdline; `spx_reenum` deliberately not read |
| FRAME_CTRL reg formula | qcom.c:281/:294 | `SWRM_MCP_FRAME_CTRL_BANK_ADDR(bank)`; SSP_PERIOD=1 runtime (qcom.c:2624) | matches Windows' 48-frame/9.6 MHz layout |
| Clock divider | qcom.c:1722 `spx_clk_div` | default (9.6 MHz bus); 19.2 MHz proven silent — keep default | |
| Port params compute | qcom_swrm_compute_params, qcom.c:2904+ | `sample_interval = pcfg->si + 1` (DT si), `spx_port_si` override if >=0; `blk_pkg_mode`: 0xff→0 under win_transport else DT absent ⇒ 0xff | DT has **no** `qcom,ports-block-pack-mode` ⇒ stock writes BLOCK_CTRL_1=0xff; Windows leaves it at reset |
| DPn PORT_CTRL word | qcom_swrm_port_enable_bank, qcom.c:2829+ | word = `en_chan<<24 \| off2<<16 \| off1<<8 \| sinterval`. Endpoint A master DP1: **0x01000107** both banks. Endpoint B master DP4: **0x01000607** both banks (UNVERIFIED-today, from v19/v21 logs) | bit-exact vs DT `ports-sinterval-low/offset1/offset2` and vs Windows static left descriptor |
| win_transport compose | qcom.c:2829+ | single composed PORT_CTRL write instead of RMW over the flaky AHB bridge; skips BLOCK_CTRL_1, slave BlockCtrl3, HCTRL | A/B'd twice (v7, doc memory) — static unchanged either way |
| Bank mirror/shadow | qcom.c:2869+ `spx_shadow_dp1_enable` | enable/disable shadowed across both banks | proved B0=B1 parity in v5; not the silence/static gate |
| AHB bridge discipline | qcom.c:540–650 | 8-byte contiguous WR_DATA+WR_ADDR, ≤6 status-byte polls (WR_DONE bit0/RD_DONE bit1), RD_DATA as four separate byte reads | reads unreliable; never trust a write |
| Broadcast switch | SCP_FRAMECTRL_B0/B1 (0x0060/0x0070)=0x07 | one broadcast per switch; drops are invisible (whole-boot-silence RCA) | |
| spx_snapshot | qcom.c:1820 (0200) | serialized DP1/DP4 dump mid-stream | v22 showed the snapshot itself occupies ~165 ms of the shared bridge during playback |

## Layer 6 — WSA881x slave: DP programming + PA sequence (`wsa881x.c`)

Port order DAC(0)/COMP(1)/BOOST(2)/VISENSE(3); dpn_prop min=max_ch=1,
simple_ch_prep_sm. Slave DP1 is programmed by the core from the same port-map;
master DP selection comes from DT `port-mapping` (endpoint A `<1 2 3 7>`,
endpoint B `<4 5 6 8>`).

| What Linux programs | file:line | Live value | Notes |
|---|---|---|---|
| Port mask | sound/soc/codecs/wsa881x.c:712 | `spx_stream_port_mask` default BIT(PORT_DAC) — DAC only | COMP/VISENSE/BOOST ports not opened |
| Port map | sound/soc/codecs/wsa881x.c:727 | slave DP1 ↔ master DP1 or DP4 | |
| Powerdown GPIO | sound/soc/codecs/wsa881x.c:794 | endpoint B ⇒ GPIO pin2 (val 0x04); pin1 dead (v20/v21) | physical HIGH = amp ON |
| Cold-init table | :353 rev_2_0 table (INTR_MASK 0x1B, DRV_GAIN 0xC1, DAC_CTL 0x42, BIAS_INT 0x5F, BIAS_PSRR 0x44, BOOST_PRESET_OUT1 0xB7 …) | replayed at idle cold init | pre-PD table |
| PA PRE_PMU | :1345+ spkr_pa_event | capture pa_gain from shadow; replay supplies DIG/ANA CLK bit0 + TEMP_OP bit3 + DAC_CTL bit7; boost EN +1.5 ms; OCP en; PA_GAIN_SEL=gain; then `spx_win_pa_seq`: ANA_CTL bit2 pulse; profile≠3: DAC_CTL 0x62→0x42; DAC_CTL=0xc2; OCP 0xb4; profile3: OCP b6→b2 + DRV_EN 0xfc; VI-diag + PWRSTG_DBG 0xa0→0 (profile≠3); ramp 0xc→pa_gain 1 ms/step; final DRV_EN 0xfd, BIAS_CAL 0xac | **divergence vs Windows**: protection disabled (`3110=00 3111=00 3140=95 313a=ce`) and VISENSE off — v22 tested exactly this and static remained |
| PA profile knob | :909/:914 | `spx_win_pa_seq=1`, `spx_win_pa_profile=0` (v23 staged profile 3) | |
| Gain mode | :1281 "PA Volume" on SPKR_DRV_GAIN; REG mode (not DRE/COMP — compander mutes real audio) | ramp to +18 dB code 12 in guarded runs | plain re-set is an ALSA no-op; force-write required |
| Write policy knobs | :818/:823/:905 | `spx_write_only`, `spx_blind_rmw`, `spx_sample_edge` | blind RMW needed for natively-enumerated dual amp |
| POST_PMD teardown | visense teardown + OCP HOLD; digital_mute clears SPKR_DRV_EN bit7 | GPIO parked to 0x00 | verified every guarded run |

## Layer 7 — Booted FDT sound nodes

The **currently running** blob (`/sys/firmware/fdt`, sudo fdtdump, saved at
/tmp/booted-fdt.txt) is NOT an audio boot:

- sound node compatible `qcom,apq8098-sndcard`-style with
  `wcd-playback-dai-link{cpu sound-dai=<0x02 0x71>; codec sound-dai=<0x03 0>}`
  referencing **q6apm bedais** phandles (AudioReach/GPR style) — no q6afe/q6asm FE links;
- `slim-ngd@171c0000` present with `slim@1/ifd@0,0/codec@1,0` (`slim217,250`,
  clock-frequency 0xbb8000, gpio-controller@42) but **no `soundwire@c85` child**
  and no speaker nodes at all;
- bootargs contain
  `module_blacklist=soundwire_qcom,snd_soc_wsa881x modprobe.blacklist=… wcd934x.spx_wsa_en_pin=-1 wcd934x.spx_wsa_gpio_dir=0x06 wcd934x.spx_wsa_gpio_val=0x00`.

Consequence: nothing on this boot can confirm any transport register. The
reference audio DT for diffing against Windows docs is the source tree:

| What Linux programs | file:line | Value | Notes |
|---|---|---|---|
| Master node | arch/arm64/boot/dts/qcom/sc8180x-wcd9340.dtsi `swm: soundwire@c85` | `reg<0xc85 0x40>`, dout 6/din 2, interrupts-extended <&wcd9340 20>, qcom,soundwire-v1.3.0 | codec-internal master, no MMIO/IRQ usable |
| Port params | same node | `ports-sinterval-low <0x07 0x1f 0x3f 0x07 0x1f 0x3f 0x0f 0x0f>`, offset1 <0x01 0x02 0x0c 0x06 0x12 0x0d 0x07 0x0a>, offset2 <0x00 0x00 0x1f 0x00 0x00 0x1f 0x00 0x00> | DP1=0x07/0x01/0x00, DP4=0x07/0x06/0x00 — bit-exact with observed PORT_CTRL words |
| Block pack mode | same node | **absent** ⇒ blk_pkg_mode 0xff ⇒ driver writes BLOCK_CTRL_1=0xff unless win_transport | Windows leaves these at reset |
| Amps | same dtsi `left_spkr sdw10217201000@0,1` (port-mapping <1 2 3 7>, pin1), `right_spkr …@0,2` (<4 5 6 8>, pin2) | part_id 2010 IDs 1/2 | older probes saw real IDs 3/4 with `0217:2110` — permanent stereo must fix identities + sequential dev1/dev2 |
| Card | arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts | compatible qcom,sdm845-sndcard; slim-playback-dai-link cpu<&q6afedai SLIMBUS_2_RX> platform<&q6routing> codec<&wcd9340 0>,<&left_spkr>,<&right_spkr>,<&swm 0>; audio-routing "SpkrLeft IN"/"SPK1 OUT", "SpkrRight IN"/"SPK2 OUT"; capture SLIMBUS_0_TX | |
| Right-only variant | arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x-speaker-right.dts | disables left_spkr; codec list `<&wcd9340 0>,<&right_spkr>,<&swm 0>`; right-only routing; apss watchdog@17c10000 added | v19+ guarded baseline |

## Layer 8 — Live ALSA state

This boot exposes **no ALSA card** (`/proc/asound/cards` empty; modules
blacklisted, no SWR subtree in FDT) — so no live mixer/hw_params state can be
captured today. Last valid first-stream evidence (guarded logs, all
UNVERIFIED-today):

- hw_params exactly S16_LE / 48000 Hz / 2 ch; C1/front-right submitted (v19);
- Q6ASM close counter `bits=16 submitted=19 write_done=19 fallback=0` — fully
  DSP-paced, no timer fallback;
- active master DP4 banks both `0x01000607` (endpoint B) or DP1 both
  `0x01000107` (endpoint A);
- `MCP_SLV_STATUS=0x1` observed before playback (device 0 present), later
  samples may flicker to 0x0 (documented latch ambiguity);
- PA Volume forced 0→12 (+18 dB REG mode), GPIO parked to 0x00 after POST_PMD.

## Diff highlights vs Windows RE docs 01–07 (most suspicious values)

1. ~~**AFE `shared_ch_mapping[]` is all-zero**~~ **RETRACTED 2026-08-23**: this
   tree's `sdm845.c` card driver programs Windows-exact shared channels —
   `SPX_SPKR_SLIM_CH0/1 = 192/193` (0xC0/0xC1, sdm845.c:36–37) are pushed to
   SLIMBUS_2_RX on every BE hw_params (sdm845.c:102–110) and at card init
   (:326–334) when `of_machine_is_compatible("microsoft,surface-pro-x")`; the
   map reaches the APR payload via `q6afe_slim_port_prepare` →
   `slim_cfg.shared_ch_mapping`. The installed snd-soc-sdm845.ko carries the SPX
   strings and the 08-22 guarded run logged
   `SPX speaker backend: SLIMBUS_2_RX`, so the audible era (v15–v31, module
   dated 07-28) always had the map programmed. Residual gap: no packet-level
   APR capture; a one-line q6afe dev_info log of the prepared slim_cfg would
   close it. As a static source it also fails the §33 gain test (a misroute
   corrupts samples, which must scale with PA gain).
2. **NULL_COPP topology 0x10312, acdb_id 0, app_type 0, NULL_POPP** — no
   Windows device-0x45 / key-0x15200 post-processing graph, no speaker-protection
   calibration module 0x1025f.
3. **Parked-session family** (`spx_keep_asm`, `spx_keep_copp`,
   keep_port_running, `spx_persist_stream`) leaves DSP/COPP/AFE/WCD state alive
   across streams by design — stale-state class risk.
4. **Non-stock ASM memory map**: mem_pool_id=4 (stock 3) + high-IOVA
   `iova|sid<<32` alias, single contiguous region instead of Windows'
   scatter map.
5. **BLOCK_CTRL_1 / slave BlockCtrl3 / HCTRL**: stock writes 0xff/0xff/0xf0,
   win_transport leaves reset values; both A/B'd, static unchanged — but the
   divergence itself remains vs Windows.
6. **WSA PA profile**: protection explicitly disabled, VISENSE off — an exact
   branch match to DriverStore's protection-off sequence, not the full protected
   profile.
7. Today's boot cannot validate any of the above electrically (no card, modules
   blacklisted, no swr-master in FDT).

