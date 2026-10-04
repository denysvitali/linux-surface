# SPX QMI power-request trial H — 2026-09-22

H reuses G's verified kernel, all187 modules, DTB and initramfs without
rebuilding. Its release remains `7.3.0-rc2-spx-mainline-20260922g+`; the new
attempt marker is `spx_attempt=20260922h`. The only functional command-line
change is `slim_qcom_ngd_ctrl.spx_probe_stage=1` to `=2`.

G completed756.96seconds with one modem start and no announcement/fatal/GPU
errors, working Wi-Fi, normal UINPUT/IPTSD startup and guarded audio stage1.
See [RESULT-20260922g.md](RESULT-20260922g.md). H also observes whether that
clean modem startup repeats while testing the separately planned audio power
request. A single clean G boot did not settle the intermittent QRTR hypothesis.

Follow [AUDIO-STAGE2-20260922.md](AUDIO-STAGE2-20260922.md). Stage2 sends
ACTIVE (`pm_req=2`) with the optional response-type TLV omitted, then stops.
Success requires the decoded zero result/error, explicit stage2 stop and stable
ADSP/system observation. It must not reach later probe stages or produce a
soundcard yet. Retain pin_after_qmi=1 and disabled DMA/INT_EN/full/PIO/PDR/bypass
guards. A successful power response sets mmio_alive; the already-enabled Linux
IRQ line is still protected by the child's runtime-suspended check. Do not
claim that stage2 prevents every possible MMIO access. No live stage escalation,
unload or device rebind is authorized by this test procedure.

Boot files stay at `/boot/spx-trial-20260922g/`; H's separate GRUB entry and
attempt archive select that same payload once with the new parameters. The
complete build archive is copied under `attempts/20260922h/build/`, with its
original hash manifest and explicit reused-artifacts record.

| Artifact | SHA-256 |
| --- | --- |
| Compressed kernel | `90aaa0d4373cfd714f7bb259240c07586304eded5f0dd0434b2ee04c42e63004` |
| Initramfs | `3ca1a3a637efa82ba69fa4ed65f141e9ad83a918c9c86f0061836c28103886ba` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |

Preboot is retained G, ID `c17b7ebf-0dfd-47b7-a7d9-a5cddfa859db`. Its pinned
baseline result hash is
`7d651448b1e400f95922cb32191424d7afa7a98dfa60074d4f7c029d1dc01014`.
Known-good remains persistent default; artifact/recovery hashes and pending
selection are rechecked before queuing H. The600-second diagnostic return and
periodic logging remain configured. Read attempt.json/reboot-requested before
any action; this preparation record does not prove a boot or stage2 success.

Automatic continuation is the verified native Happy resume-on-daemon-start
path, configured to inject `continue` into the same Codex thread. The earlier
manual-input interpretation was wrong; see
[CONTINUATION-20260922g.md](CONTINUATION-20260922g.md). Redundant helper/gate
units were archived and removed without stopping Happy. H preflight rechecks
only whitelisted native metadata; it does not retain credentials or messages.
The G89-test diagnostic suite and artifact checks remain applicable; no kernel
or installed diagnostic code changes are introduced for H.

Read-only cellular GETs after G's baseline succeeded but reported factory-test
mode and absent SIM. Host IPA/WWAN/RMNET data support is also missing. No mode,
SIM unlock or data-session changes are part of H. The separate IPv6 MARK config
correction remains unbuilt. Physical input, audio playback, external display,
cameras and suspend/resume still require further port work and validation.
