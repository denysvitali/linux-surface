# BI: dock hotplug forwarding and touch startup availability

Historical preparation below; BI has since booted. See [live result](RESULT-20261004bi.md).

Installed, **not selected or booted**. Recovery remains boot
`f309dbfa-4e99-4bdd-9059-efc12f21b817`, `6.18.3-1-surface+`.
The candidate keeps release `7.3.0-rc2-spx-mainline-20261004bg+` and build
directory `/var/tmp/spx-mainline-trial-20261004bg/work-build`.

Commit `4262fecc320c` adds a manually loaded Surface USC-to-DP0 module and
publishes the MSM bridge's OF node for public DRM lookup. This ports the 6.18
event/ACK protocol without private MSM structure casts or kprobes. Device links
and an ordered workqueue manage provider lifetime and event delivery. Only EC
port 0 is forwarded; orientation switching, initial-state discovery, the second
port and suspend remain unvalidated. Existing evidence never proved visible
monitor pixels. Never unload or rebind MSM.

Separately, one targeted udev add event restored recovery IPTSD after failed
startup left no service instance. Commit `8d3640afc444` adds an exact SPI HID
`045E:0C21` rule requesting IPTSD independently of the packaged identification
helper. The installed three-start/120-second retry policy remains unchanged.
The rule passes `udevadm verify` and is installed/reloaded; automatic recovery
on a new add event is untested. See [recovery observations](PHYSICAL-FOLLOWUP-20261004.md).

Incremental Image/modules build, module linking, depmod, initramfs generation
and boot-entry syntax checks passed. Initramfs has the same two warnings as BH:
inapplicable aarch64 microcode hook and absent privacy-screen module. The known-good
payloads/default were checked, pending selection is empty, and the reusable
900-second return and functional-check timers are enabled for BI. The collected
BH boot directory was removed; its logs remain and BI uses the shared module
release. State/build logs are under
`/var/lib/spx-boot-diagnostics/functional/20261004bi/`.

Next: with the user available, select BI once through `tools/spx/trial.py boot
20261004bi`. After desktop startup, load `surface_aggregator_usbc`, ask for a dock
replug, and require visible output alongside USC/DRM/EDID observations. Batch
finger/pen event counts and Bluetooth peripheral use on the same identified boot.
Unload only the experimental USC module before any separately prepared sleep
test. A userspace return timer cannot wake a suspended device; no RTC alarm exists.
No sound or camera/microphone capture is scheduled. No acceptance box closes.
