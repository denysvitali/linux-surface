# Rear stream failure cleanup before privacy release

C01/C05 offline fix, 2026-10-03. This record describes the source at that step;
subsequent [V4L2 privacy ordering](../camera-privacy-20261003/STREAM-ORDERING.md)
fixes LED-after-start and reruns this integration suite. Its immutable archive
and original findings remain unchanged. The original OV13858 stream-off path discarded
a failed standby write and used asynchronous runtime PM. The unchanged V4L2
wrapper turns the privacy LED off when that driver call returns; it also forces
negative stream-stop returns to0. Propagating the standby error alone therefore
does not establish that the sensor stopped before LED release.

The managed-power path now asserts the configured reset on failed start or stop,
then drops the stream's PM reference with synchronous suspend. The original I2C
error is preserved. A separate stream-error latch blocks controls, new streams
and runtime resume while power remains on with reset asserted. Normal power-off
clears that latch after reset assertion and clock removal. The existing rail
cleanup error latch still blocks I/O if regulator cleanup fails. Successful
stream-off keeps its original PM path; firmware-managed devices preserve their
existing PM ownership and now return the standby-write error.

Synchronous PM can return0 while another user retains a PM reference: the code
does not treat that return as proof of power-off. The retained reset/error state
provides the SPX software guard in that case. SPX has a configured reset GPIO17;
the generic optional-GPIO path does not establish an electrical privacy guarantee
on boards lacking that reset. Physical reset behavior still needs validation.

`check_rear_stream_failure.py` extracts the actual sensor functions, regulator
bulk-disable implementation and unchanged V4L2 `call_s_stream`. The original
source reproduces LED release with reset deasserted after a failed standby write.
The final source passes **67 stream fault cases plus171 existing lifecycle cases**
under ASAN/UBSAN with strict compiler warnings. Cases cover failed start/standby,
suspend forbidden, retained PM users, all three regulator-disable points, partial
vote release/failed restore, separate regulator users, quarantine, normal retry,
failed resume and shutdown. PM/GPIO/clock/I2C are modeled; these are software
checks, not a physical stream or capture pass.

Original sensor SHA256:
`1dbf38dfbf4e6d19952d888c3594f2917a9c9fb551fe642c1566ae78e5de30c7`.
Final sensor SHA256:
`358a0d5c6c380cddc69542dcb99c1c74e4c15f90fd09aeff06c27e6639057de5`.
Prior source, complete pre-existing diff, scoped delta, extracted harnesses,
original failing assertion and intermediate/final results are preserved.
The initial baseline invocation omitted its mode flag and failed before harness
generation; its corrected exclusive run reproduces the intended defect.

Reproduce with a fresh output directory:

```sh
/usr/bin/python3 tools/spx/boot-diagnostics/camera-power-20261003/check_rear_stream_failure.py drivers/media/i2c/ov13858.c /var/tmp/spx-rear-stream-check-new
```

Scoped code style checks report0 errors/warnings/checks; commit-message/signoff
checks are excluded because the artifact is a source delta, not a signed commit.
The original metadata-only check output remains retained. The first native compile
failed because it started before fixture copying finished. The replacement source
was checked against all96,078 parent files/102 links before changing only the
sensor; the build fixture was copied to a separate fresh destination.

No modified module was loaded or installed, and no new trial was selected.
Actual boot remains known-good `74f8ed0e-be29-43fc-b8c1-9c9fa4e25d9b`.
V4L2 still enables its LED after successful driver start; physical onset/stop
timing, capture, real fault cleanup and receiver analog ownership remain open.
All47 hardware acceptance checks remain open.

Native ARM64 compilation with `W=1 KCFLAGS=-Werror` and strict modpost/link
passes for all16 camera/support modules. The single-module attempts compiled
the driver but failed modpost because in-tree module checks require the support
modules on the same command. `KBUILD_EXTRA_SYMBOLS` applies to external modules
and did not repair the in-tree attempt. Both failures are retained; the final
command includes all16 actual dependencies and suppresses no missing-symbol
errors. The untouched retained September kernel export object is the compile
basis; this is not a complete current-kernel build or a deployable candidate.
The fixture release remains `7.3.0-rc2-spx-mainline-20260922g`.

The166-file durable AT `offline-rear-stream-failure-20261003` archive preserves
original/final source and tests, all failures, exact native commands/config,
16 linked modules/objects, full source hash inventory, implementation and
contemporaneous checklist/boot records. Every archived file rehashes; manifest
`57686ef14a819554c1d4388f9db9dc4e1e712c01885ec4099b0ba8ea94ce181e`.
Known-good UUID/default, empty next entry, absent BootNext and all47 checks
still open were verified during the archive.
