# Agent rules

## Reboot hygiene (MANDATORY before every reboot)

Before issuing ANY `systemctl reboot` / power-cycle:

1. **Check the current boot first**: `uptime -s` + `cat /proc/sys/kernel/random/boot_id`
   and compare against the boot you last verified. If you have not re-checked since
   your last action, do it now.
2. **If a previous reboot command was interrupted/aborted, assume it EXECUTED.**
   Verify with `uptime -s` / `boot_id` before ever re-issuing it. A duplicate
   `reboot` has already destroyed one healthy test boot this way.
3. **Confirm you are not already in the expected state.** If the current boot's
   cmdline/boot_id already matches what the planned reboot was supposed to
   achieve, DO NOT reboot again — harvest the state and continue.
4. **Check when the last boot happened** (`uptime -s`). If the machine booted less
   than ~2 minutes ago, wait and re-check state instead of stacking another
   reboot; test boots need time to reach their steady state.

This exists because tool-call interruptions ("Claude was aborted or killed")
do NOT mean the command failed — on 2026-08-25 two such "failed" reboot calls
had both actually executed, and blindly retrying killed a healthy soak boot.
