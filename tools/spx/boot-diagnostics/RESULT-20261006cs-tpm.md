# CS: firmware TPM app and metadata confirmed; command path WIP

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

**Meaning:** the fitted firmware TPM is accessible through the legacy named
transport. This is metadata evidence, not TPM command acceptance. No control
area mapping/write, TPM startup/clear, ownership change or key creation occurred.
B06 remains open. UID81 object discovery needs newer firmware and is not the
supported route for this retained SPX firmware.

**Next:** port the existing legacy auxiliary TPM driver with the Windows
SEND_COMMAND input-size value1024, reservation/ownership guards and cleanup.
Then test standard capability, PCR-read and bounded GetRandom operations.
The original driver uses normal TPM-core startup/self-test, not Clear.

Evidence: `/var/lib/spx-boot-diagnostics/functional/20261006cs/tpm/`,
`query-result.json` and`query-kernel.log`; offline source/Windows ABI captures
are retained at`/var/tmp/spx-tpm-source/`.
