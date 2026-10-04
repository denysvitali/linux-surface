# AE: distinct kernel with eight bounded touch startup windows

AE is installed and independently reviewed from AD boot
`86c3ff68-09a9-480c-9288-be9443254378`, still running AA release.
Authoritative selection state is `/var/lib/spx-boot-diagnostics/attempt.json`.
Inspect actual boot identity and pending selection before acting; installation
does not prove AE booted or passed. Never blindly re-arm a failed attempt.

AD's frozen scope passed at620.22s, with native left attachment and final touch
readiness, but its separate review records a failed fourth open: gated IRQ,
no powered IRQ/report, three zero headers, timeout/open-110. A later ordinary
open succeeded after the four-window logger was exhausted. Read
RESULT-20260930ad.md and TOUCH-AFTER-AD-20260930.md. No live intervention or
playback/capture/PCM/input-event reads were performed.

AE changes only SPI_HID_DIAG_WINDOWS4->8 in the driver and LOCALVERSION.
The new lifetime ceiling is384 records (48/window); default-off0444 boolean,
format, event limit and terminal reservation are retained. No additional device
I/O, hardware reads, reset/power/IRQ/SPI/descriptor/timeout policy change.
More logging can affect scheduling; this is diagnostic coverage, not a fix.
The running AD/AA kernel still has the old four-window budget until reboot.

AE release `7.3.0-rc2-spx-mainline-20260930ae+` has a distinct kernel,187 modules
and private initramfs. Boot files are `/boot/spx-trial-20260930ae/{vmlinuz,
initramfs.img,spx.dtb}`. The rebuilt DTB is byte-identical to AB. Command-line
selectors exactly match AD apart from `spx_attempt=20260930ae`; logger1,
force/core/watchdog0, pin1, left2110/unique3, right2010/unique4, DSP and all
userspace policy remain unchanged. No audio or live reset/rebind is scheduled.

Archive `/var/lib/spx-boot-diagnostics/attempts/20260930ae` retains1,084 build
files/272 symlinks,202 module-tree files and15 AB DT/source files. Independent
build review proves the one-line driver delta, config onlyLOCALVERSION,
unchanged other source diff chunks, exact embedded config,187 AE vermagic
records, private logger and DTB identity. Installation review rehashed all
payload/recovery/runtime files,348 preboot snapshot files and13 deployment
scripts. Python syntax/global-name checks, GRUB syntax, systemd unit verification
and whitespace checks passed. AST comparison proves the entire AD baseline
predicate is unchanged; bounds alone become8windows/384records. The new parser
also accepts the archived successful L trace.

| Evidence | SHA256 |
| --- | --- |
| Build manifest | `dafc7606cb237397e8355a0814cebe6a31e517d5a354c3193adba0b091dc8b0e` |
| Independent build review | `011107fa8bb337cc75e683f130777db679a416dc509af57449fdbda03bcb749b` |
| Module manifest | `716e1a002137f99d881c49370075706225b36b1030b5fc82f7106f30e077a086` |
| Kernel | `19c73c8f09e10bee6775054ca02207cb88977545d2295f4f4122a7adc0bb467e` |
| Initramfs | `ede71367894468ff2ab888c10a59c39439b826761dd4fd9df085188ac8bdfcda` |
| DTB | `97983ecc8fc9a940787e6550071b03d1d8b63ccee00e75f2d10f452f82d7a187` |
| Installation review | `4cacd9529055aea51c4f08a4618f907aee1b01e43951b00480243935a4b8040c` |
| Deployment source manifest | `3ac5464dad07319f7c267fb80a1ed5ded786f5ed87ddf71c533b7aaec4159f80` |
| Native continuation review | `10e0aefcc956f160ff322c1f620422417017e04f4fbe5b73210f65b20bbff343` |

To fit the distinct payload, one inactive historical kernel backup
`/boot/vmlinuz-linux-surface.bak-20260610-220702` was copied and hash-verified
under `retired-unused-backup/` before removal from boot. Neither active GRUB
configuration references it. Restore the verified archived file to its original
path before using a historical configuration that does. Backup SHA
`b9ac565c80e3741dd0a64b2a805a80f008bf7f47c4c1d2272e17e582bf206d91`,
five-file retirement manifest
`518c107112c9fb2d3f7bfc731dc4c42007c975c5fb7032dd94b61a56023153c6`.
Active AA/AB payloads and all known-good artifacts remain unchanged and hashed;
27MB boot space remains after AE installation.

Collector620s/fallback900s retain every AD native/GPIO/codec/DSP/graphics/Wi-Fi/
final-readiness/taint/error criterion. Failed opens, invalid headers and clean
startup are reported separately even when final readiness passes; raw dmesg is
also archived alongside journal/export and counters. Scoped readiness remains
distinct from reliable startup, physical input, electrical state and acoustics.
Fallback stops only after a successful archive hashes; failure leaves it armed.
Original AD collector/result/scripts remain unchanged.

Native continuation is verified for current thread/promptcontinue; retired
resume marker absent. Known-good remains persistent default, next entry empty
at installation, EFI BootNext absent. The one-shot queue schedules a30s guard
that rechecks actual boot ID, pending entry, default, module/DT/payload/recovery/
runtime hashes and timer enablement immediately before reboot. EFI/early-kernel
automatic recovery remains unvalidated; repeated boots are explicitly authorized.

On continuation require AE release/path and `spx_attempt=20260930ae`, diagY/
force0. Preserve raw kernel/jiffies chronology of probe and later opens,
accepted reports, powered/gated IRQs, polls, counters and IPTSD state without
live restart/rebind. Wait for final-result/finalizer-action, then run
review-ae-result.py and interpret clean startup separately. If fallback returned,
archive AE's prior journal and actual new known-good identity. Collect the result
before another experiment; no unsolicited audio or input test.
