boxes closed: 3 of 47; newly closed: none

# Firmware HPD IRQ while idle: AUX PHY lifetime hypothesis (WIP)

Current baseline boot `5d70b0cc-739c-4d14-bf64-930cdec21e24`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`, last canonical result **26/49 functional**,
**44/52 inventory, 31 blocked, 0 fail/error**:
[report](/var/lib/spx-boot-diagnostics/boots/5d70b0cc-739c-4d14-bf64-930cdec21e24/hw-validation/report.json).
Verify passes. These boot-time scanout passes are not current display-on claims.

**New observation:** baseline logs five sink-count AUX/USC IRQ `-110` failures
at uptimes974.15,990.53,1006.92,1023.31,1039.69s, without a new connection event.
GNOME idle delay is900s. Current read-only DRM state has all CRTCs inactive,
both connectors disabled; Mutter PowerSaveMode=3, DP runtime_status=active.
The failures are historical, not continuously recurring now. No forced modeset,
PHY action, trace configuration, hotplug or private capture was performed.

**Source contract:** stream disable powers down and exits the external DP PHY.
External runtime resume deliberately restores the host only. The firmware IRQ
entry resumes the host then immediately performs AUX reads. `host_phy_init()`
explicitly supplies the AUX prerequisite; QMP initialization restores AUX after
power-off. The6.18 IRQ path instead skipped display-off state. Current runtime
active therefore does not establish usable AUX. This is evidence for an idle
timeout hypothesis, not proof of the original hotplug panic's cause.

**Change:** acquire the PHY temporarily around the forwarded IRQ when not
already initialized, and release only that acquired reference before runtime
put. Existing event/plugged locks exclude concurrent stream enable. Existing
references, return codes and firmware ACK behavior remain intact. Scoped debug
logging records temporary ownership, stream-power state and handler return.
The existing PHY-init helper's ignored initialization error remains a limitation.

**Checks / next trial:** a harness compiling the real IRQ function reproduced
AUX use with the PHY off before correction. Ten corrected ownership cases pass,
including active/off streams, handler errors, PM failure and early rejections.
Full incremental modules build/MODPOST and final MSM link pass; vermagic matches
the running release, checkpatch and diff checks pass. Build log:
`/var/tmp/spx-dp-aux-phy-modules-build.log`. Trial20261021ap will retain the
baseline sensor stack and wait for normal compositor idle and a natural firmware
IRQ. No forced blank/unblank, synthetic physical event or live MSM reload.
Default/automatic return and mandatory per-boot validation remain required.
