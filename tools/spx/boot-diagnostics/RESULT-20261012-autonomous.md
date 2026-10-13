boxes closed: 3 of 47; newly closed: none.

# Autonomous hardware support continuation

Boot b9c406c9-df8d-4609-9aac-23682d85d911, kernel
7.3.0-rc2-spx-mainline-20261004bg+. Physical session declined; requirements
remain pending, not replaced by automation. No sound/capture/suspend/reboot.

Venus: removed corrupt generated outputs and rebuilt all three modules from
committed c2bd77008aae source in canonical work-build. Recovered missing modular
exports from original artifacts/Module.symvers via KBUILD_EXTRA_SYMBOLS; no
unresolved-symbol bypass. Installed SC8180X secure fields were zero, whereas
candidate contains existing vendor-derived values: distinct startup hypothesis.
Scoped per-Venus autoload barrier prevented installed-child ABI mixing.
Candidate core/decoder/encoder loaded; video32/33 registered; no earlier
workqueue/NULL host fault observed. FW version query still fails. One existing
120-frame H.264 fixture decode selected qcom-venus on /dev/video32 but
VIDIOC_REQBUFS timed out (-110,2.26s), zero frames. No repeat. All candidates
unloaded cleanly, temporary policy removed, installed modules unchanged.
Logs: /var/tmp/spx-venus-{decode,kernel}-20261012.log. D03 remains open.

Type-C: integrated scoped lane-mode WIP commit7b42b0190473. Both final objects
compile without diagnostics against canonical config. HPD-low precedes routing;
active-link guards affect only firmware-managed SC8180X. Port0 only, opt-in;
no PD/port1/initial-state/USB-only restoration claim. Binding is proposed local
ABI; full schema validation and hardware trial pending. No live deployment.

Cellular/CDSP researcher checks authoritative contracts, not guessed DT/data.
Sensor services active; no physical light/axes claims. All locks released.
No numeric hardware constants changed: existing vendor ranges/event mapping
retained. Next Venus hypothesis needs session response/IRQ evidence, not
another unchanged reload. User-visible hardware support remains incomplete.
