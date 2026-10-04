# Q: bounded PIO capability waiter

Q is prepared on known-good boot `c3c06c11-b245-443b-8bb1-263e58f6650f`.
No boot was selected during preparation. It reuses P's exact kernel, 187
modules, DTB and initramfs with release
`7.3.0-rc2-spx-mainline-20260922p+`. Q's 985-file private build copy and
202 installed module-tree files were rehashed with exact manifest coverage.
The build manifest SHA-256 is
`84df0c3afb1e75bf374f8f5027285f412539d948c860648ee40541c8cb96447e`.
P's recovered result manifest is
`f8c877eca2f9ed6c83eda59e38096fadce8823f36813488fa409da2814f37550`;
its final collector was at 1315.07 seconds before the scheduled return.

Only two ordered kernel command-line tokens differ from P:

```text
spx_attempt=20260922p                    -> spx_attempt=20260927q
slim_qcom_ngd_ctrl.spx_stage7_step=6      -> slim_qcom_ngd_ctrl.spx_stage7_step=7
```

Stage 7, step 7 adds the five-second `reconf` capability waiter after the
same QMI request, CFG enable, RX poll thread and possible reactive
REPORT_SATELLITE response that P exercised. Proactive retries remain zero.
DMA, nonzero NGD interrupt enable and full controller registration remain
disabled. A specific capability-DONE or timeout marker classifies the result;
the outer probe can report success even after a timeout. This does not test
soundcard registration, codec traffic or playback.

The existing 600-second return timer is excluded for Q by an exact kernel
command-line condition. A Q-only service automatically collects and hash-checks
the result at 620 seconds, with its service timeout set to 180 seconds. A
Q-only 900-second fallback returns to known-good if that service fails or the
scoped capability and graphical baseline does not pass. The finalizer stops
the fallback only after atomically publishing and verifying the result archive.
The preparation and read-only verifier passed before boot selection. The
new scripts and unit files are hash-pinned in Q's attempt manifest.
The separate queue/timer reviewer also passed before selection. Native Happy
continuation is enabled for this thread; Q's automatic result collector does
not depend on that continuation.

The installed kernel SHA-256 is
`dd6428bb9627b5bbff130b4b537663c7550ad1ce9a353caa6381aefa3fcd4d65`;
initramfs
`ed82fa0ed659fd1163682114f6be5f45c37fadec63b6da873f4402c557736f68`;
DTB
`5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5`.
The three known-good recovery hashes remain pinned in Q's manifest. The
persistent default is `spx-known-good`, with no GRUB `next_entry` or EFI
BootNext before selection. Q's entry references the P payload paths; it
does not add another `/boot` payload copy.

The queue helper is one-shot and refuses an existing `reboot-requested`
marker. Its scheduled reboot helper rechecks boot ID, pending Q entry,
known-good default and payload/recovery hashes immediately before requesting
the reboot. A failed check clears a still-pending Q selection on the same
origin boot. Neither helper should be replayed after a request marker exists;
inspect the state first. Automatic recovery from an EFI or early-kernel hang
remains unvalidated despite the user's authorization for this experiment.
