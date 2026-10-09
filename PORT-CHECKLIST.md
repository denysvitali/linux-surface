# Surface Pro X mainline port checklist

**Goal: run mainline Linux on this device with every fitted hardware feature
working.** Acceptance is the 47 boxes below. **Closed: 3 of 47**
(B02, B03, D02).

Rules for this file (see `AGENTS.md`):

- The boxes are frozen. Only the user adds, splits or re-words one.
- A box is ticked only when its full text is met on a real boot. Record the
  boot ID, kernel release and result file on one line under it.
- A narrower pass goes into the result file and, at most, the "Notes" line.
  Missing fixtures or physical actions mean untested, not passed.
- What to work on next is in `TODO.md`, not here.
- The earlier long version with all partial results, lettered sub-boxes and
  evidence links is
  [CHECKLIST-HISTORY-20261008.md](tools/spx/boot-diagnostics/CHECKLIST-HISTORY-20261008.md)
  (older: [CHECKLIST-HISTORY-20261004.md](tools/spx/boot-diagnostics/CHECKLIST-HISTORY-20261004.md)).

## Status (2026-10-08)

| Area | State | What is missing |
|---|---|---|
| Boot to desktop, NVMe/LUKS root | CX/CY/DA/DB/DD actual return observed; CW startup failure unexplained | Cold/warm repeat reliability and late cleanup (B01) |
| CPU and memory (B03) | **Passed on AP; BU automatic frequency scaling active** | Recheck on final candidate |
| Storage (B02) | **AP sustained I/O; DC post-resume direct I/O pass** | Final candidate regression |
| GPU FD680 (D02) | **Passed on AW**, 30 min rendering | A person looking at the screen |
| Internal panel (D01) | **CE: D01a GNOME off/on scanout passes**; user reports display/brightness working | Visual attribution/quality, brightness range and physical wake |
| Wi-Fi (N01) | 5 GHz/reconnect and IPv6 VPN pass; 2.4 GHz accepted by user assumption | Native WAN IPv6, roaming and sustained use |
| RTC (B05) | **BX early boot time; DD RTC/alarm/sleep checks pass** | Cold power-off retention |
| Firmware TPM/security (B06) | **CT measured boot; DD sleep recovery; DO ephemeral P256 signing pass** | Secure Boot validation |
| Touch startup (I01) | BI: automatic IPTSD, ready, zero bus errors/restarts | Repeated startup reliability |
| Touch, pen (I02, I03) | **User confirms both work on BI** | Detailed gestures/pen capabilities and resume |
| Speakers (A01) | **BY desktop playback; DP shutdown; DR controls; DX live resume pass** | Persistence, useful volume/mapping/balance, reopen and arbitrary shutdown |
| Microphones (A02) | **DK array; EF native reopen; EC/ER resume; EI cold startup; EK boot opt-in** | Quality, physical mapping, persistence and full lifecycle |
| Cameras (C01–C05) | Rear processed and IR raw frames captured; front identify times out | Processed IR, physical image quality, full lifecycle and supply ownership |
| Video decode (D03) | Not working, core start times out | **Parked** after 8 boots |
| Keyboard, touchpad (I04, I05) | **BI keyboard works**; recovery keyboard restored after SSAM timeout | Startup reliability, full keys/gestures and resume |
| Buttons (I06) | User: short power press opens shutdown prompt, boot pending | Volume/posture and intended wake |
| Bluetooth (N02) | **DT: N02a radio cycling; DX: N02b discovery resumes; EA: N02c active client resumes** | Intermittent framing error, peripheral pairing/reconnect and repeated resume |
| USB data (U01) | Untested | Both ports/orientations, fixtures |
| USB-C PD, DisplayPort, dock (U02–U04) | **CG: external off/on scanout restoration passes; normal orientation API works** | Visible output, physical replug, roles/PD, ports/orientations/resume |
| Battery and charging (P01) | **CF: P01a actual charging passes, +1.26Wh/120s** | Charge-policy explanation, discharge/transitions and charger coverage |
| Suspend/resume (P03) | **DD13 direct wakes; DO/DS normal AC sleep; DX/EC/ER native/default mic resume pass**; targets masked | Full device recovery, battery sleep and physical wakes |
| Thermal (P05) | **CM cooling limits; CX/CY combined load/cleanup; DN below temporary55C, automatic testing parked** | Real automatic response, longer envelope and enclosure behavior |
| Idle power (P02) | BU: CPU scales down; GPU runtime-suspends | **Battery tests deferred by user**; remaining forced-on devices |
| Sensors (S01, S02) | **DD backend/desktop clients survive repeated/30-minute AC sleep** | Light/axes/calibration; DA fault; final regression |
| Cellular, GNSS (N03, N04) | Recovery: GNSS starts/stops but no fix; modem rejects online mode | Real modem provisioning, IPA datapath, SIM; actual GNSS fix |

## Boot, storage and platform

- [ ] **B01 — Repeatable startup/shutdown.** At least five cold boots and ten
  warm reboots on the final candidate, on battery and external power, with
  clean boot, power-off/restart and no manual repair, unexplained reset or
  regression.
- [x] **B02 — Storage integrity.** Verify read/write/fsync and checksum
  readback using disposable files; sustained I/O and post-resume I/O show no
  NVMe, IOMMU, encryption or filesystem errors. Never use destructive
  raw-device tests.
- [x] **B03 — CPU and memory operation.** All expected cores/memory available;
  bounded concurrent CPU/memory load, frequency transitions and idle recovery
  work without faults, hangs or unexplained throttling.
- [ ] **B04 — Firmware services.** ADSP/CDSP/modem and their required services
  remain stable during combined use and resume. Review the diagnostic QRTR
  rollback and pinned/debug paths; document or remove remaining workarounds.
- [ ] **B05 — RTC/time.** Verify clock retention across power-off and
  timekeeping across suspend without relying on network time to conceal a
  broken RTC.
  *Notes, not acceptance: partial passes B05a, B05b, B05c.*
- [ ] **B06 — Security hardware/firmware inventory.** Establish the actual
  TPM/ firmware security interfaces and Secure Boot support available on this
  unit; validate applicable functions with a documented boot/signing path.
  Lack of a Linux node is not proof that the hardware is absent.
  *Notes, not acceptance: partial passes B06a, B06b, B06c, B06d, B06e.*
- [ ] **B07 — Additional accelerators.** Inventory fitted DSP/NPU/other
  compute capabilities and available interfaces; validate a real supported
  workload or document the specific missing support. A thermal-zone name is
  not a working NPU.

## Internal display, GPU and video

- [ ] **D01 — Internal panel.** Native resolution/refresh, correct image and
  orientation, no flicker/corruption; visually verify brightness over its
  usable range, blank/unblank and display return after idle/suspend.
  *Notes, not acceptance: partial passes D01a, D01b.*
- [x] **D02 — GPU acceleration.** Confirm hardware rendering in desktop and
  real 3D workloads; at least30minutes of rendering/compositing plus idle
  transitions, without GPU resets, hangs, faults or silent software fallback.
  Record APIs tested.
- [ ] **D03 — Video acceleration.** Inventory the device's supported
  encode/decode blocks and formats; exercise supported hardware paths with
  real media, checking output, acceleration and sustained playback. Software
  playback is not HW decode.

## Keyboard, touchpad, touch, pen and switches

- [ ] **I01 — Reliable touch startup.** Eliminate unexplained startup timeouts
  and invalid headers, or explicitly resolve their cause and acceptable
  recovery; repeat B01 with no missing touch or manual restarts.
- [ ] **I02 — Touchscreen.** Real taps, drags, edge coverage and multi-touch
  gestures produce correct desktop actions, without stuck/missing contacts;
  repeat after display blanking and suspend. Do not mistake synthetic events
  for physical input.
- [ ] **I03 — Pen.** Verify position, pressure, tilt where supported, hover,
  buttons/eraser and palm rejection with the actual compatible pen, including
  post-resume behavior. Map advertised capabilities to those actually fitted.
- [ ] **I04 — Keyboard.** Typing, modifiers, Fn/media keys, indicators and
  backlight where fitted; detach/reattach and resume recover without stuck
  keys.
- [ ] **I05 — Touchpad.** Pointer, click, scrolling, multi-finger gestures and
  palm rejection work across detach/reattach and resume.
- [ ] **I06 — Buttons and posture switches.** Power/volume buttons,
  cover/lid/tablet state and appropriate desktop policy respond to real
  changes without duplicate events or lost wakeups. Establish which switches
  actually exist.
- [ ] **I07 — Pen accessory features.** If this keyboard/pen supports
  charging, accessory battery reporting or wireless buttons, verify those with
  the accessory; otherwise record the identified accessory model and
  applicability.

## Audio

- [ ] **A01 — Both physical speakers.** Correct independent left/right
  acoustic output, channel mapping, balance, useful volume range and mute; no
  static, clipping, excessive pops or persistent bus errors. Use bounded
  appropriate signals and measured/listened output, respecting recorded sound
  preferences.
  *Notes, not acceptance: partial passes A01a.*
- [ ] **A02 — Internal microphones.** Real known stimulus/voice recorded on
  each fitted microphone, correct routing/channel assignment and usable
  gain/noise; repeated capture/open/close without leaks or hangs. Noise-floor
  samples alone do not establish full microphone quality. Do not retain
  incidental private audio.
  *Notes, not acceptance: partial passes A02a, A02b, A02c.*
- [ ] **A03 — Audio lifecycle/userspace.** Normal PipeWire/ALSA/UCM playback
  and capture, simultaneous use, volume/mute controls and repeated open/close
  work after reboot/resume without manual mixer setup or ad-hoc repair.
  Resolve or explicitly validate the parked-session workaround and its
  resource lifetime.
  *Notes, not acceptance: partial passes A03a, A03c, A03d, A03e, A03f, A03g,
  A03h, A03i, A03j, A03k; failing A03b.*
- [ ] **A04 — External audio.** Test applicable USB-C audio/dock and Bluetooth
  output/input devices, routing, hotplug and reconnect. The logical codec
  "Headset Jack" node does not establish a physical analog jack on this
  device.

## Connectivity and external I/O

- [ ] **N01 — Wi-Fi.** Association/authentication on available supported
  bands, DNS and IPv4/IPv6 connectivity, sustained bidirectional transfer and
  reconnect after signal loss, radio toggle and suspend. Resolve overlapping
  supplicant ownership; verify relevant networking configuration, including
  the recorded IPv6 netfilter gap, without changing firewall policy merely to
  get a pass.
  *Notes, not acceptance: partial passes N01a, N01b.*
- [ ] **N02 — Bluetooth.** Real pairing, reconnect and peripheral use (HID and
  audio as available), radio toggle and resume; Wi-Fi coexistence under load.
  Preserve the active remote connection while planning radio tests.
  *Notes, not acceptance: partial passes N02a, N02b, N02c.*
- [ ] **N03 — Cellular control/data.** Stable modem startup and discovery,
  correct SIM/eSIM applicability, network registration and actual
  bidirectional data with service; disconnect/reconnect, radio control and
  resume. Resolve mode and IPA/RMNET/WWAN integration before declaring
  connectivity. An unavailable SIM or subscription remains a test dependency,
  not a pass or a driver-failure verdict.
- [ ] **N04 — GNSS/location.** Establish fitted capability and its
  modem/interface path; if applicable obtain a real fix with plausible
  time/location and reacquire. A missing `/sys/class/gnss` entry does not
  alone decide support.
- [ ] **U01 — USB data on each physical port.** Test both USB-C ports and plug
  orientations with actual USB2/USB3 devices, checksum-verified transfers and
  repeated hotplug/resume; verify negotiated speeds and no controller/IOMMU
  faults.
- [ ] **U02 — USB-C roles and power delivery.** Correct orientation/role
  detection, charger negotiation and attach/detach on applicable ports with
  known adapters; no brownouts or stuck roles. Controller enumeration is
  insufficient.
- [ ] **U03 — External DisplayPort.** Actual monitor output through each
  supported port/dock path, intended mode, hotplug, extend/mirror and suspend
  recovery. Resolve Type-C/alt-mode/HPD integration. Never live-unbind/rebind
  MSM components.
  *Notes, not acceptance: partial passes U03a.*
- [ ] **U04 — Dock and Surface Connect.** Inventory actual Surface
  Connect/dock capabilities; validate supported charging, USB, Ethernet,
  display and audio concurrently with the relevant accessories. Identify USB
  vs Thunderbolt mode correctly; a dock's product name does not prove
  Thunderbolt support.

## Cameras

- [ ] **C01 — Proper camera integration.** Resolve real regulator
  ownership/power sequencing and resource/binding issues; build and validate
  the actual enabled candidate. Do not deploy placeholder supplies or guessed
  RPMh rail votes.
- [ ] **C02 — Front camera.** Capture real scenes with correct
  colors/orientation, exposure and usable frame rate/resolution; repeated
  stream start/stop and resume.
- [ ] **C03 — Rear camera.** Real frames, supported focus/exposure and
  resolutions, correct orientation/colors; repeated stream start/stop and
  resume.
- [ ] **C04 — IR camera.** Real IR frames and any fitted
  illumination/safety/control path, repeated use and resume. Keep camera
  operation separate from any optional face-authentication integration; a raw
  frame is not biometric validation.
- [ ] **C05 — Normal camera applications.** Processed streams in normal
  userspace, camera selection, concurrent-use/resource behavior and
  privacy/activity controls where fitted. Validate actual scene output, not
  only sensor test patterns.

## Sensors, battery, power and thermal behavior

- [ ] **S01 — Light/proximity.** Correct the confirmed TCS3430 ALS binding and
  verify readings under cover/uncover stimulus and intended desktop brightness
  behavior. TCS3430 has XYZ/IR light channels, not APDS proximity; do not
  treat the former driver's proximity zero as evidence of a fitted proximity
  sensor.
- [ ] **S02 — Motion/orientation.** Inventory actual
  accelerometer/gyro/magnetometer or sensor-hub interfaces; validate axes,
  orientation changes and auto-rotation, including resume. PMIC ADCs are not
  evidence of motion-sensor support.
  *Notes, not acceptance: partial passes S02a, S02b, S02c, S02d, S02e, S02f,
  S02g, S02h.*
- [ ] **P01 — Battery and charging.** Plausible
  voltage/current/capacity/status, observed discharge and charging, AC
  transitions, charge limits where supported and low-battery behavior. Test
  applicable USB-C and Surface Connect chargers; distinguish policy/threshold
  behavior from a driver fault.
  *Notes, not acceptance: partial passes P01a.*
- [ ] **P02 — Idle/runtime power.** Measure idle and active consumption,
  CPU/GPU frequency scaling, runtime-PM behavior and battery endurance against
  a recorded reference under comparable conditions. Remove/justify diagnostic
  power pins, clock overrides and performance-governor defaults before
  daily-use acceptance.
- [ ] **P03 — Suspend/resume and wake.** At least ten controlled s2idle
  cycles, including a30-minute sleep on battery, with measured drain and
  intended wake sources. Display, input, network, audio, cameras and attached
  devices recover; no kernel hang/reset or repeated manual intervention.
  *Notes, not acceptance: partial passes P03a, P03b, P03c, P03d, P03e, P03f,
  P03g.*
- [ ] **P04 — Hibernate applicability.** Establish whether the intended
  platform/ storage/security setup supports hibernation; if supported, verify
  image restore and the same functional regression checks. An exposed `disk`
  state is not proof.
- [ ] **P05 — Thermal management.** Sensor plausibility, CPU/GPU cooling
  response and sustained combined workloads without overheating, hangs or
  firmware faults. Do not disable thermal protections or assume this device
  has a fan.
  *Notes, not acceptance: partial passes P05a, P05b.*

## Diagnostic integrity and final acceptance

- [ ] **R01 — Useful persistent diagnostics.** Diagnose missing ramoops data
  and retain identity-bound late shutdown/early failure evidence. Keep
  software callback completion distinct from physical power-off.
- [ ] **R02 — Recovery characterization.** Validate the actual reset/recovery
  coverage, including the EFI handoff, or explicitly document its remaining
  limits. Existing reboot authorization permits experiments while this is
  open; it is not evidence that a watchdog or userspace fallback covers early
  hangs.
- [ ] **F01 — Complete inventory.** Reconcile fitted model/accessories against
  firmware/DT and device evidence; assign every remaining hardware capability
  to an ID, including any optional feature listed above. No silent omissions.
- [ ] **F02 — One final candidate.** Build/install a reproducible kernel,
  config, DTB, modules, firmware and required userspace stack; all applicable
  feature tests pass on that same configuration without live repair or
  diagnostic-only force paths. Record upstream vs local patches and remaining
  workarounds.
- [ ] **F03 — Combined regression.** At least24hours of mixed realistic
  operation, battery/AC transitions and idle, plus B01/P03 cycles. Audit
  journal/error counters, peripheral reconnect, audio/camera coexistence and
  storage integrity. These finite tests give evidence, not a guarantee against
  every future failure.
- [ ] **F04 — Completion review.** Every applicable open box resolved with
  evidence, every non-applicable item justified, all known issues explicitly
  reconciled, and user-visible physical tests recorded. Do not declare "all
  hardware works" while substantive tests are blocked, untested or failing.

## Milestones (narrower than acceptance, already reached)

M01 mainline boots the encrypted NVMe root to the desktop. M02 hardware
EGL/FD680 desktop and Wi-Fi baseline. M03 touch stack reaches ready. M04 both
WSA amplifiers identify natively. M05 known-good recovery payloads preserved.
