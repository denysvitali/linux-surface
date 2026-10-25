# Automatic Surface Pro X hardware checks

This Go 1.22 tool runs bounded automatic checks. It does not parse or edit
`PORT-CHECKLIST.md`. `AUTO-HW-CHECKLIST.md` is the active automatic completion
list, generated entirely from the catalog and report outcomes. All checks
remain visible when blocked or unsupported. There are no manual conditions.

A check being implemented means the validator can attempt it. It does **not**
mean a driver is implemented or that the fitted hardware works.

## Run

From the repository root:

```sh
go -C tools/spx/hw-validation run . --repo "$PWD" --output /var/tmp/spx-auto-hw
```

This writes `/var/tmp/spx-auto-hw.json`, `/var/tmp/spx-auto-hw.md`, and
`AUTO-HW-CHECKLIST.md`. The existing `--repo PATH --output BASE` invocation
continues to work. `.json` or `.md` on BASE is optional. Without `--output`,
reports go to `tools/spx/boot-diagnostics/auto-hw-DATE-BOOT.json` and `.md`.
A report stores the run date and boot/kernel identity before and after checks.
Keep report basenames distinct when keeping multiple runs.

| Flag | Meaning |
| --- | --- |
| `--repo PATH` | Repository root; default current directory. |
| `--user USER` | Explicit existing desktop session user for selected session commands. No fixed UID or guessed account. |
| `--output BASE` | JSON/Markdown report basename. With `--checklist`, source saved JSON. |
| `--list` | Print catalog IDs, areas, kinds and titles. No tests, commands, locks or hardware reads. |
| `--list-json` | Print current catalog metadata as JSON, with validator implementation meaning. |
| `--from-report JSON` | Generate checklist from saved report and matching current catalog, preserving date and boot. Catalog changes require a new run. |
| `--require-current-boot` | With saved-report generation, require complete live evidence for the current boot/kernel before and after checks. Read-only boot identity reads; no checks or locks. |
| `--checklist` | Generate checklist only. No tests, commands, locks or hardware reads. Without `--output`, every row is marked not run. |
| `--checklist-path PATH` | Override `<repo>/AUTO-HW-CHECKLIST.md`. |
| `--root PATH` | Fixture filesystem root; disables all external commands and live locking, even for `--root /`. |
| `--capture-camera` | Allow three processed frames per camera, discarded in memory; no IR emitter activation. An announcement is printed. |
| `--capture-microphone` | Allow bounded microphone capture subject to parked audio restrictions; samples discarded. Does not authorize sound. |
| `--capture` | Compatibility alias enabling both capture opt-ins. Does not authorize speaker playback. |
| `--media PATH` | Existing media fixture for bounded decoder-only checks; takes precedence over directory fixtures of the same codec. No encoder trials. |
| `--media-dir PATH` | Absolute directory of verified public video fixtures; regular files are probed in lexical order, without recursion. |
| `--dns-name NAME` | Deliberate public DNS fixture hostname; default `example.com`. System resolver lookup has a three-second total deadline. |
| `--no-dns-lookup` | Disable external DNS lookup; its functional row stays blocked. |
| `--storage-dir PATH` | Directory for bounded disposable-file storage checks; never raw-device writes. |

Regenerate exactly the saved boot's checklist, preserving its date:

```sh
go -C tools/spx/hw-validation run . --repo "$PWD" --checklist --output /var/tmp/spx-auto-hw
```

`--checklist` alone creates an unrun catalog, not a success report. It will
replace the active checklist with unchecked rows; use a separate
`--checklist-path` if the current run should be preserved.

## Automatic checks on every boot

Build the userspace binary, then install the existing boot wrapper and service:

```sh
go -C tools/spx/hw-validation build -o /var/tmp/spx-hw-validation .
sudo python3 tools/spx/boot-diagnostics/automatic-validation.py install \
  --repo "$PWD" --binary /var/tmp/spx-hw-validation --user dvitali \
  --media /absolute/path/to/verified-public-h264.mp4 \
  --storage-dir /var/lib/spx-boot-diagnostics
```

Replace the example media path with the existing verified decoder fixture.
`--user` selects the actual desktop account; it does not change root hardware
probes. Windowless GTK rendering imports only `WAYLAND_DISPLAY`, `DISPLAY`,
and `XAUTHORITY` from that existing user manager via read-only `show-environment`;
no display socket is guessed and no other environment values are retained.
The installer writes `/etc/spx/hw-validation.json` with `repo`, `user`,
`media`, `media_dir`, `storage_dir`, and `network_wait_seconds`, preserving
previously selected optional values. `network_wait_seconds` defaults to 90,
can be set to 0 to disable the wait, and is clamped to 0..300 seconds. On each
`run`, the wrapper polls `/proc/net/route` and `/proc/net/ipv6_route` about once
per second before starting the validator; it does not change network state.
The bounded wait is outside the Go suite's device-lock interval.
The binary and wrapper live in `/usr/local/lib/spx-boot-diagnostics/`.
`spx-hw-validation.service` is enabled for future boots; installation does not
start tests, reboot, change boot selections, or modify recovery timers.
After any validator code/catalog change, rebuild and install the binary with
`--binary` again. Trial setup preserves the installed binary; it does not
compile a new catalog from changed source.

Each boot writes private evidence under
`/var/lib/spx-boot-diagnostics/boots/<boot-id>/hw-validation/`: `report.json`,
`report.md`, `checklist.md`, and `runner.json`/`runner.md`. The runner status
records the actual wait duration and whether a default route existed when the
suite started, including when the wait expires without a route. Successful report
generation updates the repository's active checklist without rerunning checks.
A busy device lock defers this same boot for 60 seconds. A missing executable,
configuration, tool, fixture, permission or desktop session is reported
explicitly; the wrapper does not install tools or repair services. Read private
reports with the required privilege; progress may read their generated public
checklist summary without duplicating outcomes.

The service has a fifteen-minute runtime ceiling to include the maximum
five-minute network wait and the existing validator budget. An interrupted or timed-out run
records failed runner status through its finalizer; a retained report does not
become that failed invocation's result. After repairing a prerequisite, rerun
and inspect this boot's evidence:

```sh
sudo systemctl restart spx-hw-validation.service
sudo python3 -B tools/spx/boot-diagnostics/automatic-validation.py verify
tools/spx/progress -v
```

Verification rejects missing, fixture, older-boot, inconsistent-identity and
incomplete/current-catalog-mismatched reports. It accepts recorded hardware
failures so a corrective trial remains possible. `trial.py boot` and `promote`
require this verification before changing boot selection. Bounded trial return
records the validation paths/status and continues recovery if it is incomplete.

Decoder requirements are separate for H.264, HEVC, MPEG-2, VP8 and VP9. The
supplied `--media` fixture and regular files in `--media-dir` are probed with
ffprobe. The first valid fixture attributed to each codec is selected (explicit
`--media` first, then directory entries in lexical order). Duplicate fixtures
never trigger retries, including after a failure. Each codec gets at most one
explicit FFmpeg V4L2 mem2mem decode, capped at 30 frames / 2 seconds of media;
software fallback cannot pass. Missing fixtures/tools/decoder nodes stay blocked;
hardware rejection or decode errors fail. Existing encoder exposure blocks decoding.
The boot installer accepts `--media-dir` and preserves it in configuration;
without an explicit directory, the hook uses
`/var/lib/spx-boot-diagnostics/fixtures/media` if present (under `--base` when
overridden). The existing single `--media` configuration remains supported.

DNS lookup requires a configured resolver and a usable IPv4 or IPv6 default
route. The system resolver queries the chosen absolute hostname (no search-domain
expansion); any A/AAAA answer passes, while failure/NXDOMAIN/timeout with these
prerequisites fails. Reports retain the fixture name and family counts, never
resolved addresses or raw errors. Disabled lookups, missing prerequisites and
fixture-root runs stay blocked.
Bluetooth discovery needs fresh peer reports as well as safe session cleanup;
an empty scan remains blocked for reception, without requesting a human action.
Static Vulkan compares all 4,096 public-fixture pixels; it does not cover the
separate partial-area load/store regression. `graphics.vulkan.dynamic-damage`
runs the installed windowless CPU-model comparison as the selected `--user`:

```sh
env TU_DEBUG=gmem [VK_DRIVER_FILES=...] [VK_ICD_FILENAMES=...] \
  timeout --kill-after=2s 15s /usr/local/lib/spx-turnip/spx-vk-partial-load-store
```

Bracketed assignments are included only when set by simple KEY=VALUE lines in
`/etc/environment`; surrounding quotes and comment lines are ignored. The
report identifies the effective ICD selection (`VK_DRIVER_FILES` takes
precedence over `VK_ICD_FILENAMES`), or `system default`. The normal user-command
wrapper supplies runtime/bus variables and uses `runuser` when needed. No
window or display-session lookup is needed for this windowless test.
The timeout selector unwraps `env`/`runuser`, so this command uses the existing
20-second runner ceiling, with an explicit 15-second workload and two-second
kill grace; no timeout table change is required.

A pass requires exit zero, a `PASS;` line and a hardware Turnip `Device:`
witness. Software fallback is rejected. Exit 1 or `FAIL;` fails, retaining
only the first nonzero pixels-differ count, never raw pixels or hashes.
A missing binary/user, fixture-root run, unsupported exit 77 or missing device
witness stays blocked. Exit 2, malformed results and abnormal runner exits are
errors. This checks the specific partial LOAD/STORE GMEM defect, not general
Vulkan conformance or visual scrolling acceptance. A pass needs the msm A680 GMEM-base fix (kernel `fa0a790ad9ed`);
with the private sysmem-workaround driver it avoids rather than tests that
kernel path. See [Mesa notes](../mesa/README.md).

Boot camera capture defaults to disabled. `install --camera-capture` persists
`"camera_capture": true` in `/etc/spx/hw-validation.json`; `install --no-camera-capture`
disables it. Reinstallation without either option retains the previous boolean.
`run` forwards only `--capture-camera` when enabled and announces both classes
in runner status. Persisted boot settings cannot enable microphone capture or sound.

Camera rows run sequentially, checking each sensor's test pattern is off before
requesting three BGR888 viewfinder frames with no file/display sink. Frames stay
in memory and are discarded; only parsed frame counts/sequence evidence is reported.
Capture uses `timeout --signal=INT --kill-after=2s 15s`. The private `cam` build
uses explicit `LD_LIBRARY_PATH` entries for its `build/src/libcamera` and
`build/src/libcamera/base`, `LIBCAMERA_SOFTISP_MODE=cpu` and
`LIBCAMERA_LOG_LEVELS=*:ERROR`; its normal build-tree discovery supplies IPA paths.
Other inherited `LIBCAMERA_*` settings are not overridden. Camera commands run as
the validator account (root in the boot service), not the `--user` desktop account.
No IR-emitter controls are requested; physical driver behaviour remains untested
by these offline fixtures. A camera absent from the libcamera list stays blocked.

Native microphone
stimulus, speaker output and parked audio lifecycle checks can remain blocked
even with `--capture`: that flag does not supply a stimulus, authorize playback,
or remove the parked DSP restrictions. Encoder trials remain blocked. Missing
`cam`, `ffmpeg`, `eglinfo`, `vulkaninfo`, GL/GLES render tools, `gtk4-rendernode-tool`,
`pactl`, or other feature tools are concrete blockers, not hardware absence.

## CPU transitions and transient TPM signing

`cpu.frequency-transitions` reads each policy's current/min/max frequency,
related CPUs, governor and optional transition/time-in-state statistics. It
runs one fixed 1.5-second busy loop on one CPU per policy concurrently, samples
frequency every 250 ms for six samples, then samples idle frequency every
500 ms for three seconds. All policies share this approximately 4.5-second
window (timeout's kill grace is 0.2 seconds). Each policy needs a loaded peak
above its starting frequency followed by a lower idle sample, or an increased
`stats/total_trans`. Details retain per-policy min/idle/peak/after kHz. Fixed
performance/powersave governors or equal limits, missing attributes/tools and
fixture runs stay blocked. A policy starting at its maximum without either
existing transition witness is also blocked: there is no headroom to measure
a rise, and the starting sample does not establish an idle baseline. This
is not a pass or proof of a hardware fault. A complete below-ceiling failure
on another policy still fails the check, even when a policy is blocked.
No sysfs writes or governor/limit changes occur; this short transition smoke
is not thermal or battery/endurance validation.

Exact external commands (CPU is the first numeric `related_cpus` member):

```sh
sh -c 'command -v taskset >/dev/null && command -v timeout >/dev/null && command -v sh >/dev/null'
taskset -c CPU timeout -k 0.2 1.5 sh -c 'while :; do :; done'
```

`security.tpm-signing` requires accessible `/dev/tpmrm0` and tpm2-tools. It
selects ECC from read-only algorithm capabilities, falling back to RSA when
ECC is not advertised. It creates an unrestricted signing primary explicitly
under the NULL hierarchy, signs the SHA-256 digest of the public fixed string
`Surface Pro X automatic TPM signing smoke v1`, and verifies using the same
saved context. A mode-0700 `os.MkdirTemp` directory holds the mode-0600 digest,
context, signature and verification ticket, then is removed on every exit.
Creation refusal is blocked; sign/verify failure after creation fails; cleanup
failure is an error. Fixture runs never open the TPM or execute commands.

Exact external commands (`DIR` is the private temporary directory, `ALG` is
`ecc` or `rsa`):

```sh
sh -c 'command -v tpm2_getcap >/dev/null && command -v tpm2_createprimary >/dev/null && command -v tpm2_sign >/dev/null && command -v tpm2_verifysignature >/dev/null && command -v tpm2_flushcontext >/dev/null'
tpm2_getcap --tcti=device:/dev/tpmrm0 algorithms
tpm2_createprimary --tcti=device:/dev/tpmrm0 -C n -G ALG -g sha256 -a 'sign|fixedtpm|fixedparent|sensitivedataorigin|userwithauth' -c DIR/primary.ctx
tpm2_sign --tcti=device:/dev/tpmrm0 -c DIR/primary.ctx -g sha256 -d -f tss -o DIR/signature DIR/digest
tpm2_verifysignature --tcti=device:/dev/tpmrm0 -c DIR/primary.ctx -g sha256 -d DIR/digest -s DIR/signature -t DIR/verification.ticket
tpm2_flushcontext --tcti=device:/dev/tpmrm0 -t
```

Cleanup attempts flush even when creation/sign/verification fails. Linux's
resource manager releases each command connection's transient objects on
close. The final `-t` flush is restricted to its resource-manager connection;
it cannot flush other clients' objects. tpm2-tools 5.8 does not accept saved
object-context files as flush arguments (only transient handles/session files).
No raw `/dev/tpm0` fallback, persistent handles, NV writes, hierarchy/auth
changes, PCR extends or owner/endorsement hierarchy use occur. TPM output and
raw errors are discarded; results describe only the workflow and its scope.

## Outcomes

- `pass`: a functional check completed its stated workload. Only this outcome
  ticks a generated checkbox.
- `observed`: interface/service inventory, or observation without functional
  proof. Inventory rows have no checkbox and never return `pass`.
- `blocked`: missing kernel/userspace support, permission, tool, service or
  fixture. The detail states the reason. A missing node does not prove
  hardware absence.
- `fail`: a recognized functional malfunction.
- `error`: validator error or invalid outcome. Inventory cannot return `pass`.

All outcomes are recorded, even if another check fails. Failed/error checks
cause exit 1 after reports are written. Infrastructure/CLI errors cause exit 2.
A busy shared device lock causes exit 75, with no checks run. Blocked checks remain
incomplete but alone do not cause a failed run. Unavailable or changed
boot/kernel identity is a report error; mixed-boot results are never accepted.
Functional counts are independent of the historical full acceptance list.
They must not be reported as 47-box acceptance counts.

Live runs acquire/release `tools/spx/spx-lock` for the device. Each command has
an in-memory output cap and a process-group timeout: normally 20 seconds, 60 seconds for
media/graphics tools, 10 seconds for locking. Feature commands also use their
own shorter workload bounds. No raw command output is saved. Feature results
must be concise summaries, without MAC/IP/SSID, device serials or private
capture data; report formatting adds address/identifier redaction as a safety
net. Commands must not toggle/disconnect radios, modeset or reload MSM,
read unsafe debugfs/MMIO, suspend, reboot, load modules, test the battery or
run parked encoders. Sound is not authorized by these flags.

## Sensor delivery

`sensors.desktop-motion` invokes repository-relative `sensorproxy_probe.py` using
`python3 -B` through the normal command runner. Python PyGObject (`Gio`, `GLib`)
is required. It works as root on the system bus, uses one private persistent
connection, checks NameHasOwner first and disables activation on all calls.
It pins the existing service owner, reads HasAccelerometer and the orientation
before claiming, subscribes to PropertiesChanged before ClaimAccelerometer,
reads the orientation after claiming and observes for up to six seconds.
A finally path attempts ReleaseAccelerometer on the same connection, including
refused/lost claim replies and errors, then unsubscribes and closes. Async calls
have bounded timeouts; a GLib work deadline at 9.5 seconds cancels pending work
and enters cleanup, and a hard GLib deadline at 11.5 seconds terminates the
helper with an error result. Fixture-root runs never execute the helper.

A pass requires a post-claim PropertiesChanged carrying AccelerometerOrientation
or AccelerometerTilt, or orientation changing from undefined/empty before the
claim to a defined value afterward. The detail identifies the evidence.
An already-defined orientation with no signal is blocked: the device is
stationary and the property was already defined before the claim so freshness
cannot be distinguished. A successful claim with orientation undefined/empty
throughout the complete six-second window fails because the proxy obtained no
reading. Missing service, HasAccelerometer=false, claim refusal and unavailable
Python/helper/PyGObject remain blocked; runner/protocol/cleanup faults are errors.
No physical stimulus, service start, raw IIO reading or calibration is attempted.

The former combined `sensors.desktop-delivery` row is split into functional
`sensors.desktop-motion` and `sensors.desktop-compass`, increasing the functional
catalog total by one. A motion pass cannot establish compass delivery. The motion
detail reports HasCompass (true, false or unreadable) queried on
`/net/hadess/SensorProxy/Compass`, interface `net.hadess.SensorProxy.Compass`.
`sensors.desktop-compass` invokes the same helper with `--compass`, using the
Compass interface and path. It checks HasCompass, reads CompassHeading before
the claim, subscribes before ClaimCompass, and records finite in-range headings
from post-claim PropertiesChanged signals for up to six seconds. ClaimCompass
AccessDenied is reported as an access-policy block. No service activation or
policy bypass is attempted. A pass requires at least one fresh signal and a
released claim; the detail includes the count, rounded heading range and before/
after values. A no-signal run fails only when the value remained at its initial
value or was non-finite through the complete window. This proves fresh desktop
compass delivery only, not calibration, true-north accuracy or tilt compensation.

`sensors.light-lux` finds the IIO device whose `name` is `tcs3430`, requires
`/sys/module/tcs3430/parameters/surface_unit_calibration` to be `Y`, and reads
`in_illuminance_input` twice as finite non-negative processed lux. The report
includes both values and the available gain and integration-time attributes.
It then invokes `sensorproxy_probe.py --light` on one persistent system-bus
connection, without activation. The probe checks `HasAmbientLight`, subscribes
to `PropertiesChanged` before `ClaimLight`, reads `LightLevelUnit` and
`LightLevel` after claiming, and releases in a finally path. A post-claim
`LightLevel` signal or read is sufficient; an unchanged proxy reading in a
stationary dim room is acceptable because the two kernel reads already prove a
fresh conversion. Missing device/calibration/proxy, false capability and
refused claims are blocked. An unreadable/non-finite kernel lux value, or a
successful proxy claim with non-lux units or a non-finite level, fails.
Calibration is this unit's factory Type_3 data applied with the Windows
driver's formula; it does not establish absolute accuracy against a reference
lux meter, colour temperature, or brightness-control behaviour.

The helper emits one JSON object on stdout (exit zero for recorded outcomes):
`status` (pass/blocked/fail/error), `reason` (signal, transition, stationary,
undefined, no_heading, no_service, no_compass, no_accelerometer, access_denied,
claim_refused, unavailable, bus_unavailable, helper_error, timeout, release_error
or close_error), `has_compass` (boolean or null), `orientation_before` and
`orientation_after` (string or null), `signal`, `claimed`, `released`, and
`window_complete` (booleans). Compass mode additionally reports numeric
`compass_before`/`compass_after`, `compass_signal_count`, `compass_min` and
`compass_max`. Orientation strings remain in command memory; the Go report records
only controlled evidence summaries and compass capability. A pass or hardware
failure requires acknowledged claim release; incomplete observation is an error,
never a hardware failure. Raw errors and other command output are discarded.

`sensors.motion-read` uses the existing `ssccli` client against an already
running SensorsPD provider. It samples accelerometer, gyroscope and magnetometer
for three seconds each, sequentially. Each needs at least20 finite XYZ samples,
acknowledged enable/disable and the same active provider afterward. The client
has a12-second process bound. No host restart, DSP reset, raw IIO motion read,
physical movement or calibration judgement is part of this check. Raw values
and protocol logs stay in memory; the report retains only counts and scope.
The provider's existing private libssc selection is reused, not installed or
changed by the validator. Service/library/tool failures remain blocked or failed.

## GL/GLES offscreen tools

`graphics.gl.render` and `graphics.gles.render` require `glmark2-gbm` and
`glmark2-es2-gbm`, respectively. If the required executable is absent, a bounded
shell builtin PATH lookup distinguishes an installed glmark2 flavour without
GBM from no glmark2 tool installed. Distribution glmark2 2023.01 builds provide
other flavours, not these GBM executables. Those builds stay blocked:
`installed glmark2 has no GBM offscreen flavour; DRM flavour is excluded because
it requests a modeset`. Lookup failures leave installation status unknown.
The lookup only locates executables; it never runs DRM, EGL, desktop or Wayland
flavours. There is no DRM or Wayland fallback. Render-node prerequisites,
hardware-renderer selection and pixel-validation requirements still apply.

## Fixture contract and tests

`--root PATH` maps logical `/proc`, `/sys`, etc. to PATH. `AutoContext.Read`
returns trimmed text and replaces NULs with spaces. `ReadBytes` preserves
binary EFI/EDID data. `Glob` returns logical
absolute paths suitable for `Read`. Fixture paths and symlinks cannot escape
the root. Put fixture boot identity in:

```text
proc/sys/kernel/random/boot_id
proc/sys/kernel/osrelease
```

CLI fixtures never execute commands, native CPU/storage workloads, or take the live device lock. Unit tests
may explicitly inject `AutoContext.Run` with predetermined command responses.
This is not live hardware evidence. Fixture reports are labeled `fixture: true`.
Fixture runs without `--checklist-path` write `BASE-CHECKLIST.md` beside the
report, never the active real checklist. An explicit `--checklist-path` opts
into writing that selected path.

```sh
go -C tools/spx/hw-validation test ./...
```

Markdown includes `Report JSON: [JSON](ABSOLUTE_PATH)` for consumers such as progress.
`meta.report_json` stores the same pointer; it is not a second outcome store.

JSON contains `meta`, `coverage`, `catalog`, `results`, `counts`, and optional
report-level `errors`. Each catalog entry includes ID/title/area/kind,
historical box references, and validator implementation meaning. Outcomes
match catalog order and IDs. Markdown is derived from these fields, for example:

```markdown
- [x] **storage.io — Disposable-file integrity** (functional; pass): read/write/fsync checksum matched
- [ ] **camera.capture — Bounded capture** (functional; blocked): --capture-camera not enabled
- **network.inventory — Network interfaces** (inventory; observed): wireless interfaces=1
```

These examples describe semantics, not results on this device.

### GL/GLES offscreen tool

`graphics.gl.render` and `graphics.gles.render` need `glmark2-gbm` and
`glmark2-es2-gbm`. The distribution package has no GBM flavour, so they are
a private upstream build in `/var/tmp/spx-glmark2/prefix` (flavours
`gbm-gl,gbm-glesv2`, data path compiled in) linked into `/usr/local/bin`.
The check does not pass `--off-screen`: that FBO path makes `--validate` read
an empty buffer and fail even on llvmpipe. The GBM flavour opens only the
render node and never sets a mode.

### Authorized trial evidence

The audio speaker/acoustic/microphone/lifecycle, CPU thermal response, normal
suspend recovery, combined firmware stability and watchdog recovery rows read
helper evidence. They never start playback, capture, load, sleep or reset.
Every result must match `/proc/sys/kernel/random/boot_id` and the running kernel
release. A trial cmdline selects its attempt; otherwise results are found by
current boot identity. Earlier reports cannot satisfy these rows.

Evidence lives under `/var/lib/spx-boot-diagnostics/functional/<attempt>/`:

- `audio/reopen-result.json`: quiet channel phases, advancing native stereo
  hardware pointer, two distinct playback owners, continuous DMIC1 and parking.
  The PCM helper now records `running_status`, `consumed_status` and
  `dsp_consumed`. Full DSP UNMAP/AFE STOP and DMIC0 independence remain outside
  this retained reopen scope.
- `audio/feedback-result.json`: supplies the amps-off crosstalk control absent
  from reopen. Acoustic requires successful phases plus physical park readback
  and rejection of the same tones with the amplifiers off. Reopen alone leaves
  acoustic blocked. Feedback `--microphone-array` tests DMIC1/DMIC0 separately.
- `combined-thermal/result.json` or `cpu-thermal/result.json`: both clusters
  must cross the recorded trip, automatically reduce their maximum via cooling,
  then naturally recover below trip minus 5°C with original limits/state zero.
  `complete` alone never passes thermal response. The 50°C combined test needs
  verified native FP workers and witnessed CPU/GPU overlap, stops on both
  responses or at 75°C, and permits 180 seconds idle recovery.
- `systemd-suspend/result.json`, `systemd-suspend-recovery/result.json` or
  `audio-resume/result.json`: current-boot RTC/kernel/service proof, same fresh
  sensor owners, network/storage checks and restored masks. These prove the
  stated powered s2idle subset; display/BT/camera/decoder resume is additional
  coverage, and no energy-saving claim follows.
- `audio-resume/result.json`: failed retained audio/resume oracles fail firmware
  stability. A successful retained subset stays blocked for full combined
  firmware coverage. The admission contract for future `combined_firmware`
  evidence is `seconds >= 30`, `owners_preserved`, `clean_teardown`, an explicit
  empty `faults` array, and `before`/`after` maps containing `status: pass` for
  audio, sensors, wifi, bluetooth, gl, vulkan, decoder, tpm and cdsp. **The
  current helper does not produce this full combined workload.** Missing CDSP
  transport/loader and other workloads must not be replaced with inventory.

`trial.py watchdog-reset ATTEMPT` is a separate explicit abrupt-reset test.
It saves and releases PID1's runtime watchdog property, opens once, verifies
10-second timeout/zero pretimeout, fsyncs a nonce and keeps the descriptor
without pings. Surviving 20 seconds disarms/restores PID1 and records failure.
The boot wrapper invokes `trial.py watchdog-collect ATTEMPT` only when the
pending marker exists. Collection briefly releases PID1, reads bootstatus,
disarms and restores its property. Its durable consumed result is
`boots/<current-boot>/watchdog-reset/result.json`. Only a marker linked to the
journal's immediately previous boot with newly set `WDIOF_CARDRESET` passes;
missing reset cause blocks attribution. A consumed marker cannot pass another
boot, and a same-boot hook retry leaves an armed marker untouched.
