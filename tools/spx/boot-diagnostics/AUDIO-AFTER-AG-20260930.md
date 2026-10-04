# After AG: corrected-topology pin1 control

AG fixes right firmware matching while retaining one native command error.
The next justified experiment AH reuses exact AG corrected DTB5adbda17...,
AE kernel/initramfs/modules/config/source and bounded diagnostics. Change only
attempt marker and pin2->pin1. This compares single-pin selectors against the
same corrected two-codec topology; AE used the old right compatible and is
not that exact control. Do not enable both pins or relax native error checks.

Predeclare exactly two DT-backed2110/unique3 and2110/unique4 codecs, native
force/core/watchdog0/exactwindowsN/no worker, raw slot1 unique3 with rc0/0,
left Attached/device1 and a left-specific init-entry marker, GPIO software
DIR2/VAL1a/pin1/raw overrides-1/swapN. The right may remain UNATTACHED.
Keep existing baseline/DSP/taint/touch readiness and logger bounds8/48/384;
all selected command/bus/clock-stop/FIFO/status/init errors must remain absent.
An init-entry marker alone is not hardware completion or playback validation.

Collect at620s; preserve fallback900 on any strict failure. Verify AG's actual
known-good return, all artifacts/default/empty selection before installation;
select AH once with guarded boot-ID/pending checks. Source authority is AG
`dtb-build/source.diff`; cloned `build/source.diff` preserves AE's old DT input.
No audio/PCM/capture/input reads or live restart/reset/rebind are included.
Keep spx-known-good persistent default; EFI/early-kernel recovery unvalidated.
