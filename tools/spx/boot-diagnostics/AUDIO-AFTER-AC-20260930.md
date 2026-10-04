# Next step after AC: bounded touch startup metadata

AC establishes the narrower native left attachment result: correct DT identity,
one initialization, force worker absent, no selected native errors. Full boot
scope failed because touch supplied no delivered IRQ and three zero headers.
Preserve this failure rather than redefining its baseline. Read
RESULT-20260930ac.md and TOUCH-L-REVIEW-20260922.md.

Prepare AD using exact AC artifacts and selectors, changing only attempt ID
and `spi_hid.startup_diag=0` to1. AC's automatic known-good return was collected
and independently hash-verified first. Keep force/core/watchdog0, pin1,
left2110/unique3, right2010/unique4, DSP and existing startup policy unchanged.
No reset, GPIO/IRQ policy, descriptor bootstrap or live intervention is justified
by the current evidence. No playback, capture, PCM or input-event reads are
authorized by this continuation.

The existing read-only0444 logger records metadata from existing operations
without extra SPI transfers. Source bounds are **four windows,48 records each**,
192 records per device lifetime;47 ordinary records reserve the terminal
summary. Archive its parameter, window/event counters, reset/power/IRQ/read
chronology, /proc/interrupts, ready/error counters, HID publication and IPTSD
state. Retain AC's full strict620-second baseline and900-second fallback;
add diagnostic enabled/bound checks. Do not change any deployed AC collector.

Logging extends input-lock-held work and may alter scheduling. A successful AD
boot alone would not prove a logger fix, startup reliability, an electrical IRQ
edge, physical rail state or causality. Existing irq-enabled bookkeeping can
lag request_irq/enable_irq; powered is a software gate. Inspect accepted report
types and descriptor/ready transitions before considering IRQ retention or
timing changes. A failed AD supplies targeted missing-response metadata;
collect that result before selecting another experiment.

Keep known-good default, select AD only once, hash recovery and exact reused
source/config/kernel/modules/DTB/initramfs, verify native continuation, and check
actual boot ID/pending selection immediately before reboot. Userspace fallback
does not establish EFI/early-kernel recovery coverage.
