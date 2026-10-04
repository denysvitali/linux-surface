# Surface Pro X mainline validation

**Current acceptance tracking is in [PORT-CHECKLIST.md](../../../PORT-CHECKLIST.md).**
Read it before choosing port work and update its feature IDs after testing.
The [AO result](RESULT-20261002ao.md) passed the bounded baseline, including
native right-codec initialization and touch readiness after an automatic retry.
Full hardware functionality is incomplete. The [current inventory](HARDWARE-INVENTORY-20261002.md)
is metadata only. This document retains historical evidence; its older soundcard,
microphone and recovery statements are not current status. In particular, read
the [microphone correction](AUDIO-ORACLE-RESTORED-20260928.md).

## Historical component evidence (through Q)

The historical [Q result](RESULT-20260927q.md) records a completed stage-7 PIO
capability waiter and 620.48-second automatic archive. Its first-pass fault
filter misread `ramoops` as an oops; an independent archived check found no
actual selected fault and stopped the fallback after verification. SLIM
controller registration, soundcard and playback remain untested.
The preceding [P result](RESULT-20260922p.md) records a 1315.07-second final
collector and scheduled fallback return. P reached the reactive PIO capability
worker and first FIFO write with no logged PIO error; it did not prove frame
delivery, capability completion or functional audio. The live finalizer was
missed, so P has a recovered archive rather than a retained-session result.
The previous [O result](RESULT-20260922o.md) records 611.87 seconds on the
same L kernel `7.3.0-rc2-spx-mainline-20260922l+`, with startup logging disabled.
Audio stage 5, step 2 completed the isolated interrupt-status-clear sequence
and stopped. All printed statuses were zero; the actual write operand was
not logged. Graphics, Wi-Fi, remote processors and input startup remained
healthy. All 296 result files were verified before stopping the fallback.
Audio transport, playback, physical input and sustained reliability remain
unverified. J/K's missing HID and I's different open timeout are not established
as fixed by these later successful boots. I through O performed no recovery
return. P used a new build with the capability-retry length fix; its
20-minute replacement fallback returned it.

The earlier [2026-09-22 H result](RESULT-20260922h.md) records mainline
`7.3.0-rc2-spx-mainline-20260922g+`, boot
`3af15a82-c6ed-4d5e-b165-b332e3869793`, with these bounded results:

- Encrypted root and the graphical desktop remained running through the
  865.10-second observation. The session was retained on mainline; H performed no
  recovery reboot, and the persistent default remains `spx-known-good`.
- The A680 GBIF correction passed [D's graphical startup and orderly
  return](RESULT-20260922d.md). E, F, G and H created Wayland EGL contexts
  using freedreno FD680, with OpenGL 4.6 and OpenGL ES 3.2. No GPU/HFI failure
  was recorded during H's observation. F's brief brightness write at 364 seconds
  produced matching requested/actual readbacks and restored the original
  value. Human visual confirmation, rendering stress and display blank/unblank
  remain unverified.
- NetworkManager/wpa_supplicant completed WPA/CCMP association and DHCP;
  `wlan0` remained connected and carried the session. G's activation at 42.553
  seconds was 43.524 seconds earlier than F, without F's modem restart delay.
  H activated at 44.113 seconds and again had no modem restart delay.
  CMAC support allows iwd to start, but logs still show overlapping supplicants
  and scan warnings.
  Sustained transfer and Bluetooth peripheral tests remain pending.
- F, G and H include UINPUT as a normal in-tree module. IPTSD automatically connected
  `045E:0C21` and created virtual touchscreen/stylus nodes; it remained active
  through the observation, with kernel taint zero. This persists
  [E's supplementary-module result](RESULT-20260922e.md). Physical touch/pen
  actions remain unverified.
- H audio stage 2 completed QMI SELECT_INSTANCE, pinned the NGD module, received
  a successful ACTIVE power acknowledgment and stopped at its guard. ADSP
  remained running, the child runtime-suspended, and DMA, NGD interrupt-enable,
  full registration and PIO parameters disabled. No soundcard or playback is
  expected at this stage; [stage 3 is a separate plan](AUDIO-STAGE3-20260922.md).
- G's modem started once at 26.736 seconds, with no announcement failure or
  fatal error through the observation after the isolated QRTR reversal. This
  supports the timing hypothesis; H repeated a clean modem startup at28.652s.
  These bounded boots do not establish an intermittent-race fix. Subsequent
  read-only DMS/UIM queries on G succeeded:
  operating mode is factory-test and the SIM card is absent. No mode/unlock/data
  change was made. The missing WWAN/IPA/RMNET host data path also remains, so
  cellular data is not passed. External displays and suspend/resume remain
  unvalidated. [Camera history](CAMERA-STATUS-20260922.md) now confirms three
  working raw capture paths on 6.18 v23, but mainline config, DT and proper
  regulator integration are still incomplete; only offline review is underway.

Record release, source/config, artifact hashes, boot ID and connected hardware
with every further test. The table below describes the broader functional
evidence still required; startup or enumeration alone does not satisfy it.
The [earlier journal review](OFFLINE-20260922.md) and 2026-09-13 diagnostic
boots are historical evidence, superseded for current boot/graphics status by
the D/E/F/G/H results above.

| Component | Required functional evidence |
| --- | --- |
| Boot and storage | Encrypted root mounts, no oops/panic or filesystem errors, sustained normal use and a subsequent boot with the same artifacts. |
| Internal display and GPU | Native panel mode, working brightness control, hardware-rendered desktop, no DRM faults under rendering and display blank/unblank. |
| USB-C and DisplayPort Alt Mode | Connected dock/device enumerates on each port, external monitor uses its intended mode, unplug/replug recovers without a kernel fault. Enumeration of a USB root hub alone does not pass. |
| Speakers | Both physical channels play independently; microphone captures confirm useful output, balance at several volumes and no added static. Driver/card enumeration is insufficient. |
| Microphones/headset | Actual captured signal from built-in microphones; headset output/input and jack detection where supported. |
| Modem | Remoteproc starts, ModemManager discovers the modem, SIM/network status is readable; actual data connectivity requires an available SIM/service. A running remoteproc alone does not pass. |
| Wi-Fi/Bluetooth | Wi-Fi connects and transfers data; Bluetooth controller initializes and a real peripheral reconnects and functions. |
| Keyboard/touchpad/touch/pen | Real input events and expected desktop actions, including detach/reattach where applicable. |
| Power and battery | Plausible battery telemetry, AC changes observed, charge/discharge behavior and idle power checked. |
| Suspend/resume | Explicit suspend resumes with display, input, network and audio still functional; no watchdog reset or unexpected reboot. |
| Cameras | Device enumerates and actual frames are captured with appropriate exposure/orientation. |
| Sensors | Orientation/light or other exposed sensor readings change appropriately with physical stimulus. |

Recovery snapshot 2026-09-13: only USB root hubs are attached, no external
microphone or dock is enumerated, and ModemManager is inactive. These are test
fixture/service constraints, not evidence of a mainline driver failure. Request
the relevant physical devices when the full mainline kernel is ready to test.
