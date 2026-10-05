# USB-C firmware contract recovered; event correction is WIP

Recovery boot `1bdff3c9-f785-4613-bf23-4d137850bbb1`, kernel
`6.18.3-1-surface+`. User cannot provide physical tests; continue autonomously.
Battery tests remain deferred. No capture or playback in this phase.

**Evidence:** retained `SurfaceUsbCMuxAcpiFilterDriver.sys` converter RVA0x3c588
consumes USC bytes0–3 sequence,4 port,5 CC,6 mux,7 high-speed,8 DP pin,
9 HPD level,10 HPD IRQ. The converter log reference is RVA0x3ca2c.
Qualcomm `qcusbcucsi8180.sys` RVAs0x6f68–0x6fd8 validate mux2 pins3/5/9/11
and mux3 pins2/4/8/10. Pins7–12 are reversed versions of1–6; historical
“link4” means assignment D, not four lanes. No current-state GET was found.

Qualcomm maps primary0x088e8000 at RVA0xd8c8 and secondary0x088ed000 at
0xda8c. Port0 and port1 write `(old & ~BIT(0)) | CC | BIT(1)` at offset0x10
(RVAs0x66fc–0x670c and0x6870–0x6880). Linux QMP TYPEC_CTRL uses that same
register: CC0 NORMAL, CC1 REVERSE, CC2 detached. This supersedes the earlier
claim that no grounded orientation mapping was available.

**Changed:** commit6b717a0bf359 decodes all event fields, validates DP mode/pins,
forwards DP-only level events and detach after subscriber reload, and leaves
HPD IRQ unhandled instead of falsely acknowledging it. Incremental W=1 Surface
module build passes with fixed7.3 release. Not installed or hardware-tested.
Mode2 needs PHY lane selection; a software correction closes no acceptance box.

**Trial prepared:** afb4e980aada adds opt-in primary Type-C switch graph and
CC polarity before HPD, rejecting changed polarity while DP is connected.
Modules and DTB compile;31 existing trial-helper tests pass. CG is installed
with `phy_orientation=1`, the attached dock, known-good default and900s return.
Preparation initially caught a stale one-entry modules.order; a full incremental
modules build regenerated it and clean depmod passed. No hardware pass yet.

**Next:** boot CG once; collect decoded USC fields, Type-C callback log, EDID
and fresh scanout without human input. MSM's existing HPD
callback distinguishes IRQ from a native hardware pulse counter; it has no
external explicit IRQ API. Never synthesize replug to mimic an IRQ. Visible
output, flipped plugs, other-port coverage and U02–U04 remain unverified.
