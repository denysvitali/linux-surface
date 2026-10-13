boxes closed: 3 of 47; newly closed: none.

# Kernel work identified from hardware inventory

Boot `298cf388-134f-4db3-a218-413f5af213d3`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. Read-only investigation; no driver
reload, configuration deployment, sleep, capture or reboot. Sources checked
against current TODO and earlier results, not the dated checklist status table.

## Kernel/DT work (not an instruction to change blocker order)

| Boxes | Evidence and specific work | Dependency / limit |
|---|---|---|
| D03 | Venus probe failed -110 on this boot. `drivers/media/platform/qcom/venus/core.c` has SC8180X secure VA ranges; `hfi_venus.c` has startup polling; `hfi.c` and packet/response paths have bounded Iris1 session IDs (commit c2bd77008aae). Test the matching candidate modules on a clean, coordinated boot with bounded real H.264 decode. | Earlier candidate compiled, but firmware execution was not tested because vcodec0 power domain stuck off. Do not re-run the known stuck-state trial or claim browser acceleration from codec nodes. |
| U02/U03/U04 | `drivers/platform/surface/surface_aggregator_usbc.c` handles port0 orientation/HPD only; no `typec_register_port`, no full roles/PD or second-port routing, and no initial-state query/replay. Board DT has only `usb-c-connector0`. Implement firmware-backed state discovery, Type-C/role/PD reporting, QMP lane-mode forwarding and evidence-backed second-port routing. Existing `qmp_combo_typec_mux_set()` supplies PHY C/E versus D/F handling; both board USB controllers currently force host mode. | Must establish actual firmware commands and physical wiring first; enabling TYPEC_DP_ALTMODE is not a substitute. Never unbind MSM or switch a live DP PHY merely to inventory it. |
| N03 | Live `/proc/config.gz`: QCOM_IPA and WWAN disabled. `sc8180x.dtsi` has IPA SMP2P signaling but no IPA device node; `drivers/net/ipa/ipa_main.c` has no SC8180X match or data table. Need supported IPA/GSI resource and endpoint definitions, bindings/DT and config (including RMNET), plus modem data control. | Do not alias another SoC or guess IOMMU/interrupt/endpoint values. Modem provisioning/online mode and SIM service remain separate blockers. Earlier modem evidence found placeholder rmtfs EFS backing; establish genuine same-device backing without donor calibration or reset. That is a plausible, not proven, cause of DeviceNotReady. WWAN=y alone is not a data path. |
| B07 | QCOM_FASTRPC=m, CDSP processor available, but live CDSP FastRPC node is explicitly disabled. `drivers/misc/fastrpc.c` and board DT carry guarded SPX transport WIP. | Previous untagged transaction caused watchdog. Address/tag/session contract and firmware process authorization must be resolved before enabling; missing node is intentional, not missing silicon. |
| C01/C02/F02 | Source `arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts` contains front sensor wiring/power sequence, but this boot's front DT node is disabled and no OV5693 subdevice is registered. Earlier successful front stream was on a different boot with live enablement. Persist proven sensor/graph changes on the canonical DTB and verify cold startup. | Do not repeat old timeout hypotheses; source already includes ordered sequencing/vendor binned mode work. Full image quality/resume and shared PHY supply ownership still need validation. Private libcamera packaging is userspace, not a kernel driver fix. |
| A03/P03/P02/F02 | Audio still uses retained DSP mappings, codec clock votes and userspace feeder. `slim_qcom_ngd_ctrl.spx_s2idle_retain=N` on this boot; sleep targets masked. Need verified native DSP teardown/resource lifetime or explicitly validated retention, and safe suspend recovery with audio present. | Reopen is already fixed. No new acoustic variants; do not unload card/Q6 stack, issue AFE STOP or unmask suspend on this baseline. Prepare existing guarded sleep path on an appropriate candidate. |
| P02/F02 | `clk_ignore_unused` and many diagnostic/force parameters remain on cmdline. | Remove/justify only after identifying dependent clocks/devices; do not strip them blindly or start deferred battery tests. |

## Not established as kernel defects

- S01: `CONFIG_TCS3430=m` and IIO device named `tcs3430` are present.
  `iio-sensor-proxy` and `spx-sensors` inactive. Desktop service integration
  and physical stimulus are pending; PMIC ADCs are not motion sensors.
- A02/A03: ALSA card/PCMs exist and PipeWire/WirePlumber run; missing desktop
  microphone source requires userspace routing/integration investigation,
  not an inference that DMIC silicon or kernel capture is absent.
- D01: blanked/off panel status alone is not a regression.
- I04/I06/I07: absent backlight/lid/accessory nodes need fitted accessory
  identification; do not invent unsupported capability requirements.
- U01/A04/N02: attached USB/dock/radio enumeration is not transfer, acoustic,
  pairing or lifecycle evidence. These need the physical fixtures/session.
- Hibernate prerequisites are missing; P04 needs applicability analysis,
  not automatic enabling. B01/F03 repeat counts and battery portions remain
  actual-test dependencies, not bugs inferred from missing counters.

## Evidence sources

Running configuration came from `/proc/config.gz`; the canonical build
`.config` was unreadable, so repository `.config` was not used as deployed
truth. Query-only kernel journal confirms Venus -110 on this boot. Current
DT metadata and cached V4L subdevice names confirm front disabled, rear/IR
present. Known-good findings and `../linux-surface-kernel` provide no working
SC8180X IPA, full PD controller or CDSP compute implementation to transplant.

## Next

Keep the current blocker order in TODO. The nearest existing kernel experiment
is D03's already-written session-ID fix, but it needs a clean boot and candidate
integration rather than another arbitrary patch. Camera baseline persistence
also needs a planned DTB trial. This inventory does not authorize silent
promotion of either candidate or close any acceptance box.
