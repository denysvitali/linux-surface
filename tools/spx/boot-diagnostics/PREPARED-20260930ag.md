# AG installed: silent right2110/unique4 firmware matching

Prepared and reviewed from actual known-good boot
`4fe7d83a-37fd-4eb7-800c-850d2aa0885b`, release `6.18.3-1-surface+`, after
AF's verified900s userspace fallback. Read authoritative
`/var/lib/spx-boot-diagnostics/attempts/20260930ag/attempt.json` for selection
state. Preparation is not an observed AG hardware result.

Read RESULT-20260930af.md and AUDIO-AFTER-AF-20260930.md. AF independently
reported native2110/unique4 with a mismatched2010/unique4 firmware node,
an extra firmware-less device, zero attached codecs/initializations and one
SWR CMD error. Its strict baseline and separate pin2 diagnostic failed.
Graphics/Wi-Fi/touch/DSP passed. Original AF evidence and criteria remain
frozen; it was not re-armed. The535-file return archive proves userspace
recovery for that attempt, not EFI/early-kernel recovery.

AG changes only right_spkr compatible sdw10217201000->sdw10217211000 and
the attempt marker. Independent decompilation proves a single-string delta;
left2110/3, rightreg0/4, pin2 GPIO flags, port map4/5/6/8, regulators, sound
routing and all other properties remain exact. Kernel/187 modules/private
initramfs/config/source outside this DTS file are exact AE. Archive has1084
build files/272 symlinks,202 module-tree files and15 new DT source/build records.

Release remains `7.3.0-rc2-spx-mainline-20260930ae+`; BOOT_IMAGE remains
`/spx-trial-20260930ae/vmlinuz`. Initramfs also remainsAE. Only DTB is installed
under `/boot/spx-trial-20260930ag/spx.dtb`; require spx_attempt=20260930ag.
Pin2 stays selected, raw two-pin overrides-1, swapN, force/core/watchdog0,
exactwindowsN, enumdiagY, touchdiagY bounds8×48/384 lifetime. No driver,
addressing, port-map, reset/IRQ or transport-policy change is included.

Predeclared620s scope requires exactly two DT-backed wsa881x codecs2110/3
and2110/4, right Attached/device1 and its own cold-init marker; repeat bounded
slot1 decoded2110/unique4 with rc0/0. Native errors, worker/force markers,
FIFO/init/status failures must be absent; GPIOsoftware4/1c, DSP/controller/
soundcard/graphics/Wi-Fi/touch/taint baseline must pass. Left may remain
UNATTACHED. The separate pin2 diagnostic does not control fallback. A failed
scope retains900s fallback; a pass stops it only after the archive hashes verify.

Validation: complete source/config/artifact/recovery/module/runtime rehash;
native DTB build and one-string decompilation proof; four systemd units and
GRUB syntax; eight helper AST/global-name checks; six preserved AF boundary
predicates; archived identity replay/five negative pairing cases; a positive
scope case plus five negative scope cases (including left-only initialization)
and whitespace checks. No audio/PCM/capture/input-event read or live intervention.

| Evidence | SHA256 |
| --- | --- |
| AG DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |
| DT source/build15-file manifest | `cd15b388067403643a36b24d2c6912b2b8c370f2072e1a3fde3a179ea5bffa5d` |
| Independent DT review | `514ddf1e64c3af3bbc738f5d867cf231419293cb522327f969f240ca0a8c72e8` |
| Installation review | `d32caa662d748557e010f991878465cfdc725a46034b8938398a9c17c9e9d8b5` |
| Deployment11-source manifest | `c50aebcf44e7fdfbbcda9f9c4a6af84e717200733de15c5fc0497a9ad751f702` |
| Native continuation review | `f7fb4cef0c36fdcc812e6fc2ea8644be863593eb2e071bd57d0cac7f72e75ab6` |
| Independent prequeue review | `fda0b7e14c7a620ab9fd8a1029a7067d65fda7d69335c2dcd357f26aca39050d` |

Native continuation is configured for the current thread/promptcontinue,
daemon startup and absent legacy marker. Known-good persistent default,
empty next_entry and absent EFI BootNext were independently verified. Queue
once; the30s guard rechecks actual boot ID, pending entry and DT/module/
payload/recovery/runtime hashes before requesting reboot. Repeated boots
including possible manual power cycles are explicitly authorized; EFI/early
automatic recovery remains unvalidated.

On continuation require AG marker, AE release/kernel/initramfs and AG DTB.
Collect actual raw words/status/return codes, right binding/init, selected
command errors and raw touch chronology. Wait for final-result/finalizer-action,
then run review-ag-result.py and decode the frozen words independently. Keep
readiness separate from reliable startup, physical GPIO/routing/register
readback, idle resume, transport and acoustics. Collect the result before another
experiment and never blindly re-arm a failed image.
