# SPX startup logging control M — 2026-09-22

M reuses the exact L kernel, modules, DTB and initramfs. The release remains
`7.3.0-rc2-spx-mainline-20260922l+` and boot files remain under
`/boot/spx-trial-20260922l/`. Only the attempt marker and
`spi_hid.startup_diag=1` to `0` change in the command line. Audio remains
stage 4, with every guard, pinning and runtime policy unchanged. No rebuild,
module replacement, power/reset/IRQ change or descriptor bootstrap is part
of this control.

[L's completed result](RESULT-20260922l.md) covers 629.82 seconds. It had three
successful startup windows, 64 bounded metadata records, no fallback polls,
no invalid headers and no daemon retries. IPTSD created virtual touch and
pen devices and stayed active. Graphics, Wi-Fi and remote processors remained
running; audio stage 4 returned its expected values and stopped. Its 283-file
result was hash-verified before stopping the fallback; no recovery return
occurred. Physical input remains unverified.

[The trace review](TOUCH-L-REVIEW-20260922.md) found that early interrupts
while software considered the device unpowered were followed by normal
reset responses approximately 139 ms after reset deassertion. The
`irq-enabled` field can lag the actual enable operation. These observations
do not justify retaining early IRQs or changing delays. Logging can affect
timing; one successful L boot does not establish an intermittent-failure fix.

M tests whether clean startup repeats without diagnostic logging. A failure
must retain its chronology and is not permission to re-arm the same image
blindly. A success is one additional observation, not proof of reliability.
Verify the effective parameter is `N`, mode 0444, and that no
`startup-diag:` records appear. Check HID/IPTSD publication, retry count,
driver/SPI errors, virtual devices, audio guards and system health.

The preboot is L, ID `90f1a5fc-5a70-4bd5-8d7d-99e45039b007`. Its immutable
result SHA-256 is
`4f7c265f10b586e65c7836d376c4a3c8c081a61b68e0bcc2000cb873c228625d`.
M preserves its own complete copied build/provenance archive, entry and
manifest. Installed payload hashes are unchanged:

| Artifact | SHA-256 |
| --- | --- |
| Compressed kernel | `8d5703cb36ddbc0679a93e54d1159c2f6bea6acc06b3def119e323be0bbf6e85` |
| Initramfs | `9c09fcec33e5f5ac1b04d5f071354957ef1deba5468dffa73f4a0f938cc3c391` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |

Keep `spx-known-good` persistent default and recheck boot identity, all
payload/module/recovery/runtime hashes and pending GRUB/EFI selection before
selecting M once. Native Happy continuation remains enabled. On continuation,
check identity, uptime and timers first. Arm a replacement fallback at least
20 minutes away before stopping the original 600-second timer if needed.
Observe at least 600 seconds and hash the result archive before retaining
mainline or selecting another experiment. No live display or audio rebind,
forced NGD runtime resume, stage change or ADSP restart. Pre-kernel automatic
recovery remains unvalidated.
