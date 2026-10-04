# BA Venus interconnect correction: full private build and assembly

Preparation is now historical: [BA's actual terminal result](RESULT-20261004ba.md)
records one boot83ebc5bb, corrected ICC parsing, PAS memory-setup failure,
passing620.27s scoped baseline and verified900.25s return to known-gooda824008e.
Preserve all original preparation/rejected guard/runtime-revision archives.

Latest actual result is terminal [AZ](RESULT-20261003az.md). Its VIDEOCC
supplier binds, but Venus fails before PAS/HFI because its four ICC endpoint
tuples omit tags required by the providers' two-cell argument declaration.
The guarded return reached verified known-good
`19cfd105-9780-4c85-995f-625bb1eb0529`. Default remains `spx-known-good`,
next is empty and EFI BootNext absent. BA is subsequently installed but remains
unselected pending final deployment review. Current known-good boot is
`1f30baae-c6b5-403b-855d-6cf9d7040650`; the touch failure and runtime revision
are recorded below. Historical preparation reviews retain their original state.

Fresh release: `7.3.0-rc2-spx-mainline-20261004ba+`.
[build-ba.py](build-ba.py) freezes96938 source records from AZ, changing only
`arch/arm64/boot/dts/qcom/sc8180x.dtsi`: four zero ICC tags. Resolved configuration
changes only LOCALVERSION, retaining VIDEOCC and all previous camera/RTC/video
configuration. Source manifest:
`e54fb2a81aa87d044304829dac6841c87d28709d2fdd2baa72ee56b66758bb75`.
Stream-verified source archive:
`340d67ee8c9658dbb1ff7731e38f40ed3fcc819d37c10ad9a129c6ffab4a7603`.
Resolved configuration:
`d5bcd6307102a47ffa00bb00659fa0ec226944538a213b9abf098bd6e15597cd`.
Full Image/board DTB linking now passes in1701.108s. The linked raw board DTB
also passes provider-contract parsing, hash
`8f68dbfea9d04f9c3ba27125eefa4e77e02cf2a190830b6b2b015f226585a958`.
All five compiler warnings are exact matches to AZ after normalizing the private
stage path; linked-DT review manifest
`465b8469b1237e6290833b9ab68bd0d81db8755e2756231b29420a69ed268b3b`.
All202 modules now link in356.147s; full build/source/config checks finish at
2026-10-03T22:42:00.592192Z. Private assembly passes217 module-tree files,
202 exact vermagic strings, clean depmod, provider alias resolution and55 exact
embedded modules/logger at22:43:54.212196Z. The source snapshot, live/parent
configs and embedded kernel configuration remain exact. No installation or
selection occurred. Durable independent archive review now passes972 build files/272 links and625
preparation files, including streamed source verification and exact source/boot
DT contracts. Archive review at22:47:00.895281Z:
`8295024a6bbd2e9e73ba1852ad0b494cc352930ddff421feb03bf6d82642dcfb`.
Build manifest:
`d59a0650b44d21af97adc3a388448ab7b02753a5ae7ea8f0133185c913ce2b64`.
Preparation manifest:
`00c9ed6be4c7413ade6eb8e25263389161b24ecf314b8177fd23f1ece1225357`.
Independent pre-deployment review at22:49:37.792568Z verifies84669 live source
paths, both archives,217 module files/links, provider alias resolution,45 media
fixtures, source/actual DT contracts and unchanged recovery. BA is uninstalled
and unselected at that review. Durable attempt:
`/var/lib/spx-boot-diagnostics/attempts/20261004ba/`.

Raw Image:
`79959c6b45600e066cce5022934195ed4c4da4e682b9b737bec8c1706da9b1a8`.
Compressed kernel:
`b3e4ee3e9c4dc49aa8639825d003babb496bed2152851e06ad777c778afceee3`.
Private initramfs:
`5d4735eee5adae6588aeb64f960b9d80e4a8b5a4f072d12e45fa792953cff20c`.
Actual boot DT remains the verified4d96be24…4a9 artifact below.
Four-file build/assembly execution capsule:
`ef647900c1ca989db548a06399005a2d77319368e2af6c345ff20994698f6181`.

The actual retained boot DT is reconstructed from AX's pinned provider tree
and corrected frozen BA consumer source. Compared with AZ, only Venus
`interconnects` changes; every other node/property and reservation is exact.
Actual boot DT hash:
`4d96be24498f39afc10db917d7be155ee4b0d8314bfdfec924ddf1131594f4a9`.
[Provider-arity parser](video-power-20261003/video_dt_contract.py) verifies
exact references/arguments for ICC, clocks, resets, domains, IOMMU, memory and
required OPPs on both compiled-source and actual boot DT. Both trees reject
seven malformed ICC controls, including the original missing-tag list, and
pass four binding controls/38 native cases/three broken native candidates.
Those mocked leaf calls establish no hardware sequencing or media result.

Source66-file verification manifest:
`97f0deb7392b8289fc07c619e3055a298a84abbb8ea0c9d5d3e342534c32d6b5`.
Actual boot61-file verification manifest:
`a99e97b9f77f817bee14539805bee13964ede2dfd0b259e1bd54b12d61af91c2`.
Durable225-file offline capsule under AZ/offline-interconnect-20261004ba:
`b4a63ab1a42d25595626e6c48d049e2bd9c33947489ec5c6868ee4b3e6eb3a4b`.
Original malformed AZ/AY DTs and old verifier results remain unchanged.

Private stage: `/var/tmp/spx-mainline-trial-20261004ba/`.
Fresh runtime plan verifies15 parsed helpers/twelve units, one valid/eight
invalid identity cases, two exact reference pairs and seven invalid output
controls. The media parser additionally requires ordered PTS/DTS and unit frame
duration. Timers retain60s provider/90s video/120s rear idle/180s gated media/
620s baseline/900s guarded return. No helper or unit is installed by this step.
Plan manifest:
`ea62257091af4afff2d447df83230451354e980ff361051a2dedba929fd2064d`.
Durable43-file AZ/offline-ba-runtime-20261004 capsule:
`f83efe1be5e1fb50c5e9b7a20d9860ef1cf73c3ec3221965e051dd42c9095db6`.
Strict source-style checks pass with commit metadata excluded; original
metadata-only failures are retained. Style capsule:
`5791ccf915c30cd05b09c3b3de2e8f93b83553df2fcf345082e4cc48a46ee110`.

Terminal AV's unreferenced three ESP payloads are now retired after exact
archive/rehash, freeing41,282,842 bytes. Restore capsule under AZ has manifest
`79b53c0301762193633632e8fe9f039ed89cbaec45ecca021eeca837e7d95f39`.
Current boot/default/GRUB/EFI/AZ and all known-good recovery files reverify
unchanged before/after. The boot partition has64,073,728 free bytes for BA;
all historical source/module/result evidence remains intact.

Complete independent durable archive verification and actual installed/helper/
unit/recovery/identity checks before one-use boot selection.
All47 hardware acceptance boxes remain open.

Installation subsequently completed for all three payloads,217 module files,
ten runtime helpers/twelve units and six timers. The original preboot guard
then rejected touch readiness on known-good19cfd105 (not ready, bus errors1(-22));
BA was not selected. Its raw failure/metadata/logs remain sealed under
`deployment-readiness-failure-v1/`. A normal reboot to persistent known-good
reaches1f30baae-c6b5-403b-855d-6cf9d7040650 with unchanged release/cmdline,
taint4096, recovery hashes/default/empty next/noBootNext. Touch still fails,
bus errors6(-22), all other counters0. Normal shutdown and startup logs are
sealed in `known-good-readiness-reboot-result/`, manifest
`c0f0c6d074300757bac3b5790d7d8e64034ce0ca2ab63a1d01647ef7eb42cb2f`.

The separate `runtime-plan-v2/` preserves the original frozen plan and records
outgoing known-good touch failure. It updates only the installed boot guard;
BA's strict ready/zero-counter touch baseline is unchanged. One valid/eight
invalid identity cases, two reference pairs/seven malformed outputs and twelve
unit checks pass. Revised plan manifest:
`962dc90bc83412ced9faef999873c176a2eb876786912bfd22f7f1020e31a739`.
`runtime-revision-v2/` retains original installed guard/global and local metadata
before any revision. No live SPI or MSM reset was used. These preparation and
recovery failures establish no mainline hardware acceptance.

Revised installed preboot and independent deployment reviews pass on1f30baae,
checking84669 live compiled source paths, exact ten runtime helpers/twelve
units, clean installed unit verification, six enabled timers and all candidate/
recovery hashes. Default known-good, empty next and noBootNext remain verified.
The actual preboot review explicitly records touch not ready/6(-22).
Revision capsule manifest:
`31057cf6bd0359edf31b5a735b05b66a2f5934cc729422a4b1ad6388b2c429ce`.
BA is prepared for one-use selection followed by actual startup/media/strict
baseline and guarded900s return collection. Early EFI recovery stays unvalidated.
