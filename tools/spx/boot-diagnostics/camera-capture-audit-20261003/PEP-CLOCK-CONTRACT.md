# SQ2 PEP receiver clock conversion and frequency selection

C01 follow-up on actual known-good boot
`b6b4f20b-376f-4577-b282-677ad4ae0ec8`, release `6.18.3-1-surface+`.
The [receiver table audit](RECEIVER-POWER-CONTRACT.md) recorded raw firmware
fields; its conclusion that existing Linux rates needed no change was premature.
The [loader audit](PEP-LOADER-CONTRACT.md) then located PEP table parsing. Selected
clock parser, conversion and frequency-selector bytes now explain the raw
300 MHz request. This is static evidence; no Windows execution or live clock
readback was observed.
The later [power-domain review](PEP-POWER-DOMAIN-CONTRACT.md) connects selected
footswitch, rail-client and default-list contracts. It preserves the analog
ownership and actual execution limits below; no further kernel change follows.

The raw `ClockData` parser at RVA0x1ec890 resolves the clock name, calls action
conversion0x207100 at0x1ec9c0 and mode conversion0x207388 at0x1eca5c, then
normalizes frequency units at0x1eca88. The action table at0x207370 converts
firmware codes1–15 into internal powers of two. Firmware action8 becomes0x80,
whose diagnostic label is `EN_SETFREQ`. It must not be interpreted as internal
bitmask8. The twelve-entry mode table at0x207720 converts raw mode3 into
internal mode2, the closest-rate selector; its units remain Hz.

The selected action conversion passes operation/rate/mode through0x1ead90 to
the clock builder0x1f4358. Clock aggregation0x84b50 contains the frequency call
at0x854f8, through wrapper0xf2200 to setter0xf78b8 and selector0xf72f8. The
selector scans 0x38-byte frequency records, checks availability0xf8fb0 and
returns exact matches first. Internal mode0 chooses the ceiling, mode1 the
floor and mode2 the closest rate, with ties choosing the lower rate. The setter
has a selected call to hardware programming0xf74b0. These call sites do not
establish complete NPA callback wiring, successful programming or every path.

Initialization0xf1de0 retains BSP0x189850 in global0x1cd280. Name lookup0xf1fc0
scans427 nodes with a0x60-byte stride. The sixteen relevant nodes have these
retained plans:

| Clocks | Frequency plan | Raw firmware request | Static selection |
| --- | --- | --- | --- |
| CSIPHY0–3, full IFE0–3 and Lite0–3 CPHY receiver |19.2 /400 MHz | MPCS300 MHz; IFE/Lite400 MHz, closest |400 MHz |
| CSI0–3 PHY timers |19.2 /300 MHz | MPCS300 MHz, closest |300 MHz |

The twelve CPHY nodes share domain0x19e050 and table0x1988d0. There is no300 MHz
entry in this retained plan. Timer nodes use separate domains and table0x198a40.
All selected availability tuples are zero; the checked availability function
accepts that tuple unconditionally. No live BSP mutation is observed or excluded.
The shared CPHY RCGR is0x0ad0a064; timer RCGRs are0x0ad06004/28/4c/70.

All sixteen domain descriptors point to rail0x196230, whose name is
`/arc/client/rail_mmcx`. The static titan-top power-domain descriptor shares
that pointer and names GDSC0x0ad0c1bc. This correspondence does not map MMCX to
the dedicated `vdda-phy` or `vdda-pll` suppliers. Default resource ownership,
analog supply wiring and the full power sequence remain unresolved.

The local Linux changes remove the extra300 MHz CPHY table entry and request
400 MHz PHY /300 MHz timer for all four SC8180X CSIPHY resources. The previous
comment incorrectly treated MPCS's raw300 MHz field as the programmed rate.
Other clock tables, receiver DT status and supply requirements remain as before.
The real Linux `qcom_find_freq()` body selects the ceiling, with a fastest-rate
fallback; on the corrected CPHY table a300 MHz request also selects400 MHz.
Actual clock-framework transitions and capture still require hardware validation.

`audit_pep_clock.py` checks85 selected instruction contracts in13
exception-bounded ranges from the original2,442 records, both conversion tables,
427 unique clock names, sixteen selected BSP nodes and sixteen firmware requests.
The fourteen-file inventory manifest is
`b850c47fb7fd5466f80ab5e9b10c8546f347ba9e56b39f7919fd26af39fdfe20`.
This audit records selected instruction/range contracts, not full control-flow
closure of the vendor driver.

`verify_pep_clock.py` rehashes the inventory and ranges, replays conversions and
compiles an independent native C selector alongside the actual Linux lookup
body with `-Wall -Wextra -Werror` and UBSan. All96 cases pass:80 boundary/mode
cases plus16 firmware requests. Seven altered fixtures reject: old CPHY table,
old PHY requests, wrong CPHY/timer plan rates, conditional availability, wrong
closest mode and wrong action8 conversion. Native model execution is not
execution or emulation of Windows vendor code. Review manifest:
`53f66cd72e15dcfc1f55fe9df7bc47f027c85bd44b1a06a09b75a910eef219ae`.
The first reviewer failed before compiling because its C extraction pattern
stopped at a semicolon. Its source/stderr remain preserved; the corrected
reviewer extracts the complete const-return function and passes. Final source
review also caught the earlier header comment repeating the300 MHz core claim.
Inventory-v2/review-v3 incorporate its correction; their static contracts and
native results are identical to inventory-v1/review-v2 apart from the source
input hash. Both evidence sets are retained.

Reproduce with installed system Python/Capstone/gcc, retained pinned loader and
receiver inventories, and the preserved two-source preimages:

```sh
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_pep_clock.py /var/tmp/spx-pep-clock-new
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/verify_pep_clock.py /var/tmp/spx-pep-clock-new /var/tmp/spx-pep-clock-review-new --preimage /var/tmp/spx-pep-clock-preimage-20261003
```

Both affected kernel objects compile with GCC16.1.1 in a private copy of all
96,937 frozen AU/AX source records. The effective AX configuration is byte exact
before/after `olddefconfig` and preparation. A separate review verifies the full
private source mapping has exactly the two constrained changes, both output
objects are AArch64 relocatables, and configuration/preparation/object compiler
stderr is empty. The27-file build manifest is
`248b350ac4f9940d19dc2c00037cc6319cac3adcc2b8ae093f6d4fbc016bf639`.
This scoped check does not link a full kernel or modules. It inherits AX's
release string for compilation only; the two revised objects are not deployed
into AX, whose original artifacts remain frozen.
Both final objects are byte identical to the first clock build, confirming that
the later header correction changes source documentation only.

The100-file final AX `offline-pep-clock-20261003-v2` archive retains pinned
originals, inventory-v2/review-v3, seven altered fixtures, build-v2/config/source
mapping/patch/objects/logs, failed reviewer-v1, exploratory limitations and
prior manifests. Every copied file is rehashed; manifest:
`766622e843724c5d3addbe0b5e1edefb3514be211d2a351aff214a676100da79`.
The earlier99-file `offline-pep-clock-20261003` archive remains sealed at
`4a2568bb0258bd8618f3a7ad86828902e6177b94e78956d240049574012cbdd0`;
its obsolete header comment is explicitly superseded by the final version.

Frozen AX's518 preparation/499 build/208 installed files,34 runtime helpers
and three payloads verify unchanged. Five other receiver/SoC sources remain
exact to AX; only the two independently constrained source changes above differ.
All5,183 known-good module files/links plus recovery payloads, EFI and default
verify. The actual boot remains the known-good UUID above, pending selection is
empty and no BootNext exists. No vendor code or ACPI method was executed and
no camera hardware operation or reboot occurred.
No new trial has been selected. Analog ownership, enabled receiver integration,
capture/idle/fault regression and all47 hardware acceptance checks remain open.
