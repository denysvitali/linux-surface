# BE static Venus memory reservation trial

BE has now booted once as11e69e59. The static reservation and PAS9 memory
setup pass; core startup then times out-110, with no HFI/video nodes/media.
Independent actual reviews and strict621.08s baseline pass.901.04s actual
return/frozen baseline replay/candidate/recovery/source/config verify; BE is
terminal. Returned legacy touchnotready/20(-22) remains an I01 gap.
Read [actual result](RESULT-20261004be.md) and do not re-arm BE.
The preparation record below describes the earlier pre-boot state.

One-use handoff scheduled06:02:37Z with30s initial delay, timeractive and
empty next verified.18-file frozen preboot manifest:
`572dc15b3122ef8fa8d3db8ff0eeead4d5d9b8eaadbc33bcd0a7c9cbe6e461ca`.
Checker SHA:
`35387017fb3476572c96ffeb4b456848c24344a3303f1be86d154afc5ad946dc`.
Selection is deferred to that exact checker. It verifies source/config,
installed artifacts/runtime/firmware/recovery and current outgoing boot,
selects once, then immediately rechecks boot ID/default/pending entry/BootNext
before reboot. Known-good remains the persistent default. Actual BE static
reservation/PAS/authentication/HFI/media result is pending; collect it before
choosing another experiment. Do not re-arm BD or BE.

BE has a verified distinct offline candidate archive. It reuses exact BC
kernel/modules/private initramfs and release
`7.3.0-rc2-spx-mainline-20261004bc+`; its attempt identity will be20261004be.
Only the board's external DT firmware-memory node changes from BD to
static8d300000/5MiB/no-map. See
[allocation evidence and placement limits](VIDEO-STATIC-RESERVATION-20261004.md).
BD remains terminal; its actual result is preserved. BE's runtime is now
durably frozen and verified. No BE boot or hardware result has been observed.

Independent installed review at06:00:46Z passes13 exact helpers,12 units/six
enabled timers,84669 source paths/config,217 shared BC module files and5183
recovery file/link records. BE's boot slot contains only its2d67375a…d252 DTB;
the exact BC kernel/initramfs paths and bytes remain. GRUB syntax/actual entry
paths/default known-good/empty next/noBootNext verify. Review SHA:
`dc084d2a372c62e7c6070c5c1ca813b2a965b7596801ab5cc4ee5eae63d5a9d7`.
Known-good outgoing433a78d6 is ready with two-22 touch bus errors; this remains
an I01 gap, while the fresh trial retains the strict clean-startup baseline.
Live native same-thread resume-on-daemon-start/continue and session process
verify. Next freeze the outgoing records and schedule the one-use handoff;
selection remains empty until the exact checker completes its final checks.

The3104-file preparation freezes13 helpers and12 units/six timers at60,90,
120,180,620 and900s. It preserves preliminary synthetic tests separately.
Identity checks pass1 positive/16 negative cases; the actual startup interpreter
passes7/17, memory-map checks1/3, and the actual startup reviewer body6/21.
Final helper regeneration is byte-exact. The static node/reg/PAS arguments
are checked; both memblock maps are collected to verify continued NOMAP
coverage and reject a reserved entry overlapping the experimental video slot.
These are offline checks, not hardware results or feature acceptance.
Preparation manifest:
`0195a959d619d4aca3dace3024f5069bf076610d4a6e00155e7ae8379a034b84`.
Runtime-plan manifest:
`7a025961e251507611645adc1085d1e1791a14b96aa065011418ba3735035dd4`.
Independent runtime-review SHA:
`436f265e3d5efe903bc758dde1ba2b3a72ad61bad08cab8361d8f3c45a3f0232`.

A separate full-source review streams all96938 archive records/modes/links,
checks84669 live compiled paths/config and verifies the complete raw/retained
DT reserved-node delta, all other properties/phandles/FDT reservations and
provider contracts. Exact BC build/modules and known-good recovery rehash.
Independent preparation-review SHA:
`e00d37c2fc4fdd2ac02b415abff26ed7426b575ef96b4ac7b5f0299dd673eb18`.

The full96938-record source archive is stream-verified, with exactly one board
delta from BD.84669 compiled paths permit that delta, and the live config is
unchanged. Source archive SHA:
`14767739be01be6d867a6d26c74112b28307c824899c9e13f054fe5fc205d537`.
Source manifest SHA:
`bb381d622b8089abeb5756ff2430fc1c611f4355118e13eb43143fe90ab21666`.

The durable archive is `/var/lib/spx-boot-diagnostics/attempts/20261004be`.
All2849 parent executable-build files and272 links rehash exactly; the
217-file module tree has202 modules, with55 embedded in the private initramfs.
The generic private logger records actual boot ID/cmdline and has no hardcoded
BC attempt. Resolved executable config SHA:
`86f046b08693c74b5e270b93c9fbc9c05850652aaa613a5bde2d172fb644bbe0`.
Parent build manifest:
`b342315db3d3b1d4daf3f975f3f271de47b063e980a2f4ecc3e045f05c1a9422`.

The39-file DT archive includes the exact source/preprocessed trees, old/new
compiled DTBs, provider proof, pinned primary reserved-memory schema and
complete candidate source archive/config. DT manifest:
`57707d786ca6bcaebb531c68fa078b0e2c3f60e8fdd10159da2d5aafa8602884`.
Retained boot DTB SHA:
`2d67375aa71fb14ff66748216ff4879bf1031cadc099d026438498399a14d252`.
Raw source DTB SHA:
`0b86a7f1d18f19f281cf880c5cf5159ff2711116b1f51fe56aa5ad361ecd8928`.
Full642/657-node comparisons permit only the intended reserved node change;
all other values/phandles/FDT reservations and provider arguments match BD.
The copied original provider helper is retained as a proof input; the frozen
verifier adjusts only its expected memory-provider path to the renamed node.
BE's frozen runtime helper adopts that expected path without changing the
original proof input.

The archive also preserves the sealed PGCM dataflow and placement-policy
capsules. Archive-review SHA:
`68e0892d9b32fed854359ef3e310a3111554439c3c5eb9a996ab51a2fb3d69d6`.
Independent package-review manifest:
`dbd51ed2587ff72f4dbc2e588cddd567027ff8532206933c414932b0c1e77b92`.
Known-good433a78d6/default/empty next/noBootNext and recovery artifacts verify.
The live board deliberately differs from BD's frozen source; its scoped
verification is the static-reservation proof, not a passing BD guard.source.

BE's distinct guards/startup collectors/baseline/media/return retain BC's
executable release and update only the required attempt, outgoing boot,
static geometry/provider-path handling and captured memory-map review.
Collect actual allocation/firmware authentication/HFI before media;
preserve failed outcomes. Keep the strict touch/rear-idle/desktop/Wi-Fi/audio
baseline and the900s guarded return. Independently verify the installed
entry/helpers/units/native continuation and recovery/source/artifact hashes,
then select BE once with immediate boot-ID/pending-selection checks.
Do not re-arm BD. Automatic recovery across early EFI handoff is unvalidated.

Static reservation/PAS success and video functionality remain unobserved.
Unknown owner absence, IPA/SPSS placement and the existing ramoops/QSM overlap
remain open. All47 hardware acceptance boxes remain open; full completion
still requires functional checks and combined regressions on one final candidate.
