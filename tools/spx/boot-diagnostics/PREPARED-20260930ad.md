# AD: silent bounded SPI-HID startup metadata

AD is installed and independently reviewed from known-good boot
`2b761569-5b25-4ec5-a67e-f960c8fea28d`, release `6.18.3-1-surface+`.
Authoritative selection state is `/var/lib/spx-boot-diagnostics/attempt.json`.
Inspect actual boot ID/cmdline before acting; preparation does not establish
that the trial booted or passed. Never blindly re-arm a failed attempt.

AC's620-second scope failed solely because SPI-HID was not ready. Its native
left attachment/GPIO/codec/DSP checks passed. Touch delivered no IRQ and three
zero headers; first invalid read preceded native audio enumeration. Its900s
userspace fallback returned to this known-good boot. Both boots and recovery
were archived and hash-verified before choosing AD. Read RESULT-20260930ac.md,
AUDIO-AFTER-AC-20260930.md and TOUCH-L-REVIEW-20260922.md.

AD reuses exact AA kernel/modules/initramfs and AB DTB, source and config.
Booted release remains `7.3.0-rc2-spx-mainline-20260930aa+`; BOOT_IMAGE remains
`/spx-trial-20260930aa/vmlinuz`, DTB `/spx-trial-20260930ab/spx.dtb`.
The only selector changes from AC are attemptID `spx_attempt=20260930ad` and
`spi_hid.startup_diag=0` ->1. Force/core/watchdog0, pin1, left2110/unique3,
right2010/unique4, DSP and all other selectors/artifacts are preserved.
No reset/power/IRQ/SPI policy or source change; no payload replaced or retired.
No playback, capture, PCM, input-event reads or live device/service operations
are scheduled.

The existing0444 logger observes software metadata and existing transfer
results, without extra SPI transfers or report payload logging. It allows four
startup windows with48 records each, reserving a terminal summary,192 records
per device lifetime. It adds lock-held logging time and can affect scheduling;
successful startup alone does not establish a fix or reliable fresh boots.
powered/irq-enabled/regulator/pinctrl metadata are software observations,
not measured electrical state. Interpret accepted reports and descriptor/ready
transitions, not merely IRQ or successful SPI call returns.

Archive `/var/lib/spx-boot-diagnostics/attempts/20260930ad` retains1,025 build
files/272 symlinks,202 installed-module hashes and15 DT/source files. Independent
installation review verified15 payload/recovery/runtime files,162 preboot
snapshot files and seven deployment scripts. Repository diff/config exactly
match AB's frozen snapshot. Python parsing, GRUB syntax, systemd unit verification
and diff whitespace checks passed. AST comparison proves AC's entire original
baseline predicate is retained with one additional diagnostic predicate; actual
L64-record/3-window logs pass the new parser, while disabled/missing/over-limit/
missing-begin diagnostics are rejected. Original AC scripts remain unchanged.

| Evidence | SHA256 |
| --- | --- |
| Reused build manifest | `92f2219ca1f4ed0d7db3816b132410200019e12778e633b26368014f569cf5f1` |
| Exact AB DT/source manifest | `e209f920d045a0572b65d57c137fefc9ba492e8934190fdc251dd9ba1d67d728` |
| Installation review | `dd1fadc6ad5adc8df43a9574bef82dba989c95a3e9bae8088d15c038f13a6a05` |
| Deployment source manifest | `017b9851eb243bae49dbaf46e9baf6417d59b7c5ca2b68b0bf26c3cbbe53b4f1` |
| Native continuation review | `1bd579801992045f850f9188b5b7944bb09a292c8848b8e9f41f70309beb521e` |
| Collected AC return manifest | `739c6264c1762499f014b692c947c0519823c7c848ee9f72064ceb5ec0e404d9` |

Native continuation is enabled for current thread, promptcontinue; retired
resume marker absent. Known-good remains persistent default, next entry empty
at installation review, no EFI BootNext. One-shot queue schedules a30s guard
that checks actual boot ID, pending selection, default, EFI state, installed
module/payload/DT/recovery/runtime hashes and timer enablement before reboot.
Userspace fallback does not validate EFI/early-kernel recovery; repeated
experimental boots remain explicitly authorized.

Collector620s/fallback900s retain all strict AC native/GPIO/codec/DSP/FD680/
Wi-Fi/touch/taint/error criteria. The added predicate requires diagnosticY,
bounded parsed records and each observed window starting with exactly one
begin. Ready/error/reset counters, IRQ counts, input publication and IPTSD
state are archived with full boot logs; counter/service fields are observations,
not new full functionality claims. Success stops fallback only after archive
hash verification. Failure keeps the900s return armed. No deployed AC collector
or result has been rewritten.

On continuation require `spx_attempt=20260930ad`, diagnosticY and force0,
despite the reused AA release/path and AB DTB. Collect actual startup windows,
accepted report types, power/reset/IRQ/read sequence, counters and IPTSD state
without a live restart/rebind. Wait for final-result/finalizer-action, then run
review-ad-result.py before choosing another experiment. If recovery returned,
archive AD's prior journal/fallback and actual new known-good identity.
