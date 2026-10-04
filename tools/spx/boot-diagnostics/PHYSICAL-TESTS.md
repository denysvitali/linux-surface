# Surface Pro X hands-on checks

Run these after the agent identifies the current mainline boot. Report each
item as **works**, **fails** (what happened), or **not available**. No camera,
microphone or speaker test is included. Keep a phone or another chat device
available during a network or sleep check.

1. **Keyboard/touchpad:** type `Surface Pro X 123`, use Shift and Backspace,
   move the pointer, click, right-click and scroll with two fingers. Detach
   and reattach the cover, then repeat. (I04, I05)
2. **Touch/pen:** tap the four corners and centre; drag a window and scroll.
   With the pen, draw slow lines across the screen, press lightly then firmly,
   hover, and try its fitted buttons/eraser. Report missing pen separately.
   (I02, I03)
3. **Buttons/panel:** press each volume button and check the on-screen level;
   close and reopen the cover. Inspect the screen for corruption/flicker and
   change brightness from low to high. Leave the power-button sleep check
   until step7. (I06, D01, D02)
4. **USB/charging:** insert a disposable USB stick in each port, then flip the
   connector orientation. The agent will run a checksum transfer only on a
   scratch file. Unplug the charger for60s, reconnect it and wait60s; identify
   whether it uses USB-C or Surface Connect. (U01, U02, P01)
5. **Bluetooth:** put one owned mouse/keyboard/headset in pairing mode; identify
   it so the agent pairs only that device. Check input with an HID device.
   Headset sound needs a separate explicit request. (N02)
6. **Sensors:** shade then illuminate the ambient-light sensor, bring a hand
   near it, and rotate the tablet clockwise and back. Report whether desktop
   brightness/rotation responds; the agent records sensor channels. (S01, S02)
7. **Sleep, when the agent is ready:** press power to sleep, wait30s and press
   power once to wake. Confirm the panel, input and network return. Do not
   repeat if it hangs; the agent records the result first. (P03)

For the next session, first isolate the current blockers:

- **Touch/pen:** after the agent announces a recording window, drag a finger
  for five seconds, then hover and draw with the pen for five seconds. The
  agent counts the SPI-HID IRQ/report metadata tracepoints and virtual IPTSD
  input events, without storing report payloads or coordinates. Record the
  kernel and boot ID with the observation; recovery and mainline differ.
- **Dock:** name the dock and tablet port, unplug/replug it, and report whether
  a desktop appears on its monitor. The first forwarding candidate supports
  only EC port 0; the physical connector mapping and reverse orientation need
  verification. Connector status alone is not visible-output evidence.
- **Power/wake:** first press power briefly while the agent inhibits its desktop
  action and observes the PMIC power-key input/IRQ. Do not assume it is an SSAM
  button. If identified, test one 15-second s2idle with a second short press to
  wake, before the longer step above. The agent must temporarily unmask the
  sleep targets and check wake policy. SSAM wake remains disabled initially;
  it can wake on unrelated EC events. Unload the experimental USC forwarding
  module before this first sleep test; never unload MSM. There is no working
  RTC alarm fallback.

These initial actions establish usable functions. Longer charging, both Wi-Fi
bands, repeated sleep/USB cycles, accessories and final-candidate regression
remain separate acceptance checks.
