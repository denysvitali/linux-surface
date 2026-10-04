# AQ installed and reviewed, 2026-10-03

Targets **C01**, **I02/I03**. Actual running boot remains AP
`7cc51af7-1dfb-4722-a23d-6e262a0e2c6f`, release
`7.3.0-rc2-spx-mainline-20261001am+`. AQ's distinct release is
`7.3.0-rc2-spx-mainline-20261003aq+`. Read the live selection and request markers
before acting; this document does not itself establish that a reboot happened.

AQ was fully built from an isolated snapshot of96,765 source records, with
LOCALVERSION-only config change and an explicit Kbuild `LOCALVERSION=+`.
The live .config stays `f0c4a7ff...`. All187 modules compile and strictly link;
the staged/installed tree has202 files, and54 initramfs module payloads match.
The full Image build has five recorded stack-frame warnings in ELF/SMMU code;
no errors. Module compilation has no warnings or errors. Build logs are retained.

Independent review streamed and verified the complete source archive, compressed
kernel, embedded config, module releases and DT graph.755 build files and272
symlinks verify. Initial provider assembly renumbered72 existing phandle-related
properties and failed the strict comparison. Its ten-file failure snapshot is
retained. The final DTS pins the three input providers' existing base IDs before
adding references; all existing properties and memory reservations now remain
exactly unchanged. Only the PMC8180 regulator subtree and l1/l14/l17 are added.
No sensor nodes, consumers, boot/always-on or initial-mode properties are added.
See [trial plan](AQ-PLAN-20261003.md) and the camera power audit.

AQ source archive SHA256:
`2dba60537e31b1d8702020a2237228a7ea195cb24428973605bc0412863bda19`.
Build manifest:
`0a143b87abded90e06d0984d1bc7a1a487b8dfd1cdefaae6dd31f357a15178ef`.
Config:
`a59d1955648a565f17200d2df33521c4e1823872cad7a403bdef05e2b0102d60`.
Boot payloads:

- Kernel: `de2a109511f952081bbe1822611d669b1a29ef588647a6db2006f09e07246710`.
- Initramfs: `c2c0493f94d00d7916c38a94331264de70ceee54dc524fa7fdd38962fe297b24`.
- Provider DTB: `aa378e0fc5fab926de76549eec68ba8b4c88cff1ce74150e5734b65fd790da16`.

AQ is installed alongside AM and preserved known-good artifacts, without changing
the main GRUB config, recovery entry, EFI loaders or old module/payload files.
The persistent default remains `spx-known-good`. Its camera collector60s,
strict baseline620s and fallback900s timers are enabled but inactive on AP;
the old600s return is excluded for AQ. AP's12 baseline criteria expressions are
unchanged; one positive/nine negative cases pass. New boot-state guard2positive/
10negative and complete-freeze guard1positive/13negative cases pass. All84,671
compiled-source/DT inputs match the isolated snapshot. The actual systemd guard
passed without SUDO_UID, preserving known-gooddefault/empty next/no BootNext.
Guard SHA256 `fd5495b557d199850fde4fbcdb299d27ad4d09414d93e60af9707c2e5d03c3d0`.

Deployment sources manifest:
`0cdbb3aa37ffccf3584e353a0826084a73ca596b9ceb8ad8e45214c5c630a6f7`.
Outgoing AP snapshot231 files:
`11f9543f4583fd38039d4c9c94916a6dd9a205bf3fbf721356c4c42f2fff0cc3`.
All artifacts and reports are in
`/var/lib/spx-boot-diagnostics/attempts/20261003aq/`.

Before selecting AQ, verify this current Happy session's native continuation,
publish the complete prequeue freeze and run the fresh full guard. Queue only
through `queue-aq-once.py`; its exclusive request marker prohibits blind retries.
The scheduled guard checks actual AP identity, exact selection, recovery/artifacts,
source and freeze again, then checks boot ID/pending entry immediately before reboot.
Existing authorization covers this experiment and manual power-cycle risk;
automatic recovery after EFI handoff remains unvalidated.

On continuation after the actual boot:

1. Read this document, LOCAL-PROGRESS.md, PORT-CHECKLIST.md, actual live boot ID/
   release/cmdline, `attempt.json`, selection and `reboot-check-passed.json`.
   If AQ failed/returned to known-good, preserve that actual outcome and logs;
   never re-arm the same request.
2. On actual AQ, run `review-aq-handoff.py`; preserve identity-bound or missing
   pstore/shutdown evidence without claiming electrical rail-off.
3. After the60s collector, run `review-aq-camera-provider.py`. Its independent
   decoder compares all21 raw PMIC records to AP. Missing/failing collection or
   registration remains a failure/untested finding; do not silently rerun it.
4. Wait for the620s finalizer, then run `review-aq-result.py`. On failure leave
   the900s fallback armed and verify/preserve actual recovery. Review both provider
   and baseline findings before choosing another experiment.
5. Update canonical checklist/progress, retaining all47 open acceptance checks
   unless a listed functional check actually passed. Registration is not capture.
   Next work may be a proper rear-only consumer/CCI identification trial, after
   sharing/shutdown review; front/IR/CAMSS supplies remain unresolved. No dummy
   providers, guessed RPMh votes, pinned audio unload/restart or live MSM rebind.

The user requested continuing until the port is complete. Bounded build/deploy
tasks do not satisfy that goal; continue against the full acceptance checklist.
