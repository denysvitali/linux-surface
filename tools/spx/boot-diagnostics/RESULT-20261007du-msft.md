# DU live module fix: spurious MSFT warnings removed

**Problem/change:** QCA firmware reload sends vendor events shorter than the
retained MSFT prefix. msft_vendor_evt attempted prefix pull before matching and
logged44 malformed00 warnings during DU's first two cycles. dab469e5cbfa adds
one length guard: too-short events cannot match the prefix and return before
pull. Identified MSFT event parsing stays intact; no UART/baud/firmware change.

**Observed:** same boot `c6d85070-3bba-451b-b9c2-bc7c9138f12b`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. Rebuilt only bluetooth.ko incrementally,
exact release/link passed. Admitted idle/no saved peripheral, stopped BlueZ,
unloaded Bluetooth dependents/core without force, installed/reloaded modules
and restarted BlueZ. Original controller address/policy, named rfkill states
and same WLAN retained; no MSM/display change. Runtime reload complete.

**Functional:** changed-module native test two off/on cycles, owned5s scans
14/15 fresh peers, original policy/power/rfkill/address restored, clients reaped
and WLAN1MB passes.15.763s complete/no helper or cleanup error. After reload,
zero new malformed MSFT warnings, UART errors, trace records or fatal faults.
Live poweredtrue/discoveryfalse/original outer policy retained. No sound,
microphone/camera capture, sleep or battery test.

**Scope/next:** spurious MSFT classification warnings fixed on live hardware;
no peripheral pairing/reconnect/resume or advertisement-monitor validation.
DT's intermittent UART-84 did not reproduce before/after and remains unresolved.
N02a prior pass retained; no new box. Next candidate must include rebuilt core
in its initramfs for boot persistence; DU boot payload itself predates live fix.

**Evidence/recovery:** functional/20261007du/msft-module-reload.json,
bluetooth-power-msft/result.json, msft-result.json/msft-after-kernel.log and
msft-live.json preserve both stages separately. DU initial evidence remains.
Guarded known-good return/log collection next; actual recovery pending.
