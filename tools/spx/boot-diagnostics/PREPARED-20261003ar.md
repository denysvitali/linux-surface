# AR firmware touch delay candidate

Read live identity, attempt and selection before acting. Actual AR boot
`5b14cce2-951f-4b43-a786-3cd2339f79b5` passed its620.97s scoped baseline with clean
touch startup. Read RESULT-20261003ar.md for verified scope and hashes. The outgoing
known-good boot was `991a6fbd-2217-4f93-8185-287a223a13f6`, release
`6.18.3-1-surface+`, following AQ's verified failed trial/return. Never re-arm AQ.

AR is fully built and independently archived, with distinct release
`7.3.0-rc2-spx-mainline-20261003ar+`. Deployment and independent installed review
are complete; one-shot selection and actual incoming result are now verified.
The request marker is exclusive and must never be repeated. Earlier prequeue
records preserve the preparation state; the actual result supersedes it.
The goal remains the full hardware checklist, with all47 acceptance checks open.

The isolated source has96,798 records, all independently streamed and verified
from its complete archive. Only board touch timing and rear lifecycle source
changed among compiled inputs versus AQ. The corrected config changes LOCALVERSION
and eight CCI/rear/V4L2 settings; rejected radio/lens defaults and original logs
are retained. Live AM.config stays unchanged. All193 modules compile/link, adding
exactly six and removing none. The208 staged files, all release vermagics and54
embedded initramfs module payloads/private logger verify. Image compilation took
1689.49s with AQ's same five ELF/SMMU stack-frame warnings; modules342.74s with
no warnings/errors. Both actual Image and compressed kernel independently yield
the exact intended embedded config. No historical-export camera module is deployed.

The DTB adds only `/ts-5p0-regulator/startup-delay-us = <300000>` relative to AQ.
Every other property/node and memory reservation matches. The existing provider
subtree remains; no CCI, camera sensor or CAMSS node is added. Provider/fixed
regulator schemas emit no diagnostics. Camera driver modules are built for later
integration; this boot requests no sensor probe, rail consumer or capture.
No single successful startup would establish timing causality or reliability.

Hashes:

- Full source archive: `488d6705fbdea620d59cdd67f73c63df5dcf9256a384e7a49cea1c421bf358f2`.
- Build manifest (908 files/272 links): `7e23c627c4b02ee44c0af9d8cc4e693133f510bebd49415d9f0e9b486c1d6df8`.
- Config: `0d315eff642a357d537b614ffd943955cd1700905a0ecf9b191401740a302fb1`.
- Kernel: `408515f77e82eac5803ccf7a6162d1c5a80d20deb1e1688afa3edc534f0fbe0e`.
- Initramfs: `ac00b9013eec27e6fda99fb125d506451993c81a2a68d56a9c1c2d6b6289065d`.
- DTB: `fc567fd1a7593d9b5b430dee4edb7086f3ef3f71179dd2c304801c6b5e49bd3e`.
- Independent actual embedded-config proof: `620504e2c79e6d288f64710d0d489ac8641d1fab5bb76b4cea1a6022b2317d0c`.

All artifacts are private under
`/var/lib/spx-boot-diagnostics/attempts/20261003ar/`. The separate130-file disabled
rear-only DT/schema draft is archived in `build/offline-rear-only/`; it is not AR's
boot DTB. Its manifest is7aff1a4a..., with five negative schema checks and seven
unchanged pre-existing TLMM diagnostic groups. See its README for mapping limits.
Touch reviewer replayed real failed AQ/clean AP logs, reports missing anchors and
rejects corrupted metadata; two-file proof manifestcd21cac6... is also archived.
The first archive recursively skipped four nested rear-draft source files. Its
records are preserved in initial-archive-filter-failure (manifest58c23ed1...).
All four were restored exactly; all original904 files and boot payloads remain
unchanged. A fresh full-source review and complete staged-file/link comparison
passed, along with internal130-file draft evidence rehash.

Installation through deploy-ar.py, independent review-ar-install.py and the
full guard in actual systemd service context have passed:208 installed module
files,908 archived build files and5183 protected recovery module files/links.
The service guard ran without SUDO_UID and preserved empty next_entry and the
known-good default. Its hash is
`3b7ad1a1fe56c28d628b6a40ed3945f5d9a31bfe3ef10a3c608070c737a45f3e`.
All12 strict baseline predicates are unchanged. AR's60s/620s/900s timers are
enabled and inactive on known-good. The53-file outgoing snapshot manifest is
`2b95418e3ec6c385355e98ff5f6fb6d91f240dd94353d4fd7931654639ad9467`;
the23-helper deployment manifest is
`aa21b2c5c74cd50daf9e0f6da6ef2b66b1dfd3c32730ce5f1e6cca4a49184d77`.
The outgoing known-good collector/kernel log includes legacy touch reopen
failures. Known-good's
out-of-tree taint4096 and idle not-ready are recorded recovery state, not a clean
mainline functional baseline. AR's incoming strict criteria still require taint0
and clean touch/graphics/Wi-Fi plus the inherited audio diagnostic predicates.
Verify this session's native daemon continuation, freeze complete prequeue records,
and queue only through queue-ar-once.py. It creates an exclusive request marker
and schedules a30s guard that freshly rechecks boot ID/selection immediately
before reboot. Keep known-good default and every recovery artifact protected.

On actual continuation:

1. Read this document, LOCAL-PROGRESS.md, PORT-CHECKLIST.md and actual boot ID,
   release/cmdline, attempt.json, selection and reboot-check-passed.json. Never
   repeat the request marker or infer successful boot from queued state.
2. On actual AR, run review-ar-handoff.py. Outgoing known-good lacks the newer
   candidate's shutdown logger; absence of such markers proves no rail-off claim.
3. Review the60s read-only camera-provider result with review-ar-camera-provider.py.
   Registration/21 sampled controls remain separate from consumers and capture.
4. After the620s strict finalizer, run review-ar-result.py and review-ar-touch.py.
   Review raw reset-assert→regulator-enable-return→reset-release chronology,
   first probe and later opens. Software timestamps do not measure electrical rails.
5. On failure leave900s fallback armed, verify actual recovery and archive both
   boots before choosing another experiment. Never blindly retry a failed image.
   On a scoped pass, continue the full acceptance checklist and preserve regressions.

Existing authorization covers repeated boots/manual power-cycle risk; automatic
recovery after EFI handoff remains unvalidated. Do not reset/rebind live touch/MSM,
unload pinned audio, restart ADSP or enable the old all-camera prototype. A later
rear-only identification experiment needs actual baseline review and its own
complete source/DT/artifact/collection provenance. Front/IR/CAMSS supplies and
all listed physical hardware acceptance remain open.
