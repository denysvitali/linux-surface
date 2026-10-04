# AX read-only wake inventory for B05/P03

Actual AX `c05c40c3-3f45-49b7-9a6e-524f72a8fe79` exposes
`freeze mem disk` and only `[s2idle]` as its mem sleep selection. This audit
does not suspend the machine, arm an alarm, change wake policy or touch the
ongoing RTC/GPU collectors. Enumeration is not successful wake evidence.

Only rtc0 is present, named `surface_rtc 01:01:01:00:00`. The frozen candidate's
RTC driver implements read_time and set_time, with no read_alarm/set_alarm or
alarm IRQ operations. RTC core clears RTC_FEATURE_ALARM when set_alarm is
absent; sysfs exposes wakealarm only when alarm and wake capabilities exist.
Actual rtc0 has no wakealarm attribute. Enabling RTC_SYSTOHC repairs a time
synchronization path; it does not add an alarm implementation. Do not assume
rtcwake or a CLOCK_BOOTTIME_ALARM timer will provide an independent resume here.
This says nothing about unexposed firmware alarm capabilities.

The DT SAM controller is bound as serial1-0 on c94000.serial, with GPIO180 as
its wake interrupt. `/proc/interrupts` shows IRQ183 `ssam_wakeup`, zero recorded
interrupts at this snapshot. Its power/wakeup is disabled, as is its serial1
parent; the GENI UART platform device has no power/wakeup attribute. The driver
explicitly defaults controller wake permission off because EC battery and other
events can cause unwanted wakes, and filtering callbacks are not implemented.
During suspend it enables the IRQ, but only calls enable_irq_wake when the
controller's wake permission allows it. The IRQ is disabled again on resume.
The default is a policy choice documented in source, not proof that GPIO180 or
the EC wake mechanism is broken. There is no ACPI wakeup file on this DT boot.

The PMIC power-key IRQ232 and its wakeup source enumerate with zero events.
The snapshot does not establish which physical button reaches that IRQ, that it
wakes this platform, or that Type Cover/pen/touch/network wake works. UART normal
IRQ counts show activity, not a suspend wake path. Remoteproc and battery/charger
wakeup-source entries likewise do not establish an intended wake fixture.

Next controlled B05/P03 work must first identify and verify the intended wake
source on the final candidate. Preserve before/after policy, IRQ/wakeup counters,
battery measurements, CLOCK_BOOTTIME versus CLOCK_MONOTONIC intervals, RTC
readback and full suspend/resume logs. Validate bounded short sleeps before the
required ten cycles and30-minute battery sleep, then regress display/input/
network/audio/cameras/accessories. A scheduled userspace fallback cannot execute
while the whole machine sleeps and is not proof of an automatic resume path.
Do not enter suspend during AX's frozen timed experiment. Physical wake and
unmasked retention/timekeeping tests remain open.

Durable audit:
`/var/lib/spx-boot-diagnostics/attempts/20261003ax/wake-readonly-audit/`,14 files,
manifest `ce48991482ac590fa494a9c63dbf86c176cb4805c186f86ca0ebba0204116c74`.
Eight source files are byte-checked against AX's frozen source-files manifest;
the capsule includes their copies, actual identity/policy, RTC class attributes,
power states, wakeup sources, interrupts and input inventory. No acceptance
checkbox closes.
