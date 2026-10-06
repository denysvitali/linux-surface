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

**Verified:** four offline guard tests and installed unit verification pass.
UART module reload recreated the real missing-address condition, but management
enumeration took longer than the initial 15-second observation. The helper now
waits up to 30 seconds for enumeration and fails explicitly if it never appears.
The first repair was rejected while the unconfigured controller was powered;
ordinary management power-off also returned Invalid Index. After explicitly
blocking Bluetooth for the test, the installed service repaired the address,
returned success and preserved the blocked preference. Restored the original
unblocked, powered-on state; the configured-controller service path succeeds
without changing it. Both locks are free.

**Limits:** fresh-boot timing remains untested. The guard does not force a powered
unconfigured radio off; that case fails explicitly instead of changing its power
preference. Module reload emitted hardware error 0x40 and repeated malformed MSFT
events during setup; do not claim a fault-free reload or peripheral operation.

**Remaining:** no paired-device key records or usable peripheral fixture.
Pairing, reconnect, data and resume remain untested. Mainline retains its
private DTB address configuration; this recovery-only override does not alter it.
No reboot, discovery, pairing, sound or capture was performed.
