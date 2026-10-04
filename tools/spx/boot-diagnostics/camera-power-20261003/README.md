# Camera rail audit and supply-order candidate, 2026-10-03

**Later AQ result:** the three SPMI providers registered disabled with zero
consumers; all21 sampled PMIC bytes match AP. AQ failed its baseline because
initial touch probe timed out, then returned automatically to known-good. Read
[the actual result](../RESULT-20261003aq.md). No sensor was enabled.

**Rear lifecycle correction after AQ:** power-off now returns rail cleanup errors
to runtime suspend. Failed normal/rollback bulk-disable latches the power error:
later resume, controls and stream operations reject further use. Bulk-disable
may restore earlier rails, or report an upstream failure after releasing the
consumer's own vote; blindly retrying can leak or underflow references. The latch
preserves that uncertainty rather than guessing the remaining votes. Reset stays
asserted and the clock is stopped; electrical rail-off remains unproven on error.

A DT-managed I2C shutdown callback now drains runtime PM, excludes controls/stream
changes and powers down. Remove uses the same quiesce helper before destroying
controls/mutex. Repeated quiesce is idempotent; the shutdown wrapper retains the
ACPI-managed path. Actual power/PM/control/stream/quiesce functions and the actual
regulator bulk-disable function pass171 ASAN/UBSAN fault cases: errors before/after
vote release, failed restores/unwind, shared references and shutdown gates. The
original driver is rejected because runtime suspend silently returns success.
Actual candidate native object and16 camera/support modules compile/strictly link
without warnings using isolated historical exports; these artifacts are never
deployable. Hardware callback timing, firmware arbitration, real shared rails and
sensor operation still need actual tests. A failed-cleanup latch is a reported
fault requiring recovery; it is not a claim of repaired electrical behavior.
The combined87-file AQ follow-up archive has verified manifest
`c05163c4bea62a2845eb90fd4400bb8d91e18d5668f43238a46ff3f37409abc9`;
actual sensor source SHA256
`1dbf38dfbf4e6d19952d888c3594f2917a9c9fb551fe642c1566ae78e5de30c7`.

Checklist target: **C01**. Cameras remain absent on the running AP kernel.
This work corrects a source-level power-sequence defect and adds SC8180X CCI
binding coverage. It does not resolve regulator ownership or enable cameras.

Later bounded AP reads resolved the three PMIC subtypes. See the measured provider
section below; its kernel registration and electrical behavior remain untested.

The firmware source is the retained SQ2 DSDT at
`/home/dvitali/Documents/acpi/surface_pro_x_sq2/dsdt.dsl`, SHA256
`e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8`.
`audit_firmware.py` extracts CPXC as literal packages, validates all 986 declared
package lengths, and preserves every operation's order and DSL line number.
The complete extraction is retained in the evidence archive.

| Firmware device | Proven topology counterpart | D0 votes in table order | D3 votes in table order |
| --- | --- | --- | --- |
| CAMS, GPIO22/MCLK0 | Rear OV13858 | LDO14_A 1.8 V → LDO17_A 2.85 V → LDO1_A 1.2 V | LDO1_A → LDO17_A → LDO14_A, zero votes |
| CAMF, GPIO12/MCLK2 | Front OV5693 | LDO14_A 1.8 V | LDO14_A, zero vote |
| CAMI, GPIO23/MCLK3 | IR OV7251 | LDO14_A 1.8 V | LDO14_A, zero vote |

Rear D0 vote packages start at DSL lines63473/63487/63501; D3 at
63590/63604/63618. Front D0 starts63798; IR D0 starts64076.
The firmware also asserts reset before the sensor votes and configures19.2MHz
MCLK before releasing reset. D3 asserts reset before stopping MCLK/removing
votes. The rear/front D3 tables include a one-unit delay after reset assertion;
this audit does not establish the unit or validate Linux shutdown timing.

Front/IR each request just LDO14 in this table. The historical shared three-rail
fixed supplies cannot establish their physical AVDD/DVDD wiring. Missing votes
are not evidence that those physical supplies are absent. CAMP's six component/
F-state tables contain no PMICVREGVOTE entries; they do not identify the actual
CAMSS analog supply providers. No CAMSS regulator requirement was removed.

## Source changes and validation

`ov13858_power_on()` now enables its existing `dovdd`, `avdd`, `dvdd` consumers
sequentially. Previously it called `regulator_bulk_enable()`, whose core
implementation uses asynchronous workers and gives no completion-order guarantee.
The existing historical mapping associates those three names with the rear
firmware sequence. On an enable or clock failure, the candidate passes only
the successfully enabled prefix to `regulator_bulk_disable()`, retaining that
API's reverse order, error reporting and disable-failure handling. The normal
power-off path and ACPI-managed path are unchanged. This is a prerequisite for
real regulators; the old always-on placeholders hid the ordering defect.

`check_power_sequence.py` compiles the actual source power functions with ASAN/
UBSAN and fault-injects all three enable failures and a clock failure. Eleven
cases pass, including retry after failure, successful order, balanced references
with another consumer, idempotent calls and the unmanaged path. A valid reversed
bulk-enable completion schedule makes the original source fail the same ordering
test. The stubs assume successful disables; real disable failures, electrical
settling, timing and hardware operation remain untested.

The two-line CCI binding change adds `qcom,sc8180x-cci` with the existing
`qcom,msm8996-cci` fallback and includes it in the five-clock group. Existing
CCI-v2 driver matching is sufficient. `check_cci_binding.py` validates the actual
schema, compiles the current board plus disabled camera extraction, and checks
five positive/four negative cases. Missing power domain, four clocks, incorrect
fifth clock name and incorrect fallback are rejected. SC7280/SM8250/SM8450
regression descriptions remain valid. All enabled variants are disposable offline
DTBs. Existing base DTC and focused-schema reference warnings remain in the logs;
this is not full camera-tree schema acceptance.

The driver and binding are separate review patches. Each passes strict checkpatch
with zero errors/warnings/checks and a reverse-application check. The initial
combined checkpatch run correctly warned that bindings need a separate patch;
that log is preserved. Native build details and final strict-link status are in
the evidence's `native-build.json`/`native-link.json`. The isolated build derives
from the preserved September camera configuration/source snapshot and historical
kernel exports. It validates the new sensor source; it is not a full current
kernel or a deployable module set. No artifacts from it were installed.

## Remaining integration work

1. Obtain bounded, identity-bound PMIC revision/subtype, configured voltage,
   enable and status evidence for SID1 pages0x4000/0x4d00/0x5000 before choosing
   the direct regulator implementation. The historical helper writes only EN_CTL
   bit7; it does not program voltage. Its failed optional reads are unchecked and
   its header incorrectly identifies peripheral type0x1c as an LDO, although the
   actual write gate checks0x04. Do not use its unchecked reads as provider proof.
2. Resolve ownership/concurrency with firmware, upstream input supplies, shared
   consumer references, fault rollback and shutdown. The recorded RPMh ACK
   timeouts establish a failed path; the claim that a different DRV owns it is
   a hypothesis. Avoid another LDO14_A RPMh vote on that evidence.
3. Establish front/IR physical supplies and CAMSS `vdda-phy`/`vdda-pll` providers;
   do not route every sensor supply to guessed shared rails or remove CAMSS
   requirements because firmware lists no vote. Review reset/clock sequencing
   in the other sensor drivers against the firmware and their sensor contracts.
4. Finish CAMSS SID/binding and sensor endpoint/binding review, then prepare a
   distinct camera-enabled kernel/config/DTB/modules/initramfs with staged boot
   collection. Include the existing reviewed touch-output bounds patch in that
   source provenance. AP's preboot source guard cannot accept this modified tree.

Reproduce offline from the repository root:

```sh
python3 tools/spx/boot-diagnostics/camera-power-20261003/audit_firmware.py /home/dvitali/Documents/acpi/surface_pro_x_sq2/dsdt.dsl /var/tmp/camera-firmware.json
python3 tools/spx/boot-diagnostics/camera-power-20261003/check_power_sequence.py drivers/media/i2c/ov13858.c /var/tmp/camera-power-check
python3 tools/spx/boot-diagnostics/camera-power-20261003/check_cci_binding.py /var/tmp/camera-cci-check
```

The last command uses system Python/libfdt and the existing dtschema environment/
schema reference subset recorded in its source. Evidence is under
`/var/lib/spx-boot-diagnostics/attempts/20261002ap/camera-power-c01-20261003/`.
It preserves source before/after, separate patches, firmware DSL/extraction,
native objects/modules/config, raw validation logs and a verified SHA256 manifest.
AP's original baseline and build archives remain immutable.

## Measured direct SPMI provider candidate

On the same AP boot, `read_pmic.py` used21 bounded O_RDONLY/pread reads through
the existing regmap debugfs interface: seven whitelisted identity/control bytes
at each known SID1 peripheral0x4000/0x4d00/0x5000. It did not scan the map, read
IRQ/status bytes, load modules or write registers. Source review established
9-byte records and the address→file-offset mapping before reading. All reads
succeeded in0.002s; boot ID, taint0 and touch readiness stayed unchanged.

| Rail | Measured type/subtype, revision | Existing driver voltage table | Programmed voltage | Enable byte |
| --- | --- | --- | --- | --- |
| LDO1_A | 04/6b, rev2 (N600_510) | nldo_510 | 1.200 V | 00 |
| LDO14_A | 04/72, rev2 (LV_P300_510) | ht_lvpldo | 1.800 V | 00 |
| LDO17_A | 04/7d, rev2 (MV_P600_510) | pldo660 | 2.856 V | 00 |

These are existing LDO_510 types. Firmware's2.850V request is not on the8mV
grid; the exact current LDO17 code0x0b28 is2.856V. The offline fragment retains
that measured value. Its three input phandles match the board's existing PMIC A
RPMh supply groups; the RPMh node has no ldo1/14/17 consumers. This establishes
the proposed Linux mapping, not firmware arbitration or concurrent electrical
behavior. Front/IR physical AVDD/DVDD and CAMSS analog providers are still unknown.

The candidate adds a limited `qcom,pmc8180-regulators` mapping to the standard
SPMI driver, supporting only these three measured camera rails. It checks bus
errors/range/step alignment in the existing voltage getter and skips unchanged
8-byte initialization writes. Explicit legacy pin and VS configuration changes
retain their writes. Actual-function ASAN/UBSAN tests pass196,608 voltage codes,
three read errors, default/idempotent initialization, pin changes, read/write
failure and VS soft start; the original getter fails. The full source compiles
and strictly links against preserved September exports; that test module must
never be installed or loaded. Separate driver/binding patches pass strict
checkpatch0/0/0.

`spx-camera-regulators-disabled.dtsi` is an offline, disabled fragment with no
consumers, boot-on, always-on or initial-mode properties. Validation checks its
exact voltages/upstream phandles and absent duplicate RPMh nodes; two positive
and two negative cases pass. Initial wrong-node-path and insufficient type-size
mutation checks are retained as setup failures. Final negative checks reject
pin-control overflow and an unknown supply. This limited schema invocation does
not prove supply/voltage cell typing; those exact compiled values are independently
checked in the FDT. Full base-DT warnings remain in the DTC log.

Core review: matching voltage constraints cause no voltage write; absent boot/
always-on flags cause no enable; late cleanup skips disabled rails. These are
source expectations, not measurements of candidate registration. A fresh AQ
build uses a full isolated source snapshot and the unchanged AM config except
LOCALVERSION. Its next intended scope is provider registration with sensors
disabled, followed by an actual result before deciding another experiment.

Durable AP evidence:

- `camera-pmic-metadata-20261003/`: source and raw21 reads, manifest
  `6fc4372f9bdbaad65efc649c688e9910fd51991b215705128cd4761875cf26b0`.
- `camera-regulator-c01-20261003/`:104 files, including initial/final tests,
  patches, full-source compile/link, disabled and mutated DTBs, schemas and logs;
  independently verified manifest
  `d1fe47920500ee869d16ed08df8d9426f6aa1706916ce58b18f6f96180c83d2e`.

No candidate probe, register write, rail enable or camera capture has occurred.
C01–C05 and all47 acceptance checks remain open.
