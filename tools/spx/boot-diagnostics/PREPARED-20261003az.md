# AZ VIDEOCC correction: preparation record

Actual AZ startup/baseline/return is now recorded in [AZ](RESULT-20261003az.md).
AZ is terminal; never re-arm it. The sections below preserve the preparation
state and hashes before that boot.

At preparation, the latest actual result was terminal [AY](RESULT-20261003ay.md), which reached its
scoped baseline but stopped Venus before probe because its clock supplier was
disabled. Its guarded return reached known-good
`57b50440-3c7b-4626-bcc8-b2f065b697f6`. AZ addresses that observed missing
dependency, preserving the previous Iris1 implementation and actual boot DTB.

Fresh release: `7.3.0-rc2-spx-mainline-20261003az+`.
The96938-record snapshot differs from AY only in `arch/arm64/configs/spx.config`,
adding `CONFIG_SM_VIDEOCC_8150=m`. Effective config changes only that option
and LOCALVERSION. GCC/GDSC and all previous camera/RTC/video source stay exact.
[build-az.py](build-az.py) streams/rechecks the self-contained source archive,
builds full Image/board DTB and202 modules, checks embedded config and confirms
exactly one added module: `drivers/clk/qcom/videocc-sm8150.ko`.

Full build completed2026-10-03T21:17:34.983087Z: Image/DTB1711.107s, modules351.690s.
Private [assembly](assemble-az.py) has clean depmod,202 matching vermagic strings
and217 module-tree files. The actual DT fallback alias resolves to
`videocc_sm8150`. Its raw base DTB and actual provider boot DTB remain exact AY.
The initial check expected54 embedded modules and failed: kms embeds the new
clock provider too, giving55. A first finalizer also found a stale private helper
filename. Both original sources/stdout/stderr are retained; no payload was
rebuilt or overwritten to hide them. [Final verification](finish-az-assembly.py)
checks that VIDEOCC is the only additional embedded module and all55 payloads
match the202-module release, with the private logger exact.

| Artifact | SHA-256 |
| --- | --- |
| Source manifest | `61b41f3cfb5e5436d2f415939f36c6dac5a35fc05267b9e044944197a76d098b` |
| Source archive | `a30dc283908b051103a661a6f5ad67b1c29020b86d9d67d23a98f7d43d5bcd8d` |
| Effective config | `998d388ca22c0a7e12f25a4d885b76021d9f589213b482f2622f706387c1fb86` |
| Raw Image | `e698287076d9e3f2e8fdf20fe48bd5b12e3152aa15fd4f189f80842d5cafa147` |
| Compressed kernel | `a053930c4511a0518d25e2f05dd4a4296cda5a113c36c92625533fa496d14376` |
| Private initramfs | `ed49b678f3d16ef3e368f3b972839ced47b0ecfa9b21ab06f1958775274aff9f` |
| Actual boot DTB | `59bc82d2959d09da7e5bec38b616bba55406e50f53718dcc1f17ed89dd2b2856` |
| Installed firmware00042 | `4e93d34504da96320775476bbd509aa06f985b48fb781d4436c8eb812b929928` |

Private stage: `/var/tmp/spx-mainline-trial-20261003az/`.
Durable archive:
`/var/lib/spx-boot-diagnostics/attempts/20261003az/`,828 build files/272 links
and293 preparation files. Its source archive was independently streamed and
all96938 members rechecked, with exactly one source delta from AY.
Build manifest: `0f21bef8aa19a51badc67c51e4d6e9e5859753a9b5ec7881c61fe72b6984df4c`.
Preparation manifest: `a8f030ada3ad41e70ce42c28f4a16104fe5e2219269b6dccd8a560f67a406830`.
Archive review: `199b894722b2df9f811b4ccfa43543893de64c0bde56a00f3dae13ccb40fe104`.
Independent pre-deployment review at2026-10-03T21:29:33.349606Z rehashes those
trees, checks84669 live source paths,217 staged module files and45 fixture files,
resolves the OF alias again and verifies the unchanged AY boot DTB/recovery.
No AZ installation or boot selection had occurred at that review.

Subsequent deployment installs the sealed AZ module tree/three boot payloads
and fresh helpers, then rechecks the actual known-good boot/source/recovery.
Independent installed review at2026-10-03T21:34:35.157911Z rehashes84669 live
source paths, verifies ten helpers/twelve units against the exact frozen plan,
passes actual installed systemd unit verification and confirms six timers enabled.
Persistent known-good/empty next/noBootNext remain verified; AZ has not yet been
selected at this review. Global diagnostic metadata now names AZ, so historical
AY loaders must not be used for current recovery/collection.

The14-helper/12-unit frozen runtime plan passes AST/systemd verification, with
one valid/six rejected boot-identity cases. Startup90s, gated media180s,
baseline620s and known-good fallback900s are prepared. Plan manifest:
`a3b4120d5ff889df61144080703e72bd98144d50b8995cad8a47a125c194ce24`.
Its durable35-file preparation capsule under AY has manifest
`7bea7f9eb084d3c9288b68a4e8c16d841c8ee2dd563bbae29074faef05b96d6f`.
[Real-film fixtures/runner](video-media-20261003/README.md) are prepared for
normal Venus binding and both video nodes, with actual device FD witnesses,
bit-exact decoded output and encoded frame/quality checks. No media run yet.

The obsolete unreferenced AQ ESP slot was archived/rehashed before removal,
freeing41,281,182 bytes. Known-good/AY payloads, modules and GRUB/EFI bytes stay
exact; recovery/default/empty pending selection reverified. Root-owned restore
capsule: `AY/retired-aq-boot-slot/`, manifest
`d14d1afb02d2e4871ccbe2e2d5c673a9f35407a5abb24164e0d5a08cfb531181`.

Complete [archive verification](archive-az.py), independent preparation review
and installed helper/unit/identity checks before selecting this trial once.
No firmware/PAS/HFI, decoded/encoded media, sustained or suspend acceptance
follows from this build. All47 hardware boxes stay open. Early EFI/kernel
automatic recovery remains unvalidated; the user-authorized reboot loop applies.
