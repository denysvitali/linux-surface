# Automatic hardware checklist

Date: 2026-10-13T16:31:53+02:00
Boot: `93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d`
Kernel: `7.3.0-rc2-spx-mainline-20261004bg+`
Mode: run; fixture: false

Report JSON: [JSON](/var/lib/spx-boot-diagnostics/boots/93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d/hw-validation/report.json)

Functional checks passed: **10 of 40**. Inventory observations: 34 of 52. Blocked: 46. Failed: 2. Errors: 0.

Implemented checks are validator coverage, not proof that hardware drivers are implemented. Only a functional pass from this boot completes a check. Inventory is never a functional pass.

All catalog rows remain visible, including unsupported or blocked checks. This automatic list has no human conditions and does not certify the historical full acceptance checklist. Each run replaces the active list with that boot's outcomes.

## Platform

- **cpu.cores — CPU online/present inventory** (inventory; observed): online=8; present=8; enumeration only; no CPU load or frequency-transition test
- **cpu.memory — Memory capacity inventory** (inventory; observed): total=15373 MiB; available=12583 MiB; no memory load test
- **cpu.cpufreq — CPU frequency policy inventory** (inventory; observed): policy0 driver=qcom-cpufreq-hw governor=schedutil min/current/max=300000/883200/1766400 kHz; policy4 driver=qcom-cpufreq-hw governor=schedutil min/current/max=825600/1881600/3148800 kHz; no transitions or idle recovery exercised
- [x] **cpu.workload — AC-only bounded CPU/memory consistency** (functional; pass): External power online; 8 concurrent workers, 1 MiB private buffer each, 512 total consistency rounds; &lt;=64 rounds/worker and one-second work deadline; no affinity/clock changes; not frequency, thermal, sustained or all-core placement validation
- [ ] **cpu.frequency-transitions — Loaded frequency transitions and idle recovery** (functional; blocked): Frequency-transition/idle-recovery workload is deferred; policy metadata alone cannot validate transitions
- [x] **rtc.read-time — RTC accessible time agrees with system clock** (functional; pass): Surface rtc0 time read; wall-clock difference=1 s (limit 5 s); 1 other RTC(s) not compared; no power-off/suspend retention or independence from network time established

## Storage

- **storage.nvme — NVMe controller inventory** (inventory; observed): nvme0 model=HFM256GDGTNG-87A0A; controller enumeration only
- [x] **storage.fsync-checksum — Disposable filesystem write/fsync/checksum (4 MiB)** (functional; pass): 4 MiB disposable file written, fsynced, reopened and SHA-256 matched; file removed; filesystem type=0xef53; filesystem test only; not sustained/post-resume or raw NVMe validation

## Firmware

- **fw.remoteproc — Remote processor states (no startup)** (inventory; observed): modem=running; cdsp=running; adsp=running; slpi=running; no remote processor started; offline CDSP is not a malfunction; combined-use/resume stability is untested
- **fw.services — Firmware service states** (inventory; observed): pd-mapper.service load=loaded active=active sub=running enabled=enabled; rmtfs.service load=loaded active=active sub=running enabled=enabled; tqftpserv.service load=loaded active=active sub=running enabled=enabled; status only; missing/inactive/masked required service blocks operation
- [ ] **fw.stability — Combined-use/resume firmware stability** (functional; blocked): Combined firmware-use/resume fixture is not supplied; this safe boot suite does not start parked DSPs or suspend the device
- **accel.cdsp-fastrpc — CDSP/FastRPC interface inventory (no startup)** (inventory; blocked): 1 FastRPC interface(s), no CDSP interface exposed; known CDSP support/startup is parked, not evidence of absent compute hardware
- [ ] **accel.cdsp-workload — Supported CDSP workload** (functional; blocked): CDSP startup/workload remains parked; no supported workload fixture or authorization to start the disabled path

## Security

- **security.tpm — TPM interface inventory** (inventory; observed): tpm0 version=2; metadata only; no keys changed
- [ ] **security.tpm-capability — Read-only TPM2 fixed-capability response** (functional; blocked): Read-only tpm2_getcap unavailable: tool, device permission or TPM transport required
- [ ] **security.tpm-signing — TPM signing workflow** (functional; blocked): No authorized signing fixture supplied; this boot suite makes no TPM key creation, provisioning or key changes
- **security.secureboot — EFI Secure Boot state inventory** (inventory; observed): EFI SecureBoot=disabled; state only, not verification of a trusted boot/signing path; no firmware settings changed

## Thermal

- **thermal.metadata — Thermal temperatures, trips and cooling states (no load)** (inventory; observed): aoss0-thermal=34100 mC, cpu0-thermal=35200 mC, cpu7-top-thermal=34900 mC, cpu4-bottom-thermal=34900 mC, cpu5-bottom-thermal=34900 mC, cpu6-bottom-thermal=35200 mC, cpu7-bottom-thermal=35200 mC, gpu-top-thermal=33700 mC, aoss1-thermal=35100 mC, wlan-thermal=34300 mC, video-thermal=34700 mC, mem-thermal=34300 mC, cpu1-thermal=35600 mC, q6-hvx-thermal=34300 mC, camera-thermal=34300 mC, compute-thermal=34700 mC, mdm-dsp-thermal=34700 mC, npu-thermal=33600 mC, pmc8180a-thermal=33759 mC, pmc8180c-thermal=34765 mC, pmc8180e-thermal=33305 mC, cpu2-thermal=34500 mC, cpu3-thermal=35600 mC, cluster0-thermal=34500 mC, cluster1-thermal=35600 mC, cpu4-top-thermal=35200 mC, cpu5-top-thermal=34900 mC, cpu6-top-thermal=35600 mC; 38 trip(s), 4 cooling device(s); instantaneous metadata only; no load or policy changes; thermal names do not establish compute capability
- [ ] **thermal.response — Automatic thermal response under load** (functional; blocked): Thermal-response workload is parked; this suite does not heat the device or change thermal policy

## Power

- **pwr.supplies — Battery and external-power metadata (no discharge/load)** (inventory; observed): Mains online=1; Battery status=Not charging capacity=48%; metadata only; battery/discharge/endurance/charger transitions deferred; no load
- **pwr.support — Sleep interfaces and masked service states (no suspend)** (inventory; observed): state=freeze mem disk; mem_sleep=\[s2idle\]; disk=\[shutdown\] reboot suspend test_resume; sleep.target load=masked enabled=masked; suspend.target load=masked enabled=masked; hibernate.target load=masked enabled=masked; hybrid-sleep.target load=masked enabled=masked; suspend-then-hibernate.target load=masked enabled=masked; masks respected; exposed sleep states do not validate suspend/hibernate; no state changed
- [ ] **pwr.suspend-recovery — Device suspend/resume recovery** (functional; blocked): Suspend/resume is excluded from the safe boot suite; no sleep masks or driver states are changed
- [ ] **pwr.hibernate-recovery — Device hibernate/resume recovery** (functional; blocked): Hibernation/reboot recovery is excluded from the safe boot suite; no sleep masks or boot state are changed

## Diagnostics

- **diag.watchdog — Watchdog interface inventory (no device open)** (inventory; blocked): Watchdog identity metadata is not readable; no watchdog device opened
- [ ] **diag.watchdog-recovery — Watchdog reset/recovery** (functional; blocked): No reset/recovery fixture or authorization in this boot suite; watchdog devices are never opened or armed
- **diag.boot — Boot identity and retained fault-record inventory** (inventory; observed): Current boot identity available; kernel=7.3.0-rc2-spx-mainline-20261004bg+; 0 retained pstore record(s); prior-boot records are not a current-boot fault verdict; no startup/shutdown repeatability test
- [x] **diag.kernel-faults — Current boot warning-priority kernel fault scan** (functional; pass): Accessible current-boot warning-priority kernel journal scanned; no recognized BUG/oops/panic, warning, storage, IOMMU, firmware, critical thermal or lockup signatures; lower-priority messages not scanned; not a load/lifecycle test
- **diag.taint — Kernel taint inventory** (inventory; observed): kernel taint bitmask=4096 (0x1000); taint is context, not a functional pass/fault verdict
- [ ] **diag.failed-units — Current systemd failed-unit scan** (functional; fail): 2 failed system unit(s), excluding 0 prior validator unit(s); private unit names/logs omitted; not user-service or repeat-startup validation

## Network

- **net.wifi.interfaces — Wi-Fi interfaces and current carrier** (inventory; observed): wireless interfaces=1; up=1; carrier=1; unreadable state=0; enumeration is not working data
- **net.wifi.link — Current Wi-Fi association evidence** (inventory; observed): primary wireless interface associated; association alone does not verify DNS or data
- [x] **net.wifi.scan — Bounded Wi-Fi scan completes** (functional; pass): NetworkManager completed a scan (LastScan advanced); available AP entries=1; current connection was not changed
- **net.ip.families — Wi-Fi address and default-route families** (inventory; observed): primary Wi-Fi addresses: IPv4 global=1, IPv6 global=0, IPv6 link-local=1, tentative/DAD-failed=0; default routes: IPv4=1, IPv6=0; configured families are not working WAN data
- **net.dns.config — Configured DNS resolver families** (inventory; observed): configured resolver entries: IPv4=1, IPv6=0, loopback stubs=1; working DNS is untested without an approved lookup fixture; no external query was sent
- [ ] **net.dns.lookup — Bounded DNS lookup of a deliberate public fixture** (functional; blocked): a deliberate public DNS lookup fixture is not configured; resolver settings do not prove working DNS
- [x] **net.wifi.gateway4 — Local IPv4 gateway replies over Wi-Fi** (functional; pass): local IPv4 gateway echo replies=3/3 over primary Wi-Fi; 8-byte payloads; not WAN, DNS or sustained transfer acceptance
- [ ] **net.wifi.gateway6 — Local IPv6 gateway replies over Wi-Fi** (functional; blocked): no configured private/link-local IPv6 gateway fixture; no external destination was contacted

## Bluetooth

- **bluetooth.inventory — Bluetooth paired, connected and service capability counts** (inventory; observed): adapters=1; powered=1; discovering=0; cached peers=1; paired=1; connected=0; cached HID-capable=1; cached audio-capable=0; cached service metadata only; pairing, reconnect and peripheral use are not tested
- [x] **bluetooth.discovery — Bounded Bluetooth discovery starts and releases its own session** (functional; pass): Bounded 5-second discovery started; owned scanner exited and discovery is inactive; fresh reports=12 from peers=12; prior connections retained; no power, pairing or disconnect changes

## Graphics

- **graphics.display.internal — Internal connector modes and preferred timing** (inventory; observed): card1-eDP-1 connected, disabled, modes=2880x1920, EDID preferred=2880x1920@60.00Hz; advertised timing only, not active scanout, image quality, hotplug or resume
- **graphics.display.external — Connected external display modes and preferred timing** (inventory; blocked): No connected external display fixture exposed (2 connectors, 2 disconnected/unknown); this does not establish hardware absence
- [ ] **graphics.display.internal.scanout — Current internal native scanout and advancing vblank** (functional; blocked): Connected internal display is not currently enabled; no power/mode changes requested
- [ ] **graphics.display.external.scanout — Current external scanout and advancing vblank** (functional; blocked): No connected external display fixture currently exposed; no hotplug/power/mode action requested
- **graphics.backlight — Backlight metadata without changing brightness** (inventory; observed): backlight type=raw requested=1256 actual=1256 maximum=4095; no writes or brightness-range/visual claim
- **graphics.egl — Surfaceless EGL hardware GL/GLES contexts** (inventory; observed): Surfaceless EGL exposes Adreno 680 contexts: OpenGL core profile, OpenGL compatibility profile; context creation is not draw/readback or desktop acceleration evidence
- **graphics.vulkan.devices — Vulkan hardware device and API inventory** (inventory; blocked): Vulkan device inventory requires an installed tool/fixture
- [ ] **graphics.gl.render — Offscreen GL expected-image smoke** (functional; blocked): OpenGL offscreen expected-image test requires an installed tool/fixture
- [ ] **graphics.gles.render — Offscreen GLES expected-image smoke** (functional; blocked): OpenGL ES offscreen expected-image test requires an installed tool/fixture
- [x] **graphics.vulkan.render — Windowless Vulkan static render and pixel readback** (functional; pass): Adreno 680 Vulkan rendered a public 64x64 color fixture windowlessly and matched pixel readback; output discarded. Static path only: recorded GMEM scrolling/partial-damage corruption remains unresolved
- [ ] **graphics.vulkan.dynamic-damage — Vulkan scrolling and partial-damage corruption regression** (functional; blocked): Recorded Vulkan GMEM scrolling corruption is unresolved; TU_DEBUG=sysmem is a workaround, not a fix. No safe windowless reproducer for that workload is available; a static render does not cover it

## Video

- **media.decode.formats — Exposed Venus decoder formats** (inventory; observed): 1 exposed Venus decoder node(s); advertised compressed-input formats: H264, HEVC, MPG2, VP80, VP90; enumeration does not prove any codec workload; encoder is parked
- [x] **media.decode.fixture — Hardware decode of supplied real media** (functional; pass): Supplied 1920x1080 fixture: h264_v4l2m2m on Venus; decoded=32 output=30, zero decode errors, complete progress; capped at 2s/30 frames, output discarded. Only this fixture codec/path tested; not encoder, all formats, pixels or sustained playback
- [ ] **media.encode — Hardware encoder workload** (functional; blocked): Encoder trials parked: known CVP fault/reset/hang and unresolved protected-buffer/recovery contract; no encoder open, autoload or workload attempted

## Cameras

- **camera.graph — CAMSS media graph integration** (inventory; blocked): CAMSS graphs=1, enabled links=72, fitted sensor entities=rear,ir; missing registered sensor graph support for front; no overlays, modules or link changes attempted
- **camera.libcamera — Libcamera fitted-sensor metadata** (inventory; blocked): verified private libcamera/CPU ISP (not distro integration); rear model=ov13858 pixel_array=4224x3136 location=1 rotation=180 controls=3; ir model=ov7251 pixel_array=648x488 rotation=0 controls=3; front not exposed by libcamera; needs running sensor graph/userspace support, not evidence of hardware absence
- [ ] **camera.front.frames — Front processed frame delivery** (functional; blocked): front camera capture requires explicit --capture opt-in; three processed frames would be discarded in memory, no IR emitter or retained images
- [ ] **camera.rear.frames — Rear processed frame delivery** (functional; blocked): rear camera capture requires explicit --capture opt-in; three processed frames would be discarded in memory, no IR emitter or retained images
- [ ] **camera.ir.frames — Ir processed frame delivery** (functional; blocked): ir camera capture requires explicit --capture opt-in; three processed frames would be discarded in memory, no IR emitter or retained images

## Audio

- **audio.alsa — ALSA cards and PCM interfaces** (inventory; observed): ALSA cards=1, identified SPX cards=1, playback interfaces=3, capture interfaces=3; nodes do not establish acoustic output or microphone quality.
- **audio.controls — Native audio routing control capabilities** (inventory; observed): Native ALSA controls=1378, stereo PA control names=true, MM2 internal microphone route control names=true; capability only, no values read/written or stream started.
- **audio.soundwire — SoundWire core enumeration** (inventory; observed): SoundWire core nodes=2, attached=0, unattached=2, other states=0; parked amps may be unattached. Core enumeration is not verified physical output; no bridge/register reads.
- **audio.services — Desktop audio service availability** (inventory; blocked): pipewire.service=inactive; pipewire-pulse.service=inactive; wireplumber.service=inactive; active desktop services, systemctl and access to the selected desktop session bus required; no service started or restarted
- **audio.graph — Desktop audio graph and default routing** (inventory; blocked): Cannot query desktop sinks; pactl JSON support, the Pulse-compatible audio service and selected desktop session permission required.
- **audio.feeder — Native desktop feeder readiness** (inventory; blocked): Native desktop feeder=failed; installed/running feeder service and system service-query access required. No start or restart attempted.
- [ ] **audio.speakers — Physical speaker output** (functional; blocked): Speaker playback is not authorized for this suite; --capture is not playback permission. No PCM, amplifier power or gain change started.
- [ ] **audio.acoustic — Speaker acoustic feedback** (functional; blocked): The existing quiet audio.py reopen loop already verified the resolved WX fix. Its authorization is scoped to that fix, not routine acoustic retesting; no tone or microphone recording started.
- [ ] **audio.microphones — Internal microphone stimulus capture** (functional; blocked): Microphone capture is opt-in (--capture) and disabled. New audio/microphone variations remain parked; no private recording or PCM started.
- [ ] **audio.lifecycle — Native audio stream lifecycle** (functional; blocked): Parked DSP mappings must be preserved; full UNMAP/AFE STOP and arbitrary teardown remain unsafe/unvalidated. No PCM open/close, graph mutation, service restart or module change performed.
- [ ] **audio.external — External USB and Bluetooth audio data paths** (functional; blocked): External audio fixtures cannot be identified through the desktop graph; pactl JSON support, audio service and user-session access required.

## Cellular

- **cell.prerequisites — Cellular IPA/WWAN data-path prerequisites** (inventory; blocked): QCOM_IPA=disabled; WWAN=disabled; RMNET=disabled; WWAN control nodes=0, cellular-style net paths=0; repository lacks SC8180X IPA match/device resources (source finding, not deployed config); missing kernel/data-path integration or exposed path; SIM/service and genuine same-device modem provisioning are separate prerequisites, not hardware absence
- **cell.control — ModemManager and QRTR control metadata** (inventory; blocked): QRTR table available=true, advertised services=67; discovered modems=0; ModemManager service not installed
- [ ] **cell.data — HTTPS HEAD reachability on an existing cellular bearer** (functional; blocked): ModemManager service not installed; no connection or radio/provisioning change attempted

## GNSS

- **gnss.path — GNSS class and modem location capability** (inventory; observed): GNSS class paths=0; QRTR table available=true, LOC service16 entries=1; modems advertising GNSS=0; no position/session query; capability alone is not a fix; prior factory-test/DeviceNotReady and genuine provisioning must be resolved rather than repeating reception trials
- [ ] **gnss.fix — Real GNSS fix and reacquisition** (functional; blocked): ModemManager service not installed; real fix/reacquisition requires a separately authorized positioning session and suitable reception; automatic scans do not start GNSS or collect position; previous online-mode/provisioning gap is not cured by LOC enumeration

## USB

- **usb.controllers — USB controller root hubs and advertised speeds** (inventory; observed): USB root hubs=6, advertised rates(Mbit/s)=10000,10000,10000,480,480,480; root hubs are not a physical-port count or data-transfer proof
- **usb.attached — Attached USB device negotiated speeds** (inventory; blocked): No readable attached non-root USB device fixture; both ports/orientations and checksum transfer remain untested, not hardware absent
- [ ] **usb.transfer — Checksum-verified disposable USB storage transfer** (functional; blocked): No explicit mounted USB storage fixture was supplied; automatic disposable checksum engine is not connected to a verified USB-backed directory. Ordinary root-storage I/O or device/speed enumeration cannot prove USB data transfer; no block device opened

## USB-C

- **usb.roles — Read-only Type-C attachment and role metadata** (inventory; blocked): Type-C class ports=0, partner paths=0, USB role interfaces=0; ; role/orientation reporting interface missing; the SPX port-zero HPD bridge is not full two-port Type-C/PD integration
- **usb.pd — Reported USB-C power-delivery metadata** (inventory; blocked): Type-C ports reporting PD mode=0; USB power interfaces=0, online=0, reporting PD type=0; no supported PD contract/charger reporting path; firmware PD/second-port contract unresolved, not absence of charging hardware

## Dock and Surface Connect

- **dock.paths — Dock and Surface Connect attached path attribution** (inventory; blocked): Current paths: non-root USB=0, non-wireless Ethernet-style=0, connected external DRM=0, Thunderbolt bus entries=0, Surface Aggregator clients=11; supported Surface Connect attachment/capability attribution unavailable. These counts do not identify connector/dock, Thunderbolt mode, audio/charging or concurrent operation; accessory topology fixture/firmware contract needed

## Input

- **input.startup — IPTSD service and virtual-device startup health** (inventory; observed): IPTSD active=1, failed=0, restarts=0; virtual touch=true, virtual pen=true; readiness metadata only, not physical touch or repeat-boot reliability; restarts are reported, not concealed
- **input.accessory — Pen and keyboard accessory battery metadata** (inventory; blocked): No attributable pen/keyboard battery-reporting path; identified accessory model/applicability and supported charging/wireless-button interface needed; no hardware absence inferred
- **input.touch — Touchscreen direct multi-touch capabilities** (inventory; observed): Matching input capability interface exposed; Surface/IPTSD identified=true; advertised capabilities only; no input events, physical actions or lifecycle tested
- **input.pen — Pen position, pressure and tilt capabilities** (inventory; observed): Matching input capability interface exposed; Surface/IPTSD identified=true; pressure=true, tilt X=true, tilt Y=true, eraser=true, barrel buttons=true; advertised capabilities only; no input events, physical actions or lifecycle tested
- **input.keyboard — Keyboard key and indicator capabilities** (inventory; observed): Matching input capability interface exposed; Surface/IPTSD identified=true; CapsLock indicator=true; advertised capabilities only; no input events, physical actions or lifecycle tested
- **input.touchpad — Touchpad pointer multi-touch capabilities** (inventory; observed): Matching input capability interface exposed; Surface/IPTSD identified=true; advertised capabilities only; no input events, physical actions or lifecycle tested
- **input.buttons — Power/volume and posture switch capabilities** (inventory; observed): Matching input capability interface exposed; Surface/IPTSD identified=true; power=false, volume up/down=false/false, lid/tablet switches=false/true; advertised capabilities only; no input events, physical actions or lifecycle tested

## Sensors

- **sensors.channels — Light and motion channel capabilities** (inventory; observed): Allowlisted light channels=4, motion channels=0, TCS3430 interfaces=1; PMIC ADCs excluded; TCS3430 XYZ/IR is not proximity or a verified lux conversion; SDSP motion may be outside IIO; advertised capability only, not stimulus, axes or calibration
- **sensors.backend — SDSP sensor backend and startup services** (inventory; fail): SDSP FastRPC endpoints=1, CDSP endpoints=0; sensor provider=failed, proxy=inactive; running DT disables CDSP FastRPC: compute transport intentionally parked, not missing silicon and not the SDSP sensor path; service reports startup/backend failure; no automatic repair
- **sensors.desktop — Already-running SensorProxy cached properties** (inventory; blocked): SensorProxy is not already active/readable; no D-Bus auto-start or policy bypass
- [x] **sensors.light-read — One-shot light-channel numeric read** (functional; pass): One-shot finite light-channel reads=4, zero-valued=0; raw values discarded; zero is not a light/stimulus failure; no scale/lux, physical axes, calibration, rotation, proximity or lifecycle claim
- [ ] **sensors.motion-read — One-shot motion-channel numeric read** (functional; blocked): No permitted motion sample path: safe raw reads are restricted to known TCS3430 light channels; SDSP motion needs a supported fresh service-delivery sample, not arbitrary IIO or PMIC ADC substitutes; cached properties are not delivery
