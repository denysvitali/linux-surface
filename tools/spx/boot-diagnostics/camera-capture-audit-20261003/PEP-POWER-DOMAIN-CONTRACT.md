# SQ2 PEP camera power domains and rail-client ownership boundary

C01 follow-up on actual known-good boot
`b6b4f20b-376f-4577-b282-677ad4ae0ec8`, release `6.18.3-1-surface+`.
The [clock review](PEP-CLOCK-CONTRACT.md) left footswitch execution and default
ownership unresolved. Selected PEP bytes now connect the camera footswitch
parser, action conversion, resource templates, callback and GDSC control table.
They also identify the rail-client availability path and retained default lists.
No live Windows resource ownership or dedicated PHY/PLL analog provider follows.

The `FootswitchData` name leaf0x136f0 is paired with parser0x1ee870 in the
static vtable. At0x1ee914 the parser calls converter0x206f18; its four-entry
table converts raw actions1–4 to internal1–4. The selected action builder passes
the operation through to0x1f2d80 and registration0x8a518. Templates name
`/fs/*/enable` and `/fs/*/hwctrlenable`; node template0x1c07b0 publishes
callback0x89d20. Its four targets distinguish software enable/disable from
hardware-control enable/disable. All64 camera domain actions retained across
CPXC/CPC1/CPC2 use raw1/2, corresponding to software control. Complete NPA
callback wiring and actual invocation/success are not asserted.

Power-domain lookup0xf2db0 scans39 BSP records with a72-byte stride and returns
an index tagged0x20000. Eight camera records agree with the current Linux CAMCC
addresses:

| Domain | Physical GDSCR |
| --- | --- |
| BPS |0x0ad07004 |
| IFE0 /1 /2 /3 |0x0ad0a004 /0x0ad0b004 /0x0ad0f004 /0x0ad0f070 |
| IPE0 /1 |0x0ad08004 /0x0ad09004 |
| Titan top |0x0ad0c1bc |

All eight retained descriptors use control table0x19f928 and rail descriptor
0x196230, named `/arc/client/rail_mmcx`. Software enable0xf8358, reached through
wrapper0xf2e60, has a selected first-use path that records a0x30 rail request
and calls rail aggregation0xfc5b0 before its HAL enable call. Its domain count
then increments. Software disable0xf8578 has the selected HAL collapse call
before rail request recomputation0xfc7b0. Shared counts, flags, provider state
and indirect operations remain prerequisites; a complete transition graph is
not established by these call sites.

The control table resolves to these original helpers:

| Operation | PEP bytes | Linux control contract |
| --- | --- | --- |
| Software collapse |0xff420 clears bit0;0xff460 sets bit0 | `SW_COLLAPSE_MASK = BIT(0)` |
| Hardware control |0xff4f0 sets bit1;0xff520 clears bit1 | `HW_CONTROL_MASK = BIT(1)` |
| Enable completion |0xff420 loops on GDSCR bit31 | These eight Linux domains use CFG_GDSCR at GDSCR+4, bit16 |

PEP's MMIO read helper loads a32-bit word; the unrecorded write leaf at0xfe1e8
is checked as exactly `STR w1; RET`. Its two-instruction selection has no PE
exception record and is not presented as an inferred pdata boundary. Matching
control masks do not establish equivalent polling, timeout or shutdown behavior.
The selected PEP enable loop has no timeout. Linux's CFG polling difference is
retained explicitly, not changed based solely on this comparison. Its seven
non-Titan camera domains have Titan as parent; all eight lack an always-on flag.

BSP initialization reaches0xfcae8, which reads the three rail descriptors and
the `ClockRailConfig` table. It stores MMCX's value16 at descriptor+0xdc. In
the checked aggregation path, that field limits requests while a client handle
is absent; it is not an observed default voltage or evidence that analog rails
are powered. Availability callback0xfc8c0 creates client types0x40/0x800,
labelled required/suppressible by the retained scalar-request diagnostics, and
conditionally replays cached requests. Aggregation's selected scalar call is
0x102cc8. The live ARC provider, full callback graph and actual request outcomes
remain unobserved.

Five complete, null-terminated retained startup lists are decoded:

| List | Entries | Bounded camera finding |
| --- | --- | --- |
| ClockAlwaysOnList |33 | No `cam_cc_` entry |
| RefCountSuspendedList |2 | No `cam_cc_` entry |
| SuppressibleList |38 | No `cam_cc_` entry |
| ExcludedPowerDomains |9 | None of the eight camera domains |
| ForceMemCoreAndPeriphList |91 |20 camera clock entries |

The last list is a distinct memory/core/peripheral policy. It must not be
treated as an always-on analog supplier list. These absences cover only the
retained tables; they do not rule out boot firmware, another driver, dynamic
configuration or physical supply sharing. Public-source searches did not
retrieve direct SQ2 camera analog wiring, and no cross-SoC rail alias is used.

`audit_pep_power_domain.py` verifies105 selected instruction contracts in24
ranges:23 exception-bounded ranges plus the selected unrecorded two-instruction
writer. It checks conversion/dispatch tables, all39 unique power-domain names,
eight camera records,64 firmware actions, three rail descriptors, the five
startup lists and Linux address/parent/mask contracts. It records selected
contracts rather than full vendor control-flow closure. Final14-file manifest:
`6aee09fb958ecaf151ba4ec2e7cc419d73cc2a25233ad431c2f135e20965e5af`.
The earlier102-instruction/23-range inventory remains preserved; the final
version adds the name-leaf checks and Linux parent validation.

`verify_pep_power_domain.py` rehashes the inputs/ranges, replays64 raw actions
and compiles the actual Linux `gdsc_check_status`, `gdsc_hwctrl` and
`gdsc_update_collapse_bit` bodies against fake register access. Strict
`-Wall -Wextra -Werror` with ASan/UBSan passes183 cases covering status-source
selection, preserved bits, alternate collapse registers and I/O error return.
Ten altered fixtures reject: wrong Titan address, HAL, rail alias, raw action
conversion, camera always-on membership, collapse mask, power polling, missing
client limit, Linux domain polling and Linux collapse bit. No native vendor
code is executed. Review manifest:
`ffd1c987c9230639b262cda303c560daa6946fa61cfee3b18dfb0e86ce8df2ac`.

Reproduce with installed system Python/Capstone/gcc and retained pinned clock
and receiver inventories, using fresh directories:

```sh
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_pep_power_domain.py /var/tmp/spx-pep-power-domain-new
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/verify_pep_power_domain.py /var/tmp/spx-pep-power-domain-new /var/tmp/spx-pep-power-domain-review-new
```

The80-file AX `offline-pep-power-domain-20261003` archive retains both
inventories, original PEP/DSDT bytes, Linux sources, native helper executable,
ten altered fixtures, exploratory mistakes/limits, prior clock seal and
recovery/source state. Every file is rehashed; manifest:
`6177bf651d885775014f73c203c9a68b7e0abeac8d2f3cca79c0dea5943f0a12`.
Nine relevant kernel sources remain exact to the final clock review, including
unchanged GDSC helpers. AX's518 preparation/499 build/208 installed files,
34 runtime helpers and three payloads remain frozen. All5,183 known-good
module files/links plus recovery payloads, EFI and default verify. Pending boot
selection is empty and no BootNext exists; the actual known-good UUID is unchanged.
Receiver supply requirements and disabled DT status remain unchanged. Complete
ARC/default ownership, actual analog wiring, enabled bindings, capture and
idle/fault regression remain C01 work. All47 hardware acceptance checks stay open.
