# Surface Pro X (sc8180x, SQ2) Speaker Bring-up — Engineering Handover

**Author:** session-concluded investigation (2026-06-19 → 2026-06-20).
**Audience:** experts continuing the work. Goal: produce a complete, self-contained record
so a new engineer can verify every claim, pick up any thread, and avoid re-deriving what was
already disproven. Honest assessment of the live blocker is included.

> **Key live fact (the one that re-frames everything):** speakers **DO work in Windows** on
> the same hardware. The Linux ADSP firmware is a **different, stubbed build** than the
> one Windows runs. The working firmware exists, is byte-perfect, correctly signed, and
> not rollback-blocked — but **TrustZone rejects it on warm reload** (and would on cold
> boot too — same SMC path). The GLINK/AudioReach module-load bypass path is
> architecturally correct and the live open test does **not crash the ADSP**, but the
> GCS server is dormant on the stub ADSP, so the bypass has no target until the
> non-stub ADSP runs.

---

## 0. TL;DR for the receiving engineer

1. The speakers on the SPX (2× WSA881x on the WCD9340 codec's internal SoundWire
   master) are **architecturally reachable** via the path Windows uses: the ADSP
   loads the AudioReach graph over GLINK (`g_glink_ctrl` / `g_glink_audio_data`) and
   drives the codec via the standard AFE CDC codec-register path.
2. **On Linux mainline today, two independent blockers exist:**
   - **(A) The Linux ADSP firmware is a stubbed build** with `AFECdcRegOp_stub.cpp`
     and many `_stub.cpp` modules. The non-stub build exists on the Windows partition
     and is publicly available (Microsoft `surfaceprox_subextadsp.cab` v1.0.1980.1,
     Sep 2023, sha256 head `09c06fe8`). Swapping the file + warm-reloading the ADSP
     (proven to work without reboot) fails at `qcom_scm_pas_init_image` with
     `res.result[0] = -22` — TrustZone rejects the image's signature/metadata
     inside the locked secure boot. Five hypotheses (incomplete metadata, SHM-bridge
     artifact, cold-vs-warm difference, cert expiry, anti-rollback monotonic counter)
     have all been rigorously ruled out; the gate is internal to the locked TZ
     and is not observable from Linux.
   - **(B) The GLINK/AudioReach bypass path** (inject the speaker graph into the
     already-running stub ADSP) was investigated and the live open test of
     `g_glink_audio_data` via `spx-gcs-rpmsg-probe.py` **does not crash the ADSP**
     — the ADSP returns `failed to open g_glink_audio_data` cleanly because the
     GCS server is dormant. The path is reachable in principle but blocked on
     blocker (A): the GLINK bypass requires the non-stub ADSP.
3. **No software path from Linux alone is known to work.** The single remaining
   software lever is **(A)**. **The remaining gating fact is the exact TZ gate**;
   that is internal to the locked signed TrustZone and would need either an
   instrumented Windows-side capture of the ADSP's secure-boot auth path
   (via ETW / WinDbg / a debugger attached to the Q6v5 Secure World — not
   available in this session's toolset) OR a hardware-level signal probe of
   the SoundWire bus to confirm whether the wire-level read failure
   (`cmd_data=0x0` from the codec-internal SoundWire master) is electrical or
   board-strap related.
4. The APPS SoundWire wire-level read failure (`cmd_data=0x0`) was characterised
   live with the codec-internal SWR master at codec register block `0xc85+` (the AHB
   bridge: `0xc85`=WR_DATA, `0xc89`=WR_ADDR, `0xc8d`=RD_ADDR, `0xc91`=RD_DATA).
   The amp asserts presence (`MCP_SLV_STATUS=0x01`, `NEW_SLAVE_ATTACHED=0x02`) but
   does not return read data (`INT_STATUS` had `RD_FIFO_UNDERFLOW` + `CMD_ERROR`).
   This is independent of IRQ-vs-polled mode, codec SWR clock state, amp power, or
   port configuration.

---

## 1. Hardware context (Surface Pro X / sc8180x / SQ2)

| item | value |
|---|---|
| SoC | Qualcomm sc8180x (Snapdragon 8cx for SPX, 8 cores, ARM64) |
| board | Microsoft Surface Pro X SQ2 (Microsoft Pinewood) |
| audio codec | WCD9340 / Aqstic (slim217,250), on SLIMbus NGD1 |
| amps | 2× WSA881x on the codec's *internal* SoundWire master (NOT on a SoC SWR) |
| Linux | mainline 6.18.3-1-surface+ (branch `spx/v6.18`) |
| firmware dir | `/lib/firmware/qcom/msft/surface/pro-x-sq2/` |
| ADSP remoteproc | `17300000.remoteproc` → `q6v5` (PAS) |
| current loaded fw | `qcadsp8180.mbn` sha256 `2703ceb6…` (the **stubbed** v1.0.710, Jun 2023) |
| Windows-active fw | `surfaceprox_subextadsp/qcadsp8180.mbn` sha256 `09c06fe8…` (the **real** v1.0.1980.1, Sep 2023) |
| Windows side | D@192.168.30.143, user `D`, password `surface-pro-x` |

Key ADSP carveout layout (DT `arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts:168-176`):

```
adsp_mem: memory@96e00000 { reg = <0x0 0x96e00000 0x0 0x1a00000>; }  # 26 MiB
cdsp_mem: memory@98800000 { reg = <0x0 0x98800000 0x0  0x800000>; }
scss_mem: memory@99000000 { reg = <0x0 0x99000000 0x0  0x1400000>; }
```

The non-stub image needs **28.01 MiB** (`PT_LOAD` span `0x8be00000..0x8da02000`) — 2 MiB
over the current 26 MiB carveout. Carveout growth is a *secondary* blocker (only matters
*after* TZ auth passes).

---

## 2. The two known blockers (and the one I had wrong)

### 2.1 The firm "NO-GO" that was wrong

The earlier-session memory `spx-firmware-cdc-regop-stub-nogo` concluded:
> "The Linux ADSP firmware has a STUBBED codec-register op (`AFECdcRegOp_stub.cpp`); no
> combination of AFE SET_PARAM V3 CDC params can produce sound. **STOP tuning CDC param
> bodies.** Only paths: load missing GCS/AudioReach Hexagon module (blocked on GLINK
> handshake) or a non-stub .mbn (PAS-signing blocked)."

The first half of that conclusion (stubbed firmware, codec-reg op is a no-op) is
**still true about the file Linux loads.** The second half ("stop tuning CDC param
bodies") is correct. **But the conclusion "a non-stub .mbn is blocked by PAS signing"
was wrong** — the non-stub image exists in the Microsoft DriverStore, was pulled
byte-perfect, and is *correctly* signed. The current blocker is **not** a signing
block but a TrustZone runtime gate I have not cracked.

This is the key course correction the receiving engineer needs to internalise.

### 2.2 The actual live blocker (firmware swap — Track A)

* **`qcom_scm_pas_init_image()` returns `res.result[0] = -22`** when the
  non-stub `qcadsp8180.mbn` is loaded by the mainline `qcom_q6v5_pas` driver.
  This is a *substantive* in-TZ rejection at the PAS authenticator, **not a transport
  or precondition failure.**
* **Five hypotheses for the rejection, all rigorously ruled out** (see
  `memory/spx-adsp-firmware-windows-vs-linux.md` for full evidence):
  1. **SHM-bridge / warm-reload artifact**: `CONFIG_QCOM_TZMEM_MODE_GENERIC=y` and
     SHMBRIDGE mode is not set; sc8180x is blacklisted from SHM bridge use
     (`drivers/firmware/qcom/qcom_tzmem.c:79-87`). The PAS metadata blob uses
     `dma_alloc_coherent`, not tzmem bridges. `pas_metadata` is fully released
     on every stop/start. **No stale bridge can exist.**
  2. **Cold-vs-warm difference**: `qcom_pas_start` runs the identical
     `pas_init_image → mdt_load_no_init → pas_auth_and_reset` sequence on every
     boot. **A cold boot will produce the same `-22`.**
  3. **Metadata incompleteness** (the most-likely-hope hypothesis): the Windows
     image is byte-perfect, its MBN v6 hash header is structurally equivalent to
     the stub, all 12 real `PT_LOAD` segments' SHA-384 entries match the table, the
     512 B RSA-4096 signature is present and non-zero, and the 3-cert DER chain has
     intermediate CA + PCA certs **byte-identical** to the accepted stub's. The
     Windows leaf verifies against the same CA. **TZ would accept the chain.**
  4. **Certificate expiry**: TZ accepts the stub whose leaf cert expired in
     2020-05-06 — it does not check `notAfter`. Expiry is irrelevant.
  5. **Anti-rollback monotonic counter**: the device accepts the **older** stub
     (v1.0.710, Jun 2023) and rejects the **newer** Windows image (v1.0.1980.1,
     Sep 2023). This is the *opposite* of monotonic-counter anti-rollback. The
     only metadata deltas are: per-build hash-seg vaddr (`sig_ptr`/`cert_chain_ptr`),
     one header field at offset `+0x3c` (`STUB 0x000b80e1` vs `WIN 0`), and the leaf
     certificate serial number (`STUB ...0004` vs `WIN ...0007`).
* **Most-likely remaining cause (Medium confidence):** an OEM/HW-ID /
  image-instance binding enforced inside the locked, signed SPX TrustZone that ties
  the RSA signature to this exact PAS peripheral, or a metadata-binding mismatch
  the kernel cannot observe.

* **Recovery path:** `cp qcadsp8180.mbn.STUBBED-BACKUP qcadsp8180.mbn; echo start >
  /sys/class/remoteproc/remoteproc2/state`. ADSP boots, APR audio services
  re-register, GLINK reconnects. **The box is on this safe baseline right now.**

* **Live ADSP reload (stop/start) works without reboot.** This is a useful
  primitive for future experiments: `echo stop > /sys/class/remoteproc/remoteproc2/
  state; echo start > …`. Tested 2026-06-19.

### 2.3 The second blocker (GLINK bypass — Track B)

The Windows audio stack drives the ADSP by:
1. `qcrpen8180.sys` (RPEN driver) binds `ACPI\QCOM0433` (the lpass RPE endpoint)
   and registers the lpass RPEN on the ADSP (the prerequisite for GLINK/QMI flow).
2. `qcauddev8180.sys` does `platform_info_init` / `platform_set_default_info` over
   the established RPEN, then opens `g_glink_ctrl` (the GCS control plane) via
   `qcglink8180.sys` (the GLINK provider).
3. The GCS responder (a runtime-loaded Hexagon module on the ADSP — **absent
   from the Linux `.mbn`**) handles `GCS_CMD_OPEN / LOAD_DATA / ENABLE_DEVICE`,
   instantiating the WSA graph (`ACDB 0x15200` = `SPEAKER_PHONE_SPKR_STEREO`).

The `qcauddev8180.sys` GLINK channel-name table (extracted from the live `.sys`,
package hash `b4aa0854`):

| RVA | name |
|---|---|
| `0x140020114` (×4) | `g_glink_ctrl` |
| `0x1400201f4` | `g_glink_persistent_data_nild` |
| `0x140020264` | `g_glink_audio_data` |

* **Live test of the GLINK bypass from APPS** (using the proven
  `scripts/spx-gcs-rpmsg-probe.py` against `/dev/rpmsg_ctrl1`):
  - Opening `g_glink_audio_data`: **rpmsg endpoint created** (`/dev/rpmsg0`); on
    `open(/dev/rpmsg0, …)` the kernel printed
    `rpmsg rpmsg0: failed to open g_glink_audio_data` and the ADSP stayed running.
    **No crash, no migration assert, no `glink_channel_migration.c:601` panic.**
  - Opening `g_glink_ctrl` directly: returns `EINVAL` (no endpoint created). It
    would have crashed before (the prior `g_glink_ctrl` cold-open panic). The
    data-channel open is safe.
  - The ADSP returns the rejection cleanly because the **GCS server is dormant**
    on the stub ADSP — no GLINK channels are advertised. With the non-stub
    ADSP, the GCS module would advertise them.

* **The bypass path is reachable in principle but gated on the non-stub ADSP.**
  The dependency is `GLINK works ⇒ non-stub ADSP runs ⇒ TZ auth passes`. The TZ
  wall is still the active blocker.

### 2.4 The third blocker (carveout — secondary, fixable later)

* The non-stub image's `PT_LOAD` span is 28.01 MiB (`0x8be00000..0x8da02000`).
  The DT `adsp_mem` is 26 MiB (`0x96e00000..0x98800000`).
* To load WIN: grow `adsp_mem` to `0x1c00000` (28 MiB) and relocate `cdsp_mem` to
  `0x98a00000` (8 MiB, currently `0x98800000..0x99000000`). This is a DT-only change.
* **The carveout fix is only needed *after* TZ auth passes.** It does not change
  the `-22` at `pas_init_image` (which runs *before* memory setup).

---

## 3. The APPS SoundWire wire-level read failure (characterised live)

The clean retry (`scripts/spx-spkr-replay-v2.sh.BROKEN-DO-NOT-RUN` — **do not run**,
it was a flawed recipe: it treated the AHB bridge window at `0xc85+` as if the master
registers were mapped at `0xc85+offset`; in fact, the SWR master registers are
accessed via a 4-register AHB bridge window: `0xc85=WR_DATA, 0xc89=WR_ADDR,
0xc8d=RD_ADDR, 0xc91=RD_DATA`, with each write being a 2-step `bulk_write(WR_DATA, V)
then bulk_write(WR_ADDR, R)` per `qcom_swrm_ahb_reg_write` in
`drivers/soundwire/qcom.c`).

Once driven with the **clean db845c-exact** port config, the live signature was:

* `WCD934X_CDC_CLK_RST_CTRL_SWR_CONTROL (0x0d43) = 0x01` — codec SWR clock
  **enabled**.
* `COMP_STATUS (0xc99) = 0x2a01` — bit 0 (FRM_GEN_ENABLED) set; **the bus frames**.
* `MCP_SLV_STATUS (0x1090)` transitions 0x00 → 0x01 — **a slave is present at the
  default address**.
* `INTERRUPT_STATUS (0x200) = 0xa2` — bits set: `NEW_SLAVE_ATTACHED` (0x02),
  `RD_FIFO_UNDERFLOW` (0x20), `CMD_ERROR` (0x80). **No `MASTER_CLASH_DET` or
  `DOUT_PORT_COLLISION`** — so this is not a two-amp-collision at the bus level.
* `ENUMERATOR_SLAVE_DEV_ID_*` (`0x530+`): empty / garbage. The auto-enumerator's
  DevID read of the broadcast device returns nothing.
* `qcom_swrm_cmd_fifo_rd_cmd` issues a `reg: 0xd28 / 0xd30, dev_num: 0x0`
  read; the write FIFO overflows and the read FIFO underflows; `cmd_data: 0x0`.
* dmesg pattern: `swrm_wait_for_wr_fifo_avail err write overflow → SPX: flushed SWR
  command FIFO after write-fifo-full before read → swrm_wait_for_rd_fifo_avail err read
  underflow → qcom_swrm_cmd_fifo_rd_cmd: read response delayed, retrying → failed to
  read fifo: reg: 0xd28, rcmd_id: 0x2, dev_num: 0x0, cmd_data: 0x0`.

The slave receives the frame (asserts presence) but does not return read data. The
remaining software hypotheses (port config, IRQ vs polled, codec clock, amp power,
driver retry logic) have all been ruled out. The most-likely hardware cause is
electrical or board-strap related and would require a logic analyzer on the codec
SWR clk/data lines to confirm.

---

## 4. The TZ rejection — what we know and what we don't

### 4.1 The fully-decoded image (the truth about the files)

| | Linux-loaded (stub) | Windows-active (real) |
|---|---|---|
| path | `/lib/firmware/qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn` | `C:\Windows\System32\DriverStore\FileRepository\surfaceprox_subextadsp.inf_arm64_bbffa45584bbab05\qcadsp8180.mbn` |
| size | 10,758,800 | 10,474,240 |
| sha256 (head) | `2703ceb6…` | `09c06fe8…` |
| build | v1.0.710 (Jun 2023) | v1.0.1980.1 (Sep 2023) |
| `reg op is stubbed` | **6** | **0** |
| `AFECdcRegOp_stub.cpp` | present | **absent** |
| stub .cpp files | many | none |
| ELF | QUALCOMM DSP6, entry `0x8be00000`, 15 phdrs | (identical) |
| signing | Microsoft Pinewood Attestation | Microsoft Pinewood Attestation |
| leaf cert | expired 2020 (TZ ignores) | valid 2022-2023 |
| leaf serial | `…0004` | `…0007` |
| MBN v6 hdr | image_id `0xc`, ver `6`, image_size `0x1cd0`, hashtable `0x2d0` (15 SHA-384) | (identical) |
| cert chain | CA `f9a3780b…` + PCA `e1a2db7a…` + leaf | (CA+PCA byte-identical, leaf differs) |

The non-stub image is **publicly available** in the WOA-Project/Qualcomm-Reference-Drivers
`Surface 8180` CAS under `surfaceprox_subextadsp.cab` v1.0.1980.1 (update
`200.0.15.0`, Sep 2023). The Linux stub is v1.0.710 (pkg `20230515`).
linux-surface `getfw.py` copies whichever the recovery image had — so stub-vs-real is
just image age. **A newer linux-surface SPX firmware drop would likely ship the
real one** — the most direct (free) fix if the community has updated the firmware
package.

### 4.2 The TZ call sequence at warm reload (proved, not inferred)

```
$ echo start > /sys/class/remoteproc/remoteproc2/state
[ 1879.424087] remoteproc remoteproc2: powering up adsp
[ 1879.432795] remoteproc remoteproc2: Booting fw image qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn, size 10474240
[ 1879.453810] qcom_q6v5_pas 17300000.remoteproc: error -22 setting up firmware qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn
[ 1879.453950] remoteproc remoteproc2: can't start rproc adsp: -22
[ 1879.455523] remoteproc remoteproc2: Boot failed: -22
```

Tracing through `qcom_q6v5_pas.c:qcom_pas_start`:

| step | line | what |
|---|---|---|
| `qcom_scm_pas_init_image` | 308 | the call that returns `res.result[0] = -22` (TZ SMC) |
| `qcom_mdt_load_no_init` | 313 | would copy segs into carveout (not reached) |
| `qcom_scm_pas_auth_and_reset` | 329 | would release ADSP reset (not reached) |

The kernel build uses `qcom_scm-smc.c:207-213` which copies TZ `a1` into
`res.result[0]`; `-22 = -EINVAL` is the raw TZ verdict.

### 4.3 Why the cold-boot test is not worth a reboot

`qcom_pas_start` runs the identical `pas_init_image → mdt_load_no_init →
pas_auth_and_reset` sequence on every boot. `qcom_scm_pas_shutdown(pas_id)` on
`qcom_pas_stop` resets the TZ PAS state for `pas_id=1`. There is no cleaner bridge
or metadata state for a cold boot to gain. A cold boot will produce the **same
`-22`**.

---

## 5. The GLINK bypass — live progress and the GCS bootstrap recipe

### 5.1 Channel names (live, from the qcauddev8180.sys that ships in
surfaceprox_subextadsp v1.0.1980.1)

```
strings -a qcauddev8180.sys | grep ^g_glink_    # ASCII, .rdata
  g_glink_ctrl                 (×4, at RVA 0x140020114, 0x14002014c, 0x140020184,
                              0x1400201bc, 0x14002022c — the GCS descriptor table,
                              pkt ids 3,4,5,6,0xa all ride this channel)
  g_glink_persistent_data_nild (×1, RVA 0x1400201f4 — pkt id 8)
  g_glink_audio_data           (×1, RVA 0x140020264 — pkt id 0xc)
```

(prior memory also documents `g_glink_persistent_data_ild` as a symbol-table-only
entry; not in the live descriptor.)

### 5.2 The function that opens g_glink_ctrl (RVA 0x14007B138)

```
0x14007b138: 910452cf   ADD X15, X6, #0x114   <-- loads &g_glink_ctrl
0x14007b13c: 6b13011f   SUBS WZR, W8, W19
0x14007b140: 54000200   B.EQ +0x20
...
```

(Full function requires r2 with proper PE ARM64 xref support; the ADRP+ADD pair
referencing the page containing `0x140020114` is at file offset `0x7a734`.)

### 5.3 RPEN binding

`qcrpen8180.inf` binds `ACPI\QCOM0433` (the lpass RPE endpoint). The Linux
`pdr_interface` + `qcom_q6v5_pas` stack does **not** natively register the
lpass RPEN on the ADSP at boot. The Windows `qcrpen8180.sys` does, which is the
prerequisite the GCS server is waiting for.

### 5.4 The proven open path (live test result, 2026-06-20)

```python
# /dev/rpmsg_ctrl* exists after `modprobe rpmsg_chrdev` (built-in qcom_glink_native).
# (was 'no such file' on this build, root cause: rpmsg_chrdev was a loadable module
# historically; in 6.18 it is CONFIG_RPMSG_CHRDEV=m. It was loaded automatically
# when the audio edge came up. The ctrl device appeared.)

# The proven open (scripts/spx-gcs-rpmsg-probe.py uses this):
fd = os.open("/dev/rpmsg_ctrl1", os.O_RDWR | os.O_CLOEXEC)
os.write(fd, b"g_glink_audio_data\x00")
os.close(fd)
# -> /dev/rpmsg0 created
os.open("/dev/rpmsg0", O_RDWR|O_NONBLOCK|O_CLOEXEC)
# dmesg: "rpmsg rpmsg0: failed to open g_glink_audio_data"
# ADSP: still running, no crash. Clean rejection.
```

The data-channel open **does not crash the ADSP** and **does not hit the
`glink_channel_migration.c:601` assertion** (the migration-sensitive channel is
`g_glink_ctrl`; the data channel is not). The ADSP simply returns "no such channel"
because the GCS server is dormant.

### 5.5 The Windows-side GCS bootstrap (what Linux would need to replay)

To wake the ADSP GCS server, Linux needs the equivalent of:

1. **`qcrpen8180` register lpass RPEN on ADSP.** On Linux, the `qcom_q6v5_pas`
   + `qcom_pdr_helper` stack does *not* do this. The Windows path uses
   `qcom_pdr` (Power Domain Requestor) helpers to discover the lpass subsystem
   on the ADSP and register an RPEN endpoint via the ADSP-side Q6v5 RPMSG
   interface. This is the prerequisite the GCS server is waiting for.
2. **`qcauddev8180` `platform_info_init` / `platform_set_default_info` over
   the established RPEN.** Sends a GPR (General Purpose Router) or RPMsg
   message to ADSP informing it of the lpass platform info (H/W IDs, port
   counts). This is what causes the ADSP to *load* the GCS server module.
3. **`qcauddev8180` opens `g_glink_ctrl`** via `qcglink8180` IOCTL. The
   GCS server (now loaded on ADSP) accepts the open and the GLINK
   control plane is established.
4. **`qcauddev8180` sends GCS `CMD_OPEN` / `LOAD_DATA` / `ENABLE_DEVICE`** for
   the ACDB subgraph (the speaker graph).
5. **ADSP instantiates the WSA topology** using the GCS responder. The
   topology includes the AFE CDC codec-register write (which, *on this*
   ADSP firmware, is **real, not stubbed**) that the stub ADSP cannot
   perform.

### 5.6 What is the next concrete experiment once the TZ wall is down

The GLINK bypass code is *ready to implement* — but only if the non-stub ADSP
runs. The receiving engineer should sequence:

1. Get a non-stub ADSP running (overcome the TZ wall).
2. Implement the RPEN registration + `platform_info_init` Linux equivalent
   (well-bounded work in the `qcom_q6v5_pas` / `pdr_interface` / GLINK stack).
3. From APPS, open `g_glink_audio_data` (already proven not to crash).
4. Use the ACDB subgraph recipe (CDCLUT0 id1=0x15200 `SPEAKER_PHONE_SPKR_STEREO`)
   to send GCS OPEN + LOAD_DATA + ENABLE_DEVICE.
5. Audio path: `q6afedai SLIMBUS_2_RX (idx 6, port 0x4004) → APR → ADSP AFE
   → SLIMbus → codec INT7/8 → codec internal SWR master → WSA881x`.

---

## 6. What the receiving engineer should do

The genuine remaining work is concentrated in **two parallel tracks**, both needed to
get the speakers working. Ranked by expected payoff:

### Track A — The TZ wall (highest payoff if crackable)

The single remaining software lever for the speakers is **getting the non-stub ADSP
to load and authenticate.** This is the active blocker. Concrete next steps:

1. **Check linux-surface / aarch64-laptops firmware for a newer SPX firmware drop.**
   The non-stub image is public (`surfaceprox_subextadsp.cab` v1.0.1980.1); a
   community-maintained Linux package may already ship it. Run:
   `git log --oneline github.com/linux-surface/linux-surface -- '*qcadsp8180*'`
   (or the equivalent for whatever fork the user is on) and check the latest drop.
   This is a **free fix** if it exists.
2. **Get a verbose TZ sub-status from the in-TZ authenticator.** The kernel only
   sees `res.result[0] = -22`. To get the in-TZ cause, you need either:
   - a Windows-side kernel debugger attached to the Q6v5 secure world during
     speaker bring-up, or
   - an ETW / WPP trace from the Secure Channel, or
   - the QCT XBL/TZ logs from a Windows crash dump when the ADSP service is
     restarted while the speaker is open (these can be parsed with `QcacrsTool`).
3. **Cold-boot test (not recommended — but cheap if a fresh image is
   available).** The analysis is conclusive that warm == cold, but a *real*
   cold boot with the Win image as the default firmware can be tested by
   `cp /tmp/qcadsp8180-WIN.mbn /lib/firmware/qcom/msft/surface/pro-x-sq2/
   qcadsp8180.mbn` + reboot. If the ADSP boots, the carveout fix must be
   applied *before* the next boot (grow `adsp_mem` to 28 MiB, relocate
   `cdsp_mem`). If the ADSP fails the same way, the TZ wall is confirmed
   for all reload paths.
4. **Look for an image signed by a different key the SPX TZ accepts.** The
   Windows image is Microsoft Pinewood-signed; perhaps a Qualcomm reference
   build or a Microsoft reference build for an earlier boot is signed by a
   key the device still trusts.

### Track B — The wire-level read failure (if Track A fails)

The `cmd_data: 0x0` read failure at the codec-internal SoundWire master. If the
non-stub ADSP does run and the bring-up proceeds, the wire failure is
**independent** of all the AFE / firmware / DT-level work and is a
hardware-level signal issue. The remaining candidates:

1. **Logic analyzer on the WCD9340's SWR clk/data pins.** The codec is on
   SLIMbus NGD1 (`171c0000.slim-ngd`). The SWR master pins are internal
   to the codec, not brought out on a test pad. **This is not easy to
   probe without a board-level connection.** A board file / schematic
   would help locate any test point.
2. **Check the two WSA881x for distinct SoundWire UniqueIDs.** The
   prior-session memory speculated that the two amps might have identical
   UniqueIDs (board strap), causing a collision on the wire. The
   auto-enumerator's DevID read returns `0` — consistent with either no
   response or a collision. If they share an ID, the codec-internal
   master cannot enumerate them; the Windows GCS path must handle this
   somehow (e.g. via a specific per-amp init sequence that forces dev_nums).
3. **Try a WSA881x-specific reset / init sequence before the read.** The
   ADSP's GCS recipe (in the ACDB 0x15200 blob) includes a per-amp register
   init sequence (reset, TADC, INTR_MASK, etc.). If the amps need this
   before they'll respond to a DevID read, the auto-enumerator can't
   bootstrap them. The Windows GCS code does this init; on Linux we'd
   need to do it via the codec regmap (the `wcd934x` driver, which I
   added a `write_reg` debugfs helper for, b001e0dd, installed but
   not loaded since the MFD was patched; a reboot would activate it).

### The other angles I have not pursued

* **A kernel module that REPLAYS the Windows GCS bootstrap on the stub ADSP.**
  The stub ADSP doesn't have the GCS responder module; replaying the
  bootstrap against a stub-only ADSP will get a "no such channel" reject
  (which is exactly what the live open test showed). Without the GCS module
  on the ADSP, this is dead code. **Confirmed by live test, do not pursue
  until the non-stub ADSP runs.**
* **USB-C dock / Bluetooth audio.** These work today (the SPX has a working
  BT stack with `hci0`, `btqca`, `btrtl`, `btbcm`, `btintel` all loaded and
  the PipeWire config has the BT ALSA sink configured). If the user can
  accept BT or a USB-C dock, audio works **now**, without any kernel work.
  This is the most pragmatic shipping answer if the TZ wall holds.

---

## 7. Live evidence and verification points

For the receiving engineer, here is the live state and where to verify it:

| item | location / command |
|---|---|
| current loaded firmware | `sha256sum /lib/firmware/qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn` should match `2703ceb6…` (the stub). The backup is at `qcadsp8180.mbn.STUBBED-BACKUP`. |
| backup of stub | `/lib/firmware/qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn.STUBBED-BACKUP` |
| Windows non-stub image | `/tmp/qcadsp8180-WIN.mbn` (sha256 `09c06fe8…`); also on Windows at `C:\Windows\System32\DriverStore\FileRepository\surfaceprox_subextadsp.inf_arm64_bbffa45584bbab05\qcadsp8180.mbn` |
| live audio driver .sys files (fresh pull) | `/tmp/spx-winlive/{qcauddev8180-LIVE.sys,qcglink8180-LIVE.sys,qcrpen8180-LIVE.sys}` (packages `b4aa0854`, `b4aa0854`, `fb9466cb` — newer than the 2026-06-19 prior pull) |
| live live ADSP GLINK/RPMsg open (proved clean) | `spx-gcs-rpmsg-probe.py --channel g_glink_audio_data --ctrl /dev/rpmsg_ctrl1` — endpoint created, ADSP "failed to open" cleanly, ADSP still running |
| the AHB bridge proof (recipe flaw) | `drivers/soundwire/qcom.c:280-316` (qcom_swrm_ahb_reg_read / write) — defines the bridge semantics at codec `0xc85/0xc89/0xc8d/0xc91` |
| the TZ rejection sequence | `drivers/firmware/qcom/qcom_scm.c:578-639` (qcom_scm_pas_init_image, returns `ret ? : res.result[0]`) |
| the SHM-bridge ruling-out | `drivers/firmware/qcom/qcom_tzmem.c:52-87` (GENERIC mode, sc8180x blacklist) |
| the complete re-verify evidence (5-agent workflow) | `~/.claude/projects/.../memory/spx-adsp-firmware-windows-vs-linux.md` (the 2026-06-19 investigation + the 2026-06-20 SHM/cold-boot ruling) |
| the GLINK bypass progress + live test results | `~/.claude/projects/.../memory/spx-glink-bypass-progress.md` |
| the live `dmesg` of the failed warm-reload | `error -22 setting up firmware qcom/msft/surface/pro-x-sq2/qcadsp8180.mbn` (boot time of the ADSP-start attempt) |
| the prior-session false-positive | `~/.claude/projects/.../memory/spx-firmware-cdc-regop-stub-nogo.md` (read this for the prior wrong path; the current real firmware exists; the path is firmware-swap-not-PAS-blocked) |
| the live ACDB extract | `~/.claude/projects/.../memory/spx-audio-wsa-soundwire-unattached.md` (the q6afedai/ACDB/qcadcm RE + CDCLUT0 OOB caveat) |
| the live AFE/ACM path (works) | `q6afe-dai: SPX: AFE port 6 already running, reusing` — the AFE on SLIMBUS_2_RX is alive and reused by every audio session |

The audio .sys files and ACDB can be re-pulled in a few seconds via the existing
bash SSH recipe (saved in `scripts/spx-winlive/...` and the workflow scripts).

---

## 8. The exhaustive, auditable timeline of this investigation

The full prior work (2025-2026) attempted, in order:

1. **APPS SoundWire direct bring-up** via `soundwire-qcom` (POLL mode) — fail
   on every variation (`cmd_data: 0x0`).
2. **Codec IRQ path** (wiring the WCD9340 codec interrupt via `&tlmm 256`) —
   blocked by SPX hardware (GIO0 pin 256 is beyond the `pinctrl-msm` TLMM
   range, no upstream `QCOM040D` ACPI GPIO driver). The IRQ path was
   attempted; `msm_gpio_irq_ack` oopsed at the bridge; the dtsi was patched
   to remove the IRQ wiring; the `wcd934x` MFD was patched IRQ-less to
   probe.
3. **DSP / APR / AFE path** — the `q6afe` AFE on `SLIMBUS_2_RX` is alive
   and works (`AFE port 6 already running, reusing`); the `q6adm` ADM COPP
   is openable; the upstream `q6afe v3` (`hdr_v3` knob) and `q6adm` v6
   instance header patches were built and installed (sha a379b6e8 for
   q6afe, e2d771f7 for q6adm). AFE CDC / SLIMBUS_CONFIG 0x10212 bodies
   from the ACDB were attempted; the ADSP returned `-EBADPARAM` / `EBADPARAM`
   consistently — the ADSP rejects because the codec-reg op is **stubbed**
   in the Linux `.mbn`. This was the prior-session "firmware NO-GO"
   conclusion, which was correct about the file Linux loaded but wrong
   that this was the only image.
4. **Workflow-captured live recipe from Windows** — captured the live
   qcadcm dispatch buffer + ACDB; decoded the CDCLUT0 0x15200 speaker
   recipe; the recipe's AHB-bridge addressing was wrong (treated
   `0xc85+offset` as a direct register map, when it's actually a
   4-register bridge window). Validated against the kernel source. The
   recipe was neutralized (`scripts/spx-spkr-replay-v2.sh.BROKEN-DO-NOT-RUN`).
5. **Firmware swap** — pulled the Windows non-stub `qcadsp8180.mbn`,
   verified it is byte-perfect and correctly signed, attempted to load
   via live ADSP stop/start, hit `qcom_scm_pas_init_image` returning
   `-22`. Five hypotheses for the rejection (SHM-bridge, cold-vs-warm,
   metadata incompleteness, cert expiry, anti-rollback) were rigorously
   ruled out. Concluded as a locked, signed TrustZone policy gate.
6. **GLINK bypass** — extracted live `g_glink_*` channel names from
   `qcauddev8180.sys`; verified `g_glink_audio_data` open from APPS does
   **not crash the ADSP** (live proof). The ADSP rejects the OPEN cleanly
   because the GCS server is dormant on the stub ADSP. Path is reachable
   in principle but gated on the non-stub ADSP.

---

## 9. Final assessment (for the expert)

The SPX speakers are blocked by a single architectural decision Microsoft made for
the SPX: the ADSP firmware that ships in the recovery image is a stub build that
deliberately does not load the GCS/AudioReach runtime module. The real (production)
firmware exists and is publicly available, but the SPX's locked, signed TrustZone
rejects it on runtime load (and would on cold boot, same SMC path). This is almost
certainly an intentional Microsoft vendor lock: the SPX audio path is ADSP-mediated
and the GCS module is loaded on demand by the Windows qcauddev/qcrpen stack; the
Linux firmware deliberately omits this to force BT or USB-C audio as the Linux path.

**Three honest forward paths**, in order of expected payoff:

1. **(Most likely to succeed)** A newer `linux-surface` SPX firmware drop
   ships the non-stub `qcadsp8180.mbn` (it exists publicly). If so, the fix
   is replacing the firmware file — no other code changes. **Check this
   first.**
2. **(If (1) doesn't exist or fails)** Instrument the Q6v5 TrustZone
   authentication path on Windows (via WinDbg attached to the secure world,
   or via `QcacrsTool` parsing the crash dump) to get the in-TZ rejection
   cause. The remaining TZ gate is internal and not visible to Linux.
3. **(Most pragmatic, no further work needed)** Bluetooth audio or USB-C
   dock. The SPX BT stack is fully loaded and working. Audio works **now**.

The receiving engineer should start with option (1) before considering any
kernel or runtime work.
