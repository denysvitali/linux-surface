# SPX top-level audio version-read trial I — 2026-09-22

I reuses G's kernel, all 187 modules, DTB and initramfs. The release remains
`7.3.0-rc2-spx-mainline-20260922g+`. Relative to H, only the attempt marker
and `slim_qcom_ngd_ctrl.spx_probe_stage=2` to `=3` change. No kernel rebuild,
camera, IPv6 MARK, loader or userspace configuration change is included.

H completed 865.10 seconds with a successful ACTIVE QMI power acknowledgment,
the expected stage-2 stop, suspended NGD child, unchanged guards and no observed
modem fatal, GPU fault or kernel oops. Desktop, EGL FD680, Wi-Fi and IPTSD were
active. Its 266-file result archive was hash-verified before stopping the
replacement return timer. No recovery return occurred. See
[H result](RESULT-20260922h.md).

Follow the [stage-3 source review](AUDIO-STAGE3-20260922.md). After the same
QMI handshake, stage 3 reads only the top-level NGD version register at
`0x171c0000`, logs it and stops before the child-register reads. Historical
6.18 evidence gives raw `0x02020000`, version `0x202`; unexpected values must
be preserved and investigated. The optional window dump remains disabled.
No soundcard or playback is expected at this stage.

Retain the pin and disabled DMA, INT_EN, full-controller, PIO, window-dump,
PDR-auto-enable and QMI-bypass parameters. Verify all effective values after
boot. Do not force runtime resume, change stages live, unload/rebind audio or
restart ADSP. The parent IRQ is enabled; the suspended child is the expected
ISR barrier after the power acknowledgment. This does not prove every MMIO
path is disabled. A register read can stall without a timeout; pre-kernel or
hang recovery is not established by this experiment.

Boot files remain in `/boot/spx-trial-20260922g/`. I has its own entry,
source/config/build/module archive and reused-artifacts record under
`/var/lib/spx-boot-diagnostics/attempts/20260922i/`.

| Artifact | SHA-256 |
| --- | --- |
| Compressed kernel | `90aaa0d4373cfd714f7bb259240c07586304eded5f0dd0434b2ee04c42e63004` |
| Initramfs | `3ca1a3a637efa82ba69fa4ed65f141e9ad83a918c9c86f0061836c28103886ba` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |

Preboot is retained H, ID `3af15a82-c6ed-4d5e-b165-b332e3869793`. Its pinned
baseline result SHA-256 is
`ec640e0ce3b3ed5fdb85ad13d67b1b2250229484b92e5e2d88752f0a6c823943`.
Keep `spx-known-good` as persistent default, check the boot ID and pending
selection immediately before reboot, and select I once. Read the request
marker and actual boot result before any later experiment; never re-arm I
blindly. Recheck recovery, boot and installed-module hashes before queuing.

The 600-second return timer and periodic evidence collector remain configured.
On continuation, inspect identity, uptime and timers immediately. If a longer
observation is needed, first arm a replacement fallback at least 20 minutes
away, then stop the original timer. Preserve at least 600 seconds of actual
stage-3/system evidence and hash the final archive before holding mainline or
choosing another trial. A preparation record is not a successful boot result.

Native Happy resumes this same Codex thread automatically with `continue`;
the redundant task helper and network gate remain absent. Preflight checks
the native flags, thread, path and running session process without retaining
credentials or message contents. The diagnostic test suite and G artifact
verification remain applicable because this trial changes only parameters.
