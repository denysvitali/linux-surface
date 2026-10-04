# AX read-only RTC observation preparation

AX is built/archived and has not booted. Current known-good UUID remains
`fbc6d663-8269-4d2f-9aac-c4a687583b00`, with persistent known-good default and
empty next selection. [Prepared kernel](PREPARED-20261003ax.md),
[diagnosis](RTC-SYNC-20261003.md).

[Native probe](rtc-readonly.c) opens rtc0 read-only, uses RTC_RD_TIME and
brackets it with realtime/boottime reads. It neither queries adjtimex nor writes
either clock. A native `-O2 -Wall -Wextra -Werror` build passes. Undefined-symbol
inspection verifies no adjtimex/clock_adjtime/clock_settime/settimeofday imports.
[Controller](ax-rtc.py) uses chrony's tracking reporting command for NTP state;
raw14-column CSV is retained with parsed stratum/reference/system correction/
leap status. These are chrony observations, not a direct kernel STA_UNSYNC read.

The first probe version queried adjtimex with modes0. Local
`kernel/time/timekeeping.c:do_adjtimex()` still calls ntp_notify_cmos_timer after
that query. Repeated queries could therefore prompt the RTC worker being tested.
That version is superseded before deployment; its original11-file sealed packet,
native binary/sample and tests remain at AX/rtc-observer-query-side-effect,
manifest `3514cc700d17b56cfbc933e4a24f566b1359cdd3fc1361c16bf38ada869a5ea9`.
Its one probe execution was on known-good with the RTC synchronization path
disabled. No AX observer ran and no RTC/system write was issued. A separate
note records why it was superseded; its original manifest remains exact.

The final known-good read-only sample at3237.39s still shows RTC about791.25s
ahead of system time despite chrony stratum2/Normal and about88µs system
correction. This is a diagnostic control, not AX hardware evidence.

The planned AX controller must start at30s, finish at2600s and preserve a sample
every15s. It asserts actual AX release/cmdline/UUID, exact embedded config and
probe hash, SSAM RTC identity/hctosys, and zero taint throughout.
[Verdict](ax_rtc_core.py) requires90–200 samples, no observation gap beyond45s,
no slow/stepped read bracket, first sample20–180s and last2590–2680s. After60s
settling from the first synchronized chrony report, at least45 samples spanning
at least660s must all have Normal leap status, stratum1–15, a reference no older
than1800s and system correction within1s. RTC-minus-system read intervals must
stay within±2s, accounting for whole-second quantization and read latency.
A synchronized system clock with the old791s RTC offset is explicitly rejected.

[Criteria verification](verify-ax-rtc-core.py) passes one explicitly synthetic
positive and31 negative cases: identity/config/probe mismatches, wrong RTC,
missing synchronization option, observer writes, incomplete/late/nonmonotonic
sampling, taint, slow/stepped reads, missing/stale/future NTP reference, unstable
NTP, insufficient synchronized span and wrong RTC readback. These are observer
tests, never hardware acceptance.

Final preparation archive: AX/rtc-observer-preparation,13 files, manifest
`9b94591a004a6989f69d8aa87fbc5bac4be2a6c5e888e1dd523b3bdc563dfaf3`.
Probe binary SHA256:
`155ea047bea75da77a7b8bb89fe10d854e235bfedb1b0cdbcb2cae0f0a654b13`.
Both packets independently rehash. Collector/assessor/verification source and
the native compiler/version/imports/sample are frozen there.

Next integrate the RTC service at30s alongside the strict baseline and GPU/
ordered-camera regressions, include its raw evidence and independent verdict in
the2800s finalizer, and keep the3300s guarded known-good return armed. Review
all deployed bytes/units/criteria and fresh outgoing UUID/default/selection
before selecting AX exactly once. No observer is installed yet. RTC correction
will remain an inference from actual readback/configuration without an enabled
RTC tracepoint. Power-off retention, suspend timekeeping and long-term drift
are still separate B05 requirements; all47 acceptance boxes remain open.
