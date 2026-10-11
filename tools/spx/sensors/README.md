# Surface Pro X SensorsPD startup

This opt-in service retains the first SensorsPD listener for the entire desktop
session. It runs with `spx_sensors=1` or the explicit persistent baseline opt-in
below, keeps the secure FastRPC device private to root, and does not retry attachments. A libssc metadata probe gates systemd
readiness; a systemd generator adds proxy dependencies only on opted-in boots.
The scoped udev rule adds the missing `ssc-accel` discovery tag; the existing
iio-sensor-proxy rule pulls in the proxy. No sensor stream or desktop policy
claim is made by the probe. A listener exit, even status zero, fails the service
and stops the dependent proxy.

The configuration is the retained Surface Windows vendor JSON and six socinfo
files used for the successful CN accelerometer/gyroscope streams. The daemon
serves them read-only. Upstream 0.5.0 rejects registry writes; calibration does
not persist. Writable calibration, mount-matrix interpretation, physical
rotation and suspend/resume remain separate work.

Coordinator preparation (after integrating this commit):

```sh
cc -Wall -Wextra -Werror tools/spx/sensors/ready.c $(pkg-config --cflags --libs libssc) -o /var/tmp/spx-sensors-ready
sudo python3 -B tools/spx/trial.py prepare ATTEMPT --sensors \
  --sensors-config /var/tmp/spx-sensors-config \
  --sensors-daemon /var/tmp/spx-hexagonrpc/build/hexagonrpcd/hexagonrpcd \
  --sensors-library /var/tmp/spx-hexagonrpc/build/libhexagonrpc/libhexagonrpc.so.0.5 \
  --sensors-ready /var/tmp/spx-sensors-ready OTHER_TRIAL_OPTIONS
sudo python3 -B tools/spx/trial.py install ATTEMPT
```

Installation enables the fixed service for the next opted-in boot; it never
starts or restarts either daemon on the current boot. The private library layout
preserves the daemon's `$ORIGIN/../libhexagonrpc` RUNPATH. No global library search
path changes are needed. Check service readiness and the ordinary GNOME proxy
properties after boot. Keep polkit's desktop claim policy intact.

Offline tests: `python3 -B tools/spx/sensors/test_supervise.py` and
`python3 -B tools/spx/test_trial_sensors.py`.

## Persistent baseline opt-in (WIP, not deployed)

The generator also accepts `/etc/spx/sensors-enabled`, containing `private`
for the installed private libssc or `system` for the system library. This is an
explicit coordinator opt-in, not a default. It applies only to promoted boots
with `spx_baseline=...`; `spx_sensors=0` disables it. Recovery and ordinary
trial boots ignore the file. Trials keep their existing command-line library
selection. No microphone source, recording or speaker action is added.

Before opting in, confirm the promoted DTB exposes the working SLPI/SDSP
backend and ownership lease, and the installed vendor configuration, daemon,
readiness binary and chosen library match the CO/DD working stack. A file
cannot repair a missing DT backend or firmware contract. Install this generator
through the existing sensor staging path; do not restart the retained listener
merely to update its files. For the next ordinary baseline startup, the generated
unit override replaces the trial-only condition, queues the provider and keeps
the proxy bound to its real readiness. Startup failure still has `Restart=no`;
automatic reset/recovery remains separately trial-opted-in and unvalidated.

Remove the file or use `spx_sensors=0` to opt out on the next boot. Removal is
not an instruction to stop live SensorsPD or SLPI. Coordinated same-boot
activation requires exclusive device ownership, confirmed absence of an old
attachment and the established backend prerequisites; do not automatically
restart either service. Expected functional check: provider reaches READY once,
the initial host remains retained, and the desktop exposes motion/compass to an
ordinary seated client without recovery or new DSP faults. Physical axes and
calibration still need the user.

TCS3430 exposes X/Y/Z/IR channels, not a verified lux conversion. Existing
BW evidence had all-zero channels and no physical light stimulus. This change
does not invent a lux source or close S01. Microphone integration remains
explicitly opt-in under the existing audio policy; this service never captures.

## Private libssc matrix compatibility fix

`libssc-0.4.4-matrix.patch` replaces the integer-sum fallback test with complete,
finite, orthonormal 3x3 validation. Invalid matrices are completely cleared before
identity fallback. Valid signed and fractional rotations are preserved byte for
byte. Both handednesses are accepted; no board axes or placement layout change
is inferred. Identity fallback is a compatibility policy, not verified axes.

The helper header is shared by the source patch and standalone offline tests:

```sh
cc -std=c99 -Wall -Wextra -Werror tools/spx/sensors/test_matrix.c -lm -o /var/tmp/spx-test-matrix
/var/tmp/spx-test-matrix
cp tools/spx/sensors/spx-matrix.h /var/tmp/spx-libssc/src/spx-matrix.h
git -C /var/tmp/spx-libssc apply "$PWD/tools/spx/sensors/libssc-0.4.4-matrix.patch"
git -C /var/tmp/spx-libssc apply "$PWD/tools/spx/sensors/libssc-0.4.4-build.patch"
meson setup /var/tmp/spx-libssc/build /var/tmp/spx-libssc
ninja -C /var/tmp/spx-libssc/build src/libssc.so.2 src/ssccli
```

The separate build patch guards optional GIR generation when g-ir-scanner is
absent. The installed system library is untouched. Stage the private library by
adding `--sensors-ssc-library /var/tmp/spx-libssc/build/src/libssc.so.2` to prepare.
The generator exposes it only to the SensorsPD readiness helper and desktop
proxy when both `spx_sensors=1` and `spx_sensors_libssc=private` are present.
A bounded CLI can use `LD_LIBRARY_PATH=/var/tmp/spx-libssc/build/src` directly.
The coordinator can test a proxy-only runtime override on the current opted-in
boot without restarting the retained initial SensorsPD listener. Do not restart
that listener merely to change the desktop library.

Opt-in automatic failure recovery (WIP): prepare with `--sensors-crash-recovery`
and the existing `--sensors --sensors-ssc-library PATH`. This adds
`spx_sensors_recovery=1` and queues one post-baseline test. It cannot be combined
with audio, CDSP or thermal testing. The provider still has `Restart=no`.

Only a verified retained host's unexpected exit after READY creates an eligible
current-boot witness. Initial failure and intentional service stop do not.
`spx-sensors-recovery.service` acquires the exclusive device lock and reserves
one attempt per boot before stopping owned services and SLPI. It starts SLPI
again only after fresh `channel remove users=0 pending=0` and final HLOS heap
restoration `owners=0x8` evidence. Missing proof keeps the backend stopped;
there are no retries, forced references, module reloads or host-only reattach.
Fresh shared ownership `0x28`, a changed host and a changed private-library
proxy are required. Outside the harness, the old proxy identity comes from its
owned unit's retained `ExecMainPID`; an observer marker is optional and stale
markers refuse a lock handoff. Recovery requires the current patched lease,
firmware, prepared attempt, failed provider and at least 300s automatic-return
reserve, and is bounded by a 180s helper deadline/200s unit timeout.

The queued test requires actual active/unlocked UID1000 Wayland seat0 and keeps
polkit unchanged. It observes real orientation and three finite heading updates
before one pidfd SIGKILL of the verified SensorsPD child. It observes the actual
OnFailure unit, then requires finite accelerometer/gyro/magnetometer streams
with clean disable and fresh UID1000 orientation/heading delivery across client
close/reopen. Client logs use monotonic timestamps. Old-client continuity is
explicitly unproven. A result directory prevents automatic test retry, including
an interrupted run. Native delivery and clean owned-client cleanup are required;
metadata readiness alone cannot pass. Live acceptance remains unverified until
the coordinator runs this feature on the trial kernel.
