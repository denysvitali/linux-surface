boxes closed: 3 of 47; newly closed: none.

# Automatic validation guidance and boot enforcement

Current boot `93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`: **11/48 functional passes**, 36/52
inventory observations, **51 blocked, 2 failed, 0 errors**. Generated evidence:
[report.json](/var/lib/spx-boot-diagnostics/boots/93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d/hw-validation/report.json),
[report.md](/var/lib/spx-boot-diagnostics/boots/93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d/hw-validation/report.md),
[active checklist](../../../AUTO-HW-CHECKLIST.md).

Ten bounded agents contributed feature research and an isolated graphics fix.
The canonical suite remains `tools/spx/hw-validation`; `../hw-validation` is
already retired to a forwarding shim with its reports preserved as history.
`../validation` and the physical-test document remain voluntary human checks.
Corrected stale recovery, sensor, battery and audio instructions accordingly.

**Implemented:** `trial.py boot` and `promote` now require complete live results
matching the current boot/kernel before and after checks and the current
catalog. Recorded hardware failures permit corrective trials. Automatic return
records report/runner paths and status without delaying recovery. The installed,
enabled per-boot service has a ten-minute runtime ceiling and interruption
finalizer. Updated guidance requires rebuilding/reinstalling the validator after
code/catalog changes; installing a trial alone preserves the existing binary.

The 100-row generated catalog separates five advertised decoder codecs;
one supplied fixture is decoded once and only its matching codec can pass.
Bluetooth discovery now requires fresh reception. Vulkan compares all 4,096
public-fixture pixels. Failed audio services and exposed light I/O failures are
failures, unexpected runner problems are errors, and proven platform faults
survive incomplete metadata. Unimplemented DNS/USB workloads are labelled as
validator gaps. Type-C routing, concurrent dock operation, calibrated lux and
fresh desktop motion/compass delivery retain explicit blocked requirements.

**Observed:** Wi-Fi scanning, Bluetooth reception from 16 peers, static Vulkan
readback, H.264 hardware decoding and native sensor delivery passed. The two
failed rows are `audio.feeder` and `diag.failed-units`, both identifying the
existing failed desktop speaker feeder; this rework does not fix its EIO.
Other codecs lack fixtures; cellular support/provisioning, complete Vulkan,
camera integration, audio lifecycle and accessory paths remain open.
Unsafe encoder, playback/capture and battery tests were not attempted.

**Validation:** Go tests and 14 Python boot-wrapper tests pass; service syntax
validation and userspace build pass. Installed binary rejects another boot's
report without generating a checklist. The updated service completed its
current-boot run, generated the checklist and passed report verification despite
the recorded hardware failures. No reboot or device/kernel/DT/module changes
were made for this rework. Execution on a subsequent actual boot is unverified.

The current hardware defect remains the speaker-feeder EIO, with its existing
diagnostic and authorization requirements in TODO. Future baseline, trial and
recovery boots must each record and inspect their own validation result.
