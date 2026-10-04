# AL touch lifecycle audit and reset-worker self-wait correction

AL failed initial probe, with14 bounded metadata records, no delivered touch IRQ,
three all-zero headers and no accepted reset/descriptor reports. Final IRQ227,
TLMM122, has zero interrupts on all eight CPUs; iptsd-state is empty. The protocol
validator counts three -22 failures despite status0/actual_length9 completions.
Do not conflate those completions with firmware availability. Initial probe
returns0 after arming polling, before HID publication. Its timeout neither fails
probe nor publishes a HID; the existing iptsd service retry cannot act in this
state. Late valid IRQs can still start enumeration. Extending diagnostic windows
or changing daemon retry count cannot create the missing initial response.

The frozen AL driver has a function named spi_hid_shutdown, but the spi_driver
registers only probe/remove. Actual device_shutdown -> SPI bus spi_shutdown
calls sdrv->shutdown only when registered; the helper's name is not a reboot
hook. Warm-retained firmware state remains a hypothesis. Adding a callback alone
would expose inherited teardown paths, so lifecycle hazards need review first.

A concrete existing self-wait appears on this path:
spi_hid_reset_work -> descriptor spi_hid_output fails -> spi_hid_error_handler
-> cancel_work_sync(&shid->reset_work). Once startup_active is false and the
startup/power/stopping guards permit recovery, the current worker waits for its
own completion. Local workqueue source cancels pending work and flushes the
executing worker through a barrier; current_work returns that work pointer.
AL never reached reset_work, so this is not evidence for its startup cause.

The only functional source delta uses cancel_work for the current reset worker
and retains cancel_work_sync for every other context. A pending requeued reset
invocation is still canceled; the current invocation can return. No reset, power,
IRQ, wire format, retry budget, descriptor bootstrap, shutdown hook, or audio
selector change is included. Existing reset/create/refresh cancellation cycles
outside this one self-wait remain unresolved. MAX_RESET_ATTEMPTS=3 is less than
SOFT_RETRY_ATTEMPTS=5, so the inherited full-reset branch is currently unreachable;
this change preserves both constants and their behavior.

Final candidate v2 compiled the native SPI-HID object without warnings.
An ASAN/UBSAN harness extracts both old/new actual error handlers and descriptor
workers:7200 handler cases and5760 worker cases passed, including pending versus
absent requeues, startup/stopping/power gates, ready state, attempt thresholds,
external contexts, descriptor failures and flush results.264 old self-waits are
detected with a stub trap; all other return/state/call traces match. Workqueue,
HID, output and electrical behavior are mocked; this is not exhaustive kernel
concurrency or a hardware startup test. The first v1 candidate and initial missing
round_up stub build failure remain preserved separately, not deployed.

Final source319237fe6601a5ba88a9d08edfe2065aaf69beac0637fcc0951e9acc377f8441;
full diff29a15c98d9d060bc394a9d6d84febebb9aa1e15e60f7ea176ea5b21ea8153478.
Config50118c6b... and every other tracked diff chunk remain unchanged.
14 candidate files manifest0e48f0a4a088b1d10e1e8d6258fa1c492983e65c4eebf077480f02ff1d064073
are frozen under AL/reset-self-wait-candidate-v2. This candidate is not installed
or hardware-tested. AL's original source/config and17 post-result records remain
frozen4d75cf9c..., and583 actual-return files c8716e72... verify known-good recovery.

Next port work: review the remaining worker cancellation graph before adding a
reboot quiesce path or initial-probe retry. A descriptor bootstrap additionally
needs transport reservation, IRQ deferral/draining and late reset/two-outstanding
reply handling; a mutex around writes is insufficient. Keep audio topology and
strict final readiness criteria. No further hardware experiment has been selected;
AL is not re-armed, known-good remains default and all recovery files are preserved.
