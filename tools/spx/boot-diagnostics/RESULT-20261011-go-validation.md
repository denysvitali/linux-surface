boxes closed: 3 of 47; newly closed: none.

# Go hardware inventory and kernel work

Boot `298cf388-134f-4db3-a218-413f5af213d3`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Changed:** replaced Python validator/tests with standalone standard-library
Go in `tools/spx/hw-validation/`. No Python or sibling runtime dependency.
The exact frozen47 checklist requirements are loaded at run time; current
closed status remains3. Missing interfaces/tools/permissions remain unknown;
presence never grants functional acceptance. Build, fixture tests, race tests
and vet pass. No hardware constants, gain or kernel configuration changed.

**Ran:** `/tmp/spx-hw-validation --repo . --output
 tools/spx/boot-diagnostics/hw-validation-go-20261011` on live hardware under
the shared lock.43 probes:31 observed,9 unknown,3 needing investigation.
Outputs: `hw-validation-go-20261011.md` and `.json` in this directory.
Missing exposed interfaces: CDSP, WWAN/GNSS, Type-C/roles, video decoder/encoder.
Sensor proxy inactive; sleep targets masked. Pstore unreadable; watchdog
identity path unavailable: neither counts as missing recovery hardware.

**Kernel interpretation:** live config confirms IPA/WWAN off; source lacks
SC8180X IPA resources/data/DT and full two-port Type-C/PD/role integration.
Venus's session-ID fix exists but firmware validation is still missing.
Current boot front camera is disabled, unlike earlier live-overlay capture;
source changes need persistent DT deployment/cold-start validation. CDSP is
intentionally disabled/parked after failures. TCS3430 is present: desktop
service integration is a separate issue. Details/code paths and dependencies
are in `KERNEL-GAPS-20261011.md`.

**Next:** preserve blocker order. No speculative kernel patch or deployment
was made from enumeration alone. Existing Venus candidate requires a planned
clean boot; camera persistence requires a DTB trial. Full physical/lifecycle
acceptance and speaker latency/distortion judgment remain pending. No sound,
capture, raw sensors, load, suspend, module change or reboot in this session.
