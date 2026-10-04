# SPX QRTR handshake rollback trial — 2026-09-22

Trial `20260922g` uses `7.3.0-rc2-spx-mainline-20260922g+`. It reverses
commit `544d85de4dc22c01badfd8cefa59829ce35c4858` in `net/qrtr/af_qrtr.c`
and `net/qrtr/ns.c`. Both resulting files exactly match that commit's parent.
This restores the older name-server HELLO behavior for an isolated comparison
with F's announcement failure and modem crash about40seconds later.

This is a diagnostic rollback, not a general upstream fix. It removes proactive
initiation used by some passive MHI endpoints; this SPX config uses SMD and
has no QRTR_MHI. No failed-send errno was captured in F, and one clean boot
cannot resolve an intermittent timing hypothesis conclusively. See
[QRTR-20260922.md](QRTR-20260922.md) for evidence and limitations.

Relative to F, configuration changes only LOCALVERSION. Retain the A680 GBIF
fix, CMAC, normal UINPUT, exact DTB and userspace settings. Audio remains at
`slim_qcom_ngd_ctrl.spx_probe_stage=1` with `spx_pin_after_qmi=1`; do not advance
it or unbind/unload its pinned stack live. The separately proposed IPv6 MARK
configuration correction is absent from G. The entry retains graphical.target,
GPU policy isolation and a600-second diagnostic return window.

Preboot is retained F, ID `9ed25de5-fecb-499d-8ef6-c4f4ca29d08c`. Its scoped
813.84-second desktop/input/audio result explicitly records the modem fault;
result SHA-256 is
`54d7f2edb1dda75ede9d4e07a453ceaea3be1cf86da97b12edd9ff93fdbe4036`.
See [RESULT-20260922f.md](RESULT-20260922f.md). Preserve known-good as the
persistent default and select G only once after all artifact checks.

All89 diagnostic tests pass, including35 continuation tests. The conditional
Happy startup gate waits at most180seconds for server DNS/TCP only on a new,
explicitly armed matching boot. Unarmed boots do not wait; timeout still permits
normal daemon startup. This is intended to avoid the stale-session restore race
observed on F. Installed unarmed and same-boot no-ops passed; no live daemon
restart occurred. Actual automatic prompt delivery remains unverified.

Full archive destination:
`/var/lib/spx-boot-diagnostics/attempts/20260922g/`.
Staging: `/var/tmp/spx-mainline-trial-20260922g.c1lt_874/`.
Read current attempt.json, reboot-requested and GRUB state before any reboot;
this preparation record does not prove G booted. Collect its first modem start,
announcement errors, fatal count, firmware-transfer/ath10k timing, Wi-Fi and
continued graphics/input/audio-control behavior through>=600seconds. Preserve
all journals and hashes before choosing the next trial.

## Verified packaged artifacts

All187 modules have matching G vermagic; embedded config and initramfs MSM/logger match. Staged depmod is clean.

| Artifact | SHA-256 |
| --- | --- |
| vmlinuz | `90aaa0d4373cfd714f7bb259240c07586304eded5f0dd0434b2ee04c42e63004` |
| initramfs.img | `3ca1a3a637efa82ba69fa4ed65f141e9ad83a918c9c86f0061836c28103886ba` |
| artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |
| artifacts/drivers/gpu/drm/msm/msm.ko | `cbe21493c43cd988677235b656f4e3342b6fe4b4a69f0221e86a579bafbe58e9` |
| artifacts/drivers/input/misc/uinput.ko | `1486f59412783c219717620ea54109ea30e22c49a118525478a7ff90f416440f` |
| artifacts/crypto/cmac.ko | `41f59126188acc751603b9756f30418764cfad647ea7e6becef709c8048f3345` |
