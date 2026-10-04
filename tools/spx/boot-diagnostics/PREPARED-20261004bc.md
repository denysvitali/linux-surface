# BC PIL area-query candidate preparation

BC is now terminal. Its actual successful query, unchanged PAS memory failure,
620s baseline and900s known-good return are recorded in
[the actual result](RESULT-20261004bc.md). The preparation record below preserves
the state before that boot.

Latest actual result remains terminal [BB](RESULT-20261004bb.md). Current
known-good boot is `e00a2d25-03f7-4265-b56e-0eac05b234d3`, release
`6.18.3-1-surface+`. BC's three boot payloads/217 module files, ten helpers/twelve
units and six timers are installed. Independent deployment review03:06:18Z
passes84,669 source paths, exact frozen helpers/units and candidate/recovery
hashes. Known-good default/empty next/no EFI BootNext verify. Outgoing touch
is ready with one−22 bus error and other counters zero. No BC boot selection
or hardware result existed at deployment review. Fourteen-file handoff freeze
`7f2139ebca54e8f6cd79fa08ce5feceab1270d01258b4705d78a0d20cef8c22d`
pins checker `1a2d15abe6687361a12ffcaae22055348d370172915fc4ca92821d335cf6619e`.
Native same-thread daemon continuation is verified. One checked handoff is
scheduled03:11:38Z with30s initial delay; selection is deferred to that checker.
It rechecks actual identity/source/artifacts/recovery and pending selection,
selects once, then immediately reboots. No actual BC area reply has been
collected. Collect the result before choosing another experiment.

The distinct candidate is `7.3.0-rc2-spx-mainline-20261004bc+`, prepared under
`/var/tmp/spx-mainline-trial-20261004bc`. Its 96,938-record private snapshot
changes exactly qcom_scm.c and qcom_scm.h from BB. The SMC implementation and
all other frozen source files remain exact BB. Configuration changes only
LOCALVERSION; firmware, memory reservation and DTB policy remain unchanged.
Full Image/DTB compilation passes in1,692.077s;202 modules link in353.767s.
Embedded config, both default-zero flags/parameter namespaces, unchanged
source/live/parent configs and exact BB raw DTB verify. Image SHA256:
`876db20ca3c044a830bed586787dba4af0527232cb7db19e5ab5986a7234017f`.
Private217-file module tree,55 embedded modules/logger, clean depmod/vermagic,
VIDEOCC alias and exact retained BB boot DTB now verify. Durable2849-file/
272-link build and1486-file preparation archives independently rehash. All
five compiler warnings match BB. This does not establish working hardware.

Build manifest:
`b342315db3d3b1d4daf3f975f3f271de47b063e980a2f4ecc3e045f05c1a9422`.
Preparation manifest:
`b0a25a51477d4f47741b7023e89cfc9005df2802ce7490463ff57f5688137512`.
Independent archive review:
`e77bb7968f0989b09960ba7f92ddb80de79b77c902bd99cba33bb02b93b40a65`.
Independent predeployment review at03:01:26Z passes84,669 current source paths,
both archives/217 module files, DTB contracts/VIDEOCC alias,45 media fixtures
and unchanged recovery. Installation is the next guarded step; no BC selection
or hardware result exists.
Compressed kernel:
`706da79ad142c4f09d54d47b43bb68281cdf167545e56652b19771ba855fb33e`.
Private initramfs:
`6628dd3b7d54c52719e3fc02b13241fe41fb0924e89b91b5dbb7f8d5afb54be1`.
Retained BB boot DTB:
`4d96be24498f39afc10db917d7be155ee4b0d8314bfdfec924ddf1131594f4a9`.

The original post-link metadata finalizer failed on a repeated dictionary key;
all compile/link and preceding validation steps passed. Original script/failure
are preserved. A separate finalizer independently reverified all artifacts,
embedded config/source/flags/DTB/module order and recovery before writing the
completion record. No compile was repeated. Finalizer review manifest:
`b8cdb20a4ad777a05b7bf712ae612575913babc2a31a942b9156befd06ab1219`.

Frozen source manifest:
`97324a81e10e8e2f7039c0437744d0518cc5d8f3bedc8485edb759ed66d8fb0f`.
Source archive, verified record by record:
`fd5faf2ae5dff5f840b157c2d76eff5c09b60fd000fd121121513d9ed813f5ac`.
Resolved private configuration:
`86f046b08693c74b5e270b93c9fbc9c05850652aaa613a5bde2d172fb644bbe0`.
Live archived AM configuration remains unchanged.

The [offline diagnostic](pas-area-diag-20261004/README.md) makes one zero-spare
PIL command 02000209 before PAS9 image initialization, under a separate
default-off/read-only parameter. Original image/memory calls and returns remain.
Its 403-file capsule rehashes, manifest
`5c48431dd13217778361fa211e717413c5efd7738e29b3daabef7f7780be6404`.
436 native checks/416 comparisons and nine mutated candidates pass/reject;
scoped AArch64 compilation/linking and source style pass. The parser preserves
uninterpreted full raw words; 52 BB fixtures/17 query traces pass, 33 corruptions
reject and actual BB diagnostics replay exactly. No actual device memory bounds
or suitable allocation are established.

The uninstalled runtime plan requires both `qcom_scm.spx_pas_diag=1` and
`qcom_scm.spx_pas_area_diag=1` exactly once. It records values and 0400 modes
at startup. Fifteen helpers/twelve units, one valid/fourteen invalid identities,
two media reference pairs/seven corruptions and the actual entry-construction
body/GRUB syntax pass independent offline review. Strict desktop/touch/Wi-Fi/
WSA/rear idle baseline remains; startup90s, media180s, baseline620s, return900s.
Runtime plan manifest:
`a890f8eeee8f879eb5e821de5e35cf3413f6d7451e28f66781f554ac2d5ece21`.
Independent review manifest:
`a035a46acdabeebc845def177187251abd0430e383ef7d8f6268af8c515c571c`.
Original helper-generation failure is preserved before publishing any helpers.

Terminal BA's obsolete three ESP payloads were retired after actual return,
reference and exact restorable-copy verification. Retirement manifest
`cd08bde016508cf3922966c952f9e476069f1bc6d3ddb812c80bc214ac9941e6`;
63,963,136 boot bytes free. Recovery/BB payloads/modules and menu/EFI bytes
remain verified. The archive is under BB/retired-ba-boot-slot-for-bc/payloads.

The read-only actual-result reviewer retains a failed-query reply without
changing its interpretation. Its actual startup function passes three
explicitly synthetic successful/unknown-a0/leaf-failure cases and rejects five
corruptions, including changed PAS outcomes and parameter mode. It also retains
the frozen baseline replay and normal-return checks. Synthetic proof manifest:
`75aa6784feae55b1afa57c74b37e49531aaa9ce14b183cd942bacf4fc8613e4d`.
No synthetic record is a BC hardware result. If original PAS behavior changes,
the reviewer rejects the expected BB comparison and preserves the failure.

Keep `spx-known-good` persistent, select BC only once after full build/archive/
deployment reviews, and recheck actual boot ID and pending selection immediately
before reboot. User authorization covers a possible manual power cycle; early
EFI/ExitBootServices automatic recovery remains unvalidated. Query completion
alone cannot close D03. All 47 feature acceptance boxes remain open.
