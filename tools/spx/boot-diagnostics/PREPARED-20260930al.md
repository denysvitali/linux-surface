# AL: exact AK artifacts, isolated silent pin1 control

AL reuses exact AK release7.3.0-rc2-spx-mainline-20260930ak+ and allthree
/spx-trial-20260930ak/ payload paths. Require spx_attempt=20260930al to distinguish
this boot. Selection state is authoritative only in private attempt.json.

Source/config/kernel/modules/correctedDTB/private-initramfs are byte-identical to
verified AK. Both detached-control guards retained. Build1242files/272symlinks,
202module files/187KO/vermagic,15historical DTprovenance files preserved/rehashed.
Fullsource authority is build/source.diff, not historical dtb-build/source.diff.
Build manifestb5dfed91..., source2325ca7b..., config50118c6b..., modulesa444629f...,
kernel119fab35..., initramfsc2610da8..., DTB5adbda17.... No new build or boot-space
retirement is needed; all protected recovery artifacts remain unchanged.

Only two cmdline tokens change: attemptmarker AK->AL and enablepin2->1. Strict
scope selects left2110/unique3 Attached/device1/left-init/DTspeaker@0,3, identity
unique3 and GPIOsoftware2/1a; exactlytwoDT-backed2110 nodes remain mandatory.
Nativeforce/core/watchdog0/exactwindowsN, bounded commanddiagY16/max2/34lines,
enumdiagYmax8 transactions, touchdiagY8windows/48/384, other selectors unchanged.
Selected nativeerrors and graphics/Wi-Fi/touch-ready/DSP/card/taint0 baseline
failures still fail. Separatepin1diagnostic does not controlfallback. Collector620/
fallback900, clean touchstartup reportedseparately from mandatory finalreadiness.

AK401file finalmanifest5159ef06... passed621.14s; fallbackstopped after verification.
Right2110/4 Attached1/initonce, nativeerrors0, no error-triggered history dumps.
Touch sixwindows118records with a failedopen/3invalidheaders before laterready;
finalready/bus3(-22), cleanstartupfalse.17post4df970d5... froze source/config/results.
AI/AJ/AKcomparison1790633b... proves source/DT/selector/config boundaries and
unchanged strict expression; separateboots do not establish reliability or HW
error causality. Read RESULT-20260930ak.md/AUDIO-AFTER-AK-20260930.md.

Before queue require hashes/source/module/initramfs/GRUB/systemd/runtime/recovery/
criteria/nativecontinuation checks. Keep known-good default, select ALonce and
recheck actual bootID/pendingchoice immediatelybefore reboot. Current verified
AK bootdb98e8ac-8aa3-44d4-8899-47c4fab5fb07 is the parent. CollectactualAL before
another experiment. No both-pin/address/routing change, manual audio/PCM/capture/
input-event read, or live reset/rebind/restart. EFI/early-kernel recovery remains
unvalidated; repeatedexperimentalboots explicitlyauthorized.
