# Next bounded PIO question after P

P established that the stage-7 step-6 PIO thread saw a master capability and
reached the first reactive FIFO write. It did not log TX_MSG_SENT or
`reconf` completion. The smallest existing selector change that answers this
question is `spx_stage7_step=7` with `spx_pio_cap_retries=0`, while retaining
P's exact kernel, modules, DTB, initramfs and all other guards. Give that
one-shot attempt a new ID; never re-arm P. Step 7 enables the existing
five-second capability waiter. It does not register the controller or soundcard.

The waiter completes if the reactive worker succeeds and signals `reconf`.
Otherwise it logs a timeout and the final STATUS/INT_STAT. The helper then
returns to the stage-7 guard; its outer probe can still report success, so
classify the capability result from the specific done or timeout marker, not
from `enable done`. With retries zero, no proactive REPORT_SATELLITE is queued
by the waiter. A received MASTER_CAPABILITY can still start the reactive
worker, including its bounded NACK retries. A wait success would support a
completed reactive exchange, but would not establish codec traffic or audio.

Before selecting that boot, preserve and hash-check P's recovered result and
the recovery files, independently review the exact ordered command line and
artifact reuse, and build a finalizer that runs automatically by the
600-second deadline. P's live finalizer was only a draft and was missed; the
20-minute fallback then returned the machine. Verify the finalizer and
fallback ordering before queuing the new one-shot entry. Keep persistent
`spx-known-good`, recheck boot ID and pending selection immediately before
reboot, and collect the actual result before choosing another experiment.
Do not change module parameters or rebind devices in the live session.

This step still has the documented PIO thread and QMI lifecycle risks,
including no timeout for a stalled MMIO access and incomplete SSR cleanup.
The user already authorized experimental boots that may require a manual
power cycle; this plan does not claim automatic early-hang recovery.
