# Z: exact-Y, silent single-pin boot trial

Z reuses Y's `7.3.0-rc2-spx-mainline-20260927y+` kernel, modules, DTB and
initramfs at their existing paths. Its distinct entry is
`spx-trial-20260930z`; the only hardware selector added is
`wcd934x.spx_wsa_en_pin=1`. No playback, PCM test or capture is scheduled.
Read [the reviewed boundary](AUDIO-CONTINUATION-20260930.md).

The permanent archive is
`/var/lib/spx-boot-diagnostics/attempts/20260930z`. Installation verified 977
build files, 272 symlinks, 202 installed module files, 15 payload/recovery/
runtime files and 328 preboot snapshot files. Installed-review SHA256 is
`b6f3ed97af79c06c49a20f4082d0bf1c87cdf3e7e2dfeac7c5b7784999c64f89`.
Preboot snapshot manifest SHA256 is
`86c186644c0483f9a34d7a18a0d170e1d796b72dc68f9865737d9b95098147f3`.
The separate Y audio-state manifest SHA256 is
`6969972cce4de77a2364326f0f5e3c5024aa40521b87e994fbe1361e7eb986ca`.
Deployment source manifest SHA256 is
`7eb56867090c48a7f12cbe61a8d08abb36c9e51e7b2e9a2ef3a43bde4ab4de65`.

Two preparation guards caught issues before selection. The whole source-diff
comparison rejected post-Y diagnostic/documentation commits; the archived
comparison verifies identical kernel changes and config, preserving both Y's
original source snapshot and the current diff. A final snapshot found that
`spx_rearm_init` is write-only. The collector now skips unreadable sysfs
parameters; the previous script/review/snapshot are retained under
`prequeue-collector-correction`, and corrected runtime hashes plus installation
were verified again. Neither issue selected an entry or requested a reboot.

The 620-second automatic collector archives software GPIO state, module
parameters, SoundWire and baseline evidence. Only a verified scoped pass stops
the 900-second fallback. GPIO register reads may be cached; a pass does not
prove physical pad voltage or acoustic output. No trial should be reselected
without collecting its result.

Before selection Y boot ID was `b5f0a540-3e81-4415-b08c-f869e01349a2`, saved
default was `spx-known-good`, next_entry was empty and EFI BootNext absent.
Native Happy continuation is verified for Codex thread
`01a0f1ab-5218-7880-a0f0-feff144bca7d`, with resume flag true and prompt
`continue`; the retired resume marker remains absent.

Use the archived one-shot queue helper, which retains a request marker and
schedules an immediate recheck before reboot. The current `attempt.json`,
`reboot-requested`, `grubenv.queued.txt` and `reboot-check-passed.json` record
selection/reboot progress. On continuation first inspect actual release,
boot ID, attempt, uptime and timers. While Z is live, let its collector finish
before interpreting the result. If already on known-good, preserve the Z boot
logs and failure outcome before any next experiment. Do not run audio unless
the user explicitly requests that playback run.
