# AI: silent right-side command-history diagnostic

Parent AH bootb1485998-0a40-46b7-bd77-88796fa99a89 passed620.60s, fallback
stopped; frozen388-file result05f44a37..., reviewab33bf28..., post16file9cde5272...
records old source/config before command-history implementation. AG pin2
corrected topology matched right2110/unique4 but failed one native CMD error;
AH same artifacts on pin1 matched left2110/unique3 without selected errors.
Different boots do not isolate the cause. AI observes existing submissions.

Distinct release7.3.0-rc2-spx-mainline-20260930ai+,187 modules/202 module files,
private logged initramfs; all three payload paths20260930ai. Rebuilt corrected
DTB byte-exact AG5adbda17...; config only LOCALVERSIONae->ai. Driver33aeace2...
is the frozen sanitizer-tested candidate: default-off/read-only Surface selector,
16 software-history records, at most2 existing CMD-error dumps/34 lines.
Snapshot before existing recovery, print after existing FIFO flush. No extra
register access/write/retry/poll/delay, no changed FIFO/xfer/caller returns.
Recent requests/bridge return values and post-submission software timestamps
are not hardware acknowledgment or causal identification. Instrumentation may
perturb timing; diagnostics are not a pass or a workaround.

Compared with AH command line, only attempt marker, pin1->pin2 and new
soundwire_qcom.spx_cmd_diag=1. Compared with AG the diagnostic and distinct
release/payloads are added. Nativeforce/core/watchdog0/exactwindowsN/no worker;
GPIOsoftware4/1c/pin2/raw-1/swapN; exactlytwo DT-backed2110/3+4 codecs; right
Attached/device1, right-specific init-entry, slot1 unique4 rc0/0. Left may remain
UNATTACHED. Keep strict no selected native command/bus/FIFO/clock-stop/status/
init errors plus baseline/DSP/taint/touchready and8windows/48events/384budget.
The history parser additionally requires diagnosticY and valid bounds/order.
Empty history is permitted when no CMD error dumps occur. The separate pin2
diagnostic never controls fallback; a native error still fails the full scope.
No audio/PCM/capture/input-event reads or live restart/reset/rebind are included.

AI full source authority build/source.diff0d716fbe..., config869dadaa...;
1170 build files/272 symlinks manifest3ef511f2..., modulesefd079b1...;
independent buildd60063b0..., installed507567bc...,16 deployment sourcese3bc0958...
verified. The cloned15-file DT archive preserves historical AG source/config;
current full AI source/config are in build. Kernel9c86fc4b..., initramfs42de59d1...
private logger byte-exact inherited AH, extracted new modules verified separately.

To fit payloads, unreferenced historical /boot/vmlinuz-linux-surface.bak-
20260610-214101 (16206552bytes, SHA1c2a9e1c...) was copied/rehashed to private
AI/retired-unused-backup then removed. Six retirement records manifesta859684d...
include configs/helper/report and restore instruction. Active AH AE/AG payloads
and known-good artifacts unchanged. Recovery default remains spx-known-good;
next_entry empty/BootNext absent at preparation. Collector620/fallback900.
Native continuation current thread and promptcontinue verified, no legacy marker.
Independent scope/AST/GRUB/systemd/payload/source/config/hash/negative parser
checks precede selection. Authoritative selection state is private attempt.json.
One guarded selection; immediate check of preboot ID/pending selection/artifacts
before reboot. Collect AI result before choosing another experiment; never
blindly re-arm AG. EFI/early-kernel recovery remains unvalidated.
