# AB: isolated left-speaker firmware identity matching

AB is installed and independently reviewed from AA boot
`4c68904a-46a5-4eb8-a9ee-3991fbb3c243`. Read authoritative
`/var/lib/spx-boot-diagnostics/attempt.json` for selection state and inspect
actual boot identity before acting. A prepared record is not a boot result;
never reselect a consumed or failed trial blindly.

The **release remains AA**, `7.3.0-rc2-spx-mainline-20260930aa+`.
GRUB loads exact AA `/spx-trial-20260930aa/vmlinuz` and initramfs, with new
DTB `/spx-trial-20260930ab/spx.dtb` and `spx_attempt=20260930ab`.
Decompiled DT comparison proves one string changed: left_spkr compatible
`sdw10217201000` → `sdw10217211000`. Unique3, right2010/unique4, GPIO pins,
port maps, regulator and all transport/GPIO/DAC/diagnostic selectors are
unchanged. The source diff outside this DT file and config are exact AA.
No PCM/playback/capture or live parameter/device changes are scheduled.

AA's independently reviewed 353-file scoped result passed. Its one successful
existing-read transaction before the force worker produced words
21170213/00000010 → bytes13 02 17 21 10 00 → 0217:2110/unique3. The same
extra identity appeared in Z and older local records mention2110 IDs3/4.
Bridge reads are volatile but immediate and may be stale/torn. AB tests a
firmware-matching hypothesis rather than asserting stable physical identity.
Read RESULT-20260930aa.md and AUDIO-AFTER-AA-20260930.md for the evidence and
synthetic attachment/address-routing limits that still apply.

Artifact archive: `/var/lib/spx-boot-diagnostics/attempts/20260930ab`.
Reused `build/` contains AA kernel/modules/initramfs, source/config and logs.
`dtb-build/` contains new/parent DTB, exact source/config/diff, decompiled
comparison, real DTC build log, command/exit result and rationale. 15 DT files,
1,025 reused build files, 272 symlinks, 202 installed module files verified.
Independent install review also verified15 payload/recovery/runtime files,
a336-file preboot snapshot and7 deployment scripts. GRUB/systemd checks passed;
known-good recovery artifacts/default unchanged. No boot slot was retired forAB.

| Evidence | SHA256 |
| --- | --- |
| DT/source archive manifest | `e209f920d045a0572b65d57c137fefc9ba492e8934190fdc251dd9ba1d67d728` |
| New DTB | `97983ecc8fc9a940787e6550071b03d1d8b63ccee00e75f2d10f452f82d7a187` |
| Reused build manifest | `92f2219ca1f4ed0d7db3816b132410200019e12778e633b26368014f569cf5f1` |
| Installation review | `b440530f98ebb4f1e6950d81cf12754a6ebbcbca0e5d046589850c819ddb9960` |
| Deployment source manifest | `e8600ac2088ea99518ce385590ced0940c9c94b7b22f7e8d14272a829ba2f495` |
| Native continuation review | `f535c027e643ad93ea20ae943a811ca72fa9f74b3b248cbb34a674549ab4a5f0` |

Collector at620s, fallback at900s. Success requires the bounded2110/3 trace,
exactly two expected DT-backed codec devices (left2110/3 and right2010/4),
left Attached/1 with of_node ending speaker@0,3, AA GPIO software state,
controller/DSP/card/graphics/Wi-Fi/touch baseline, taint0 and no selected
kernel/WSA FIFO/init/status errors. Archive/hash verification precedes any
fallback stop. Failure leaves return armed. Matching success alone does not
validate physical address selection or audio; no_assign still rewrites forced
writes todev0, and the2010-only worker can assign the unused right descriptor
a duplicate logical number. These mechanisms are preserved for this comparison.

Native continuation is enabled on currentthread, promptcontinue, retiredmarker
absent. One-shot queue plus30s guard rechecks bootID/pendingselection/default,
EFI BootNext, payload/recovery/runtime/module/DT archive hashes and timers
before reboot. Userspace fallback does not prove EFI/early-kernel recovery;
repeated experimental boots are authorized in AGENTS.md.

On continuation first inspect actual bootID/cmdline/uptime andAB timers. AA's
release string/BOOT_IMAGE is expected even forAB; require spx_attempt=20260930ab
and inspect the live left compatible/firmware binding. Preserve initial raw
trace and codec topology. Wait for final-result/finalizer-action, then run
review-ab-result.py before choosing another trial. If recovery returned, archive
prior AB journal and fallback evidence. Do not run automatic audio tests.
