# SPX audio stage 5, step 2 — trial O, 2026-09-22

O tests the isolated interrupt-status-clear sequence on a fresh boot with
the exact L kernel, modules, DTB and initramfs used by N. The release remains
`7.3.0-rc2-spx-mainline-20260922l+`; the boot slot remains
`/boot/spx-trial-20260922l/`. No rebuild or installation is needed.

[N's completed result](RESULT-20260922n.md) covers 616.08 seconds, with 292
result files hash-verified before stopping the fallback. Stage 5, step 0
completed its six reads with INT_STAT and INT_EN both zero, printed the
no-writes marker, and stopped. Graphics, Wi-Fi, modem and DSPs remained
healthy. Touch reached ready with zero errors and IPTSD stayed active with
no restarts; physical input and intermittent reliability remain unverified.
N performed no recovery return and did not establish audio transport.

The [step-2 source review](AUDIO-STAGE5-STEP2-20260922.md) supports this next
PIO-relevant boundary. Step 1's RX timeout write is deliberately omitted:
the eventual PIO path skips it, and the diagnostic cases are noncumulative.
This does not validate that omitted write. Step 3's nonzero INT_EN write
remains excluded because of the historical delayed reset.

The ordered command line changes only:

```diff
-spx_attempt=20260922n
+spx_attempt=20260922o
-slim_qcom_ngd_ctrl.spx_stage5_step=0
+slim_qcom_ngd_ctrl.spx_stage5_step=2
```

Stage 5, pinning, startup diagnostics off, all guards and runtime policies,
and the 600-second window remain unchanged. This path performs nine
synchronous 32-bit reads and one INT_CLR write. QMI still changes firmware
state beforehand. Preserve the common stage-5 values, the pre-clear status,
the final status, the explicit stop and child enable completion.

The actual write operand is a separate, unlogged status read. It cannot be
inferred from the preceding printed value, even when every printed value is
zero. The final read observes INT_STAT, not INT_CLR. A successful result
establishes completion of this isolated sequence with its observed values;
it does not prove acknowledgment of a pending interrupt or a working audio
transport. Preserve unexpected values without live corrective writes.

Origin boot: `49e88055-f682-4317-9f81-41cc9cf51dbf`.
N result SHA-256:
`d56fc12297222aa12f182f292d03cdb9c0a3b7b722e615cfa062e8969018d092`.

| Artifact | SHA-256 |
| --- | --- |
| Kernel | `8d5703cb36ddbc0679a93e54d1159c2f6bea6acc06b3def119e323be0bbf6e85` |
| Initramfs | `9c09fcec33e5f5ac1b04d5f071354957ef1deba5468dffa73f4a0f938cc3c391` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |

Preserve O's complete source/config/build archive, rehash all installed
modules, payloads, recovery artifacts and runtime policies, and keep
`spx-known-good` as the persistent default. Recheck boot ID and pending
GRUB/EFI selectors immediately before selecting O once. On continuation,
check identity, uptime and return timers first. Arm a 20-minute replacement
before stopping the original timer when extending observation. Archive and
hash the actual >=600-second result before stopping the replacement or
selecting another experiment.

Keep all effective guards and child runtime suspension verified. No live
stage change, forced resume, pinned-module unload/rebind, ADSP restart or
live MSM rebind. No soundcard or playback is expected yet. Pre-kernel
automatic recovery remains unvalidated; the user has authorized these boots.
