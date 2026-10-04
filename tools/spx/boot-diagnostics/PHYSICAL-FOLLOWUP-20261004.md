# Physical follow-up: useful functions and desktop blockers

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
  contains a different address; it was left unchanged. GNOME toggle/pairing still
  needs a person. BH already supplied the address through its private DTB and
  successfully scanned after software unblock and firmware setup.
- `sleep.target` and `suspend.target` are masked. `CanSuspend` returns `no`,
  although the kernel exposes `freeze mem disk` and `[s2idle]`. The masks date
  from August 29. GNOME's power-button setting is `suspend`; its observed shutdown
  prompt is consistent with unavailable sleep, but the precise UI fallback was
  not traced. No suspend or wake test ran; the masks remain in place.
- Recovery touch startup logs contain invalid headers, `-22` and ready timeout;
  no IPTSD instance is active. BH, separately, had clean startup and virtual
  input publication, without a physical sample test. Those observations cannot
  explain a runtime touch failure on BH.

Offline comparison finds the mainline primary DP controller already enabled,
but no Surface USC-to-HPD forwarding module. The 6.18 `spx_hpd_inject` source
cannot be copied unchanged: its private MSM structure and HPD callback ABI differ
from mainline. Port it using `drm_bridge_hpd_notify`, then test actual monitor
output. Connector enumeration in older logs never proved visible pixels.

## Next functional checks

1. Confirm the tested kernel; reopen GNOME Bluetooth settings and toggle off/on,
   then pair/use one owned input device.
2. On an identified boot with IPTSD active, capture input-event counts and SPI-HID
   metadata while the user drags a finger for five seconds and hovers/draws with
   the pen. Locate whether delivery stops before or after virtual input creation.
3. Port DP hotplug forwarding, then replug the identified dock and confirm a
   visible extended/mirrored desktop. Never reload or rebind MSM display.
4. Prepare the SSAM power-button wake path before unmasking a controlled sleep
   test. Kernel sleep-state exposure alone does not establish successful wake.

Evidence: `functional/20261004bh/followup-20261004/` under
`/var/lib/spx-boot-diagnostics/`, retained BH journals, and the user's report.
No reboot, sound, camera/microphone capture or full acceptance pass this round.
