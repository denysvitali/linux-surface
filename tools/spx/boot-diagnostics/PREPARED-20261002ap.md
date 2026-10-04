# AP: early ramoops persistence diagnostic, 2026-10-02

Checklist targets: **R01** (persistent diagnostics), **I01** (touch regression).
AO's actual620.86s pass on boot24d683f1-1493-44e1-a5b4-b7d7ed6e46ce was collected
and independently verified before this choice. AO remains the required outgoing
boot. Inspect actual attempt/queue/proof files before action; this document does
not establish a boot or authorize reusing an existing request marker.

AP20261002ap reuses release7.3.0-rc2-spx-mainline-20261001am+, the installed AM
slot,202 module files and the exact source/config/kernel/DTB/private initramfs.
The only functional selector delta is `ramoops.dyndbg=+p`; the attempt marker
also changes. Pin2/native attachment and touch diagnostics remain unchanged.
No retired boot slot or module tree was restored.

The current repository differs from the built source only by three reviewed
tracked documents: AGENTS.md, diagnostics README.md and COMPONENTS.md. AP copies
AO's immutable documentation-provenance archive (manifest868667be...) separately
from its unchanged build archive. The source guard pins that full manifest,
checks the original diff against build/source.diff, proves that exactly those
three patch sections changed and requires the complete live diff to equal the
reviewed after-source.diff. It also checks the exact config. No broad path
exclusion or rewriting of the built source archive is used.

Install review verified1354 build files/272 links/202 installed module files,
17 payload/recovery/runtime hashes,3 working recovery payloads and all5183
working module files/links, known-good entry and EFI loaders. Collector/reviewer
are exact AO identity transformations;12 strict expressions and6 negative scope
cases remain unchanged. Actual preboot2positive/11negative and fallback1positive/
8negative cases pass. New archive guards pass2positive/9negative freeze and
1positive/5negative source cases. GRUB and systemd unit checks pass. Full read-only
preboot passed under systemd without SUDO_UID. Timers620/900 enabled/inactive on
AO, generic600s return excludes AP. Defaultknown-good, nextempty/noBootNext.

Outgoing227-file snapshot manifest:
1505b85d8662fa0e7cc7bbfccef3d9a6abc14112642c947b6eb2110cceb1317d.
Eleven deployment source files manifest:
32be398a8e75c242a5a05b2dd95eb2a6926d726e97edd5b9789940f0fdbbea6a.
Native Happy host2925/thread01a0fb73-77a8-7152-9fdf-545691026ee3 is daemon-started,
running, resumeOnDaemonStart=true/promptcontinue. Legacy resume marker absent.

`freeze-ap-prequeue.py` checks all input paths and Python syntax before creating
its temporary archive, copies and verifies exact content, reruns preboot, records
completion and atomically publishes the manifest. Both queue and immediate
reboot guard require this complete manifest and matching installation/boot/source
records. An exclusive request selects AP once; a30s scheduled guard performs
fresh boot-ID/pending/default/recovery/artifact checks before reboot. It writes
an outgoing AO identity marker before genuine shutdown. No callback is invoked
manually. Actual queue-review.json/reboot-check-passed.json govern continuation.

After actual AP boot, run these in order:

1. `sudo -n python3 tools/spx/boot-diagnostics/review-ap-handoff.py`
2. `sudo -n python3 tools/spx/boot-diagnostics/review-ap-persistence.py`
3. After the actual620s finalizer: `sudo -n python3 tools/spx/boot-diagnostics/review-ap-result.py`

The persistence reader preserves raw old-buffer diagnostics and pairs each with
its following labeled zone. Current ram.c divides0xe0000 dump bytes among three
zones and aligns each size down to2bytes, yielding stride0x4aaaa and console
start0x9a55fffe. The reader derives and checks that exact layout rather than
assuming0x40000 spacing. Four positive and nine negative parser cases pass;
missing/ambiguous/unexpected messages produce an incomplete finding. The layout
is observed, not changed by AP.

Missing/changed signature indicates a problem before ramoops probe, not which
component lost it. A valid console proves callback software completion only when
the exact outgoing identity then begin/complete appear in one newly retained
record. Software completion is not physical rail-off. R01/I01 remain open until
their acceptance evidence exists; an AP scoped pass alone does not close them.
Failure leaves900s fallback armed; verify actual known-good return and preserve
logs before another choice. No manual audio/PCM/capture/input or live reset/rebind.
EFI/early-kernel automatic recovery remains unvalidated.
