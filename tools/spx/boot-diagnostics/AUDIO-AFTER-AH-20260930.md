# After AH: observe existing command submissions on the failing right path

AH passed without selected errors using the exact corrected AG topology.
AG and AF both reported pin2 CMD errors. Do not enable both pins, change native
address assignment, relax error checks or infer command failures from FIFO low
bytes. PCM and acoustics remain outside this authorized silent boot scope.

The next source change is default-off bounded command-history instrumentation.
Record existing WCD AHB FIFO read/write-command submissions from software
arguments and their existing bridge return values, in a per-controller ring.
Print the most recent16 records for at most two existing CMD-error interrupts
per controller. Snapshot before existing recovery, but print after its existing
FIFO flush so printing does not delay that flush. No additional register access,
write, retry, delay, polling, completion wait or command routing change. Keep
the existing caller return behavior, including ignored submission return values.
The read-only selector is specific to the Surface Pro X; default false.

Use a spinlock for writer/snapshot concurrency. Record while the existing AHB
mutex still serializes submission, release diagnostic lock before printk, and
initialize both locks before child/register operations. Sequence is software
submission order; stored request fields and return codes do not establish
actual queue occupancy, wire acknowledgment or causal error attribution.
Two dumps of16 records plus headers bound logs to34 lines/controller; memory
recording can still perturb timing. A separate kernel release/build/module/
initramfs archive is required before any boot that enables this diagnostic.

First implement/review/compile offline. Any future fresh boot must preserve
AG corrected DTB, pin2/native0/no worker and strict right-specific matching/
no-error criteria, baseline and touchbounds8/48/384. Collector620/fallback900,
known-good default, one selection with immediate boot-ID/pending checks and
native continuation. A diagnostic dump is evidence, not a scoped pass. No live
module reload/reset/rebind or audio/input activity is included.
