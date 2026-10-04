# Read-only RTC versus independent NTP packet

Targets B05 preparation for unmasked retention checks. On actual AX
`c05c40c3-3f45-49b7-9a6e-524f72a8fe79` at2133.94s uptime,
[rtc-ntp-reference.py](rtc-ntp-reference.py) used the already frozen read-only
RTC probe and sent one NTP client request to83.150.53.153, the numeric source
reported by the running chrony tracking observation immediately before testing.
It performs no adjtimex, time discipline, RTC write, daemon/policy change,
boot selection or retry. The frozen2600s RTC controller remained running.

The correlated48-byte server response reports stratum2, RTT6.35ms and reported
root/precision uncertainty0.397ms. Projecting integer RTC readback through its
full ioctl bracket to response receipt, with one-second quantization, the full
RTT and reported server uncertainty, gives RTC offset interval
**−0.25388 to+0.75704 seconds**. This independently compares readback to the
responding server instead of accepting local synchronized wall time alone.
No cold power-off or suspend occurred, and the normal kernel RTC sync worker
remained enabled. This sample cannot establish unmasked retention or drift.
The network response is unauthenticated; it is diagnostic evidence, not a
security or general NTP conformance result.

The parser follows the timestamp/header layout in
[RFC5905](https://www.rfc-editor.org/rfc/rfc5905.html), sections7–8. It checks
server mode/version/leap/stratum, origin correlation, receive/transmit ordering,
reference age, reported uncertainty, one-second RTT bound and absence of a
local wall-clock step during the request. It deliberately rejects unsupported
packet extensions and NTP eras rather than guessing. The projected interval is
a conservative diagnostic model with an additional1ms rounding allowance,
not an RTC oscillator characterization.

[Offline reviewer](verify-rtc-ntp-reference.py) replays the actual raw packet and
rejects13 malformed/stale mutations; shifting RTC readback by791s yields a
failed bounded sample verdict. These are parser checks, not additional network
queries or hardware acceptance. The first command printed to tool stdout
without redirection; its exact raw packet and clock-sample fields were copied
from that result into `initial-observation.json`. This capture limitation is
recorded explicitly. Archive-time identity is recorded separately and matches
the original boot. There was no second network query.

For future cold/suspend retention, capture stdout/stderr directly, preserve
before/after reference and RTC samples and prove normal clock discipline did
not mask the interval being assessed. Retain all failures; a daemon status or
this single live sample cannot close B05. Physical power-on/wake fixtures and
full common-candidate regression remain required.

Durable evidence:
`/var/lib/spx-boot-diagnostics/attempts/20261003ax/rtc-independent-reference/`.
All47 acceptance boxes remain open.
