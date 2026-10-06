# Recovery Bluetooth restored; address guard passes module-reload repair

Boot `827ad473-8314-4909-916d-9e15dc43f901`, `6.18.3-1-surface+`.
Recovery maintenance; no mainline N02 acceptance box closes.

**Problem:** the fitted Qualcomm UART controller lacked its installation address,
so BlueZ exposed no default controller. The installer service was disabled and
used a different address. Its replacement initially rejected a powered,
unconfigured controller; management power-off returned Invalid Index.

**Changed:** recovery-only guard identifies the fitted missing-address controller,
takes the device lock and temporarily blocks only its rfkill device. It verifies
block readback, repairs the private installation address, observes a configured
index, then restores and verifies the original soft-block setting in `finally`.
Configured controllers are left alone. Wi-Fi and global rfkill policy are untouched.
The address remains private in `/etc/spx-bluetooth/address`; the existing installer
unit uses a local override. Enumeration wait is bounded to 30 seconds.

**Observed:** at 23:12 CEST, UART module reload reproduced the real missing-address
state with Bluetooth unblocked. Service repair succeeded at 23:12:33 without a
manual radio block; the controller became primary with its retained address.
Bluetooth returned to `Powered: yes`, `PowerState: on`, `Discovering: no`; both
Bluetooth and Wi-Fi remained unblocked. Configured-controller no-op also passes.
Five offline tests include restoration after repair failure and Wi-Fi isolation;
installed unit verification passes. Both locks are free.

**Limits:** this is a module-reload test, not a fresh boot or peripheral test.
Setup emits repeated malformed MSFT vendor events; the preceding reload also
emitted hardware error 0x40. No fault-free lifecycle claim. Concurrent external
rfkill changes and an in-progress setup can still interrupt repair.
No paired peripheral fixture exists; pairing, data, reconnect and resume remain
unverified. Mainline keeps its private DTB address. No reboot, discovery, pairing,
sound, microphone/camera capture or battery tests were performed.
