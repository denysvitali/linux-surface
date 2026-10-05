# SSAM late-probe workaround

`spx-ssam-startup.service` retries the known firmware-version timeout once after
uptime 30 seconds. This is a userspace workaround, not the startup root-cause
fix. It requires the exact Surface Pro X DT compatible, one Surface SAM serdev
child, an unbound controller and both matching current-boot kernel errors.
It takes the normal device lock without waiting or stealing, rechecks binding,
then writes the driver's bind attribute once. It never unbinds, resets a parent
or reloads a module. Healthy mainline startup does nothing.

Install `tools/spx/ssam_startup.py` and executable `tools/spx/spx-lock` together
in `/usr/local/lib/spx-boot-diagnostics/`; install this directory's
`spx-ssam-startup.service` in `/etc/systemd/system/`, then run
`systemctl daemon-reload` and `systemctl enable --now spx-ssam-startup.service`.
No kernel, DTB or initramfs changes are required. Disable the service to remove
the workaround. An existing attempt marker must not be removed to retry a
failed controller on the same boot.

Each outcome goes to the service journal. `/run/spx-ssam-startup/result.json`
records the result, and `attempt` prevents a second bind after service restart
or interruption. The bind subprocess has a 20-second timeout; the entire
service has a 75-second startup limit. These userspace limits cannot resolve a
kernel task stuck in uninterruptible sleep. A busy device lock means a logged
skip, with no automatic retry.

Check a healthy boot with `systemctl start spx-ssam-startup.service` and the
journal: expect `already_bound` and no bind attempt marker. On a naturally
recurring timeout, expect `bound` after exactly one late probe, then verify
SSAM children, keyboard/touchpad use and battery/RTC readout. Do not unbind a
working controller to manufacture the failure. The automatic recovery path
still requires validation on such a boot.

Offline: `python3 -B -m unittest discover -s tools/spx -p test_ssam_startup.py`.
