# Surface Pro X SensorsPD startup

This opt-in service retains the first SensorsPD listener for the entire desktop
session. It runs only with `spx_sensors=1`, keeps the secure FastRPC device private
to root, and does not retry attachments. A libssc metadata probe gates systemd
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
