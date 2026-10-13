boxes closed: 3 of 47; newly closed: none.

# Automatic validation and guidance rework

Boot `93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d`, kernel `7.3.0-rc2-spx-mainline-20261004bg+`;
no reboot, kernel/DT/module changes, sound or camera/microphone capture.
User requested ten agents; all ten completed bounded offline work.

**Changed:** `tools/spx/hw-validation` is the one automatic catalog/runner.
Retired the duplicate sibling Python suite to a forwarder; archived its dated
spec/reports with network identifiers redacted. The sibling desktop app remains
for voluntary human checks, not automatic completion. Guidance/playbooks use
generated `AUTO-HW-CHECKLIST.md`; historical 47 acceptance texts/ticks are intact.
Manual tests are excluded from the active checklist and never gate porting.

`spx-hw-validation.service` is installed and enabled for baseline, trial and
recovery boots. It records per-boot JSON/Markdown and runner status, regenerates
the active checklist, and defers a busy device lock. Trial install/promotion
keeps it enabled. Existing boot defaults/return policy are unchanged. Installation
and current-boot execution work; execution on the next actual boot is unverified.

**Observed:** 92 catalog rows: **10/40 functional passes**, 34/52 inventory
observations, 46 blocked, 2 failed, 0 errors. Real Wi-Fi scan completion, BT
five-second discovery (fresh reports, prior connections preserved), Wi-Fi gateway
echo, AC CPU/memory consistency, file fsync/checksum, Surface RTC time, light
channel reads and warning-priority kernel fault scan pass. Explicit Venus H264
decode returns30 output frames, zero decode errors, no software fallback.
Adreno680 Vulkan windowless static-color pixel readback passes; dynamic GMEM
scrolling corruption is still blocked/unresolved, not fixed by this pass.
The internal panel is idle/disabled, external display disconnected, and GL/GLES
render/vulkaninfo tools unavailable; those tests were not passed or forced on.

**Real gaps:** failed sensor backend and two failed system units (sensor service
and native speaker feeder); desktop audio inactive. Front camera not in this
boot's graph. IPA/WWAN/RMNET cellular support/provisioning missing. Cameras need
capture opt-in, external USB/dock paths need fixtures. Parked encoder, DSP audio
lifecycle, battery/load/sleep/recovery paths remain blocked, not silently omitted.
No complete audio/cellular/GPU/video support is claimed.

Evidence: `/var/lib/spx-boot-diagnostics/boots/93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d/hw-validation/`
(`report.json`, `report.md`, `checklist.md`, `runner.json`, `runner.md`). Summary:
[`AUTO-HW-CHECKLIST.md`](../../../AUTO-HW-CHECKLIST.md).
Fixture tests, race tests, Go vet/build and12 boot-wrapper fixture tests pass.
Checker fixes: portable journal `-k`, warning-priority bounded scan, own failed
unit excluded, user-session environment, public GPU fixture readable under
private service umask. Missing prerequisites are blocked, not hardware absent.

**Assumptions/bounds:** safe scans/short offscreen checks and disposable-file I/O
are authorized by this request; specific capture/sound/encoder/battery limits
remain. No hardware tuning constants changed. Test bounds: CPU<=1s/8MiB,
storage4MiB+4MiB reserve, BT5s, decode<=2s/30frames, camera opt-in3frames,
Vulkan64x64, sensor read3s, lock retry60s; detailed budgets are in the README.
**Next:** diagnose the failed SDSP sensor service before kernel changes; preserve
speaker parked mappings. Future boots must each record their own validation.
