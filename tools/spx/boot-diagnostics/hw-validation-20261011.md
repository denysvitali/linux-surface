boxes closed: 3 of 47; newly closed: none.

# Surface Pro X hardware gaps

Kernel: `7.3.0-rc2-spx-mainline-20261004bg+`; boot: `298cf388-134f-4db3-a218-413f5af213d3`; date: 2026-10-11T21:04:38+02:00

Interface observations are not functional acceptance. A suspected gap can mean
missing support, an unloaded driver, an absent accessory, access restrictions,
or a wrong probe assumption. Missing Linux nodes do not prove missing hardware.
No sound, media capture, raw sensor reads, load, sleep or reboot is performed.

## Interface findings needing investigation

| Probe | Boxes | Finding | Detail |
|---|---|---|---|
| accel.cdsp | B07 | gap suspected | no /dev/fastrpc-cdsp*; present: fastrpc-sdsp-secure; NPU has no Linux driver |
| disp.panel | D01 | needs investigation | connected mode=2880x1920 enabled=disabled dpms=Off (panel not scanning out now; lid/cover or display settings) |
| video.codec | D03 | gap suspected | no codec video nodes; modules loaded: venus_core |
| in.kbd_backlight | I04 | needs investigation | no kbd_backlight LED class device |
| in.switches | I06 | needs investigation | tablet(Microsoft Surface KIP Tablet Mode Switch); no lid/cover-closed switch |
| aud.desktop | A03 | gap suspected | internal sink=True source=False |
| aud.external | A04 | needs investigation | USB audio card present (1 [USB            ]: USB-Audio - ThinkPad Thunderb); routing/hotplug need a listener |
| net.wwan | N03 | gap suspected | netdev=none wwan ports=0 ipa module=False ModemManager=inactive |
| usb.superspeed | U01 | needs investigation | 4 SuperSpeed device(s), e.g. 4-1.4.4 USB3.1 Hub@10000; per-port/orientation coverage needs a person |
| usb.typec | U02 | gap suspected | typec ports=0 (expected 2), DT connectors=1, role switches=0 |
| usb.dp | U03 | needs investigation | DP-1=connected; only one DP connector for two USB-C ports |
| sens.als.desktop | S01 | gap suspected | iio-sensor-proxy not running (inactive) |
| sens.motion | S02 | gap suspected | IIO accel=False gyro=False magn=False; sensor proxy accelerometer=n/a; spx-sensors=inactive (sensors sit behind SLPI, opt-in service not running) |
| pwr.suspend | P03 | needs investigation | state=[freeze mem disk] mem_sleep=[s2idle] suspend.target=masked this boot ok=0 fail=0 |
| pwr.hibernate | P04 | gap suspected | disk state=True swap=False resume= on cmdline=False |
| pwr.idle | P02 | needs investigation | 2 cpuidle states; overrides on cmdline: clk_ignore_unused |
| diag.kernel_errors | F03 | needs investigation | 40 error-level lines; top: 6x wcdNx-codec wcdNx-codec.N.auto: ASoC: mux RX INTN MIXN INP has no path / 5x [drm:msm_dp_link_process_request [msm]] *ERROR* DP parse sink count fa / 4x wcdNx-codec wcdNx-codec.N.auto: ASoC: mux CDC_IF TXN MUX has no paths |
| diag.taint | F02 | needs investigation | tainted=4096 (out-of-tree) |
| diag.cmdline | F02 | needs investigation | 31 diagnostic parameters: clk_ignore_unused earlycon spx_boot spx_attempt spx_baseline oops ... |

## Remaining acceptance (exact frozen checklist requirements)

Full requirements below remain unmet or unverified, even where interfaces were observed.
Use TODO.md for current findings and blocker order; this tool does not choose work.
Battery testing remains deferred. Physical/lifecycle requirements need real evidence.

### B01
Repeatable startup/shutdown. At least five cold boots and ten warm reboots on the final candidate, on battery and external power, with clean boot, power-off/restart and no manual repair, unexplained reset or regression.
Inventory probes: none; not automatically checked

### B04
Firmware services. ADSP/CDSP/modem and their required services remain stable during combined use and resume. Review the diagnostic QRTR rollback and pinned/debug paths; document or remove remaining workarounds.
Inventory probes: fw.remoteproc, fw.services

### B05
RTC/time. Verify clock retention across power-off and timekeeping across suspend without relying on network time to conceal a broken RTC.
Inventory probes: none; not automatically checked

### B06
Security hardware/firmware inventory. Establish the actual TPM/ firmware security interfaces and Secure Boot support available on this unit; validate applicable functions with a documented boot/signing path. Lack of a Linux node is not proof that the hardware is absent.
Inventory probes: tpm.present, tpm.secureboot

### B07
Additional accelerators. Inventory fitted DSP/NPU/other compute capabilities and available interfaces; validate a real supported workload or document the specific missing support. A thermal-zone name is not a working NPU.
Inventory probes: accel.cdsp

### D01
Internal panel. Native resolution/refresh, correct image and orientation, no flicker/corruption; visually verify brightness over its usable range, blank/unblank and display return after idle/suspend.
Inventory probes: disp.panel, disp.backlight

### D03
Video acceleration. Inventory the device's supported encode/decode blocks and formats; exercise supported hardware paths with real media, checking output, acceleration and sustained playback. Software playback is not HW decode.
Inventory probes: video.codec

### I01
Reliable touch startup. Eliminate unexplained startup timeouts and invalid headers, or explicitly resolve their cause and acceptable recovery; repeat B01 with no missing touch or manual restarts.
Inventory probes: in.touch

### I02
Touchscreen. Real taps, drags, edge coverage and multi-touch gestures produce correct desktop actions, without stuck/missing contacts; repeat after display blanking and suspend. Do not mistake synthetic events for physical input.
Inventory probes: in.touch

### I03
Pen. Verify position, pressure, tilt where supported, hover, buttons/eraser and palm rejection with the actual compatible pen, including post-resume behavior. Map advertised capabilities to those actually fitted.
Inventory probes: in.pen

### I04
Keyboard. Typing, modifiers, Fn/media keys, indicators and backlight where fitted; detach/reattach and resume recover without stuck keys.
Inventory probes: in.keyboard, in.kbd_backlight

### I05
Touchpad. Pointer, click, scrolling, multi-finger gestures and palm rejection work across detach/reattach and resume.
Inventory probes: in.touchpad

### I06
Buttons and posture switches. Power/volume buttons, cover/lid/tablet state and appropriate desktop policy respond to real changes without duplicate events or lost wakeups. Establish which switches actually exist.
Inventory probes: in.buttons, in.switches

### I07
Pen accessory features. If this keyboard/pen supports charging, accessory battery reporting or wireless buttons, verify those with the accessory; otherwise record the identified accessory model and applicability.
Inventory probes: none; not automatically checked

### A01
Both physical speakers. Correct independent left/right acoustic output, channel mapping, balance, useful volume range and mute; no static, clipping, excessive pops or persistent bus errors. Use bounded appropriate signals and measured/listened output, respecting recorded sound preferences.
Inventory probes: aud.card, aud.amps

### A02
Internal microphones. Real known stimulus/voice recorded on each fitted microphone, correct routing/channel assignment and usable gain/noise; repeated capture/open/close without leaks or hangs. Noise-floor samples alone do not establish full microphone quality. Do not retain incidental private audio.
Inventory probes: aud.card

### A03
Audio lifecycle/userspace. Normal PipeWire/ALSA/UCM playback and capture, simultaneous use, volume/mute controls and repeated open/close work after reboot/resume without manual mixer setup or ad-hoc repair. Resolve or explicitly validate the parked-session workaround and its resource lifetime.
Inventory probes: aud.desktop, aud.feeder

### A04
External audio. Test applicable USB-C audio/dock and Bluetooth output/input devices, routing, hotplug and reconnect. The logical codec "Headset Jack" node does not establish a physical analog jack on this device.
Inventory probes: aud.external

### N01
Wi-Fi. Association/authentication on available supported bands, DNS and IPv4/IPv6 connectivity, sustained bidirectional transfer and reconnect after signal loss, radio toggle and suspend. Resolve overlapping supplicant ownership; verify relevant networking configuration, including the recorded IPv6 netfilter gap, without changing firewall policy merely to get a pass.
Inventory probes: net.wifi

### N02
Bluetooth. Real pairing, reconnect and peripheral use (HID and audio as available), radio toggle and resume; Wi-Fi coexistence under load. Preserve the active remote connection while planning radio tests.
Inventory probes: net.bt

### N03
Cellular control/data. Stable modem startup and discovery, correct SIM/eSIM applicability, network registration and actual bidirectional data with service; disconnect/reconnect, radio control and resume. Resolve mode and IPA/RMNET/WWAN integration before declaring connectivity. An unavailable SIM or subscription remains a test dependency, not a pass or a driver-failure verdict.
Inventory probes: net.wwan

### N04
GNSS/location. Establish fitted capability and its modem/interface path; if applicable obtain a real fix with plausible time/location and reacquire. A missing `/sys/class/gnss` entry does not alone decide support.
Inventory probes: none; not automatically checked

### U01
USB data on each physical port. Test both USB-C ports and plug orientations with actual USB2/USB3 devices, checksum-verified transfers and repeated hotplug/resume; verify negotiated speeds and no controller/IOMMU faults.
Inventory probes: usb.controllers, usb.superspeed

### U02
USB-C roles and power delivery. Correct orientation/role detection, charger negotiation and attach/detach on applicable ports with known adapters; no brownouts or stuck roles. Controller enumeration is insufficient.
Inventory probes: usb.typec

### U03
External DisplayPort. Actual monitor output through each supported port/dock path, intended mode, hotplug, extend/mirror and suspend recovery. Resolve Type-C/alt-mode/HPD integration. Never live-unbind/rebind MSM components.
Inventory probes: usb.dp

### U04
Dock and Surface Connect. Inventory actual Surface Connect/dock capabilities; validate supported charging, USB, Ethernet, display and audio concurrently with the relevant accessories. Identify USB vs Thunderbolt mode correctly; a dock's product name does not prove Thunderbolt support.
Inventory probes: none; not automatically checked

### C01
Proper camera integration. Resolve real regulator ownership/power sequencing and resource/binding issues; build and validate the actual enabled candidate. Do not deploy placeholder supplies or guessed RPMh rail votes.
Inventory probes: none; not automatically checked

### C02
Front camera. Capture real scenes with correct colors/orientation, exposure and usable frame rate/resolution; repeated stream start/stop and resume.
Inventory probes: none; not automatically checked

### C03
Rear camera. Real frames, supported focus/exposure and resolutions, correct orientation/colors; repeated stream start/stop and resume.
Inventory probes: none; not automatically checked

### C04
IR camera. Real IR frames and any fitted illumination/safety/control path, repeated use and resume. Keep camera operation separate from any optional face-authentication integration; a raw frame is not biometric validation.
Inventory probes: none; not automatically checked

### C05
Normal camera applications. Processed streams in normal userspace, camera selection, concurrent-use/resource behavior and privacy/activity controls where fitted. Validate actual scene output, not only sensor test patterns.
Inventory probes: cam.privacy_led

### S01
Light/proximity. Correct the confirmed TCS3430 ALS binding and verify readings under cover/uncover stimulus and intended desktop brightness behavior. TCS3430 has XYZ/IR light channels, not APDS proximity; do not treat the former driver's proximity zero as evidence of a fitted proximity sensor.
Inventory probes: sens.als.desktop

### S02
Motion/orientation. Inventory actual accelerometer/gyro/magnetometer or sensor-hub interfaces; validate axes, orientation changes and auto-rotation, including resume. PMIC ADCs are not evidence of motion-sensor support.
Inventory probes: sens.motion

### P01
Battery and charging. Plausible voltage/current/capacity/status, observed discharge and charging, AC transitions, charge limits where supported and low-battery behavior. Test applicable USB-C and Surface Connect chargers; distinguish policy/threshold behavior from a driver fault.
Inventory probes: none; not automatically checked

### P02
Idle/runtime power. Measure idle and active consumption, CPU/GPU frequency scaling, runtime-PM behavior and battery endurance against a recorded reference under comparable conditions. Remove/justify diagnostic power pins, clock overrides and performance-governor defaults before daily-use acceptance.
Inventory probes: gpu.devfreq, pwr.idle

### P03
Suspend/resume and wake. At least ten controlled s2idle cycles, including a30-minute sleep on battery, with measured drain and intended wake sources. Display, input, network, audio, cameras and attached devices recover; no kernel hang/reset or repeated manual intervention.
Inventory probes: pwr.suspend

### P04
Hibernate applicability. Establish whether the intended platform/ storage/security setup supports hibernation; if supported, verify image restore and the same functional regression checks. An exposed `disk` state is not proof.
Inventory probes: pwr.hibernate

### P05
Thermal management. Sensor plausibility, CPU/GPU cooling response and sustained combined workloads without overheating, hangs or firmware faults. Do not disable thermal protections or assume this device has a fan.
Inventory probes: none; not automatically checked

### R01
Useful persistent diagnostics. Diagnose missing ramoops data and retain identity-bound late shutdown/early failure evidence. Keep software callback completion distinct from physical power-off.
Inventory probes: diag.pstore

### R02
Recovery characterization. Validate the actual reset/recovery coverage, including the EFI handoff, or explicitly document its remaining limits. Existing reboot authorization permits experiments while this is open; it is not evidence that a watchdog or userspace fallback covers early hangs.
Inventory probes: diag.watchdog

### F01
Complete inventory. Reconcile fitted model/accessories against firmware/DT and device evidence; assign every remaining hardware capability to an ID, including any optional feature listed above. No silent omissions.
Inventory probes: plat.model

### F02
One final candidate. Build/install a reproducible kernel, config, DTB, modules, firmware and required userspace stack; all applicable feature tests pass on that same configuration without live repair or diagnostic-only force paths. Record upstream vs local patches and remaining workarounds.
Inventory probes: diag.taint, diag.cmdline

### F03
Combined regression. At least24hours of mixed realistic operation, battery/AC transitions and idle, plus B01/P03 cycles. Audit journal/error counters, peripheral reconnect, audio/camera coexistence and storage integrity. These finite tests give evidence, not a guarantee against every future failure.
Inventory probes: diag.kernel_errors, diag.units

### F04
Completion review. Every applicable open box resolved with evidence, every non-applicable item justified, all known issues explicitly reconciled, and user-visible physical tests recorded. Do not declare "all hardware works" while substantive tests are blocked, untested or failing.
Inventory probes: none; not automatically checked

## All interface observations

| Probe | State | Detail |
|---|---|---|
| plat.model | observed | Microsoft Surface Pro X (SQ2), kernel 7.3.0-rc2-spx-mainline-20261004bg+ |
| cpu.cores | observed | online=0-7 usable=8 |
| cpu.freq | observed | policy0 schedutil max 1766400/1766400 kHz; policy4 schedutil max 3148800/3148800 kHz |
| mem.total | observed | 15.01 GiB |
| storage.nvme | observed | nvme0n1 HFM256GDGTNG-87A0A 256 GB |
| storage.space | observed | 31804 MiB free on / |
| fw.remoteproc | observed | adsp=running cdsp=running modem=running slpi=running |
| fw.services | observed | pd-mapper=active rmtfs=active tqftpserv=active |
| tpm.present | observed | TPM 2, PCR0 4841698A6FEE2639 |
| tpm.secureboot | observed | SecureBoot=0 |
| accel.cdsp | gap suspected | no /dev/fastrpc-cdsp*; present: fastrpc-sdsp-secure; NPU has no Linux driver |
| disp.panel | needs investigation | connected mode=2880x1920 enabled=disabled dpms=Off (panel not scanning out now; lid/cover or display settings) |
| disp.backlight | observed | backlight 1256/4095 |
| gpu.devfreq | observed | 2c00000.gpu userspace, cur 461000000 Hz |
| video.codec | gap suspected | no codec video nodes; modules loaded: venus_core |
| in.touch | observed | input=True iptsd=active |
| in.pen | observed | spi 045E:0C21 Stylus, IPTSD Virtual Stylus 045E:0C21 |
| in.keyboard | observed | Microsoft Surface 045E:09AE Keyboard, Microsoft Surface 045E:09B0 Keyboard |
| in.kbd_backlight | needs investigation | no kbd_backlight LED class device |
| in.touchpad | observed | Microsoft Surface 045E:09AF Touchpad |
| in.buttons | observed | power=['pm8941_pwrkey'] volume=['Volume Buttons'] |
| in.switches | needs investigation | tablet(Microsoft Surface KIP Tablet Mode Switch); no lid/cover-closed switch |
| aud.card | observed | card 0: 3 playback, 3 capture PCMs |
| aud.amps | observed | 2 bound, attached |
| aud.desktop | gap suspected | internal sink=True source=False |
| aud.feeder | observed | spx-desktop-playback active (out-of-tree feeder workaround, see A03) |
| aud.external | needs investigation | USB audio card present (1 [USB            ]: USB-Audio - ThinkPad Thunderb); routing/hotplug need a listener |
| net.wifi | observed | ath10k_snoc, 5180.0 MHz, rx 650.0 MBit/s VHT-MCS 7 80MHz short GI VHT-NSS 2 |
| net.bt | observed | [address omitted] powered=True |
| net.wwan | gap suspected | netdev=none wwan ports=0 ipa module=False ModemManager=inactive |
| usb.controllers | observed | 3 xHCI controllers (xhci-hcd.1.auto xhci-hcd.2.auto xhci-hcd.3.auto) |
| usb.superspeed | needs investigation | 4 SuperSpeed device(s), e.g. 4-1.4.4 USB3.1 Hub@10000; per-port/orientation coverage needs a person |
| usb.typec | gap suspected | typec ports=0 (expected 2), DT connectors=1, role switches=0 |
| usb.dp | needs investigation | DP-1=connected; only one DP connector for two USB-C ports |
| cam.privacy_led | observed | spx:front:privacy, spx:rear:privacy |
| sens.als.desktop | gap suspected | iio-sensor-proxy not running (inactive) |
| sens.motion | gap suspected | IIO accel=False gyro=False magn=False; sensor proxy accelerometer=n/a; spx-sensors=inactive (sensors sit behind SLPI, opt-in service not running) |
| pwr.suspend | needs investigation | state=[freeze mem disk] mem_sleep=[s2idle] suspend.target=masked this boot ok=0 fail=0 |
| pwr.hibernate | gap suspected | disk state=True swap=False resume= on cmdline=False |
| pwr.idle | needs investigation | 2 cpuidle states; overrides on cmdline: clk_ignore_unused |
| diag.pstore | observed | backend=ramoops mounted=True |
| diag.watchdog | observed | watchdog0 ? timeout=? |
| diag.kernel_errors | needs investigation | 40 error-level lines; top: 6x wcdNx-codec wcdNx-codec.N.auto: ASoC: mux RX INTN MIXN INP has no path / 5x [drm:msm_dp_link_process_request [msm]] *ERROR* DP parse sink count fa / 4x wcdNx-codec wcdNx-codec.N.auto: ASoC: mux CDC_IF TXN MUX has no paths |
| diag.taint | needs investigation | tainted=4096 (out-of-tree) |
| diag.units | observed | none failed |
| diag.cmdline | needs investigation | 31 diagnostic parameters: clk_ignore_unused earlycon spx_boot spx_attempt spx_baseline oops ... |
