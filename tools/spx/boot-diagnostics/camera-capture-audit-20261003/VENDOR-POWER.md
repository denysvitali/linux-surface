# Vendor camera power and privacy-indicator evidence

Static C01/C05 inspection, 2026-10-03, after AS's combined baseline and rear control
pass. No vendor binary was loaded/executed and no hardware operation occurred.
The retained platform/MIPI-CSI driver pair is ARM64 PE, version1.0.1660.0000
from2021-10-29 according to their installation files.

The four originals are hash-pinned by `audit_vendor.py`. PE section parsing maps
file offsets to original image addresses; Capstone disassembles the bounded
platform privacy-indicator function0x140001df0..0x140002118. References at
0x140002084/0x1400020a4 target the PMIC/PState privacy messages at
0x140010988/0x1400109a8. These are indicator dispatch messages, not identifiers
for receiver analog supplies. The PMIC-message branch itself only logs before
return; that observation does not prove the entire vendor stack lacks PMIC work.
The separate GPIO and PState branches have calls; selection/wiring is not yet
validated. Do not execute or transplant a Windows request into Linux.

The hash-pinned SQ2 DSDT's CAMP.PERF containsPSTATE_SET11/type2 namedCAM_PRLD,
with states0/1 (DSL100511–100523). CAMP.PRLD exposes six encoded entries beginning
0x0101/0x0502. CAMP resources include GPIO11/25. This bounded inventory does not
decode those tuple fields, associate an entry with a physical camera/LED, or
establish GPIO polarity/sharing. The earlier CAMP CPXC audit's absence of
PMICVREGVOTE and presence of MMCX votes remain separate evidence, not analog
PHY/PLL supply mapping.

C01 receiver analog supplies remain unresolved. C05's fitted privacy/activity
indicator needs the PRLD parser/action selector and resource correspondence
reviewed, then a normal Linux control path and physical stream/idle/privacy
checks on the final candidate. All47 acceptance checks remain open. No new
kernel/config/DTB or trial selection was made by this static inspection.

The first string-count assertion also matched an Unsupported privacy message.
Its partial output/source/failure manifest are preserved separately. The corrected
selector matches the two explicit PMIC/PState messages; all input/address and
complete disassembly checks then pass. The13-file final output manifest is
`8e10e19c674a5fa12f87ba4668e0d7dcdbc1b859b8ef4015248f5753a4636299`.
The output includes full original drivers/installation files, imports, filtered
ASCII strings with offsets/addresses, function disassembly, retained CAMP methods,
source, result/limits and hashes. ASCII strings/imports are not a complete
call-graph or an absence proof; no actual supply/indicator mapping is claimed.

Reproduce with installed system Python/Capstone/rabin2 and a fresh directory:

```sh
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_vendor.py /var/tmp/spx-camera-vendor-power-new
```
