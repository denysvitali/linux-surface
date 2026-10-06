# CS: firmware TPM capability, PCR and GetRandom work

Boot `a0a7c1af-7a7a-445b-9f47-df3e7c48d242`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Changed:** an external module calls the existing QSEECOM named-app lookup.
Its opt-in metadata query uses the4-byte `QUERY_INFO_2` request and12-byte
response corroborated against the retained Windows `QcTrEE8180.sys` and the
[existing legacy driver](https://github.com/strongtz/linux-radxa-qcom/blob/13ee95f997f07e1442c3d68479ea9239854cf450/drivers/char/tpm/tpm_qcom_qsee.c).
No TEE configuration, boot image or global TZMEM mode change.

**Observed:** named `qcom.tz.tpm` lookup returns0/appID1. Metadata query
returns0, NV-store size16384 and control area`0x9ffda000`. The address matches
the retained SQ2 TPM2 table and UEFI reservation; live iomem reserved range
`0x9ffb0000–0x9fffffff` covers its three pages. Both query modules unload.
Sensor provider723/proxy1213 remain running with zero restarts.
UEFI reads return SecureBoot0/SetupMode1 through the retained QSEECOM provider.

**B06a passes:** the guarded legacy driver uses Windows SEND_COMMAND
input-size1024 and exclusively claims the three reserved pages before mapping.
Live auxiliary registration creates`/dev/tpm0` and`/dev/tpmrm0`; normal TPM-core
startup/self-test completes. A bounded standard client returns TPM2.0/QCOM
properties, SHA1/SHA256/SHA384 PCR banks, a nonzero SHA256 PCR0 digest and two
distinct32-byte GetRandom outputs. Client exits0 and closes its descriptor.
Removal deletes both class/auxiliary device and memory claim. Reattachment
passes the same commands again and preserves PCR0/update-counter91. No Clear,
PCR write, ownership/provisioning or persistent-key operation is performed.
Sensor services retain their PIDs and zero restarts; the working TPM is retained.

**Meaning/next:** fitted TPM commands work. B06 remains open for automatic
startup on the next kernel, signing/Secure Boot and measured-boot integration,
and resume. UID81 object discovery requires newer firmware; preserve QSEECOM.
Build the named auxiliary entry into the next image for ordinary startup.

Evidence: `/var/lib/spx-boot-diagnostics/functional/20261006cs/tpm/`,
`query-result.json`, `check-result.json`, `reopen-result.json` and kernel logs;
offline source/Windows ABI captures
are retained at`/var/tmp/spx-tpm-source/`.
