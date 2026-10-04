# AX RTC synchronization candidate: preparation and one-shot provenance

AX has now actually booted once. Its RTC/baseline/sustained GPU and combined
post-load scoped verdicts and actual guarded return pass independent review. Read
[the actual result](RESULT-20261003ax.md) for current hardware state. The
preparation narrative below describes the pre-selection state, preserved in
the immutable prequeue snapshot. Do not queue AX again.

Targets B05 and regression evidence for I01/C01/C05. Actual current boot is
known-good `fbc6d663-8269-4d2f-9aac-c4a687583b00`, release
`6.18.3-1-surface+`, persistent default `spx-known-good`, empty next selection.
[AW's actual sustained GPU result and return](RESULT-20261003aw.md) are collected
before this new candidate. AX is now installed and independently reviewed; no boot is selected.

[RTC diagnosis](RTC-SYNC-20261003.md) proves a missing synchronization
configuration path: chrony enables rtcsync, while both prior kernels omit the
kernel RTC write worker. This prevents intended correction of the observed791s
offset; it does not establish the offset's original cause or RTC retention.
The board fragment now explicitly enables RTC_SYSTOHC and selects rtc0.

AX release is `7.3.0-rc2-spx-mainline-20261003ax+`. Its effective configuration
differs from the full AU seed by exactly:

- `CONFIG_LOCALVERSION`: AU → AX.
- `CONFIG_RTC_SYSTOHC`: disabled → y.
- `CONFIG_RTC_SYSTOHC_DEVICE`: absent → "rtc0".

The complete frozen AU source archive (96,937 paths) is reused byte exactly.
AU's original four compiled-input changes relative to AR remain inherited;
AX introduces no C change. The updated live board fragment is a separately
archived configuration overlay; the frozen source's old fragment is preserved.
The effective AX config is produced from the AU seed by the explicit settings
in [build-ax.py](build-ax.py), followed by olddefconfig.

[prepare-ax.py](prepare-ax.py) makes a private copy of the AU output directory;
normal native Kbuild performs Image/DTB (122.18s), modules (27.38s) and current
Module.symvers modpost, reusing unchanged objects through dependency checks.
The AU output is fully hashed before preparation and independently unchanged
after assembly/archive. No parent artifact or source file is rewritten.
Both raw/gzip Image embedded configs exactly match the AX config. The compiled
NTP object now contains sync_hw_clock and calls rtc_class_open/rtc_set_time;
the preserved AU object lacks that worker. This is build evidence, not evidence
of an actual RTC write.

[assemble-ax.py](assemble-ax.py) verifies193 AX-vermagic modules/208 module-tree
files, clean depmod,54 byte-exact embedded initramfs modules and the exact AT
rear/LED DTB. The two initramfs warnings match AU (unsupported ARM64 microcode
hook and built-in privacy symbol); Image/modules have no new compiler warnings.
No camera receiver or new capture/analog power path is enabled.

| Payload | SHA256 |
| --- | --- |
| Compressed Image | `f4e1f895f9a21de2f0ecea7edecfbceb8db2dfbd6aef41b601223550e613a907` |
| Private initramfs | `d5838fe73bfb1019db85e4a7bd97cf3efb262b11b8e694f82456bb58e74b61f8` |
| AT rear/LED DTB | `50984a306a7cdac1f48083ce4257b4fed19384698a3afa33b6a4ac2303f53a8c` |
| Effective config | `0a4cb5663a718b9a8cb20cfe7628fd0cb08849908d25a9dfadd86c6ad04cf6bb` |

[archive-ax.py](archive-ax.py) stream-verifies the complete source archive and
rehashes the durable preparation at
`/var/lib/spx-boot-diagnostics/attempts/20261003ax/`. Its518 preparation files
have manifest `5fc5c3e4860a375cc14cd6e40da0f8ec113a844cd3737ea1816499cb38f5576a`;
499 build files/one link have manifest
`b24f61c4a5fd87727d9b420d202e5334154f257853686b99bd272cb18bfbef50`.
[Independent review](review-ax-preparation.py) rehashes these, embedded configs,
modules, parent output and recovery; its separate sealed evidence preserves
both NTP objects, compiled command, disassembly and findings.
Three known-good payloads/EFI/menu and5,183 recovery files/links verify.

The bounded read-only observer and31-negative verdict verification are now
prepared; [observer record](RTC-OBSERVER-20261003.md) preserves both versions.
Next integrate unchanged baseline/ordered camera/GPU checks, install/review the distinct
one-shot trial and guarded return, and observe startup plus a subsequent
11-minute synchronization interval. Preserve actual return before any next
experiment. No manual offset write or NTP policy change is part of this trial.
Even if synchronization works, B05 retains independent power-off/suspend tests
without network corrections masking failure. Early EFI recovery is still
unvalidated; existing reboot authorization applies. All47 hardware acceptance
boxes remain open.

Installation/review completed on the same known-good UUID. Seven timers are
configured: RTC30 (sampling through2600), provider60, control120, baseline620,
GPU660, combined review2800 and unconditional fallback3300. All are enabled but
inactive on known-good. The finalizer rehashes/reparses raw RTC CSV/readback and
requires RTC and GPU passes before combined scoped success; recovery remains
armed on success or failure. Fourteen unit definitions/system-manager timeouts
verify. No observer/helper is run as an actual AX trial on known-good.

Installed208 module files/499 build files/one link/full5183 recovery entries
verify; both raw/gzip embedded config and native RTC code preparation retain
prior proofs. The public immutable AU GPU fixture is reused; collector bytes
are exact AW, plan changes only trial selector and candidate release. Separate
44-file GPU provenance manifest13844ad2e5f246ada3b57219ebed224b9bffa576a26514c88ab2bb732f922e18
preserves all AW reference/failure/sampling evidence plus the AX plan.

Strict12 baseline AST expressions,9 baseline/39 initial and39 final camera/
18 privacy/6 timing negatives,26 GPU verdict/12 counter-format negatives,
31 RTC criteria and9 independent RTC archive negatives pass. One generation
stopped at an unmatched deploy-aw.py suffix; a later exact policy comparison
caught raw_ aliases renamed through broad aw_ substitution. Both offline
failures/base sources are preserved in generation-provenance and
generation-policy-failure; aliases are restored before deployment. No policy
or frozen AT24/AU25/AV25/AW26 helper is changed.

AX34-source deployment manifest:
`fb19415ab7aedbf8ddcd495f06903a18a0b8cd89bd7911ed7912990af23442c3`.
Fresh73-file outgoing snapshot manifest:
`b0499a8579ec046c0f0aeb0f1a2a9b5426222c0ff6529a0f7a0c3371fe915e3c`.
Separate system-manager preboot (no SUDO_UID) passes with guard SHA
`3b7d3a8cd662f9b4c4cd853314de97b580a69da6fd350e77248b8990519729d6`.
Known-good default/empty next/no EFI BootNext persist. Fresh native continuation,
prequeue freeze and exclusive one-shot selection are next; actual results remain
pending, all47 hardware acceptance boxes open.
