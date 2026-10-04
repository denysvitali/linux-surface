# BB PAS memory-setup diagnostics: private candidate

BB has now booted once. Read [actual BB result](RESULT-20261004bb.md) for the
observed raw SCM error and regression evidence. The preparation records below
describe the historical state at each review; they do not establish hardware
acceptance. Baseline/actual guarded return review now passes; BB is terminal.

BB is now installed on outgoing known-gooda824008e. Independent deployment
review at2026-10-04T01:03:43.149850Z passes84669 live source paths, exact ten
helpers/twelve units, all six enabled timers and artifact/firmware/recovery
hashes. Known-good remains default, next is empty and EFI BootNext absent.
Recovery touchready/1(-22) bus error remains recorded; strict trial baseline
is unchanged. No BB hardware boot has occurred. Native continuation metadata
selects the same active Codex thread with resume enabled and promptcontinue.

Latest actual mainline result remains terminal [BA](RESULT-20261004ba.md):
corrected ICC parsing reaches PAS memory setup, which returns -22. Its guarded
return reached known-good `a824008e-cf43-4287-84f8-4e930fa41a06`, currently
running `6.18.3-1-surface+`. Persistent default is `spx-known-good`, next is
empty and EFI BootNext absent. Recovery touch is ready with one -22 bus error;
that is preserved evidence, not clean touch acceptance.

Fresh release: `7.3.0-rc2-spx-mainline-20261004bb+`.
[build-bb.py](build-bb.py) has frozen and stream-verified 96,938 BA source
records plus exactly the three verified SCM diagnostic changes. Configuration
changes only LOCALVERSION. Full Image/board-DTB linking passes in1706.129s;
all202 modules link in351.599s. Final source/config verification passes at
2026-10-04T00:50:27.309312Z. The embedded configuration is exact; the diagnostic
gate resolves, its flag is in zero-initialized BSS and the parameter namespace
is correct. Raw board DTB is byte-exact BA and all five warnings match BA.
Linked-image review manifest:
`b163b23840734b173300a8572b7d6be7ea2eba805001b3040df5485c4a9eeb56`.

Private assembly passes at00:52:19.351872Z:217 module-tree files,202 exact
vermagic strings, clean depmod/provider alias resolution,55 exact embedded
modules and logger. Retained boot DTB and raw compiled board DTB both remain
byte-exact BA. No installation or selection occurred at those private checks.
Independent durable archival verification passes at00:54:31.973325Z:
958 build files/272 links and916 preparation files, including the streamed
source archive, full payloads, diagnostic checks and terminal BA evidence.
Archive review:
`3c1839b531118484b047f6144490c2ad7fed76644bd5b8c111fc9afa5cbe485e`.
Build manifest:
`e222cbf372662fe895a493e76aefee083d8391f2d146e1ccc7b72cecc31a74b0`.
Preparation manifest:
`088829864bd5370fc6e70d181d9b989655e341d96306de8bb26e96b35cac4b2c`.
Durable attempt: `/var/lib/spx-boot-diagnostics/attempts/20261004bb/`.
Independent predeployment review at00:58:11.673730Z verifies84,669 live source
paths, both archives,217 module files/links, DTB provider contracts, VIDEOCC
alias resolution,45 media-fixture files and unchanged known-good recovery.
The same outgoing boot ID and empty pending selection verify. BB is uninstalled
and unselected at this review.

Raw Image:
`bdd0148d148f9fcd68a2dcd9a05ac884f3086eadacd4c4a822031a7299f982f5`.
Compressed kernel:
`0e9763d140cf5a32b6596d5daf252bb721a4bc95c3bc9a905482e0d517168c0f`.
Private initramfs:
`c14516664c7be758bf37f013a2e24d0da0036da1b52ddc85ca1af6299c2dfe53`.

Source manifest:
`daa1485a10a3cb7769238dab01ba8a35af7d90a2156b0b3414fb5f6bf214c5bd`.
Stream-verified source archive:
`aedf4f0067216ed83c888b611639d163fba021e9ab2b3bd5a75bd7304ccb86f1`.
Resolved configuration:
`5eebcc75e9daa8a8b8552e3574d2c3f8daafa6e656a2f522c67a085d6d3d60aa`.
Private stage: `/var/tmp/spx-mainline-trial-20261004bb/`.

The parameter `qcom_scm.spx_pas_diag=1` enables at most 32 messages for PAS9
image initialization and memory setup. Logging is read-only/default-off and
preserves calls, arguments, allocation, retries, cleanup and return behavior.
The [diagnostic capsule](pas-diag-20261004/README.md) retains 91 actual-body
native checks, 80 original/candidate comparisons, five rejected mutations and
three compiled AArch64 constituents with a checked relocatable link. Those
leaf operations are mocked. BB must preserve BA's boot DTB byte for byte:
`4d96be24498f39afc10db917d7be155ee4b0d8314bfdfec924ddf1131594f4a9`.
Its firmware remains the verified installed 00042 image. No address or secure
firmware policy change is part of this experiment.

The offline runtime plan passes 15 parsed helpers, 12 systemd units, one valid
identity and 11 rejected identities, including missing/disabled/duplicate PAS
logging options. Two media references and seven corrupted outputs pass/reject.
Independent review exercises the actual deployment entry body and GRUB syntax.
Plan manifest:
`9fff3050961271879ea10184fc7216af63dfedf1fcb7a31a8aa1dd4f6458e22d`.
Independent review:
`9e3ce4736e0a24e8b5006f4e8b916fe0eefad7766cc5d11185204adc638dc464`.
Nine collectors/reviewer are exact BA behavior apart from BB identity/helper
references. Strict touch and baseline acceptance remains unchanged. Timers
retain 60s provider, 90s video, 120s rear idle, 180s gated media, 620s baseline
and 900s guarded return. No runtime helper or unit is installed by preparation.

The [PAS log reviewer](pas-diag-20261004/parse_log.py) passes 52 synthetic traces
and rejects 14 corruptions. It keeps raw evidence, distinguishes clock,
bandwidth, low-level transport, SCM a0 remapping and secure-service a1 failures,
and rejects incomplete/overlapping traces. No diagnostic messages do not prove
success. Its 121-file capsule independently rehashes and pins all three frozen
BB source hashes, manifest
`2363d93696bff7aa44ace64f0889e7e530aa7c3aaa3c49075c58000928eb2f2e`.

Terminal AZ's unreferenced three ESP payloads were archived and retired after
terminal-return/hash/reference verification. Exact restorable copy is under
BA/retired-az-boot-slot/payloads; 12-file manifest
`e210a59b994c805c2ffa3fee576381c982b029170dde4c08415beb78867ceebe`.
The partition now has 64,024,576 bytes available. Boot menus/EFI, BA payloads,
known-good recovery, AZ source/modules and all results remain preserved.

Early EFI recovery remains unvalidated. All 47 hardware feature acceptance
boxes stay open. Installed BB is ready for guarded one-use selection;
actual PAS and subsequent hardware tests remain unobserved.
