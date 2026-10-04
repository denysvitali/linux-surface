# SC8180X PHY programming comparison

C01 offline investigation, 2026-10-03, actual known-good boot
`74f8ed0e-be29-43fc-b8c1-9c9fa4e25d9b` after AT's return. No new candidate,
module load, register/bus access, camera stream or vendor execution occurs here.
Analog ownership remains unresolved by the [power-path review](MIPI-POWER-PATH.md).

`audit_phy_program.py` independently maps PE sections in the pinned ARM64
`qccammipicsi8180.sys`, SHA256
`39e299af8ada6d80778f510c363085f49c5a06d94d418ce98ea87065c806a306`.
It decodes three selected complete function ranges, then verifies47 instruction
contracts for the register writer, table pointers/counts, hardware detection and
conditional table branch. Original bytes and listings remain preserved.

The writer at RVA0x4488 consumes12-byte tuples:32-bit register offset/value and
delay. Hardware detection at0x47e0 first writes2 to0x818, then reads offsets
0x8e0/8e4/8e8/8ec, combines shifts0/8/16/24 and compares against0x10000000.
This proves the vendor's expected revision, not a measured live hardware revision.
Linux's existing revision-read function uses those same offsets and shifts.

The vendor start function at0x4590 passes54 entries at RVA0x9720 to that writer.
Of those,47 fixed lane values match the current SDM845 GEN2 1.0 table, five
settle-count offsets are dynamically programmed and two are common controls.
The four data-lane CFG1 values are0x91; SC8280XP's table uses0x90 there. The
current compatible-based SC8180X selector chooses the matching GEN2 1.0 table.
This gives byte-based support for keeping that selection.

Full register programming is **not identical**. Linux additionally writes ten
lane calibration registers at offsets ending0x60/0x64. The vendor has two
conditional ten-entry tables that overwrite lane CFG2 and termination impedance:
one uses0x2a/0xca, the other0x08/0x0a. Its branch reads a64-bit context field at
offset0x18 and literals-1500000000,500000000,2000000000. The encoded unsigned
comparison selects the first table for input1500000000–2000000000 inclusive,
the second above2000000000, and neither below1500000000. This review does not
establish that field's physical units or complete caller path. Labels in the
inventory identify encoded thresholds; they do not prove a lane bitrate contract.
IRQ mask/clear ordering and calibration behavior also differ from Linux.

The extracted **actual Linux** `csiphy_gen2_config_lanes` and settle calculation
compile under strict warnings and ASAN/UBSAN against modeled MMIO. At the rear
driver's supported link frequencies270/540MHz with300MHz timer, the calculated
settle counts are22/21. Both traces preserve all47 matching fixed values and
produce62 writes each. Work is not a physical CSI receiver/capture test. Four
negative fixtures reject incorrect CFG1, missing dynamic settle, wrong settle
formula and swapped SoC profile. Their failures are retained.

The source comments previously claimed SC8180X and SC8280XP shared the same
Titan480 hardware and that the vendor's entire register program was identical
to SDM845. Those claims exceed the resource/byte evidence and are corrected.
Comment-stripped source is unchanged in both modified files; no runtime
programming, provider requirement or compatible dispatch changes. Scoped style
checks pass with no errors/warnings. No fresh native kernel build is inferred.

All47 hardware acceptance checks stay open. Next receiver work still needs
justified analog provider/ownership and CSID/VFE programming/revision evidence,
then one full current candidate and actual frame/idle/fault regression. The
observed power votes, expected PHY revision and raw historical captures do not
establish those requirements.

Reproduce with system Python/Capstone and a fresh directory:

```sh
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit_phy_program.py /var/tmp/spx-phy-program-new
```

Final-v3 output manifest:
`fa6adef6cbf67cf1d00d6fcc725bc796326610c3dcc67552b51b7747a81bfc87`.
Initial and intermediate outputs are retained. Version2 replaced a hard-coded
instruction count with the verified mapping's actual count and checked more
pointer/branch instructions. Version3 checks both selector arms and supports
separate negative source fixtures.

The89-file durable AT `offline-phy-contract-20261003` archive rehashes with manifest
`339434abf723bf0021a5307191cfb25e56d2a7d8d6c4329925d1f0e9fdbfd387`.
It preserves original/final source, every inventory iteration, selected vendor
listings/bytes/tables, actual Linux harness/results, four rejected fixtures,
source/style review and contemporaneous checklist/boot records. Known-good
UUID/default, empty next entry, absent BootNext and all47 open boxes verify at freeze.
