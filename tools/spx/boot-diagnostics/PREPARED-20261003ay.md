# AY Iris1 startup candidate

AY is a fresh full kernel candidate for D03. It connects the previously tested
Iris1 power/IRQ source to a dedicated SC8180X resource, firmware-specific
SYS_INIT2, binding, enabled board consumer and dynamically allocated firmware
memory. Actual video startup, formats, output, encoding and recovery outcomes
must be read from the subsequent real boot record; this preparation closes
no hardware acceptance box.

The full build completes at2026-10-03T19:52:24.910833Z, release
`7.3.0-rc2-spx-mainline-20261003ay+`. It links201 modules, stages216 module-tree
files, verifies matching vermagic/clean depmod/embedded config and embeds54
exact modules and the private logger in its initramfs. The sealed source
archive verifies all96938 records and13 exact deltas from the frozen AX base.

| Artifact | SHA-256 |
| --- | --- |
| Source manifest | `d615df71827c76b05bf1db0619b9660eb8f3d993088486a4d869e8d94a205308` |
| Source archive | `ca9735d4ed70e537bd9cb04d0a3331f575bacb88c32fb8f468baa5e2c2750721` |
| Effective config | `75665e3df65b248ad1eb9bc85d0d1900574081bbfb70e2a0bc8cd7583e0c4cd5` |
| Installed compressed Image | `c3f4c92ced19e8b867c4343df2fb023ad1c19ed25f26261d74aa1b4b53b79fc2` |
| Private initramfs | `325bb46571c23c682bfd561d8f128e06835e17d3ff8cd953cb989331da03420d` |
| Candidate boot DTB | `59bc82d2959d09da7e5bec38b616bba55406e50f53718dcc1f17ed89dd2b2856` |
| Installed firmware00042 | `4e93d34504da96320775476bbd509aa06f985b48fb781d4436c8eb812b929928` |

Durable `/var/lib/spx-boot-diagnostics/attempts/20261003ay/build` contains794
files/272 links, manifest
`d7694406594489d3a6f560488efae037fb364e6aec650499f4a394906230a3bd`.
Preparation209 files, manifest
`64f7397faa4f714d789f42e034d0ae3ca3fd931d87a0ec48d0dc6d9a0ad2a458`.
Independent preinstallation review rehashes these and checks84669 live source
paths against the candidate, all5183 known-good files/links, recovery payloads,
EFI images and persistent default. It observes boot
`b6b4f20b-376f-4577-b282-677ad4ae0ec8`, release`6.18.3-1-surface+`, taint4096,
empty next selection and no EFI BootNext.

The provider boot tree preserves every existing AX property value/reservation.
It adds nine nodes and only two new existing-provider/OPP reference phandles.
Initial200MHz startup/MMCX64 and DDR200MB/s are retained-data candidates.
Runtime bandwidth tables remain provisional. Separate watchdog SPI175,
physical allocation/PAS/UC, live SID/corner/rate behavior and real-media
functional checks remain open. Read the
[integration evidence and limits](video-power-20261003/INTEGRATION.md).

AY's exact command line preserves AX's diagnostic/audio/touch policy and adds
only the AY attempt selector plus Venus/reserved-memory dynamic debug. Timers
collect camera providers at60s, raw Venus startup/formats at90s, rear idle
state at120s, the scoped baseline at620s and a verified known-good return at900s.
No sustained GPU or media workload is scheduled by this startup preparation.
The generic600s return is excluded only on AY. All runtime helpers are fresh
copies bound to AY; historical AX sources and terminal logs remain preserved.

`ay-reboot-check.py` verifies actual boot identity, source/payload/module/helper
hashes, firmware bytes, known-good default/recovery, empty pending selection
and EFI state before selecting AY exactly once. It repeats the complete guard
with AY pending and checks boot ID/default/next/EFI immediately before reboot.
Selection failures clear only AY's pending entry on the same known-good boot.
An interrupted/failing trial is never blindly re-armed. Automatic recovery
across EFI/early-kernel hangs remains unvalidated; repeated experimental boots
including potential manual power cycles are explicitly authorized in AGENTS.md.
