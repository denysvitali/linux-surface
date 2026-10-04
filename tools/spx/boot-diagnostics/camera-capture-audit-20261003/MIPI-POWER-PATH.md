# Retained MIPI-CSI power call path

Follow-up after AX return: the [receiver power contract](RECEIVER-POWER-CONTRACT.md)
adds the independent CPC0/CPC1/CPC2 firmware tables, which the CPXC-only inventory
below did not cover, and directly decodes all six callback bodies including the
unrecorded active-condition leaf. The original inventory and archive remain
unchanged. The later [PEP loader review](PEP-LOADER-CONTRACT.md) traces its static
STND/table parsing path; actual Windows consumption and dedicated analog
ownership remain unresolved.
The subsequent [PEP clock review](PEP-CLOCK-CONTRACT.md) decodes selected clock
conversion/execution call sites and retained plans; it corrects the local PHY
rate to400 MHz. Analog providers and complete default ownership remain open.
The later [power-domain review](PEP-POWER-DOMAIN-CONTRACT.md) adds selected
footswitch, GDSC, rail-client and startup-list evidence; its bounds still leave
dedicated analog wiring and actual receiver transitions unresolved.

C01 offline investigation after AT's automatic known-good return. The retained
68,208-byte ARM64 `qccammipicsi8180.sys` uses PoFx component activation and idle
accounting. This establishes a software path, not the analog provider mapping.

Ten selected call sites are verified from the original bytes and import table:

| Function/call site | Observed operation |
| --- | --- |
| PrepareHardware0x140029780 /0x14002995c | Calls power registration0x140002620 |
| Registration /0x140002820 | PoFxRegisterDevice |
| Registration /0x140002838 | PoFxStartDevicePowerManagement |
| Private control0x140001850 /0x140001984 | Calls component activation0x1400023f8 |
| Private control /0x140001968 | Calls component deactivation0x1400024f8 |
| Activation /0x1400024b0 | PoFxActivateComponent after reference count becomes1 |
| Deactivation /0x1400025b0 | PoFxIdleComponent after reference count becomes0 |
| PrepareHardware /0x1400299c8 | Calls ACPI PERF parser0x1400038d8 |
| PrepareHardware /0x1400299cc | Calls performance-state registration0x14002a278 |
| Performance registration /0x14002a4e0 | PoFxRegisterComponentPerfStates |

Registration publishes callbacks at0x140002aa0/2b00/2b50/2b70/2bb0/2bf0.
The decoded idle-state and idle-condition callbacks acknowledge completion
through PoFx. The power-control callback references
`PEP_STATE_ASYNC_PATH_COMPLETE`; it is not a PMIC rail name.
The ACPI parser's literal method name is `PERF` at RVA0x3cf0. Preparation
maps actual resources through MmMapIoSpaceEx before power registration.
Component count is read from the device context, not inferred from strings.

`audit_mipi_power.py` parses97 PE exception records and retains the complete
bounded listing, original drivers/INF/DSDT, firmware parser, imports and JSON
call-site inventory. It excludes calls/references outside a bounded control-flow
walk; unknown indirect branches stop that path.35 opaque words occur outside
that walk, including PERF/data literals. There are124 resolved import calls and
87 unresolved indirect calls across these functions. Unrecorded leaf functions,
WDF dispatch, external interfaces and the PEP implementation prevent a complete
power call graph. These counts do not imply every entry is a power operation.

The986 literal firmware packages are verified again. CAMP's six retained CPXC
states remain the previously reviewed clock/MMCX contract. This investigation
does not establish that analog supplies are unnecessary, already powered or
owned by MMCX. No required supply is removed and no guessed provider is added.
The next camera candidate still needs justified SC8180X/SQ2 analog ownership.

Reproduce with installed system Python/Capstone/rabin2 and a fresh directory:

```sh
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_mipi_power.py /var/tmp/spx-mipi-power-new
```

The final eight-entry output manifest is
`f303cf18cd0f641d3a826fbfd48f34adde2e341f9016822c193f1011b503ab21`.
Original output/source from the initial manifest failure (importlib-created
bytecode directory) is preserved. Intermediate inventories are retained:
v2 stopped linear decoding at opaque words and omitted newline-containing
messages; v3 added bounded CFG/opaque handling; v4 restricted string references
to complete ADR/ADD addresses rather than coincidentally matching ADRP pages.
Final v5 handles shifted immediates and asserts the ten selected calls.
No vendor code was loaded/executed; there was no device operation or reboot.
Receiver analog ownership and all47 hardware acceptance checks remain open.

The49-file durable AT `offline-mipi-power-20261003` archive preserves the original
failure and every intermediate/final inventory. Its manifest is
`9c1add75d5bfce4559cd10a049da2a0a25f8d7ba5895d15f9af62d18fe4a72e2`;
every archived file was rehashed after copying.
