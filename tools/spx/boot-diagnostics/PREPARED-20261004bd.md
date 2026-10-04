# BD prepared bounded video-allocation trial

BD is terminal. Its actual boot found the aperture NOMAP and failed dynamic
reservation before PAS. The strict620s baseline and actual900s return pass;
known-good433a78d6 is restored, source/config/recovery verified. Read the
[actual BD result](RESULT-20261004bd.md). Preparation/deployment history follows.

BD is now installed and independently reviewed at2026-10-04T04:38:27Z.
The actual entry matches the frozen plan: BC's exact kernel/initramfs and BD's
sole installed DTB.13 helpers,12 units, six enabled timers,217 shared module
files,84669 live source paths/config and5183 recovery file/link records verify.
Default known-good, empty selection and absent EFI BootNext remain. Returned
recovery touchready/two-22 bus errors are preserved, not accepted as mainline
input evidence. The first deployment helper's syntax precheck failed before
execution; its original source/failure capsule is sealed as
`eb4f13ccdaad78681c5bc650362ddbd21d8cee12dc286a6d3b2daed816dbfbe3`.
The corrected helper then completed installation and its preboot guard.
One checked handoff was scheduled at2026-10-04T04:41:29Z with30s initial delay.
The scheduler verified its active timer and empty selection. The frozen checker
selects BD only after another full preboot check, then immediately rechecks boot
ID/pending selection and reboots.18-file handoff manifest:
`4642f4892f4060106ee71c56d7a96ffa975fb9a16c2352f1be721e1d73c34bb5`.
Checker SHA256:
`450c4d969798f3942f159cf9fe23bbbc3340e396be4dd1b78ace1c074fecf006`.
Native same-thread resume/continue and its live session process verify. No BD
hardware result exists yet; collect its actual outcome before another experiment.

BD is a distinct DT-only experiment for open D03. It reuses the exact archived
BC kernel, modules and private initramfs, retaining release
`7.3.0-rc2-spx-mainline-20261004bc+`. Its attempt, menu, timers and log directories
use `20261004bd`. Only the external DTB changes: Venus alloc-ranges now covers
inclusive8b700000/exclusive9ab00000; the5MiB size,1MiB alignment, no-map and
dynamic allocation remain. The response correlation and original BC failure
are recorded in [the allocation audit](VIDEO-ALLOCATION-20261004.md) and
[BC's terminal result](RESULT-20261004bc.md).

The archive at `/var/lib/spx-boot-diagnostics/attempts/20261004bd` contains the
exact2849-file/272-link BC build plus39-file DT build. A separate full96938-
record candidate source archive changes precisely one board-source line;
84669 compiled paths and the unchanged live config verify. Full source and
retained DTB comparisons change precisely one property; all other nodes,
values, phandles and explicit reservations agree. Both provider contracts pass.
Independent candidate review: `6c486d882e6810ba271c63e6f7bbf2b42c626373c43b5784e0ceb92a44b69ed8`.

The retained DTB is `4205df02a7ad7b0827eff3816d50446123442ff10b9eec16203e564018f4e812`;
raw source DTB is `98d242d6fad92f0587e2671067cc989eb7a55473b395bad2e1e142ebb227b5d7`.
Candidate source stream SHA256:
`48ec9e64483527cb22e7ce9d3d2940d5587b98513e2c54827bd6e2d213961759`.

The durable1360-file preparation archive freezes13 helpers and12 units, with
camera-provider60s, video90s, rear idle120s, bounded media180s, strict
baseline620s and return900s. Media is ordered after the video collector and
requires normally bound decoder/encoder nodes. The two four-second H.264
decode references and one four-second encode are scoped diagnostics; their
frame comparator and firmware/fixture hashes match verified BC. Sustained
playback, additional codecs and functional hardware acceptance remain open.

The actual identity guard passes one correct identity and rejects15 corrupt
identities, including a supposed BD release, old BC attempt, duplicate flags
and different executable path. The actual outcome interpreter passes seven
cases/rejects15 corruptions. The complete startup-review body passes six cases
and rejects18 corruptions across FDT, source, identity, reservation and media
provenance. All these boot records are explicitly synthetic. The original
failed synthetic address replacement and the earlier runtime plan are retained.

Preparation manifest:
`6ddcfc60c06abfd7c8331afcb92bb4d280743d4fa9dea8232a43001eb648b193`.
Final runtime-plan manifest:
`2d07decf54cf92ddee25cd020b3d922f5aaac0db5abcda1ce66a1400611d6842`.
Actual-review-body test manifest:
`f59a777a8be2ece2a58ea3858ccff009562d0ed103f698637b65a0425596f7ee`.

The reviewed GRUB entry uses BC's installed vmlinuz/initramfs and BD's new DTB;
only0.16MiB of extra boot storage is needed. `spx-known-good` stays persistent
default. At preparation completion, known-good78d60cce remains running,
selection is empty and EFI BootNext absent. Nothing BD is installed or selected
yet. Deployment must independently rehash the frozen plan, installed shared
payloads, modules, recovery, firmware and live source/config before selection.
The one-use checker must then recheck boot ID and pending selection immediately
before reboot. Experimental boots are authorized by the2026-09-22 instruction;
automatic recovery after early EFI handoff remains unvalidated.

No new actual reservation or PAS/authentication/HFI/media outcome has been
observed. Keep all47 feature boxes open and collect this result before choosing
another experiment.
