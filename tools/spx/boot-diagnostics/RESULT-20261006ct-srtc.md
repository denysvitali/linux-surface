# CT: mainline AC timer control works; wake delivery remains unproven

Boot `b56c1e85-0913-4327-aade-233064c8b45a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Changed:** extend the reusable SRTC command to verified mainline boots.
Build only the stock SSAM cdev module; load it for each bounded test and unload
afterward. The same SQ2 firmware commands previously verified on recovery
program/read AC timer0. No system sleep or battery test is performed.

**Observed:** both timers begin disabled. AC timer0 reports30 seconds, then26
after4 seconds. At32 seconds it reports disabled again. Explicit disable/read
leaves both timers disabled. A passive category1 observer sees no events.
Display-off notification0x15 and restoration0x16 both return0; expiry still
shows no event. Normal operation keeps the wake IRQ disabled, so its initial
zero interrupt count cannot establish lack of a physical signal.

**Awake IRQ tests:** a guarded helper verifies SPX, GPIO180/msmgpio,
rising-edge and initially disabled/non-wakeup IRQ183, then enables the
already registered IRQ while Linux stays awake. Queued-display expiry still
has zero interrupts. SQ2 `_DSM` function8 confirms D0 notifications; adding
0x33 exit/0x34 entry also returns0 and restores normally, still zero IRQs.
Both runs unload the helper, balancing IRQ enable/disable. Display-on and both
timers are restored; the cdev unloads. System wake permission stays unchanged.
Sensors708/proxy1270 remain active with zero restarts; boot ID is unchanged.

**Meaning/next:** mainline firmware timer control and expiry work. There is
no validated wake fixture yet: awake notification tests do not establish
platform-sleep routing. P03 stays open; no RTC alarm feature is advertised.
Park this path pending a supported platform wake contract or physical wake
test. Do not repeat these unchanged observations or infer successful suspend.

Evidence: `/var/lib/spx-boot-diagnostics/functional/20261006ct/`,
`srtc-timer`, `srtc-expiry`, `srtc-queued-expiry`, `srtc-irq-expiry` and
`srtc-d0-expiry` result files. Initial missing-cdev failure is separately
retained. The reusable tool and guarded IRQ helper are committed on `spx/next`.
