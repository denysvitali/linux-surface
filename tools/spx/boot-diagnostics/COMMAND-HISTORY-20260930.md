# Bounded SoundWire command-history candidate

AH passed at620.60s with the corrected AG topology and pin1, no selected native
errors, left2110/unique3 Attached/device1 and clean touch startup. AG pin2
attached right2110/unique4 with one CMD error using the same artifacts. This
supports observing command submission history before changing bus behavior.

The qcom.c candidate adds read-only, default-false `spx_cmd_diag`, gated to
microsoft,surface-pro-x. Record only existing AHB FIFO command-write/read
submissions while the existing AHB mutex is held, after the existing bridge
function returns. A spinlock protects16 ring records and coherent snapshots.
Each record retains sequence, post-submission software monotonic timestamp,
packed command, read/write direction and existing bridge return value.
Failed submissions remain visible, without changing caller return handling.

On the existing CMD-error IRQ, snapshot up to16 records before the existing
status read/recovery and print after the existing FIFO flush. Two snapshot
budgets/controller bound printed records+headers to34 lines. Empty snapshots
consume one budget and print nothing. Recording continues in bounded memory
after print budgets are spent. No additional bus read/write, delay, retry,
flush, routing change or completion wait. Firmware state, controller behavior
and asynchronous attribution remain unverified; enabling memory recording
and printk can alter timing. A record timestamp is not hardware completion.
The candidate only covers the WCD AHB submission path, not direct MMIO paths.

Validation: native `make -j4 drivers/soundwire/qcom.o` passed without warnings;
config unchanged. Actual C helper bodies were compiled with -Wall/-Wextra/
-Werror, pthread synchronization shim and address/undefined sanitizers. Tests
passed default-off, noncommand filtering, empty snapshot, ring overflow,
packed payload/direction/return capture, immutable snapshots,20000 concurrent
writer submissions with snapshots, and34-line output cap. Spinlock semantics
were represented by mutexes for userspace execution; this does not validate
hardware, kernel IRQ scheduling or realtime behavior.

Independent source review verifies original FIFO read/write functions, xfer
routing, bridge implementation and caller returns byte-for-byte; original
IRQ function is identical after removing instrumentation. Lock initialization
precedes any registered operations; history is written inside AHB lock, snapshots
release their spinlock before any bus operation or printk. Other source diff
chunks and configuration match the frozen AH pre-change snapshot. The isolated
patch checkpatch reports zero code errors/warnings; one metadata warning requests
a commit description for the uncommitted diff. The full preexisting driver has
12 style warnings, which are outside this change. Git diff --check passes.

DriverSHA25633aeace2b61741347c3015affa700c3ca875c6db719d1c19998252948253e83c.
AH post-result16-file manifest9cde5272760030b763db98a55715098a4c3aa1e330aafca67c1c61a8bae31b30
preserves old qcom.c/config/source.diff and actual result before changes.
The first harness build caught signed-comparison warnings in the new helper;
its parameters now use unsigned register/packed values, preserving bit patterns.
Both iterations are preserved in the private candidate archive.

This is an object-compiled offline candidate, not a bootable trial or hardware
result. Running AH remains exact original AE kernel/modules with AG corrected
DTB. No module reload, live reset/rebind, audio/PCM/capture/input-event read or
new boot selection occurred. The next required step is a distinct complete
kernel/module/private-initramfs build and archive; preserve corrected DTB and
pin2/native0/right matching/no-error judge for the diagnostic boot. Keep620s
collection/900s fallback, spx-known-good default and immediate boot-ID/pending
checks. Never re-arm AG blindly or treat diagnostic history as a strict pass.
EFI/early-kernel recovery remains unvalidated under the user's reboot authorization.
