# PAS9 memory-setup diagnostics, 2026-10-04

[BA's terminal result](../RESULT-20261004ba.md) gets past corrected Venus
interconnect parsing, but `qcom_pas_mem_setup()` returns `-EINVAL`. The original
SCM wrapper collapses clock, bandwidth, transport and service errors into one
return. BA's signed firmware and inferred PAS9/fe500000/5MiB arguments remain
unchanged; the secure service's acceptance of that reservation is unresolved.

Three source files now add a default-off diagnostic selected by
`qcom_scm.spx_pas_diag=1` in a future fresh candidate. The parameter is read-only
(0400). Its gate permits only SIP/PIL PAS9 initialization and memory setup.
Normal caller logs distinguish clock/bandwidth failures and transport/service
results. The SMC layer records the original calling convention, call ID,
argument registers and valid raw return registers after the existing operation.
Atomic calls and calls without a device do not receive these SMC logs.

Saturated atomic budgets allow at most four initialization callers, four memory
callers and eight SMC callers, two lines each:32 lines per built-in driver boot.
Invalid service/raw results are marked invalid and not read. No secure call,
argument, allocation, retry, authentication or return policy is changed.
The original caller cleanup and error paths remain. Logging can change timing;
live diagnostic behavior has not been observed.

[verify_diag.py](verify_diag.py) extracts four actual candidate bodies and three
original BA bodies.91 ASan/UBSan checks pass, including80 before/after cases
across ARM32/64 conventions, both callers, enabled/disabled diagnostics and ten
success/failure outcomes. Leaf clock/BW/SMC/atomic operations are mocked.
Ten exclusion cases and saturation check the scope/limit. Production global
declarations supply the default and budgets; the actual parameter declaration
is checked for0400. Five candidate mutations fail: wrong PAS filter, unbounded
budget, lost service return, invalid raw result and default-enabled logging.
Native final manifest:
`b1d8690ad0cf638de889d6746507a9c860daecf0ec7c86f6a17522564e833969`.

[link_scm.py](link_scm.py) independently rehashes96938 frozen BA source records,
with exactly three diagnostic source deltas. It compiles the actual three
built-in SCM constituents with unchanged BA configuration, then checks an
independent relocatable AArch64 link. The diagnostic gate resolves and the
compiled parameter namespace is exactly `qcom_scm.spx_pas_diag`.
The relocatable aggregate is
`59e02d1d0aea6142ef6622f477774fdf572dcf7583887664f5934e4461603b41`;
build review manifest:
`fd5ed74e557931542646a370a60f4003ad2e29ae61d1a815ab445ee91e59c745`.
This is not a linked full kernel or a hardware boot.

Source-style checks pass with commit message/signoff requirements excluded:
`e48023bff009a5464fbd7b29769d2dda2b7b251cff5f60b6a93cac753e5e51c4`.
Initial missing mock/compiler-warning failure, control-selection failure,
wrong built-in aggregate target and metadata-only style rejection remain
preserved. Original BA archives and recovery artifacts are unchanged.

Private stage: `/var/tmp/spx-pas-diag-20261004/`.
Durable192-file evidence under BA/offline-pas-diag-20261004 independently
rehashes, including final checks, all failed preparations and original sources.
Manifest:
`2ef2de5057329f649216ed2a418493f5ea02758f90cffd3ae10560253528e9c2`.
84669 current compiled source paths match BA plus exactly these three changes;
candidate/recovery artifacts and current boot/default/pending selection reverify.
Current known-good is a824008e-cf43-4287-84f8-4e930fa41a06, persistent default
known-good/empty next/noBootNext. No fresh full candidate is installed or selected.
All47 hardware acceptance boxes remain open.

The fresh [BB candidate](../PREPARED-20261004bb.md) now has a complete verified
Image/board-DTB/all202-module build and private217-file module tree/55-module
initramfs. Its full linked gate/zero-initialized flag/parameter namespace,
exact BA boot/raw DTBs and source/config/payloads verify. Independent durable
archive review passes958 build files/272 links and916 preparation files;
predeployment review checks84669 live source paths and unchanged recovery.
BB remains uninstalled/unselected; hardware PAS results remain unobserved.
The separate PAS log reviewer passes52 synthetic traces/rejects14 corruptions,
with121-file manifest2363d936…f2e. These checks close no hardware feature.
