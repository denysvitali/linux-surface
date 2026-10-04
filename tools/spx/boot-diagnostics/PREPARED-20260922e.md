# SPX CMAC and extended graphical validation — 2026-09-22

Trial `20260922e` retains the A680 GBIF correction that passed
[D's graphical test](RESULT-20260922d.md). The kernel configuration changes
only `CONFIG_CRYPTO_CMAC=m` and the release name, now
`7.3.0-rc2-spx-mainline-20260922e+`. Kernel source is unchanged from D.

CMAC addresses iwd's missing crypto prerequisite. D already associated Wi-Fi
through NetworkManager/wpa_supplicant and acquired a DHCP lease. The network
backend remains unchanged; both daemons also run on known-good 6.18. Capture
their behavior instead of treating iwd startup as proof of Wi-Fi stability.

The trial retains `graphical.target` and `spx_gpu_profile=skip`. Its additional
`spx_diag_window=600` marker skips the ordinary 180-second timer and enables
the ten-minute return timer. Both use the existing guarded return service.
Without that marker, other diagnostic boots retain the three-minute window.
The E-only user service records `eglinfo -B -p wayland` after 90 seconds.
Periodic evidence includes crypto providers, iwd state, wireless interfaces,
NetworkManager devices, GPU governor and cached SMEM data.

## Verified payload

Image, DTB and all 186 modules built. Embedded config matches, staged and
installed depmod are clean, and initramfs contains the exact rebuilt MSM
module and enabled initrd logger. CMAC module vermagic matches the release.
All 63 diagnostic tests pass, including 21 continuation tests. Timer and
renderer-check units pass systemd verification.

| Artifact | SHA-256 |
| --- | --- |
| Compressed kernel | `66dadcf279f46d17f9f4dcacf6f2ef33965e4bebda6ba4706ba508a660ac7aea` |
| Initramfs | `73bbd97a243ac6e1b968af79f766e62f7703c9c7d9168928ba9febcaaeaa975a` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |
| CMAC module | `f6e4a674065635c62e689783a64e2422ca750da1391c2fcba7cfab9ccc11af36` |

Full source/config/artifact/module/log archive:
`/var/lib/spx-boot-diagnostics/attempts/20260922e/`. The D boot slot was
archived and hash-checked before reclaiming its space for
`/boot/spx-trial-20260922e/`. All known-good artifact hashes remain unchanged.
Preboot recovery ID is `6394d00d-4cc0-4f01-9239-8de02fa4ae93`.

Read `attempt.json` and `reboot-requested` before any boot action; this
preparation record does not establish runtime success. Keep `spx-known-good`
as persistent default, use E once and preserve trial/recovery evidence.

The continuation helper now uses Happy's own local daemon session launcher,
which supplies RPC/session credentials. It checks server DNS/TCP before a
durable request claim and will not repeat an ambiguous spawn request.
Actual automatic delivery remains unverified before this boot.

Update after the user manually continued on the retained E kernel: no E
recovery boot occurred, and the recovery-only service was correctly skipped.
The stale continuation marker was archived and removed, and the user unit
disabled without stopping any session. See
[CONTINUATION-20260922e.md](CONTINUATION-20260922e.md) for evidence and the
next recovery procedure. Automatic recovery continuation remains unverified.

The board fragment's newly added `CONFIG_INPUT_UINPUT=m` is for a future
build and is absent from E. It addresses C's proven `/dev/uinput` omission;
SPI-HID transport timeouts remain a separate issue. The proposed QRTR modem
experiment in [QRTR-20260922.md](QRTR-20260922.md) is also not included in E.
