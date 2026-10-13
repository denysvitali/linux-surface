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
| `--capture` | Allow minimal bounded camera/microphone capture. An announcement is printed; data is discarded. Does not authorize speaker playback. |
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
Static Vulkan compares all 4,096 public-fixture pixels; it still does not close
the separate unresolved scrolling/partial-damage requirement.

Boot checks keep capture disabled and do not play sound. Cameras therefore
remain blocked without explicit capture authorization. Native microphone
stimulus, speaker output and parked audio lifecycle checks can remain blocked
even with `--capture`: that flag does not supply a stimulus, authorize playback,
or remove the parked DSP restrictions. Encoder trials remain blocked. Missing
`cam`, `ffmpeg`, `eglinfo`, `vulkaninfo`, GL/GLES render tools, `gtk4-rendernode-tool`,
`pactl`, or other feature tools are concrete blockers, not hardware absence.

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

`sensors.desktop-delivery` remains blocked by a validator dependency: the module
has no vendored Go D-Bus client, and separate `busctl`/`gdbus` call and monitor
commands cannot claim, receive signals and release on one persistent connection.
SensorProxy tracks claims by the caller's unique bus name; a short-lived claim
command cannot supply that session. No claim or service activation is attempted.
This is distinct from missing sensor hardware or backend support. Desktop
compass support and fresh compass delivery remain separately unverified.

A future client must use the already-owned system bus name
`net.hadess.SensorProxy`, root path `/net/hadess/SensorProxy` and compass path
`/net/hadess/SensorProxy/Compass`, disable activation, require HasAccelerometer,
subscribe before claiming and release on every path. Only a fresh
PropertiesChanged carrying AccelerometerOrientation within five seconds can
establish orientation delivery; cached properties cannot. No rotation or other
physical stimulus is requested. A stationary device may legitimately produce
no orientation change: require a fresh raw-reading path if exposed, otherwise
report blocked (`no stimulus; fresh delivery cannot be distinguished from a
stationary device`), never infer a delivery failure from silence alone.

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
- [ ] **camera.capture — Bounded capture** (functional; blocked): --capture not enabled
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
