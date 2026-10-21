# SPX port: what to do next

## Current defect: external-display connection failure (2026-10-20)

**2026-10-21 H-prepare-retrain (offline confirmed; hardware trial pending):**
Stream preparation discarded a retraining error, then returned success and
allowed video startup on an untrained link. Preserve that error, stop the
training pattern and use existing mainlink teardown. Five new real-C cases
pass (sixteen with retry tests); full incremental modules build passes.
The display is connected again; prepare a one-shot candidate trial with both
error-propagation fixes and the earlier AUX guard, with sound/capture disabled.
Active scanout is a regression check, not proof of exercised error branches or
the reported panic's cause. See `RESULT-20261021-dp-retrain.md`.

**2026-10-21 H-retry-exhaustion (offline confirmed; hardware untested):**
Four failed DP training attempts can return success after the final fallback
reset overwrites `rc` with zero. The extracted real C control flow reproduces
success with four failed attempts and no teardown. Exhaustion now uses existing
failure teardown; eleven offline cases and the incremental controller-object
build pass. This is not proof of the reported panic's cause or a working display
fix. Runtime testing needs an already-connected display and attributable retry
exhaustion; no live MSM reload or fabricated hotplug. Original AUX timeout and
panic stack remain missing. See `RESULT-20261021-dp-retry.md` in boot-diagnostics.

User reports a panic after connecting the external display. Retained evidence
shows AUX timeouts, failed DP training and stalled DRM commits, but no retained
panic stack. A concrete fallback-training bug (unchecked AUX link-status reads
feeding stale/uninitialized bytes into lane/rate decisions) is corrected offline;
the single DP controller object compiles. This is not a proven panic fix.
One hypothesis: fail training immediately when the fallback status read fails,
instead of continuing with invalid status. Runtime validation remains for the
coordinator; no hardware test, deployment or reboot was performed for this fix.
See `tools/spx/boot-diagnostics/RESULT-20261020-dp-aux.md`.

## Current request: automatic hardware coverage (2026-10-13)

**Resolved 2026-10-13: Venus decoder codecs.** H264/HEVC/VP8/VP9 decode
120/120 bit-exact with strict error checking on boot 6e361af1 (commits
88f65136695f, 492a7b1dfc63); MPEG-2 is hidden because Iris1 rejects its output
layout and storms (never decode it until a single-output layout is sourced).
See `RESULT-20261013-venus-codecs.md`. No automatic failure remains on this
boot (18/48, 43 blocked). The speaker-feeder EIO has not recurred on this
boot; its origin logging is installed and waits for the next failure.
**Deferred defect: front OV5693 first transfer after power-up stalls
intermittently (C02/C05).** Baseline is now 20261014ff (front DTB promoted).
CAMSS links each sensor at bind, so rear/IR survive a failed front (verified
at boot 7638f0cb). CCI retries once after its timeout recovery (f2917d87cf2b,
not yet exercised). Root cause unproven; refuted: probe concurrency, CCI
re-init order, clock rate/gating, reset overlap, unpowered time, controller
pinned active. See RESULT-20261014ff.md.
1. H-retry-recovers: CONFIRMED on boot 95e14bba (stall at boot, retry ok,
   front+rear+IR registered, 0 fail). Keep watching `dmesg | grep SPX` on
   ordinary boots; a `result=<error>` would reopen this.
2. H-timing-readback (root cause still open, not blocking): compare master-1
   SCL/SDA/MISC timing readbacks with their programmed values before and after
   timeout recovery. Failure-only diagnostics are built, reloaded and installed
   (2026-10-20); front/rear/IR re-registered and no-capture regression is clean.
   No timeout occurred, so the hypothesis remains untested until a boot stall.
   Matching readbacks on both sides would refute stale timing programming,
   not hidden controller state. See RESULT-20261020-cci-timing.md.
3. Frames from the front camera at boot remain uncaptured (capture needs an
   explicit opt-in); colour/exposure tuning is unchanged.
**MPEG-2 (2026-10-14, closed as unsupported):** downstream SM8150 recipe
(single primary output, work route 1) tested by module reload: work route is
rejected (0x1007) and, without it, the firmware reports "Linear format not
supported for DPB!". With the earlier "OPB is not supported in MPEG2 Decoder",
MPEG-2 can only produce UBWC frames on VIDEO.IR.1.2. Driver keeps it hidden;
patch kept at /var/tmp/spx-codex/venus-mpeg2-primary-final.patch. The 0x1008
containment held (no storm, no reboot needed).
**Vulkan GMEM corruption: workaround deployed** (RESULT-20261014-vulkan-gmem.md).

**Authorised tests (user, 2026-10-14: "proceed with whatever you want").**
Trial 20261014ga = baseline + PMIC RTC + slim s2idle retention + 50 C CPU
passive trip; queued quiet `reopen` audio test runs before any playback.
ON RESUME (spx_attempt=20261014ga): wait for the trial checker; then as root
`trial.py audio 20261014ga --audio-action feedback --microphone-array
--allow-amp-power --allow-playback --allow-capture`; `trial.py thermal
20261014ga --thermal-combined`; systemd-run ... `trial.py systemd-suspend
20261014ga --parked-audio` (see commit 8c993236 message / Codex plan
/var/tmp/spx-codex/authorised-plan.md); validation run+verify; RESULT page;
`trial.py return 20261014ga`. Then the watchdog trial (watchdog-reset).
In-place audio on a boot where the feeder already used the DSP does not
render (hw_ptr 0); use the fresh trial boot.

Next candidates, each blocked on the stated prerequisite:
Parked with briefs in /var/tmp/spx-codex/: IPA (no sourced IPA version/tables),
Type-C class ports (no firmware initial-state query; ADSP has no PMIC_RTR
channel), ALS lux (no calibration), front camera persistence (needs a DTB
trial; trial.py boot currently refuses because of older uncommitted prune
edits in trial.py/collect.sh/initrd-log.sh/initcpio-install).


Use `tools/spx/hw-validation` after every baseline, trial and recovery boot.
Generate `AUTO-HW-CHECKLIST.md` from its catalog and that boot's JSON report;
check the recorded result before choosing another experiment. It is the active
implementation/regression checklist. `PORT-CHECKLIST.md` below is historical
full acceptance, not the automatic work queue. Manual tests are excluded and
are voluntary when a human wants them; do not prompt or wait for them.

- Canonical suite and persistent `spx-hw-validation.service` are installed.
  Current-boot result: `/var/lib/spx-boot-diagnostics/boots/<boot-id>/hw-validation/`;
  its catalog/results generate the active checklist. This is validator coverage,
  not a claim that all fitted drivers/features are implemented.
- Sensor startup H-device-order confirmed in place: unit79d4b25d0b65 requires
  and follows secure SDSP `.device`, preserving closed access and no capabilities.
  One first attachment reachesREADY; native3s accel/gyro/mag deliver84/74/38
  finite samples and acknowledge disable; retained host and proxy stay active.
  No DSP reset, module/DT change or reboot. Future-boot ordering is unverified;
  axes/calibration and physical checks remain separate, not automatic gates.
  See `RESULT-20261013-sensor-startup.md`; canonical motion row passes89/69/29
  finite samples and whole-catalog result11/40,36inventory,44blocked,1fail,0error.
  The sensor backend failure is resolved; full physical acceptance not claimed.
- Current remaining failure: native desktop speaker feeder stopped after12h19m
  with primaryEIO; final feeder counters show31 underruns. Cleanup also assumed
  every monitor has a threaded `.stop` event, but DirectMonitor has none.
  H-monitor-cleanup: signal only threaded DesktopMonitor before amp parking;
  native DirectMonitor process is closed by existing graph cleanup afterward.
  Source dispatch fixed; changed-path fixture tests pass. Full audio suite has
  one timing-sensitive underrun assertion failing twice (118/119); no settings
  or oracle relaxed. Separate primaryEIO remains.
  Its strongest source match is periodic SoundWire `state()` bridge/canary read,
  not proved ALSA underrun. Persist traceback basename/function/line+errno on
  the next failure; do not mask/retry health reads or change buffers/watchdogs.
  Six offline avenues found no supported primary correction: the old page
  bug is fixed, PM is held, and observed FIFO errors follow teardown. A separate
  u32 ring-position wrap defect does not match this EIO boundary; parked, not
  an EIO fix. H-state-origin: if the Python traceback identifies state(), the
  callback's failure stage/register/return or successful-but-bad canary sample
  distinguishes the next hypothesis. Failure-only logging prepared offline;
  no new reads, retries, settings or fatal-check changes, and not installed.
  See `RESULT-20261013-audio-eio-investigation.md`. No sound/amp restart or
  parked-DSP mutation. Primary evidence needs a separately authorized playback
  run or normal boot; stop rather than repeat unrelated successful tests.
- Missing support, missing tools/fixtures and known unsafe paths stay separate
  blocked results, never passes or omitted rows. Wi-Fi/BT scans and one H264
  decode fixture do not establish all networking/codec/lifecycle support.
  Keep manual checks outside the active automatic queue.
- Known limits remain: Vulkan GMEM corruption (sysmem workaround, not root fix),
  encoder CVP faults/resets (no retry), cellular IPA/WWAN/provisioning gaps,
  parked audio/DSP lifetime restrictions, camera package/DT integration and
  unavailable accessories. Battery/load tests stay deferred. Do not claim
  complete support from successful H264 decode or a service being active.

The feature notes below retain earlier evidence and safety limits. References
there to human-blocked acceptance or a frozen 47-box queue do not apply to the
new automatic checklist. Do not tick historical boxes from inventory.


2026-10-13 user instructions: continue compiling/testing in place where
possible; reboot is allowed again. Human checks are deferred until the end:
do not ask for them during porting. Their acceptance boxes remain open.

## Current requested work: Chromium Venus decode (2026-10-12)

**Working H264 hardware decode (2026-10-13):** unchanged installed ArchARM
Chromium152 plays H2641080p through Venus after a kernel-only correction.
Native Iris1 firmware requires CODECCONFIG for standalone header input;
Venus now recognizes SEI/SPS/PPS/AUD/filler/SPS-extension, keeps picture input
unflagged, and skips header-only picture timestamp entries. Matching installed
core+decoder load with normal defaults. The persistent launcher flag is
`--enable-features=AcceleratedVideoDecoder`; a browser must exit fully before
relaunching to read it. Encoder remains absent/blocked.

1. D03 remains open: requested browser playback and reopen work, including
   3600 frames over120s (33 dropped), and a fresh browser decoding the complete
   30s AUD-containing clip (900 frames, three dropped). Full format/path
   inventory, other codecs and the parked encoder fault remain outside this
   evidence. Human observations stay deferred until the end.
2. H-header flags confirmed: split H264 input changes from zero to60 frames;
   adding AUD reproduced zero frames/input timeout until its native metadata
   handler was included, then the same split fixture returned60 frames without
   timeout. Browser hardware path, installed modules/defaults, clean close and
   reopen verified. No remaining hypothesis for this H264 browser failure.

See `tools/spx/boot-diagnostics/RESULT-20261013-chromium-venus-fixed.md` for
boot/release, firmware contract, results and installed state. No reboot or
Chromium rebuild was needed. The browser AU patch/build is a stopped,
unvalidated fallback in `/var/tmp/spx-chromium-build`; retain incremental
outputs and do not resume it for this corrected H264 path. The signed
`llvm22-libs` dependency restores installed Mesa after the build-toolchain
change. Test browser/server stopped; build/device locks released.

Boxes closed: 3 of 47 (B02, B03, D02). Run `tools/spx/progress` for the
current number. The order below is set by the user; agents do not reorder it.

## Current blocker: Vulkan GPU corruption (user requested 2026-10-12)

User requests full GPU support with parallel agents. D02 remains closed for
its recorded GL/GLES evidence; this does not establish Vulkan support.
GTK Vulkan showed strips/broken glyphs; OpenGL workaround remains installed.
No Vulkan cause proved, no new kernel/driver feature claimed.
1. Same public widgets offscreen Vulkan matchesGL visually at1x/2x; no strips.
   Visible Wayland Vulkan fixture selectedA680(scale2), user observation pending.
   Exact upstreamMesa#15349(SPX/a680GTK) reports TU_DEBUG=sysmem avoids corruption,
   unaligned_store worsens. Test same scrolling/damage workload baseline vs
   per-process sysmem; this is a discriminator/workaround, not full support.
   Forcedunaligned same2x static output also byte-identical. Human session now
   reproduces scrolling corruption: screenshot shows repeated colored strips
   below rows15/16 on baselineVulkan. User confirms samefixtureTU_DEBUG=sysmem
   clear after scroll/resize. HardwareVulkan retained; GMEM avoidance is verified
   workaround, not rootfix/fullsupport. BoundedCPU-side GMEMselection/store
   diagnostic committed2f296f119a36; privateMesa26.2.1 Turnip build passed.
   Per-process devenvICD ready, no install. LiveGPUtest awaits exclusive device
   handoff from concurrent user-requested Chromium/Venus recovery session.
   NativePython selection needed venvPATH as well as Mesonnativefile; no distro
   driver install. Need actual failing area/format/store witness before patch.
   Research complete; no justified kernel/Turnip patch. Device lock released.
   Source report /var/tmp/spx-vulkan-turnip-research-20261012.md.
2. Check installed Turnip FD680 support and known upstream rendering defects;
   require matching workload/source evidence before any patch or package change.
3. Check MSM/FD680 firmware, cache/synchronization and fault evidence against
   working6.18; no MSM reload/unbind or unsupported GPU numeric changes.
Coordinator owns builds/device; bounded offline workers only. Preserve working
OpenGL default until a Vulkan correction is verified. No sound/capture/reboot.

## Hardware inventory (2026-10-11, user requested Go tool)

User2026-10-11 now requests parallel implementation of inventory gaps,
prefer no reboot. Bounded workers: Type-C lane-mode plumbing, cellular/CDSP
contract-dependent support, desktop sensor integration. Venus candidate reload reached startup but ended with __flush_work warning
and NULL dereference in v4l_id on boot2530c4ce. No further reloads: ELF analysis proves installed dec/enc and candidate core
have incompatible venus_inst offsets; mixed autoload predicts recorded faults,
but loaded provenance is unproven. Any future trial must prevent old-child
autoload and install/load a coherent verified three-module set before exposure.
See RESULT-20261012-venus-abi.md. Do not add NULL/work guards to hide ABI errors. Type-C candidate now scopes QMP guards and preserves HPD-low/disconnect
before routing changes. It passes apply checks and both candidate objects compile against canonical
work-build; no final module links or live deployment. Binding description now
uses firmware ownership only; dt-schema/DTB checks and binding acceptance
remain pending. Isolated DTB compiles with tree warnings; dt-schema tools
are unavailable. See RESULT-20261012-typec-compile.md. Git connectivity was
recovered with15 empty objects quarantined; originals and lost-commit patch
preserved. See RESULT-20261012-typec-scoped.md.
No reboot, MSM reload, sleep unmasking or speculative CDSP activation.
Physical tests remain pending; not replaced by inventory.

2026-10-12 autonomous continuation (user declined physical session): bounded
parallel workers resume scoped Type-C implementation, Venus next experiment,
and authoritative cellular/CDSP contracts. No physical acceptance substitute.
D03 coherent trial on b9c406c9: matching three-module rebuild with scoped
child-autoload barrier starts, no prior host ABI fault. Installed secure fields
were zero; candidate has existing vendor values. One H.264 decode fails
REQBUFS -110 (zero frames); all candidates cleanly removed and policy restored.
Diagnostic3fd103055904 localizes timeout to SESSION_INIT0x10007 SID0:
CMD33/33 consumed, MSG637/643 has six unread words, cached IRQ0x4.
Next hypothesis: Iris1 serialized native-parser completion polling delivers
queued response within existing deadline; no resend/SID change. Porter WIP.
See RESULT-20261012-venus-timeout.md. Correction: unload returned0 but later
journal shows OF refcount error at genpd_release_dev; not a clean kernel unload.
Polling candidate451c34 built, insertion interrupted by reset; no decode result.
Post-reset source/Git recovered: polling WIP d2485a0c6984; OF ownership
fix50af624d3d50 replaces consuming parent lookup with child-scoped lookup.
Git connectivity passes and cleaned coherent Venus stack builds successfully.
One matched-stack trial on6c15131e validates teardown without OF refcount
errors; session polling gets past init, but firmware asserts dxva_venus.c:1004
and input-buffer-requirement query times out. Zero frames; no host reset.
All candidates removed/policy restored. Next offline protocol comparison with
working6.18; no unchanged retry.
1. Compared6.18: frame-size SET/bufreq GET words match except session token;
   v4 firmware query fallback unchanged.6.18 has no validated SC8180X resource,
   so no known-working Venus decode reference. No basis for version/query change.
2. Capture actual init/set/get words, init-done SID/error and event data before
   recovery. SET is async; current log cannot attribute assertion to GET.
   Tracefac728e7b561 proves INIT_DONE SID0 error0 then SET11001 frame96x96
   and GET211009/property202001 immediately followed by SYS_ERROR/SFR1004.
   Firmware1004 is unsupported-command dispatch; vendor decode111001 uses DXVA
   codec state, unlike generic Linux211xxx. Disassembly links SYS_INIT arch
   directly to that dispatch; no opcode/host-size rewrite needed.
   Root cause proven: hfi_video_arch2 selects DXVA; b7076dde3766 removes
   override to established nativeOX1. Hardware H264 decode now succeeds;
   all120 frame hashes exactly match software, reopen+teardown clean.
   See RESULT-20261012-venus-native-hfi.md. D03 still needs supported-format/
   encode inventory and sustained real-media playback before closure.
   High-profile/B-frame120 hashes pass too. H264 encode triggers NOC CVP fault;
   Previous recovery worker blocked PAS metadata CMA/LRU drain allocation,
   holding core mutex; recovery reboot now confirmed on e61d4de7, unchanged7.x.
   Protected encoder PERSIST requirement is a vendor-backed lead, not proven
   SQ2 fault cause; no ready protected allocator/context contract in current tree.
   Recovery workqueue/core-lock cycle not supported: LRU drain has no Venus
   dependency and sleeping events worker yields its pool. Earlier recoveries
   succeeded; persistent PIO timer sleep also stuck after CVP fault suggests
   broader wakeup disturbance. CPU/queued-drain/timer state was not captured.
   Fault-producing trial deferred until recovery risk/capture is resolved.
   See /var/tmp/spx-venus-recovery-wait-20261012.md; no recovery patch justified.
   Hypothesis: encoder PERSIST/first-buffer layout explains CVP fault;
   bounded allocation/layout diagnostic dcb395476b20 integrated and canonical
   matched Venus module build passes. User requested live run20:27:42 on
   e61d4de7; device rebooted to6272005e. Encoder output0bytes, live log empty,
   journal ends at launch, no buffer/final fault evidence. No address inference.
   Stop further fault-producing encode; recovery/capture remains unresolved.
   See RESULT-20261012-venus-encoder-diagnostic-reset.md.
   Prior overlapping sustained test stopped/no pass. New user-requested decoder-
   only trial on6272005e passes120 exact high-profile hashes and120s1080p@30
   hardware decode-to-null, zero decode errors; unload clean, boot unchanged.
   User-requested unpaced same120s1080p segment:15.653s,230fps/7.67x,
   zero errors; clean unload. See RESULT-20261012-venus-throughput.md.
   No encoder loaded/retry, installed stack unchanged. Other codecs/encode/full
   D03 acceptance remain open. See RESULT-20261012-venus-decode-sustained.md.
Reset attribution remains unknown. See RESULT-20261012-venus-reset.md.
Type-C WIP7b42b0190473 integrated; final objects compile, no deployment.
See RESULT-20261012-autonomous.md. No new numeric hardware constants.
Standalone validator: `tools/spx/hw-validation/`, Markdown/JSON output only;
never edits acceptance. Live run:43 probes,31 observed/9 unknown/3 warnings;
`RESULT-20261011-go-validation.md` and `hw-validation-go-20261011.md`. See `tools/spx/boot-diagnostics/KERNEL-GAPS-20261011.md`
for kernel/DT versus userspace/fixture findings. Live config from
`/proc/config.gz` confirms IPA/WWAN off; current source lacks SC8180X IPA
resources/data and full two-port Type-C/PD integration. CDSP intentionally
parked/disabled. TCS3430 is present; sensor services are inactive, not proof
of a missing ALS driver. This boot298cf388 has front DT disabled despite
prior live-overlay capture on another boot. Existing Venus session-ID WIP
needs clean-boot validation. No blocker reorder or kernel deployment.

## Latest fix: baseline bootloop / external display (B01, U03)

20261010a boot `c8158f7d` runs the patched MSM driver on 7.3.0-rc2. User
confirms external display works; no prior DP training/clock errors appear.
Promoted to persistent `spx-mainline`, both automatic trial timers disabled.
6.18 remains manual recovery. Full B01/U03 acceptance remains open.

- Desktop audio startup isolation was refuted: reset occurred with it skipped.
- Removing automatic trial workloads was insufficient: later live DP changes
  still reset. Keep those workloads off ordinary baseline boots.
- DP event serialization and failed-stream clock cleanup now verify on a real
  boot. Keep the automatic EDID override disabled. Do not repeat live modesets
  just to extend this result. See `RESULT-20261010a.md`.

## Persistent baseline: 7.x (user requested 2026-10-09)

20261010a is the persistent `spx-mainline` in `/boot/spx-mainline`.
Ordinary boots and trial returns use 7.x. Promoted boots have no automatic
return or functional workload. Do not demote the default to 6.18 without
user instruction. The patched MSM module is installed for future initramfs builds.

## 1. Human session (deferred until the end, about 20 minutes)

Do not prompt during porting (user requested 2026-10-13). Steps for the final
session are in
[PHYSICAL-TESTS.md](tools/spx/boot-diagnostics/PHYSICAL-TESTS.md), one action
each. It decides, or partly decides: I02, I03, I04, I05, I06, D01, U01, N02,
S01, S02, P03. Battery steps are left out (deferred by the user).

2026-10-09 speaker session: user requests microphone feedback and no human
tests. Leave the physical session pending; do not substitute synthetic checks.

## Speaker playback close and reopen: resolved on WX (A01–A03 remain open)

- WX verifies the permanent fix after reboot: the codec automatically holds
  INT7/8 without a helper, and the microphone detects both speakers before
  and after close. The requested reopen fix is complete; full A01–A03
  acceptance stays open. No further reopen tests or trial boots are needed.
- Preserve parked DSP mappings. Corrected APR headers now allow playback
  CLOSE/OPEN, but UNMAP and AFE STOP remain unsafe/unverified. No unrelated
  audio/microphone variations.

1. **H-WSA-reset, refuted as a sufficient fix (WR):** the amp needs the Windows digital reset at
   teardown followed by complete native initialization. WQ boot `183438a1`
   never reached playback: its legacy `spx_write_only=1` setting was rejected
   by the native stereo guard. Correct that pairing in the native driver,
   retain `spx_write_only=0`, and run the existing two-PCM microphone test.
   WR boot `f7854ae1` detected both speakers initially, then reopened left
   fell to the noise floor (0.262 versus 0.233 RMS) despite successful native
   reinitialization. See `RESULT-20261009wr.md`. Do not repeat this reset trial.
2. **H-WCD-reset, refuted as sufficient (WT):** WCD keeps its SLIMbus playback stream active,
   but DAPM still resets RX7/RX8 on close. Suppress only those interpolator
   resets with `spx_skip_speaker_reset=1`, leaving clock/PA shutdown intact.
   Expected: existing microphone reopen test detects both channels on its
   second PCM. This switch is writable live; do not destroy parked DSP sessions.
   WS boot `1436256e` completed baseline checks but ended uncleanly with no
   acoustic result, return record or retained crash dump. The user does not
   know the restart cause. See `RESULT-20261009ws.md`; do not count this as
   an acoustic failure or blindly re-arm the same image.
   WT boot `2c78c7c8` stayed available with automatic audio omitted. The manual
   reopen test detected both initial channels, but second left was absent
   (0.097 RMS versus 0.340 baseline). Both reset skips were logged.
3. **H-RX-clock, prevention confirmed on WW; live restoration failed:** stopping
   interpolator clocks while retaining SLIM playback may disrupt the path.
   Use a live module to force only INT7_CLK/INT8_CLK supplies through DAPM,
   preserving the card and DSP mappings. Expected: the existing acoustic
   reopen test detects both channels across close; unload restores the votes.
   WT: loaded `spx_audio_rx_hold` on the same boot; both supplies stayed on.
   Guarded parked FIFO recovery succeeded, but the first left tone on the
   already-failed route was absent (0.204 RMS versus 0.449 baseline). Module
   unloaded and votes restored. This does not test prevention before the first
   playback on a fresh DSP session. Do not repeat restoration on this session.
   Older findings (`spx-win-parity-knobs-implemented.md`, section 49.1) show
   RX0 overflow is a self-masking boundary flag, also present with audible
   output. It does not establish this hypothesis or justify a port reset.
   WU boot `876ae499` held both clocks before any PCM. Its first run stopped
   before tones: COMP7/8 mixer switches were off but hardware enable bits were
   still set. Their setter updates only software until the next clock event,
   which retention suppresses. Clearing the two bypass bits live preserved
   the clock votes; a retry consumed 168/168 buffers but its first left tone
   was absent (0.473 versus 0.342 baseline). No audible initial baseline was
   established, so prevention remains inconclusive. Fix the native disable
   control to apply bypass immediately before the first PCM, then repeat this
   same hypothesis on a clean start. See `RESULT-20261009wu.md`.
   WV boot `d717b2ee` included that fix and completed baseline collection,
   but ended uncleanly before audio testing. No return record or crash dump
   survived; restart cause is unknown. See `RESULT-20261009wv.md`. This is
   neither a speaker failure nor a pass, and the image must not be blindly
   re-armed unchanged.
   WW boot `74d5cfa5`: before any PCM, the native controls cleared both
   compander bits from 2 to 0 with INT7/8 forced on. All six acoustic phases
   were detected across two distinct PCM owners; DSP consumed 332/332 and
   325/325 buffers without fallback. Amps parked, FIFO empty, raw audio
   discarded; the helper remains loaded to preserve the working route.
   The codec probe now applies the same two DAPM votes when SPX retained
   playback is enabled. WX verified that integration without the helper.
   Do not unload the live codec/card or repeat the successful experiment.
   See WW and WX results.
4. **H-ASM-flush, refuted as sufficient (WT):** retained playback reuses an EOS-ended session
   without the PAUSE/FLUSH used by Qualcomm's downstream same-stream reuse.
   Use a one-shot live module with exported q6asm APIs, holding the PCM open
   mutex and requiring no open playback owner. Pause/flush playback only;
   no CLOSE/UNMAP/RUN or callback replacement. Expected: the unchanged
   microphone reopen test restores its first tone; a second-close failure
   would then support integrating flush at each retained prepare.
   PAUSE initially timed out with a reply to unregistered service 16.
   `q6asm_add_hdr()` leaves `src_svc` uninitialized on stack commands while
   APR preserves nonzero source IDs. After initializing it through a live
   ASM-only header correction, PAUSE/FLUSH both ACKed status 0, but the first
   left tone remained absent (0.658 versus 1.172 baseline).
5. **H-ASM-native-close, refuted as sufficient (WT):** the proven header defect also affects
   CLOSE, invalidating earlier attribution of all CLOSE timeouts to firmware.
   With corrected headers and no PCM owner, pause/flush then CLOSE playback;
   only if acknowledged, recreate the same playback format using retained
   memory mappings. Do not UNMAP, alter capture or unload the card. Expected:
   the existing acoustic test restores its first stereo playback. Stop on
   any command failure instead of discarding the retained client.
   CLOSE/OPEN/format all ACKed status 0 on the same boot. The first tone
   remained absent and WRITE_DONE stopped (158 submissions, 0 completions).
   Remapping session 1 to the retained speaker COPP through the native ADM
   API restored real DSP completions (153/153, zero fallback), but no tone
   (0.350 RMS versus 0.383 baseline). Retained DMA mappings still work;
   native ASM restart plus matrix reconnection does not restore sound.
6. **H-startup isolation, test completed on WW:** WV ended before audio testing, with no
   reset cause in available logs. Boot the same candidate to `multi-user.target`
   instead of starting GNOME, preserving parked amps and the two-hour return.
   Expected: mainline remains available for native compander verification and
   the existing microphone reopen test. Success makes that test possible; it
   does not prove that GNOME caused the earlier reset. The Happy user daemon
   has lingering enabled and starts from the user default target.
   WW completed native control verification and the acoustic reopen test in
   multi-user mode. The earlier reset cause remains unknown.
7. **H-native clock activation, confirmed on WX:** the codec probe must establish
   the same INT7/8 DAPM votes without the helper. User requested immediate
   completion after being told this reboot verification remains. Boot the
   installed driver with WW's configuration and run the existing quiet
   microphone reopen test once. Expected: no helper loaded, both clocks
   forced on, and both speakers detected before and after a real PCM close.
   WX boot `11455cda`: no helper loaded; both supplies forced automatically.
   All six acoustic phases detected the expected tones, including reopened
   left/right at 2.688/20.412 RMS versus 0.257/0.083 noise references. DSP
   consumed 326/326 then 328/328 buffers, no fallback. Amps parked, FIFO zero,
   raw capture discarded. See `RESULT-20261009wx.md`.

User reminder (2026-10-09): minimize reboots; use module reloads wherever
possible. Current boot `c7ebfe0d` is the promoted mainline baseline, with
GNOME active and permanent clock votes. Acoustic reopen was verified on WX
boot `11455cda`. The requested fix is complete.
Stop here; do not extend this successful audio test or select another
blocker. Broader acceptance still includes useful volume, physical mapping,
balance and lifecycle coverage. The user declined human testing. 7.x is
now the persistent default, no next boot is selected, and the promoted
baseline's automatic trial return is disabled.
No card/Q6-stack unload or AFE STOP: retained mappings outlive PCM opens and
AFE STOP has frozen the platform. Keep the existing reopen test.

## Missing desktop speakers (A03, diagnosed 2026-10-09)

- **2026-10-11 handoff (A01/A03, WIP):** boot `298cf388` now uses the
  native feeder on MultiMedia2 with 480-frame (10 ms) periods and 8 periods;
  reported ring fill25–40 ms is not acoustic latency. Saved PA step6 is
  +9 dB. Distortion and perceived delay still need the user's listening check;
  do not increase gain or repeat successful audio tests. Runtime device2
  override does not survive reboot; installed device1 feeder startup is
  unverified. No reboot just to extend this result. Shutdown still logs
  `Desktop graph cleanup failed`, although the prior trial parked amps.
  See `RESULT-20261011-speaker-latency.md` and commit `d6e5f85d563c`.
  Next: user judges delay/loudness. Only if still delayed, consider240-frame
  periods on a fresh mapping, then the DSP low-latency mode.

- **Persistent speakers installed (2026-10-10, user request):** native
  `spx-desktop-playback.service` enabled for promoted baseline boots only.
  `/etc/spx/speaker-gain-step` saves2 (+3 dB); start at +1.5 dB and apply the
  saved gain on the same stream after5 seconds. Preserve user slider/mute.
  Installed code is independent of this checkout. Current clear PCM19468
  retained; next normal boot must verify automatic startup. See
  RESULT-20261010-speaker-persistence.md. No extra successful sound tests.

- **H-gain-vs-restart, same-stream +3 dB clear:** user confirms "Now it's
  perfect" after changing +1.5 -> +3 dB without restarting PCM19468 or its
  trigger/PipeWire graph. Earlier restart/session confounds the apparent
  +1.5 dB ceiling; exact glitch mechanism remains unproven. Leave +3 dB.
  Root-only runtime `pa-gain-step` accepts0/1/2 with serialized health checks.
  See RESULT-20261010-speaker-glitch.md. No further successful audio tests.

- **H-amplifier-gain (A01, user authorized 2026-10-10):** full digital
  scale still sounds below expected loudness. Try one equal +1.5 dB PA step
  using native mixer controls after initialization on silence. Keep boost,
  protection and compander settings unchanged; require exact gain readback.
  User confirms +1.5 dB clear with no audible distortion and requests +3 dB
  on both speakers. Step2 applied: both mixers read2, PCM13643 running;
  user reports a bilateral playback-like glitch at +3 dB. Restored +1.5 dB;
  whether the symptom follows gain remains unknown. DSP1615/1615 completions,
  no logged underrun; digital peak9652. Do not label this a confirmed gain
  distortion limit. No tones or microphone capture.
  See RESULT-20261010-speaker-gain.md.

- **H-night-cap, confirmed (A01, 2026-10-10):** GNOME is
  at 100%, but play-desktop scales samples to 1433/32768. Raise ordinary
  playback's ceiling to the supported 12000/32768 (+18.46 dB), preserve PA
  gain 0 and low-latency queues. Applied and user confirms "That is louder."
  User subsequently requested another increase and independent volume control:
  ordinary playback now defaults to unity/peak32768 (+8.73 dB over12000).
  GNOME slider and volume keys control the full digital range; subsequent
  user-requested PA +1.5 dB is recorded above.
  Serve/acoustic modes retain their12000 ceiling and1433 default.
  Factory maximum remains unestablished. See RESULT-20261010-speaker-volume.md.
  No automatic tone or microphone capture.

**Open problem, recorded at user request 2026-10-10 (A03):** desktop speaker
latency is perceptible and unacceptable. User observed approximately 500 ms
or more; after reducing userspace buffering, 150 ms remains queued in ALSA.
That queue measurement is not an end-to-end latency measurement, and the user
has not confirmed the improvement. Desired behavior: no perceptible delay.
Resume with smaller DSP periods/buffers on a fresh mapping, preserving the
verified stereo/reopen fix. No further experiment requested in this update.
The low maximum volume is also outstanding for A01; the user now explicitly
requests higher loudness. The H-night-cap change above supersedes the previous
night cap for ordinary application playback, not automated test signals.

- **H-missing-native-feeder, confirmed 2026-10-10:** `play-desktop`
  reuses WX native initialization and forwards the public sink without capture.
  User hears both speakers. Runtime `spx-desktop-playback` is active on boot
  `c8158f7d`; startup persistence installed, next-boot verification pending. Unity gain active,
  PA +3 dB now active and user-confirmed clear after same-stream change.
- **H-excess-buffering, partly confirmed:** user reports >=500 ms delay.
  Reduced ordinary pipes to 4096 bytes and monitor queue to 20 ms; restarted
  on the same mapped PCM geometry. ALSA backlog now samples at 150 ms and
  feeder pipe empty; perceived improvement unconfirmed. Smaller DSP periods
  need a fresh mapping; parked playback retains old offsets/count. Do not
  alter geometry on this live session or interrupt the current DP trial.
  See `RESULT-20261010-desktop-speakers.md`. No more acoustic test variations.

- **H-desktop-inhibited, confirmed:** current mainline boot `c7ebfe0d`
  retains `spx_audio=parked`; user service/socket trial drop-ins prevent
  PipeWire, pipewire-pulse and WirePlumber from starting. ALSA detects the
  Surface card. This explains the absent desktop outputs despite WX's
  speaker fix. Desktop services now start on the promoted baseline and GNOME
  connects; Surface Pro X Speakers is the default output at 5%. The existing
  virtual sink was initially unconnected; the native feeder above now provides
  playback. Legacy bridges remain inhibited; microphones were not captured.
  See `RESULT-20261009-speaker-ui.md`.

## GNOME after the speaker trial (D01, restored 2026-10-09)

- **H-console-target, confirmed:** WX explicitly selected
  `systemd.unit=multi-user.target` for audio startup isolation, so GDM was
  enabled but never started. User requested the desktop back. Started
  `graphical.target` on the same boot: GNOME Shell runs in the user's active
  Wayland session on foreground VT2, with display power on.
- Removed the console override from WX's saved boot entry. Future trial
  preparation discards inherited target overrides unless explicitly selected.
  No reboot, display-module reload, sound or capture was needed. No further
  desktop checks are needed for this restoration; full D01 remains open.

## Graphics lag (active by user request 2026-10-09; D01/D02)

1. **H-rendering/load:** determine whether the live desktop uses software
   rendering, a constrained GPU/CPU clock, or excessive compositor/app load.
   Read renderer, DRM client counters, clock policy and display mode; expect
   a software renderer or measurable resource/frame bottleneck if confirmed.

## GTK window corruption (D01/D02, workaround confirmed 2026-10-09)

1. **Confirmed: H-renderer (FH, boot `1dd03623`).** The corrupted Text
   Editor lacked `GSK_RENDERER=opengl` and loaded Turnip Vulkan; Console and
   GNOME inherited the existing systemd OpenGL setting. The user confirmed
   the OpenGL editor is clear. Added the same setting to `/etc/environment`
   for PAM launches and reopened the editor with its saved draft intact.
   This is a working accelerated workaround, not an underlying Vulkan fix.
   See `RESULT-20261009-graphics.md`; full D01 acceptance remains open.

Graphics stopping point: the reported window corruption is resolved through
OpenGL. Human checks are deferred until the end; no additional successful OpenGL
checks or kernel trial are needed. Vulkan investigation needs a specific
request for that path.

## 2. Cameras: front OV5693 first (active by user request 2026-10-09; C02, then other cameras)

2026-10-11 fresh user-requested check: rear now resolves a real room scene
at about30fps; yesterday's dark/flat result is superseded for this view.
Front/IR also return120 fresh frames each, but current views are dim/noisy.
No tuning/code change. Images: `~/Documents/tmp/CAMERA_IMAGES_20261011/`;
see `RESULT-20261011-camera-check.md`. Calibration remains deferred.

2026-10-10 user deferred calibration and authorized images from rear/IR next.
All three return image data on c8158f7d; viewed front/IR resolve the scene,
rear is dark/near-flat and does not establish a usable rear scene. Private
OV7251 helper now maps code16 to1x;120 IR frames at30fps show scene edges,
metadata6x matches native gain96. No IR emitter activation. Images and logs:
`~/Documents/tmp/CAMERA_IMAGES_20261010/`; result `RESULT-20261010-camera-images.md`.
Calibration remains deferred; C02/C03/C04 remain open.

2026-10-10: front streams real scenes without reboot on boot `c8158f7d`.
C02 stays open: user confirms orientation; lit colour/exposure and resume
still need physical observation. See `RESULT-20261010-camera-status.md`.

- **H-front-binned-window (confirmed):** vendor native readout window and
  offsets restore real 1296x972 scenes with both flips. Extending crop ends
  alone produced grey frames; analogue registers alone still stalled.
- **H-front-startup (partial):** ordered AVDD/DOVDD/DVDD, clock then reset
  now streams and reopens with CCI auto-suspend. Forcing CCI on alone was
  insufficient. Cold-start and system-resume reliability remain unverified.
  Resume preflight on c8158f7d: loaded audio has read-only
  `slim_qcom_ngd_ctrl.spx_s2idle_retain=N`. Existing normal-sleep helper
  requires powered retention; bypassing it invokes the unsafe force-runtime
  suspend path. Requires a prepared trial boot with retention enabled, not
  an unguarded suspend of this baseline. Camera's no-autonomous-reboot limit
  remains in effect; no sleep or boot was attempted.
- **H-front-colour (physical check pending):** CPU/GPU share the tint;
  primary RAW supports BGGR. Neutral ratios vary spatially. Daylight vendor
  CCM now runs through the private native ISP; preview at
  /tmp/spx-front-20261010/vendor-daylight.png needs user assessment. Spatial
  shading requires a suitable neutral illumination/reference, not fixed WB.
- **H-front-reference-spectrum (confirmed):** Night Light2700K alters the
  target. With the desktop unlocked/on and idle inhibited, temporarily
  disabling it changes estimated CCT3176 ->5059K and R/B gains1.148/2.676
  ->1.822/1.653. Restored afterward. Earlier screen-off noise is inconclusive.
- **H-front-per-unit-shading (inconclusive):** powered front EEPROM reads
  supply valid17x13 per-channel calibration. Vendor normal * golden / EEPROM
  correction on saved grey RAW reduces G/B spread8.214% ->6.515% but worsens
  G/R6.018% ->6.532%; viewed residual tint remains. Oblique monitor confounds
  the result; need diffuse neutral reference before live integration.
  See RESULT-20261010-front-lens-shading.md.
- **H-front-missing-CCM (partial):** vendor conversion establishes RGB order;
  all three front IPE profiles share the4600..10000K matrix. An explicit
  daylight tuning option completes240 frames around29fps; chart saturation
  improves visually. Gain2 ->3 confounds brightness comparison. General
  AEC/lux/CCT mapping remains unvalidated; no default tuning change.
  See RESULT-20261010-front-colour.md.
- **H-front-exposure-compensation (confirmed):** off-centre screen/dark
  surround washes out highlights under whole-scene AE. Private libcamera
  patch0003 exposes standard ExposureValue, preserving EV0. Same scene at
  -2 EV: gain20 ->5, near-clipping56.8% ->0%; chart details return. New
  session defaults to EV0. Default metering and full colour remain open.
  See RESULT-20261010-front-exposure.md and /tmp/spx-front-20261010/ev-minus2.png.
- Native sensor module installed; front graph enabled by live overlay.
  Source DT updated, persistent boot DTB and distro libcamera unchanged.

- Earlier front-only capture restriction superseded by the user's2026-10-10
  request for images from the other cameras. Test sensors sequentially.
  Leave the working speaker route untouched.
- No autonomous reboot. Prefer evidence-backed live measurements and module
  changes; request a camera-only physical image check once front frames exist.
- **Blocked before research (2026-10-09):** both read-only research agents
  failed before any file/tool access with API 401 (`fledge-alpha-free` is
  unsupported), including a retry with an explicit model. The live-state
  agent was canceled rather than repeating the same failure. Isolated agent
  worktrees also failed to populate; the root filesystem has about 467 MB
  free. No new camera hypothesis was tested, no capture/module change/boot
  occurred. Resume this front-only investigation when subagents can run;
  do not infer a hardware cause from these infrastructure failures.

- Known: the rear sensor identifies. Receiver SID and mask are resolved.
- Missing: resolved ownership of the `vdda-phy` and `vdda-pll` supplies,
  plus validated scene colours/orientation. EV captured real mainline frames.
- Start from the working 6.18 rear capture: commit `005adbc494a5` in
  `../linux-surface-kernel` and `docs/spx-camera-recon.md` section 7.
- Do not use dummy supplies or guessed RPMh votes. Do not repeat camera audits
  that change nothing.

Supply finding (2026-10-08): no vendor stack switches a regulator for the CSI
receivers. The SQ2 DSDT power tables for MPCS, VFE0, JPGE and CAMP contain no
PMIC vote (only sensors vote LDO1_A/14_A/17_A); Qualcomm's `sm8150-camera.dtsi`
names `pm8150l_l3` 1.2 V for the CSIPHYs but leaves it out of
`regulator-names`, so it is never requested; 6.18 v23 captured all three
sensors with no supply on the camss node. The pins are on the shared PHY
rails: 1.2 V = LDO3_C (named by Qualcomm), 0.88 V = LDO5_E (inferred: it is
the DSI/UFS/PCIe core rail, which carries the CSI 0.9 V nets on the SM8150
reference board; LDO9_E is USB-only). Both are already on for UFS/eDP.

Hypotheses:

6. The front OV5693 and IR OV7251 only need the v23 wiring that worked on
   6.18 (front: CCI0 bus 1, MCLK2/GPIO15, reset GPIO12, CSIPHY0 two lanes;
   IR: CCI0 bus 0, MCLK3/GPIO16, enable GPIO23, CSIPHY3 one lane), and the
   colour/processing gap is the missing ISP stage, which libcamera's software
   ISP supplies. Change: commit `23848bdb15dd` (DT, sensor modules) plus
   `UDMABUF`/`DMABUF_HEAPS` and a bounded `cam` step. Expect: all three
   sensors in the graph, two informative raw captures each, and `cam -l`
   listing three cameras with 20 processed frames each.
   **Partly refuted (ew, boot 9366f2e2).** Front OV5693 fails on CCI bus 1
   at identify (`master 1 queue 0 timeout`, reg 0x300a -110); IR OV7251
   probes but has no graph link; rear logs no probe; no frames. See
   `RESULT-20261008ew.md`.
7. Hypothesis: front fails only because gpio19/20 are missing from the CCI0
   pinctrl. **Refuted (ex, boot 028f358f).** Same timeout with the pins added;
   MCLK2 and the three rails are on during the probe. See `RESULT-20261008ex.md`.
8. **Refuted: H-reset.** `ov5693_sensor_powerup()` releases reset before
   identify, so the output-low `cam_front_reset` pin does not hold the sensor.
   Source reading only; no trial needed.
9. **Confirmed: H-async (fa, boot `b1da04a0`).** With the front node disabled
   and its CSIPHY0 endpoint removed, the rear and IR link to CSIPHY2/CSIPHY3 and
   stream. Camss waits for every CSIPHY endpoint's remote. See
   `RESULT-20261008fa.md`.
10. **Answered: H-rear (ez).** The rear OV13858 probes silently. Its link was
   missing because of the camss notifier, not the sensor. See
   `RESULT-20261008ez.md`.
12. **Refuted: v23 extra CCI pads (fb, boot `1a5a2dde`).** gpio31-34/41/42 as
   `cci_i2c` did not fix front bus 1. Untested: enable CCI1-3 as v23 did.
13. **Refuted: CCI1 enabled (fc, boot `b1b3e2d9`).** Front bus 1 unchanged. No
   untested hypothesis left for the front OV5693; rear and IR work with it off.
11. **Answered: scene (fd, boot `89f87251`).** Lit scene: rear and IR show real
   frames; the dark frames were the scene. Open: user confirms colours and IR
   orientation, then resume/repeat start-stop. See `RESULT-20261008fd.md`.
14. **Rear exposure (fe/ff).** Washed out = default exposure at the black level;
   libcamera AE converges over about 90 frames (mean 17 -> 80); DT rotation 180
   reported to apps. Open: physical image validation and full lifecycle.
   Missing black correction was refuted in hypothesis 15 below.
   See `RESULT-20261008ff.md`.

15. **Refuted without a boot: missing rear black correction.** FF's processed
    metadata already reports `SensorBlackLevels = [4096,4096,4096,4096]`,
    equivalent to RAW10 level 64. The installed fallback includes BlackLevel,
    AWB and AGC. A duplicate tuning file cannot fix the reported quality gap.
16. **IR application integration (confirmed, FG):** libcamera rejected OV7251 because mandatory
    `V4L2_CID_ANALOGUE_GAIN` (0x009e0903) is absent; the driver exposes the
    same sensor gain as `V4L2_CID_GAIN`. Change that control ID, leaving the
    gain range and register writes unchanged. Expect: the missing-control
    error disappears and IR progresses to format negotiation in `cam -l`;
    then test whichever real format libcamera exposes. **FG, boot `5c0eb87d`:**
    IR is listed and streams 90 native RAW10 frames; RGB processing is missing.
    See `RESULT-20261009fg.md`.
17. **IR processed format (confirmed, FG):** libcamera's software ISP rejected monochrome
    `R10_CSI2P`. Add scalar RAW10 conversion and equal-channel statistics to
    its CPU path, using the existing black/exposure processing. Expect: real
    IR RGB output has equal channels and is written by the normal `cam` app.
    **Verified:** six offline format/gamma fixture cases; then 90 real 632x480
    BGR888 IR frames near 30 fps, with identical RGB channels. Rear GPU
    capture remains functional. Patch: `tools/spx/libcamera/`; private build
    `/var/tmp/spx-libcamera-0.7.2/build`, package integration pending physical
    image validation. Open: normalized gain helper, IR mounting metadata,
    illuminator/control applicability and full lifecycle. See FG result.

Current stopping point (FG): returned to known-good boot `276d70cb`; trial
payloads and units removed. Need the user's IR scene/orientation check and
the pending human session. Front hypotheses are exhausted; supply ownership
needs authoritative wiring evidence. Keep C01–C05 open; package integration
waits for physical image validation.

5. RAW-to-display rendering omits black subtraction, AWB and transfer.
   **Implemented offline, physical acceptance pending:** `camera_render.py`
   adds full RAW10 decoding, provisional common black subtraction, bounded
   frame-derived grey-world AWB, common exposure normalization and sRGB
   transfer. Twelve fixtures pass, including neutral/primary patches and RGB
   rotations. `camera.py` keeps the diagnostic and adds a rear view rotated
   180° for the upside-down image reported by the user. EV was reprocessed
   (`RESULT-20261008-processing`); no acceptance or calibration claimed.
   **Controlled real-frame comparison:** reused this renderer on the archived
   6.18 rear RAW10 frame; held black=64, white=11.5 and sRGB transfer fixed.
   Changing only grey-world gains from unity to R=1.36186/B=1.52247 reduced
   the baseline green cast (`RESULT-20261008-white-balance`). Strong noise
   and missing physical colour validation remain; no vendor matrix applied.
   Next: confirm the actual scene colours/pose with a known-colour neutral
   target before matrix tuning or a sensor/DT orientation change.
   Live-trial attempt cannot start in the current restricted session:
   known-good `6.18.3-1-surface+`, boot `5c85d8e5-876a-4c84-8c48-93f27164d80b`;
   candidate build directory unreadable, camera nodes unavailable, and sudo
   rejected by `NoNewPrivs=1`. Needs restored device-session access; standing
   reboot authorization remains valid. No trial was selected or capture run.

4. Residual colour error may require the vendor's colour matrix rather than
   per-plane gains. Decode the rear tuning blob's CC12/CC13 reference chains
   and recover the temperature-dependent coefficient sets with their module
   and profile IDs. Expect non-identity matrices in an enabled processing
   stage. **Coefficients recovered:** rear BPS/IFE sets are identity; IPE
   has seven selector profiles, 52 temperature regions, 51 non-identity.
   `camera_tuning.py` follows all references and preserves selector/trigger
   chains (`RESULT-20261008-colour-tuning`). This supports a missing ISP
   processing lead; it does not prove the scene colour cause or RGB ordering.
   Next: establish selector semantics/coefficient ordering and use libcamera's
   CAMSS software ISP with black-level correction and AWB before colour-matrix
   tuning. Libcamera is absent locally; shell downloads are blocked by the
   current restricted environment. No guessed gains or kernel colour patch.
   **Matrix-only trial negative:** applied profile 3 / symbol 421 / region 0
   to the accessible 6.18 rear RAW10 frame, preserving all ten bits. Both RGB
   and BGR interpretations intensified the green cast; about 30% of channel
   samples became negative before clipping. This selected matrix alone is
   insufficient (`RESULT-20261008-matrix-test`); other profiles and the full
   exposure/AWB pipeline remain untested. EV is inaccessible in this sandbox.

0. The offline renderer corrupts colour and orientation: `/tmp/spxjpg/dem.py`
   writes `(g, r, b)` into RGB and its `rot90cw` is a transpose. Compare a
   standard FFmpeg `bayer_grbg8` conversion of the saved EV bytes, with one
   common percentile stretch, and verify with a known-colour Bayer fixture.
   **Confirmed offline:** known GRBG colours and padded RAW10 rows decode
   correctly; EV matches the direct FFmpeg conversion. Fixed `camera.py` to
   produce a demosaiced, common-percentile PPM (`RESULT-20261008-render`).
   Physical orientation and scene colour still need the user's confirmation.

1. The only thing missing for a frame is the camss node itself, which was
   never enabled on mainline. Change: add camss (cell-identical to 6.18 v23)
   with `vdda-phy` = L5E, `vdda-pll` = L3C, linked to the rear OV13858 on
   CSIPHY2, and build `qcom-camss`. Expect: camss binds, the media graph
   shows ov13858 -> csiphy2, and a 2112x1568 raw frame of a real scene is
   captured. **Confirmed.** Trial `20261008ev`
   (boot `fffa14b0`): colour bars (129/119-stddev, full 16-255) prove the
   sensor -> CSI -> CSID -> VFE -> IOMMU path, and the demosaiced bright frame
   is a real scene (`RESULT-20261008ef`). The user identified it as the **back**
   camera and rejected the earlier scene description and colours. The EF
   render analysis is superseded by `RESULT-20261008-render`: its custom
   converter swapped R/G and transposed an image labelled as a rotation.
   The standard GRBG preview preserves sensor pixel orientation and applies
   one common percentile stretch; it has no white balance or calibration.
   The previous mode-flip explanation is also unsupported: `0xab ^ 0xa8`
   is `0x03`, so bits 3/4 do not change between those values. The mode tables
   match the working 6.18 source. Do not infer a sensor flip from the faulty
   render or guess a white balance. Next: the user confirms actual colours
   and tablet pose for the corrected EV preview, then choose a supported
   orientation/calibration change. Do the human-session items first.

2. If camss binds but STREAMON hangs or no frame arrives: compare the live
   CSIPHY/CSID register programming and clock rates with the 6.18 run
   (`camss-video.c` bisect knob, 400/300 MHz PHY rates).
3. If the frame is empty: IOMMU SID 0x0a00/0x04e0 fault or buffers never
   written; check `arm-smmu` faults and the CSID test generator path first.

## Parked (not finished; needs a new idea or the user's decision)

### D03 reopened by user, 2026-10-10: browser video acceleration

- Secure VA setup and startup polling now register codec nodes, but actual
  H.264 decoding faults during session creation. Venus is unloaded after a
  stuck power-domain recovery. Browser integration follows working decode.
- **H-UC backing (refuted as sufficient, 2026-10-10):** BF observed a declared 3 MiB firmware-visible
  region larger than its queue allocation, with the SFR outside that region.
  The existing `spx_uc_shared_alloc` option backs the complete region and puts
  SFR inside it. BG explicitly left this off. Test this one change through a
  Venus-only module reload with bounded startup diagnostics, expecting core
  readiness and decoder/encoder registration if this is sufficient. First
  obtain the device lock. Privileged inspection now locates the installed
  `venus-core.ko` with matching vermagic; shared-UC and diagnostics are both
  off, and no module holders exist. User then authorized parallel Venus-only
  testing. Reload with this option confirmed SFR inside the backed region,
  but startup still timed out with status zero; no codec nodes. Original
  parameters restored, no reboot. Do not repeat this allocation trial.
  See RESULT-20261010-video-codec.md. Browser integration follows real decode.
- **H-firmware-version (refuted as sufficient):** installed VIDEO.IR.1.2 build 00042 differs
  from archived 2020 build 00040 and 2022 build 00061. Both archived images
  have a previously verified five-MiB load span, but no recorded live startup
  result. Temporarily select 00061, then 00040 if needed, through firmware
  lookup and a Venus-only reload; preserve installed bytes and other driver
  settings. Expected discriminator: core readiness or a changed secure/startup
  error. Both archived versions authenticated but still timed out with status
  zero at 01:22:10/01:22:21 on boot c8158f7d. Lookup, installed firmware and
  default module restored. No reboot; do not repeat these firmware swaps.
- **H-video-VA-setup (startup readiness confirmed):** SC8180X omits the
  four resource values enabling `qcom_scm_mem_protect_video_var`. Original
  SQ2 miniport constructs this same secure call (0x02000c08), with arguments
  0/0x25800000/0x01000000/0x24800000 from its Venus510 table. Added those
  resource fields and bounded return logging. Compile only Venus and reload
  it with installed firmware/default allocation; expect range-call success
  and core readiness if this omission caused startup failure. User authorized
  proceeding; secure call returned zero and firmware reached 0x40000001.
  SYS_INIT still needed host queue polling.
  See RESULT-20261010-video-memory.md.
- **H-DSP-interrupt-mask (refuted):** after VA setup, firmware consumes all
  18 command words and writes a successful SYS_INIT reply (0x20001/error0),
  but Linux leaves all 637 response words unread. One CPU interrupt drains
  an initially empty queue; Iris1 DSP bit1 remains masked in 0x1e2. Unmask
  that already-supported DSP source and expect response consumption/codec
  registration. Bounded timeout diagnostics distinguish this from packet
  parser rejection. User explicitly authorized proceeding despite build lock.
  Mask 0x1e0 still leaves the same responses unread; reverted this change.
- **H-wrapper-ack (refuted):** only the first CPU interrupt arrives, before
  responses. Iris1 omits the legacy wrapper interrupt-clear write based on a
  vendor chip branch whose live selection was never proven. Add the normal
  pre-Iris2 wrapper acknowledgement after the existing source clear; expect
  subsequent response interrupts and SYS_INIT completion. No IRQ remapping.
  Additional acknowledgement leaves the same timeout/queues; reverted.
- **H-firmware-power-collapse (refuted):** Linux enables firmware-controlled
  power collapse before awaiting SYS_INIT; the SC8180X power path is new.
  Request this property off for Iris1 only, expecting responses to interrupt
  the host if premature power collapse was suppressing notification.
  Disabling this property leaves the same timeout; reverted.
- **H-startup-poll (startup confirmed, decode fails):** vendor VedHfiSysInit explicitly reads the
  response queue at RVA0x356138 in a bounded loop. Linux instead waits for
  an interrupt. For Iris1 startup only, drain through the native parser with
  IRQ handling serialized and retain the existing one-second deadline.
  SYS_INIT completed and video32/video33 registered at 01:35:15. First
  H.264 decode produced zero frames and a firmware ARM access fault; unloaded
  Venus to stop failed recovery. See RESULT-20261010-video-memory.md.

- **H-session-ID (built; needs recovered device):** SQ2 firmware treats SYS_SESSION_INIT's ID as
  a table index, whereas native packets use a pointer hash. Assign Iris1
  sessions unique IDs below MAX_SESSIONS under the existing core lock and
  use the same IDs for commands/reply lookup. Expect session creation without
  the observed ARM access fault; then retry bounded H.264 decoding. Candidate
  core/decoder/encoder compiled. Reload at 01:42:11 could not reach firmware:
  vcodec0_gdsc stuck off after the preceding crash. All Venus modules unloaded.
  Next test needs a clean boot coordinated with the active camera session;
  no persistent modules replaced.

| Item | Why |
|---|---|
| D03 video decode | Startup repaired; session-ID candidate needs clean boot after codec power domain stuck off |
| B07 accelerators (CDSP) | 3 boots without a usable result |
| P05 automatic thermal response | Load never reaches the trip points |
| N03, N04 cellular and GNSS | Modem needs real provisioning; no SIM service |
| I01 touch startup reliability | Works on recent boots; repeat count needs B01 |

## Needs a fixture or the user

- U01, U02, U04: USB stick, charger and dock on each port and orientation.
- U03: a person confirming the external monitor shows a picture after replug.
- A04: a USB-C or Bluetooth audio device.
- P01, P02 and the battery part of P03: deferred by the user.

## Last

B01, R01, R02 and F01–F04 (repeat boots, diagnostics, final candidate and
regression) come after the feature boxes.
