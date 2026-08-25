# qcslimbus8180.sys transport RE (Surface Pro X)

Target: `~/Documents/drivers/FileRepository/qcslimbus8180.inf_arm64_4e26050f56aec0c6/qcslimbus8180.sys` (185 KB ARM64, PDB path `Z:\b\WP\slimbus\rel\10.5\ARM64\Release\qcslimbus8180.pdb`).

## Watermark findings

**UNRESOLVED at the numeric level — and the reason is itself the finding.**

`qcslimbus8180.sys` contains **no watermark constant anywhere in its code or data
sections**. The driver's own strings show it is not the entity that owns FIFO
thresholds:

- `Attempt to submit descriptors when BAM handle is NULL`
- `Attempt to submit descriptors when BAM is not connected`
- `Attempt to submit descriptors when port channel is being removed`
- `No room for new port BAM descriptor xfer`
- `Error returned from BAM pipe transfer`

(all `.text`, VA 0x140023f30-0x140023fe0). This is a **BAM DMA pipe driver**: its
job is to move buffer descriptors between host memory and the SLIMbus BAM, not to
program slave-port watermarks. The watermark for a WCD934x RX port lives in
codec-page registers (`SLIM_PGD_PORT_CFG`) written by whoever owns the codec — on
Windows that is `qcauddev8180.sys` / ADSP AFE, not qcslimbus.

Cross-check against Linux: `sound/soc/codecs/wcd9335.c:41-49` defines
`SLAVE_PORT_WATER_MARK_{6,9,12,15}BYTES = 0..3`,
`WCD9335_SLIM_WATER_MARK_VAL = (2 << 1) | 1 = 5` (12 bytes, port enabled).
`wcd934x.c` inherits the same 12-byte convention. If Windows programs 15 bytes
(constant 3 → encoded value `(3<<1)|1 = 7`), that single register write would be
done by the codec-side owner (qcauddev/ADSP), so **this binary cannot confirm or
refute it**; check `qcauddev8180.sys` instead.

## Channel configs

The INF (`qcslimbus8180.inf`, `[Hardware_Registry_Base]`, lines 69-87, UTF-16)
defines **two SLIMbus master instances** and no per-use-case (48 kHz stereo
speaker) audio parameters:

| Key | SLM1 | SLM2 |
|---|---|---|
| MasterEA | `00 00 A0 02 17 02` | `01 00 A0 02 17 02` |
| MyEE | 1 | 1 |
| LocalBasePortNum | **11** | **5** |
| NumLocalPorts | **5** | **1** |
| LocalChannelBaseNum | **65** | 65 |
| BamBaseAddr | `0x17184000` | `0x17204000` |
| NumChld / child | 1 → `SLM1\QCOM0424` | 0 |

Device enumerates as `ADSP\QCOM0410`; the child `QCOM0424` is the WCD934x codec.
There are **no packet-size, sample-rate or channel-count keys** — those live in
ACDB/miniport, not here. What this does establish is the *master-side port
allocation*: SLM1 owns master ports 11-15 with logical channels starting at 65,
SLM2 owns master port 5.

## Programming interface

**BAM DMA + QMI over IPC Router — not direct register pokes to the SLIMbus
controller, and not raw ADSP APR messages either.** Evidence:

- Import table includes `MmMapIoSpaceEx`, `MmAllocateContiguousMemorySpecifyCache`,
  `MmGetPhysicalAddress` — used for the BAM ring, plus BAM-specific strings
  ("BAM pipe transfer", "BAM descriptor xfer").
- It embeds the full Qualcomm **QMI/QCCI-over-IPC-router** stack
  (`qmi_cci_xport_ipc_wdf.c`, `ipc_router_core_open_with_options`,
  `\Device\IPC`, `ipcr_xport_open`) and registers PnP notifications for
  `\Device\Slimbus` / `\Device\Slimbus2`.
- So the model is: qcslimbus exposes a bus/child-device stack (`SLIMBUS_CLIENT_CONTEXT`,
  `SLIMBUS_DEVICE_CONTEXT`, `SLIMBUS_ISR_CONTEXT`, `SLM_Child%02d`); channel data
  flows through **BAM descriptors** at `0x17184000`/`0x17204000`; control/messaging
  goes out via **QMI service calls on the IPC router** toward the entity that owns
  SLIMbus messaging (the ADSP side).

## Frame geometry

No superframe/subframe/divider constants were identified in this driver's code
or data sections; the only frame-related content is generic QMI boilerplate.
The INF carries no geometry keys either. UNRESOLVED: geometry appears to be
firmware/ADSP side (consistent with our earlier finding that Windows never
writes `SCP_FRAMECTRL` from the apps processor).

## Relevance to RX0 overflow

The RX FIFO that overflows on our board is the **codec-side (WCD934x slave port)
FIFO**, whose threshold register is `SLIM_PGD_RX_PORT_CFG`. qcslimbus8180.sys
never touches it — it only feeds master-side BAM pipes. Two consequences:

1. On Windows the RX watermark is programmed by the same path that owns the
   codec registers (qcauddev/ADSP AFE). Our Linux `wcd934x.c` hardcodes the
   12-byte value; a Windows-vs-Linux mismatch there remains plausible but must
   be verified against `qcauddev8180.sys`, not this file.
2. Because qcslimbus moves data via BAM DMA into a contiguous ring
   (`MmAllocateContiguousMemorySpecifyCache`) and signals completion through QMI,
   the *host* side has no per-sample PIO timing pressure. Any static we see from
   host-side SLIMbus timing models does not apply to the data path — consistent
   with our earlier kprobe result that nothing writes the bus during steady-state
   playback.

## Confidence + open questions

- Watermark numeric value: UNRESOLVED here by design; next source is
  `qcauddev8180.sys` or the ADSP image's AFE SLIMbus module. Confidence that
  qcslimbus does not contain one: high (strings + section sweep of .text/.rdata/
  PAGE/INIT found no such constant).
- The earlier partial-pass note about per-port ctx+0x1d8/+0x1dc saved/active
  values is consistent with driver-local BAM/channel state, not codec FIFO
  watermarks; treat those offsets as internal-only evidence.
- Channel geometry (packet size/rate/count): confirmed absent from INF; lives in
  ACDB + miniport as previously established.
- Open: whether SLM1's five ports 11-15 map to the WCD9340's internal-master
  ports used for speaker RX; our DT uses master DP1/DP4 for the two endpoints,
  which are *slave*-side numbers, so no contradiction was established.
