# Touch firmware timing after AQ

Target **I01**. AQ's initial-probe failure is preserved in
[the actual result](RESULT-20261003aq.md); its userspace fallback returned to
known-good. No live touch restart, reset or rebind was attempted.

Retained SQ2 DSDT SHA256
`e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8`
contains GTCH/MSHW0235/PNP0C51 with falling-edge GPIO122 and GPIO54 reset.
Its `_PS0`, under FLAG3, performs Sleep300, writes GPIO54 IO value2, then
Sleep150 (DSL lines101845/101853/101854). `_RST` writes zero, Sleep300,
then writes2 (101894–101896). The GPIO IO address0x03136004 matches the
TLMM GPIO54 layout; the Linux board uses output-low/assert and output-high/release.
ACPI [Sleep operands are milliseconds](https://uefi.org/specs/ACPI/6.5/19_ASL_Reference.html#sleep-milliseconds-sleep).

LPMX chooses LPXC or LPXX using SBFF bit0 from firmware NVS. LPXC D0 enables
the PMIC output without a table delay; LPXX D0 includes DELAY300 before releasing
GPIO54. Neither active SBFF nor custom PEP DELAY units was read or established.
The explicit `_PS0`/`_RST` Sleep300 evidence does not require assuming those units.
The alternate table's D3 output values also differ; do not infer a complete power
sequence from just one table or equate a firmware GPIO request with its measured voltage.

The audited driver powers its5V fixed supply, waits5–6ms and releases reset.
The fixed regulator has no startup-delay property. The new board candidate adds
`startup-delay-us = <300000>` so the regulator core waits before returning the
first enable, while the driver still holds reset. The source chain is
fixed.c startup_delay→desc.enable_time→core.c `_regulator_get_enable_time()` /
`_regulator_do_enable()`→fsleep. This is a firmware-backed candidate for powered
startup, not proof that settling time caused AQ's failure. Existing 150ms initial
post-release wait, IRQ/poll budgets, wire format and recovery behavior are retained.
An enable of a rail already held by another consumer may skip the hardware delay;
this property alone does not implement the firmware's independent `_RST` method.

Offline compilation with AQ's exact provider assembly yields DTB
`fc567fd1a7593d9b5b430dee4edb7086f3ef3f71179dd2c304801c6b5e49bd3e`.
Exact FDT comparison to AQ proves only `/ts-5p0-regulator/startup-delay-us`
was added; every other property/node and memory reservation matches. The focused
fixed-regulator schema emits no diagnostics, and the separate source patch passes
strict checkpatch with commit metadata checks omitted. An initial post-compile
Python import setup failure is retained, followed by the successful review.

`audit-touch-firmware.py` extracts all three methods and both literal tables,
checking16/20 package lengths and the unchanged camera parser's986-package
default result. It records line provenance and selection limits. No firmware AML,
NVS or GPIO/MMIO was executed/read by this audit. Durable87-file combined evidence is under AQ's
`offline-followup-candidates-20261003/`, manifest
`c05163c4bea62a2845eb90fd4400bb8d91e18d5668f43238a46ff3f37409abc9`.
Independent SHA-256 rehash passed; the touch files are in `touch-timing/`.

Next actual test needs a distinct complete attempt, preserved known-good recovery,
source/config/kernel/modules/DTB/initramfs provenance and the unchanged strict
baseline. Verify real assert→enable→release chronology and both initial probe and
later opens. A successful single boot would remain insufficient for I01/B01;
preserve any invalid response, missing IRQ or automatic retry. Never re-arm AQ.
