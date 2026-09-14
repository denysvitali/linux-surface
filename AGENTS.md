# Agent rules

## Experimental SPX boot lock (2026-09-14)

The user requires automatic recovery from EFI-stub/early-kernel hangs without
manual power cycling. Experimental hardware boots are currently prohibited.
Do not re-enable or bypass `tools/spx/boot-diagnostics/preflight.py --reboot`,
restore experimental GRUB entries, or queue an experimental kernel until a
pre-kernel reset mechanism has been independently validated for this device,
including coverage after ExitBootServices. A userspace return timer, compiled
watchdog driver, successful build, or UEFI SetWatchdogTimer alone is not proof.
The diagnostic DTB currently has no hardware-watchdog node and systemd reported
no watchdog device. Keep `spx-known-good` as the default; preserve all evidence.
Continue offline port work while that recovery requirement is unresolved.
