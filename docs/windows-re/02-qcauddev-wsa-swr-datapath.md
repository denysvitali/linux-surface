# 02 — qcauddev8180.sys: WSA881x SoundWire datapath (apps-side SWR master)

Binary: `~/Documents/spx-winlive/qcauddev8180-LIVE.sys`
(sha256 `2c3f32…`; DriverStore copy sha256 `47a1b7b7…`). ARM64 PE.
Method: pure static disassembly with capstone (`/tmp/wcd.py` harness,
throwaway scripts `/tmp/runNN.py`). No hardware touched, no boot changed.

Scope of this document: **everything between the ADSP/AFE boundary and the
WCD9340-internal SoundWire bus** as implemented in the Windows apps-side
driver — the SWR master protocol stack, its hardware access engines, port
configuration, bank switching, enumeration and interrupt handling. The WSA881x
codec-register sequences (PA bring-up `0x140098af0`/`0x140099058`, shutdown
`0x14009a228`, cold-init tables) are codec-side and are only referenced here
where they call into this layer.

Headline findings up front:

1. **Windows drives the SWR master through the exact same paged AHB bridge
   Linux uses** (bridge base `0xc85`, length/type reg `0xc95`, ready/status
   `0xc96`, 5-retry polls). Our bridge discipline is the ground-truth
   implementation, byte-for-byte equivalent.
2. **Windows' bank switch never sends a broadcast `SCP_FrameCtrl`
   transaction.** It rewrites every port's transport parameters into the
   *destination* bank (master words and slave registers, from one source of
   truth) and then flips an internal context byte; the frame changes shape at
   the next bank boundary.
3. Every register encoding (frame ctrl, DP_PORT_CTRL word packing, dev-id,
   slave status) matches Linux `drivers/soundwire/qcom.c` exactly.
4. Every command-FIFO write is followed by a drain/status transaction with
   retries — Windows never trusts a submitted write either.

---

## 1. State layout (globals)

| location | meaning |
|---|---|
| `[0x1400a0020]` | pointer to the live SWR runtime context (`ctx`) |
| `0x140022a70` | static context base; `[byte @0x140022a70]` = bus-started flag |
| `ctx+0x00` | active bank byte (0/1), toggled internally |
| `ctx+0x01` | dirty flag (pending re-program) |
| `ctx+0x02` | command counter byte (low 3 bits go into each slave write) |
| `ctx+0x04` | non-zero = allowed to auto-idle after events |
| `ctx+0x08` | frame-shape selector (indexes timing table A) |
| `ctx+0x0c` | second frame parameter (indexes timing table B) |
| `ctx+0x14` | extra frame-ctrl field (used only in one hw revision path) |
| `ctx+0xd0+i*0xc` | per-port transport record, i = 0..14 (see §5) |
| `ctx+0xf0` | enabled-interrupt mask |
| `ctx+0xf4` | latched previous interrupt status (edge detection) |
| `ctx+0x100`, `ctx+0x108` | two mutexes (bus lock, trace/log lock) |
| `ctx+0x110` / `ctx+0x118` | registered slave-irq callback ptr / saved arg |
| `ctx+0x120` | idle refcount |
| `ctx+0x124` | last drain success flag |
| `ctx+0x148` (= `0x14022bb8`) | 12 device records × 0x30 bytes (enumeration) |
| `[0x14022ba0]` | attach callback fnptr |
| `[0x14022b38]` | detach callback fnptr |
| `[0x14022bb0]` | raw `MCP_SLV_STATUS` cache |
| `[0x1400a002c]` | bypass flag: non-zero skips the `0xc96` ready poll entirely |
| `[0x1400218ec]` | flag gating the `0xc95` length RMW |
| `[0x1400215ae]` | cached previous `0xc95` byte for that RMW |
| `[0x1400a0058]` | shared refcount; 1→0 transition signals an event via `0x14007ce48` |
| `[0x14001a380]` | import-dispatch fnptr table (RmAlloc/RmFree/etc.) |

## 2. Register map, Windows-observed vs Linux

All accesses are master-relative offsets submitted through the bridge engines
of §3. Names on the right correspond to Linux `drivers/soundwire/qcom.c`
(≈ where the match is by structure rather than a verified upstream symbol).

| Windows reg | use in qcauddev | Linux equivalent |
|---|---|---|
| `0x200` (rd, len 3) | interrupt status, read at top of DPC | `SWRM_INTERRUPT_STATUS` (0x200) |
| `0x208` (wr, len 3) | written back with the just-read status = W1C clear; also `0xffffff` blanket clear | interrupt clear/mask block (≈0x208+) |
| `0x300` (wr, len 3) | slave/command writes | `SWRM_CMD_FIFO_WR_CMD` (0x300) |
| `0x30c` (rd, len 3) | command-FIFO status polled after every submit | `SWRM_CMD_FIFO_STATUS` (0x30C) |
| `0x308` (wr) | written `0xffffff` on error-class interrupts = FIFO flush | `SWRM_CMD_FIFO_CMD` flush (0x308) |
| `0x318` (wr, len 1) | pops one read-FIFO byte during read verify | `SWRM_CMD_FIFO_READ` (0x318) |
| `0x44` (wr via slave wrapper, dev 0xf) | idle/park payload (broadcast dev 15) | — |
| `0x500` (rd then wr) | paired around slave-irq callback delivery | — |
| `0x101c + 0x40*bank` (wr, len 2/3) | frame control per bank | `SWRM_MCP_FRAME_CTRL_BANK(n)` = 0x101C+0x40·n |
| `0x1024 + (bank + 4i)<<6` (wr, len 3) | master DP port ctrl per bank/port | `SWRM_DP_PORT_CTRL_BANK(n,m)` = 0x1124+0x100·(n−1)+0x40·m — algebraically identical |
| `0x1048` (rd/RMW, set bit 1) | touched inside the post-command drain | MCP/bus control region (exact name not pinned) |
| `0x1090` (rd, len 3) | slave ping/attach status | `SWRM_MCP_SLV_STATUS` (0x1090) |
| `0x530 + 8*port`, `0x534 + 8*port` (rd, len 3) | attached device ID lo/hi | no direct mainline symbol located |

Word packing of the master DP_PORT_CTRL is identical to Linux:
`sinterval | offset1<<8 | offset2<<16 | chan_en<<24`.

## 3. The two hardware access engines

### 3.1 Write engine `0x14009a0a8`

Args: `x0` → `{u32 reg_offset; u32 payload}`, `w1` = length (2 or 3).
Caller census: **22 call sites**.

1. Take bus mutex `[ctx+0x108]`.
2. If flag `[0x1400218ec]`: RMW WCD reg `0xc95` to `(old & 3) | len`
   via `PGDHLPR(0, 0xc95, 0xff, 0, new_len, 0)`, caching the old byte in
   `[0x1400215ae]` (restored afterwards). This is the paged-bridge
   length/type field — same discipline as Linux `qcom.c` plus our
   `spx_swrm_regs.ko`.
3. Copy the 32-bit payload little-endian to a local buffer; lock the WCD
   regmap (`[[0x1400a0030]+8]`, init-checked at `[+0x10]`); call `0x14000d820`.
4. Perform the transfer: `0x14006da70(arg, 0xc85, &buf, 8)` — an **8-byte
   paged-bridge transaction at bridge base 0xc85**.
5. Poll readiness reg `0xc96` via `0x14006dd98` (access width 2), up to
   **5 retries**; skipped entirely when bypass flag `[0x1400a002c]` is set.
6. Return −5 on failure else 0; unlock.

### 3.2 Read engine `0x14009a488`

Same locking and `0xc95` discipline; transfer thunk
`0x14006da70(arg, 0xc8d, buf, 4)` (**0xc8d = 0xc85 | 8 = bridge READ opcode**);
ready poll on `0xc96` with access width 2; 5 retries. **15 call sites.**

Consequence for SPX: the Windows apps-side driver performs every master
register access over the identical paged AHB bridge Linux uses. Nothing about
our bridge model (`docs/windows-re/06`, `spx-swrm-paged-bridge-required`)
needs revision; it is the Windows ground truth too.

## 4. Command-FIFO protocol stack

### 4.1 Slave register write wrapper (`0x14009ae90` family)

Builds the 4-byte SoundWire command payload on the stack:

```
[sp+0x14] = reg_lo        [sp+0x15] = reg_hi
[sp+0x16] = (cmd_ctr++ & 7) | dev_num << 4
[sp+0x17] = value
```

increments the runtime counter byte `[[0x1400a0020]+2]`, submits
`0x14009a0a8(0x300, 3)` (command FIFO), then always finishes with the drain
`0x14009ab90`. Trace GUID table `0x14001e18`. Note the low 3 bits of each
command carry a rolling counter — SoundWire v1.x command tagging — so two
identical writes in a row still differ on the wire.

### 4.2 Multi-register write + verify `0x14009afdc`

Submit loop through the write engine, then polls a readback field until
non-zero (≤10 tries, else −6), pops the read FIFO (`0x318`, len 1),
compares the command-counter byte parity, and finishes with the drain.
This is Windows verifying that its writes actually landed — the same
"never trust a write" rule CLAUDE.md encodes for SPX.

### 4.3 Post-command drain/status `0x14009ab90`

Read `{0x30c}` (FIFO status); read/RMW `0x1048` setting bit 1; poll until
field `[4:2] == 2` with nested 5×5 retries; set success flag `[ctx+0x124]`;
release one reference on the `[0x1400a0058]` event (KeWait path `0x14007ce48`).

### 4.4 Idle/park `0x14009b238`

Context `0x140022a70`; lock `[+0x108]`; decrement refcount `[--0x120]`;
when zero and `[+0x38c]==0`: slave-wrapper write with dev `0xf` (SoundWire
broadcast address 15) payload starting `0x44`, `msleep(1)` (`0x14000be80`),
KeWait `{0,3}`.

### 4.5 Teardown `0x14009bc40`

Frees/zeros the 12 device slots and flag `[0x1400a0029]`.

## 5. Port configuration — `0x14009b308` (prepare)

Iterates ports `i = 1..0xf`; per-port record stride 0xC rooted at
`[0x1400a0020]+0xd0+i` (cursor step 0xC); records whose first byte is 0 are
skipped.

Record fields observed in use:

| offset | meaning |
|---|---|
| `+0x00` | valid/enable byte |
| `+0x1d` | slave port number |
| `+0x1e` | slave device number |
| `+0x24` | sinterval (also becomes slave-side value A) |
| `+0x25` | offset1 (slave-side value B) |
| `+0x26` | offset2 (slave-side value C) |
| `+0x27` | channel mask / type-dependent extra byte |
| pending byte | "needs re-program in destination bank" flag |

Master side: `reg = 0x1024 + (bank_byte + 4*i) << 6`, word assembled
`[+0x24] | [+0x25]<<8 | [+0x26]<<16 | [+0x27]<<24` — the exact Linux
`DP_PORT_CTRL` packing — submitted `(reg, 3)`.

Slave side: reads `[+0x1d]`=slave port, `[+0x1e]`=dev, then writes the
banked slave registers at `(bank_byte + port*16)<<4 + …`:

- `+0x20` ← `[+0x24]`  (ChannelEn page — cf. our trace `0x0120=0x01`)
- `+0x22` ← `[+0x25]`  (PortCtrl     — cf. `0x0122=0x07`)
- `+0x24` ← `[+0x26]`  (OffsetCtrl1  — cf. `0x0124=0x01`)
- `+0x25` ← `[+0x27]`  only when port type ≠ 1 (high half of the offset word)

and marks the record pending. Ordering and addresses match our captured
bring-up trace line-for-line (`0x0122=0x07 0x0124=0x01 0x0120=0x01`).

## 6. Bank switch — `0x14009b5e0`  ★ decisive finding

```
target_bank = [ctx+0] ^ 1
for each port record with pending flag set:
    write master 0x1024 + (new_bank + 4i)<<6
             ← [+0x25] | [+0x26]<<8 | [+0x27]<<16     (three bytes only;
                                                        chan byte untouched)
    write slave reg ((2 + new_bank + port*16)<<4) ← 0   (destination-bank
                                                        page; see §13 item 1)
    clear pending flag
```

There is **no broadcast `SCP_FrameCtrl` write anywhere in the switch**, and no
`0x0070`-style SCP command at all in this layer. Windows programs the
*destination* bank's master and slave registers ahead of time from one source
of truth; the separate frame-control writer (§7) flips `[ctx+0] ^= 1`, after
which the wire frame changes shape at the next bank boundary.

Implications for SPX:

- A dropped broadcast `SCP_FRAMECTRL` write being invisible (CLAUDE.md,
  whole-boot-silence section) is not a Windows failure mode because Windows
  never issues one. Our historical mid-stream recovery that "mirrored the
  enabled configuration into the still-active bank" was directionally
  Windows-like, but the true Windows mechanism is stronger: **both banks are
  kept complete and correct at all times; the flip is pure bookkeeping.**
- `spx_mirror_banks` duplicated each write at write-time and desynced the amp;
  that is a different mechanism from composing each bank independently from
  port records. Do not conclude Windows-parity from `spx_mirror_banks=1`.
- A faithful Linux port of this design = maintain per-bank shadow words for
  master DPn and slave DPn, program the inactive bank on any parameter change,
  and switch by writing `MCP_FRAME_CTRL_BANK[new]` only — the only
  wire-visible master-side act (§7).

## 7. Frame-control writer — `0x14009b8e0`

Toggles `[ctx+0] ^= 1`, then writes
`0x101c + new_bank*64 ← ([ctx+8]&7) | ((…)&0x1f)<<3 | ((…)&7)<<5`
(len 2, or 3 when `[0x14022bf8]==2`, adding `[ctx+0x14]&0x7f << 16`),
then walks ports 1..0xB (enabled test at `ctx_table−0x2c`) writing the slave
enable register `((new_bank + 0xe + port)<<4)` with value
`(port == 1)` through `0x14009ae90`, and finally clears the `[ctx+1]` dirty
flag.

**The master-side bank change therefore emits exactly one master register
write (the frame-ctrl word) plus per-port slave enable writes — never a
broadcast SCP transaction.**

## 8. Frame timing — `0x14009b800`

Tables `[0x1400a0188]` (indexed by `[ctx+8]`) and `[0x1400a0210]` (indexed by
`[ctx+0xc]`); `w12 = row*col`; then

```
udiv  0x09207C00 / (col+1)
lsl   1
udiv  /(row*col)
result = popcount(channel_mask) * [x0+4] / divider
```

`0x09207C00` = **153,600,000** = 19.2 MHz × 8. Consistent with our settled
finding that the SWR core runs from the 19.2 MHz family with a divider
(`spx_dr_freq=19200000` dual-edge experiment → silence; 9.6 MHz default
audible): Windows derives its clock divider from the 153.6 MHz root, not from
a raw 19.2 MHz dual-edge assumption. Logged via trace GUID `0x14001e18`.

## 9. Enumeration — attach worker `0x14009bdb8`

1. Read `MCP_SLV_STATUS {0x1090}` len 3.
2. Walk 12 device records at `[0x14022bb8]` (= `0x140022a70+0x148`), 0x30 each,
   consuming the status **two bits per device**:
   - `case 1` (present): `RmAlloc(0x0f)` name, read DEV-ID low
     `0x530 + port*8` and high `0x534 + port*8` (both len 3), store into
     record `+2/+6`, invoke attach callback `[0x14022ba0]` (through the
     import dispatcher `[0x14001a380]`), set `record[0]=1`,
     `record[+1]=port`.
   - `case 2` (detached): invoke detach callback `[0x14022b38]` with
     `record+8`; flag `|= 2`.
3. Cache raw status in `[0x14022bb0]`; finish with drain `0x14009ab90`;
   optional event reset `[0x14021500]`.

This is exactly the semantics our guarded harness implements manually:
observe a real per-device presence bit before treating the amp as attached,
and read the dev-id registers to learn the assigned device number.

## 10. Interrupt/status DPC — `0x14009c2a0`

Full decode:

1. Gate on started byte `[0x140022a70]`; take mutex `[ctx+0x100]`; trace
   enter (table `0x14001e18`, id `#0x34`).
2. Increment `[0x1400a0058]`; on 0→1 transition KeWait `{0,3}` +
   `msleep(1)` (serialize against the idle path).
3. Loop: read `{0x200}` len 3 (interrupt status); write `{0x208}` ← the
   captured status (W1C clear); mask with enabled bits `[ctx+0xf0]`
   (`w21 = [ctx+0xf0] & status`), edge-compare against latched `[ctx+0xf4]`.
4. Single-bit walk (`lsr w20, w20, #1` per iteration):
   - **bit 0** → call attach worker `0x14009bdb8` (device present/absent).
   - **bits 0x40 / 0x80** → error class: write `{0x308}` ← `0xffffff`
     (command-FIFO flush) and continue.
   - **bit 0x800** → read `{0x500}`, write `{0x500}`, set byte `[sp+0xc]`,
     zero `[ctx+0x110]`, invoke the registered slave-irq callback
     `[ctx+0x118]` through the import dispatcher.
   - **bit 0x4000** → decrement `[0x1400a0058]`; on reaching 0 signal the
     event (`0x14007ce48`, arg 4) — wakes idle waiters.
   - **bit 0x10000** → ignored.
   - other set bits → traced as unexpected (ids `#0x35/#0x36/#0x37/#0x38`).
5. Tail: if the attach worker returned 1 and `[ctx+4]` is set → idle-park
   `0x14009b238`; final refcount decrement + event signal; unlock mutex; ret.

Architectural consequence: Windows leans on the SWR interrupt block (`0x200`)
to notice attach/detach and bus errors. SPX has no usable IRQ from this
controller, so Linux must poll `MCP_SLV_STATUS`/`0x200` — which is precisely
what our snapshot/harness machinery does. Nothing in the DPC suggests a
register write sequence we are missing; it is reactive only.

## 11. Trace GUID tables (correction of an earlier note)

Referenced tables (adrp 0x14001000 pages + `add #imm`):

- `0x14001df8` — write-path traces
- `0x14001c58` — read-path traces
- `0x14001e18` — slave-write / drain / timing traces

An earlier working note listed `0x14001c8c0`/`0x14001c8d0`; both addresses are
zero-filled and referenced by nothing — disregard them.

## 12. Cross-check summary against Linux / SPX state

| area | verdict |
|---|---|
| paged AHB bridge (`0xc85`/`0xc95`/`0xc96`, 5-retry ready poll) | identical to Linux `soundwire_qcom` + `spx_swrm_regs.ko` |
| `DP_PORT_CTRL` word packing | bit-exact (`en<<24 \| off2<<16 \| off1<<8 \| sinterval`) |
| frame-ctrl banking (`0x101c+0x40·bank`) | identical |
| slave DPn banked regs (`port*0x100 + bank*0x10 + 0x20/0x22/0x24/0x25`) | identical to our `0x0120/0x0122/0x0124` trace |
| `MCP_SLV_STATUS` 2-bit-per-device semantics | identical; Windows caches the raw value and requires a real present bit before attaching |
| command FIFO (`0x300` wr / `0x30c` status / `0x318` pop / `0x308` flush) | identical roles; Windows drains and verifies after every write |
| bank switch | **different**: Windows programs the destination bank (master+slave) and flips internally; no broadcast SCP_FrameCtrl |
| clocking | derived from the 153.6 MHz root; compatible with our 9.6 MHz audible setting |

## 13. Incomplete items

1. Exact value written to the destination-bank slave register in the bank
   switch (`0x14009b5e0`): disassembly shows immediate 0 at sub-offset 0x20;
   needs re-verification whether a record byte is actually copied there.
2. Slave-enable addressing in the frame-control writer (`0x14009b8e0`):
   `(new_bank + 0xe + port)<<4` — the `0xe<<4 = 0xE0` component may be an
   SCP-region offset or a decode artifact; re-derive before relying on it.
3. Producer of the per-port records (`+0x24..+0x27`, `+0x1d/+0x1e`) not yet
   traced to its caller; connecting it to the already-decoded static
   left/right descriptor tables (left slaves 1/2/3/4 → masters 1/2/3/7 masks
   1/f/3/3; right 4/5/6/8) remains open.
4. Linux-side names for auxiliary registers `0x44` (idle payload), `0x500`
   (callback pair), `0x1048` (drain-time RMW) not pinned.
5. Small glue: `0x14009ad18` lock helper, exact entry boundary of the
   `0x14009ae90` wrapper family, callers of the timing calc `0x14009b800`.
6. Codec-side WSA881x sequences (`0x140098af0`, `0x140099058`,
   `0x14009a228`, cold-init tables, protection-disabled profile) live in the
   companion doc and are intentionally out of scope here.
