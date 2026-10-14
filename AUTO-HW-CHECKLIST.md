# Automatic hardware checklist

Date: 2026-10-14T09:31:07+02:00
Boot: `95e14bba-f6b5-4400-8091-b43fe585069f`
Kernel: `7.3.0-rc2-spx-mainline-20261004bg+`
Mode: run; fixture: false

Report JSON: [JSON](/var/lib/spx-boot-diagnostics/boots/95e14bba-f6b5-4400-8091-b43fe585069f/hw-validation/report.json)

Functional checks passed: **28 of 49**. Inventory observations: 42 of 52. Blocked: 31. Failed: 0. Errors: 0.

Implemented checks are validator coverage, not proof that hardware drivers are implemented. Only a functional pass from this boot completes a check. Inventory is never a functional pass.

All catalog rows remain visible, including unsupported or blocked checks. This automatic list has no human conditions and does not certify the historical full acceptance checklist. Each run replaces the active list with that boot's outcomes.

## Platform

- **cpu.cores — CPU online/present inventory** (inventory; observed): online=8; present=8; enumeration only; no CPU load or frequency-transition test
- **cpu.memory — Memory capacity inventory** (inventory; observed): total=15373 MiB; available=13499 MiB; no memory load test
- **cpu.cpufreq — CPU frequency policy inventory** (inventory; observed): policy0 driver=qcom-cpufreq-hw governor=schedutil min/current/max=300000/1113600/1766400 kHz; policy4 driver=qcom-cpufreq-hw governor=schedutil min/current/max=825600/2361600/3148800 kHz; no transitions or idle recovery exercised
- [x] **cpu.workload — AC-only bounded CPU/memory consistency** (functional; pass): External power online; 8 concurrent workers, 1 MiB private buffer each, 512 total consistency rounds; &lt;=64 rounds/worker and one-second work deadline; no affinity/clock changes; not frequency, thermal, sustained or all-core placement validation
- [x] **cpu.frequency-transitions — Loaded frequency transitions and idle recovery** (functional; pass): policy0 min/idle/peak/after=300000/883200/1766400/300000 kHz; total_trans increased=true; policy4 min/idle/peak/after=825600/3148800/3148800/825600 kHz; total_trans increased=true; 1.5s pinned load per policy in parallel, 3s idle sampling; no sysfs writes, governor/limit changes, thermal or battery test
- [x] **rtc.read-time — RTC accessible time agrees with system clock** (functional; pass): Surface rtc0 time read; wall-clock difference=0 s (limit 5 s); 1 other RTC(s) not compared; no power-off/suspend retention or independence from network time established

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
- [x] **security.tpm-capability — Read-only TPM2 fixed-capability response** (functional; pass): TPM2 GetCapability returned fixed properties with family 2.0; no keys, PCRs or firmware settings changed
- [x] **security.tpm-signing — TPM signing workflow** (functional; pass): TPM ecc signed fixed SHA-256 digest and verified signature with the same context; only a transient unrestricted signing primary under NULL, public fixed SHA-256 digest and disposable private files; no persistent handles, NV writes, hierarchy/auth changes, PCR extends or owner/endorsement use; resource-manager transient flush succeeded; command connections closed, private files removed
- **security.secureboot — EFI Secure Boot state inventory** (inventory; observed): EFI SecureBoot=disabled; state only, not verification of a trusted boot/signing path; no firmware settings changed

## Thermal

- **thermal.metadata — Thermal temperatures, trips and cooling states (no load)** (inventory; observed): aoss0-thermal=38700 mC, cpu0-thermal=39500 mC, cpu7-top-thermal=39500 mC, cpu4-bottom-thermal=39900 mC, cpu5-bottom-thermal=39500 mC, cpu6-bottom-thermal=39900 mC, cpu7-bottom-thermal=39900 mC, gpu-top-thermal=37600 mC, aoss1-thermal=39300 mC, wlan-thermal=39000 mC, video-thermal=39300 mC, mem-thermal=39000 mC, cpu1-thermal=39900 mC, q6-hvx-thermal=39000 mC, camera-thermal=39000 mC, compute-thermal=39000 mC, mdm-dsp-thermal=39000 mC, npu-thermal=38200 mC, pmc8180a-thermal=39436 mC, pmc8180c-thermal=40020 mC, pmc8180e-thermal=38722 mC, cpu2-thermal=39100 mC, cpu3-thermal=39900 mC, cluster0-thermal=39100 mC, cluster1-thermal=40700 mC, cpu4-top-thermal=39500 mC, cpu5-top-thermal=39900 mC, cpu6-top-thermal=41100 mC; 38 trip(s), 4 cooling device(s); instantaneous metadata only; no load or policy changes; thermal names do not establish compute capability
- [ ] **thermal.response — Automatic thermal response under load** (functional; blocked): Thermal-response workload is parked; this suite does not heat the device or change thermal policy

## Power

- **pwr.supplies — Battery and external-power metadata (no discharge/load)** (inventory; observed): Mains online=1; Battery status=Not charging capacity=47%; metadata only; battery/discharge/endurance/charger transitions deferred; no load
- **pwr.support — Sleep interfaces and masked service states (no suspend)** (inventory; observed): state=freeze mem disk; mem_sleep=\[s2idle\]; disk=\[shutdown\] reboot suspend test_resume; sleep.target load=masked enabled=masked; suspend.target load=masked enabled=masked; hibernate.target load=masked enabled=masked; hybrid-sleep.target load=masked enabled=masked; suspend-then-hibernate.target load=masked enabled=masked; masks respected; exposed sleep states do not validate suspend/hibernate; no state changed
- [ ] **pwr.suspend-recovery — Device suspend/resume recovery** (functional; blocked): Suspend/resume is excluded from the safe boot suite; no sleep masks or driver states are changed
- [ ] **pwr.hibernate-recovery — Device hibernate/resume recovery** (functional; blocked): Hibernation/reboot recovery is excluded from the safe boot suite; no sleep masks or boot state are changed

## Diagnostics

- **diag.watchdog — Watchdog interface inventory (no device open)** (inventory; observed): watchdog0 driver=qcom_wdt parent=17c10000.watchdog compatible=qcom,apss-wdt-sc8180x,qcom,kpss-wdt; identity/state/timeout attributes unavailable because the kernel lacks watchdog sysfs attributes; capability inventory only; no device open, arm, reset or recovery test
- [ ] **diag.watchdog-recovery — Watchdog reset/recovery** (functional; blocked): No reset/recovery fixture or authorization in this boot suite; watchdog devices are never opened or armed
- **diag.boot — Boot identity and retained fault-record inventory** (inventory; observed): Current boot identity available; kernel=7.3.0-rc2-spx-mainline-20261004bg+; 0 retained pstore record(s); prior-boot records are not a current-boot fault verdict; no startup/shutdown repeatability test
- [x] **diag.kernel-faults — Current boot warning-priority kernel fault scan** (functional; pass): Accessible current-boot warning-priority kernel journal scanned; no recognized BUG/oops/panic, warning, storage, IOMMU, firmware, critical thermal or lockup signatures; lower-priority messages not scanned; not a load/lifecycle test
- **diag.taint — Kernel taint inventory** (inventory; observed): kernel taint bitmask=4096 (0x1000); taint is context, not a functional pass/fault verdict
- [x] **diag.failed-units — Current systemd failed-unit scan** (functional; pass): 0 failed system unit(s), excluding 0 prior validator unit(s); private unit names/logs omitted; not user-service or repeat-startup validation

## Network

- **net.wifi.interfaces — Wi-Fi interfaces and current carrier** (inventory; observed): wireless interfaces=1; up=1; carrier=1; unreadable state=0; enumeration is not working data
- **net.wifi.link — Current Wi-Fi association evidence** (inventory; observed): primary wireless interface associated; association alone does not verify DNS or data
- [x] **net.wifi.scan — Bounded Wi-Fi scan completes** (functional; pass): NetworkManager completed a scan (LastScan advanced); available AP entries=1; current connection was not changed
- **net.ip.families — Wi-Fi address and default-route families** (inventory; observed): primary Wi-Fi addresses: IPv4 global=1, IPv6 global=0, IPv6 link-local=1, tentative/DAD-failed=0; default routes: IPv4=1, IPv6=0; configured families are not working WAN data
- **net.dns.config — Configured DNS resolver families** (inventory; observed): configured resolver entries: IPv4=1, IPv6=0, loopback stubs=1; configuration inventory only; see net.dns.lookup for functional evidence; this inventory sends no query
- [x] **net.dns.lookup — Bounded DNS lookup of a deliberate public fixture** (functional; pass): DNS fixture=example.com; system resolver answers: A=2 AAAA=2; total deadline 3s; no network state changed
- [x] **net.wifi.gateway4 — Local IPv4 gateway replies over Wi-Fi** (functional; pass): local IPv4 gateway echo replies=3/3 over primary Wi-Fi; 8-byte payloads; not WAN, DNS or sustained transfer acceptance
- [ ] **net.wifi.gateway6 — Local IPv6 gateway replies over Wi-Fi** (functional; blocked): no configured private/link-local IPv6 gateway fixture; no external destination was contacted

## Bluetooth

- **bluetooth.inventory — Bluetooth paired, connected and service capability counts** (inventory; observed): adapters=1; powered=1; discovering=0; cached peers=1; paired=1; connected=0; cached HID-capable=1; cached audio-capable=0; cached service metadata only; pairing, reconnect and peripheral use are not tested
- [x] **bluetooth.discovery — Bounded Bluetooth discovery with fresh peer reception** (functional; pass): Bounded 5-second discovery started; owned scanner exited and discovery is inactive; fresh reports=13 from peers=13; prior connections retained; no power, pairing or disconnect changes

## Graphics

- **graphics.display.internal — Internal connector modes and preferred timing** (inventory; observed): card1-eDP-1 connected, enabled, modes=2880x1920, EDID preferred=2880x1920@60.00Hz; advertised timing only, not active scanout, image quality, hotplug or resume
- **graphics.display.external — Connected external display modes and preferred timing** (inventory; blocked): No connected external display fixture exposed (2 connectors, 2 disconnected/unknown); this does not establish hardware absence
- [x] **graphics.display.internal.scanout — Current internal native scanout and advancing vblank** (functional; pass): eDP-1 current=2880x1920@60Hz, active framebuffer, vblank advanced 1; current scanout only, not image quality, hotplug, blank/unblank or resume
- [ ] **graphics.display.external.scanout — Current external scanout and advancing vblank** (functional; blocked): No connected external display fixture currently exposed; no hotplug/power/mode action requested
- **graphics.backlight — Backlight metadata without changing brightness** (inventory; observed): backlight type=raw requested=1256 actual=1256 maximum=4095; no writes or brightness-range/visual claim
- **graphics.egl — Surfaceless EGL hardware GL/GLES contexts** (inventory; observed): Surfaceless EGL exposes Adreno 680 contexts: OpenGL core profile, OpenGL compatibility profile; context creation is not draw/readback or desktop acceleration evidence
- **graphics.vulkan.devices — Vulkan hardware device and API inventory** (inventory; observed): Adreno 680 Vulkan hardware devices=1, software devices=0, API=1.3.354; enumeration does not establish renderer selection or fix recorded GMEM scrolling corruption
- [x] **graphics.gl.render — Offscreen GL expected-image smoke** (functional; pass): OpenGL Adreno 680 GBM VBO scene rendered offscreen at 800x600 and passed pixel readback; one-scene smoke only, not sustained/desktop/idle coverage
- [x] **graphics.gles.render — Offscreen GLES expected-image smoke** (functional; pass): OpenGL ES Adreno 680 GBM VBO scene rendered offscreen at 800x600 and passed pixel readback; one-scene smoke only, not sustained/desktop/idle coverage
- [x] **graphics.vulkan.render — Windowless Vulkan static render and pixel readback** (functional; pass): Adreno 680 Vulkan rendered a public 64x64 color fixture windowlessly and matched all 4096 pixels; output discarded. Static path only: recorded GMEM scrolling/partial-damage corruption remains unresolved
- [x] **graphics.vulkan.dynamic-damage — Vulkan partial-area load/store regression (tile-buffer mode)** (functional; pass): Partial load/store in GMEM mode regression; ICD=VK_DRIVER_FILES=/usr/local/share/spx-turnip/freedreno_icd.aarch64.json; not general Vulkan conformance. A pass with the patched driver reflects a system-memory rendering workaround for affected passes, not a root-cause fix. Hardware Turnip matched the CPU pixel model for every frame

## Video

- **media.decode.formats — Exposed Venus decoder formats** (inventory; observed): 1 exposed Venus decoder node(s); advertised compressed-input formats: H264, HEVC, VP80, VP90; enumeration does not prove any codec workload; encoder is parked
- [ ] **media.encode — Hardware encoder workload** (functional; blocked): Encoder trials parked: known CVP fault/reset/hang and unresolved protected-buffer/recovery contract; no encoder open, autoload or workload attempted
- [x] **media.decode.h264 — H.264 hardware decode of supplied real media** (functional; pass): Supplied 1920x1080 fixture: h264_v4l2m2m on Venus; decoded=32 output=30, zero decode errors, complete progress; capped at 2s/30 frames, output discarded. Only this fixture codec/path tested; not encoder, all formats, pixels or sustained playback
- [x] **media.decode.hevc — HEVC hardware decode of supplied real media** (functional; pass): Supplied 1920x1080 fixture: hevc_v4l2m2m on Venus; decoded=32 output=30, zero decode errors, complete progress; capped at 2s/30 frames, output discarded. Only this fixture codec/path tested; not encoder, all formats, pixels or sustained playback
- [ ] **media.decode.mpeg2video — MPEG-2 hardware decode of supplied real media** (functional; blocked): Unsupported by this firmware for linear output: VIDEO.IR.1.2 rejects a separate MPEG-2 output buffer (OPB) and, in single-output mode, a linear DPB (SM8150 downstream recipe tested 2026-10-14); only UBWC output would remain, which ffmpeg/browsers cannot consume. The driver hides MPEG-2; no decode attempted
- [x] **media.decode.vp8 — VP8 hardware decode of supplied real media** (functional; pass): Supplied 1920x1080 fixture: vp8_v4l2m2m on Venus; decoded=32 output=30, zero decode errors, complete progress; capped at 2s/30 frames, output discarded. Only this fixture codec/path tested; not encoder, all formats, pixels or sustained playback
- [x] **media.decode.vp9 — VP9 hardware decode of supplied real media** (functional; pass): Supplied 1920x1080 fixture: vp9_v4l2m2m on Venus; decoded=32 output=30, zero decode errors, complete progress; capped at 2s/30 frames, output discarded. Only this fixture codec/path tested; not encoder, all formats, pixels or sustained playback

## Cameras

- **camera.graph — CAMSS media graph integration** (inventory; observed): CAMSS graphs=1, enabled links=74, fitted sensor entities=front,rear,ir; enumeration is not regulator ownership, frame delivery or full graph acceptance
- **camera.libcamera — Libcamera fitted-sensor metadata** (inventory; observed): verified private libcamera/CPU ISP (not distro integration); front model=ov5693 pixel_array=2592x1944 location=0 rotation=180 controls=3; rear model=ov13858 pixel_array=4224x3136 location=1 rotation=180 controls=3; ir model=ov7251 pixel_array=648x488 rotation=0 controls=3; metadata enumeration only, no capture or normal-app integration claim
- [x] **camera.front.frames — Front processed frame delivery** (functional; pass): front: verified private libcamera/CPU ISP (not distro integration); Three consecutive complete 1280x960 BGR888 frames with increasing timestamps; native test pattern off; memory-only discard, no emitter activation. Proves short processed delivery only, not image quality, illumination, app packaging or resume
- [x] **camera.rear.frames — Rear processed frame delivery** (functional; pass): rear: verified private libcamera/CPU ISP (not distro integration); Three consecutive complete 1280x960 BGR888 frames with increasing timestamps; native test pattern off; memory-only discard, no emitter activation. Proves short processed delivery only, not image quality, illumination, app packaging or resume
- [x] **camera.ir.frames — Ir processed frame delivery** (functional; pass): ir: verified private libcamera/CPU ISP (not distro integration); Three consecutive complete 632x480 BGR888 frames with increasing timestamps; native test pattern off; memory-only discard, no emitter activation. Proves short processed delivery only, not image quality, illumination, app packaging or resume

## Audio

- **audio.alsa — ALSA cards and PCM interfaces** (inventory; observed): ALSA cards=1, identified SPX cards=1, playback interfaces=3, capture interfaces=3; nodes do not establish acoustic output or microphone quality.
- **audio.controls — Native audio routing control capabilities** (inventory; observed): Native ALSA controls=1378, stereo PA control names=true, MM2 internal microphone route control names=true; capability only, no values read/written or stream started.
- **audio.soundwire — SoundWire core enumeration** (inventory; observed): SoundWire core nodes=2, attached=2, unattached=0, other states=0; parked amps may be unattached. Core enumeration is not verified physical output; no bridge/register reads.
- **audio.services — Desktop audio service availability** (inventory; observed): pipewire.service=active; pipewire-pulse.service=active; wireplumber.service=active
- **audio.graph — Desktop audio graph and default routing** (inventory; blocked): Graph outputs=1, sources=1 (monitors=1), SPX speaker nodes=1, SPX microphone nodes=0, USB output/input=0/0, Bluetooth output/input=0/0; default output=SPX, input=not exposed in graph. Read-only API/routing inventory, not signal delivery. Usable endpoint/default-route support is required; no route changed.
- **audio.feeder — Native desktop feeder readiness** (inventory; observed): Feeder active with current-boot readiness, recorded PA step=6, digital peak limit=32768; retained ASM enabled; full DSP destruction unvalidated. Readiness is not measured sound, latency or stream-lifecycle validation; no gain/PCM/graph changed.
- [ ] **audio.speakers — Physical speaker output** (functional; blocked): Speaker playback is not authorized for this suite; --capture is not playback permission. No PCM, amplifier power or gain change started.
- [ ] **audio.acoustic — Speaker acoustic feedback** (functional; blocked): The existing quiet audio.py reopen loop already verified the resolved WX fix. Its authorization is scoped to that fix, not routine acoustic retesting; no tone or microphone recording started.
- [ ] **audio.microphones — Internal microphone stimulus capture** (functional; blocked): Microphone capture is opt-in (--capture-microphone) and disabled. New audio/microphone variations remain parked; no private recording or PCM started.
- [ ] **audio.lifecycle — Native audio stream lifecycle** (functional; blocked): Parked DSP mappings must be preserved; full UNMAP/AFE STOP and arbitrary teardown remain unsafe/unvalidated. No PCM open/close, graph mutation, service restart or module change performed.
- [ ] **audio.external — External USB and Bluetooth audio data paths** (functional; blocked): External USB/Bluetooth graph output/input nodes=0/0; real audio fixtures, a controlled signal/recording path and separate sound authorization required for data-path validation. No playback, capture, radio/route change or hotplug performed.

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
- [ ] **usb.transfer — Checksum-verified disposable USB storage transfer** (functional; blocked): USB-backed disposable transfer probe is not implemented: needs an explicit mounted fixture and verified USB block-device ancestry before bounded checksum I/O. Ordinary root-storage I/O or speed enumeration cannot prove USB transfer; no block device opened or file written

## USB-C

- **usb.roles — Read-only Type-C attachment and role metadata** (inventory; blocked): Type-C class ports=0, partner paths=0, USB role interfaces=0; ; role/orientation reporting interface missing; the SPX port-zero HPD bridge is not full two-port Type-C/PD integration
- **usb.pd — Reported USB-C power-delivery metadata** (inventory; blocked): Type-C ports reporting PD mode=0; USB power interfaces=0, online=0, reporting PD type=0; no supported PD contract/charger reporting path; firmware PD/second-port contract unresolved, not absence of charging hardware
- [ ] **usb.typec-routing — Data delivery over an attributable Type-C route** (functional; blocked): Full firmware Type-C/PD and lane-routing support remains unresolved; functional route/transfer probe and already-attached attributable fixture are unavailable. Port-zero HPD metadata does not prove data delivery; no role, cable, PHY or display changes attempted

## Dock and Surface Connect

- **dock.paths — Dock and Surface Connect attached path attribution** (inventory; blocked): Current paths: non-root USB=0, non-wireless Ethernet-style=0, connected external DRM=0, Thunderbolt bus entries=0, Surface Aggregator clients=11; supported Surface Connect attachment/capability attribution unavailable. These counts do not identify connector/dock, Thunderbolt mode, audio/charging or concurrent operation; accessory topology fixture/firmware contract needed
- [ ] **dock.concurrent — Attributable dock concurrent data and display operation** (functional; blocked): Concurrent dock probe is not implemented; needs an already-attached identifiable dock, supported connector topology, safe data fixture and active external scanout. Generic USB/display counts are inventory; no attachment, playback or charging actions attempted

## Input

- **input.startup — IPTSD service and virtual-device startup health** (inventory; observed): IPTSD active=1, failed=0, restarts=0; virtual touch=true, virtual pen=true; readiness metadata only, not physical touch or repeat-boot reliability; restarts are reported, not concealed
- **input.accessory — Pen and keyboard accessory battery metadata** (inventory; blocked): No attributable pen/keyboard battery-reporting path; identified accessory model/applicability and supported charging/wireless-button interface needed; no hardware absence inferred
- **input.touch — Touchscreen direct multi-touch capabilities** (inventory; observed): Matching input capability interface exposed; Surface/IPTSD identified=true; advertised capabilities only; no input events, physical actions or lifecycle tested
- **input.pen — Pen position, pressure and tilt capabilities** (inventory; observed): Matching input capability interface exposed; Surface/IPTSD identified=true; pressure=true, tilt X=true, tilt Y=true, eraser=true, barrel buttons=true; advertised capabilities only; no input events, physical actions or lifecycle tested
- **input.keyboard — Keyboard key and indicator capabilities** (inventory; observed): Matching input capability interface exposed; Surface/IPTSD identified=true; CapsLock indicator=true; advertised capabilities only; no input events, physical actions or lifecycle tested
- **input.touchpad — Touchpad pointer multi-touch capabilities** (inventory; observed): Matching input capability interface exposed; Surface/IPTSD identified=true; advertised capabilities only; no input events, physical actions or lifecycle tested
- **input.buttons — Power/volume and posture switch capabilities** (inventory; observed): Matching input capability interface exposed; Surface/IPTSD identified=true; power=true, volume up/down=true/true, lid/tablet switches=false/false; advertised capabilities only; no input events, physical actions or lifecycle tested

## Sensors

- **sensors.channels — Light and motion channel capabilities** (inventory; observed): Allowlisted light channels=5, motion channels=0, TCS3430 interfaces=1; PMIC ADCs excluded; TCS3430 XYZ/IR is not proximity or a verified lux conversion; SDSP motion may be outside IIO; advertised capability only, not stimulus, axes or calibration
- **sensors.backend — SDSP sensor backend and startup services** (inventory; observed): SDSP FastRPC endpoints=1, CDSP endpoints=0; sensor provider=active, proxy=active; running DT disables CDSP FastRPC: compute transport intentionally parked, not missing silicon and not the SDSP sensor path; endpoint/service metadata only, not sensor delivery or CDSP workload
- **sensors.desktop — Already-running SensorProxy cached properties** (inventory; observed): Already-running SensorProxy advertised capability groups=2, finite cached numeric properties=1; read-only, no Claim/stream/start; cached values may be stale, not fresh delivery, axes/calibration or brightness response
- [x] **sensors.light-lux — Calibrated ambient-light report delivery** (functional; pass): Kernel processed lux reads=38.2131,38.2131; surface_unit_calibration=Y; gain=unavailable; integration_time=unavailable; SensorProxy LightLevelUnit=lux, LightLevel=38.2131 after ClaimLight; LightLevel was read after the claim; claim released on the same connection; calibration is this unit's factory Type_3 data applied with the Windows driver's formula; this does not establish absolute accuracy against a reference lux meter, colour temperature, or brightness-control behaviour. A stationary dim room may leave the proxy value unchanged: the two kernel reads prove fresh conversion while the proxy polls the processed channel
- [ ] **sensors.desktop-motion — Fresh desktop accelerometer delivery** (functional; blocked): Device is stationary and the property was already defined before the claim so freshness cannot be distinguished; no accelerometer PropertiesChanged in 6 s; claim released; HasCompass=true; compass not covered: delivery not exercised (ClaimCompass normally restricted to geoclue)
- [x] **sensors.desktop-compass — Fresh desktop compass delivery** (functional; pass): Fresh desktop compass delivery: PropertiesChanged headings=29, min/max=82.3/82.4 degrees; before=82.1° after=82.3°; proves fresh desktop compass delivery only, not calibration, true-north accuracy or tilt compensation; claim released
- [x] **sensors.light-read — One-shot light-channel numeric read** (functional; pass): One-shot finite light-channel reads=5, zero-valued=1; raw values discarded; zero is not a light/stimulus failure; no scale/lux, physical axes, calibration, rotation, proximity or lifecycle claim
- [x] **sensors.motion-read — Bounded SSC accelerometer/gyro/magnetometer delivery** (functional; pass): Fresh finite XYZ rows: accelerometer=70, gyroscope=69, magnetometer=29; each CLI exit0 with enable/disable ACKs, requested stream=3s, outer TERM=12s/KILL-after=2s; same already-running provider; raw samples/logs discarded; no physical axes, mounting, calibration, rotation or resume claim
