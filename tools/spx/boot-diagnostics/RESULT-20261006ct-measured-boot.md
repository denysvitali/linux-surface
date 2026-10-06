# CT: firmware and GRUB measurements match the live TPM

Boot `b56c1e85-0913-4327-aade-233064c8b45a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Changed:** no hardware or boot configuration change. The new bounded
read-only client parses the TCG2 log exposed by the working TPM driver and
replays recorded digest extensions into software PCR values. Layout follows
`include/linux/tpm_eventlog.h` and the
[TCG firmware profile](https://trustedcomputinggroup.org/resource/pc-client-specific-platform-firmware-profile-specification/).
It ignores informational EV_NO_ACTION records and handles StartupLocality;
dynamic/resettable PCRs are outside this test.

**B06c passes:** Linux exposes a 17,345-byte firmware log with70 events.
All ten recorded SHA256 static PCRs0–9 exactly match fresh public PCR_Read
responses from `/dev/tpmrm0`. GRUB file events in PCR9 contain the CT kernel,
initramfs and DTB; each logged digest matches its actual `/boot` payload.
PCR8 also records GRUB commands and the kernel command line. No PCR write,
reset, TPM provisioning, key enrollment or EFI variable change is performed.

**Verification:** two live command opens already passed on CT. This client
exits0 for the real log and payloads. Empty, short-header and truncated-final
logs are rejected; a missing payload event returns incomplete/exit1. No
malformed input is sent to firmware. Sensor services retain zero restarts.

**Meaning/next:** firmware and the existing GRUB path measure the actual
kernel/initramfs/DTB, and Linux can verify/read those measurements. This does
not prove signature enforcement or firmware trustworthiness. SecureBoot0/
SetupMode1 remains the observed state. Signing/Secure Boot and resume still
leave full B06 open; systemd's optional UKI/PCR barriers are not enabled by
the current GRUB boot. Preserve ownership and the recovery boot path.

Evidence: `/var/lib/spx-boot-diagnostics/functional/20261006ct/tpm/`,
`firmware-eventlog.bin` and `measurements.json`; reproducible client
`tools/spx/tpm/measurements.py`.
