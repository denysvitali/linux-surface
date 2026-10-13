# Surface Pro X: hardware completion checklist (from the published specs)

Every hardware feature Microsoft lists for the Surface Pro X, what "works"
means for it on Linux, and where it stands. Source: Microsoft's "Surface Pro X
features and specs" page
(<https://support.microsoft.com/en-us/surface/models/surface-pro-x-features-and-specs>),
plus hardware found on this unit (SQ2, 16 GB, 256 GB, LTE).

This file does not replace `linux-surface-next/PORT-CHECKLIST.md`. That file is
the frozen acceptance list (47 boxes); the "Box" column maps each spec item to
it. Every spec item below is already covered by a box, so no box is missing.

- **Auto check**: the `hwv.py` check IDs that probe the item. They prove the
  interface exists and answers, nothing more.
- **State** is as of 2026-10-11, kernel `7.3.0-rc2-spx-mainline-20261004bg+`,
  boot `c8158f7d`, from the suite run and the port's result files.
  *Works* = usable today. *Partial* = usable with a gap. *Broken* = not usable.
- An item is done when its box closes: tick it here only then.

## Compute and storage

| | Spec item | Done when | Box | Auto check | State |
|---|---|---|---|---|---|
| [x] | Microsoft SQ2 (SC8180XP), 8 cores | 8 cores online, both clusters scale to full frequency, stable under load | B03 | cpu.cores, cpu.freq | Works |
| [x] | 16 GB LPDDR4x | full memory visible and stable under load | B03 | mem.total | Works |
| [x] | 256 GB NVMe SSD | checksummed I/O, sustained and after resume, no errors | B02 | storage.nvme, storage.rw | Works (disk is 100% full: 76 MiB free) |
| [x] | Adreno 690 GPU | hardware GL in the desktop, 30 min rendering without faults | D02 | gpu.render, gpu.devfreq | Works on OpenGL; Vulkan (Turnip) corrupts GTK windows, worked around |
| [ ] | Hardware video decode/encode (Venus) | real H.264/HEVC/VP9 decode through V4L2, sustained playback | D03 | video.codec | Broken: driver not loaded; startup fixed, decode faults in firmware |
| [ ] | Hexagon compute DSP / NPU | a real workload on CDSP, or documented as unsupported | B07 | accel.cdsp | Broken: CDSP runs, no FastRPC compute node; NPU has no driver |
| [ ] | ADSP, CDSP, modem, SLPI firmware | all stay up through combined use and resume | B04 | fw.remoteproc, fw.services | Partial: all four run; resume and workarounds unreviewed |

## Display and input

| | Spec item | Done when | Box | Auto check | State |
|---|---|---|---|---|---|
| [ ] | 13" PixelSense 2880x1920, 3:2 | native mode, no flicker, brightness range, returns after blank/suspend | D01 | disp.panel, disp.backlight | Partial: works, needs an EDID override on the command line; visual sweep and resume not done |
| [ ] | 10-point multi-touch | real taps, drags, edges, gestures; again after suspend; reliable at boot | I01, I02 | in.touch | Partial: user confirms touch works; repeat-boot and resume not done |
| [ ] | Surface Pen (MPP) | position, pressure, tilt, hover, buttons, eraser, palm rejection | I03 | in.pen | Partial: user confirms pen works; capabilities not itemised |
| [ ] | Surface Pro X Keyboard | typing, Fn/media keys, backlight, detach/reattach, resume | I04 | in.keyboard, in.kbd_backlight | Partial: typing works; no backlight control exposed; hotplug/resume untested |
| [ ] | Keyboard touchpad | pointer, click, scroll, gestures, palm rejection | I05 | in.touchpad | Partial: enumerates; gestures/hotplug untested |
| [ ] | Slim Pen cradle charging | pen charges in the keyboard, battery reported | I07 | (manual) | Untested |
| [ ] | Power and volume buttons | each press gives one event and the right desktop action; wake | I06 | in.buttons | Partial: power prompt confirmed; volume and wake untested |
| [ ] | Cover / tablet posture | tablet mode and cover-closed detected | I06 | in.switches | Partial: tablet-mode switch present; no lid/cover-closed switch |

## Audio

| | Spec item | Done when | Box | Auto check | State |
|---|---|---|---|---|---|
| [ ] | 2 W stereo speakers | both speakers, correct L/R, useful volume, no static | A01 | aud.card, aud.amps | Partial: stereo confirmed by ear and microphone; low maximum volume, about 150 ms latency |
| [ ] | Dual far-field Studio Mics | known stimulus recorded on each mic, usable gain/noise | A02 | aud.card | Partial: array captures; quality and mapping not judged |
| [ ] | Desktop audio (PipeWire/UCM) | normal apps play and record after boot and resume with no manual setup | A03 | aud.desktop, aud.feeder | **Broken right now**: PipeWire and the speaker feeder service have been dead since 2026-10-10 08:39; it depends on an out-of-tree Python feeder and parked DSP sessions |
| [ ] | USB-C and Bluetooth audio | external output/input, hotplug, reconnect | A04 | aud.external | Untested (no 3.5 mm jack on this device) |

## Connectivity

| | Spec item | Done when | Box | Auto check | State |
|---|---|---|---|---|---|
| [ ] | Wi-Fi 5 (802.11ac) | 2.4/5 GHz, IPv4/IPv6, sustained transfer, reconnect after toggle/suspend | N01 | net.wifi, net.wifi.ping | Works for daily use at 5 GHz; roaming, native IPv6 and resume open |
| [ ] | Bluetooth 5.0 | pair, reconnect, HID and audio, coexistence, resume | N02 | net.bt | Partial: radio works; intermittent framing error; peripherals untested |
| [ ] | Snapdragon X24 LTE, nano-SIM + eSIM | registration and real data, reconnect, resume | N03 | net.wwan | Broken: modem firmware runs but no IPA/WWAN device, no ModemManager; rejects online mode |
| [ ] | Assisted GPS + GLONASS | a real fix with plausible position, reacquire | N04 | net.gnss | Broken: QMI location service is up, no Linux GNSS device, no fix |

## Ports

| | Spec item | Done when | Box | Auto check | State |
|---|---|---|---|---|---|
| [ ] | 2x USB-C data (USB 3.2 Gen 2) | both ports, both orientations, USB2 and USB3, checksummed transfer, hotplug | U01 | usb.controllers, usb.superspeed | Partial: a dock with a 10 Gb/s hub, Ethernet and audio works on one port now; per-port/orientation not covered |
| [ ] | USB-C Power Delivery and roles | orientation and role detection, charger negotiation on both ports | U02 | usb.typec | Broken: no Type-C class ports or role switches; orientation is forced on the command line |
| [ ] | USB-C DisplayPort | monitor on each port, hotplug, extend/mirror, resume | U03 | usb.dp | Partial: one DP output works (3440x1440, user confirmed); only one DP connector exists for two ports |
| [ ] | Surface Connect | charging, and dock USB/Ethernet/display/audio | U04 | (manual) | Untested |

## Cameras

| | Spec item | Done when | Box | Auto check | State |
|---|---|---|---|---|---|
| [ ] | Front 5 MP, 1080p | real scenes, correct colour/exposure, start/stop, resume | C02 | cam.front, cam.frames | Partial: streams about 30 fps, orientation confirmed; colour tint and resume open |
| [ ] | Rear 10 MP autofocus, 1080p/4K | real scenes, focus, resolutions, start/stop, resume | C03 | cam.rear, cam.rear_af | Partial: streams 30 fps, dim/noisy; **no autofocus actuator driver** |
| [ ] | Windows Hello IR camera | IR frames, illuminator control, repeated use | C04 | cam.ir, cam.ir_led | Partial: streams 30 fps with a private libcamera patch; **no illuminator control** |
| [ ] | Cameras in normal apps, privacy LEDs | processed streams in apps, camera selection, activity LED | C05 | cam.apps, cam.privacy_led | Partial: libcamera lists all three; needs private libcamera build; DT not in the boot DTB |
| [ ] | Camera power integration | real supplies and sequencing, no guessed rails | C01 | cam.camss | Partial: binds; supply ownership unresolved |

## Sensors

| | Spec item | Done when | Box | Auto check | State |
|---|---|---|---|---|---|
| [ ] | Ambient light sensor (TCS3430) | readings follow light, desktop auto-brightness | S01 | sens.als, sens.als.desktop | Partial: IIO device reads; sensor proxy not running, no auto-brightness |
| [ ] | Accelerometer, gyroscope, magnetometer | correct axes, auto-rotation, resume | S02 | sens.motion | Broken on this boot: sensors sit behind SLPI and the opt-in service is not running; worked on earlier trial boots |

## Power and platform

| | Spec item | Done when | Box | Auto check | State |
|---|---|---|---|---|---|
| [ ] | Battery 38.2 Wh, charging | plausible values, charge and discharge, AC transitions, charge limit | P01 | pwr.battery, pwr.charging | Partial: reports correctly (30.6 of 38.2 Wh, 166 cycles); on AC but "Not charging" at 46%, unexplained; battery tests deferred |
| [ ] | Battery life / idle power | measured idle and active draw, no forced-on clocks | P02 | pwr.idle, gpu.devfreq | Untested; `clk_ignore_unused` still set |
| [ ] | Modern standby (s2idle) | ten cycles, 30 min battery sleep, all devices recover | P03 | pwr.suspend | Partial: AC sleep passed on trial boots; suspend targets are masked on the baseline |
| [ ] | Hibernate | restore works, or documented as unsupported | P04 | pwr.hibernate | Not set up: no swap, no resume device |
| [ ] | Fanless thermal design | sensors plausible, throttling holds under sustained load | P05 | pwr.thermal | Partial: 28 zones and 4 cooling devices; automatic response never triggered |
| [ ] | Firmware TPM | TPM 2.0 functions, Secure Boot path documented | B06 | tpm.present, tpm.secureboot | Partial: TPM 2.0 works; Secure Boot is off and unvalidated |
| [ ] | Real-time clock | time survives power-off and suspend | B05 | rtc.present | Partial: Surface RTC correct; cold retention untested |

## Whole-system acceptance (not in the spec sheet)

| | Item | Box | State |
|---|---|---|---|
| [ ] | 5 cold and 10 warm boots without repair | B01 | Open |
| [ ] | Crash diagnostics and recovery coverage | R01, R02 | Open (pstore and watchdog are present) |
| [ ] | Full inventory, one final candidate, 24 h regression, review | F01 to F04 | Open: 30 diagnostic parameters on the command line, out-of-tree modules loaded |

## Summary

4 of the 34 spec items are done (CPU, memory, SSD, GPU), which matches the 3
closed boxes (B02, B03, D02). Not usable at all today: hardware video codec,
cellular, GNSS, USB-C PD/role handling, compute DSP/NPU, hibernate, rear
autofocus, IR illuminator, and (on this boot) desktop audio and motion sensors.
