# Recovery Bluetooth restored; startup guard installed

Boot `827ad473-8314-4909-916d-9e15dc43f901`, `6.18.3-1-surface+`.
Recovery maintenance; no mainline N02 acceptance box closes.

**Problem:** HCI0 existed but management reported an unconfigured Qualcomm UART
controller missing its public address. BlueZ exposed no default controller.
The installer address service was disabled and contained a different address
from the retained working mainline installation.

**Changed:** restored the documented installation address through management;
after the asynchronous index transition, HCI0 became a primary controller.
Unblocked the radio and verified BlueZ `Powered: yes`, `PowerState: on`.
`7b952d003cad` adds a guarded helper and an override for the existing address
service. It runs only on known-good Surface Pro X recovery boots and only when
the fitted UART controller reports the missing-public-address option. Configured
controllers are preserved. The private address is stored outside git in
`/etc/spx-bluetooth/address`. The guard never writes radio power or rfkill state.

**Verified:** three offline guard tests pass; installed unit verification passes.
Enabled/startup unit returns success on the current configured controller,
performing no address/power changes. Radio stays powered on. Automatic repair
of an unconfigured controller on a fresh recovery boot remains unverified;
the actual management-address repair was exercised manually on this boot.

**Remaining:** no paired-device key records or usable peripheral fixture.
Pairing, reconnect, data and resume remain untested. Mainline retains its
private DTB address configuration; this recovery-only override does not alter it.
No reboot, discovery, pairing, sound or capture was performed.
