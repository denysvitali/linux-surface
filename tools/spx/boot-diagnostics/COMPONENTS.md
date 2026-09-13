# Surface Pro X mainline validation

Boot success is a prerequisite, not component validation. Record the tested
kernel release, commit, config, DTB/image hashes, boot ID and connected hardware
with each result. The 2026-09-13 diagnostic tests intentionally disable devices
and cannot satisfy this table. All mainline functional results below are pending.

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
