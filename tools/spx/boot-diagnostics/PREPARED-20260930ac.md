# AC: silent attachment with force path disabled

AC is installed and independently reviewed from AB boot
`094a2a10-d6cd-4e86-ba50-dd99bff8c6dd`. Authoritative selection state is
`/var/lib/spx-boot-diagnostics/attempt.json`; inspect actual boot identity before
acting. Do not mistake preparation for a successful boot or reselect a
consumed/failed image blindly.

Release and BOOT_IMAGE remain AA: `7.3.0-rc2-spx-mainline-20260930aa+`,
`/spx-trial-20260930aa/vmlinuz`; exact AA initramfs/modules and AB DTB
`/spx-trial-20260930ab/spx.dtb`. No boot payload is replaced or retired.
The only selector change from AB is `soundwire_qcom.spx_force_attach=1` → `0`,
plus attempt marker `spx_attempt=20260930ac`. Pin1, raw GPIO defaults, left2110/3,
right2010/4, port maps, regulator, DSP, codec-shadow, DAC and enum logger selectors
are preserved. No playback/capture/PCM or live parameter/device operation is
scheduled.

AB's357-file scoped result passed at620.77s, independently verified. Exactly two
DT-backed codecs, left2110/3 Attached/1, one init before and one after the forced
worker, no selected fault/FIFO/init/status error, baseline passed. Read
RESULT-20260930ab.md and AUDIO-AFTER-AB-20260930.md. The new question is attachment
without the worker's synthetic status, duplicate logical assignment, terminal
IRQ masking, dev0 write rewrite/blind FIFO or controller PM reference. These
mechanisms depend on the one force selector. Codec shadow reads remain active;
native status and submitted writes cannot establish acoustic output or hardware
register readback.

Archive: `/var/lib/spx-boot-diagnostics/attempts/20260930ac`, including exact
reused `build/` and `dtb-build/`. Independent install review verified1,025 build
files,272 symlinks,202 installed module-tree files,15 DT/source files,
15 payload/recovery/runtime files,340 preboot snapshot files and7 deployment
scripts. Full repository diff/config match AB's DT-build snapshot. GRUB syntax,
Python syntax and systemd unit verification passed. Known-good default and
recovery hashes unchanged; no EFI BootNext. Native continuation verified for
currentthread, promptcontinue, retired marker absent.

| Evidence | SHA256 |
| --- | --- |
| Reused build manifest | `92f2219ca1f4ed0d7db3816b132410200019e12778e633b26368014f569cf5f1` |
| Exact AB DT/source manifest | `e209f920d045a0572b65d57c137fefc9ba492e8934190fdc251dd9ba1d67d728` |
| DTB | `97983ecc8fc9a940787e6550071b03d1d8b63ccee00e75f2d10f452f82d7a187` |
| Installation review | `b8adff1091d4842841cf05e356e4e7591816b281eefcffd42b737f0f510af096` |
| Deployment source manifest | `dc07d738e24385bc815bafa0329893322f8c825a0578a2e6d8d187e3a0efeb6b` |
| Native continuation review | `b4cb713bdd7d6f50f51996c7a061b8fcc20d25eec545dc132e48308a2de5f3f0` |

Collector at620s, fallback at900s. Success requires the bounded2110/3 trace with
pendingforce0/forced0; exactly the two DT-backed codec nodes; left Attached/1;
force/core/watchdog0, exact_windows_initN; no enum worker or force markers;
GPIO software state and controller/DSP/card/graphics/Wi-Fi/touch baseline;
taint0 and no selected kernel, WSA FIFO/init/status or native bus/clock-stop
error. The collector also archives runtime-PM sysfs state, preserving unsupported
attribute errno values. The PM snapshot does not itself verify suspend/resume.
Result archive and hashes verify before any fallback stop; failure keeps900s
return armed. All old collectors/criteria remain unchanged.

One-shot queue schedules a30s guard, rechecking current bootID, pending entry,
known-good default, EFI BootNext, module/DT/payload/recovery/runtime hashes and
enabled timers immediately before reboot. Userspace fallback does not validate
recovery across EFI handoff; repeated experimental boots remain authorized.

On continuation inspect bootID/cmdline/uptime/AC timers. AA release/path and AB
DTB are expected; require spx_attempt=20260930ac and force_attach=0. Preserve
initial native trace, init order, IRQ/error lines, firmware binding and PM state.
Wait for final-result/finalizer-action, then run review-ac-result.py before any
next experiment. If known-good returned, archive AC's prior journal and fallback
outcome. Never run automatic playback, capture or live device rebinding.
