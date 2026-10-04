# One-use PIL memory-area query diagnostic

This D03 candidate follows BB's actual PAS9 memory-setup failure. The retained
PIL driver and pinned Qualcomm interface define GET_MEM_AREA command
02000209, one zero spare argument. Static vendor dataflow uses the reply to
bound a dynamic physical allocation. The device's actual reply, Linux raw
register layout and suitability of its existing reservation remain unverified.
See [the retained evidence](../pas-status-20261004/README.md) and
[BB's actual result](../RESULT-20261004bb.md).

Two source files change from BB: qcom_scm.c and its internal header. The SMC
implementation remains byte-exact BB. Read-only (0400), default-off boot
parameter `qcom_scm.spx_pas_area_diag=1` allows one query before the first PAS9
image initialization that successfully enables clocks and bandwidth. Its
single atomic budget never resets. The query uses those already-held resources,
then the original image call proceeds with the original descriptor and cleanup.
Query failures do not replace the original initialization return value.

The existing `qcom_scm.spx_pas_diag=1` diagnostic remains separate. Its shared
eight-call SMC logging budget now includes the query when enabled. Original
caller limits remain four image/four memory messages. At most 34 lines are
emitted with the new query enabled; the previous mode still has its 32-line
limit. Valid raw a0–a3 and result words r0–r2 are logged without interpretation;
failed transports log no invalid register/result contents.

No memory address, length, allocation, firmware, authentication, SMC retry,
VIDEOCC, DTB or configuration policy changes. A new full candidate and one-use
hardware boot are required to observe the query. A query reply will require
independent interpretation before any allocation-policy change.

`verify_diag.py` extracts five actual candidate and three actual BB bodies.
Native ASan/UBSan checks cover 416 before/after comparisons, including 336
query combinations, plus 18 scope exclusions and two saturation checks: 436
checks total. Nine mutated candidates must abort, including wrong PAS/spare,
unbounded query/logging, invalid result use and either flag default enabled.
Kernel atomic, clocks, bandwidth and SCM leaves are mocked; this is offline
behavioral evidence, not hardware acceptance.

`build_scm.py` verifies a fresh 96,938-record BB private snapshot, overlays
exactly two changes, compiles the three actual AArch64 Kbuild constituents and
independently links them with `ld -r`. It checks both parameter namespaces,
diagnostic gate resolution and unchanged private/live configurations. Live
configuration intentionally retains its archived AM release; the private build
uses BB's archived resolved configuration. Recovery payloads/modules/menu/EFI,
actual known-good boot identity and empty pending selection are checked.

`parse_pas.py` is the byte-exact archived BB parser. `parse_log.py` correlates
the nested query before applying it to unchanged PAS records. The reader keeps
full raw words and labels them uninterpreted. `verify_log.py` replays all 52
archived BB positive traces, rejects its 14 corruptions, exercises 17 area
traces and rejects 19 additional corruptions. It checks the shared eight-SMC
and 34-line budgets, failure validity, query/PAS correlation and a saturated
trace; absent diagnostics never imply success.

Original harness, terminal-state/config guard and signoff-only style-check
failures are preserved in separate directories. Successful runs use fresh
directories. Source patch checks exclude commit metadata because no commit
is being prepared. All 47 acceptance boxes stay open. The known-good default
and empty pending selection remain required. Early EFI hang recovery remains
unvalidated.

Durable evidence is archived under
`/var/lib/spx-boot-diagnostics/attempts/20261004bb/offline-pas-area-diag-20261004`:
403 files independently rehashed, manifest
`5c48431dd13217778361fa211e717413c5efd7738e29b3daabef7f7780be6404`.
Native manifest `9da84ad665d61cf17c1cfec65dc5db7739d5e065073f02d2dbb11965404d1175`;
scoped build manifest `b4d1a5835db0537811e58b5fe0225344265d5b84d5bd18fa666a40db1dde3d99`;
log verification manifest `c9b5432d841c0cc5270786dc14d3eb3260215f81fbd0f29690131ba536b5e8d7`.
The revised reader also exactly replays BB's actual eight-line diagnostic.
