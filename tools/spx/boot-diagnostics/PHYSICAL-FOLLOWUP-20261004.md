# Physical follow-up: useful functions and desktop blockers

On mainline BI, boot `84e729fc-a68c-4720-a6f0-042acf60f604`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`, the user now confirms **touch, pen, keyboard
and Bluetooth work**. Speakers do not work; BI intentionally blocks their
drivers. Dock monitor confirmation was requested separately. See the
[BI result](RESULT-20261004bi.md) for current evidence.

## Earlier report, kernel attribution unresolved

The user reports cover detach/reattach works but is slow; display and brightness
work; touch and pen do not work; GNOME cannot enable Bluetooth; USB-C charging
works but the dock monitor is blank; no suspend option appears, and a short power
press opens the shutdown prompt. **Which kernel was tested is awaiting the user's
confirmation.** Do not assign these observations to BH or close its acceptance
boxes until that is established. Dock model and port are also pending.

## Verified separately

The coordinator inspected recovery boot
`f309dbfa-4e99-4bdd-9059-efc12f21b817`, `6.18.3-1-surface+`:

- Bluetooth lacked its public address, so BlueZ had no controller. Restoring the
  documented installation address made it appear with `Powered: yes` and
  `PowerState: on`. This is a runtime repair only. The disabled installer service
  contains a different address; it was left unchanged. The user subsequently
  confirms “BT works now” on this recovery boot. Pairing/peripheral use and
  persistence remain untested. BH supplied the address through its private DTB and
  successfully scanned after software unblock and firmware setup.
- `sleep.target` and `suspend.target` are masked. `CanSuspend` returns `no`,
  although the kernel exposes `freeze mem disk` and `[s2idle]`. The masks date
  from August 29. GNOME's power-button setting is `suspend`; its observed shutdown
  prompt is consistent with unavailable sleep, but the precise UI fallback was
  not traced. No suspend or wake test ran; the masks remain in place.
- Recovery touch startup logs contain invalid headers, `-22` and ready timeout;
  initially no IPTSD instance was active. The installed add-only udev rule runs
  `iptsd-check-device` before requesting the service. That helper opens hidraw,
  so a failed startup can leave neither the systemd device dependency nor an
  IPTSD instance for the existing service retry policy to restart. A single
  targeted `udevadm trigger --action=add /sys/class/hidraw/hidraw5` on the same
  recovery boot restored `ready`, a running IPTSD instance (`NRestarts=0`),
  and virtual touchscreen/stylus devices. Bus errors rose from five to seven
  (`-22`); startup reliability is not fixed. Physical touch/pen confirmation was
  requested. BH separately had clean startup and virtual input publication,
  without a physical sample test. Recovery success does not establish a
  mainline input pass.
  The new `71-spx-iptsd-startup.rules` matches only SPI HID `045E:0C21` and
  requests IPTSD independently of the packaged helper's result, letting the
  existing three-start/120-second service policy handle failed opens. It passed
  `udevadm verify` and is installed/reloaded without another device trigger.
  Automatic startup with this rule remains untested.
  The user subsequently confirms touch works on recovery f309dbfa/6.18.3,
  though sensitivity seems low and is acceptable for now. Pen operation was
  not confirmed. This observation must be repeated on mainline.

Offline comparison finds the mainline primary DP controller already enabled,
but no Surface USC-to-HPD forwarding module. The 6.18 `spx_hpd_inject` source
cannot be copied unchanged: its private MSM structure and HPD callback ABI differ
from mainline. Port it using `drm_bridge_hpd_notify`, then test actual monitor
output. Connector enumeration in older logs never proved visible pixels.

## Next functional checks

1. Confirm the kernel used for the original five observations; test GNOME's
   Bluetooth toggle on mainline, then pair/use one owned input device.
2. On an identified boot with IPTSD active, capture input-event counts and SPI-HID
   metadata while the user drags a finger for five seconds and hovers/draws with
   the pen. Locate whether delivery stops before or after virtual input creation.
3. Port DP hotplug forwarding, then replug the identified dock and confirm a
   visible extended/mirrored desktop. Never reload or rebind MSM display.
4. Identify the physical power button through PMIC input events/IRQ before
   unmasking a controlled sleep test. The SPX SSAM registry omits its HID system
   controls device; do not assume the power button uses SSAM. The PMIC driver
   already enables wake by default. SSAM wake remains disabled initially
   because unfiltered EC events can cause unwanted wakes. No RTC wake fallback
   exists. Kernel sleep-state exposure alone does not establish successful wake.

Evidence: `functional/20261004bh/followup-20261004/` under
`/var/lib/spx-boot-diagnostics/`, retained BH journals, and the user's report.
The single retrigger result is `touch-single-add-retrigger-20261004.log`.
A subsequent 60-second virtual-event count observed no input, with no confirmed
physical stimulus; it cannot establish an input failure or pass.
No reboot, sound, camera/microphone capture or full acceptance pass this round.
