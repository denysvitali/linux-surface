# SQ2 PEP camera table loader

C01 offline follow-up on actual known-good boot
`b6b4f20b-376f-4577-b282-677ad4ae0ec8`, release `6.18.3-1-surface+`.
The [receiver power audit](RECEIVER-POWER-CONTRACT.md) left the PEP loading path
untraced. The pinned PEP bytes now establish a static path from STND through
method-name conversion and table evaluation to device/action parsing. No actual
Windows execution, successful firmware request or analog provider is inferred.
The later [clock review](PEP-CLOCK-CONTRACT.md) traces selected clock-field
conversion and frequency execution call sites, correcting the local CPHY rate
interpretation. The loader findings below retain their original scope;
complete execution/default ownership and analog wiring remain unobserved.
The subsequent [power-domain review](PEP-POWER-DOMAIN-CONTRACT.md) adds selected
footswitch/GDSC/MMCX client and retained default-list contracts. These do not
establish complete ARC/default ownership or dedicated analog wiring.

The retained DSDT's STND method at line 1758 returns STNX, a literal list of 31
names at line 1763. The camera entries are reversed names:

| List index | STNX entry | Assembled word | Little-endian request bytes | Return package |
| --- | --- | --- | --- | --- |
|5 | DM0C |0x444d3043 | C0MD | CPC0 |
|6 | DM1C |0x444d3143 | C1MD | CPC1 |
|7 | DM2C |0x444d3243 | C2MD | CPC2 |
|27 | XMPC |0x584d5043 | CPMX | CPXC |

PEP's parser at RVA 0x1fa4d0 shifts the first string byte by 24 bits, the second
by 16 and the third by 8, ORs the fourth byte, then stores the 32-bit word. On
little-endian ARM64, `DM1C` therefore becomes the request name `C1MD`. The
camera method names need not occur as literals in the binary. This explains
the earlier literal-name search limitation. Some other STNX names have no simple
return declaration in this retained DSDT; no claim that all31 exports exist or
all requests succeed is made.

Selected original-byte call sites preserve the static route:

| RVA | Observed path |
| --- | --- |
|0x562bc | Calls loader0x20c2e0 |
|0x20c6b8 /0x20c6d4 | Loads the direct STND literal and calls evaluation wrapper0x209a90 |
|0x20c708 | Calls list parser0x1fa4d0 |
|0x20c864 /0x20c874 | Loads a converted list name and calls the same evaluation wrapper |
|0x20cb68 /0x20cbbc | Copies a returned table and calls table consumer0x3fa38 |
|0x3fbb8 /0x1eba94 | Calls generic device parser0x1eb8d0, then device-data conversion0x1e9250 |
|0x1ea344 | Selected state path calls action converter0x1ead90 |

The evaluation wrapper zeroes 260 bytes, stores the method word at offset 4 and
the original signature bytes `AeiA` at offset 0, then sends raw control code
`0x32c018`. Its shape matches the documented four-byte signature plus 256-byte
method path in [ACPI_EVAL_INPUT_BUFFER_EX](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/acpiioct/ns-acpiioct-_acpi_eval_input_buffer_v1_ex).
The [extended evaluation interface](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/acpiioct/ni-acpiioct-ioctl_acpi_eval_method_ex)
accepts such a path. This interface identification uses the documented shape;
the historical vendor acpiioct.h is unavailable, so its macro definitions are
not presented as independently verified source evidence.

Two WDF wrappers use pointer-table offsets 0x150 and 0x5d0. On this 64-bit layout
they correspond to indices 42 and 186, respectively DeviceGetIoTarget and
IoTargetSendIoctlSynchronously, in both pinned Microsoft
[KMDF1.15](https://github.com/microsoft/Windows-Driver-Frameworks/blob/b6191d9543441329154da32f7ab9bdd97228dd3c/src/publicinc/wdf/kmdf/1.15/wdffuncenum.h)
and [KMDF1.33](https://github.com/microsoft/Windows-Driver-Frameworks/blob/b6191d9543441329154da32f7ab9bdd97228dd3c/src/publicinc/wdf/kmdf/1.33/wdffuncenum.h)
headers. Both full headers, commit response and provenance metadata are retained.
The live Windows WDF binding and imported implementations remain unobserved.

Three matching 16-entry tag-table prefixes have CLOCK at index 2, PMICVREGVOTE
at 5, NPARESOURCE at 10 and FOOTSWITCH at 15. The selected action converter compares
those enum values and calls distinct builders 0x1f4358/0x1f59f0/0x1f2518/0x1f2d80.
This table/dispatch concordance is bounded evidence; builder internals,
resource execution, default-resource ownership and the full PEP graph remain
untraced. It does not turn the receiver recipes' absence of PMICVREGVOTE into
proof that a dedicated analog supply is unnecessary or already powered.

`audit_pep_loader.py` verifies 76 selected instruction contracts in 12 ranges,
with exception boundaries checked from the original 2,442 records. The two
opaque words are request literals outside the bounded control-flow walk.
The 12-file inventory manifest is
`f2f629de2f2c39edb85cfc01c4430ef695680da88b1db699f5f3447dbabadefa`.
`verify_pep_loader.py` rehashes the inputs/ranges and independently models the
byte assembly with strict native C/UBSan. All 31 converted names plus the direct
STND literal match. Four altered firmware fixtures reject: unreversed C1MD,
missing C1MD entry, missing STND return and wrong C1MD return package.
The 12-file review manifest is
`da7b01de9d5f0de5b9c8711940f620541bd9a3980aa12f8e5712779ac165542f`.

Reproduce with installed system Python/Capstone/gcc and the retained pinned
reference headers in a fresh output directory:

```sh
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_pep_loader.py /var/tmp/spx-pep-loader-new --references /var/tmp/spx-pep-primary-20261003
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/verify_pep_loader.py /var/tmp/spx-pep-loader-new /var/tmp/spx-pep-loader-review-new
```

The 44-file AX `offline-pep-loader-20261003` archive retains the pinned originals,
code, reference headers, native model and negative fixtures, exploratory
listings, prior receiver manifest and recovery/source state. Every copied file
is rehashed; manifest
`ab9ae87863078619398bed32d5ed5b9017e59a7e9c1164693feea3eb4b5b9c9d`.
Seven kernel sources, AX's 34 helpers and three payloads remain byte exact to
frozen AX. All 5,183 recovery files/links plus payloads/EFI/default verify; next
selection is empty and no BootNext exists. No hardware operation or reboot.

The next C01 work is the CLOCK/MMCX/footswitch execution and default ownership
path, or direct SC8180X/SQ2 board supply evidence, before enabling the receiver.
Analog ownership, capture and all 47 hardware acceptance checks stay open.
