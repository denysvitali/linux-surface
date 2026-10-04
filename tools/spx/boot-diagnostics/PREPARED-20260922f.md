# SPX touch persistence and QMI-only audio trial — 2026-09-22

Trial `20260922f` uses `7.3.0-rc2-spx-mainline-20260922f+`. Relative to E,
only LOCALVERSION and CONFIG_INPUT_UINPUT=m change the kernel configuration.
Kernel code and DTB are unchanged. E's supplementary exact-build module
restored iptsd and virtual touch/pen registration; F includes uinput as a normal
in-tree module. Physical touch and pen movement remain unverified.

The audio command line adds `slim_qcom_ngd_ctrl.spx_probe_stage=1` and
`slim_qcom_ngd_ctrl.spx_pin_after_qmi=1`. This tests QMI SELECT_INSTANCE,
then stops before power requests and NGD register/DMA/PIO operations.
All other guards remain at their disabled defaults. A soundcard is not expected;
see [AUDIO-STAGE1-20260922.md](AUDIO-STAGE1-20260922.md) for boundaries.
No QRTR change is included. Retain E's GPU policy isolation and600-second window.

Image, DTB and187 modules built; embedded config matches. Staged depmod is clean;
initramfs contains the exact rebuilt MSM module and enabled initrd logger.
All83 diagnostic tests pass, including29 continuation and25 preflight checks.
The collector now records NGD parameters/refcount, audio-loader logs and input
service/device state. The delayed EGL user check applies to diagnostic mainline
boots. No actual F runtime result is implied by this preparation note.

| Artifact | SHA-256 |
| --- | --- |
| Compressed kernel | `5edbe17934a8a79842bcda5fc2ecdcf6b843da4f75eede8732bde7443bb3861d` |
| Initramfs | `9077077df54c7dbff58c298e7a73138b8f5c98bd5082593cc29d67c654922997` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |
| uinput module | `2c9618685674a10c89fc552ef49426bc9c520dfc2e1d3ae5285a504591d58cb4` |

Preboot is validated retained E, ID `1caa8c4c-0fa9-4986-9e3b-32bf1919cea3`.
Its827.19-second successful baseline result is pinned by SHA-256
`8bc60e4dbc9966faec3bfc79b80c236ab257545916295cfca8df5bb5ce3ab37c`.
Preflight accepts this specific archived provenance; ordinary unvalidated
mainline boots are still refused. The preflight command itself remains read-only.

The continuation marker explicitly names F's expected attempt and release;
the helper accepts matching new mainline boots or known-good recovery only.
The daemon launches the same session with its own credentials. This has passed
mocked tests but actual automatic prompt delivery is still unverified.

Full archive destination:
`/var/lib/spx-boot-diagnostics/attempts/20260922f/`.
Staging: `/var/tmp/spx-mainline-trial-20260922f.k099tnn7/`.
Keep spx-known-good persistent default and select F once. Before reboot read
attempt.json, reboot-requested and GRUB state. Collect F's result before choosing
any further experiment. If F is retained after a verified600-second window,
record that explicitly; do not claim an orderly recovery return occurred.
