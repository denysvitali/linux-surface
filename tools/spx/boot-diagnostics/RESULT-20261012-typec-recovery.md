boxes closed: 3 of 47; newly closed: none.

# Recovered Type-C patch: not ready to integrate

Surviving three-file diff preserved in /var/tmp/spx-typec-recovered.patch.
No damaged Git objects removed or repaired. Main sensor commit is intact.

Recovered QMP guards are unconditional, despite bridge lane-mode being opt-in:
they alter all supported QMP combo callers. Do not integrate as default-off.
A safe revision needs explicit per-PHY scoping and binding documentation or
independent justification/tests for generic behavior changes. Mode-switch DT
also advertises the provider regardless of bridge parameter. Mux acquisition
should follow successful switch acquisition; normalize error pointers for clear
cleanup. Existing typec_mux_put already handles error pointers, so this is NOT
an established ERR_PTR dereference bug.

Firmware supports lane-class evidence only; no PD/initial-state/port1 contract.
Disconnect cannot blindly restore USB mode before DP power-down. Current live
display remains untouched. Patch is unbuilt/unvalidated and not deployed.

Venus reload ended with workqueue warning/NULL dereference in v4l_id; no retry.
Need offline auto-probe/deferred work lifetime analysis and complete fault
trace before next hardware experiment. No requested reboot or capture.
