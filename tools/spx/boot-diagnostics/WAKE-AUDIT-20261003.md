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

## New supported timer lead (2026-10-05; not a wake pass)

SQ2 firmware `~/Documents/acpi/surface_pro_x_sq2/dsdt.dsl:103154` enables
SRTC/ACPI000E; `_GCP` returns SGCP0x1f7, advertising AC/DC timer wake.
`_STV` at103285 sends SAM category1/target1/instance0 command0x1a with
LE32 timer ID and LE32 relative seconds, requiring a4-byte status response.
`_TIV` at103311 sends command0x1d with LE32 ID and reads4-byte remaining time.
Existing `drivers/acpi/acpi_tad.c` defines AC0/DC1, disabledU32_MAX and relative
seconds. This is a firmware-defined command contract, rather than a register guess.

A bounded next investigation can preserve both timer values, arm/verify a short
countdown, then disable/restore. Successful countdown alone would not establish
wake. `_GWS` reads firmware memory GWAS/GWDS; `_STP` is a no-op and `_TIP`
returnsOnes. GPIO180 expiry delivery and controller event filtering remain
unvalidated. Do not expose an RTC alarm feature or enter unattended s2idle
until the actual wake path works. No timer command or sleep was run here.

The actual SPX DTS manually defines PMCs without an RTC node; it does not
include the generic `sc8180x-pmics.dtsi` RTC. SQ2 firmware disables PRTC while
enabling SRTC. There is no validated PMIC RTC ownership/IRQ alternative.

## Countdown contract verified (2026-10-05; recovery kernel only)

On recovery boot `403ca502-ca68-47b8-88be-926a175708e5` (`6.18.3-1-surface+`),
the documented SAM commands read both AC and DC timers as disabled (`U32_MAX`).
While on DC, timer1 accepted 30 seconds, reported 26 after four seconds, and
returned to disabled after the documented disable value. Both timers read
disabled afterward. The temporary SSAM cdev module unloaded and the device lock
was released. See [SRTC result](RESULT-20261005srtc1.md).

This verifies a bounded firmware countdown and cleanup on recovery only. It
does not show expiry delivery, wake IRQ handling, mainline behavior, or suspend
resume. Do not close P03 or advertise RTC alarms from this result.
