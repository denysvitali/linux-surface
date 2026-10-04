# SQ2 CSID/VFE register contract

C01 offline review after AX's terminal return, 2026-10-03. Actual recovery boot
`b6b4f20b-376f-4577-b282-677ad4ae0ec8`, release `6.18.3-1-surface+`.
No new trial, vendor execution, camera register/bus access or capture occurred.

The retained ARM64 `qccamisp8180.sys` is SHA256
`39d8d130d03e703138be4f05dbd19d90a709eb961cc6c65cccdfac1dfd37471f`;
its INF is `5ba8efe39de8812c604298604e5f5fc5f1c8d6b781d187f95705742aa6c56449`.
The INF associates it with VFE0's `ACPI\QCOM0428` and labels the ISP Spectra390.
That label does not establish a register implementation or hardware revision.

`audit_isp_inventory.py` decodes382 PE exception-covered function ranges.
Its bounded CFG/address inventory preserves80 opaque words, none reached by
that CFG, and leaves unresolved indirect branches/calls explicit. Leaf functions
and unresolved paths make this incomplete; it is not an absence proof for power
votes or alternate register accesses.

`audit_isp_contract.py` independently decodes eight selected code spans and
checks47 exact instruction contracts. The VFE interrupt function's span excludes
its final padding/literal; the independent reviewer verifies the corresponding
exception record. Vendor initialization at RVA0x11648/11650/11654 stores CSID as
VFE base+0x4000 and the bus writer as VFE base+0x2000. This agrees with the
[firmware resource split](DMA-CONTRACT.md).

The CSID configuration dispatch reaches three RDI writers at RVA0x1ad48,
0x1aef8 and0x1b0a8. All66 stores across their full/Lite branches are verified.
The register subset compared with Linux is:

| Contract | Vendor offsets | Linux implementation |
| --- | --- | --- |
| CSID receiver configuration | 0x100/0x104 | Gen2 RX CFG0/CFG1 |
| Full CSID RDI configuration | 0x300+n×0x100 | Gen2 full RDI layout |
| Lite CSID RDI configuration | 0x200+n×0x100 | Gen2 Lite RDI layout |
| RDI drop/subsample registers | RDI base+0x0c/0x10/0x14/0x18/0x24/0x28/0x2c/0x30 | Same offsets in both layouts |
| VFE top IRQ status/clear/command | 0x6c/0x70,0x64/0x68,0x58 | 17x VFE |
| VFE bus IRQ status/clear/global clear | 0x205c/0x2060/0x2064,0x2050/0x2054/0x2058,0x2068 | 17x VFE |
| VFE writer configuration, first three clients | 0x2208/0x2308/0x2408 | 17x WM CFG |

The19-entry bus-client switch table is read as signed32-bit offsets. Its bounded
dispatch for ports0x3006/0x3007/0x3008 reaches the verified first three WM CFG
stores; merely finding unreachable instructions would not establish this path.
Actual Linux macro definitions compile under `-Wall -Wextra -Werror` and evaluate
to all69 selected vendor-derived values. The native program only computes/prints
integers. Four deliberately wrong full-CSID/Lite-CSID/bus-IRQ/VFE480 profiles are
rejected, with their fixtures and failures retained. GCC16.1.1, Python3.14.7 and
Capstone5.0.7 versions are recorded.

This supports keeping the present Gen2 CSID and17x VFE selection for further
integration. It does not establish full programming equivalence. Vendor RDI0
sets CGC bit8; Linux selects dynamic gating. Crop, decode/packing, calibration,
clock/power votes, interrupt timing, other clients and DMA frame behavior still
need review or functional verification. No runtime kernel/DT/config changes
follow from this audit, and all five reviewed camera kernel files match AX's
frozen source manifest.

Two retained historical stream logs report VFE0 `1.2.1` and CSID0 `1.0.0`.
The v23 front-camera log additionally reports PHY `0x10000000`; v22 has no PHY
revision line. Their full copies and present hashes are preserved. These are
historical observations: the standalone logs lack their original boot UUID and
complete source/config provenance, and no revision was measured on AX or on a
new candidate. The v23 log explicitly contains missing-supply dummy-regulator
warnings. Those warnings, and the rehashed nine old capture artifacts, do not
establish receiver analog ownership.

All47 hardware acceptance boxes remain open. The next camera dependency is
justified receiver analog power/ownership and the complete enabled binding,
followed by real frames and stream/idle/fault regression on one full candidate.
Keep the existing analog requirements; no placeholder provider or rail vote was
added. [Power path](MIPI-POWER-PATH.md), [analog review](ANALOG-INVENTORY.md).

Reproduce into fresh directories using system Python:

```sh
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_isp_inventory.py /var/tmp/spx-isp-inventory-new
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_isp_contract.py /var/tmp/spx-isp-contract-new
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/verify_isp_contract.py /var/tmp/spx-isp-inventory-new /var/tmp/spx-isp-contract-new /var/tmp/spx-isp-review-new
```

Final inventory manifest `96ef3fe3112424cf228ae6488457c4dd82f9856b123126290499958a4d7cfad8`;
contract-v3 `9af01fb51a1b6998bbebbfb212da49482af2142f41a475894d0b112a8ce9245c`;
review-v2 `aa5decc22d0640db548ae0012e6d05d11afd12210da7c950c0f57076cea8c02e`.
Earlier contract reports and the initial reviewer failure remain preserved:
v1's selected-range report accidentally reused a loop variable; v2 corrected it,
and v3 clarified the ISR code-span wording. The first reviewer correctly failed
when it demanded a PHY line absent from v22; v2 records that missing observation.

The145-file durable AX `offline-isp-contract-20261003` archive verifies with
manifest `1d0eb6ff10466179794a9b865dba60692c94a33a5e6ec7b86f1c00dd625fede8`.
It includes every iteration, original vendor/source bytes, selected listings,
native macro executable/results, rejected profiles, historical logs and recovery
state. Recovery payload/EFI/all5183 module entries and AX runtime/payload hashes
verify; persistent known-good default and empty pending selection are unchanged.
