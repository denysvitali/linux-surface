# 2026-10-20: CCI timing readback diagnostic (WIP, not a camera fix)

boxes closed: 3 of 47; newly closed: none.

- Boot `ada67ad4-c217-474e-82c9-c9551bc78513`, kernel
  `7.3.0-rc2-spx-mainline-20261004bg+`; no reboot or capture.
- Current canonical report verified before and after the work: **28/49
  functional, 42/52 inventory, 31 blocked, 0 fail/error**:
  `/var/lib/spx-boot-diagnostics/boots/ada67ad4-c217-474e-82c9-c9551bc78513/hw-validation/report.json`.
- **H-timing-readback:** stale master-1 timing programming might distinguish
  first-transfer boot stalls from successful timeout recovery. Compare the
  read-only SCL, SDA0/1/2 and MISC registers with the exact expected values
  immediately before reset and after successful reset. Log only on timeout;
  no retries, sleeps, clocks, power sequencing or successful transfers changed.
  Equal readbacks would refute stale timing programming, not hidden FSM state.
- Compared the 6.18 CCI implementation and prior fd/fe/ff findings; no justified
  ordering fix was identified. Do not repeat concurrency, clock/gating, reset
  overlap/re-init, unpowered-time or pinned-active variants.
- **Checks:** incremental CCI module build passed with `LOCALVERSION=+` in
  the existing build directory/source; vermagic matches the running release.
  Initial build from the repository failed its existing in-tree-artifact guard;
  rerunning from the established build source restored generated headers and
  the exact release. Only the changed CCI source file was synchronized.
  Patch checkpatch: 0 errors/warnings; `git diff --check` passed.
- One safe CCI module reload (no open video/subdevice clients) re-registered
  front `5-0036`, rear `4-0010`, IR `4-0060`; no timeout occurred. The new
  timeout diagnostic itself remains **unexercised**, not a proven fix.
  Installed the module in the current release tree and ran depmod; previous
  module retained at `/var/tmp/spx-cci-before-timing.ko`. No initramfs or boot
  payload was changed; availability during early initramfs is not established.
- Separate complete canonical-runner regression, with camera/mic capture and
  sound disabled: **25/49 functional, 42/52 inventory, 34 blocked, 0 fail/error**.
  `/var/tmp/spx-cci-timing-regression/report.json` and `report.md`.
  All three status differences from the canonical report are camera frame
  checks blocked by deliberately absent capture opt-in; graph still observes
  all three sensors and 74 enabled links. Existing generated checklist and
  prior boot report were preserved, not presented as this regression's result.
- **Next:** inspect `SPX cci-timing` pairs on a subsequent controlled boot
  that stalls; no fault injection, forced captures or repeated reload rounds.
  A clean reload cannot test this boot-only defect. Camera quality/packaging/
  resume, audio EIO/origin evidence, power/recovery, cellular/IPA/GNSS,
  Type-C/dock/USB fixtures, calibration and parked accelerators remain open;
  this diagnostic closes none of those support requirements.
