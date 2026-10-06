# Surface Pro X mainline port checklist

**Goal: run mainline Linux on this device with every fitted hardware feature working.**

Keep this header short: no hashes, no file counts, no build narration. The
history that used to live here is in
[CHECKLIST-HISTORY-20261004.md](tools/spx/boot-diagnostics/CHECKLIST-HISTORY-20261004.md).

## Status (2026-10-06, CM: CPU/GPU cooling requests pass)

**Sensors parked:** CH/CJ/CK produced no motion samples. CL's shared-pool fix is
prepared but unbooted. Latest result: [CM](tools/spx/boot-diagnostics/RESULT-20261006cm.md), kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. **U03a passes:** two GNOME off/on cycles
restore3440×1440/50Hz external scanout. CC0 normal Type-C callback succeeds;
reverse plugs, visible output and hotplug remain unverified.
CF retains P01a actual charging pass; further battery tests are deferred.
**D01a passes on CE:** two GNOME off/on cycles
restore native2880×1920/60Hz scanout with fresh vblank and no new display faults.
Visual quality and suspend remain open. CG extends CE's power-cycle coverage to the attached dock. CA's earlier
DP0 startup/reload result remains scoped to its attached dock.
CC closes A02b: both fitted microphone inputs record known stimuli; quality,
simultaneous mapping and lifecycle remain open. CB playback reopen still fails.
**CM closes P05a:** both CPU clusters and GPU enforce/release cooling limits.
Default microphone clients remain unverified after helper failure and level abort.
B05a early RTC and N01a IPv6 VPN retain prior passes. **N01b is accepted by user
assumption from working5GHz; no2.4GHz functional pass was measured.** Light
response needs physical stimulus. Input/BT confirmations belong to BI; the
[physical report](tools/spx/boot-diagnostics/PHYSICAL-FOLLOWUP-20261004.md)
awaits attribution for later observations.

| Area | State | What is missing |
|---|---|---|
| Boot to desktop, NVMe/LUKS root | Works | Cold/warm repeat count (B01) |
| CPU and memory (B03) | **Passed on AP; BU automatic frequency scaling active** | Recheck on final candidate |
| Storage (B02) | Passed on AP | Post-resume I/O |
| GPU FD680 (D02) | **Passed on AW**, 30 min rendering | A person looking at the screen |
| Internal panel (D01) | **CE: D01a GNOME off/on scanout passes**; user reports display/brightness working | Visual attribution/quality, brightness range and resume |
| Wi-Fi (N01) | 5 GHz/reconnect and IPv6 VPN pass; 2.4 GHz accepted by user assumption | Native WAN IPv6, roaming, sustained use and resume |
| RTC (B05) | **BX: B05a early boot time passes**; readback/warm reboot pass | Cold power-off retention and suspend |
| Touch startup (I01) | BI: automatic IPTSD, ready, zero bus errors/restarts | Repeated startup reliability |
| Touch, pen (I02, I03) | **User confirms both work on BI** | Detailed gestures/pen capabilities and resume |
| Speakers (A01) | **BY: quiet default desktop playback passes** | Persistence, volume/mapping/balance, reopen and lifecycle |
| Microphones (A02) | **BN DMIC1 and CC DMIC0 record known speaker tones** | Quality, simultaneous channel mapping and full lifecycle |
| Cameras (C01–C05) | Rear sensor identifies | No frame captured |
| Video decode (D03) | Not working, core start times out | **Parked** after 8 boots |
| Keyboard, touchpad (I04, I05) | **BI keyboard works**; recovery keyboard restored after SSAM timeout | Startup reliability, full keys/gestures and resume |
| Buttons (I06) | User: short power press opens shutdown prompt, boot pending | Volume/posture and intended wake |
| Bluetooth (N02) | **User confirms Bluetooth works on BI** | Device-specific pairing/reconnect and resume |
| USB data (U01) | Untested | Both ports/orientations, fixtures |
| USB-C PD, DisplayPort, dock (U02–U04) | **CG: external off/on scanout restoration passes; normal orientation API works** | Visible output, physical replug, roles/PD, ports/orientations/resume |
| Battery and charging (P01) | **CF: P01a actual charging passes, +1.26Wh/120s** | Charge-policy explanation, discharge/transitions and charger coverage |
| Suspend/resume (P03) | Kernel exposes s2idle; systemd sleep/suspend targets masked | Intended wake, then controlled sleep |
| Thermal (P05) | **CM: P05a CPU/GPU cooling limits pass**; BH 3 min load stable | Automatic temperature response; sustained combined workload |
| Idle power (P02) | BU: CPU scales down; GPU runtime-suspends | **Battery tests deferred by user**; remaining forced-on devices |
| Sensors (S01, S02) | BW: TCS3430 runtime-PM/readout passes; **S02 parked after CH/CJ/CK** | Physical light response; auto-brightness; CL shared pool untested, registry and motion streams |
| Cellular, GNSS (N03, N04) | Recovery: GNSS starts/stops but no fix; modem rejects online mode | Real modem provisioning, IPA datapath, SIM; actual GNSS fix |

## Next work, in order

User cannot provide physical assistance (October6); continue autonomous work.
Physical observations remain unverified. USB-C Windows-driver evidence now
establishes CC polarity and port-to-QMP routing; integrate standard Type-C
switching and test the attached dock. Event decoding correction is WIP; no
USB-C acceptance box has closed. See
[USB-C contract](tools/spx/boot-diagnostics/RESULT-20261006usbc.md).

1. **Deferred three-minute quiet physical batch:** on mainline, type on the
   keyboard; cover/uncover the front light sensor for5seconds each, twice;
   obtain readiness before starting sampling, plus room-light context. Battery
   tests are deferred at the user's request (October5); omit charger actions.
   Repeating zero-only light samples without these actions adds no result.
2. **One human session (about 20 minutes),** prepared in advance so each step
   is one action: type on the keyboard and use the touchpad (I04, I05); tap,
   drag and use the pen (I02, I03); press power and volume buttons, close the
   cover (I06); plug a USB stick into each port (U01);
   look at the panel (D01, D02); pair one Bluetooth device
   (N02); rotate the device (S02); press power to wake from suspend (P03).
3. **Touch startup reliability (I01):** recovery's failed udev identification
   left no IPTSD instance to retry. One targeted add event restored the service;
   BI now starts automatically and physical touch/pen work. Verify reliability.
4. **Audio (A01–A03):** preserve BY's working continuous quiet desktop setup.
   CB's acoustic reopen fails despite a clean first close and real DSP completions;
   localize the post-close route before another changed test. No validated causal
   fix is available; avoid unchanged retries or destroying parked DSP sessions.
   The user authorized bounded speaker/microphone testing; announce capture and
   park the amps afterwards. WCD/ADM lifecycle and persistence remain open.
5. **Camera frames (C02–C04):** the working6.18 v23 rear capture is preserved in
   sibling commit `005adbc494a5` and `docs/spx-camera-recon.md`, section7. Receiver
   SID/mask is resolved; real `vdda-phy`/`vdda-pll` ownership remains missing.
   Reuse that two-frame recipe after the power contract is established; do not
   repeat unchanged camera audits or substitute dummy supplies.
6. External display and dock (U03, U04). Cellular/GNSS (N03/N04) require real
   modem provisioning before further online/reception retries; preserve the
   working WLAN dummy-file setup. Video (D03) remains parked.
7. Final candidate and regression (F01–F04). Battery tests (P01/P02) are
   deferred at the user's request; retain CF's charging pass and do not request
   charger unplug/replug or run battery load/endurance tests.

## How to use this checklist

1. Read this file, the newest entry in [LOCAL-PROGRESS.md](LOCAL-PROGRESS.md),
   and the latest actual result before continuing work. Inspect live boot identity
   and selection; dated records do not establish the current state.
2. Choose work against the open IDs below. Record which IDs each experiment
   targets; collect its result before choosing the next experiment.
3. Update status and evidence after every relevant experiment, including failures.
   Use the Happy ToDo list for bounded session work; this file retains the complete
   hardware backlog between sessions. Completing a ToDo does not close a feature.
4. Tick a box as soon as its functional test passes on a real boot. Record the
   boot ID, kernel release, method and the result file. A device node, successful
   build, driver bind or return code alone is not a pass.
5. Do not hold a box open for the final candidate. Regression on one common
   candidate is the separate F02/F03 step; reopen a box if its feature regresses.
6. Missing fixtures or physical actions mean **untested**, not passed. Mark a
   capability **not applicable** only with evidence that this device/accessory
   lacks it; leave the box unchecked and record that disposition explicitly.
   Do not invent support for a connector merely because a driver exposes a node.

Status terms: **partial** = bounded functionality demonstrated; **issue** = known
failure; **untested** = no adequate functional evidence; **inventory pending** =
physical presence or scope still needs establishing. No complete hardware category
has final acceptance yet. Numerical targets below are initial acceptance targets,
not tests already performed or promises of reliability.

## Proven milestones — narrower than hardware acceptance

- [x] **M01** Mainline-based kernel boots encrypted NVMe root and reaches the
  desktop. AM/AO/AP use the same kernel/modules/DTB/initramfs; AP passed620.77s.
- [x] **M02** Hardware EGL/FD680 desktop baseline and connected Wi-Fi passed the
  bounded AP check. Sustained graphics/network performance remains open.
- [x] **M03** AP SPI-HID/IPTSD reached ready with clean startup and no retry.
  AO's prior timeout remains unresolved; this does not close I01 or I02.
- [x] **M04** AP's right WSA and now **both BJ WSA amplifiers** identify and
  initialize natively. BJ verified separate addresses and powerdown on boot
  `1f02d693-c8b9-4372-afcd-32f599ecb35a`, kernel
  `7.3.0-rc2-spx-mainline-20261004bg+`; [BJ result](tools/spx/boot-diagnostics/RESULT-20261004bj.md).
  This does not prove audible output.
- [x] **M05** AP result/build artifacts were hash-verified; known-good recovery
  payloads, module tree and persistent default were preserved.

Evidence for M01–M05: [AP result](tools/spx/boot-diagnostics/RESULT-20261002ap.md),
[AO result](tools/spx/boot-diagnostics/RESULT-20261002ao.md),
[AM result](tools/spx/boot-diagnostics/RESULT-20261001am.md). None implies the
remaining acceptance boxes below are complete.

## Boot, storage and platform

Current: **partial**. NVMe → LUKS → LVM root is active. ADSP/CDSP/modem report
running. Surface RTC, two CPU-frequency policies and thermal zones enumerate.
No TPM or GNSS class devices are exposed; physical capability remains to be
reconciled. [Inventory](tools/spx/boot-diagnostics/HARDWARE-INVENTORY-20261002.md).

- [ ] **B01 — Repeatable startup/shutdown.** At least five cold boots and ten warm
  reboots on the final candidate, on battery and external power, with clean boot,
  power-off/restart and no manual repair, unexplained reset or regression.
- [ ] **B02 — Storage integrity.** Verify read/write/fsync and checksum readback
  using disposable files; sustained I/O and post-resume I/O show no NVMe, IOMMU,
  encryption or filesystem errors. Never use destructive raw-device tests.
  **Partial, AP:** 18 direct-I/O/fsync/checksum cycles, 2.25GiB each direction in
  62.79s, all checksums matched with no new storage/IOMMU faults; disposable file
  removed. Post-resume and final-candidate regression remain untested.
  [Evidence](tools/spx/boot-diagnostics/RESULT-20261002ap.md).
- [x] *Passed on AP (2026-10-02).* **B03 — CPU and memory operation.** All expected cores/memory available;
  bounded concurrent CPU/memory load, frequency transitions and idle recovery
  work without faults, hangs or unexplained throttling. **Partial, AP:** eight
  CPU workers completed 621 million arithmetic iterations in a 35.72-second
  run; three 512 MiB memory fill, checksum and page-readback cycles passed.
  Boot ID and zero taint were stable. A later bounded `userspace` test drove
  both policies min→max twice (0.3→1.7664 and 0.8256→3.1488 GHz). With
  `schedutil`, both rose under load and reached lower rates after load ended.
  The original `performance` governor was restored on AP. BU repeats load/idle
  scaling with the desktop stream active and retains `schedutil`; see the
  [BU hardware result](tools/spx/boot-diagnostics/RESULT-20261005bu-hardware.md).
  Sustained operation and final-candidate regression remain open.
  [Evidence](tools/spx/boot-diagnostics/RESULT-20261002ap.md).
- [ ] **B04 — Firmware services.** ADSP/CDSP/modem and their required services
  remain stable during combined use and resume. Review the diagnostic QRTR
  rollback and pinned/debug paths; document or remove remaining workarounds.
- [ ] **B05 — RTC/time.** Verify clock retention across power-off and timekeeping
  across suspend without relying on network time to conceal a broken RTC.

  - [x] **B05a — RTC supplies correct startup time before networking.** BX,
    boot `85aa4bf6-2169-41d5-9d62-ed797b570132`, kernel
    `7.3.0-rc2-spx-mainline-20261004bg+`: RTC sets UTC at3.212s, before root
    switch14.605s and first NTP source59.007s. No NTP step is logged.
    [BX result](tools/spx/boot-diagnostics/RESULT-20261005bx.md).

  **Observed AV startup, 2026-10-03:** SSAM surface_rtc0 is about791s ahead of
  NTP-synchronized wall time at495.63s; chrony stepped the system clock by
  -790.936215s during startup. Read-only evidence is retained at AV/
  timekeeping-startup. This does not establish a driver fault, retention or
  drift rate; RTC synchronization and power-off/timekeeping checks remain open.
  **Read-only diagnosis after AW return:** known-goodfbc6d663 RTC0 remains about
  791s ahead at1695/1710s uptime with synchronized NTP/UTC policy. Both kernels
  disable RTC_SYSTOHC/GENERIC_CMOS_UPDATE while chrony enables rtcsync; source
  proves its kernel RTC write path is absent. Board fragment now enables
  RTC_SYSTOHC with rtc0; distinct AX Image/modules/private initramfs now build
  and independently verify exactly this change plus its release (193 modules,
  54 embedded, exact AT DTB). AX has actually booted once asc05c40c3. Read-only
  samples show791s offset after NTP startup at60.38s, then conservative offset
  0.30–1.30s at75.39s; observer makes no writes/adjtimex query. This supports
  synchronization without direct setter tracing. Final173-sample2600s readback
  verdict independently passes:167 settled samples/2479.58s within−0.63 to+1.36s,
  taint0 while GPU rendering proceeds. Separate read-only NTP packet comparison
  places RTC within−0.25 to+0.76s; no observer writes. Retention, suspend,
  long-term drift and origin of the existing offset remain unproven.
  Actual warm known-good return b6b4f20b retains the corrected RTC within about
  +0.0185 to+1.0204s at135.87s, with no startup791s chrony step. That is one warm
  reboot, not cold power-off or suspend acceptance.
  [Diagnosis and next test](tools/spx/boot-diagnostics/RTC-SYNC-20261003.md),
  [verified AX preparation](tools/spx/boot-diagnostics/PREPARED-20261003ax.md).
  Bounded read-only observer/31 negative criteria cases now prepared. A first
  adjtimex query version was superseded before deployment because even modes0
  prompts RTC work; final probe uses no such query, NTP status from chrony
  tracking. Actual known-good RTC remains about791s ahead at3237s. Seven timers/finalizer integrate RTC30–2600 with baseline620/GPU660/review2800/
  fallback3300. RTC verdict/9 independent archive negatives and unchanged
  baseline/GPU/camera criteria pass; actual AX continuous RTC verdict now passes,
  but no full B05 acceptance follows. [Actual RTC result](tools/spx/boot-diagnostics/RESULT-20261003ax.md).
  [Observer evidence](tools/spx/boot-diagnostics/RTC-OBSERVER-20261003.md).

- [ ] **B06 — Security hardware/firmware inventory.** Establish the actual TPM/
  firmware security interfaces and Secure Boot support available on this unit;
  validate applicable functions with a documented boot/signing path. Lack of a
  Linux node is not proof that the hardware is absent.
- [ ] **B07 — Additional accelerators.** Inventory fitted DSP/NPU/other compute
  capabilities and available interfaces; validate a real supported workload or
  document the specific missing support. A thermal-zone name is not a working NPU.

## Internal display, GPU and video

Current: **partial**. Native panel mode2880×1920 is exposed; FD680 EGL baseline
passes. Historical brightness readback worked, but visual confirmation and stress
are pending. The inventory's `enabled=disabled` is one idle-time sample, not a
functional blank/unblank result. [Earlier evidence](tools/spx/boot-diagnostics/COMPONENTS.md).

- [ ] **D01 — Internal panel.** Native resolution/refresh, correct image and
  orientation, no flicker/corruption; visually verify brightness over its usable
  range, blank/unblank and display return after idle/suspend.
  **User report, October 4:** display and brightness work; tested-kernel
  confirmation and blank/unblank/resume remain pending.
  [Follow-up](tools/spx/boot-diagnostics/PHYSICAL-FOLLOWUP-20261004.md).

  - [x] **D01a — Normal desktop display power off/on.** GNOME's display
    power control disables active scanout and restores the original active
    framebuffers with fresh vblank after two brief off/on cycles, without new
    display/kernel faults. Physical image/brightness quality and suspend remain
    separate D01 checks. Use the normal compositor path; never unbind MSM.
    CE boot `a8b864a4-0813-4ce5-8ac3-c90e4759afae`, kernel
    `7.3.0-rc2-spx-mainline-20261004bg+`: two3-second off intervals disable
    internal CRTC/framebuffers; each return restores2880×1920/60Hz, a GNOME
    framebuffer and advancing fresh vblank. Final restoration passes; no new
    display/kernel faults. [CE result](tools/spx/boot-diagnostics/RESULT-20261005ce.md).

- [x] *Passed on AW (2026-10-03); visual check by a person still wanted.* **D02 — GPU acceleration.** Confirm hardware rendering in desktop and real
  3D workloads; at least30minutes of rendering/compositing plus idle transitions,
  without GPU resets, hangs, faults or silent software fallback. Record APIs tested.
  **Actual AW, 2026-10-03:** exact full AU kernel,620.25s FD680 desktop
  baseline/ordered rear idle checks pass. Independent result recomputation verifies
  60 successful image checks,30 timed60s rows and1,800 total GL/GLES render seconds
  on FD680/Mesa26.2.1 (GL4.6/GLES3.2). All10 processes have renderD128 witnesses;
  six idle windows total180.974s with runtime suspension at each endpoint and
  advancing suspended counters. No scoped GPU/kernel faults through3309.62s
  shutdown, all workload taints0, same GNOME process and fresh2801s touch/Wi-Fi
  pass. The3301s fallback returns to verified known-goodfbc6d663. AV's preceding
  missing-FD failure stays unchanged; AW20ms validation/first-witness polling
  corrects that observer. **Partial:** sustained rendering now demonstrated;
  real desktop compositing stress, visual correctness and common final-candidate
  regression remain unverified. GLES default-precision conditional/oracle
  discrepancy remains unresolved; selected explicit high precision passing does
  not resolve it. A separate known-good step-readback diagnostic now reproduces
  mediump27 and highp33. A half round-toward-zero conversion model including
  mediump output matches all12 measured pixels; the first round-to-nearest model
  did not. This provides an exact numerical explanation hypothesis, with compiler
  instruction attribution/conformance and mainline diagnostic comparison still
  unproven. Original failed evidence and frozen AX workload remain unchanged.
  [Precision investigation](tools/spx/boot-diagnostics/GLES-PRECISION-20261003.md).
  D02 stays open.
  [AW actual result](tools/spx/boot-diagnostics/RESULT-20261003aw.md),
  [AV retained failure](tools/spx/boot-diagnostics/RESULT-20261003av.md),
  [original workload/limits](tools/spx/boot-diagnostics/gpu-workload-20261003/README.md).
- [ ] **D03 — Video acceleration.** Inventory the device's supported encode/decode
  blocks and formats; exercise supported hardware paths with real media, checking
  output, acceleration and sustained playback. Software playback is not HW decode.
  **Shared UC candidate verified offline:** one computed3MiB owner backs
  unchanged queue geometry/SFR view under default-off0400 SC8180X+Iris1 gate;
  cleanup frees one owner.744 unchanged-path comparisons/24 shared cases/six
  rejected corruptions and actual14 AArch64 objects/zero-default0400 parameter
  pass.96938 source records/84669 live paths/config restrict scope to one file.
  Source/native/object capsule0cec64d9…9dec and strict final module proof
  2d2d1213…52a5 pass; original fixture/producer/partial-target failures retained.
  Modules remain uninstalled with BF vermagic; full distinct executable and
  bounded trial review precede a new one-use boot. Firmware containment/
  translation/root cause and hardware decode/encode remain unproven.
  [Candidate proof](tools/spx/boot-diagnostics/venus-uc-allocation-20261004/README.md).
  **BF actual:** PASinit/memory0 repeat; new diagnosticY0400 records actual
  auth-reset9/0 and remote resume1/0/cleanup0/0, queuebfc00000/2461696/UC3MiB/
  SFRbfbff000/4096/TZ1 and poll-110/count100/status0/mask1e2/hw5010002f.
  Core still times out before HFI/nodes/media; media skips with exact provenance.
  Normalized version matches retained Venus510 branch; UC/translation/cause and
  raw authSMC/firmware execution remain unproven. Independent actual handoff/
  startup/source/config/artifact/provider/recovery reviews pass. Strict620.52s
  scoped baseline/900.49s actual return/exact frozen replay verify. Read-only
  correlation86 retained contracts/GNU24 pins/exact sanitized macros shows SFR
  below/outside UC and an unproven0xa7000 tail mapping; retained vendor SFR is
  placed after queue data. Ownership28 independent pins separates NS context0
  from alignment4/internalCB13; Linux NS mask does not cover internal SID2304.
  Next isolated candidate tests single backing/borrowed views/one free under a
  default-off SC8180X gate after actual-C ownership checks/full fresh build.
  UC policy/translation/root cause stay open. [BF result](tools/spx/boot-diagnostics/RESULT-20261004bf.md).
  **Fresh startup diagnostic:** only three Venus files gain default-off0400
  Iris1 observations sharing32 lines.79,296 actual-C before/after comparisons,
  six rejected corruptions,16,000 concurrent calls/config and14 actual AArch64
  linked objects pass.96938 private/84669 live source paths/config verify;
  original control-compile/prefix-check mistakes are preserved.186-file proof
  24ac5c41…a5b1. Actual DMA/poll/version/API values and HFI/media stay unobserved;
  distinct BF full build/archive now verifies full Image/DTB and202 modules,
  embedded config/all vermagic/default-zero diagnostics and byte-exact BE
  raw/retained DTBs.243-file0faf4fa9…cf7e/review2b35e937…cd81 pass; only
  LOCALVERSION changes and original stale-provider verifier failure is retained.
  Separate818-file/272-link assemblyf4dc5ed7…0723 verifies202 exact staged
  modules/55 embedded modules/logger and private initramfs1da8adaa…286.
  Separate293-file preparation0971bec8…b953 freezes14 helpers/12 units;
  identity1/19, actual-C log4/parser12/15/interpreter2/3 and helper replay
  pass. Complete startup body9/30/main wrapper and strict baseline reviewer/
  actual guard1/4 now pass modeled BF fixtures. Independentcf799de0…d4a8
  verifies full source/executable/initramfs/DT/runtime/recovery; separate9450-file
  reviewed preparationfd1f4a90…ae18 corrects shared-archive paths with all
  physical predicates unchanged. Original first freeze/fixture failures remain.
  Installed review3f2534eb…bff9 now verifies three fresh payload paths/217
  module files/202 vermagic/14 helpers/12 units/six enabled inactive timers/
  84669 live paths/config/5183 recovery records. Native continuation/frozen
  handoff and one-use selection are next. No boot selected or acceptance closed.
  Subsequent single handoff scheduled08:57:39Z; timeractive/empty next verified,
  native continuation checks pass.18-file freeze8cfa30ea…f8c9 pins checker
  543aa825…3d04; final selection is deferred to immediate guarded checks.
  Actual BF startup/new values/HFI/media/620s baseline/900s return remain pending.
  [BF preparation](tools/spx/boot-diagnostics/PREPARED-20261004bf.md).
  [Diagnostic proof](tools/spx/boot-diagnostics/venus-startup-diag-20261004/README.md).
  **BE actual:** static8d300000/5MiB reservation and PAS9init/MEM9/8d300000/
  500000raw0/service0 are observed. Matching query/full apertureNOMAP remains.
  Core startup then times out-110 before HFI SYS_INIT/nodes; media180 skips.
  Independent actual startup/provider/source/artifact/recovery reviews and
  strict621.08s baseline pass.901.04s actual return/frozen baseline replay/
  candidate/recovery/source/config verify; BE terminal. Exact-C
  reset polling and retained UC evidence identify missing live DMA/status/
  version/return observations, without proving the root cause or changing
  UC policy. Auth-reset APIzero is inferred from exact ordering; raw auth
  result/firmware execution remain unobserved. Media acceptance stays open.
  [BE result](tools/spx/boot-diagnostics/RESULT-20261004be.md).
  **BE static reservation trial:** experimental8d300000/5MiB/no-map changes
  only the external board memory node. Exact BC executable artifacts/modules
  remain. Full96938-record source stream,84669 live compiled paths/config,
  complete raw/retained DT comparisons and providers pass.3104 runtime files
  freeze13 helpers/12 units, identity1/16/interpreter7/17/map1/3/actual-review-
  body6/21 cases; six timers preserve strict620s baseline/900s return.
  Installed DTB/independent installed review verify13 helpers/12 units/six
  enabled timers/217 shared modules/5183 recovery records; native continuation
  verifies. One-use handoff scheduled06:02:37Z, timeractive/empty next verified;
  selection deferred to frozen checker35387017…46dc. BE allocation/PAS/authentication/HFI/media
  result exists. Unknown owners/IPA/SPSS placement and ramoops/QSM overlap
  remain open. [BE preparation](tools/spx/boot-diagnostics/PREPARED-20261004be.md).
  **BB actual startup:** PAS9 init returns zero; memory call42000202 observes
  arguments9/fe500000/500000 and rawa0ffcfffba (-3145798). Default SCM remap
  yields-22; vendor meaning and secure allocation remain unresolved. No video
  nodes/authentication/HFI/media; actual provider contracts/VIDEOCC bind pass.
  [BB result](tools/spx/boot-diagnostics/RESULT-20261004bb.md).
  Retained PIL memory-call ABI matches, including4KiB length rounding; BB's
  existing5MiB satisfies it.23 instruction pins/six GNU checks pass; raw status
  meaning remains unidentified. Physical-region selection/secure compatibility
  remain open.35-file capsule84dde500…0447;
  [vendor review](tools/spx/boot-diagnostics/pas-status-20261004/README.md).
  Subsequent35 pins/nine functions/eight GNU checks show vendor area-query
  command02000209/descriptor1/spare0 supplies dynamic allocator's bounds;
  20-file capsule9ca22040…17eb. Query actual device bounds/raw return layout on
  a fresh diagnostic candidate before altering secure-memory placement.
  **BC actual query:**42000209/spare0 completes with raw0/8b700000/
  9ab00000/0 and valid result words. INIT0/MEM9/fe500000/500000 rawffcfffba/
  errno-22 are unchanged. Independent actual handoff/startup reviews pass,
  both parametersY/0400.620.29s baseline/900.26s actual return pass.
  Subsequent52-pin/11-GNU-check TrEE response audit correlates start/end with
  Linuxresult0/1:8b700000..9ab00000 exclusive,244MiB; currentfe500000
  reservation is outside. Keep dynamic allocation within the reported window
  next; actual PAS memory/authentication/HFI/media success remains open.
  [BC result](tools/spx/boot-diagnostics/RESULT-20261004bc.md).
  **Offline aperture correction:** exactly one alloc-ranges source line changes
  to8b700000/0f400000. Source/retained DTBs compile;642/657-node comparison
  changes only that property, provider contracts/other values/phandles/explicit
  reservations exact.84669 compiled paths/live config checked. Candidate
  retained4205df02…e812; actual reserved base/PAS/auth/HFI/media untested.
  [Correction proof](tools/spx/boot-diagnostics/VIDEO-ALLOCATION-20261004.md).
  **Offline one-use query:** exactly two SCM changes pass436 sanitized actual-
  body checks/416 BB comparisons and nine mutated candidates. Three AArch64
  constituents compile/link with unchanged configs;52 BB parser fixtures and
  17 query traces pass,33 corruptions reject. Actual BB trace replays exactly.
  Durable403-file capsule5c48431d…6404 rehashes; recovery/default/empty next
  verify. No query result or suitable allocation is established.
  [Area-query diagnostic](tools/spx/boot-diagnostics/pas-area-diag-20261004/README.md).
  **BA actual startup, 2026-10-04:** corrected provider arguments pass actual
  FDT parsing and Venus reaches normal firmware loading. It fails-22 in
  qcom_pas_mem_setup; no video nodes, HFI or media workload. Source/control-flow
  inference places PAS9's candidate memory arguments atfe500000/5MiB; no raw
  SMC result identifies the errno origin. Retained PIL extension declares5MiB
  but supplies no fixed physical address. Secure allocation remains unresolved.
  [BA](tools/spx/boot-diagnostics/RESULT-20261004ba.md).
  **Offline PAS diagnostic, 2026-10-04:** default-off/read-only PAS9 init/memory
  scope and32-line limits now distinguish caller stage/raw SCM results.91
  actual-body native checks/80 before-after cases and five mutated candidates
  pass/reject. Three actual Kbuild AArch64 constituents/independent relocatable
  link pass under unchanged BA config/96938-record source plus exactly three
  deltas. That scope linked only a relocatable object; secure memory and D03
  acceptance remain unresolved.
  [Diagnostic evidence](tools/spx/boot-diagnostics/pas-diag-20261004/README.md).
  Durable192-file capsule2ef2de50…e9c2 independently rehashes;84669 live compiled
  source paths match BA plus exactly three changes, with recovery/default and
  pending selection unchanged. Build a fresh full candidate before hardware use.
  **BB full build/private assembly pass:**96938 BA records plus three SCM
  changes and only release-config delta are frozen/stream-verified. Image/
  boardDTB/all202 modules and217-file tree/55-module initramfs pass; linked
  diagnostic gate/default-zero flag/parameter namespace verify. No new
  boot or secure-service result. Offline helper/entry/unit review and
  52 synthetic PAS traces/14 corruptions pass/reject. Strict baseline remains
  unchanged; BA boot DTB/firmware must stay exact.
  Durable958-file/272-link build and916-file preparation archives rehash;
  review3c1839b5…485e. Actual hardware PAS/video results remain open.
  Independent predeployment review passes84669 live source paths, both
  archives/217 module files, DTB contracts/alias/45 fixtures and recovery;
  same outgoing boot/default/empty next verify. Subsequent installed deployment
  review passes exact ten helpers/twelve units/six enabled timers/source/
  artifact/recovery hashes at01:03:43Z. BB is installed and unselected;
  strict baseline is unchanged. No hardware acceptance follows from deployment.
  [BB preparation](tools/spx/boot-diagnostics/PREPARED-20261004bb.md).
  **Startup blocked, 2026-10-03:** retained SQ2 GPU0 declares a Venus engine,
  MMIO0xaa00000/2MiB and GSIs206/207; ten exact video IORT mappings differ from
  SM8150's SID namespace. Known-good b6b4f20b has Venus configured but no codec
  nodes; frozen AX disables mem2mem/Venus. AY adds a dedicated SQ2 codec
  match/consumer/carveout. Three distinct retained/installed Iris1.2 images have
  relocatable five-MiB spans, confirmed by actual Linux MDT helpers under
  ASan/UBSan.23 common register definitions match the pinned SM8150 reference.
  Native original ARM64 constructors now confirm the legacy queue layout and
  expose SYS_INIT architecture2 versus Linux's current1; Linux's builder with2
  matches exactly. Retained SMMU revision1/2 rows support the nonsecure candidate
  SID2300/mask60, including an extra wildcard alias absent from retained IORT.
  Original UC allocation now traces to a reserve-at IOVA backed by separate
  pages; retained table defaults yield df000000/16MiB, while ASL declares a
  different pool. Neither establishes live IOVA or physical firmware memory.
  The Iris1 interrupt candidate now preserves the mask/unmasks CPU2+watchdog4
  and acknowledges DSP/CPU sources separately.996 native cases/820 comparisons,
  three changed candidates and private Venus aggregate-object builds pass.
  A separate Iris1 PM candidate now enables all three GDSCs/seven clocks with
  paired bridge resets and OPP voting;118/110 native checks and three negative
  controls pass, with unchanged existing PM paths. Eight actual MDT bodies load
  all three images at synthetic addresses,33 checks with clean sanitizers.
  Guarded RAM evidence reserves the old image-loader area; a dynamic five-MiB
  no-map allocation is proposed instead of a guessed fixed address.
  A dedicated SC8180X resource/binding and board consumer now select Iris1,
  SYS_INIT2, seven clocks/three GDSCs/MMCX, paired resets, six OPPs and the
  SID2300/mask60 candidate. Firmware memory is a dynamic aligned five-MiB
  no-map reservation below4GiB.38 actual C-body native cases pass sanitizers;
  four malformed DTs and three broken native candidates reject. AY was built
  from a sealed96938-record source snapshot. Full Image/DTB and201 modules now
  link; private initramfs embeds54 exact modules/logger, with clean depmod and
  matching vermagic/embedded config. The sealed AY candidate is installed and
  fully checked and booted once. Actual90.22s startup blocks before Venus probe:
  VIDEOCC is unbound because CONFIG_SM_VIDEOCC_8150 is disabled and its module
  is absent. FDT's SM8150 fallback matches the existing driver. Early physical
  firmware reservation atfe500000..fe9fffff is observed; PAS/HFI remains untested.
  A fresh AZ candidate enables SM_VIDEOCC_8150=m; resolved configuration changes
  only that supplier and release name. Full Image/DTB and202 modules link;
  provider OF alias resolves and the217-file module tree/55-module private
  initramfs verify, with exact AY boot DTB. Original stale count/filename check
  failures remain preserved. Durable828-file/272-link build and293-file
  preparation archives verify; independent pre-deployment review checks84669
  live source paths/217 module files/45 fixtures and unchanged recovery/DTB.
  Real-film baseline/high-B-frame H.264 fixtures
  and twice-exact120-frame software references are archived; guarded V4L2
  decode/encode output testing is prepared, not run. No new video acceptance.
  Actual AZ startup now binds VIDEOCC but Venus probe fails-22: both source and
  actual boot DT omit tag arguments required by all four two-cell ICC endpoints.
  Independent actual-FDT parsing verifies the resulting GIC phandle1 lookup;
  earlier fixed-stride offline checks missed provider arity. The180s media
  gate skips normally. See [AZ result](tools/spx/boot-diagnostics/RESULT-20261003az.md).
  Fresh BA supplies four zero ICC tags. Source and actual boot tree provider
  arity/exact references now pass; seven malformed ICC controls reject on both.
  Every other actual AZ boot-tree property/reservation remains exact.225-file
  offline capsuleb4a63ab1…3a4b verifies. Full Image/DTB and202 modules now link;
  private217-file module tree/55-module initramfs/logger and depmod/vermagic/
  provider alias checks pass. Durable972-file/272-link build and625-file preparation archives verify;
  independent pre-deployment review checks84669 live source paths,217 modules,
  both DT contracts and45 fixtures/recovery. No new hardware acceptance.
  [BA preparation](tools/spx/boot-diagnostics/PREPARED-20261004ba.md).
  Media bandwidth tables remain provisional; separate SPI175 watchdog routing,
  live corner/rate transitions and physical allocation/UC behavior stay open.
  Remaining packet ABI, hardware-version/runtime mask behavior,
  input-ID/live security policy, power/reset sequencing and secure firmware
  loading remain unvalidated; no formats or media workload have passed.
  [Video inventory](tools/spx/boot-diagnostics/video-integration-20261003/README.md),
  [startup contracts](tools/spx/boot-diagnostics/video-startup-20261003/README.md),
  [Iris1 IRQ candidate](tools/spx/boot-diagnostics/video-iris1-20261003/README.md),
  [power/memory candidate](tools/spx/boot-diagnostics/video-power-20261003/README.md),
  [dedicated Iris1 integration and AY boundary](tools/spx/boot-diagnostics/video-power-20261003/INTEGRATION.md),
  [actual AY startup](tools/spx/boot-diagnostics/RESULT-20261003ay.md),
  [real-film output fixtures](tools/spx/boot-diagnostics/video-media-20261003/README.md).

## Keyboard, touchpad, touch, pen and switches

Current: **issue/partial**. Type Cover keyboard/touchpad, power/volume buttons,
KIP tablet switch and stylus/virtual touch nodes enumerate. AQ failed initial probe with no IRQs, three zero/invalid headers and no HID
publication. Its service retry cannot run without a HID node. AO had one touch-open
timeout and three invalid headers; iptsd's automatic retry recovered. AP had two
clean windows, no timeout/invalid headers and no automatic retry;
this does not explain AO's failure. Physical input has not been signed off.
[AP comparison](tools/spx/boot-diagnostics/RESULT-20261002ap.md).

- [ ] **I01 — Reliable touch startup.** Eliminate unexplained startup timeouts and
  invalid headers, or explicitly resolve their cause and acceptable recovery;
  repeat B01 with no missing touch or manual restarts. AO is not a clean pass.
  **Recovery-kernel issue, 2026-10-04:** BA's original installed preboot guard
  rejects returned known-good19cfd105: touch not ready, bus errors1(-22).
  A normal persistent known-good reboot1f30baae repeats not ready/6(-22), with
  exact recovery payloads/modules verified. Raw startup/shutdown logs and
  rejected guard are archived under BA; no BA trial outcome follows. Fresh
  mainline touch checks remain strict. [Prepared BA evidence](tools/spx/boot-diagnostics/PREPARED-20261004ba.md).
  **Issue, AQ:** initial probe timed out before HID publication; no touch IRQs,
  three invalid zero headers, final not ready at620.31s. This repeats the K/AC/AL
  initial-probe failure class and is distinct from AO's reopen. Source output
  payload functions were not reached; cause remains unresolved.
  [Evidence](tools/spx/boot-diagnostics/RESULT-20261003aq.md).
  **Timing candidate:** retained GTCH `_PS0`/`_RST` explicitly use300ms
  before reset release; the board supply now has startup-delay-us300000.
  Compiled provider DTB differs from AQ by exactly this one property and passes
  fixed-regulator schema. AR boot5b14cce2-951f-4b43-a786-3cd2339f79b5 has two
  initial clean ready sequences, with zero polls and zero touch errors at the
  discovery and620.97s snapshots. Logged assert→deassert intervals326/322ms;
  AS's independent rear-enabled boot29748fff-2312-42c5-982e-04bbd2304b52
  repeats two clean sequences/finalready0errors,328/329ms reset holds and
  136/137ms to first powered IRQ. AR/AS are two passing boots with different
  camera DT state; B01 repetition targets, physical input and electrical timing
  remain unverified.
  AW repeats clean startup in three bounded windows (63 lines), zero counters
  at620.25s and2801.02s after1,800s GPU rendering; no physical touch acceptance
  or B01 repetition completion follows. [AW](tools/spx/boot-diagnostics/RESULT-20261003aw.md).
  Custom PEP delay units/SBFF selection
  are not assumed.
  [Audit](tools/spx/boot-diagnostics/TOUCH-FIRMWARE-TIMING-20261003.md).
  AR's distinct full source/config/kernel/modules/DTB/private initramfs now verify;
  installed208 module files and actual boot verify. Its DTB compares to AQ with
  only the timing property added. [Actual record](tools/spx/boot-diagnostics/RESULT-20261003ar.md),
  [trial plan](tools/spx/boot-diagnostics/AR-PLAN-20261003.md).
- [ ] **I02 — Touchscreen.** Real taps, drags, edge coverage and multi-touch gestures
  produce correct desktop actions, without stuck/missing contacts; repeat after
  display blanking and suspend. Do not mistake synthetic events for physical input.
  **Working basic function, BI:** user confirms touch works on boot
  `84e729fc-a68c-4720-a6f0-042acf60f604`, kernel
  `7.3.0-rc2-spx-mainline-20261004bg+`, after the finger-drag test request.
  Edge coverage, multi-touch and blank/resume behavior were not individually
  reported. [BI result](tools/spx/boot-diagnostics/RESULT-20261004bi.md).
- [ ] **I03 — Pen.** Verify position, pressure, tilt where supported, hover,
  buttons/eraser and palm rejection with the actual compatible pen, including
  post-resume behavior. Map advertised capabilities to those actually fitted.
  **Working basic function, BI:** user confirms pen works on the same identified
  BI boot after the hover/draw test request. Pressure, tilt, buttons/eraser,
  palm rejection and resume remain unverified.
  [BI result](tools/spx/boot-diagnostics/RESULT-20261004bi.md).
- [ ] **I04 — Keyboard.** Typing, modifiers, Fn/media keys, indicators and backlight
  where fitted; detach/reattach and resume recover without stuck keys.
  **Partial, BH:** user confirms typing works on boot `c89ea4ed-9363-4727-a786-4a2231817165`,
  kernel `7.3.0-rc2-spx-mainline-20261004bg+`. The later user report confirms
  detach/reattach, with a delay, but its tested kernel is pending. Remaining
  keys and resume are untested.
  [Result](tools/spx/boot-diagnostics/RESULT-20261004bh.md).
  **BI:** user again confirms keyboard works, on boot
  `84e729fc-a68c-4720-a6f0-042acf60f604`, same kernel release.
  [BI result](tools/spx/boot-diagnostics/RESULT-20261004bi.md).
  **Recovery only, October 4:** boot `ab15d0b8-0e5b-404b-a380-246b9878f4ca`,
  `6.18.3-1-surface+`, lost keyboard and battery devices after an SSAM firmware
  request timed out. One late bind restored them; the user confirms keyboard
  function. Startup reliability remains open.
  [Recovery result](tools/spx/boot-diagnostics/RECOVERY-KEYBOARD-20261004.md).
- [ ] **I05 — Touchpad.** Pointer, click, scrolling, multi-finger gestures and palm
  rejection work across detach/reattach and resume.
  **Partial, BH:** user confirms clicking and trackpad use on the same boot;
  the later user report confirms slow detach/reattach, with boot attribution
  pending. Gestures, palm rejection and resume remain unconfirmed.
  [Result](tools/spx/boot-diagnostics/RESULT-20261004bh.md).
- [ ] **I06 — Buttons and posture switches.** Power/volume buttons, cover/lid/tablet
  state and appropriate desktop policy respond to real changes without duplicate
  events or lost wakeups. Establish which switches actually exist.
  **User report, October 4:** a short power press opens the shutdown prompt;
  boot attribution pending. Sleep is masked in the shared userspace installation.
- [ ] **I07 — Pen accessory features.** If this keyboard/pen supports charging,
  accessory battery reporting or wireless buttons, verify those with the accessory;
  otherwise record the identified accessory model and applicability.

## Audio

Current: **partial; bounded desktop playback works on mainline**. BP's internal
DMIC1 verified left/right/both and a second application after idle through
PipeWire/PulseAudio and one initialized native PCM. No capture clipping or ALSA
capture error occurred. Closing playback while amplifiers remained attached
disabled the speaker streams and left an empty SoundWire FIFO; then the helper
parked both amps. BN supplies the amps-off acoustic control. Persistent desktop
integration, physical mapping, quality and repeated hardware reopen remain open,
as do WCD RX overflow messages and ADM capture-close timeout(-110).
Read [BN](tools/spx/boot-diagnostics/RESULT-20261004bn.md) and
[BP](tools/spx/boot-diagnostics/RESULT-20261004bp.md).

- [ ] **A01 — Both physical speakers.** Correct independent left/right acoustic
  output, channel mapping, balance, useful volume range and mute; no static,
  clipping, excessive pops or persistent bus errors. Use bounded appropriate
  signals and measured/listened output, respecting recorded sound preferences.
  **BI:** user reports speakers do not work. This trial intentionally blacklists
  the internal codecs/SoundWire controller; only the dock USB audio card is
  present. This does not test an enabled internal playback path. The known 6.18
  stereo sequence still needs adaptation; see [audio next step](tools/spx/boot-diagnostics/AUDIO-NEXT-20261004.md).
  **BJ:** both physical IDs and native codec initialization passed on boot
  `1f02d693-c8b9-4372-afcd-32f599ecb35a`, kernel
  `7.3.0-rc2-spx-mainline-20261004bg+`, followed by verified amps-off readback.
  No PCM or acoustic test ran. [BJ result](tools/spx/boot-diagnostics/RESULT-20261004bj.md).

  - [x] **A01a — Microphone-verified channel test signals.** Restored on BU,
    boot `48d25b6b-14bf-488f-97bd-916f0ded7ee4`, kernel
    `7.3.0-rc2-spx-mainline-20261004bg+`: left/right/both, another application
    after idle, and actual public output at peak 4000 pass unchanged acoustic
    thresholds. The timing fix removes active silence insertion; no gaps were
    inserted. [BU result](tools/spx/boot-diagnostics/RESULT-20261005bu.md).
    This establishes output from both digital channels, not physical mapping,
    balance or the full useful listening-volume range.
    BW repeats all phases and default-output handoff at quiet1433/minimum PA;
    [BW result](tools/spx/boot-diagnostics/RESULT-20261005bw.md).

- [ ] **A02 — Internal microphones.** Real known stimulus/voice recorded on each
  fitted microphone, correct routing/channel assignment and usable gain/noise;
  repeated capture/open/close without leaks or hangs. Noise-floor samples alone
  do not establish full microphone quality. Do not retain incidental private audio.

  - [x] **A02a — DMIC1 records a known acoustic stimulus.** BN captured the
    speaker test tones on MM2, S16_LE/48 kHz/mono, without clipping or capture
    errors, on boot `b6ebb51f-0d63-4946-a631-e2ab3f424569`, kernel
    `7.3.0-rc2-spx-mainline-20261004bg+`.
    [BN result](tools/spx/boot-diagnostics/RESULT-20261004bn.md).

  - [x] **A02b — DMIC0 records a known acoustic stimulus.** CC, boot
    `75135fb8-8413-45c9-8321-7713bc7cbec9`, kernel
    `7.3.0-rc2-spx-mainline-20261004bg+`: selected DMIC0/DEC0/MM2 records
    quiet left/right/both tones; the identical digital signals disappear with
    amplifier power off. Both fitted inputs now have known-stimulus evidence.
    Quality, simultaneous channel mapping and full lifecycle remain open.
    [CC result](tools/spx/boot-diagnostics/RESULT-20261005cc.md).

- [ ] **A03 — Audio lifecycle/userspace.** Normal PipeWire/ALSA/UCM playback and
  capture, simultaneous use, volume/mute controls and repeated open/close work
  after reboot/resume without manual mixer setup or ad-hoc repair. Resolve or
  explicitly validate the parked-session workaround and its resource lifetime.

  - [ ] **A03a — Bounded desktop applications and SoundWire shutdown.** BU
    passes left/right/both and another application after idle; the actual
    default desktop sink passes acoustically. A two-minute ordinary desktop
    stream completes with the same PCM owner and capture closed.
    [BU result](tools/spx/boot-diagnostics/RESULT-20261005bu.md). Clean shutdown
    failed with a shutdown XRUN on BU after reboot/session stop began. BW
    restores quiet desktop handoff; keep its working stream open.
    BP previously verified empty SoundWire FIFO after stream close on boot
    `a208387a-004a-4e7b-98f4-8c8a7945cde6`, same kernel release.
    [BP result](tools/spx/boot-diagnostics/RESULT-20261004bp.md). Hardware reopen,
    WCD/ADM lifecycle and reboot/resume persistence remain unresolved.

  - [ ] **A03b — Linux playback PCM closes and reopens with parked ASM.**
    Two distinct PCM owners each produce microphone-verified quiet left/right/
    both tones, with clean attached-amplifier teardown between them and after
    the second stream. Keep one continuous microphone capture. This milestone
    does not establish DSP/capture teardown, resume or automatic mixer setup.
    CB first close passes, but reopened left tone fails despite DSP consumption.
    [CB result](tools/spx/boot-diagnostics/RESULT-20261005cb.md). No supported fix
    is established; do not repeat the unchanged test.

  - [ ] **A03c — Default desktop microphone clients.** Two ordinary recording
    clients use the selected fitted microphone through the default desktop
    source and record known quiet speaker tones. Source-output routing and the
    retained hardware PCM owners must match across client close/idle/reopen.
    Restore the previous source and park the amplifiers; retain no private raw
    recording. CM reaches client idle, then helper cleanup crashes and loses
    the scores; no acceptance. [CM result](tools/spx/boot-diagnostics/RESULT-20261006cm.md).
    Persistent availability, hardware capture reopen and full teardown stay open.

- [ ] **A04 — External audio.** Test applicable USB-C audio/dock and Bluetooth
  output/input devices, routing, hotplug and reconnect. The logical codec
  "Headset Jack" node does not establish a physical analog jack on this device.

## Connectivity and external I/O

Current: **partial/untested**. Wi-Fi carries the session; hci0 exists. Only USB root
hubs are currently attached; no Type-C class ports or WWAN device are exposed.
Historical modem queries reported factory-test mode and absent SIM, with missing
host datapath; that is not current cellular service verification.
[Inventory](tools/spx/boot-diagnostics/HARDWARE-INVENTORY-20261002.md),
[modem history](tools/spx/boot-diagnostics/COMPONENTS.md),
[QRTR review](tools/spx/boot-diagnostics/QRTR-20260922.md).

- [ ] **N01 — Wi-Fi.** Association/authentication on available supported bands,
  DNS and IPv4/IPv6 connectivity, sustained bidirectional transfer and reconnect
  after signal loss, radio toggle and suspend. Resolve overlapping supplicant
  ownership; verify relevant networking configuration, including the recorded
  IPv6 netfilter gap, without changing firewall policy merely to get a pass.
  **BW partial:** existing5GHz profile disconnect/reconnect succeeds in9.04s;
  verified-HTTPS download succeeds afterward. Startup25MB download ~419Mbit/s.
  BU upload ~189Mbit/s remains demonstrated; other bands, roaming and resume
  stay open. [BW result](tools/spx/boot-diagnostics/RESULT-20261005bw.md).

  - [x] **N01a — IPv6 VPN connectivity and firewall setup.** BY boot
    `f23d0acb-8e26-49af-b888-5769a13b7a04`, kernel
    `7.3.0-rc2-spx-mainline-20261004bg+`: Tailscale installs its intended IPv6
    rules with no router-health error; three ICMPv6 packets to a configured
    peer return without loss. Native WAN IPv6 and exit/subnet routing are
    separate tests. [BY result](tools/spx/boot-diagnostics/RESULT-20261005by.md).

  - [x] **N01b — 2.4 GHz Wi-Fi: accepted by user assumption (2026-10-05), untested.**
    User: “If 5GHz work you can assume 2.4 GHz works too.” This is an acceptance
    exception based on working5GHz; no observed2.4GHz pass is claimed. The
    original functional test would associate a visible
    saved profile on a confirmed 2.4 GHz channel, complete bounded HTTPS
    transfers and restore the original connection. Roaming, sustained use and
    resume remain under N01. Zyxel_A0B9 is now visible on 2.4 GHz; use an owned
    temporary clone without changing saved credentials or original profiles.
    CD boot `52fe2d53-cea0-4c5c-b496-b22fcf427e9b` on the fixed7.3 kernel
    stops before association: NetworkManager requires unavailable secrets.
    Original IoT5 restored, clone deleted, 1MB HTTPS transfer passes afterward;
    no 2.4 GHz data test occurred. User accepted the assumption afterward;
    do not spend further boots on this prerequisite. If revisited, configure
    usable credentials through NetworkManager first. [CD result](tools/spx/boot-diagnostics/RESULT-20261005cd.md).

- [ ] **N02 — Bluetooth.** Real pairing, reconnect and peripheral use (HID and
  audio as available), radio toggle and resume; Wi-Fi coexistence under load.
  Preserve the active remote connection while planning radio tests.
  Recovery reference: missing public address corrected using the existing
  installation address; BlueZ controller/discovery work. BG mainline completes
  firmware setup, but RFCOMM/HIDP/UHID are disabled. BH adds those modules and
  discovers 19 devices after unblock/setup. User later reports GNOME cannot
  enable Bluetooth, with boot attribution pending. Current recovery controller
  restored by runtime address configuration. User confirms “BT works now” on
  recovery boot `f309dbfa-4e99-4bdd-9059-efc12f21b817`, `6.18.3-1-surface+`.
  **BI:** user confirms Bluetooth works on mainline boot
  `84e729fc-a68c-4720-a6f0-042acf60f604`, same kernel release. Specific peripheral,
  pairing/reconnect and resume details were not reported.
  [BI result](tools/spx/boot-diagnostics/RESULT-20261004bi.md).
  [Follow-up](tools/spx/boot-diagnostics/PHYSICAL-FOLLOWUP-20261004.md).
- [ ] **N03 — Cellular control/data.** Stable modem startup and discovery, correct
  SIM/eSIM applicability, network registration and actual bidirectional data with
  service; disconnect/reconnect, radio control and resume. Resolve mode and
  IPA/RMNET/WWAN integration before declaring connectivity. An unavailable SIM or
  subscription remains a test dependency, not a pass or a driver-failure verdict.
- [ ] **N04 — GNSS/location.** Establish fitted capability and its modem/interface
  path; if applicable obtain a real fix with plausible time/location and reacquire.
  A missing `/sys/class/gnss` entry does not alone decide support.
  **Recovery prerequisite test, October5:** LOC standalone/unlocked control and
  explicit START/STOP work, but60seconds produces no fix or satellite list.
  Modem online transition fails `DeviceNotReady`; it remains factory-test.
  Installed rmtfs-dummy supplies zero-filled placeholders for WLAN bootstrap.
  Resolve actual modem provisioning before repeating reception tests; no mainline
  acceptance follows. [Result](tools/spx/boot-diagnostics/RESULT-20261005-recovery-gnss.md).
- [ ] **U01 — USB data on each physical port.** Test both USB-C ports and plug
  orientations with actual USB2/USB3 devices, checksum-verified transfers and
  repeated hotplug/resume; verify negotiated speeds and no controller/IOMMU faults.
- [ ] **U02 — USB-C roles and power delivery.** Correct orientation/role detection,
  charger negotiation and attach/detach on applicable ports with known adapters;
  no brownouts or stuck roles. Controller enumeration is insufficient.
  **User report, October 4:** USB-C charging works; tested kernel, port,
  orientation and negotiation coverage remain pending.
- [ ] **U03 — External DisplayPort.** Actual monitor output through each supported
  port/dock path, intended mode, hotplug, extend/mirror and suspend recovery.
  Resolve Type-C/alt-mode/HPD integration. Never live-unbind/rebind MSM components.
  **User report, October 4:** connected dock monitor shows nothing; boot and
  dock model pending. **BZ:** early USC-to-DP0 forwarding starts at12.114s and
  receives real dock events without a requested replug. Samsung S34J55x EDID
  checksums pass; GNOME extends to3440×1440/50Hz; DRM has an active external
  framebuffer and consecutive vblanks20ms apart. Boot
  `8518c5f4-1306-4e70-a9a0-f8f08a96cef1`, kernel
  `7.3.0-rc2-spx-mainline-20261004bg+`.
  [Result](tools/spx/boot-diagnostics/RESULT-20261005bz.md).
  Visible output, physical hotplug, orientations, second port and resume remain
  unverified. No explicit initial-state GET/replay is implemented.
  **CA:** forwarder-only reload receives fresh disconnect/reconnect notifications
  and recovers the same external mode, with settled vblanks20ms apart; no
  synthetic HPD or physical action. No frame-done timeout during this observed
  startup/reload. Boot `9349d90b-0cdc-4363-8d80-1f45bc4b9c9d`, same fixed7.3
  release. [Result](tools/spx/boot-diagnostics/RESULT-20261005ca.md). Continuous
  visible output and guaranteed firmware state replay are not established.
  [Follow-up](tools/spx/boot-diagnostics/PHYSICAL-FOLLOWUP-20261004.md).
  - [x] **U03a — Desktop external display off/on restores scanout.** CG,
    boot `e9748c2e-ca89-4ea7-b40d-f3c046eef12f`, kernel
    `7.3.0-rc2-spx-mainline-20261004bg+`: two Mutter power cycles disable and
    restore both CRTCs, matching3440×1440/50Hz external mode, GNOME framebuffer
    and fresh vblank. No new display faults. Visible output remains unverified.
    [Result](tools/spx/boot-diagnostics/RESULT-20261006cg.md).
- [ ] **U04 — Dock and Surface Connect.** Inventory actual Surface Connect/dock
  capabilities; validate supported charging, USB, Ethernet, display and audio
  concurrently with the relevant accessories. Identify USB vs Thunderbolt mode
  correctly; a dock's product name does not prove Thunderbolt support.

## Cameras

Current: **rear control path partial; capture absent**. AS normally probes rear
OV13858 through CCI with real providers, then runtime suspends. No CSI receiver
is enabled. Front OV5693, rear OV13858 and IR OV7251 raw capture worked in the
older6.18 sibling tree, not this candidate. Analog/remaining sensor supplies,
firmware ownership, receiver DT/bindings and capture integration remain open. [Camera inventory](tools/spx/boot-diagnostics/CAMERA-STATUS-20260922.md),
[offline work](tools/spx/boot-diagnostics/camera-offline/README.md).

- [ ] **C01 — Proper camera integration.** Resolve real regulator ownership/power
  sequencing and resource/binding issues; build and validate the actual enabled
  candidate. Do not deploy placeholder supplies or guessed RPMh rail votes.
  **Offline DMA/resource review, 2026-10-03:** retained IORT/SMMU INF support all16
  streams covered by SID0xa00/mask0x4e0; the old eight-stream comment omitted
  bit0x400 aliases. IORT GPU0.AVS0's16 camera requester mappings target the apps
  SMMU; its DSDT dependency names VFE0. All20 historical MMIO/IRQ descriptions
  match MPCS/VFE0 firmware resources. No hardware capture follows; analog supply
  ownership and SC8180X programming compatibility remain open.
  [DMA contract](tools/spx/boot-diagnostics/camera-capture-audit-20261003/DMA-CONTRACT.md).
  The retained MIPI driver has verified PoFx registration/activation/idle and
  ACPI PERF call sites, but unresolved external/indirect paths leave actual analog
  ownership open. [Power path](tools/spx/boot-diagnostics/camera-capture-audit-20261003/MIPI-POWER-PATH.md).
  **Receiver power follow-up after AX return:** the prior CPXC-only inventory
  omitted independent CPC0/CPC1/CPC2 tables. All 2475 literal packages now verify;
  MPCS has four components/eight states and VFE0 thirteen/twenty-six. Ordered
  clock/MMCX recipes, 81 instruction checks, eight imports and four rejected
  fixtures support a bounded power contract; actual Windows consumption and dedicated analog
  wiring remain unproven. The subsequent clock review below supersedes the
  initial comparison of raw 300/400 MHz fields with Linux values.
  Six callback bodies include the unrecorded active-condition leaf. 33-file AX
  archive verifies; no hardware operation or acceptance.
  [Receiver power contract](tools/spx/boot-diagnostics/camera-capture-audit-20261003/RECEIVER-POWER-CONTRACT.md).
  **Static PEP loader now traced:** STND lists reversed names DM0C/DM1C/DM2C/XMPC;
  verified byte assembly yields C0MD/C1MD/C2MD/CPMX requests. 76 instruction
  checks in twelve ranges support the table/device/action parser path and WDF
  reference indices. Native C/UBSan verifies all 31 names plus direct STND;
  four altered exports reject. 44-file AX archive verifies. Actual Windows
  requests, resource execution/default ownership and PHY analog wiring remain
  unobserved; no enabled receiver or capture acceptance.
  [PEP loader contract](tools/spx/boot-diagnostics/camera-capture-audit-20261003/PEP-LOADER-CONTRACT.md).
  **PEP clock conversion follow-up:** raw action8 becomes enable/set-frequency
  and raw mode3 becomes closest. The retained BSP plan selects400 MHz for MPCS's
  300 MHz CPHY request and300 MHz for its timer. Local CAMCC/SC8180X PHY requests
  are corrected accordingly. 85 instruction checks, sixteen BSP nodes/requests,
  96 native model cases and seven rejected fixtures pass. Both affected ARM64
  objects compile in a private source copy with unchanged AX configuration.
  MMCX domain pointers
  do not establish dedicated PHY/PLL analog ownership. No live clock/capture
  acceptance follows; the receiver stays disabled.
  [PEP clock contract](tools/spx/boot-diagnostics/camera-capture-audit-20261003/PEP-CLOCK-CONTRACT.md).
  **PEP power-domain follow-up:** raw footswitch1/2 selects software control.
  Eight retained camera GDSC addresses/control masks agree with Linux; selected
  calls vote MMCX before enable and recompute votes after collapse. 105 byte
  contracts/24 ranges/64 actions and183 actual Linux helper cases pass;
  ten altered contracts reject. Five retained default lists do not force camera
  clocks always-on or exclude the eight camera domains. PEP power-on polling
  differs from Linux CFG polling; neither transition equivalence nor dedicated
  PHY/PLL analog wiring is established. No receiver enable or acceptance.
  [PEP power-domain contract](tools/spx/boot-diagnostics/camera-capture-audit-20261003/PEP-POWER-DOMAIN-CONTRACT.md).
  A pinned vendor PHY comparison now verifies the expected0x10000000 revision
  check and47 fixed GEN2 1.0 lane values. Actual Linux modeled MMIO produces124
  writes at the rear's two supported rates; four wrong programming/profile
  fixtures reject. Ten extra Linux calibration writes and vendor conditional
  tables remain explicit differences; resource equality does not prove identical
  hardware. Analog ownership, CSID/VFE revisions and real capture stay open.
  [PHY programming](tools/spx/boot-diagnostics/camera-capture-audit-20261003/PHY-PROGRAM-CONTRACT.md).
  **Offline CSID/VFE contract, after AX return:** pinned SQ2 ISP bytes verify47
  instruction contracts,66 full/Lite CSID register stores and69 actual Linux
  macro values, including the VFE+0x4000 CSID/+0x2000 bus split and bounded
  writer switch. Four wrong profiles reject. This supports the existing Gen2
  CSID/17x VFE register subset; complete programming, analog ownership and
  capture remain unvalidated. Two historical logs report VFE0 1.2.1/CSID0 1.0.0;
  v23 additionally records PHY0x10000000 and dummy-supply warnings. Their original
  boot/full source provenance is absent from those standalone logs; no current
  candidate revision or analog provider is inferred.145-file AX archive verifies.
  [ISP register contract](tools/spx/boot-diagnostics/camera-capture-audit-20261003/ISP-REGISTER-CONTRACT.md).
  **Offline progress, 2026-10-03:** rear asynchronous bulk enable replaced by
  ordered DOVDD→AVDD→DVDD enables, matching retained firmware; successful-prefix
  rollback preserves reverse-order bulk-disable handling. Eleven ASAN/UBSAN
  cases and native strict linking of16 camera/support modules pass. SC8180X CCI
  binding added; five positive/four negative schema cases pass. Front/IR firmware
  tables vote only LDO14_A; physical AVDD/DVDD wiring is not established by old
  shared placeholders. Bounded read-only SID1 metadata now verifies LDO1/14/17
  subtypes, disabled states and configured1.200/1.800/2.856V. A standard SPMI
  provider mapping and checked voltage/no-op initialization fixes pass offline
  tests. **AQ registration verified:** all three providers disabled, zero consumers and
  all21 sampled PMIC bytes exact to AP. AR independently repeats this registration
  result; its193 normally compiled modules include the rear/CCI framework, with
  no camera consumers enabled. Power-up/shared consumers/firmware ownership
  remain untested. Rear I2C shutdown and cleanup-error handling are corrected offline: quiesce
  drains PM before controls are destroyed; failed cleanup propagates/latches the
  error and blocks further I/O instead of assuming remaining consumer votes.
  Actual-source171 ASAN/UBSAN cases and historical16-module strict link pass;
  AR's complete normal build is reused by AS; electrical/shutdown/shared-use tests
  remain open.
  CAMSS analog providers and remaining binding review are unresolved. No camera
  consumer/probe/capture occurred in AQ/AR; AS now probes the rear normally,
  with no capture. C01–C05 stay open.
  **Rear-only DT preparation:** disabled CCI0/rear draft uses the three measured
  providers and explicit GPIO17/18 pin states. Sensor/CCI/regulator schema checks
  pass disabled and enabled offline fixtures; five negative cases reject missing
  supplies/bad clock/lane count. Seven pre-existing board TLMM diagnostic groups
  are preserved unchanged; full board schema is not clean. Nine nodes/four new
  phandle properties only; every other property/reservation exact. No CAMSS or
  guessed analog rails. AS normal CCI/sensor identification is now verified; electrical
  behavior, repeated operation and capture remain untested. [Draft](tools/spx/boot-diagnostics/camera-rear-only-20261003/README.md).
  Post-AR v7 assigns CCI0 source37.5MHz, supported by CAMCC/CCI-v2 binding;
  actual AR read-only summary had inherited19.2MHz and zero enable counts.
  A separately compiled enabled rear-only candidate differs from v7 by only
  CCI/rear status, with focused schemas clean and existing TLMM diagnostics
  unchanged. Its72-file review archive independently verifies and preceded the
  AS installation; AS initial normal-probe result is now archived.
  [Next trial plan](tools/spx/boot-diagnostics/AS-PLAN-20261003.md).
  **Actual AS result:** exact AR kernel/module/initramfs reuse with AS command
  line/new boot ID. CCI reports0x10070000, rear normal ID check completed by bound
  driver. At120.65s sensor/CCI suspended, three providers disabled/zero users,
  actual sensor consumer links present,21 PMIC controls unchanged/no camera
  errors. Fresh final623.81s snapshot repeats these findings; provider60s and
  both camera archives independently rehash. Unchanged baseline621.12s and
  combinedtrial pass; fallback stopped. Raw chip ID bytes unlogged; no physical
  supply/capture acceptance. Offline receiver audit retains unknownanalog/SID
  contract and distinct sensor/receiver lane namespaces without guessed providers.
  [Receiver dependency audit](tools/spx/boot-diagnostics/camera-capture-audit-20261003/README.md).
  [Actual AS result](tools/spx/boot-diagnostics/RESULT-20261003as.md),
  [preparation](tools/spx/boot-diagnostics/PREPARED-20261003as.md).
  [Actual AQ result](tools/spx/boot-diagnostics/RESULT-20261003aq.md).
  [Evidence and next step](tools/spx/boot-diagnostics/camera-power-20261003/README.md).
  **Actual AW regression:** full AU build includes the standby/reset and
  synchronous privacy-order fixes. Initial120.34s/final624.96s normal rear/CCI/
  LED idle observations pass; no capture/physical fault or electrical validation.
  [AW](tools/spx/boot-diagnostics/RESULT-20261003aw.md).
- [ ] **C02 — Front camera.** Capture real scenes with correct colors/orientation,
  exposure and usable frame rate/resolution; repeated stream start/stop and resume.
- [ ] **C03 — Rear camera.** Real frames, supported focus/exposure and resolutions,
  correct orientation/colors; repeated stream start/stop and resume.
- [ ] **C04 — IR camera.** Real IR frames and any fitted illumination/safety/control
  path, repeated use and resume. Keep camera operation separate from any optional
  face-authentication integration; a raw frame is not biometric validation.
- [ ] **C05 — Normal camera applications.** Processed streams in normal userspace,
  camera selection, concurrent-use/resource behavior and privacy/activity controls
  where fitted. Validate actual scene output, not only sensor test patterns.
  Static vendor platform/MIPI inspection now preserves the privacy-indicator
  dispatch and CAMP CAM_PRLD11 state set. PMIC/PState messages identify indicator
  paths, not analog supplies. The subsequent pinned PRLD parser/dispatcher and
  sensor GUID/resource review decodes rearGPIO11/frontGPIO25, both active high.
  A rear-only offline DT candidate connects existing V4L2 privacy LED support;
  focused schemas, exact AS-relative delta and five negative cases pass. Physical
  LED wiring/stream/idle/failure checks and processed capture remain unverified.
  [Privacy contract and candidate](tools/spx/boot-diagnostics/camera-privacy-20261003/README.md).
  **Offline failure fix, 2026-10-03:** OV13858 no longer ignores failed standby
  writes. Managed start/stop failure asserts reset, requests synchronous PM cleanup
  and quarantines I/O until normal power-off; original error remains. The unchanged
  V4L2 wrapper's forced-success stop cannot bypass reset ordering in67 modeled
  stream cases;171 existing lifecycle cases and strict native16-module linking
  pass. Optional-reset boards, physical reset/LED timing and real capture/fault
  handling remain untested; no modified module is installed.
  [Stream failure cleanup](tools/spx/boot-diagnostics/camera-power-20261003/STREAM-FAILURE.md).
  **Offline ordering fix, 2026-10-03:** legacy/native V4L2 paths now complete
  privacy provider enable before first driver start; errors prevent start and
  roll back the light. Failed additional streams preserve existing stream/light
  state. Actual media/LED/GPIO functions pass129 modeled privacy cases,72 with
  LED support unreachable, and238 integrated rear lifecycle/fault cases.
  Physical timing/electrical success, real capture and concurrency remain open.
  [Privacy stream ordering](tools/spx/boot-diagnostics/camera-privacy-20261003/STREAM-ORDERING.md).
  [AT trial plan](tools/spx/boot-diagnostics/AT-PLAN-20261003.md).
  **Actual AT partial:** provider/sensor privacy relation, LED0/max1/no trigger,
  GPIO11-low/function0 and unclaimed front25 verify in separate290.11s read-only
  observation, repeated independently at650.95s. Original120s/final collectors
  miss the LED class OF link and fail; strict baseline620.45s passes and fallback
  stays armed.
  immutable failure/criteria/helpers remain. No physical light or stream test.
  [Actual AT record](tools/spx/boot-diagnostics/RESULT-20261003at.md).
  [Vendor contract evidence](tools/spx/boot-diagnostics/camera-capture-audit-20261003/VENDOR-POWER.md).

## Sensors, battery, power and thermal behavior

Current: **partial**. BW binds the correct TCS3430 driver and passes runtime
suspend/read cycles, but light channels stay zero without a known stimulus.
Motion requires Qualcomm's separate sensor-hub stack.
BU CPU policies now use schedutil and pass load/idle transitions. CF observes
actual battery charging,27→31%/+1.26Wh over120s. BU's earlier49%/14.72Wh,
Not charging observation still has no proven policy explanation.
GPU runtime suspend works.
[BU hardware result](tools/spx/boot-diagnostics/RESULT-20261005bu-hardware.md).

- [ ] **S01 — Light/proximity.** Correct the confirmed TCS3430 ALS binding and
  verify readings under cover/uncover stimulus and intended desktop brightness
  behavior. TCS3430 has XYZ/IR light channels, not APDS proximity; do not treat
  the former driver's proximity zero as evidence of a fitted proximity sensor.
  BW restores gain/timing settings and passes three runtime-PM cycles; physical
  response and auto-brightness remain unverified. [BW](tools/spx/boot-diagnostics/RESULT-20261005bw.md).
- [ ] **S02 — Motion/orientation.** Inventory actual accelerometer/gyro/magnetometer
  or sensor-hub interfaces; validate axes, orientation changes and auto-rotation,
  including resume. PMIC ADCs are not evidence of motion-sensor support.
  **CJ WIP:** separate SLPI/SDSP firmware starts in the reported PIL pool and
  SSC400 replies over GLINK/QRTR. Both motion clients wait for unavailable
  registry SUIDs; neither produces samples. CK's bare SID0 attach crashes SLPI.
  **Parked after three boots without motion samples.** CL's separately owned
  shared DMA pool and invocation guard are compiled and prepared, unbooted and
  untested. Continue other features before resuming SensorsPD.
  [CK result](tools/spx/boot-diagnostics/RESULT-20261006ck.md).
- [ ] **P01 — Battery and charging.** Plausible voltage/current/capacity/status,
  observed discharge and charging, AC transitions, charge limits where supported
  and low-battery behavior. Test applicable USB-C and Surface Connect chargers;
  distinguish policy/threshold behavior from a driver fault.
  **User report, October 4:** USB-C charging works, with boot attribution pending.

  - [x] **P01a — Connected charger increases battery energy on mainline.** CF,
    boot `c36de673-14e4-4c2f-bb90-5a41fc1a37b9`, kernel
    `7.3.0-rc2-spx-mainline-20261004bg+`:25 samples over120.035s show mains
    online/Charging,8.17→9.43Wh and27→31%, with no new kernel faults.
    Charger type was not supplied; transitions and both charger types remain
    untested. [CF result](tools/spx/boot-diagnostics/RESULT-20261005cf.md).
- [ ] **P02 — Idle/runtime power.** Measure idle and active consumption, CPU/GPU
  frequency scaling, runtime-PM behavior and battery endurance against a recorded
  reference under comparable conditions. Remove/justify diagnostic power pins,
  clock overrides and performance-governor defaults before daily-use acceptance.
- [ ] **P03 — Suspend/resume and wake.** At least ten controlled s2idle cycles,
  including a30-minute sleep on battery, with measured drain and intended wake
  sources. Display, input, network, audio, cameras and attached devices recover;
  no kernel hang/reset or repeated manual intervention.
  AX read-only wake audit confirms only s2idle/rtc0, no RTC alarm operations or
  wakealarm attribute; SSAM GPIO180 wake IRQ enumerates but wake policy defaults
  disabled to avoid unfiltered EC events. PMIC power-key presence does not prove
  physical wake. Identify/validate an intended wake fixture before controlled
  sleep; no suspend was attempted during the RTC/GPU trial.
  [Wake audit](tools/spx/boot-diagnostics/WAKE-AUDIT-20261003.md).
  **October5 lead:** fitted SQ2 firmware defines SSAM AC/DC relative timers
  (commands0x1a/0x1d); a30-second DC countdown and disable/readback pass on the
  6.18 recovery kernel. Expiry routing/filtering, mainline behavior and suspend
  resume remain unvalidated. SSAM's GPIO wake IRQ handler does not drain queued
  events or filter wake reasons, so wake permission remains disabled. Details
  in the [wake audit](tools/spx/boot-diagnostics/WAKE-AUDIT-20261003.md).
  **User report, October 4:** no suspend option; short power press opens shutdown
  prompt. Current recovery exposes s2idle, but shared systemd sleep/suspend
  targets are masked and `CanSuspend` is `no`. No sleep was attempted.
  [Follow-up](tools/spx/boot-diagnostics/PHYSICAL-FOLLOWUP-20261004.md).
- [ ] **P04 — Hibernate applicability.** Establish whether the intended platform/
  storage/security setup supports hibernation; if supported, verify image restore
  and the same functional regression checks. An exposed `disk` state is not proof.
- [ ] **P05 — Thermal management.** Sensor plausibility, CPU/GPU cooling response
  and sustained combined workloads without overheating, hangs or firmware faults.
  Do not disable thermal protections or assume this device has a fan.

  - [x] **P05a — Cooling requests enforce and release CPU/GPU limits.** CM,
    boot `e826a35b-d8f3-4b09-9d1b-99efb59ae9a1`, kernel
    `7.3.0-rc2-spx-mainline-20261004bg+`: with two short CPU workers, maximum
    cooling requests lower reported CPU frequencies from1.7664/3.1488GHz to
    0.300/0.8256GHz and GPU from315 to177MHz. Restoring each prior state restores
    its frequency limit and operating frequency. All states restored; thermal
    protections remain active, peak44.2°C,5.28s. This verifies the cooling-device
    control path; automatic temperature-triggered policy and sustained combined
    workloads remain open. [CM result](tools/spx/boot-diagnostics/RESULT-20261006cm.md).

## Diagnostic integrity and final acceptance

Current: recovery files/default verified, but early automatic reset recovery and
late console persistence remain unvalidated. AP observed zero old signatures in
all four ramoops buffers before probe and no retained shutdown console. The writer
and callback execution/physical rail-off remain unknown.
[AP finding](tools/spx/boot-diagnostics/RESULT-20261002ap.md).
[Persistence review and next design](tools/spx/boot-diagnostics/PERSISTENCE-AFTER-AO-20261002.md),
[recovery constraints](tools/spx/boot-diagnostics/RECOVERY.md).

- [ ] **R01 — Useful persistent diagnostics.** Diagnose missing ramoops data and
  retain identity-bound late shutdown/early failure evidence. Keep software
  callback completion distinct from physical power-off.
- [ ] **R02 — Recovery characterization.** Validate the actual reset/recovery
  coverage, including the EFI handoff, or explicitly document its remaining
  limits. Existing reboot authorization permits experiments while this is open;
  it is not evidence that a watchdog or userspace fallback covers early hangs.
- [ ] **F01 — Complete inventory.** Reconcile fitted model/accessories against
  firmware/DT and device evidence; assign every remaining hardware capability to
  an ID, including any optional feature listed above. No silent omissions.
- [ ] **F02 — One final candidate.** Build/install a reproducible kernel, config,
  DTB, modules, firmware and required userspace stack; all applicable feature
  tests pass on that same configuration without live repair or diagnostic-only
  force paths. Record upstream vs local patches and remaining workarounds.
- [ ] **F03 — Combined regression.** At least24hours of mixed realistic operation,
  battery/AC transitions and idle, plus B01/P03 cycles. Audit journal/error counters,
  peripheral reconnect, audio/camera coexistence and storage integrity. These
  finite tests give evidence, not a guarantee against every future failure.
- [ ] **F04 — Completion review.** Every applicable open box resolved with evidence,
  every non-applicable item justified, all known issues explicitly reconciled,
  and user-visible physical tests recorded. Do not declare "all hardware works"
  while substantive tests are blocked, untested or failing.

## Work order and test dependencies

**Superseded 2026-10-04 by "Next work, in order" at the top of this file.**
The text below is kept as background on each feature's dependencies.

1. AX's RTC/GPU/baseline/combined result and actual guarded known-good return
   are collected and independently verified; preserve its complete evidence,
   preceding AW pass and AV failed observer. No next boot is selected. D02 still
   needs desktop/visual checks and mainline/driver confirmation of the exactly
   matching reference round-toward-zero hypothesis. B05's enabled kernel RTC
   path passes continuous readback and one warm reboot; cold retention/suspend
   remain open. P03 needs a verified intended wake fixture; no RTC alarm path
   is exposed. Prioritize the missing hardware integrations and those fixtures.
   [AX result](tools/spx/boot-diagnostics/RESULT-20261003ax.md),
   [wake audit](tools/spx/boot-diagnostics/WAKE-AUDIT-20261003.md),
   [precision analysis](tools/spx/boot-diagnostics/GLES-PRECISION-20261003.md).
   [AW result](tools/spx/boot-diagnostics/RESULT-20261003aw.md),
   [RTC diagnosis](tools/spx/boot-diagnostics/RTC-SYNC-20261003.md).
   R01 remains open: no retained shutdown console; identical reboots alone cannot
   locate persistence loss. I01's timing change has scoped regression evidence,
   but physical input and B01 repetition remain open. B02's bounded AP storage
   check still needs post-resume and common-candidate regression.
2. Resolve touch reliability (**I01**) and complete stereo/audio paths
   (**A01–A03**). Diagnose from evidence, not from card enumeration.
3. Complete the concrete missing integrations: camera power/DT/config
   (**C01–C05**), video acceleration (**D03**), USB-C/external display
   (**U01–U04**), cellular (**N03**).
   Reassess order when evidence exposes a dependency; do not lose the other IDs.
   The [camera power audit](tools/spx/boot-diagnostics/camera-power-20261003/README.md)
   fixes rear supply ordering and CCI binding coverage offline. SID1 metadata
   supports a three-rail direct SPMI provider candidate, with no dummy supplies
   or new RPMh camera votes. AQ/AR verified idle provider registration; AS and
   later trials verify normal rear identification, with rear privacy LED idle
   evidence since AT. AX is terminal and has returned to verified known-good;
   no trial is pending. The [ISP register review](tools/spx/boot-diagnostics/camera-capture-audit-20261003/ISP-REGISTER-CONTRACT.md)
   supports the Gen2/17x register subset. Actual receiver analog ownership,
   front/IR supplies, enabled bindings and shared-consumer behavior remain open.
   Resolve those dependencies before current-candidate frame/idle/fault testing;
   do not re-arm a terminal historical attempt.
   D03's [device-specific inventory](tools/spx/boot-diagnostics/video-integration-20261003/README.md)
   now identifies the missing codec consumer/configuration and distinct SQ2 SIDs
   and firmware. [Native startup checks](tools/spx/boot-diagnostics/video-startup-20261003/README.md)
   now prove the queue subset/SYS_INIT architecture2 and narrow the SID2300/mask60
   candidate. The [Iris1 IRQ candidate](tools/spx/boot-diagnostics/video-iris1-20261003/README.md)
   now implements the bounded interrupt contracts and builds privately. Retained
   UC reserve-at policy is traced; ASL/runtime pool differences remain explicit.
   The [power/memory candidate](tools/spx/boot-diagnostics/video-power-20261003/README.md)
   now implements the all-domain power path and verifies relocatable loading
   offline. The [dedicated integration](tools/spx/boot-diagnostics/video-power-20261003/INTEGRATION.md)
   now connects resources/binding/DT/configuration and SYS_INIT2. Finish AY's
   full build/archive and guarded startup before real-media experiments;
   secure loading, live IOVA/corners, separate watchdog routing and runtime
   media bandwidth calibration remain open.
4. Perform functional input, Bluetooth and sensor checks with real stimuli;
   validate power/thermal/suspend and all cross-feature regressions. Read-only
   inventory can proceed while accessories are unavailable.
5. Run **F01–F04** on the converged candidate. Ask for a specific physical action
   or unavailable fixture only when the prepared test needs it; do not substitute
   a node listing or an invented observation.

Needed fixtures/actions include the compatible pen and keyboard, physical input
and orientation/lighting changes, known USB devices/cables and chargers, external
monitor/dock, Bluetooth peripheral, and an applicable SIM/service. The currently
empty USB inventory does not establish what the user owns. Schedule physical
camera/audio tests deliberately; preserve privacy and recorded audio preferences.

## Evidence index and latest update

- [2026-10-03 D03 dedicated Iris1 integration](tools/spx/boot-diagnostics/video-power-20261003/INTEGRATION.md):
  SC8180X resource/binding/DT now select the prior IRQ/PM paths and SYS_INIT2.
  Dynamic five-MiB aligned firmware reservation avoids occupied UEFI memory.
  Six OPPs and nonsecure SID2300/mask60 remain candidates needing live proof.
  Thirty-eight actual C-body cases pass sanitizers, with four invalid DTs and
  three broken native candidates rejected. AX boot property values/reservations
  remain exact apart from nine added nodes/two new reference phandles.
  Private AY source/archive verifies96938 records/13 exact deltas; full Image/DTB
  and201 modules link. Private initramfs/depmod/vermagic/config checks pass.
  Preparation receipts precede any one-use startup. No hardware acceptance.

- [2026-10-03 D03 Iris1 power/memory candidate](tools/spx/boot-diagnostics/video-power-20261003/README.md):
  Seven retained clock branches/three GDSCs and G4MD exit sequences verified.
  Three changed Venus files add separate PM selection, all-domain power and
  paired resets;118/110 native checks and three negative controls pass.
  Eight actual Linux MDT bodies pass33 relocation/error checks on three images.
  Fresh96937-record private base plus seven deltas builds Venus aggregates.
  Known-good RAM reserves the historical image-loader area; dynamic no-map
  firmware allocation is proposed. No OF resource, firmware load or boot;
  D03 and all47 hardware acceptance boxes stay open.
  Durable252-file AX archive manifest
  `303ead2e01c2aa46e5befc815c1b77df531ac7a75e0bbda8b90cede28dce80fb`;
  all96937 final source records/seven deltas independently verify.
- [2026-10-03 D03 Iris1 IRQ source candidate](tools/spx/boot-diagnostics/video-iris1-20261003/README.md):
  Eight original ranges/41 pins trace UC reserve-at/page backing and separate
  DSP/CPU acknowledgements. Two changed Venus files implement Iris1 mask/IRQ
  handling.996 native cases/820 previous-code comparisons and three negative
  candidates pass; Venus core/decoder/encoder aggregate AArch64 objects link in
  an exact private source snapshot. No enabled OF resource, deployment or
  hardware video acceptance. Durable183-file AX archive manifest
  `3b915a9b6ca07d136a20819be407cbc7b258f6c0f96fe1ef37e5d3006bcc7396`;
  all96937 final source records/four deltas independently verify.
  Firmware/power integration remains open.
- [2026-10-03 D03 SQ2 native startup contracts](tools/spx/boot-diagnostics/video-startup-20261003/README.md):
  Ten original ranges/45 instruction contracts, six native queue cases and
  three actual Linux C bodies verify with clean C sanitizers/assembly sentinels.
  SYS_INIT architecture2 differs from Linux1; Linux's argument2 matches.
  Both retained SMMU revisions support the candidate nonsecure2300/mask60 group.
  Durable151-file AX archive manifest
  `fefc722d86a44b86c59b02826d182b22b5355569704eac98fe6ebdb13c2b216a`.
  Initial-mask/UC-policy differences and all hardware acceptance remain open.
- [2026-10-03 D03 SQ2 video integration inventory](tools/spx/boot-diagnostics/video-integration-20261003/README.md):
  Guarded known-good has no codec nodes; AX lacks effective mem2mem/Venus support.
  Retained video resources, ten IORT mappings and three distinct Iris1.2 firmware
  images are sealed with native MDT/register checks.98-file AX archive manifest
  `f03ee85137a75657142a65ee6b4d818394e46a637269d397d10efc5c16118c8e`.
  SQ2 HFI/power/SMMU integration and real-media acceptance remain open.
- [2026-10-03 AS actual combined pass](tools/spx/boot-diagnostics/RESULT-20261003as.md):
  Rear normal probe/initial120.65s/final623.81s idle snapshots plus unchanged
  baseline621.12s independently verified.287-file result manifest
  `c280a524a59e8434bdebaf45eae9642b5abb468df712e1a36ae673ed8e56c718`;
  31-file post-result record freeze
  `df722ac7cdabb4586f5f0625a15e25738a7e9e1ce2107350ebe2bd160c3b7ae5`.
  No camera capture/physical input/acoustic or full feature acceptance.
- [2026-10-03 rear receiver audit](tools/spx/boot-diagnostics/camera-capture-audit-20261003/README.md):
  986 firmware packages/nine historical captures/reciprocal rear graph verified;
  actual analog supply/SID contract remains unresolved.16-file archive manifest
  `c039ef5d554b5ddd02299558336dddf90c51bf429b3513580ad26d9542cc4f16`.

- [2026-10-03 AQ prepared provider trial](tools/spx/boot-diagnostics/PREPARED-20261003aq.md):
 Full96,765-record source archive,755buildfiles/272links,187modules/202treefiles,
 54embedded modules and exact existing DT properties verified. Build manifest
 `0a143b87abded90e06d0984d1bc7a1a487b8dfd1cdefaae6dd31f357a15178ef`.
 Historical preparation; later AQ provider registration passed and baseline
 failed before automatic known-good return. See actual AQ result.
- [2026-10-03 C01 measured regulator candidate](tools/spx/boot-diagnostics/camera-power-20261003/README.md):
 PMIC metadata manifest `6fc4372f9bdbaad65efc649c688e9910fd51991b215705128cd4761875cf26b0`;
 104-file regulator evidence manifest `d1fe47920500ee869d16ed08df8d9426f6aa1706916ce58b18f6f96180c83d2e`.
 AQ/AR provider registration and AS rear normal probe/idle are now verified;
 physical ownership/sharing and capture remain open.
- [2026-10-03 C01 camera power audit](tools/spx/boot-diagnostics/camera-power-20261003/EVIDENCE.md):
 104-file manifest `98d475cd312be301d82d7bae809d271fc611b25e7ed4074c77e0ec06a5caa042`.
 Rear supply ordering and CCI binding validated offline; real regulator integration
 and hardware capture remained open at that audit. Later AQ/AR/AS evidence
 above supersedes its then-current AP boot.
- [AP current baseline](tools/spx/boot-diagnostics/RESULT-20261002ap.md): main
  result manifest `f8e2bccd2ee671c0c7ffc84a012c77941e71100d2cc091afb77730dc1d2959ca`.
- [AO earlier baseline](tools/spx/boot-diagnostics/RESULT-20261002ao.md): main
  result manifest `2c8aad90c8bc62b488f6e20938c0d264aac51e81aa6d369aac582a03075d010f`.
- [Current hardware metadata](tools/spx/boot-diagnostics/HARDWARE-INVENTORY-20261002.md):
 22-file archive; inventory is not a functional pass.
- [Earlier component evidence](tools/spx/boot-diagnostics/COMPONENTS.md),
  [camera history](tools/spx/boot-diagnostics/CAMERA-STATUS-20260922.md),
  [corrected microphone evidence](tools/spx/boot-diagnostics/AUDIO-ORACLE-RESTORED-20260928.md).
- Durable archives: `/var/lib/spx-boot-diagnostics/attempts/<attempt>/`;
  chronological decisions: [LOCAL-PROGRESS.md](LOCAL-PROGRESS.md).
- 2026-10-02: checklist created from archived results and a fresh read-only AO
  inventory. No functional hardware acceptance box was closed by this inventory.

- 2026-10-02, R01/I01: AP artifacts/installation and real systemd preboot guard
  verified. Source checks explicitly account for the frozen documentation-only
  delta. Persistence reader has4positive/9negative cases; archive/source guards
  reject incomplete freezes and unreviewed changes. Actual outcome is recorded in the later AP result below.

- 2026-10-02, R01/I01/B02: AP passed620.77s; two clean touch startup windows,
  no retries/errors, but AO's transient remains unresolved. All four old ramoops
  signatures were zero before probe; no late callback evidence was retained.
  B02 direct I/O verified2.25GiB each direction/62.79s with no new faults.
  Source/recovery preserved; no new trial selected and no acceptance box closed.

- 2026-10-02, I01/I02/I03: archived reopen audit finds successful setup returns
  but no powered response on AO's failed reopen. A separate three-function
  [output bounds candidate](tools/spx/boot-diagnostics/TOUCH-OUTPUT-BOUNDS-20261002.md)
  fixes payload copying/trailing initialization and rejects unrepresentable sizes.
  Native object and81,951 sanitizer cases pass; hardware validation is pending.
  AP's installed artifacts and recovery remain unchanged; no trial is queued.

- 2026-10-02, B03: AP completed a bounded eight-worker CPU and 1.5 GiB total
  memory integrity workload. A follow-up policy test showed two min/max
  transitions on both clusters and load/idle response under `schedutil`.
  Performance policy was restored; final-candidate regression remains open.
  Raw results and source are hash-checked under
  `attempts/20261002ap/cpu-memory-b03-20261002/`.
