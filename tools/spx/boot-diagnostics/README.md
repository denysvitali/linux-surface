# Surface Pro X boot diagnostics

The port goal and current feature acceptance tests are in
[PORT-CHECKLIST.md](../../../PORT-CHECKLIST.md). Consult and update that checklist
for each relevant experiment; a passing boot diagnostic does not mean all hardware
works. The latest actual boot result is [terminal AX](RESULT-20261003ax.md), with a
[read-only hardware inventory](HARDWARE-INVENTORY-20261002.md). For the actual
current handoff, also read [LOCAL-PROGRESS.md](../../../LOCAL-PROGRESS.md).

The [SQ2 video inventory](video-integration-20261003/README.md) identifies a
retained Iris1 video engine, distinct IORT mappings/firmware and missing mainline
codec configuration/DT/driver integration. The guarded current system has no
codec nodes. [Original native startup constructors](video-startup-20261003/README.md)
now confirm the queue subset and expose SYS_INIT architecture2 versus Linux1,
with retained SMMU evidence for candidate2300/mask60. The
[Iris1 IRQ source candidate](video-iris1-20261003/README.md) now adds mask/source
handling, passes996 native cases and builds Venus aggregate AArch64 objects.
Original UC reserve-at/page backing is traced. The
[Iris1 power/memory candidate](video-power-20261003/README.md) now adds all-domain
power, paired resets and clock ordering, passing118/110 native PM cases and
33 actual MDT relocation checks; Venus aggregates compile privately. The old
image-loader area is reserved in the guarded RAM map. A dynamic no-map firmware
allocation is proposed; dedicated resource/DT integration and secure startup
remain open. These checks do not establish decoding,
encoding or supported formats; D03 and all47 feature acceptance boxes stay open.

**The user authorized experimental boot/verify iterations on 2026-09-22,
including the possibility of manual power cycling.** This supersedes the old
mandatory recovery gate for the current port work; see `AGENTS.md`. Keep
`spx-known-good` as the default and archive each attempt before selecting it once.
The legacy `preflight.py --reboot` remains disabled; use its read-only checks
before a separately recorded, explicitly authorized one-shot selection.
Read [RECOVERY.md](RECOVERY.md): automatic recovery across the firmware handoff
remains unvalidated despite this authorization.
The historical build/preflight passes below did not establish that protection.
The same document now carries a prepared, unvalidated pre-kernel watchdog
candidate (the SoC's APSS watchdog, armed from GRUB) and its staged validation.
The historical [Q result](RESULT-20260927q.md) completed the staged reactive PIO
capability waiter and an automatic 620-second archive. Its initial result had
a `ramoops` fault-filter false positive; an independent review corrected that
classification and the fallback was stopped after archive verification.
The [next audio boundary](AUDIO-AFTER-Q-20260927.md) requires source review
before a new boot. No soundcard or playback was established at that stage.
The preceding trial [P](RESULT-20260922p.md) ran beyond 600 seconds at audio PIO
stage 7 step 6. It observed a reactive capability worker and first FIFO write,
then returned on its replacement fallback at 1315 seconds because the live
finalizer did not run. Its recovered result is hash-checked; frame delivery
and soundcard operation remain unproven. The
[next bounded audio question](AUDIO-PIO-NEXT-20260924.md) is documented for
review before another one-shot boot.
The previous retained result is [O](RESULT-20260922o.md): the exact L mainline
`7.3.0-rc2-spx-mainline-20260922l+` artifacts completed 611.87 seconds at audio
stage 5, step 2. The interrupt-status-clear sequence completed with zero
observed statuses and a guarded stop. Its actual write operand is a separate
unlogged sample; pending-interrupt acknowledgment remains unproved. Touch,
desktop/EGL FD680, Wi-Fi and remote processors remained healthy. All 296
result files were hash-verified before retaining mainline; no recovery return
occurred. [N](RESULT-20260922n.md) had passed the preceding register reads.
[M](RESULT-20260922m.md) repeated clean touch startup with logging disabled;
intermittent reliability and physical input remain unverified.
The PIO-path review found and corrected a capability-retry length bug in P's
distinct build. That retry branch was not exercised by P. No soundcard or
playback result is established yet.
[K](RESULT-20260922k.md) had completed three bounded startup polls but all
returned zero headers and no touch HID appeared; its worker was bounded,
while the underlying failure remained unresolved.
Earlier [J](RESULT-20260922j.md) observed the same pre-publication failure
with the previous single-poll implementation.
Earlier [H](RESULT-20260922h.md) passed the power request and
[I](RESULT-20260922i.md) passed the version read. I's touch startup failed but
recovered after one daemon restart; the subsequently installed retry policy
is separately documented in [TOUCH-STARTUP-20260922.md](TOUCH-STARTUP-20260922.md).
Earlier [D](RESULT-20260922d.md) completed a three-minute graphical trial and
orderly return after restoring A680 GBIF initialization; [E](RESULT-20260922e.md),
[F](RESULT-20260922f.md) and [G](RESULT-20260922g.md) added CMAC, normal UINPUT
and the diagnostic QRTR rollback. Component and sustained-use validation remain
incomplete; see [COMPONENTS.md](COMPONENTS.md).
[OFFLINE-20260922.md](OFFLINE-20260922.md) reconciles the preceding 7.3 journals
and validates an MSM framebuffer flag fix offline. The earlier build record is in
[OFFLINE-20260915.md](OFFLINE-20260915.md).
The text-target test payload is described in
[PREPARED-20260922a.md](PREPARED-20260922a.md); its deployment status is recorded
at the top of that document and in the permanent attempt manifest.
The target-only graphical comparison was prepared in
[PREPARED-20260922b.md](PREPARED-20260922b.md); its failed result is linked above.
The GPU-policy comparison was prepared in
[PREPARED-20260922c.md](PREPARED-20260922c.md).
The A680 correction and distinct payload were prepared in
[PREPARED-20260922d.md](PREPARED-20260922d.md).

The earlier 7.3 attempts reached encrypted root and early userspace, but did not
establish a stable session or pre-kernel recovery. The successful bounded text
trial also does not validate pre-kernel recovery. Do not repeat the live DPU
unbind: it previously froze the device. The recovery limitations above still apply.

The read-only [kexec guardian design](KEXEC-RECOVERY.md) is the proposed test
loop that avoids repeating the failing EFI-stub path. It remains disabled until
one supervised post-handoff watchdog-expiry proof succeeds. `kexec-guard.py`
hash-checks the target and live guardian state but cannot load or execute it.

These helpers capture a bounded diagnostic boot and its subsequent recovery boot.
They are device-specific: the initramfs logger uses this machine's EFI partition
PARTUUID. They must not be installed unchanged on other systems.

Camera reconstruction is currently an [offline review](camera-offline/README.md)
of the later, working 6.18 v23 topology. Proper regulator integration remains
unresolved; these artifacts are not deployed.

The [dedicated Iris1 integration candidate](video-power-20261003/INTEGRATION.md)
now connects the offline IRQ/PM work to a SC8180X codec resource, binding,
relocatable firmware reservation and fresh AY build. It records38 native cases,
four invalid DTs, three deliberately broken native candidates and exact scope
against AX's camera/privacy boot tree. Read actual build/archive and startup
results before treating any of this as video functionality.

## Evidence requirements

Use a unique attempt manifest under `/var/lib/spx-boot-diagnostics/attempt.json`.
Record the source commit and diff, config, build log, kernel/DTB/initramfs SHA256,
System.map, vmlinux, selected entry and pre-reboot boot ID. Preserve evidence from
both the attempted boot and recovery under `boots/<boot-id>`.

Both kernels must use the same reserved region and layout:

```
ramoops.mem_address=0x9a480000 ramoops.mem_size=0x100000
ramoops.record_size=0x40000 ramoops.console_size=0x20000
ramoops.pmsg_size=0 ramoops.ftrace_size=0
```

Reserve that physical range in both DTBs. Use either the command-line-created
ramoops device or a DT-compatible device, without duplicate registrations.
Build the diagnostic kernel with `diagnostic.config`. Its built-in ramoops
registers at postcore init and replays the available printk ring into persistent
console storage. Recovery loads ramoops via `/etc/modules-load.d/ramoops.conf`.

The initramfs service must be included and linked into `initrd.target.wants`.
It runs whenever `spx_diag` is present; the historical logger was skipped by the
latest minimal boot because it required an unrelated old EFI-trace marker.
It snapshots dmesg to the EFI partition once storage is available. The root
collector runs on recovery too, copies pstore and initramfs logs without erasing
them, and records the current journal and hardware enumeration.

`early-log.service` is installed as `spx-diag-early-log.service` for diagnostic
trials. It starts before `sysinit.target`, after the root is writable, and
requires `spx_diag=20260913`. It saves up to 90 kernel snapshots at two-second
intervals in a fresh `boots/<boot-id>/early.*` directory. A restart or failed
capture preserves earlier snapshots. This covers the logging gap before the
periodic collector; it supplies no reset protection. The installed periodic
timer currently collects every 15 seconds.

`return.timer` only matches `spx_diag=20260913`. After three minutes of a test
that reaches real userspace, it collects evidence and requests one reboot into
the persistent recovery default. It checks boot ID, uptime and pending GRUB
selection first. Never enable a loop that re-arms a failed test.
With the additional `spx_diag_window=600` marker, the ordinary timer is skipped
and `long-return.timer` requests the same guarded return after ten minutes.
The user `graphics-check.service` records a Wayland EGL renderer query after
90 seconds on matching diagnostic boots, including H. Periodic root evidence
includes crypto, iwd and network state.

Happy's native continuation was verified on G and repeated on H: metadata sets
`resumeOnDaemonStart=true` and `resumeOnDaemonStartMessage="continue"`; the
daemon restored the existing Codex thread and injected that prompt. The
corresponding Happy history contains no new user messages. See
`CONTINUATION-20260922g.md` for the evidence and read-only revalidation method.
The task-specific continuation unit and network-gate drop-in were archived and
removed without restarting Happy. Keep them uninstalled and leave their marker
absent when using native continuation.

The dormant `resume.py` and `resume.service` retain the experimental fallback
for a known-good recovery boot or an explicitly armed, matching trial boot.
The local `~/.local/state/spx-port/resume-armed.json`
records `session_id`, `preboot_id`, `attempt` and an optional `prompt_path`.
Known-good-only behavior is the default. To also permit the intended trial,
the marker must contain both `expected_trial_release` and
`expected_trial_attempt`. The latter must equal the marker's `attempt` and
the sole `spx_attempt=` value; the kernel release from
`/proc/sys/kernel/osrelease` must exactly match the expected release, and the
sole `spx_boot=` value must be `mainline-trial`. A matching trial still needs
a boot ID different from `preboot_id`. Unknown, unarmed or mismatched trials
do not query the daemon or send a request. The helper enforces these checks;
the unit itself only checks for an armed marker.

For example, F's optional trial authorization fields are
`"expected_trial_attempt": "20260922f"` and
`"expected_trial_release": "7.3.0-rc2-spx-mainline-20260922f+"`.
This example does not arm a marker or queue a kernel. An armed trial marker
also permits a subsequent known-good recovery if the trial fails before the
continuation acknowledges and consumes its marker.

The helper asks Happy's local daemon to restore the same session, supplying
the prompt via `HAPPY_INITIAL_PROMPT`. The daemon supplies its own RPC and
session credentials; a direct remote-mode executable launch lacks that context.
Saved Happy loops are not scheduled by the installed Codex implementation.
An optional `server_url` in the marker checks DNS/TCP readiness before claiming
a request. Each boot/attempt/session gets a durable request record, preventing
duplicate POSTs after ambiguous failures. A matching live session without
acknowledgement causes a retry, never replacement or a duplicate launch.
The resumed turn acknowledges its `attempt` and current `boot_id` in
`resume-ack.json`, disables the unit without `--now`, and archives/removes
the armed marker. Process existence alone does not prove continuation.
The prompt must describe both permitted outcomes and verify whether it is on
the exact trial or recovery before acknowledging or deciding its next action.

F exposed a helper startup race: Happy's stale-session restoration restored the
session before Tailscale made the server reachable, so the helper correctly
refused to replace it and could not supply the continuation prompt. See
`CONTINUATION-20260922f.md`. The optional `resume-daemon-gate.conf` template
adds `resume.py --daemon-preflight` as a Happy daemon `ExecStartPre` command.
It reuses the armed marker, new-boot and exact trial checks and requires an
explicit plain `server_url`. Unarmed, same-boot or mismatched boots return
immediately. On an authorized boot it waits at most 180 seconds for DNS/TCP,
then permits normal daemon startup even on failure. Separate child probes
bound DNS lookup time; the unit's 210-second start timeout covers the gate.
Removal or replacement of the marker releases the wait. Each gate result is
preserved under `resume-startup-gates/`, separately from spawn request claims.

G showed that restoration can occur immediately after daemon connection, so
this gate does not establish a window for the fallback's spawn request. Native
restoration already supplies its own continuation prompt; the observed root
turn was initially mistaken for a manual user continuation. The gate was
retired after preserving the G evidence. Its source remains for history, along
with the fallback's live-session guard and ambiguous-request records.

## Limits

`panic=20` permits recovery after a panic when the kernel restart path works.
A built-in watchdog restart driver does not by itself arm a watchdog before
userspace. Systemd's runtime watchdog covers failures after systemd opens it.
Neither mechanism guarantees recovery from an earlier firmware or CPU lockup.
Ramoops cannot capture failures before its initialization, and firmware or a
power cycle may erase reserved RAM. EFI trace values without a per-attempt
marker are stale evidence, not proof of where the current attempt failed.
A missing log must never be classified as a specific driver crash. If the new
attempt still leaves no early evidence, collect the last visible screen or an
external console and continue the existing source bisection.

## 2026-09-13 baseline

Recovery boot `e6350355-2f1d-4c98-80e3-25d82f4c57ac` runs 6.18.3-1-surface+.
Prior test entry used panic=0 and a mismatched recovery console layout. The last
recorded preceding boot was also 6.18 and shut down normally. No panic record
survived the reported mainline failure. RPMh skip-readback is a carried,
unverified workaround; the failed boot's root cause is not yet established.
Mainline audio, GPU, USB Alt Mode and modem remain unvalidated.

## Attempt 20260913-01 result

Recovery `a3e915fa-8a35-40e3-87db-3564a6a9db0d` has the intended ramoops
layout, but no pstore record, test journal, or `/boot/spx-diagnostics` log was
found. The diagnostic boot therefore has not established userspace reachability.
Its panic/restart location is unknown; the recovery method needs eyewitness
confirmation. Do not repeat that image unchanged or call the port working.

The latest archived bisect03 image decompresses exactly to the retained worktree
Image built at 2026-09-11 02:47:38. The worktree reflog was at `90ae888a3729`
from 02:18:40 until 02:51:42, when it moved to `6cc37b86f809` **after** the
successful boot began at 02:49:16. The journal for boot
`83670324-b53a-434f-9aeb-19497c9a362b` confirms `/init` and the guarded
userspace return at 02:52:17. This supports `90ae888a3729` as the latest good
source. The older bisect03 JSON manifests describe a previously replaced image;
they must not be used as provenance for that final successful run.

Next source candidate: `6cc37b86f809`, with the preserved three boot workarounds
(clock lookup errors, PCIe GDSCs kept on, EFI ResetSystem disabled), unique
`-spx-bisect04` release, matching diagnostic logger and built-in watchdog driver.
This is boot regression isolation, not a claim that this intermediate tree has
the full Surface port or passes component tests.

`grub-entry.py` renders literal-only test entries that save `spx_diag_attempt`
and `spx_diag_stage` to grubenv at each loader checkpoint. `handoff-ready` is
written only after fdt module, DTB, kernel and initramfs commands all succeed.
A failure records its stage and returns to the recovery menu. These disk markers
survive loss of RAM logs. They establish GRUB loader progress, not that the EFI
stub or Linux successfully executed after handoff. The collector archives grubenv.

Attempt `20260913-02` is staged as `7.1.0-spx-bisect04+` from
`6cc37b86f80985774809aba82283fe0d564d870f`. Image verification, the required
module set, clean `depmod -ae`, initramfs generation/content checks, GRUB syntax,
artifact hashes and 12 mocked reboot-guard tests passed. Its entry uses the
GRUB disk checkpoints. The result is recorded below.

Build note: invoke `make Image` separately from the set of `.ko` targets. Mixing
those goals makes this Kbuild version process targets individually, losing
cross-module exports at modpost (seen with the CAAM dependency set). Building
all required `.ko` targets together resolves that build invocation issue.

## Attempt 20260913-02 result

Recovery boot `427dcd47-72db-40f0-a8e1-9ef9ae98bfce` runs the known-good
6.18 kernel. GRUB persisted `spx_diag_attempt=20260913-02` and
`spx_diag_stage=handoff-ready`: loading the DTB, kernel and initramfs succeeded.
No pstore, initramfs disk log or test userspace journal survived. This narrows
the observed failure to after successful GRUB loading, but does not establish
whether the EFI stub or Linux ran. The recovery method remains unknown.
The complete result and recovery evidence are archived locally under
`/var/lib/spx-boot-diagnostics`.

The next source candidate is `d0bcd488c33d6673fe83b9533d6366ad84d2ec0d`,
the first parent of the PCI 7.2 merge. This keeps the three existing boot
workarounds and uses release `-spx-bisect05`. The interval includes Qualcomm
PCIe changes, but none is yet a demonstrated cause. Testing immediately before
the PCI merge separates that merge and the subsequent four merges from the
earlier interval. Runtime validation is pending.

Extracting IKCONFIG directly from the archived successful bisect03 kernel
confirms that bisect05 differs in configuration only by its release name,
`QCOM_WDT=m -> y`, and a new disabled Wacom touchscreen option. The built-in
watchdog remains a diagnostic variable relative to the historical good boot;
a failure here must not be used to blame a source commit without checking that
variable against the successful baseline. The extracted config is archived
locally as `last-good-extracted.config`.

Attempt `20260914-03` is staged as `7.1.0-spx-bisect05+`. The Image build,
matching boot-module build, separate Image verification, clean module dependency
check, initramfs generation/content checks and preflight passed. All 12 mocked
reboot-guard tests passed. The previous attempt's installed files match its
archived hashes, and the recovery kernel, initramfs and DTB match the original
recovery archive. No diagnostic reboot was queued during preparation.
The new manifest, complete build artifacts and logs are stored locally under
`attempts/20260914-03`; only the diagnostic slot was replaced.

## Attempt 20260914-03 result

`7.1.0-spx-bisect05+` at `d0bcd488c33d6673fe83b9533d6366ad84d2ec0d`
booted successfully as `b9c9d441-5e4b-422d-9978-b21ece5ee631`. The journal
confirms NVMe enumeration, `/init`, encrypted-root mounting, successful evidence
collection, and the automatic three-minute return service. Recovery is boot
`55acccc9-657c-4721-bab5-b1e4b08a2831`. Initramfs logs survived on the EFI
partition, and full journals plus the result are archived under this attempt.
No oops or panic was found. The diagnostic boot still reports USB combo-PHY
orientation/missing DRM bridge warnings, PCIe dummy supplies and IOMMU-cell
compatibility warnings, and an NVMe SUBNQN warning. Component functionality
is unvalidated.

This establishes a successful baseline with the built-in watchdog and current
diagnostic infrastructure. The source interval is now five first-parent merges:
PCI, two Rust merges, IPMI and Kbuild. The next candidate is the PCI merge
itself, `26ae421f7f49f8a6a32d15b1d21a782b46a1bad5`, with release
`-spx-bisect06` and the same three boot workarounds. Runtime validation
is pending.

Attempt `20260914-04` is staged as `7.1.0-spx-bisect06+` from
`26ae421f7f49f8a6a32d15b1d21a782b46a1bad5`. Image and matching boot modules
built successfully, separate Image verification passed, and module dependency,
initramfs content, artifact hash, GRUB and reboot-preflight checks passed. The
successful bisect05 artifacts were verified against their archive before the
diagnostic slot was replaced. The recovery artifacts remain unchanged.
The watchdog, DTB, diagnostic logger and automatic-return setup match bisect05.

## Attempt 20260914-04 result

The PCI merge (`26ae421f7f49`, bisect06) did not reach recorded userspace.
Recovery boot is `ef422b2f-d758-4d40-8670-0696935669dc`. GRUB recorded
`handoff-ready`, but there is no test journal or new initramfs/pstore log.
The recovery method remains unknown. Its immediate parent booted with the same
DTB and diagnostic setup, narrowing the reproduced failure to the PCI merge.

The next isolation test retains that PCI-merge source and restores only
`drivers/pci/controller/dwc/pcie-qcom.c` from working parent `d0bcd488c33d`.
It uses `-spx-bisect07`; the exact changes are archived with the attempt.
This separates the Qualcomm host-driver changes from the other PCI changes.
It is a diagnostic rollback, not yet a verified fix. Runtime pending.

Attempt `20260914-05` (`7.1.0-spx-bisect07+`) passed Image/module builds,
separate Image verification, module dependencies, initramfs checks and reboot
preflight. The Qualcomm driver was verified byte-for-byte against the working
parent while HEAD remains the PCI merge. Its delta is archived in `source.diff`.
Previous test artifacts and the unchanged recovery artifacts were hash-verified
before staging. No diagnostic boot was queued during preparation.

## Attempt 20260914-05 result

The single-file Qualcomm rollback booted encrypted root and userspace as
`182ebcfc-9c23-4a12-ac61-96fc5c8e78cf`; evidence collection succeeded. The
journal ends before the three-minute return service, so this is not a completed
stability or automatic-recovery pass. Recovery is
`5a02a590-e4ca-4fac-8fe7-397628b48888`; the restart method is unconfirmed.
This isolates the early-boot difference to changes in `pcie-qcom.c`.

The next candidate retains the PCI merge and reverts only
`1a23bcb452d9` (mixed PERST#/PHY binding handling), with release `-spx-bisect08`.
That change moved reset-GPIO acquisition earlier in probing. It is a candidate
for isolation, not a demonstrated root cause. Runtime pending.

`periodic.timer`, installed as `spx-diag-evidence.timer`, refreshes the existing
collector every 15 seconds during diagnostic boots, starting at 30 seconds.
The collector records uptime with each snapshot. This reduces the evidence gap
between the initial collection and the three-minute return if a test ends early.
The timer's command-line condition prevents periodic collection in recovery.

Attempt `20260914-06` (`7.1.0-spx-bisect08+`) is staged with only the
PERST#/PHY commit reverted relative to the PCI merge, plus the existing three
boot workarounds. Image/modules, separate Image verification, module dependency,
initramfs and reboot-preflight checks passed. The periodic evidence timer is
enabled; its recovery exclusion and updated collector were verified locally.
Prior test artifacts and unchanged recovery artifacts were hash-verified.

## Attempt 20260914-06 result

Reverting only `1a23bcb452d9` booted successfully as
`3aee2555-ce66-405e-9ab1-ea87fe1f5faa`. Periodic collection succeeded through
uptime 180 seconds, and the guarded return service rebooted into recovery
`2855f5b1-1536-428a-9038-828f19c53221`. This isolates the reproduced early
boot regression to the mixed PERST#/PHY change; full components remain untested.

The next candidate replaces the diagnostic revert with a smaller fix: obtain
the RC PERST GPIO after a successful PHY lookup in both binding paths. A PHY
probe deferral can then return before asserting endpoint reset. Mixed-binding
support remains present. This fix is applied to both the isolation and mainline
trees; `-spx-bisect09` runtime validation is pending.

Attempt `20260914-07` (`7.1.0-spx-bisect09+`) is staged with the smaller
PERST acquisition-order fix and mixed-binding support retained. Image/modules,
separate Image verification, dependencies, initramfs and reboot preflight passed.
The mainline 7.3 Qualcomm driver object also compiled with the same fix, and
checkpatch reported no errors or warnings. Runtime validation of this fix is
pending; mainline component validation remains outstanding. Previous test and
recovery artifacts were hash-verified before replacing the diagnostic slot.

## Attempt 20260914-07 and recovery audit

The smaller PERST fix failed to reach recorded userspace. The user reports an
EFI-stub hang and manual restart; recovery is
`fe6a93b9-8155-4e70-a2fc-2b9a26ec3e1a`. The candidate is not a verified fix
and was removed from the mainline worktree after preserving its patch.

The watchdog audit found no watchdog node in either deployed DTB and no watchdog
device. In the successful diagnostic boot, systemd explicitly reported failure
to open any watchdog device. `QCOM_WDT=y` only compiled the driver; it did not
establish hardware watchdog coverage. The userspace return timer cannot recover
an EFI/early-kernel hang. Experimental entries were archived and removed from
the active GRUB menu, with the known-good kernel/DTB/initramfs unchanged.
The reboot helper is now inspection-only and refuses `--reboot` unconditionally.

## Offline mainline continuation

The tested isolated PERST revert has been ported and built offline in mainline.
See [the build record](OFFLINE-20260914.md) for the commit, build context and
runtime limitations. This does not lift the experimental boot lock.
