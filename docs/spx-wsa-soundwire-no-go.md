# SPX internal speakers (WSA881x on SoundWire) — ~~definitive NO-GO~~ **RETRACTED**

> **RETRACTION (2026-07-01):** The conclusion below was **overturned by the
> 2026-06-29 session**: with the slimfix kernel + stock paged AHB bridge +
> `spx_frame_phase` sweep, the SoundWire **frame generator DOES lock from APPS**,
> **master-register reads DO work**, and **a WSA slave DOES respond** (`DEVID_0`
> reads real data ~2/3 of the time). The garbled/empty DevID reads documented
> below were caused by (a) the bridge running un-paged in the probe used here and
> (b) a **two-amp device-0 clash** — both WSA881x power up together (shared
> powerdown line in the DT) and answer device 0 simultaneously
> (`MASTER_CLASH_DET`, garbled DevID, `AUTO_ENUM_FAILED`). db845c survives the
> same shared pin because its master has MMIO+IRQ for the HW auto-enumerator;
> SPX's SLIMbus-bridged IRQ-less master does not.
> **Current blocker:** the device-0 clash. **Decisive staged test:** GRUB entry
> "EXPERIMENTAL: WSA SINGLE-AMP test" (`dtb.wsairq-1amp`, `right_spkr`
> disabled) — if the lone amp enumerates as `0217:2010` and attaches, sequenced
> one-at-a-time bring-up is the fix and sound is reachable.
> The register-level *methodology* below remains valid; the *interpretation*
> ("slave answers nothing / ADSP-owned / unfixable") does not.

**Date:** 2026-06-23
**Board:** Microsoft Surface Pro X (sc8180x / SQ2)
**Verdict:** The built-in WSA881x speaker amps **cannot be driven from the host
Linux stack.** Proven by direct experiment, not inference: the amps assert
electrical *presence* on the codec-internal SoundWire bus but return **no data to
any register read and accept no register write** — power, clock, and frame
generator are all confirmed good. This is a platform lockdown (the WSA SoundWire is
ADSP-owned and the only loadable ADSP audio firmware is the stubbed public blob),
not a kernel bug. Stop host-side WSA bring-up work.

This supersedes the earlier `spx-speakers-no-go.md` with register-level proof.

---

## TL;DR

| | |
| --- | --- |
| **Goal** | Get the two internal WSA881x amps to attach on SoundWire so audio plays (no 3.5 mm jack — these are the only built-in output). |
| **Result** | Amps are *electrically present* (assert the device-0 presence bit) but **digitally silent**: a direct SCP DevID read returns nothing, and a device-number *write* is not accepted. |
| **Root cause** | The WSA SoundWire register/data path is owned by the ADSP (Windows path), not the host codec-internal master. The host master can sense presence but cannot transact. The ADSP firmware that *could* drive the amps is the **stubbed** public `qcadsp8180.mbn` (no SoundWire/WSA code); the real one is PAS-signing-locked. |
| **Not the cause** (all measured) | power / SD_N GPIO, SWR clock to slaves, frame generator, bus-clock rate, auto-enum logic, interrupt servicing, the no-IRQ poll, FIFO state. |
| **Fixable from Linux?** | **No** — would require the signed full ADSP firmware (unobtainable) or a hardware path the host does not own. |
| **Real audio paths that DO work** | Bluetooth A2DP, USB-C audio adapter/dock (`snd-usb-audio`), DisplayPort audio over USB-C. All bypass the ADSP/WSA entirely. |

---

## Topology (identical to Qualcomm db845c / sdm845 reference)

```
SoC ──SLIMbus──► WCD9340 codec ──internal SoundWire master (reg block 0xc85)──► 2× WSA881x
                 (slim217,250)     "qcom,soundwire-v1.3.0"                       (sdw10217201000,
                 host-controlled   driven by drivers/soundwire/qcom.c             mfg 0x0217 part 0x2010,
                                   via the codec AHB bridge over SLIMbus          DT dev# 1 & 2, share one
                                   (qcom_swrm_ahb_reg_read/write,                  SD_N GPIO = wcdgpio pin 1)
                                    WCD934X_SWR_AHB_BRIDGE_* @ 0x0c91)
```

- DT: `arch/arm64/boot/dts/qcom/sc8180x-wcd9340.dtsi`
- db845c uses this **exact** codec + master + amp + shared powerdown GPIO
  (`sdm845-db845c.dts`) and enumerates fine. SPX does not.

### The SPX-specific difference
The WCD9340 external INT (DSDT `\_SB.GIO0` pin `0x100`) has **no usable Linux IRQ**:
there is no mainline `QCOM040D` ACPI GPIO driver and the sc8180x TLMM only covers
pins 0–190. So:
- `drivers/mfd/wcd934x.c` is patched to tolerate a missing codec IRQ.
- `soundwire@c85` has no `interrupts-extended` → `qcom-soundwire` probes with
  `irq <= 0` ("No IRQ found, SoundWire interrupts will not be available").
- A custom poll worker (`spx_swrm_enum_work`, gated by the module param
  `soundwire_qcom.spx_core_enum=1`) substitutes for the IRQ-driven enumeration.

---

## What was confirmed working (each measured, ruled OUT as the cause)

| Subsystem | Evidence | State |
| --- | --- | --- |
| Amp power / SD_N | `wsa881x_probe` runs, drives SD_N enable. The ACTIVE_HIGH/LOW DT flag is a **driver no-op** (`gpiod_is_active_low()` cancels it — physical output is identical either way; only a `dev_warn` differs). | powered |
| SWR clock to slaves | codec `SWR_CONTROL` (0x0d43) = `0x01`, `WCD934X_CDC_SWR_CLK_EN_MASK = BIT(0)` set; `mclk` enabled @ 9.6 MHz. Master `clk_prepare_enable("iface")` at probe (qcom.c:1599) — the `"iface"` clock is the codec `swclk` gate → sets `SWR_CLK_EN`. | running, before enum |
| Frame generator | `SWRM_COMP_STATUS` (0x014) bit0 set | enabled |
| Bus-clock rate | 9.6 MHz, **identical to working db845c** | not a signal-integrity issue |
| MCP config | `SWRM_MCP_CFG` (0x1048) = `0x3fff00` (`CMD_NO_PINGS=0x1f`); frame ctrl (0x101c) = `0x07` | configured |
| Slave presence | `SWRM_MCP_SLV_STATUS` (0x1090) bit0 flickers `0x1`↔`0x0` | amp is electrically on the bus |

---

## The failure, pinned to the register

The HW auto-enumerator **runs and fails** — the latched interrupt status is the
fingerprint (read at the correct v1.3 offset `0x200`, *not* the v2.0 `0x1000` region):

```
SWRM_V1_3_INTERRUPT_STATUS (0x200) = 0x822
   = NEW_SLAVE_ATTACHED (BIT1) | RD_FIFO_UNDERFLOW (BIT5) | AUTO_ENUM_FAILED (BIT11)
SWRM_V1_3_INTERRUPT_CLEAR  (0x208) = 0x00
SWRM_V1_3_INTERRUPT_CPU_EN (0x210) = 0x00   ← gated off by `ctrl->mmio && irq > 0`
SWRM_ENUMERATOR_SLAVE_DEV_ID_* (0x530..0x550) = all 0x00   ← no DevID ever captured
```

The auto-enum's own DevID read **underflows** (`RD_FIFO_UNDERFLOW`): the slave
returns no DevID, so the enum aborts (`AUTO_ENUM_FAILED`) and the device-ID slots
stay empty. The amp pings presence but answers no register read.

---

## Every attempt, and why each failed

| # | Attempt | Result / why it failed |
| --- | --- | --- |
| 1 | WSA `powerdown-gpios` `ACTIVE_HIGH`→`ACTIVE_LOW` (DTB) | **No-op.** `wsa881x` cancels the flag; physical SD_N was already correct. Power was never the issue. |
| 2 | Polled enumeration (re-read status + `qcom_swrm_enumerate` every 250 ms) | Reads only the enumerator **output** slots (0x530+); they stay 0x00 because the auto-enum failed and was never re-armed. |
| 3 | Core enumeration bypass (disable auto-enum, set `status[0]`, let `sdw_program_device_num` read device-0 SCP DevID via the cmd-FIFO) | `cmd-FIFO write-overflow` + `read-underflow`, `DEVID read fail:-5` — the **same** wire-side underflow the auto-enum hits, surfaced differently. |
| 4 | Ordering fix: re-run auto-enum from the poll after the amps are powered (`SWRM_COMP_SW_RESET` + `qcom_swrm_init`, every 8th pass) | Auto-enum still captures nothing (slots 0x00). Boot timestamps had shown the boot-time auto-enum runs *before* `wsa881x` powers the amps, but re-running it on a powered bus did not help. |
| — | "Service the latched interrupt" (read 0x200, write back to 0x208, flush FIFO) | **Refuted before testing** (multi-agent adversarial review): `qcom_swrm_init()` *already* writes `INTERRUPT_CLEAR=0xFFFFFFFF` and re-enables auto-enum on every call, and attempt #4 ran it ~4× — yet `0x200` re-latched to `0x822`. Clearing a status bit cannot change what the slave drives on the wire. |
| 5 | **Decisive probe** (below) | Settled it: slave returns no DevID and accepts no device-number write. |

---

## The decisive probe (attempt #5)

A one-shot diagnostic in `spx_swrm_enum_work` (gated `spx_core_enum=1`): on first
device-0 presence, take manual control of the cmd-FIFO (disable auto-enum, clear
interrupts, flush FIFO), then **(1)** read the WSA's SCP DevID directly at device 0
and log the raw bytes, and **(2)** force-write a device number — a *write* needs no
slave echo, so it breaks the read-DevID-before-you-can-talk chicken-and-egg — and
re-read the DevID at that number.

Result:

```
SPX DIAG dev0 DevID    rc=4  id=aa aa aa aa aa aa  int_sts=0x802
SPX DIAG dev1(forced)  slv=0x1  rc=4  id=aa aa aa aa aa aa
```

- `rc=4` = `SDW_CMD_FAIL_OTHER`; the `id` bytes are unchanged from the `0xAA` fill
  pattern → the slave returned **zero** DevID data on a direct read at device 0.
- The forced `SCP_DevNumber=1` write **did not take**: `slv=0x1` means the amp is
  still parked at device 0, and the re-read at device 1 also returned nothing.

**Conclusion: the WSA SoundWire interface ignores reads *and* writes; it only
asserts electrical presence.** With power, clock, and frame-gen all confirmed good,
no host-side software change can make a slave that does not transact respond.

---

## Why it is not fixable from Linux

The only software that can bring the WSA amps up is the ADSP's audio firmware — on
Windows the **ADSP drives the WSA SoundWire** (reverse-engineering found *no*
apps-side SWR MMIO; "ADSP-owns-SWR"). The host codec-internal master can sense the
amps' presence but the register/data path is functionally owned by the ADSP LPASS
SoundWire.

The only ADSP audio firmware we can load is the **public `qcadsp8180.mbn`, which is
stubbed** — it contains no SoundWire/WSA/WCD driver code (see
`spx-firmware-cdc-regop-stub-nogo` in project memory). The real, full firmware is
gated behind Qualcomm PAS signing and is unobtainable. This is the same wall that
blocks the ADSP internal-audio path, and it is chipset-wide across sc8180x boards
(`spx-sc8180x-chipset-wide-lockdown`), not unique to SPX.

What it would take (none currently possible):
- the **signed full ADSP audio firmware** with the SoundWire/WSA driver, or
- a way to re-route the WSA SoundWire data lines to the host master (hardware), or
- an unlocked TZ/PAS path to sign a custom ADSP image.

---

## Working audio alternatives (bypass the ADSP/WSA entirely)

| Path | Driver | Notes |
| --- | --- | --- |
| **Bluetooth A2DP** | BlueZ + PipeWire/PulseAudio | No extra hardware; SPX has BT. Fastest path to audio. |
| **USB-C audio adapter / dock** | `snd-usb-audio` | Plug-and-play class-compliant. |
| **DisplayPort audio** (USB-C → monitor) | DP controller | Routes through the display path, not the ADSP. |

---

## What this effort *did* deliver (real, kept)

- **Display:** native 2880×1920 (root cause was a racy eDP AUX EDID read; fixed with
  a pinned `drm.edid_firmware` override — now the default boot).
- **q6asm ADSP mem-map:** the years-long `ASM_CMD_SHARED_MEM_MAP_REGIONS` blocker is
  **solved** (high-IOVA alias into the ADSP SMMU window + `mem_pool_id=4`); the full
  ASM→AFE→SLIMbus prepare/playback path runs clean. See `spx-q6asm-memmap-SOLVED` in
  memory. (This is moot for *output* only because the final transducer — the WSA
  amps — is the locked piece.)

---

## Appendix — reproduce / reference

**Driver:** `drivers/soundwire/qcom.c`
- `qcom_swrm_init` (~871), auto-enum enable `SWRM_ENUMERATOR_CFG_ADDR=1`, CPU-IRQ
  enable gated on `ctrl->mmio && ctrl->irq > 0` (~950).
- `qcom_swrm_enumerate` (~588) reads HW-populated DevID slots, gated on `status[i]`.
- `spx_swrm_enum_work` poll worker + the one-shot DevID probe (gated `spx_core_enum`).
- `qcom_swrm_cmd_fifo_rd_cmd` / `_wr_cmd`, `qcom_swrm_ahb_reg_read/write`.
- IRQ handler `qcom_swrm_irq_handler` (~727) — note there is **no** `AUTO_ENUM_FAILED`
  case; `RD_FIFO_UNDERFLOW` only logs.

**Codec:** `sound/soc/codecs/wcd934x.c` (`wcd934x_swrm_clock`, `swclk_gate_*`),
`include/linux/mfd/wcd934x/registers.h` (`SWR_AHB_BRIDGE` 0x0c91, `SWR_CONTROL`
0x0d43). **Amp:** `sound/soc/codecs/wsa881x.c`.

**Live register reads** (read-only debugfs; safe — *not* the pinctrl debugfs, which
oopses on sc8180x):
```
DBG=/sys/kernel/debug/soundwire/master-0-0/qualcomm-sdw/qualcomm-registers
sudo cat $DBG | awk -F: '{gsub(/ /,"",$1);a=strtonum($1)} \
  a==0x014||a==0x200||a==0x208||a==0x210||a==0x500||(a>=0x530&&a<=0x550)||a==0x1090 {print}'
```
Codec SWR control (regmap debugfs `217:250:1:0`, register `0x0d43`): `0x01` = SWR
clock enabled.

**Run the probe:** boot the "EXPERIMENTAL: WSA speaker fix" GRUB entry (carries
`soundwire_qcom.spx_core_enum=1`), then `scripts/spx-wsa-test.sh` — the `SPX DIAG`
lines report the raw DevID bytes.

**Key SoundWire register offsets** (v1.3, in `qcom.c`): `INTERRUPT_STATUS=0x200`,
`INTERRUPT_CLEAR=0x208`, `INTERRUPT_CPU_EN=0x210`, `ENUMERATOR_CFG=0x500`,
`ENUMERATOR_SLAVE_DEV_ID_1/2(m)=0x530+8m`, `MCP_SLV_STATUS=0x1090`,
`CMD_FIFO_CMD=0x308`, `COMP_SW_RESET=0x008`. SCP (`sdw_registers.h`):
`SCP_DEVNUMBER=0x46`, `SCP_DEVID_0..5=0x50..0x55`.
