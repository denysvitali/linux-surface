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
