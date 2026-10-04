# AK: detached BOOST Switch guard, silent pin2 trial

AK is a distinct7.3.0-rc2-spx-mainline-20260930ak+ kernel/module/private-initramfs
build prepared after AJ's verified return to known-good
d3b9f9b1-7e95-4963-8225-adf840755102. Selection state is authoritative only in
private attempt.json; this document does not establish selection or a hardware
result. Allthree payload paths are AK-specific.

Only functional source delta vs AJ: set_port rejects BOOST Switch changes with
-ENODEV when the existing availability helper reports a detached enumerated-mode
slave. Check occurs before port_enable changes or boost_ctrl's write/sleep.
Attached/nonenumerated and otherthree software-only port controls keep original
behavior. Existing PA gain guard retained. Native object0/no warnings,256 actual
C differential cases pass ASAN/UBSAN. Entry-time status does not serialize an
asynchronous subsequent detach; no hardware fix or error causality is proved.
Config only LOCALVERSION AJ->AK, no GPIO/routing/retry/touch/policy delta.

Build1242files/272symlinks,202module-tree files/187KO/vermagic records. Fullsource
and config: build/source.diff and build/artifacts/.config. The15-file copied
historical dtb-build retains AG provenance, with no additional DT delta.

| Artifact | SHA256 |
| --- | --- |
| Kernel | `119fab35ce26605e992c852481dcdef4557fdb78bed4d23cff340f496620b959` |
| Initramfs | `c2610da85367e915066386b9c8bb032640c1582b0e100c2f58769d4eb3ef0975` |
| Corrected DTB, exact AG/AI/AJ | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |
| Config | `50118c6b741e214f87c4ed79a53e17239db896726bb7a5e35034d18de59dfa8c` |
| Fullsource diff | `2325ca7b00083417934ec0f27024289c1a8be56136207736747198b2b86050e9` |
| Buildmanifest | `b5dfed91884d62a55cf36a16c16fce10781d2b4317db0e31595d21b0b11edf15` |
| Modulesmanifest | `a444629f4708adf0defd799e35695883ba562032fd9795b4babebd3878cb4841` |

Command line only attemptmarker AJ->AK. Pin2/raw-1/GPIO4/1c, nativeforce/core/
watchdog0/exactN, right2110/unique4DTmatch/Attached1/initentry/exactly2DT2110nodes.
Collector/judge reproduce AJ's strict criteria after identity substitution.
Selected nativecommand/FIFO/bus/clockerrors and graphics/Wi-Fi/touch ready/
DSP/card/taint0 baseline failures still fail. Separatepin2diagnostic never controls
fallback. EnumdiagY max8transactions, cmd_diagY last16/max2dumps/34lines,
touchdiagY8windows/48records/384lifetime; software-only diagnostic limits retained.
Collector620/fallback900, frozen final readiness mandatory; clean startup reported
separately. No manual audio/PCM/input/capture or live reset/rebind/restart.

AJ397manifest1bdd8356... failedonlynativepath, touchedready/allcounters0,
lastdevice0write980b312a->BOOST_EN_CTL. Actual900fallbackreturnedcurrentknown-good;
567recoverymanifest1c69b17d..., original16post344b4ac9...frozen before BOOSTguard;
12candidatecc510b48... preserves exactsource/tests/logs. AJ not re-armed.

Boot space: inactive/unreferenced AA slotspx-trial-20260930aa was privately copied
and allthree payload hashes verified against AA's original attempt before removal.
Retirement archive retains payloads, currentGRUBconfigs/helper/report/restore
instructions. ActiveAE/AG/AI/AJ and recovery artifacts verified unchanged.

Before queue require installed/prequeue/source/config/modules/initramfs/GRUB/
systemd/runtime/recovery/scope checks, current continuationthread/prompt/livePID
and archives. Keep known-goodpersistentdefault; select AKonce and recheck bootID/
pendingchoice/hashes immediatelybefore reboot. Collect actualAK before choosing
another experiment. EFI/early-kernel recovery remains unvalidated; repeated
experimentalboots explicitlyauthorized. Read RESULT-20260930aj.md and
AUDIO-AFTER-AJ-20260930.md for evidence and limits.
