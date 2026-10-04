# P independent live review — 2026-09-22

Independent read-only inspection passed at uptime **287.62–289.87 seconds**
on boot `35a3d9e0-4a7d-4246-a762-3f5c1e807bda`, release
`7.3.0-rc2-spx-mainline-20260922p+`. The completed 600-second result remains
pending. This inspection changed no device, timer or boot selection.

All 985 immutable build files and 202 installed module-tree files, including
187 modules, matched their manifests with exact coverage. Installed trial
payloads, recovery artifacts and runtime-policy files matched their pinned
hashes. Current tracked source diff and configuration matched P's archive.
The installed NGD and SPI-HID hashes and loaded GNU build-ID notes matched
P's independently reviewed artifacts; no L module was substituted.

Stage 7 step 6 and PIO were effective, with proactive capability retries zero.
All specified guards remained N, pinning Y/refcount 1, and child runtime
suspended with active time zero and control auto. ADSP, CDSP and modem were
running. No soundcard was registered, as expected for this stage. The delayed
audio loader's “sound card did not register” failure is expected here and is
not evidence of functional audio.

QMI acknowledged power at 22.265066 seconds. Initial reads were version
`0x202`, STATUS `0x40c`, CFG zero and RX_MSGQ zero. The CFG write/readback
was 1 and the logged INT_STAT was zero. The INT_CLR operand was an unlogged
separate read; INT_EN was written zero without readback. The source-derived
pre-thread sequence has eight reads and three writes.

The PIO thread started at 22.284733 seconds. A received MASTER_CAPABILITY
entered the worker at 22.287420; the first FIFO-write boundary was logged at
22.290099, with two words and first word `0xd9ff01c7`. All 15 heartbeats,
from 22.292682 through 50.263053 seconds, logged INT_STAT zero, STATUS
`0x240e` and CFG 1. The set LADDR bit supports enumeration. With verbose
logging disabled, the worker/write-boundary markers do not prove delivery
of every message or codec communication. No capability-DONE marker is
expected for step 6. Thread PID 842 remained present at inspection; Linux
NGD IRQ 236 had zero counts on all eight CPUs.

Touch was ready with two opens and one close, no startup diagnostic records,
and zero driver and SPI error counters. IPTSD PID 771 had no restart;
connection occurred at 22.279160 seconds, followed by virtual touchscreen
and stylus at 22.295256 and 22.295505. Physical gestures and intermittent
startup reliability remain unverified. Wi-Fi and graphical services were
active; FD680 rendering was logged at 113.741296. There was one modem startup,
no selected kernel/PIO fault signature and zero kernel taint.

The replacement fallback started at 108.821643 seconds, before the original
600-second timer stopped at 108.842007. The replacement remained active;
periodic evidence collection was active. Native continuation was acknowledged
at 109.03 seconds. Known-good remained the persistent default with no pending
GRUB or EFI selection. Root must preserve and verify the complete baseline
before stopping fallback or choosing a new experiment.

The checker is `/var/tmp/spx-review-p-live.py`, SHA-256
`e11be4c9eb54ccae47206b11fbd878e79595d9674580d19655910c8226d4bcec`.
Evidence is preserved under
`/var/lib/spx-boot-diagnostics/attempts/20260922p/independent-live-review/`,
separate from the immutable build. Its 13-file manifest has SHA-256
`43e0f36fc8f05417db0cd048b89ba1bb3b7236b8419f8b2d378a0950cc238ec5`;
report SHA-256 is
`5c7d3bbce56ec909696d03b927f3ae9be49652cd202de6fbed454e8db902ecdc`.
An initial checker run stopped before creating evidence because it used
incorrect bypass-node/port parameter names; the successful checker uses the
actual `spx_qmi_node` and `spx_qmi_port` names.
