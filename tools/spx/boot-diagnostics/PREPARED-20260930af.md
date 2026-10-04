# AF installed: silent pin2 native enumeration

AF was prepared and verified from AE boot
`1b26cb6c-0e7f-4a3b-a290-f3bf44a6855c`. Read the authoritative
`/var/lib/spx-boot-diagnostics/attempts/20260930af/attempt.json` for current
selection state. This document records preparation, not an observed AF result.

Exact AE kernel/187 modules/private initramfs/source/config and AB-identical
DTB are archived again:1084 build files,272 symlinks,202 module-tree files,
15 DT source files. Release and BOOT_IMAGE remain
`7.3.0-rc2-spx-mainline-20260930ae+` and `/spx-trial-20260930ae/vmlinuz`.
All three payload paths remainAE; require `spx_attempt=20260930af` on return.
Only the attempt marker and `wcd934x.spx_wsa_en_pin=1->2` change. No new boot
payload consumes space and no recovery or active kernel artifact is retired.

Read RESULT-20260930ae.md and AUDIO-AFTER-AE-20260930.md. AE passed at620.35s
with five clean logged startup windows, zero errors and native left2110/3.
That is one observed boot and does not establish reliable startup or acoustics.
AE's376-file result and364-file post-result snapshot are frozen and hashed.

AF software GPIO expectation is DIR0x04/VAL0x1c with selector2 and one pin2 log;
raw overrides remain-1 and port swapN. Cached GPIO and unchecked masked-update
logs do not measure physical pads or establish which speaker is powered.
Force/core/watchdog0 and exactwindowsN remain unchanged. The existing touch
logger stays bounded to8 windows ×48 events,384 lifetime; it adds no new IO.

Collection620s/fallback900s. The full AE functional criteria remain unchanged
apart from GPIO expectation. Firmware topology/left attachment remain strict.
The separate pin2 diagnostic field requires known paired rc0/0 identity logs,
native/GPIO/DSP/controller/graphics/Wi-Fi/touch checks; it does not control
fallback or waive firmware matching. A third unbound2110/unique4 device is
useful evidence and fails the strict baseline. Criteria must not be changed
after observing the result. No audio/PCM/capture/input-event read, live restart,
reset or rebind is included.

Independent validation rehashed the complete artifact trees and recovery/runtime
payloads, confirmed exact current source/config, verified the four systemd units
and GRUB syntax, and checked Python AST/global names and whitespace. An AST
audit proves seven AE scope/native/topology/identity/touch/DSP predicates are
unchanged. Archived AE trace replay and five negative pairing cases verified
the new separate diagnostic classifier. No hardware test was added.

| Evidence | SHA256 |
| --- | --- |
| Build1084-file manifest | `dafc7606cb237397e8355a0814cebe6a31e517d5a354c3193adba0b091dc8b0e` |
| Module202-file manifest | `716e1a002137f99d881c49370075706225b36b1030b5fc82f7106f30e077a086` |
| Installation review | `ac4298463ff62439103e864efe0373e8bc8526076b83784eb57685925d752520` |
| Deployment10-source manifest | `2ce573cfd0e11376ace6103066ca9963cd0189f4c32bda564b64d497df0e19da` |
| Native continuation review | `9a3b06fd293e19c5628c673fae0a3d0179703847e8a3dad303757f37905a9aa0` |
| Independent prequeue review | `37823863a2953918aa14dbc24f6278ae7297309c15752086ec2501b081e77440` |
| AE364-file post-result manifest | `dca8b9baca4e2326fd901a6999c4508f7bab17677d00582aa15a1b8b5016648c` |

Native continuation is configured for the current Codex thread/promptcontinue,
daemon startup and no legacy resume marker. Known-good remains the saved default;
next_entry empty/EFI BootNext absent were verified at installation. Queue once;
the30s immediate guard rechecks boot ID, pending entry, recovery/payload/runtime,
DT source/module hashes and timer enablement before requesting reboot.
Userspace return was verified on AC. EFI/early-kernel automatic recovery remains
unvalidated; repeated experimental boots are explicitly authorized.

On continuation collect actual AF identity/selectors, timer states, raw native
words and raw touch chronology. Wait for final-result/finalizer-action; run
review-af-result.py and decode archived enumeration words independently. If it
failed, allow fallback and archive actual known-good return. Collect the result
before another experiment and never blindly re-arm a failed image.
