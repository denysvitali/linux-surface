boxes closed: 3 of 47; newly closed: none.

Offline WIP only. /var/tmp/spx-typec-final.patch is the complete scoped candidate
against the four current main working files, not Git HEAD. Only the copied
bridge in /var/tmp/spx-typec-scoped was changed in this pass. No repository,
Git, build, installed module, device, reboot or acceptance changes.

Disconnect ordering fix:
- Classify the validated port-zero event before touching PHY routing.
- For DP HPD-low, do not call orientation or lane setters. Thus a changed CC
  polarity or lane class cannot return EBUSY and suppress disconnect.
- For detach (mux0/cc2), deliver HPD-low first, then send orientation NONE only
  after successful notification. QMP's NONE is a hardware no-op. Lane mode is
  retained; no USB-only reset or speculative power-down wait was added.
- HPD-high still applies orientation and lane class before connection/IRQ;
  scoped QMP guards reject a real change until dp_powered_on is false, even
  after the bridge's connected flag becomes false. HPD notification can start
  asynchronous teardown; connected=false is NOT proof of PHY power-down.
- ACK rules are unchanged: successful non-IRQ HPD sets handled=1; IRQ sets it
  only after successful sink handling; low IRQ stays unhandled; route failure,
  unavailable HPD and unsupported ports still receive sequenced handled=0 ACK.
  Post-notification detach bookkeeping failure does not undo delivered HPD.

Binding tradeoff (retained, not endorsed as upstream-ready):
The stable ownership fact that a board's embedded firmware manages its Type-C
connector and emits routing events is defensible firmware/platform description
in DT. This is stronger than an arbitrary 'enable safe driver' switch. But the
current property description explicitly dictates EBUSY, callback no-ops and
retry behavior, and says 'without a kernel Type-C/PD controller': those describe
Linux policy/implementation rather than immutable hardware. It also controls
provider registration timing, an internal lifetime concern shared by other
possible consumers. The property is scoped to SC8180X and set on the primary
SPX PHY only, preserving unrelated callbacks, but scoping alone does not justify
an ABI. Recommend binding discussion before integration: describe actual
firmware ownership/topology, not errno or missing kernel support; model the
firmware controller/provider connection when its authoritative contract exists.
Do not infer a controller protocol, initial-state query, second-port mapping,
or future PD support from this boolean. Universal QMP locking/lifetime fixes
would need separate justification and validation, not a new policy property.

Assumptions/constants: existing mux2/3 validation, C/D lane-class mapping,
port-zero routing, QMP NONE semantics and ACK contract retained; no constants
changed. No queued retry or USB-only restoration added: the next HPD-high event
can attempt the route, and EBUSY still leaves it unhandled if DP is not off.
Source checks confirm HPD-low bypasses setters, detach follows HPD, and both
handled=1 sites remain. Not compiled or tested on hardware; physical disconnect,
replug, routing and DP-only output remain unverified.
