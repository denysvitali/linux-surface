boxes closed: 3 of 47; newly closed: none

# DP retry exhaustion: false success corrected (WIP)

Automatic functional **24/49**, inventory **42/52**, blocked **35**, failed **0**,
errors **0**. Current boot `32ec6625-df7d-431a-8376-d4cdbd4d5e7d`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`:
[current-boot report](/var/lib/spx-boot-diagnostics/boots/32ec6625-df7d-431a-8376-d4cdbd4d5e7d/hw-validation/report.json).
Existing complete current-catalog report verified; no new boot or hardware test.

**Defect:** `msm_dp_ctrl_on_link()` permits four training attempts. After the
last failure, a successful fallback/mainlink reset overwrites `rc` with zero.
The loop then expires and returns success although no attempt trained a link.
For HBR2 x4 with clock-recovery failures and readable partial lane status, the
attempts can be 540000x4, 270000x4, 162000x4, 540000x2; the final fallback selects
270000x2 and resets but never trains that configuration. The 6.18 reference
shares this defect, and its AUX implementation is identical to current source.

**Change:** explicitly mark exhausted retries as failed, entering existing
training-pattern/mainlink teardown and returning `-ECONNRESET`. Attempt count,
fallback decisions and PHY-test behavior are preserved. The guarded fallback
AUX-read correction remains a separate earlier change.

**Validation:** `python3 -B tools/spx/test_dp_training.py` compiles the actual
controller function and actual rate/lane fallback helpers with bounded hardware
stubs. Before correction it reports `expected=-104 actual=0 attempts=4 resets=4
teardown=0`. After correction, eleven cases pass: immediate/last-attempt success,
exhaustion, channel-equalization fallback failure, both AUX-read failure paths,
disconnect, reset failure, clock failure, PHY-test mode and null controller.
These are control-flow checks, not hardware evidence. Incremental `dp_ctrl.o`
compilation in the established build directory passes; checkpatch and
`git diff --check` pass. No new kernel release or build directory.

**Limits / next prerequisite:** neither the retained incident journal nor pstore
proves retry exhaustion caused the October 20 panic. This correction contains a
real failure path; it does not identify the AUX timeout or establish a panic fix.
The external display is disconnected. No deployment, MSM reload/unbind, modeset,
hotplug, capture, playback or reboot was performed. The persistent baseline and
existing DP candidate remain unchanged. A hardware trial requires an available
connected fixture and evidence of the relevant failure path; no safe automatic
reproduction is established. Original AUX/panic investigation remains open.
