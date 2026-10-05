# Recovery keyboard restored after SSAM startup timeout

Recovery boot `ab15d0b8-0e5b-404b-a380-246b9878f4ca`, kernel
`6.18.3-1-surface+`, followed BP's scheduled return. The user reported the
keyboard did not work, then confirmed **“It's back!”** after the live repair.
This is a recovery-kernel result; BI's mainline keyboard pass remains separate.

At boot, `surface_serial_hub serial1-0` failed its firmware-version request
with `-ETIMEDOUT` at uptime 11.64 seconds. The serdev child remained unbound,
the Surface Aggregator bus had no children, and both Type Cover input devices
and battery/AC readout were missing. The modules were already loaded.

At 23:22:48 CEST, with the device lock held, the coordinator bound that
unbound child once through `/sys/bus/serial/drivers/surface_serial_hub/bind`.
The bind returned successfully in 7 ms. The parser initially discarded invalid
framing/CRC data, then read SAM firmware `1.207.139`. Keyboard `045E:09AE`,
the accessory devices, touchpad `045E:09AF`, tablet switch and RTC appeared.
Udev classified the new input nodes as keyboard and touchpad. BAT1/ADP1 also
returned: battery 49%, status `Not charging`, external power online.

The user confirms keyboard function on this same boot. Touchpad registration
is established, but its physical use was not separately confirmed. No reboot,
kernel/module change, input recording, sound or microphone capture was needed.

**Meaning and next:** this was a failed SSAM startup, recoverable through one
late probe. The trigger for the initial timeout and a persistent startup fix
remain unresolved. If it recurs, retain the initial serial/controller messages
and check whether the child is unbound before considering another probe; do not
unbind a working controller. Do not reset the shared UART parent or MSM display.

Evidence: `/var/lib/spx-boot-diagnostics/recovery/20261004-ab15d0b8-keyboard/`
contains before/after input inventories and relevant kernel logs, `reprobe.json`
for the synchronous bind, and `settled-state.json` for asynchronously published
children and the user confirmation. No additional mainline acceptance box closes.

## Repeat on 2026-10-05

Recovery boot `d87f94b5-e519-4372-be2e-c616d81f5095`, same6.18 release, repeats
the firmware-version timeout at11.36s after BW's scheduled return. The SSAM
client is unbound and keyboard/touchpad, power supplies and RTC are absent.
One guarded bind at267.56s completes in6.9ms and restores all device nodes,
eleven SSAM children, BAT1/ADP1 and rtc0. RTC resumes reading the correct date.
Physical typing is not newly confirmed; the October4 user result stays separate.

A generic single late-probe workaround is being prepared for this exact
unbound-after-timeout condition. It must skip healthy controllers, never unbind
them, and make no repeated bind attempts. Root cause and cold-start reliability
remain unresolved. Evidence is under
`/var/lib/spx-boot-diagnostics/recovery/20261005-d87f94b5-ssam/`.
