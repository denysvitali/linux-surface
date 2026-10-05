# Recovery GNSS: control works, no fix; modem cannot go online

Boot `42ff58a1-4cab-474f-b744-7c3c8332ae36`, recovery kernel
`6.18.3-1-surface+`. This tests a prerequisite for N03/N04; it is not mainline
acceptance. No kernel, firmware, SIM configuration or boot selection changed.

**Observed:** QRTR advertises LOC service16/version2 on modem node0/port70,
as in mainline G. Operation mode is `standalone`; engine lock is `none`.
A single proxied LOC client was kept alive for session23 START, position/SV
monitoring and STOP. During60seconds, reports comprised60 `in-progress`, one
`general-failure` and no successful fix or satellite list. STOP returned success,
the final report was `user-ended`, and the client released/exited successfully.
Location collection was announced and raw reports retained privately.

**Radio prerequisite:** DMS reports `factory-test`, hardware restricted `no`.
One standard request for `online` fails with QMI52 `DeviceNotReady`; readback
remains `factory-test`. Do not attribute the missing fix solely to indoor
reception or SIM absence. The cause of the rejected transition is not proven.

**Provisioning finding:** rmtfs, pd-mapper and tqftpserv are active. Installed
`rmtfs-dummy-git` owns five2MiB modem backing files, all zero-filled. Its service
uses `rmtfs -r -s -o /var/lib/rmtfs`. These are deliberate WLAN bootstrap
placeholders, not evidence of cellular calibration/provisioning. The firmware
server serves SC8180X MCFG files; missing `mcfg_hw/oem_hw.txt` alone is not a
diagnosis. No backing file, service or modem configuration was replaced.
The [SPX Wi-Fi instructions](https://github.com/linux-surface/surface-pro-x/wiki/WiFi#changes-required-for-the-surface-pro-x)
document this dummy-file workaround; [EFS issue2](https://github.com/linux-surface/surface-pro-x/issues/2)
leaves the real storage path unresolved. No same-device EFS backup or validated
restoration procedure was found in local findings. Missing real EFS is a
prerequisite to investigate, not a proven cause of this QMI error.

**Meaning/next:** LOC control and cleanup work on recovery; real positioning
does not yet work. Resolve the same-device modem provisioning/online prerequisite
before another GNSS reception attempt. Cellular additionally needs the absent
IPA/RMNET host data path and a usable SIM/service. N03/N04 stay open; no boot is
justified to repeat these unchanged prerequisites.

Evidence: `/var/lib/spx-boot-diagnostics/recovery/20261005-42ff58a1-gnss/`:
`control.json`, `session.json`, `modem-mode.json`, `online-transition.json`,
`rmtfs-shape.json`, private reports and service/kernel logs. Device lock released;
known-good remains default and no next entry is selected.
