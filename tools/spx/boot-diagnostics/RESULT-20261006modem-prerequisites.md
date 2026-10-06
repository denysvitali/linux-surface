# Modem prerequisites: real backing storage remains unresolved

Recovery boot `c13e793b-9cfc-49ce-b4c2-fa1d2df6d151`,
`6.18.3-1-surface+`. Read-only prerequisite check; no cellular/GNSS test.

**Observed:** modem remoteproc runs; no WWAN interface. Installed
`rmtfs-dummy-git` supplies five2MiB files, each currently all zero, to the
active `rmtfs -r -s -o /var/lib/rmtfs` service. The only visible disk is NVMe,
with an ESP and a LUKS/LVM Linux root. No Windows volume is mounted.

**Storage path finding:** retained `qcremotefs8180.sys` references
`/boot/modem_fs1`, `modem_fs2`, `modem_fsc`, `modem_fsg` and consumes the
SocPartition provider. `QcSOCPartition.sys` exposes
`\\DosDevices\\QcSOCPartitionDevice`, walks GPT-style entries/names and formats
Windows `\\Device\\Harddisk%u\\Partition%u` paths. Its DriverStore package is
a block-partition lookup implementation, not a device-specific EFS backup.
Captured SQ2 DSDT defines SOCP/QCOM04AA with STOR0; the actual physical storage
interpretation remains unproven. Narrow inspection of the retained Windows
files found no same-device backup or validated restoration procedure. The
official SPX EFS issue still leaves the QSPI hypothesis unestablished.

**Meaning/next:** identify the fitted SOCP→physical disk→named modem partition
mapping, or obtain a verified backup from this device. Do not substitute donor
EFS, reset calibration or replace the Wi-Fi bootstrap backend. Missing genuine
backing is a plausible prerequisite, not a proven cause of `DeviceNotReady`.
Avoid unchanged online/LOC retries; IPA/RMNET and usable SIM/service also remain
required. N03/N04 stay open. No source, service, storage, radio mode or boot
selection changed; device lock released.

Sources: [prior GNSS result](RESULT-20261005-recovery-gnss.md), retained
`Documents/drivers/FileRepository/qcremotefs8180.inf_arm64_8a629fd5db8bab22/`
and `qcsocpartition.inf_arm64_ab0ef651cc2c31ea/`, SQ2 DSDT,
[official EFS issue](https://github.com/linux-surface/surface-pro-x/issues/2).
