boxes closed: 3 of 47; newly closed: none.

# Read-only hardware gaps and speaker handoff

Boot `298cf388-134f-4db3-a218-413f5af213d3`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Changed:** added `tools/spx/hw_validation.py`, reusing an explicit allowlist
from `../hw-validation/hwv.py`. The sibling `../validation` provides hands-on
input/panel/sensor tests; neither tool closes checklist boxes. The new report
reads all47 exact frozen requirements and lists44 still open. It does not
alter the checklist or pick another blocker. Three offline tests pass.

**Observed:**46 interface probes:27 observed,8 suspected gaps,11 needing
investigation. Missing nodes/services include video codecs, CDSP FastRPC,
cellular data, Type-C, desktop microphone source and sensor services. Display
panel was off; external DP was connected. Sleep target remains masked;
diagnostic power overrides remain. Missing nodes and fixed probe assumptions
are not proof of absent hardware. Full output: `hw-validation-20261011.md`
and `.json` in this directory. Device lock released after collection.

**Handoff:** `/tmp/progress.md` describes committed10 ms desktop feeder and
+9 dB gain WIP. Recorded it in TODO and the local log. No acoustic latency or
distortion judgment exists; MultiMedia1 installed startup is unverified.
Root-owned gain file could not be read unprivileged; no gain change attempted.

**Next:** user judges current speaker delay/loudness/distortion and supplies
pending physical observations. Camera calibration remains deferred. No sound,
capture, raw sensor read, load, module change, sleep or reboot in this session.
