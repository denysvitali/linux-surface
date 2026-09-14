# Recovery runtime watchdog observation, 2026-09-14

Read-only audit of boot `40bc7e68-538d-4c15-a39d-84158efe9e6a`, running
`6.18.3-1-surface+` with `spx_boot=known-good`. No reboot, watchdog device
open, register access, or boot configuration change was performed by this audit.

## Observed evidence

- The live device tree contains `/soc@0/watchdog@17c10000`, compatible with
  `qcom,apss-wdt-sm8150` and `qcom,kpss-wdt`. This differs from the uncommitted
  mainline candidate's `qcom,apss-wdt-sc8180x` compatible.
- `/sys/class/watchdog/watchdog0` and `/dev/watchdog0` exist. PID 1 file
  descriptor 15 resolves to `/dev/watchdog0`.
- The current journal reports `qcom_wdt` as the hardware watchdog and a
  hardware timeout of 30 seconds, in both initramfs and host systemd logs.
- The watchdog sysfs attributes identity/state/timeout/timeleft/bootstatus
  are unavailable in this kernel. Their absence is not evidence of inactivity.
- GRUB retains `saved_entry=spx-known-good` and an empty `next_entry`.
  A previously prepared stage-1 watchdog DTB entry is present but not queued.
- The original recovery kernel, initramfs and `.dtb.wsa` hashes still match
  the preserved recovery artifacts. The live node alone does not establish
  which DTB or earlier bootloader modifications produced this boot.
- All 13 `test_preflight.py` tests pass, including refusal to reboot even
  with valid experimental artifacts.

Root-only evidence, including hashes and the watchdog journal, is stored in
`/var/lib/spx-boot-diagnostics/runtime-watchdog-audit-20260914/`.

## Limits and next requirement

This supersedes the earlier empty-watchdog observation for this boot only.
It establishes runtime activation and systemd ownership, not reset on expiry,
bootloader access, or continued coverage across ExitBootServices. The kernel's
separate "Hard watchdog permanently disabled" message concerns its CPU lockup
detector; systemd explicitly reports the hardware watchdog above.

Experimental boots remain prohibited. Independent reset capability and measured
reset coverage before and after firmware handoff are still required. Do not
stop feeding the live watchdog to test it without that recovery route.

## RPMh candidate review

The existing uncommitted `qcom,skip-readback` candidate gates voltage reads and
initial-mode discovery at the PMIC parent node. The third `rpmh_read` call is
inside the mode helper, called only by initial-mode discovery, so it is also
excluded by that gate. Unspecified platforms retain readback. The three SPX
PMIC parent nodes opt in; cached voltage/mode initialization remains unchanged.
This source review does not establish that unsupported readback caused a hang,
or validate voltage, mode, or bypass behavior on hardware. These edits remain
uncommitted pending stronger evidence; they were not changed by this audit.
