# USB-C Alt Mode: physical test selected, no new hardware pass

Recovery remains boot `1bdff3c9-f785-4613-bf23-4d137850bbb1`, kernel
`6.18.3-1-surface+`. Battery tests remain deferred. No reboot or module change.

**Observed:** the currently attached Lenovo40B0 dock's Billboard descriptor
reports DP Alt Mode configuration successful (SVID0xff01), with USB4 and
Thunderbolt not attempted. Its USB2/USB3 hubs, receiver, audio and Ethernet
enumerate; this is not a USB payload-transfer or visible-display pass. Recovery
has no external DP connector. CA previously proved mainline external scanout
and subscriber restart on this dock, not physical output or replug.

**Contract:** saved SQ2 UPAN accepts software VCCS/VMUX/DP-assignment inputs;
UCS0 is a software-filled notification mailbox. Neither establishes a USC
state GET or connects USC orientation/link bytes to QMP orientation/lane modes.
CA only observed port0/orientation0/link4. Do not guess a PHY mapping or replay
command, or repeat its unchanged subscriber-reload test.

**Next functional test:** obtain physical readiness, then boot the fixed
mainline candidate with the collected CF DTB and existing `--usbc` startup.
Confirm actual monitor output, unplug/replug only the dock cable on its current
port, then test a flipped connector and the other port if the user is available.
Record real USC events, EDID/DRM state, fresh vblank, USB reconnect and the user's
visible-output report for each action. This is display/dock testing; do not add
battery observations or charger tests. Never unbind/reload MSM components.

Physical readiness was requested; no response has been received yet. U02–U04
remain open. The all-hardware goal remains active; no completion is claimed.
