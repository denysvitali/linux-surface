# SPX child audio register-read trial J — 2026-09-22

J reuses G's kernel, 187 modules, DTB and initramfs. The release remains
`7.3.0-rc2-spx-mainline-20260922g+`; only the attempt marker and audio stage
`3` to `4` differ in the kernel command line. Boot files remain under
`/boot/spx-trial-20260922g/`. J has its own complete copied build archive,
entry and manifest under `/var/lib/spx-boot-diagnostics/attempts/20260922j/`.

[I's completed result](RESULT-20260922i.md) covers 612.76 seconds. Its QMI
ACTIVE request succeeded, version read returned `0x02020000`/`0x202`, and
stage 3 stopped as intended. Audio guards and child runtime suspension
remained intact. Graphics, Wi-Fi and remoteprocs stayed running without
observed GPU, modem-fatal or kernel-oops faults. All 270 result hashes were
independently verified before the fallback was stopped. No recovery return
occurred.

I's IPTSD startup timed out at 30.307486 seconds. One ordinary daemon restart
at 239.088593 seconds recovered it; virtual touch and pen appeared at
239.321350/239.321448. Physical input remains unverified. After I's baseline,
a separate userspace mitigation was installed: `Restart=on-failure`, ten
seconds between retries, at most three starts in 120 seconds. This preserved
the healthy daemon's PID and passed merged-unit and systemd verification.
It has not yet been observed recovering a new spontaneous startup failure.
J explicitly includes this userspace difference; it is not evidence of a
kernel transport fix. See [TOUCH-STARTUP-20260922.md](TOUCH-STARTUP-20260922.md).

The installed retry file is
`/etc/systemd/system/iptsd@.service.d/90-spx-startup-retry.conf`, SHA-256
`1d638b6513e2b379e7a5e427ab3e0c657cd340a9eb24d84dd53851a9d0444270`.
Its before/after state and logs are in I's `touch-retry-policy/` supplement.

Follow [AUDIO-STAGE4-20260922.md](AUDIO-STAGE4-20260922.md). After the unchanged
QMI handshake and top-level version read, stage 4 reads child STATUS
`0x171c1004`, CFG `0x171c1000` and RX_MSGQ_CFG `0x171c1008`, in that order,
then logs all three and stops. Historical values are `0x40c`, `0`, `0`.
Preserve unexpected values for investigation. No soundcard, transport or
playback result is expected. A missing combined log cannot identify which
individual read stalled.

Keep pin-after-QMI enabled, window dumps and DMA/INT_EN/full/PIO/PDR/bypass
disabled, stage 5/6/7 steps zero, and the child's runtime-PM policy unchanged.
Verify effective values after boot. Never force runtime resume, access the
alternate `+0x2000` window, raise stages live, unload/rebind audio or restart
ADSP. The parent IRQ remains enabled and child suspension is its expected
access barrier. Read timeouts and pre-kernel automatic recovery are not
established by this test.

| Artifact | SHA-256 |
| --- | --- |
| Compressed kernel | `90aaa0d4373cfd714f7bb259240c07586304eded5f0dd0434b2ee04c42e63004` |
| Initramfs | `3ca1a3a637efa82ba69fa4ed65f141e9ad83a918c9c86f0061836c28103886ba` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |

Preboot is retained I, boot ID `90b986c6-2f3e-49be-9418-d212e37e9f9c`.
Pinned result SHA-256:
`82ae359833a08d7397f6648ed87990f256f1615d055f5856ad0ebec320870ee5`.
Keep `spx-known-good` persistent default; verify boot identity, recovery and
payload hashes, and pending boot selection immediately before selecting J
once. Check the request marker and actual result before any later experiment.

The 600-second return timer, periodic evidence collection and native Happy
continuation remain configured. At the next continuation, check identity,
uptime and timers first. If more time is needed, arm a replacement fallback
at least 20 minutes away before stopping the original timer. Verify at least
600 seconds of audio/system operation and hash the result archive before
retaining mainline or choosing another experiment.

The active source now has the separately build-tested CAMSS allocator Kconfig
fix. It is not in these reused artifacts, and camera config/DT remain
disabled. Offline camera binding drafts and IPv6 MARK work do not affect J.
