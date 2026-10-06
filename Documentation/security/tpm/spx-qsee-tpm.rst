.. SPDX-License-Identifier: GPL-2.0-only

Surface Pro X QSEECOM TPM
========================

The driver is based on Xilin Wu's primary tree:
https://github.com/strongtz/linux-radxa-qcom/blob/13ee95f997f07e1442c3d68479ea9239854cf450/drivers/char/tpm/tpm_qcom_qsee.c

The retained SurfaceProX_tree INF enables the preloaded ``qcom.tz.tpm`` app.
Offline decoding of its QcTrEE8180.sys confirms QUERY_INFO_2 (0x4012) with a
four-byte request and packed twelve-byte response: LE32 NV-store size, then
LE64 control address. SEND_COMMAND (0x4008) uses a 1032-byte request and a
1028-byte response. Unlike the source driver, Windows sets input_size to
1024 even when the input bytes are zero; this port follows Windows.

Live named-app lookup returns app ID 1. QUERY_INFO_2 returns NV-store size
16384 and control address 0x9ffda000. The three-page area lies inside the
reserved iomem range 0x9ffb0000..0x9fffffff. The driver checks the board and
returned address, rejects System RAM overlap, claims the resource and
requires a covering reserved parent before mapping it. Probe failures and
removal release the lease, mapping, optional SHM bridge and memory pool.
The original packed 48-byte CRB control layout and buffer placement are
retained; a complete Windows control-layout comparison remains unverified.

No new SCM TPM-type query or global TZMEM mode change is needed. Generic
TZMEM makes SHM bridge creation a no-op. The original TPM core automatic
startup is retained: self-test, conditional Startup and session setup;
there is no Clear or ownership-reset command in this driver. Registration
therefore sends commands and is not a metadata-only test.

On CS boot a0a7c1af-7a7a-445b-9f47-df3e7c48d242 with kernel
7.3.0-rc2-spx-mainline-20261004bg+, bounded standard commands report TPM2.0,
manufacturer QCOM, active PCR banks and a nonzero SHA256 PCR0. Two GetRandom
requests each return32 distinct nonzero bytes. Removing the owned auxiliary
client releases the device and resource; reattachment repeats the pass with
unchanged PCR0/update counter. No ownership or persistent object is changed.
Signing/Secure Boot and
suspend/resume remain unverified. See RESULT-20261006cs-tpm.md and the bounded
public command client in tools/spx/tpm/check.py.
