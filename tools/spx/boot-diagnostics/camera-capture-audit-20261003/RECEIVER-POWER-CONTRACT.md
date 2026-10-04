# SQ2 receiver firmware tables and PoFx callbacks

C01 offline follow-up after AX's verified return, on actual known-good boot
`b6b4f20b-376f-4577-b282-677ad4ae0ec8`, release `6.18.3-1-surface+`.
The subsequent [PEP loader review](PEP-LOADER-CONTRACT.md) establishes the static
STND path into these tables; actual Windows request success and resource/analog
ownership remain unobserved. The original table audit below is preserved.
The later [PEP clock review](PEP-CLOCK-CONTRACT.md) supersedes this audit's
raw-number comparison: mode3 converts to closest, so the retained CPHY plan
selects400 MHz for MPCS's300 MHz request. Local PHY requests/table are corrected;
timer requests stay300 MHz. These are static findings, not live readback.
The later [power-domain review](PEP-POWER-DOMAIN-CONTRACT.md) decodes selected
footswitch execution and retained startup lists; dedicated analog suppliers and
actual transitions remain unobserved.
The earlier [MIPI power inventory](MIPI-POWER-PATH.md) extracted only CPXC. That
correctly covered CAMP and sensor states, but omitted the separate receiver
tables. The retained parser already supports a package-name argument; its frozen
bytes and the earlier inventories are preserved.

The hash-pinned SQ2 DSDT contains these independently declared literal packages:

| Package / start line | Return method / line | Device | Components / Fx states | Literal packages verified |
| --- | --- | --- | --- | --- |
| CPXC /58526 | CPMX /58521 | CAMP plus CAMS/CAMF/CAMI | CAMP 3 /6; sensors have D states |986 |
| CPC0 /64271 | C0MD /64256 | JPGE |2 /4 |102 |
| CPC1 /64798 | C1MD /64261 | MPCS |4 /8 |158 |
| CPC2 /65609 | C2MD /64266 | VFE0 |13 /26 |1229 |

All 2,475 nested literal package sizes are checked. Full ordered actions, source
lines and return-method declarations are retained in `receiver-power.json`.
Declaring these methods alone does not establish that the retained Windows PEP
actually evaluates them. The subsequent loader review traces the static request
path; actual consumption remains unobserved.

For each MPCS component 0–3, F0 has nine ordered actions: MMCX resource value 48;
camera XO; camera AHB; camera GDSC clock; titan-top footswitch; CAMNOC AXI;
CPAS AHB; the component's PHY timer; and its PHY clock. The final two actions
have numeric fields `[8, 300000000, 3]`. F1 lists the eight clock/footswitch
resources in reverse order with action code 2, then MMCX value 0. All 72 actions
are compared with the expected order and fields. The CPC1 actions contain no
PMICVREGVOTE. That bounded absence does not identify a dedicated analog provider
or cover the entire PEP resource graph.

CPC2's four full IFE and four IFE-lite F0 recipes have receiver clock fields
`[8, 400000000, 3]`; all26 states and their complete actions are preserved.
CPC0/CPC2 also contain no PMICVREGVOTE actions. The Linux CAMCC timer table
already contains 300 MHz and its shared CPHY receiver table contains 400 MHz.
The existing `camcc@ad00000` node attaches to SC8180X_MMCX. These are static
correspondences, with PEP action-code/rate semantics and runtime transitions
untraced. No clock, regulator, DT or kernel implementation is changed.

The retained MIPI binary is pinned to
`39e299af8ada6d80778f510c363085f49c5a06d94d418ce98ea87065c806a306`.
Registration at RVA 0x2620 builds version 1 metadata with 64 header bytes and 32
bytes per component, a null callback context, two idle states per component,
and deepest wakeable state 1. Component count comes from the device context;
the four GUID entries do not prove a hardcoded count. Callback slot meanings
follow Microsoft's [device layout](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/ns-wdm-_po_fx_device_v1)
and [component layout](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/ns-wdm-_po_fx_component_v1).

| Callback | RVA | Local body observation |
| --- | --- | --- |
| Active condition |0x2b50 | Logging tail branch to0x2170 |
| Idle condition |0x2b00 | PoFxCompleteIdleCondition and logging |
| Idle state |0x2aa0 | Logging and PoFxCompleteIdleState |
| Power required |0x2b70 | PoFxReportDevicePoweredOn and logging |
| Power not required |0x2bb0 | Logging and PoFxCompleteDevicePowerNotRequired |
| Power control |0x2bf0 | Handles a selected 24-byte completion payload, frees optional user data and stores a completion marker |

The active-condition leaf has no PE exception record. Its eight instructions
are decoded directly from the published pointer to the adjacent exception
start at 0x2b70; this boundary inference is explicit. The other seven selected
ranges have verified exception boundaries. Logging and OS bodies remain
external, so these local bodies do not prove a complete power call graph.
The four component GUID byte sequences do not occur literally in the pinned
PEP binary; generated identifiers and dynamic matching remain possible.

PrepareHardware supplies F0 metadata `(latency 0, residency 0, nominal power 500)`
and F1 `(2,5,50)`. The documented units are 100 ns for the first two fields and
microwatts for nominal power. These are driver-supplied attributes, not measured
hardware timing or consumption. [Idle-state layout and units](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/ns-wdm-_po_fx_component_idle_state).
Preparation maps resources before registering PoFx; its later PERF parser call
does not prove that MPCS has a PERF method or that performance registration
succeeds. Actual Windows execution is not observed.

Reproduce from this repository with installed system Python/Capstone/rabin2 and
fresh output directories:

```sh
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_receiver_power.py /var/tmp/spx-receiver-power-new
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/verify_receiver_power.py /var/tmp/spx-receiver-power-new /var/tmp/spx-receiver-power-review-new
```

The 12-file inventory manifest is
`7ca2b4bc51b8f01b2715a0732c139e109b5999a81cc5eff735a56e4b36518943`.
It verifies 81 selected instruction contracts and eight imports. Positive raw
package replay, independent byte-range rehash and four rejected firmware
fixtures pass: missing CPC1, wrong MPCS rate, wrong MPCS clock action and missing
C1MD. The clock-action fixture replaces the first PHY timer name with the PHY
clock name; its retained filename is `wrong-mpcs-clock-order.dsl`.
The 6-file review manifest is
`0605e683d1c205c32b412122b5391fe4481e27e572ca7d31fc066b3fa38e87e7`.
The initial reviewer stopped on the frozen helper's repository-depth assumption
when importing its shallow `/var/tmp` copy. Its original source and complete
stderr are retained; corrected replay verifies live/frozen source equality
before importing from the original repository location.

The 33-file durable AX `offline-receiver-power-20261003` archive, including pinned
DSDT/MIPI/PEP/INF inputs, original and corrected review, negative fixtures, prior
CPXC-only scope and state evidence, is independently rehashed. Manifest:
`7ee9d6e72018de2fc9b8c0477c58de65455dd15b7eed6ca78751255e8116f97f`.
Seven relevant kernel sources, AX's 34 runtime helpers and three payloads remain
byte exact to frozen AX. All 5,183 recovery module files/links and recovery
payloads/EFI/default verify; next selection is empty and no BootNext exists.

No vendor code or ACPI method is executed, no camera hardware operation occurs,
and no reboot is requested. Dedicated PHY analog ownership and justified
enabled receiver integration remain C01 prerequisites. No new capture or
physical feature acceptance follows; all 47 hardware acceptance boxes stay open.
